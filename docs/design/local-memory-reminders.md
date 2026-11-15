# Local memory and reminders (design)

| Field | Value |
| --- | --- |
| Status | Proposal, built on branch `feat/local-memory-reminders` ahead of the roadmap order. Not accepted. |
| Tier | T2 under [DEC-18](../../descisions.md#dec-18): reversible writes to the assistant's own store, logged, with an undo path |
| Approval | [Out-of-order record](../approvals/local-memory-exception.md) |
| Reference | Roamies design reference, section 1 (ideas only), in [PR 44](https://github.com/abhishek3059/super-agent/pull/44) |
| Code | `apps/api/src/super_agent_voice/memory.py`, `memory_screen.py`, wired in `local_adapter.py` and `app.py`; console panel in `apps/web/src/app` |

## What the assistant can do

With `SUPER_AGENT_MEMORY=on` (off by default):

| Tool | Does |
| --- | --- |
| `remember_fact` | Saves one short fact the user asked it to remember |
| `add_reminder` | Saves a reminder for a spoken time, optionally repeating |
| `list_memory`, `list_reminders` | Reads back what is stored |
| `complete_reminder` | Marks a reminder done; a repeating one moves to its next time |
| `forget` | Removes up to 5 matching items |
| `undo_forget` | Restores the last forget within 24 hours |

Due reminders are spoken between turns, never over the user, and the user's
next words cut a reminder off. A question gets notes, marked "data, not
instructions", only when a stored fact or a reminder due within 48 hours
shares a word with it: at most 3 facts and 5 reminders. An unrelated question
gets none. "What do you remember about me" gets the 5 newest facts.

## Controls (in code)

1. **Local only.** One SQLite file, `~/.super-agent/memory.db`, mode 0600 in a
   0700 folder. Nothing is sent anywhere; the model is the local Ollama model.
2. **Opt-in and fail closed.** Memory tools exist only when
   `SUPER_AGENT_MEMORY=on`; any other value except `off` refuses the session.
3. **Caps.** 150 facts, 200 open reminders, 1 to 240 characters each, with
   control, bidi and zero-width characters stripped.
4. **No obvious secrets.** Text that looks like a password, PIN, API key,
   token or private key is refused and never echoed. "Change my password" is
   allowed; "my password is ..." is not. This is a pattern check, not a
   guarantee: "bank pin 4821" or a bare card number gets through.
5. **Times are parsed in code.** The model passes the user's words ("every
   weekday at nine am"); code turns them into a time or refuses, and the reply
   states the time it chose. A bare "at 5" means the next 05:00. Repeat rules are `daily`, `weekdays`, `weekends`, or one weekday.
6. **Undo.** Forget is a soft delete kept for 24 hours; `undo_forget` restores
   the last batch. Adding is undone by forgetting.
7. **Logged, metadata only.** Each memory tool call appends time, tool name,
   and ok or error to `~/.super-agent/tool-audit.log`. Never the text, so the
   log shows that something was added or forgotten, not what. Spoken
   reminders are not logged.
8. **No memory writes after reading outside text.** In a turn where a tier 1
   tool read a file, note, email or calendar entry, every memory write tool
   refuses. A message cannot plant a reminder that later speaks in the
   assistant's voice. Reading memory is still allowed. The guard covers that
   turn only: if the user repeats read text and says "remember that" in a
   later turn, it is saved, because the user asked.
9. **Stored text cannot break the notes frame.** Parentheses become square
   brackets on save.
10. **Strict arguments.** Exactly the declared keys and types; plain digit
    strings count as numbers because small models send them that way.
11. **The user must have asked.** `remember_fact`, `add_reminder` and `forget`
    run only when the user's words in that turn contain a matching request
    word ("remember", "remind", "forget" and a few like them). The small model
    otherwise saved things nobody asked for.

## Recall

Recall uses SQLite FTS5 from the standard library `sqlite3`, with the
`porter unicode61` tokenizer, so "sisters" finds "my sister is Asha". No new
dependency and no embeddings. The store is capped at 150 facts, so the index is
built from the live rows in a throwaway in-memory table on each search. It
cannot go stale: an edit, a forget or an undo shows on the next search, and a
forgotten fact is never in it. Ranking is BM25, ties newest first.

- The query is cut into plain words of 3 or more characters, each one quoted
  and joined with OR, so quotes, punctuation and the words AND, OR, NOT and
  NEAR never reach the FTS5 query syntax. At most 20 words are used.
- At startup `memory.FTS5` records whether this SQLite has FTS5. If not,
  recall falls back to the earlier word-overlap match.
- Stored text is only ever matched against, never run: a fact that looks like
  SQL, an FTS query or an instruction stays a line of data.
- Still a proposal, not built: a small local embedding model for paraphrases
  ("my sibling" for "my sister"), merged with FTS5. It needs a roadmap item and
  both maintainers' yes, as before.

Neither step reduces hallucination by itself. What does: retrieve only a few
notes per turn (done), tell the model to answer from a note or say it does not
know, and let it call `list_memory` for a full lookup.

## The memory screen

The console has a Memory panel (the book icon in the top bar) so the owner can
see everything stored, and correct or remove it, without talking to the model.
It lists facts and open reminders with when each was saved and whether it was
stored from the user's own words (the request-word gate in rule 11 passed; items
saved before this feature show "Origin not recorded"). It has search (the same
FTS5 recall), inline edit of a fact, forget, undo, and a pause switch.

It works over the session's existing authenticated socket, so it needs an open
session. If `SUPER_AGENT_MEMORY` is not on, every memory message is refused and
the panel says memory is off.

| Browser sends | Fields (all required, no others) | Reply |
| --- | --- | --- |
| `memory.list` | `query`: string, up to 100 characters ("" for everything; the page sends one only with 3 or more) | `memory.items` |
| `memory.edit` | `id`: integer 1 to 2^31, `text`: string, 1 to 1000 characters | `memory.result` |
| `memory.forget` | `kind`: `fact` or `reminder`, `id`: as above | `memory.result` |
| `memory.undo` | none | `memory.result` |
| `memory.pause` | `paused`: boolean | `memory.result` |

`memory.items` is `{ enabled, paused, undoable, items }`. Each item has `kind`,
`id`, `text`, `createdAt`, `fromUser`, and for a reminder `dueAt` and `repeat`.
`undoable` counts the items the latest forget would restore (inside the 24 hour
window). `memory.result` is `{ op, ok }` plus `error` when refused. The error is
one of `memory-off`, `bad-text`, `secret`, `duplicate`, `not-found`,
`nothing-to-restore`, `full` or `failed`. After a change the page lists again
rather than guessing what the store holds.

Rules in code (`memory_screen.py`, `memory.py`):

1. **Browser only.** The receive loop in `app.py` is the one caller. Adapter
   events (model output, tool output, transcripts) go to the console as text
   and never reach the handler. The owner functions are not model tools: they
   are not in `TOOLS`, `NAMES` or the dispatch table, so a tool call named
   `edit_fact` is "no such tool". A test fails if an adapter module imports them.
2. **Strict shape.** Wrong type, unknown or missing field, a bool where an
   integer is expected, an id out of range or text over its limit closes the
   session with `invalid-control`, as `action.decision` does. Before
   authentication the socket closes (1008) and nothing runs.
3. **Same limits as the tools.** An edit goes through the same cleaning,
   240 character limit, secret check and bracket rule as a saved fact, and may
   not duplicate another fact. Only facts can be edited; a forgotten item is
   "not found".
4. **Forget and undo reuse the soft delete.** Forget stamps one item and undo
   restores the latest batch inside 24 hours, exactly as the voice tools do.
5. **Pause.** While paused, the model's memory writes (`remember_fact`,
   `add_reminder`, `complete_reminder`, `forget`, `undo_forget`) return a fixed
   refusal. Reads and the owner's own screen edits still work, so the owner can
   clean up while paused. The flag is process-wide, cleared when a session
   starts and when it ends, and never stored.
