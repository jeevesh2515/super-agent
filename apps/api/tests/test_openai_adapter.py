"""Offline tests for the OpenAI Realtime adapter. No network, real key, or audio."""
from __future__ import annotations

import asyncio
import base64
import json
from array import array
from types import SimpleNamespace as NS

import pytest

from super_agent_voice.adapter import (
    AdapterError, AudioChunk, Interrupted, Thinking, Transcript, TurnComplete,
)
from super_agent_voice.app import _adapter_from_environment
from super_agent_voice.config import VoiceConfig
from super_agent_voice.openai_adapter import OpenAIRealtimeAdapter, classify, to_24k

PCM = b"\x01\x00" * 480


class ConnectionClosedOK(Exception):
    """Named like the websockets exception; the adapter matches on the name."""


class FakeSocket:
    def __init__(self, *events: dict | Exception) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.closed = False
        self.push({"type": "session.created"}, {"type": "session.updated"}, *events)

    def push(self, *events: dict | Exception) -> None:
        for event in events:
            self.inbox.put_nowait(event)

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        event = await self.inbox.get()
        if isinstance(event, Exception):
            raise event
        return json.dumps(event)

    def kinds(self) -> list[str]:
        return [event["type"] for event in self.sent]


def connect(socket: FakeSocket, error: Exception | None = None):
    class Context:
        async def __aenter__(self):
            if error:
                raise error
            return socket

        async def __aexit__(self, *exc):
            socket.closed = True

    return Context


def delta(response_id: str, data: bytes = PCM) -> dict:
    return {"type": "response.output_audio.delta", "response_id": response_id,
            "delta": base64.b64encode(data).decode()}


def created(response_id: str) -> dict:
    return {"type": "response.created", "response": {"id": response_id}}


def done(response_id: str, status: str = "completed", **details) -> dict:
    return {"type": "response.done",
            "response": {"id": response_id, "status": status, "status_details": details}}


async def started(*events: dict | Exception) -> tuple[OpenAIRealtimeAdapter, FakeSocket]:
    socket = FakeSocket(*events)
    adapter = OpenAIRealtimeAdapter("test-model", connect=connect(socket))
    await adapter.start()
    return adapter, socket


async def take(adapter: OpenAIRealtimeAdapter, count: int) -> list:
    stream = adapter.events()
    return [await asyncio.wait_for(anext(stream), 1) for _ in range(count)]


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_resampling_keeps_level_and_makes_three_samples_from_two() -> None:
    assert to_24k(b"") == b""
    assert to_24k(array("h", [1000] * 320).tobytes()) == array("h", [1000] * 480).tobytes()
    assert list(array("h", to_24k(array("h", [0, 300]).tobytes()))) == [0, 200, 300]
    assert list(array("h", to_24k(array("h", [-32768, 32767, -32768]).tobytes()))) == [
        -32768, 10922, 10922, -32768,
    ]


