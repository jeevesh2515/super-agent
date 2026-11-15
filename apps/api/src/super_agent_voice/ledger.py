"""PH-02 job ledger: the application-owned record of every background job.

Proposal, built ahead of roadmap order (docs/design/ph-02-ledger.md); not
wired into the voice app. One SQLite file outside the repo, owner-only, held
by one process at a time. The eight canonical states and their transitions
come from architecture.md and are enforced twice: by ``_transition`` (the
only code that writes ``state``) and by SQLite triggers that are rebuilt on
every open, so even a raw UPDATE cannot make an illegal move. A job is
``succeeded`` only from a receipt that matches the job's secret lease and a
verified output, never from model text. The events table is the audit log:
time, job id, worker, state change, reason code. Never job content.

Where the host has no owner-only, no-follow files (Windows, posix_files
decides) the ledger is off: opening it raises ``LedgerError`` with a fixed
reason instead of running a weaker version.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import policy, posix_files
from .policy import Refused, canonical
from .workers import WORKERS, Worker

DB_PATH = Path.home() / ".super-agent" / "ledger.db"
SCHEMA_VERSION = "1"
BUSY_TIMEOUT_S = 0.25  # a locked store fails fast instead of stalling its caller

STATES = ("queued", "running", "waiting_for_approval", "cancel_requested",
          "succeeded", "failed", "cancelled", "unknown")
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
# architecture.md "Canonical job states". unknown -> queued needs a journaled
# decision proving non-execution; no code path in PH-02 takes it.
TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancel_requested", "failed", "waiting_for_approval"}),
    "running": frozenset({"succeeded", "failed", "cancel_requested", "unknown", "waiting_for_approval"}),
    "waiting_for_approval": frozenset({"queued", "cancel_requested", "failed"}),
    "cancel_requested": frozenset({"cancelled", "succeeded", "failed", "unknown"}),
    "succeeded": frozenset(), "failed": frozenset(), "cancelled": frozenset(),
    "unknown": frozenset({"succeeded", "failed", "cancelled", "queued"}),
}
_EXECUTING = ("running", "cancel_requested")
_SNAPSHOT = ("id", "worker", "args", "revision", "state", "reason", "origin", "data_class",
             "provider", "attempts", "result", "receipt", "created_at", "updated_at",
             "started_at", "finished_at", "deadline_at")
_WRITABLE = frozenset({"reason", "lease_sha", "started_at", "finished_at", "attempts", "result", "receipt"})

# Exact statement text: SQLite stores it verbatim, so an open compares it to detect any other shape.
_TABLES = {
    "jobs": "CREATE TABLE jobs("
            "id TEXT PRIMARY KEY, idem_key TEXT NOT NULL UNIQUE, request_sha TEXT NOT NULL, "
            "worker TEXT NOT NULL, args TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, "
            f"state TEXT NOT NULL CHECK (state IN ({', '.join(repr(s) for s in STATES)})), reason TEXT, "
            "origin TEXT NOT NULL CHECK (origin IN ('user_turn', 'planner_step', 'schedule', 'system')), "
            "data_class TEXT NOT NULL CHECK (data_class IN ('synthetic', 'personal')), "
            "provider TEXT NOT NULL, cost_usd REAL NOT NULL DEFAULT 0, "
            "attempts INTEGER NOT NULL DEFAULT 0, lease_sha TEXT, result TEXT, receipt TEXT, "
            "deadline_s REAL NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "started_at TEXT, finished_at TEXT, deadline_at TEXT NOT NULL, "
            "CHECK (state != 'succeeded' OR receipt IS NOT NULL))",
    "events": "CREATE TABLE events("
              "id INTEGER PRIMARY KEY, at TEXT NOT NULL, job_id TEXT NOT NULL, worker TEXT NOT NULL, "
              "from_state TEXT, to_state TEXT NOT NULL, reason TEXT NOT NULL)",
    "used_keys": "CREATE TABLE used_keys(key_sha TEXT PRIMARY KEY, purged_at TEXT NOT NULL)",
    "meta": "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "transitions": "CREATE TABLE transitions(from_state TEXT NOT NULL, to_state TEXT NOT NULL, "
                   "PRIMARY KEY (from_state, to_state)) WITHOUT ROWID",
}
_TRIGGERS = (
    "CREATE TRIGGER jobs_insert_guard BEFORE INSERT ON jobs WHEN NEW.state != 'queued' "
    "BEGIN SELECT RAISE(ABORT, 'jobs start queued'); END",
    "CREATE TRIGGER jobs_state_guard BEFORE UPDATE OF state ON jobs "
    "WHEN NOT EXISTS (SELECT 1 FROM transitions WHERE from_state = OLD.state AND to_state = NEW.state) "
    "BEGIN SELECT RAISE(ABORT, 'illegal transition'); END",
)


class LedgerError(Exception):
    """``str()`` is a fixed reason code; never job content."""


class IllegalTransition(LedgerError):
    pass


class UnknownJob(LedgerError):
    pass


class StaleSession(LedgerError):
    pass


class IdempotencyConflict(LedgerError):
    pass


class RevisionConflict(LedgerError):
    pass


class ReceiptRefused(LedgerError):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="microseconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def receipt_for(job: dict, output: dict) -> dict:
    """What a worker run hands back with its output; the ledger re-derives and compares it."""
    return {"job_id": job["id"], "revision": job["revision"], "worker": job["worker"],
            "output_sha256": _sha(canonical(output))}


def _owner_only_dir(folder: Path) -> None:
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(folder)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise LedgerError("store_dir_unsafe")  # refused, never silently used or loosened


def _private_fd(path: Path) -> int:
    """Opens or creates a regular 0600 file owned by this user, never through a symlink."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        os.close(fd)
        raise LedgerError("store_file_unsafe")
    os.fchmod(fd, 0o600)
    return fd