6. **Never logged.** Each screen operation appends time, `screen_*` operation
   and ok or error to the audit log. Text, ids and queries are not logged, and
   the reply text goes to the browser only.
7. **Rendered as text.** The page parses every reply strictly, bounds it, shows
   stored text with text interpolation (never HTML) and replaces an unknown
   error code with fixed wording.

With Gemini the screen is not a model path: listing or editing never sends
stored text to Google. Only a memory tool call the model makes does.

## Known limits

- Reminders fire only while a voice session is open. A reminder due while no
  session is open is spoken at the next session's first check.
- A reminder is marked only after it is spoken. One cut off by the user, or
  by the session closing, is spoken again at a later check. A spoken one-time
  reminder is done; a spoken repeat moves to its next time.
- "Done" on a repeat that was just spoken keeps its next time. "Done" said
  early, before a repeat speaks, after an earlier one was heard, also keeps
  the next time, so that one still speaks.
- Completing a one-time reminder has no undo.
- Forgotten text stays on disk, soft-deleted, for up to 24 hours.
- The memory screen needs an open voice session, because it uses that
  socket. A refused edit closes the inline editor, so the typed text is lost.
- Recall matches word forms, not meaning: "my sibling" does not find "my
  sister".
- Items saved before the screen existed have no recorded origin.
- A memory write already running in a thread finishes even if the user
  interrupts or the session closes.
- Local time comes from `/etc/localtime`. On Windows it falls back to a fixed
  offset, so repeats can drift by an hour across a clock change. A time that
  does not exist on a clock-change day (01:30 when clocks jump) moves forward
  an hour.
- The small brain sometimes misreads stored times or pads reminder text (see
  the [test record](../implementation/local-memory-test.md)).
- A prompt injection spoken by the user, or one that reaches the model without
  a tier 1 read, can still be remembered and shown again as a note. The notes
  are framed as data and no tool can act on them.
