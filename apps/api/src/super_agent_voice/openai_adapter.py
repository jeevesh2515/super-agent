"""OpenAI Realtime adapter behind the streaming seam.

The backend holds the key and the provider socket; the browser never sees
either. `websockets` is imported only when a real session starts, and tests
inject `connect`. No tools, reconnect, or session resumption in this slice.
Protocol checked against developers.openai.com/api/docs/guides/realtime-conversations
on 2026-11-16.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from array import array
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import quote

from .adapter import (
    AdapterError, AdapterEvent, AudioChunk, Interrupted, Thinking, Transcript, TurnComplete,
)

INPUT_RATE_HZ = 16000  # what the console captures
OUTPUT_RATE_HZ = 24000  # the only PCM rate the Realtime API accepts or returns
MAX_INPUT_FRAMES = 64
MAX_TRANSCRIPT_CHARS = 2000
MAX_CHUNK_BYTES = 16 * 1024  # under the bridge's 32 KiB frame limit
SYSTEM_INSTRUCTION = (
    "You are a concise voice assistant. Keep answers short. You cannot take any action "
    "or look anything up, and you must never say you did."
)
# The server answers a cancel or clear that raced with its own turn handling with
# one of these; the session is unaffected.
BENIGN_ERRORS = frozenset({"response_cancel_not_active", "input_audio_buffer_commit_empty"})

Connect = Callable[[], Any]  # returns an async context manager yielding a socket


def classify(error: BaseException) -> str:
    """Reduce any provider failure to a fixed category; never forwards detail."""
    if isinstance(error, AdapterError):
        return error.category
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 429:
        return "provider-limits"
    if status in (400, 404):
        return "provider-unsupported"
    if type(error).__name__.startswith("ConnectionClosed"):
        return "provider-session-ended"
    # A rejected handshake (bad key, outage) or a network failure.
    if status is not None or isinstance(error, (OSError, TimeoutError)):
        return "provider-unavailable"
    return "session-failed"


def to_24k(pcm: bytes) -> bytes:
    """Resample 16 kHz mono PCM16 to 24 kHz by linear interpolation.

    shortcut: each frame is resampled alone, so the last sample of a frame is
    held instead of blended into the next; carry one sample over if that is audible.
    """
    source = array("h", pcm)  # native order; every supported host is little-endian
    out = array("h", bytes(len(source) * 3 // 2 * 2))
    last = len(source) - 1
    for index in range(len(out)):
        position, step = divmod(index * 2, 3)
        left = source[position]
        right = source[position + 1] if position < last else left
        out[index] = left + (right - left) * step // 3
    return out.tobytes()


def _session(model: str) -> dict[str, Any]:
    pcm = {"type": "audio/pcm", "rate": OUTPUT_RATE_HZ}
    return {"type": "session.update", "session": {
        "type": "realtime",
        "model": model,
        "output_modalities": ["audio"],
        "instructions": SYSTEM_INSTRUCTION,
        "audio": {
            "input": {
                "format": pcm,
                "turn_detection": {"type": "semantic_vad"},
                "transcription": {"model": "gpt-4o-mini-transcribe"},
            },
            "output": {"format": pcm, "voice": "marin"},
        },
    }}


def _socket_connect(api_key: str, model: str) -> Connect:
    def connect() -> Any:
        from websockets.asyncio.client import connect as open_socket  # only for a real session

        return open_socket(
            f"wss://api.openai.com/v1/realtime?model={quote(model, safe='')}",
            additional_headers={"Authorization": f"Bearer {api_key}"},
        )

    return connect


class OpenAIRealtimeAdapter:
    name = "openai-realtime"
    output_rate_hz = OUTPUT_RATE_HZ

    def __init__(self, model: str, api_key: str = "", *, connect: Connect | None = None) -> None:
        if connect is None and not api_key:
            raise AdapterError("provider-unavailable")
        self._model = model
        self._connect = connect or _socket_connect(api_key, model)
        self._input: asyncio.Queue[bytes] = asyncio.Queue(MAX_INPUT_FRAMES)
        self._events: asyncio.Queue[
            tuple[int, AudioChunk] | Thinking | Transcript | TurnComplete | Interrupted
            | AdapterError | None
        ] = asyncio.Queue()
        self._audio_epoch = 0
        self._stack = contextlib.AsyncExitStack()
        self._socket: Any = None
        self._tasks: list[asyncio.Task[None]] = []
        self._response: str | None = None  # the response being generated, if any
        self._dropped: str | None = None  # an interrupted response; its late audio is stale
        self._spoke = False  # audio went out since the user last started speaking
        self._release: asyncio.Task[None] | None = None
        self.closed = False

    async def start(self) -> None:
        if self.closed:  # a late start would open a session nothing closes
            raise AdapterError("session-failed")
        try:
            self._socket = await self._stack.enter_async_context(self._connect())
            await self._send(_session(self._model))
            # Fail closed: no microphone audio flows until the provider has
            # accepted this exact configuration.
            while (kind := self._parse(await self._socket.recv()).get("type")) != "session.updated":
                if kind == "error":
                    raise AdapterError("provider-unsupported")
        except Exception as error:
            with contextlib.suppress(Exception):
                await self._stack.aclose()
            raise AdapterError(classify(error)) from None
        if self.closed:  # closed while connecting: that close saw nothing to release
            with contextlib.suppress(Exception):
                await self._stack.aclose()
            raise AdapterError("session-failed")
        self._tasks = [
            asyncio.create_task(self._send_loop()),
            asyncio.create_task(self._receive_loop()),
        ]

    async def enqueue_audio(self, audio: bytes) -> None:
        if self.closed:
            raise AdapterError("session-failed")
        # Stale audio is worse than a gap, so a full queue drops the oldest.
        if self._input.full():
            self._input.get_nowait()
        self._input.put_nowait(audio)

    async def end_audio_stream(self) -> None:
        # Muted mid-sentence: the half-heard utterance must not become a turn.
        await self._control({"type": "input_audio_buffer.clear"})

    async def interrupt(self) -> None:
        if self.closed:
            return
        # Even a completed response may have PCM waiting for the event consumer.
        self._audio_epoch += 1
        self._spoke = False
        if self._response is not None:
            self._dropped = self._response
            await self._control({"type": "response.cancel"})

    async def events(self) -> AsyncIterator[AdapterEvent]:
        while True:
            item = await self._events.get()
            if item is None:
                return
            if isinstance(item, AdapterError):
                raise item
            if isinstance(item, tuple):
                epoch, chunk = item
                if epoch == self._audio_epoch:
                    yield chunk
                continue
            yield item

    async def close(self) -> None:
        self.closed = True
        # The app cancels a slow close, retries once, and reads a clean return
        # as confirmed closure. Shielding one shared release makes that true.
        if self._release is None:
            self._release = asyncio.create_task(self._release_session())
        await asyncio.shield(self._release)

    async def _release_session(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await self._stack.aclose()
        except Exception:
            # The bridge may release its session slot only after a clean close.
            raise AdapterError("session-failed") from None
        finally:
            self._events.put_nowait(None)

    def _fail(self, category: str) -> None:
        if not self.closed:
            self._events.put_nowait(AdapterError(category))

    async def _send(self, event: dict[str, Any]) -> None:
        await self._socket.send(json.dumps(event))

    async def _control(self, event: dict[str, Any]) -> None:
        if self.closed or not self._tasks:
            return
        try:
            await self._send(event)
        except Exception as error:
            self._fail(classify(error))

    @staticmethod
    def _parse(message: Any) -> dict[str, Any]:
        event = json.loads(message) if isinstance(message, str) else None
        return event if isinstance(event, dict) else {}

    async def _send_loop(self) -> None:
        try:
            while True:
                frame = await self._input.get()
                await self._send({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(to_24k(frame)).decode("ascii"),
                })
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail(classify(error))

    async def _receive_loop(self) -> None:
        try:
            while True:
                self._map(self._parse(await self._socket.recv()))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail(classify(error))

    def _say(self, role: str, text: Any) -> None:
        if isinstance(text, str) and text.strip():
            self._events.put_nowait(Transcript(role, text.strip()[:MAX_TRANSCRIPT_CHARS]))

    def _map(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if kind == "response.created":
            self._response = response.get("id")
            self._events.put_nowait(Thinking())
        elif kind == "response.output_audio.delta":
            if event.get("response_id") == self._dropped or not isinstance(event.get("delta"), str):
                return
            data = base64.b64decode(event["delta"], validate=True)
            data = data[: len(data) & ~1]  # whole PCM16 samples only
            self._spoke = self._spoke or bool(data)
            for start in range(0, len(data), MAX_CHUNK_BYTES):
                chunk = AudioChunk(data[start:start + MAX_CHUNK_BYTES], OUTPUT_RATE_HZ)
                self._events.put_nowait((self._audio_epoch, chunk))
        elif kind == "input_audio_buffer.speech_started":
            # Barge-in. The model writes audio faster than it plays, so a reply
            # can still be playing after its response finished; the provider
            # cancels a response that is still running on its own.
            if self._response is not None:
                self._dropped = self._response
            if self._spoke:
                self._spoke = False
                self._audio_epoch += 1
                self._events.put_nowait(Interrupted())
        elif kind == "conversation.item.input_audio_transcription.completed":
            self._say("user", event.get("transcript"))
        elif kind == "response.output_audio_transcript.done":
            if event.get("response_id") != self._dropped:
                self._say("assistant", event.get("transcript"))
        elif kind == "response.done":
            if response.get("id") == self._response:
                self._response = None
            status = response.get("status")
            if status in ("completed", "incomplete"):
                self._events.put_nowait(TurnComplete())
            elif status == "failed":
                error = (response.get("status_details") or {}).get("error") or {}
                limited = error.get("code") in ("rate_limit_exceeded", "insufficient_quota")
                self._fail("provider-limits" if limited else "session-failed")
            # cancelled: the interrupt that caused it was already reported.
        elif kind == "error":
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            if error.get("code") not in BENIGN_ERRORS:
                self._fail("session-failed")
