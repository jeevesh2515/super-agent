# A ledger state machine needs more than a transition table

| Field | Value |
| --- | --- |
| Date | 2026-11-15 |
| Evidence | [PH-02 ledger design note (proposal)](../design/ph-02-ledger.md), [ledger tests](../../apps/api/tests/test_ledger.py), [runner tests](../../apps/api/tests/test_runner.py) |

## What happened

We built the PH-02 ledger, policy limits, two synthetic workers and a runner
ahead of roadmap order, as a proposal, in new modules only. The shared
reviewer scored the first version REVISE (correctness 6, security 7) and
reproduced ten defects. The revision fixed them. On 2026-11-15 the API suite
without the new test files ran 741 passed, 1 skipped, and with them 893
passed, 1 skipped.

## What we learned

- A transition table in Python is not enough. The first version also had
  SQLite triggers, but the reviewer still found an audit event for a move
  that did not happen (no row-count check), triggers kept from an older file
  (`CREATE ... IF NOT EXISTS`), and a second instance voiding the first's
  leases on open. Each needed its own guard: a row count inside `BEGIN
  IMMEDIATE`, an exact schema check with a version, and a lock file.
- "Off the event loop" has to include the database. Moving workers to
  threads while the ledger's SQLite calls stayed on the loop let a locked
  database stall the loop for over 5 seconds in the reviewer's run.
- A frozen test clock hides bugs that two clock reads cause. One test with
  an advancing clock found a deadline re-derived as just over 60 seconds.
- A thread cannot be killed, so a hung worker must keep counting as an
  occupied thread. Otherwise the next job is "started" with no thread to run
  it and is wrongly recorded as `unknown`.
- Every exception path needs a defined end state. A NaN in a worker output
  raised before `finish`, and left the job `running` with a live lease.
- A fake CPU worker that steps too fast hits the step limit before the
  cancel and deadline tests can run. Test workers must do real work per step.

## What to do differently

List the failure paths (exception, lock, second process, old file, clock)
next to the happy path in the design before writing the code, and write a
test for each.

## Still unknown

- Whether conversation stays smooth with a real voice session and jobs
  running at the same time. Only synthetic loop-gap tests exist.
- Whether 7 days is the right lifetime for purged idempotency key hashes.