def test_start_configures_24k_audio_and_waits_for_the_provider_to_accept_it() -> None:
    async def run() -> None:
        adapter, socket = await started()
        session = socket.sent[0]["session"]
        assert socket.kinds() == ["session.update"] and session["model"] == "test-model"
        assert session["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
        assert session["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
        assert session["output_modalities"] == ["audio"] and "tools" not in session
        await adapter.close()
        assert socket.closed

    asyncio.run(run())


def test_start_fails_closed_when_the_provider_rejects_the_configuration() -> None:
    async def run() -> None:
        socket = FakeSocket()
        socket.inbox = asyncio.Queue()
        socket.push({"type": "session.created"}, {"type": "error", "error": {"code": "invalid_value"}})
        adapter = OpenAIRealtimeAdapter("test-model", connect=connect(socket))
        with pytest.raises(AdapterError, match="provider-unsupported"):
            await adapter.start()
        assert socket.closed  # nothing is left open after a refused start

    asyncio.run(run())


@pytest.mark.parametrize(("error", "category"), [
    (NS(response=NS(status_code=401)), "provider-unavailable"),
    (NS(response=NS(status_code=429)), "provider-limits"),
    (NS(response=NS(status_code=404)), "provider-unsupported"),
    (OSError("secret detail"), "provider-unavailable"),
    (ConnectionClosedOK(), "provider-session-ended"),
    (ValueError("secret detail"), "session-failed"),
])
def test_failures_reduce_to_fixed_categories(error, category) -> None:
    assert classify(error) == category


def test_connect_failure_carries_a_category_and_no_detail() -> None:
    async def run() -> None:
        adapter = OpenAIRealtimeAdapter(
            "test-model", connect=connect(FakeSocket(), OSError("secret detail")),
        )
        with pytest.raises(AdapterError) as caught:
            await adapter.start()
        assert str(caught.value) == "provider-unavailable"

    asyncio.run(run())


def test_a_key_is_required_and_never_stored_on_the_adapter() -> None:
    with pytest.raises(AdapterError, match="provider-unavailable"):
        OpenAIRealtimeAdapter("test-model")
    assert "sk-test" not in repr(vars(OpenAIRealtimeAdapter("test-model", "sk-test")))


def test_microphone_audio_is_resampled_and_appended() -> None:
    async def run() -> None:
        adapter, socket = await started()
        await adapter.enqueue_audio(b"\x02\x00" * 320)
        await settle()
        sent = socket.sent[-1]
        assert sent["type"] == "input_audio_buffer.append"
        assert base64.b64decode(sent["audio"]) == b"\x02\x00" * 480
        await adapter.close()
        with pytest.raises(AdapterError):
            await adapter.enqueue_audio(PCM)

    asyncio.run(run())


def test_a_full_reply_maps_to_thinking_audio_transcripts_and_turn_complete() -> None:
    async def run() -> None:
        adapter, _ = await started(
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": " hi "},
            created("r1"), delta("r1"),
            {"type": "response.output_audio_transcript.done", "response_id": "r1", "transcript": "Hello."},
            done("r1"),
        )
        assert await take(adapter, 5) == [
            Transcript("user", "hi"), Thinking(), AudioChunk(PCM, 24000),
            Transcript("assistant", "Hello."), TurnComplete(),
        ]
        await adapter.close()

    asyncio.run(run())


def test_large_and_odd_provider_audio_is_split_into_whole_sample_chunks() -> None:
    async def run() -> None:
        adapter, _ = await started(created("r1"), delta("r1", b"\x01" * (40 * 1024 + 1)))
        _, first, second = await take(adapter, 3)
        assert (len(first.data), len(second.data)) == (16 * 1024, 16 * 1024)
        assert not len(first.data) % 2
        await adapter.close()

    asyncio.run(run())


def test_barge_in_interrupts_playback_even_after_the_response_finished() -> None:
    async def run() -> None:
        adapter, socket = await started(created("r1"), delta("r1"), done("r1"))
        assert await take(adapter, 3) == [Thinking(), AudioChunk(PCM, 24000), TurnComplete()]
        socket.push({"type": "input_audio_buffer.speech_started"})
        assert await take(adapter, 1) == [Interrupted()]
        # Speech with nothing playing is not an interruption.
        socket.push({"type": "input_audio_buffer.speech_started"}, created("r2"))
        assert await take(adapter, 1) == [Thinking()]
        await adapter.close()

    asyncio.run(run())


def test_barge_in_drops_the_running_reply_and_its_late_audio() -> None:
    async def run() -> None:
        adapter, socket = await started(created("r1"), delta("r1"))
        assert await take(adapter, 2) == [Thinking(), AudioChunk(PCM, 24000)]
        socket.push(
            {"type": "input_audio_buffer.speech_started"}, delta("r1"),
            {"type": "response.output_audio_transcript.done", "response_id": "r1", "transcript": "cut"},
            done("r1", "cancelled", reason="turn_detected"),
            created("r2"), delta("r2"), done("r2"),
        )
        assert await take(adapter, 4) == [
            Interrupted(), Thinking(), AudioChunk(PCM, 24000), TurnComplete(),
        ]
        await adapter.close()

    asyncio.run(run())


def test_local_interrupt_cancels_the_reply_and_drops_queued_and_late_audio() -> None:
    async def run() -> None:
        adapter, socket = await started(created("r1"), delta("r1"))
        await settle()  # the chunk is queued for the consumer, not yet read
        await adapter.interrupt()
        assert socket.kinds()[-1] == "response.cancel"
        socket.push(delta("r1"), done("r1", "cancelled", reason="client_cancelled"), created("r2"))
        assert await take(adapter, 2) == [Thinking(), Thinking()]
        sent = len(socket.sent)
        await adapter.interrupt()  # r2 is running, so it is cancelled too
        await adapter.end_audio_stream()
        assert socket.kinds()[sent:] == ["response.cancel", "input_audio_buffer.clear"]
        await adapter.close()

    asyncio.run(run())


def test_interrupt_with_no_reply_running_sends_nothing() -> None:
    async def run() -> None:
        adapter, socket = await started()
        await adapter.interrupt()
        assert socket.kinds() == ["session.update"]
        await adapter.close()
        await adapter.interrupt()
        await adapter.end_audio_stream()
        assert socket.kinds() == ["session.update"]

    asyncio.run(run())


@pytest.mark.parametrize(("event", "category"), [
    (ConnectionClosedOK(), "provider-session-ended"),
    (done("r1", "failed", error={"code": "rate_limit_exceeded"}), "provider-limits"),
    (done("r1", "failed", error={"code": "server_error"}), "session-failed"),
    ({"type": "error", "error": {"code": "invalid_event", "message": "secret detail"}}, "session-failed"),
    ({"type": "response.output_audio.delta", "response_id": "r1", "delta": "not base64!"}, "session-failed"),
])
def test_provider_failures_end_the_session_with_a_category(event, category) -> None:
    async def run() -> None:
        adapter, _ = await started(event)
        with pytest.raises(AdapterError) as caught:
            await take(adapter, 1)
        assert str(caught.value) == category
        await adapter.close()

    asyncio.run(run())


def test_a_cancel_that_raced_with_the_provider_does_not_end_the_session() -> None:
    async def run() -> None:
        adapter, _ = await started(
            {"type": "error", "error": {"code": "response_cancel_not_active"}},
            {"type": "unknown.future.event"}, created("r1"),
        )
        assert await take(adapter, 1) == [Thinking()]
        await adapter.close()

    asyncio.run(run())


def test_openai_is_opt_in_needs_a_key_and_reads_its_model_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("SUPER_AGENT_ADAPTER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _adapter_from_environment()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert _adapter_from_environment().name == "openai-realtime"
    monkeypatch.setenv("SUPER_AGENT_LOCAL_TOKEN", "0123456789abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("SUPER_AGENT_OPENAI_MODEL", "model-from-env")
    assert VoiceConfig.from_environment().openai_model == "model-from-env"
