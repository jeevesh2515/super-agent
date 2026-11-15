# PH-02 ledger, policy, and fixed workers: design note

| Field | Value |
| --- | --- |
| Date / revision | 2026-11-15 / 2 (after the shared reviewer's REVISE findings) |
| Author | A Claude Code agent session, for operator `jeevesh2515` |
| Status | **Proposal.** Built ahead of roadmap order and not accepted. No roadmap item is ticked by this work. Any exception that lets it merge is recorded by the maintainers under `docs/approvals/`, not here. |
| Code | [ledger.py](../../apps/api/src/super_agent_voice/ledger.py), [policy.py](../../apps/api/src/super_agent_voice/policy.py), [workers.py](../../apps/api/src/super_agent_voice/workers.py), [runner.py](../../apps/api/src/super_agent_voice/runner.py) |
| Tests | [test_ledger.py](../../apps/api/tests/test_ledger.py), [test_runner.py](../../apps/api/tests/test_runner.py), [test_ledger_windows.py](../../apps/api/tests/test_ledger_windows.py) |
| Wired into the app | No. `app.py`, `memory.py`, the adapters and `apps/web` are unchanged. |

## 1. What this is

The backend core for roadmap items R-02.1 to R-02.5: a job ledger, a policy
layer, two fixed read-only workers over synthetic data, and an asyncio
runner. It follows [architecture.md](../../architecture.md) (canonical job
states), [RT-004](../../tasks/004-task-ledger-and-policy.md),
[RT-005](../../tasks/005-fixed-sample-workers.md),
[DEC-18](../../descisions.md#dec-18), [DEC-20](../../descisions.md#dec-20),
the [PH-00 setup decisions](../approvals/ph-00-setup-decisions.md) (retention,
retries, $0), and the brain interface requests in
[overview.md](brain/overview.md#11-interface-requests-for-the-ledger).

It adds no dependency. It uses only the Python standard library.

A job scheduler is proposed separately and is not part of this note or this
branch.

## 2. State machine

The eight states and their allowed moves are copied from
[architecture.md](../../architecture.md#canonical-job-states):

| From | Allowed next states |
| --- | --- |
| `queued` | `running`, `cancel_requested`, `failed`, `waiting_for_approval` |
| `running` | `succeeded`, `failed`, `cancel_requested`, `unknown`, `waiting_for_approval` |
| `waiting_for_approval` | `queued`, `cancel_requested`, `failed` |
| `cancel_requested` | `cancelled`, `succeeded`, `failed`, `unknown` |
| `succeeded`, `failed`, `cancelled` | none (terminal) |
| `unknown` | `succeeded`, `failed`, `cancelled`, `queued` |

Enforcement happens in four places:

1. `Ledger._transition` is the only Python code that writes `state`. It
   raises `IllegalTransition` for any pair outside the table.
2. It runs inside one `BEGIN IMMEDIATE` transaction, and it checks that its
   `UPDATE ... WHERE state = ?` changed exactly one row. Otherwise it raises
   `state_changed`, the transaction rolls back, and no event is written.
3. SQLite triggers reject any `UPDATE` of `state` that is not in a
   `transitions` table, and any `INSERT` whose state is not `queued`. Every
   open drops all triggers in the file and creates ours again, and rebuilds
   `transitions` from the Python table.
4. A `CHECK` constraint makes `succeeded` impossible without a stored receipt.

**What each move needs:**

- `queued` to `running`: `start()` rechecks the deadline and the concurrency
  cap, then issues a random lease. Only its SHA-256 hash is stored.
- `running` to `succeeded`: `finish()` needs the lease, a receipt equal to
  the one the ledger derives (job id, revision, worker, SHA-256 of the
  canonical output), and an output that passes the size limit and the
  worker's own check. With a valid lease but a bad, oversized, or
  unencodable output (for example NaN), the job moves to `failed` with
  reason `unverified_output`. Model text has no lease, so a claim like "it
  is done" cannot complete a job.
- Cancel on a `queued` job is `queued` to `cancel_requested` to `cancelled`
  (`never_started`). On a `running` job it is `cancel_requested`. The worker
  then either acknowledges (`cancelled`), finishes verified work first
  (`succeeded`, as the table allows), or does not answer within the grace
  time (`unknown`). Cancel on a terminal or `unknown` job changes nothing.
- No code path enters `waiting_for_approval` or takes `unknown` to `queued`.
  Both stay in the table because architecture.md defines them. Work that
  needs approval is refused at admission (section 5).

**Restart.** Only one `Ledger` can hold the file (section 3). On open it
moves every `running` job, and every `cancel_requested` job that had
started, to `unknown` (reason `restart`), and clears its lease. A
`cancel_requested` job that never started becomes `cancelled`. Nothing is
replayed. `queued` jobs never started, so running them later is a first run.
If their deadline has passed, they fail with `deadline` and do not run.

## 3. Storage and schema

- **Host rule.** The ledger follows
  [posix_files.py](../../apps/api/src/super_agent_voice/posix_files.py).
  Where owner-only, no-follow files do not exist (Windows), opening the
  ledger raises `LedgerError("ledger_off_no_posix_files")` and touches no
  file. The modules still import there.
- **Folder.** `~/.super-agent/`, outside the repository. A missing folder is
  created with mode 0700. An existing folder that is a symlink, is owned by
  someone else, or gives any group or other permission is refused with
  `store_dir_unsafe`. It is never loosened or used as it is.
- **File.** `ledger.db` is opened with `O_NOFOLLOW` and `O_NONBLOCK`, must
  be a regular file owned by this user, and is set to 0600. SQLite then
  opens the same path. Before using it, the ledger checks that the path
  still names the file it checked (same device and inode, not a symlink).
  Otherwise it refuses with `store_file_unsafe`. This closes the
  check-then-open race as far as SQLite allows: a swap and a swap back
  between the two opens would not be seen, but only the owner can write in
  a 0700 folder. SQLite gives its rollback journal the same mode as the
  database (SQLite behaviour, not tested here).
- **One instance.** A second file, `ledger.db.lock` (0600, no-follow), holds
  an exclusive `flock` for the life of the `Ledger`. A second instance on
  the same file fails with `ledger_in_use`, so recovery can never void the
  leases of a live instance.
- **One connection.** The `Ledger` owns one SQLite connection, used under a
  lock. Every operation is one `BEGIN IMMEDIATE` transaction. A locked
  database fails after 0.25 s (`BUSY_TIMEOUT_S`) instead of waiting.
- **Schema version.** `meta.schema_version` is `1`. On open, the stored
  text of every table must equal the current statements exactly, and the
  version must match. Anything else, such as an older table without its
  `CHECK`s, is refused with `schema_mismatch`. No migration exists yet.
- **Tables.**
  - `jobs`: `id`, `idem_key` (unique), `request_sha`, `worker`, `args`,
    `revision`, `state`, `reason`, `origin`, `data_class`, `provider`,
    `cost_usd`, `attempts`, `lease_sha`, `result`, `receipt`, `deadline_s`,
    `created_at`, `updated_at`, `started_at`, `finished_at`, `deadline_at`.
  - `events`: `at`, `job_id`, `worker`, `from_state`, `to_state`, `reason`.
  - `used_keys`: `key_sha`, `purged_at` (section 4).
  - `meta`: schema version, the hash of the current session id, and the
    budget counter `spent_usd`.
  - `transitions`: the allowed pairs, rebuilt on open.
- Times are UTC ISO 8601 strings with fixed-width microseconds. Admission
  reads the clock once, so `created_at` and `deadline_at` are exactly
  `deadline_s` apart. The requested `deadline_s` is stored, never re-derived.
- `origin` is set by code from the call path, never from the request.
  `data_class` and `provider` come from the worker registry (`synthetic`,
  `local`). These cover DEC-20 part 3 and brain IR-1 and IR-3.

## 4. Idempotency, revisions, sessions, and retention

- **Idempotency.** `create()` needs a caller key of 8 to 128 characters.
  The same key with the same normalized request returns the same job. The
  same key with a different request raises `IdempotencyConflict`.
- **Retention and keys.** Terminal jobs and their events are deleted 24
  hours after they finish, each time the ledger opens (PH-00 R-00.5).
  `unknown` jobs are not purged, because they still need reconciliation.
  When a job is purged, its idempotency key stays behind as a bare SHA-256
  hash in `used_keys` for 7 days (`KEY_TTL_S`). A create that reuses such a
  key is refused with `key_expired`. It never runs the job again. The PH-00
  record approves a retry count (2) but no resend window in time, so 7 days
  is a proposal. The hash holds no job content, worker, state, or time
  except the purge time. Maintainers should confirm it, because it outlives
  the 24 hours that apply to job metadata.
- **Budget.** The budget counter `spent_usd` lives in `meta`. Admission
  adds each job's cost to it. A purge never resets it, and a revision never
  changes it.
- **Revisions.** `revise(job_id, base_revision, args)` works only on a
  `queued` job and only when `base_revision` is current. Otherwise it raises
  `RevisionConflict` or `IllegalTransition`. The new args pass the same
  policy check. The deadline, attempts, and budget carry over, so a revision
  never resets a limit (RT-004 failure considerations). The idempotency
  digest stays the create request's, so a resent create still returns the
  job. Steering a running job is PH-03 (RT-006) and is not built.
- **Stale sessions.** `begin_session()` returns a new random session id and
  stores only its hash. That makes every earlier session stale. `create`,
  `revise` and `cancel` raise `StaleSession` for any other id, including a
  missing one. Runner calls are authenticated by the job lease instead.

## 5. Policy limits

All limits are constants in [policy.py](../../apps/api/src/super_agent_voice/policy.py),
checked in code. The values are proposals.

| Limit | Value | Where it is enforced |
| --- | --- | --- |
| Request fields | `worker`, `args`, `deadline_s` only | `policy.admit` |
| Worker | must be in the fixed registry | `policy.admit` |
| Arguments | only the worker's declared fields; type, length or range, and no control or format characters | `policy.admit` |
| Request size | 2048 bytes of canonical JSON (NaN and infinity refused) | `policy.admit` |
| Output size | 8192 bytes of canonical JSON, plus the worker's own check | `policy.check_output` |
| Deadline | default 10 s, above 0 and at most 60 s, counted from admission | `admit`, `Ledger.expire`, `Ledger.start`, the runner wait |
| Steps | 10,000 per attempt | `workers.stepper` |
| Automatic retries | 2, only after a worker error, never after a stop, a deadline, or `unknown` | `Ledger.retry` |
| Running jobs | 2 at once, counted in the ledger and as occupied runner threads | `Ledger.start`, `Runner.tick` |
| Queued jobs | 20 | `Ledger._admit` |
| Budget | $0. A worker with any cost is refused. | `admit` and `_admit` (counter in `meta`) |
| Data class | `synthetic` only | `policy.admit` |
| Origin | one of the four IR-1 origins and allowed by the worker | `policy.admit` |
| Approval | any worker that needs approval is refused (`approval_not_built`) | `policy.admit` |
| Retention | 24 h after a terminal state; key hashes 7 days | `Ledger._purge` |
| Database lock wait | 0.25 s | `BUSY_TIMEOUT_S` |

Every refusal is a fixed reason code, such as `unknown_worker` or
`bad_args`. A refusal never repeats the input. Any error in a check counts as
a refusal (fail closed).

## 6. The two workers

Both are plain functions over constants bundled in
[workers.py](../../apps/api/src/super_agent_voice/workers.py). They do not
use a shell, the network, files, plugins, or any owner data.

| Worker | Arguments | Output |
| --- | --- | --- |
| `sales_total` | `region`: `all`, `north`, `south`, `east`, or `west` (default `all`) | row count and total in cents over 2000 synthetic sales rows |
| `note_search` | `query`: 1 to 64 characters; `limit`: 1 to 10 (default 5) | up to `limit` matching ids and titles over 8 synthetic notes, and the count scanned |

Each worker calls `step()` once per row. `step()` raises `Stop` when a stop
was asked and `StepLimit` past 10,000 steps. Each worker also has an output
check: `note_search` results must name real note ids with their real
titles. Note `N7` is written as a prompt injection on purpose. The tests show
that it comes back as plain data and changes no state.

## 7. Runner and the event loop

[runner.py](../../apps/api/src/super_agent_voice/runner.py) keeps both kinds
of blocking work off the asyncio loop that serves audio:

- **Worker attempts** run on a two-thread pool.
- **Every ledger call** runs on one dedicated `ledger-db` thread through
  `Runner.call`. The loop only awaits it. A locked database makes that call
  fail after 0.25 s; it never stalls the loop. A test holds `BEGIN
  IMMEDIATE` on another connection and shows the loop's longest gap stays
  under 100 ms while `tick()` waits and then fails.

How a job runs:

- `tick()` first retries any job it could not settle earlier, then fails
  queued jobs whose deadline passed (`expire`), then leases queued jobs, but
  only while a runner thread is free.
- The runner waits for the worker, a cancel, or the deadline, whichever
  comes first. The wait is bounded by the deadline, so the deadline always
  fires.
- On a cancel or a deadline the runner sets the stop flag and waits
  `grace_s` (default 1 s). A stop acknowledgement gives `cancelled` or
  `failed`/`deadline`. No acknowledgement gives `unknown`/`no_stop_ack`, and
  any late result is dropped, never recorded. Work that finishes inside the
  grace time after a deadline is still `failed`/`deadline`. Work that
  finishes inside the grace time after a cancel is `succeeded`, as the
  architecture table allows.
- **Any other exception** on the worker or ledger path (for example a
  locked database during `finish`) ends the job as `unknown`/`runner_error`.
  If even that write fails, the job is kept in memory and every later tick
  tries again until the ledger holds a defined state.
- `serve()` catches a failed tick, counts it, and tries again on the next
  interval.
- **Hung threads.** A thread cannot be killed. A worker that ignores its
  stop flag keeps its thread after its job is settled as `unknown`. The
  runner counts that thread as occupied until it returns and starts no job
  without a free thread. Such a job stays `queued`, or fails with
  `deadline` if its deadline passes first. It is never recorded as doubtful
  work. This is scheduling isolation, not a sandbox
  ([RT-005](../../tasks/005-fixed-sample-workers.md) non-goals). Only
  trusted fixed functions may be registered.
- **Metadata.** `Runner.status()` reports busy threads, stuck threads,
  unsettled jobs, failed ticks, and the type name of the last fault. Each
  fault also appends one line (`ledger.runner <code>`) to the metadata audit
  log through `posix_files.append_audit`. No job content is written.
- Cancel must go through `Runner.cancel`. A cancel written straight to the
  ledger records intent but does not signal the running thread.

## 8. Threat model for this layer

| Threat | Mitigation | Test |
| --- | --- | --- |
| The model or injected text claims a job is done | `succeeded` needs the secret lease, a matching receipt and a verified output; the DB `CHECK` needs a receipt | `test_forged_done_without_valid_receipt_is_refused`, `test_database_refuses_illegal_raw_writes` |
| Injection-shaped text in job input or worker output | Args are validated data; workers never evaluate text; the state is set by code only | `test_injection_in_input_and_data_stays_inert` |
| Unknown worker, extra fields, oversized or odd values | Fixed registry, closed field sets, size and type limits, fixed refusal codes | `test_requests_refused`, `test_refusal_never_echoes_input` |
| Spending money | $0 budget; the counter survives purges | `test_money_spending_worker_refused`, `test_purge_keeps_keys_and_budget` |
| Personal data in a job | Only `synthetic` workers are admitted | `test_personal_data_worker_refused` |
| A replayed or old command | Stale-session rejection, idempotency keys and their hashes, base revisions | `test_stale_session_rejected`, `test_idempotent_create`, `test_purge_keeps_keys_and_budget`, `test_revision` |
| Blind replay after a crash | Restart moves executing jobs to `unknown` and voids their leases | `test_restart_moves_running_to_unknown_without_replay` |
| A second process voiding live leases | Single-instance `flock` | `test_second_instance_fails_closed` |
| An audit event for a move that did not happen | Row-count check in the same transaction | `test_stale_read_writes_no_event` |
| An old or tampered schema or trigger | Exact schema check, version, triggers rebuilt on open | `test_old_table_shape_is_refused`, `test_wrong_schema_version_is_refused`, `test_planted_triggers_are_replaced_on_open` |
| A runaway or stuck worker | Step limit, deadline, grace time, then `unknown`; hung threads counted | `test_step_limit`, `test_deadline_fires`, `test_cancel_without_stop_ack_is_unknown`, `test_hung_threads_block_new_starts_without_doubt` |
| A locked or failing database | Short busy timeout, ledger thread, defined end state, `serve` survives | `test_event_loop_stays_responsive_while_the_store_is_locked`, `test_serve_survives_a_failed_tick`, `test_ledger_error_during_finish_ends_unknown`, `test_unsettled_job_is_settled_by_a_later_tick` |
| Job content in logs | Events and runner audit lines hold metadata only | `test_events_hold_metadata_only` |
| Another local user reads or swaps the store | 0700 folder required, 0600 file, no symlink follow, identity check after SQLite opens | `test_store_dir_not_owner_only_is_refused`, `test_symlinked_store_dir_refused`, `test_symlinked_store_file_refused`, `test_store_swapped_before_sqlite_opens_is_refused` |
| A host without owner-only files | The ledger is off there | `test_ledger_is_off_without_posix_files` |

Not covered here: host compromise, and a malicious process running as the
same user. It can read the file and write SQLite directly; the triggers and
checks stop mistakes, not an attacker with the owner's rights. Untrusted
code is not allowed at all.

## 9. Wiring plan for app.py and the console (not done)

Another branch is changing `app.py`, `memory.py` and `apps/web`, so none of
this is wired yet. The plan:

1. On startup, if `posix_files.available()`, `app.py` opens one `Ledger()`
   and one `Runner(ledger)`, and starts `runner.serve(1.0)` as a background
   task that is cancelled on shutdown. `runner.close()` and
   `ledger.close()` run at shutdown. If the ledger refuses to open, jobs are
   off and the console shows the fixed reason.
2. Each authenticated console websocket calls
   `await runner.call(ledger.begin_session)` and keeps the id server-side
   for that connection. The browser never sees it. A second console makes
   the first stale, which matches the single-owner console.
3. New websocket messages from the console: `job.create` (worker, args,
   idempotency key), `job.cancel`, `job.revise`, `job.list`. Each maps to
   one `runner.call(...)` (or `runner.cancel`), then `runner.tick()`. A
   `Refused` or `LedgerError` returns its fixed code.
4. The server pushes snapshots from `ledger.jobs()` and `runner.status()`
   after each change, and on a timer while jobs are active.
5. Voice tools later (brain `propose_task`, `query_ledger`, `cancel_task`)
   call the same functions with origin `user_turn`. The model never gets a
   lease, and its text never reaches `finish`. A spoken "done" must come
   from a `succeeded` snapshot (brain BR-5).

## 10. Gate and acceptance mapping

| Condition | Source | Built and tested here | Not yet |
| --- | --- | --- | --- |
| Two trusted read-only synthetic workers | RT-G02, RT-005 | Yes: `sales_total`, `note_search` | |
| Bounded inputs and finite outputs | RT-G02, RT-005 | Yes: request, arg and output limits | |
| Structured receipts and verification | RT-G02, RT-005 | Yes: lease, digest and output check | An independent verifier (brain IR-4 `speakable_summary`) |
| Off-loop execution | RT-G02, RT-005 | Yes: worker pool and ledger thread; loop-gap tests with a busy worker and a locked database | Process isolation |
| Authoritative ledger states | RT-G02, RT-004 | Yes: 8 states, 64-pair table test, row-count check, triggers, schema check | |
| Externally enforced resource limits | RT-G02, RT-004 | Yes: section 5 | Provider request counting (brain IR-5) |
| Idempotency, revisions, stale sessions | RT-004, REQ-06 | Yes | Steering a running job (PH-03) |
| Budget not reset by revisions or purges | RT-004 | Yes | |
| Cancellation and uncertainty | RT-004, REQ-05 | Yes: before, during, after, race, no ack, runner faults | Emergency stop latch (PH-03) |
| Continued native conversation during overlap | RT-G02, RT-005 | No. Only synthetic loop-gap tests exist. | Needs wiring and a measured run with a voice session open |
| No arbitrary-code, host-shell, plugin or external-action exposure | RT-G02 | Yes: fixed registry, no such code paths | Independent review |
| `origin`, `data_class`, `provider` | DEC-20 | Yes | `model` per attempt (brain IR-3): no model is used |
| Restart without blind replay | REQ-06 | Yes: running to `unknown`, single instance | Reconciliation of `unknown` jobs |
| `job_terminal` event, purge receipts | brain IR-2, IR-6 | No | |
| RT-004 and RT-005 records complete | roadmap R-02.6 | No. Task records stay `not started`. | Maintainer acceptance |

## 11. Choices made where the docs were silent

- The deadline counts from admission, so time in the queue counts too.
- `unknown` jobs are never retried or purged automatically.
- A job finished inside the grace time after its deadline is still `failed`.
- Retry happens only after a worker exception, inside the same deadline.
- A runner fault ends the job as `unknown`, not `failed`, because the
  outcome is not proven.
- One session at a time: a new session makes all earlier ones stale.
- One ledger process at a time, enforced by a lock file.
- The SQLite events table is the job audit log, and runner faults go to the
  existing metadata audit log. Neither holds job content.
- Approval-needing work is refused everywhere, because no approval channel
  exists for the ledger yet.
- Purged keys survive as hashes for 7 days (section 4), pending a
  maintainer decision.
