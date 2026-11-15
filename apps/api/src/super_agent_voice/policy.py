"""PH-02 policy limits, enforced in code outside any model (REQ-10).

Proposal, built ahead of roadmap order (docs/design/ph-02-ledger.md). Every
job request is hostile input: unknown fields, unknown workers, wrong types,
oversized values and anything over a limit are refused with a fixed reason
code that never repeats the input. Refusal is the only failure mode.
"""
from __future__ import annotations

import json
import unicodedata

from .workers import ORIGINS, Worker

MAX_REQUEST_BYTES = 2048
MAX_OUTPUT_BYTES = 8192
MAX_STEPS = 10_000
MAX_RETRIES = 2  # automatic, read-only steps only (PH-00 R-00.5); never after unknown
MAX_RUNNING = 2
MAX_QUEUED = 20
DEFAULT_DEADLINE_S, MAX_DEADLINE_S = 10, 60
BUDGET_USD = 0.0  # PH-00 R-00.6: $0 cap, no paid fallback
RETENTION_S = 24 * 3600  # PH-00 R-00.5: job metadata kept 24 hours after a terminal state
# A purged job's idempotency key survives as a bare hash for this long, so a late resend is
# refused instead of run twice. Proposal: PH-00 approved no resend window; see the design note.
KEY_TTL_S = 7 * 86_400

REQUEST_FIELDS = frozenset({"worker", "args", "deadline_s"})


class Refused(Exception):
    """A policy refusal. ``str()`` is a fixed reason code, never request content."""


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _arg(spec: tuple, value: object) -> object:
    kind, low, high, _ = spec
    if isinstance(kind, tuple):
        if value not in kind:
            raise Refused("bad_args")
    elif kind is int:
        if type(value) is not int or not low <= value <= high:
            raise Refused("bad_args")
    elif (type(value) is not str or not low <= len(value) <= high
          or any(unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in value)):
        raise Refused("bad_args")
    return value


def admit(request: object, workers: dict[str, Worker], *, origin: str) -> tuple[Worker, dict, float]:
    """Validates one job request. Returns the worker, normalized args, and deadline in seconds."""
    if origin not in ORIGINS:
        raise Refused("bad_origin")
    if not isinstance(request, dict) or not set(request) <= REQUEST_FIELDS:
        raise Refused("bad_request")
    try:
        size = len(canonical(request))
    except (TypeError, ValueError):
        raise Refused("bad_request") from None
    if size > MAX_REQUEST_BYTES:
        raise Refused("too_large")
    name = request.get("worker")
    worker = workers.get(name) if isinstance(name, str) else None
    if worker is None:
        raise Refused("unknown_worker")
    if origin not in worker.origins:
        raise Refused("origin_not_allowed")
    if worker.data_class != "synthetic":
        raise Refused("data_class_not_allowed")  # REQ-13: no personal data yet
    if worker.needs_approval:
        raise Refused("approval_not_built")  # no approval channel exists for ledger jobs yet
    if not worker.cost_usd >= 0 or worker.cost_usd > BUDGET_USD:
        raise Refused("over_budget")
    args = request.get("args", {})
    if not isinstance(args, dict) or not set(args) <= set(worker.fields):
        raise Refused("bad_args")
    clean = {}
    for key, spec in worker.fields.items():
        if key in args:
            clean[key] = _arg(spec, args[key])
        elif spec[3] is None:
            raise Refused("bad_args")
        else:
            clean[key] = spec[3]
    deadline = request.get("deadline_s", DEFAULT_DEADLINE_S)
    if type(deadline) not in (int, float) or not 0 < deadline <= MAX_DEADLINE_S:
        raise Refused("bad_deadline")
    return worker, clean, float(deadline)


def check_output(worker: Worker, output: object) -> bool:
    """True only for a JSON object within the size limit that the worker's own check accepts."""
    try:
        return (isinstance(output, dict) and len(canonical(output)) <= MAX_OUTPUT_BYTES
                and worker.check(output) is True)
    except Exception:
        return False  # fail closed: a check that raises is a failed check
