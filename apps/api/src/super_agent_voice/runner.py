"""Runs admitted ledger jobs without blocking the asyncio loop that serves voice.

Proposal, built ahead of roadmap order (docs/design/ph-02-ledger.md). Worker
attempts run on a small thread pool. Every ledger call runs on one dedicated
thread, so a slow or locked database never stalls the loop either; the ledger
itself gives up on a lock after BUSY_TIMEOUT_S. A cancel or a deadline sets
the worker's stop flag; the worker stops at its next step. If it does not
acknowledge within ``grace_s`` the job becomes ``unknown``. A thread cannot be
killed (the workers are trusted fixed code, not a sandbox), so the runner
counts such a thread as occupied until it really returns and starts no job
it has no free thread for. Every failure on the worker or ledger path ends
the job in a defined state, or is retried until it does.
"""
from __future__ import annotations

import asyncio
import functools
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import policy, posix_files
from .ledger import Ledger, ReceiptRefused, receipt_for
from .workers import Stop, StepLimit, stepper

# Metadata only, same file and format as the other audit lines.
AUDIT_LOG = Path.home() / ".super-agent" / "tool-audit.log"


def _discard(fut: asyncio.Future) -> None:
    if not fut.cancelled():
        fut.exception()  # a late result after "unknown" is dropped, never recorded


class Runner:
    def __init__(self, ledger: Ledger, *, grace_s: float = 1.0, audit_log: Path | None = None) -> None:
        self.ledger = ledger
        self.grace_s = grace_s
        self.audit_log = AUDIT_LOG if audit_log is None else audit_log
        self._pool = ThreadPoolExecutor(max_workers=policy.MAX_RUNNING, thread_name_prefix="ledger-job")
        self._db = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ledger-db")
        self._tick_lock = asyncio.Lock()
        self._cancels: dict[str, asyncio.Event] = {}
        self._futs: dict[str, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()
        self._busy = 0  # pool threads held by a job or by a worker that outlived its job
        self._stuck: set[str] = set()  # jobs settled while their thread still runs
        self._unsettled: dict[str, str] = {}  # job -> lease, when even marking unknown failed
        self.tick_failures = 0
        self.last_fault: str | None = None

    async def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Runs one ledger call on the ledger thread. The wiring uses this for every console call."""
        return await asyncio.get_running_loop().run_in_executor(self._db, functools.partial(fn, *args, **kwargs))

    def status(self) -> dict:
        """Metadata for the console: thread use, stuck threads, and the last fault's type name."""
        return {"busy_threads": self._busy, "stuck_threads": len(self._stuck), "unsettled": len(self._unsettled),
                "tick_failures": self.tick_failures, "last_fault": self.last_fault}

    def _fault(self, code: str) -> None:
        self.last_fault = code
        posix_files.append_audit(self.audit_log, posix_files.audit_line("ledger.runner", code))

    async def tick(self) -> list[str]:
        """Settles leftovers, expires late queued jobs, then leases queued jobs onto free threads."""
        async with self._tick_lock:
            for job_id, lease in list(self._unsettled.items()):
                if await self._settle(job_id, lease):
                    del self._unsettled[job_id]
            await self.call(self.ledger.expire)
            started = []
            for job_id in await self.call(self.ledger.queued_ids):
                if self._busy >= policy.MAX_RUNNING:
                    break  # no free thread: the job stays queued and is never recorded as doubtful
                lease = await self.call(self.ledger.start, job_id)
                if lease is None:
                    continue
                self._busy += 1
                self._cancels[job_id] = asyncio.Event()
                task = asyncio.create_task(self._run(job_id, lease))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                started.append(job_id)
            return started

    async def serve(self, every_s: float = 1.0) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:  # a failed tick is recorded and the next one tries again
                self.tick_failures += 1
                self._fault(f"tick_error:{type(exc).__name__}")
            await asyncio.sleep(every_s)

    async def cancel(self, job_id: object, *, session_id: object) -> dict:
        snapshot = await self.call(self.ledger.cancel, job_id, session_id=session_id)
        if snapshot["state"] == "cancel_requested" and snapshot["id"] in self._cancels:
            self._cancels[snapshot["id"]].set()
        return snapshot

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks))

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._db.shutdown(wait=True)

    def _release(self, job_id: str) -> None:
        self._busy -= 1
        self._stuck.discard(job_id)

    async def _settle(self, job_id: str, lease: str) -> bool:
        """Marks a job unknown after a runner fault. True once the ledger holds a defined state."""
        try:
            await self.call(self.ledger.lost, job_id, lease, "runner_error")
        except ReceiptRefused:
            pass  # the lease is gone: the job already reached a defined state
        except Exception:
            return False
        return True

    async def _run(self, job_id: str, lease: str) -> None:
        try:
            await self._attempts(job_id, lease)
        except Exception as exc:
            self._fault(f"job_error:{type(exc).__name__}")
            if not await self._settle(job_id, lease):
                self._unsettled[job_id] = lease  # the next tick tries again
        finally:
            self._cancels.pop(job_id, None)
            fut = self._futs.pop(job_id, None)
            if fut is not None and not fut.done():
                self._stuck.add(job_id)
                self._fault("stuck_thread")
                fut.add_done_callback(lambda _f: self._release(job_id))
            else:
                self._release(job_id)

    async def _attempts(self, job_id: str, lease: str) -> None:
        loop, cancel = asyncio.get_running_loop(), self._cancels[job_id]
        job = await self.call(self.ledger.get, job_id)
        worker = self.ledger.workers[job["worker"]]
        stop = threading.Event()
        while True:
            fut = loop.run_in_executor(self._pool, worker.run, dict(job["args"]), stepper(stop, policy.MAX_STEPS))
            fut.add_done_callback(_discard)
            self._futs[job_id] = fut
            waiter = asyncio.ensure_future(cancel.wait())
            left = await self.call(self.ledger.seconds_left, job_id)
            done, _ = await asyncio.wait({fut, waiter}, timeout=max(0.0, left), return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            reason = None
            if fut not in done:
                reason = "cancelled" if cancel.is_set() else "deadline"
                stop.set()
                done, _ = await asyncio.wait({fut}, timeout=self.grace_s)
                if not done:
                    await self.call(self.ledger.lost, job_id, lease, "no_stop_ack")
                    return
            try:
                output = fut.result()
            except Stop:
                await self.call(self.ledger.stopped, job_id, lease, reason or "cancelled")
                return
            except StepLimit:
                await self.call(self.ledger.fail, job_id, lease, "step_limit")
                return
            except Exception:
                if reason is None and await self.call(self.ledger.retry, job_id, lease):
                    continue
                await self.call(self.ledger.fail, job_id, lease, "worker_error")
                return
            if reason == "deadline":
                await self.call(self.ledger.fail, job_id, lease, "deadline")  # finished inside the grace window: still late
                return
            try:
                receipt = receipt_for(job, output)
            except Exception:
                receipt = None  # an output that cannot be encoded fails verification in finish
            # A cancel that loses the race to verified work ends succeeded (architecture.md).
            await self.call(self.ledger.finish, job_id, lease, output, receipt)
            return