class Ledger:
    def __init__(self, path: Path | str = DB_PATH, *, clock: Callable[[], datetime] = _utcnow,
                 workers: dict[str, Worker] | None = None) -> None:
        if not posix_files.available():
            raise LedgerError("ledger_off_no_posix_files")
        import fcntl  # POSIX only; imported here so the module still imports on Windows

        self.path = Path(path)
        self.clock = clock
        self.workers = WORKERS if workers is None else workers
        self._lock = threading.Lock()
        self._lock_fd = self._con = None
        try:
            _owner_only_dir(self.path.parent)
            self._lock_fd = _private_fd(self.path.with_name(self.path.name + ".lock"))
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LedgerError("ledger_in_use") from None  # recovery must not void a live instance's leases
            fd = _private_fd(self.path)
            try:
                expected = os.fstat(fd)
                self._con = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_S, isolation_level=None,
                                            check_same_thread=False)
                self._con.execute("PRAGMA schema_version").fetchone()  # makes SQLite open the file now
                seen = os.lstat(self.path)
            finally:
                os.close(fd)
            # SQLite opens by path; refuse if the path changed under us between the checks and the open.
            if not stat.S_ISREG(seen.st_mode) or (seen.st_dev, seen.st_ino) != (expected.st_dev, expected.st_ino):
                raise LedgerError("store_file_unsafe")
            self._con.row_factory = sqlite3.Row
            with self._tx() as con:
                self._schema(con)
                self._recover(con)
                self._purge(con)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None
        if self._lock_fd is not None:
            os.close(self._lock_fd)  # releases the single-instance lock
            self._lock_fd = None

    # --- storage -------------------------------------------------------

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """One write transaction (BEGIN IMMEDIATE) under one lock. Rolls back on any error."""
        with self._lock:
            if self._con is None:
                raise LedgerError("ledger_closed")
            con = self._con
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise

    def _schema(self, con: sqlite3.Connection) -> None:
        found = {r["name"]: r["sql"] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'")}
        if not found:
            for sql in _TABLES.values():
                con.execute(sql)
            con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        else:
            version = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone() \
                if found.get("meta") == _TABLES["meta"] else None
            # No migrations exist yet, so any other shape or version is refused (fail closed).
            if found != _TABLES or version is None or version[0] != SCHEMA_VERSION:
                raise LedgerError("schema_mismatch")
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
            con.execute(f'DROP TRIGGER "{name}"')  # only our own triggers may exist
        for sql in _TRIGGERS:
            con.execute(sql)
        con.execute("DELETE FROM transitions")
        con.executemany("INSERT INTO transitions VALUES (?, ?)",
                        [(a, b) for a, targets in TRANSITIONS.items() for b in targets])

    def _row(self, con: sqlite3.Connection, job_id: object) -> sqlite3.Row:
        row = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone() if isinstance(job_id, str) else None
        if row is None:
            raise UnknownJob("unknown_job")
        return row

    def _transition(self, con: sqlite3.Connection, job_id: str, to: str, reason: str, **fields: object) -> None:
        """The only writer of ``state``. Raises on any move the canonical table does not allow."""
        if not set(fields) <= _WRITABLE:
            raise LedgerError("bad_field")
        row = self._row(con, job_id)
        if to not in TRANSITIONS[row["state"]]:
            raise IllegalTransition("illegal_transition")
        sets = {"state": to, "reason": reason, "updated_at": _iso(self.clock()), **fields}
        if to in TERMINAL:
            sets["finished_at"] = sets["updated_at"]
        cur = con.execute(f"UPDATE jobs SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ? AND state = ?",
                          (*sets.values(), job_id, row["state"]))
        if cur.rowcount != 1:
            raise LedgerError("state_changed")  # the transaction rolls back; no event is written
        self._event(con, job_id, row["worker"], row["state"], to, reason)

    def _event(self, con: sqlite3.Connection, job_id: str, worker: str, frm: str | None, to: str, reason: str) -> None:
        con.execute("INSERT INTO events(at, job_id, worker, from_state, to_state, reason) VALUES (?, ?, ?, ?, ?, ?)",
                    (_iso(self.clock()), job_id, worker, frm, to, reason))

    def _snapshot(self, row: sqlite3.Row) -> dict:
        snap = {k: row[k] for k in _SNAPSHOT}
        for key in ("args", "result", "receipt"):
            snap[key] = None if snap[key] is None else json.loads(snap[key])
        return snap

    def _recover(self, con: sqlite3.Connection) -> None:
        """Startup, with the single-instance lock held: nothing is executing, so anything that was is
        uncertain. Never replayed."""
        for row in con.execute("SELECT id, state, started_at FROM jobs WHERE state IN ('running', 'cancel_requested')").fetchall():
            if row["state"] == "cancel_requested" and row["started_at"] is None:
                self._transition(con, row["id"], "cancelled", "restart_not_started")
            else:
                self._transition(con, row["id"], "unknown", "restart", lease_sha=None)

    def _purge(self, con: sqlite3.Connection) -> None:
        """Drops terminal jobs and their events 24 h after they finish. Each key leaves a hash-only
        tombstone for KEY_TTL_S, so a late resend is refused rather than run again."""
        now = self.clock()
        cutoff = _iso(now - timedelta(seconds=policy.RETENTION_S))
        old = con.execute("SELECT id, idem_key FROM jobs WHERE state IN ('succeeded', 'failed', 'cancelled') "
                          "AND finished_at < ?", (cutoff,)).fetchall()
        con.executemany("INSERT OR REPLACE INTO used_keys VALUES (?, ?)", [(_sha(r["idem_key"]), _iso(now)) for r in old])
        con.executemany("DELETE FROM events WHERE job_id = ?", [(r["id"],) for r in old])
        con.executemany("DELETE FROM jobs WHERE id = ?", [(r["id"],) for r in old])
        con.execute("DELETE FROM used_keys WHERE purged_at < ?", (_iso(now - timedelta(seconds=policy.KEY_TTL_S)),))

    # --- sessions ------------------------------------------------------

    def begin_session(self) -> str:
        """A new console session. Every earlier session becomes stale."""
        session = secrets.token_urlsafe(16)
        with self._tx() as con:
            con.execute("INSERT OR REPLACE INTO meta VALUES ('session_sha', ?)", (_sha(session),))
        return session

    def _session(self, con: sqlite3.Connection, session_id: object) -> None:
        row = con.execute("SELECT value FROM meta WHERE key = 'session_sha'").fetchone()
        if row is None or not isinstance(session_id, str) or not hmac.compare_digest(row[0], _sha(session_id)):
            raise StaleSession("stale_session")

    # --- admission -----------------------------------------------------

    def _admit(self, con: sqlite3.Connection, request: object, key: str, origin: str) -> sqlite3.Row:
        worker, args, deadline_s = policy.admit(request, self.workers, origin=origin)
        digest = _sha(canonical({"worker": worker.name, "args": args, "deadline_s": deadline_s}))
        old = con.execute("SELECT * FROM jobs WHERE idem_key = ?", (key,)).fetchone()
        if old is not None:
            if old["request_sha"] != digest:
                raise IdempotencyConflict("idempotency_conflict")
            return old
        if con.execute("SELECT 1 FROM used_keys WHERE key_sha = ?", (_sha(key),)).fetchone():
            raise Refused("key_expired")
        waiting = con.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued', 'waiting_for_approval')").fetchone()[0]
        if waiting >= policy.MAX_QUEUED:
            raise Refused("queue_full")
        spent_row = con.execute("SELECT value FROM meta WHERE key = 'spent_usd'").fetchone()
        spent = float(spent_row[0]) if spent_row else 0.0
        if spent + worker.cost_usd > policy.BUDGET_USD:
            raise Refused("over_budget")
        # The counter lives in meta, so a purge never resets it.
        con.execute("INSERT OR REPLACE INTO meta VALUES ('spent_usd', ?)", (repr(spent + worker.cost_usd),))
        now = self.clock()  # one read: created_at and the deadline agree exactly
        job_id = f"job_{secrets.token_hex(8)}"
        con.execute("INSERT INTO jobs(id, idem_key, request_sha, worker, args, state, reason, origin, data_class, "
                    "provider, cost_usd, deadline_s, created_at, updated_at, deadline_at) "
                    "VALUES (?, ?, ?, ?, ?, 'queued', 'admitted', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (job_id, key, digest, worker.name, canonical(args), origin, worker.data_class,
                     worker.provider, worker.cost_usd, deadline_s, _iso(now), _iso(now),
                     _iso(now + timedelta(seconds=deadline_s))))
        self._event(con, job_id, worker.name, None, "queued", "admitted")
        return self._row(con, job_id)

    def create(self, request: object, *, idempotency_key: object, session_id: object,
               origin: str = "user_turn") -> dict:
        """Admits one job. Repeating the same key and request returns the same job."""
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
            raise Refused("bad_idempotency_key")
        with self._tx() as con:
            self._session(con, session_id)
            return self._snapshot(self._admit(con, request, f"user:{idempotency_key}", origin))

    def revise(self, job_id: object, *, base_revision: object, args: object, session_id: object) -> dict:
        """New args for a job that has not started; the base revision must be current."""
        with self._tx() as con:
            self._session(con, session_id)
            row = self._row(con, job_id)
            if type(base_revision) is not int or base_revision != row["revision"]:
                raise RevisionConflict("revision_conflict")
            if row["state"] != "queued":
                raise IllegalTransition("not_revisable")
            _, clean, _ = policy.admit({"worker": row["worker"], "args": args, "deadline_s": row["deadline_s"]},
                                       self.workers, origin=row["origin"])
            # Attempts, deadline and budget carry over: a revision never resets a limit. The
            # idempotency digest stays the create request's, so a resent create still matches.
            con.execute("UPDATE jobs SET args = ?, revision = revision + 1, updated_at = ? "
                        "WHERE id = ? AND revision = ? AND state = 'queued'",
                        (canonical(clean), _iso(self.clock()), row["id"], row["revision"]))
            self._event(con, row["id"], row["worker"], "queued", "queued", "revised")
            return self._snapshot(self._row(con, row["id"]))

    def cancel(self, job_id: object, *, session_id: object) -> dict:
        """Records cancel intent. Never-started work is cancelled at once; a finished job is left as is."""
        with self._tx() as con:
            self._session(con, session_id)
            row = self._row(con, job_id)
            if row["state"] in ("queued", "waiting_for_approval"):
                self._transition(con, row["id"], "cancel_requested", "user_cancel")
                self._transition(con, row["id"], "cancelled", "never_started")
            elif row["state"] == "running":
                self._transition(con, row["id"], "cancel_requested", "user_cancel")
            return self._snapshot(self._row(con, row["id"]))

    # --- reads ---------------------------------------------------------

    def get(self, job_id: object) -> dict:
        with self._tx() as con:
            return self._snapshot(self._row(con, job_id))

    def jobs(self, limit: int = 20) -> list[dict]:
        with self._tx() as con:
            rows = con.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),))
            return [self._snapshot(r) for r in rows.fetchall()]

    def events(self, job_id: str) -> list[dict]:
        with self._tx() as con:
            rows = con.execute("SELECT at, job_id, worker, from_state, to_state, reason FROM events "
                               "WHERE job_id = ? ORDER BY id", (job_id,))
            return [dict(r) for r in rows.fetchall()]

    def queued_ids(self) -> list[str]:
        with self._tx() as con:
            return [r[0] for r in con.execute("SELECT id FROM jobs WHERE state = 'queued' ORDER BY created_at, id")]

    def seconds_left(self, job_id: str) -> float:
        with self._tx() as con:
            deadline = datetime.fromisoformat(self._row(con, job_id)["deadline_at"])
        return (deadline - self.clock()).total_seconds()

    # --- runner side (holds the lease) ---------------------------------

    def expire(self) -> list[str]:
        """Fails queued jobs whose deadline passed before any worker was free. They never ran."""
        with self._tx() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM jobs WHERE state = 'queued' AND deadline_at <= ?",
                                             (_iso(self.clock()),)).fetchall()]
            for job_id in ids:
                self._transition(con, job_id, "failed", "deadline")
            return ids

    def start(self, job_id: str) -> str | None:
        """Leases a queued job if the deadline and concurrency cap allow. Returns the secret lease."""
        with self._tx() as con:
            row = self._row(con, job_id)
            if row["state"] != "queued":
                return None
            if datetime.fromisoformat(row["deadline_at"]) <= self.clock():
                self._transition(con, job_id, "failed", "deadline")
                return None
            running = con.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('running', 'cancel_requested') "
                                  "AND started_at IS NOT NULL").fetchone()[0]
            if running >= policy.MAX_RUNNING:
                return None
            lease = secrets.token_urlsafe(24)
            self._transition(con, job_id, "running", "leased", lease_sha=_sha(lease),
                             started_at=_iso(self.clock()), attempts=row["attempts"] + 1)
            return lease

    def _leased(self, con: sqlite3.Connection, job_id: str, lease: object) -> sqlite3.Row:
        row = self._row(con, job_id)
        if (row["state"] not in _EXECUTING or row["lease_sha"] is None or not isinstance(lease, str)
                or not hmac.compare_digest(row["lease_sha"], _sha(lease))):
            raise ReceiptRefused("bad_lease")
        return row

    def retry(self, job_id: str, lease: str) -> bool:
        """Counts one more attempt if the retry limit allows; False means fail now."""
        with self._tx() as con:
            row = self._leased(con, job_id, lease)
            if row["state"] != "running" or row["attempts"] > policy.MAX_RETRIES:
                return False
            con.execute("UPDATE jobs SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
                        (_iso(self.clock()), job_id))
            self._event(con, job_id, row["worker"], "running", "running", "retry")
            return True

    def finish(self, job_id: str, lease: str, output: object, receipt: object) -> dict:
        """``succeeded`` only if the lease, receipt and output all verify; a bad output is a failure."""
        with self._tx() as con:
            row = self._leased(con, job_id, lease)
            worker = self.workers.get(row["worker"])
            job = {"id": row["id"], "revision": row["revision"], "worker": row["worker"]}
            # check_output runs first: it refuses anything canonical() cannot encode (NaN, sets).
            if (worker is None or not policy.check_output(worker, output)
                    or not isinstance(receipt, dict) or receipt != receipt_for(job, output)):
                self._transition(con, job_id, "failed", "unverified_output", lease_sha=None)
            else:
                stored = {**receipt, "verified_at": _iso(self.clock()), "attempt": row["attempts"]}
                self._transition(con, job_id, "succeeded", "verified_receipt", lease_sha=None,
                                 result=canonical(output), receipt=canonical(stored))
            return self._snapshot(self._row(con, job_id))

    def fail(self, job_id: str, lease: str, reason: str) -> None:
        with self._tx() as con:
            self._leased(con, job_id, lease)
            self._transition(con, job_id, "failed", reason, lease_sha=None)

    def stopped(self, job_id: str, lease: str, reason: str) -> None:
        """The worker acknowledged a stop: cancelled if a cancel was asked, else failed for ``reason``."""
        with self._tx() as con:
            row = self._leased(con, job_id, lease)
            if row["state"] == "cancel_requested":
                self._transition(con, job_id, "cancelled", "stop_acknowledged", lease_sha=None)
            else:
                self._transition(con, job_id, "failed", reason, lease_sha=None)

    def lost(self, job_id: str, lease: str, reason: str) -> None:
        """The outcome cannot be proven (no stop acknowledgement in time, or a runner fault)."""
        with self._tx() as con:
            self._leased(con, job_id, lease)
            self._transition(con, job_id, "unknown", reason, lease_sha=None)
