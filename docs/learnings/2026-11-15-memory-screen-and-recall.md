# A memory screen is a second write path that must stay off the model's road

| Field | Value |
| --- | --- |
| Date | 2026-11-15 |
| Evidence | [design](../design/local-memory-reminders.md#the-memory-screen), tests `apps/api/tests/test_memory_screen.py` and `test_memory_recall.py` |

## What happened

We added a console panel to list, search, edit, forget, undo and pause memory,
and replaced word-overlap recall with SQLite FTS5.

## What we learned

- Rebuilding a tiny in-memory FTS5 table from the live rows on each search
  (the store holds at most 150 facts) removed the whole class of stale-index
  bugs: forget, undo and edit need no index code, and a forgotten fact cannot
  appear. A persistent index with triggers would also break writes on a Python
  build whose SQLite lacks FTS5.
- FTS5 treats quotes, `-`, `*`, `:`, parentheses and the words AND, OR, NOT and
  NEAR as syntax, so a raw query can raise or change meaning. Cutting the query
  into plain words and quoting each one is enough; tests cover the awkward cases.
- The owner's edit and forget functions must not be reachable by the model.
  Keeping them out of the tool tables, behind one caller in the receive loop,
  and adding a test that no adapter module imports them is cheap and checkable.
- Whether a request was heard needs the caller's gate, not the model: the
  adapter passes `from_user` after the request-word check. It is not proof of
  authorship (the text is the model's arguments, and on Gemini the gate reads
  the provider's transcription), so the screen says "You asked to save this"
  or "No request recorded", never "saved from your words".
- Pause is a process-wide flag because the backend allows one session. It is
  cleared when a session starts, not when it ends: clearing it in the end
  path ran before workers stopped, so a tool call in teardown could write
  while the user believed memory was paused.

## What to do differently

Decide early whether owner controls obey the pause. Here they do not, so the
owner can still clean up while the model cannot write.

## Still unknown

Whether paraphrase recall (embeddings) is worth its cost at this size. Not tried.
