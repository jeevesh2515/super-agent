"""Exercise one synthetic Realtime-to-Hermes handoff with injected transports."""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass
from uuid import uuid4

from .adapter import AdapterError, AdapterEvent, AudioChunk, Interrupted, TurnComplete
from .jarvis_runtime import JarvisRuntime
from .live_check import FRAME_BYTES, speak, speak_windows
from .openai_realtime import OpenAIRealtimeAdapter, RealtimeTool, Transport

TOOL_NAME = "run_research_fixture"
SPOKEN_REQUEST = "Use the run research fixture tool. Then say the verified result when it is ready."
WORKER_REQUEST = (
    "Use this synthetic fixture only. The release brief says Omar owns the mute check. "
    "Reply with exactly one sentence giving the owner."
)
EXPECTED_RESULT = "Omar owns the mute check."
ANNOUNCEMENT = "The research fixture is complete. Omar owns the mute check."
_MAX_SESSION_SECONDS = 35
_RECEIPT_TIMEOUT_SECONDS = 15
_CLOSE_TIMEOUT_SECONDS = 2
_POLL_SECONDS = 0.05
_RUN_ID = re.compile(r"run_[0-9a-f]{32}")


@dataclass(slots=True)
class HandoffEvidence:
    outcome: str = "voice-not-verified"
    job_id: str | None = None
    receipt_verified: bool = False
    acknowledgment_bytes: int = 0
    announcement_bytes: int = 0
    announcement_completed: bool = False
    transport_closed: bool = False


async def exercise_handoff(
    transport: Transport,
    runtime: JarvisRuntime,
    *,
    synthesize: Callable[[str], bytes] | None = None,
    pace: float = 0.1,
) -> HandoffEvidence:
    """The caller owns the runtime. This check owns just its session and submitted job."""
    evidence = HandoffEvidence()
    request_id = uuid4()

    def dispatch(arguments: dict[str, object]) -> dict[str, object]:
        if arguments or evidence.job_id is not None:
            return {"status": "rejected"}
        try:
            evidence.job_id = runtime.submit("research", WORKER_REQUEST, request_id)
        except RuntimeError:
            evidence.outcome = "worker-unavailable"
            return {"status": "unavailable"}
        return {"status": "queued"}

    tool = RealtimeTool(
        TOOL_NAME,
        "Queue the fixed read-only research fixture. Its result is reported separately.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        dispatch,
    )
    adapter = OpenAIRealtimeAdapter(transport, tool=tool)
    generate = synthesize or (speak_windows if sys.platform == "win32" else speak)
    try:
        async with asyncio.timeout(_MAX_SESSION_SECONDS):
            clip = await asyncio.to_thread(generate, SPOKEN_REQUEST)
            if not isinstance(clip, bytes) or not clip or len(clip) % 2 or len(clip) > 10 * 32_000:
                raise AdapterError("session-failed")
            await adapter.start()
            async with aclosing(adapter.events()) as events:
                acknowledgment, evidence.acknowledgment_bytes = await _request(adapter, events, clip, pace)
                if acknowledgment is None or TOOL_NAME not in acknowledgment.tools or evidence.job_id is None:
                    if evidence.outcome == "voice-not-verified":
                        evidence.outcome = "dispatch-not-confirmed"
                elif not evidence.acknowledgment_bytes:
                    evidence.outcome = "acknowledgment-not-verified"
                else:
                    evidence.outcome = await _verify_receipt(runtime, evidence.job_id)
                    if evidence.outcome == "receipt-verified":
                        evidence.receipt_verified = True
                        await adapter.request_announcement(ANNOUNCEMENT)
                        announcement, evidence.announcement_bytes = await _read_turn(events)
                        evidence.announcement_completed = announcement is not None
                        evidence.outcome = (
                            "verified" if evidence.announcement_completed and evidence.announcement_bytes
                            else "announcement-not-verified"
                        )
    except TimeoutError:
        evidence.outcome = "session-timeout"
    except AdapterError as error:
        evidence.outcome = error.category
    finally:
        if evidence.job_id is not None and not evidence.receipt_verified:
            runtime.cancel(evidence.job_id)
        try:
            async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                await adapter.close()
            evidence.transport_closed = True
        except (TimeoutError, AdapterError, OSError):
            evidence.outcome = "transport-close-failed"
    return evidence


async def _request(
    adapter: OpenAIRealtimeAdapter, events: AsyncIterator[AdapterEvent], clip: bytes, pace: float,
) -> tuple[TurnComplete | None, int]:
    async def send_input() -> None:
        # Let server VAD consume trailing silence. Mute clears the provider buffer.
        pcm = clip + bytes(12 * FRAME_BYTES)
        for offset in range(0, len(pcm), FRAME_BYTES):
            await adapter.enqueue_audio(pcm[offset : offset + FRAME_BYTES])
            await asyncio.sleep(pace)

    sender = asyncio.create_task(send_input())
    reader = asyncio.create_task(_read_turn(events, acknowledgment_adapter=adapter))
    try:
        _, acknowledgment = await asyncio.gather(sender, reader)
        return acknowledgment
    finally:
        sender.cancel()
        reader.cancel()
        await asyncio.gather(sender, reader, return_exceptions=True)


async def _read_turn(
    events: AsyncIterator[AdapterEvent], *, acknowledgment_adapter: OpenAIRealtimeAdapter | None = None,
) -> tuple[TurnComplete | None, int]:
    output_bytes = 0
    async for event in events:
        if isinstance(event, AudioChunk):
            if acknowledgment_adapter is None or acknowledgment_adapter.waiting_for_tool_reply:
                output_bytes += len(event.data)
        elif isinstance(event, TurnComplete):
            return event, output_bytes
        # Server VAD normally emits speech-start on the initial synthetic clip.
        elif isinstance(event, Interrupted) and acknowledgment_adapter is None:
            return None, output_bytes
    return None, output_bytes


async def _verify_receipt(runtime: JarvisRuntime, job_id: str) -> str:
    try:
        async with asyncio.timeout(_RECEIPT_TIMEOUT_SECONDS):
            while True:
                job = next((row for row in runtime.snapshot()["jobs"] if row["id"] == job_id), None)
                if job is None or job["workerId"] != "research":
                    return "receipt-not-verified"
                if job["status"] == "succeeded":
                    receipt = job.get("receipt")
                    run_id = receipt.get("runId") if isinstance(receipt, dict) else None
                    if (
                        isinstance(receipt, dict) and receipt.get("status") == "completed"
                        and isinstance(run_id, str) and _RUN_ID.fullmatch(run_id)
                        and receipt.get("resultTruncated") is not True and job.get("result") == EXPECTED_RESULT
                    ):
                        return "receipt-verified"
                    return "receipt-not-verified"
                if job["status"] not in ("queued", "running"):
                    return "job-not-verified"
                await asyncio.sleep(_POLL_SECONDS)
    except TimeoutError:
        return "receipt-timeout"
