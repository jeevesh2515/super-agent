# OpenAI Realtime in the console: testing exception to the data boundary and the $0 budget

| Field | Value |
| --- | --- |
| Date | 2026-11-16 |
| Scope | Real microphone audio from the voice console goes to the OpenAI Realtime API, for testing by the maintainers only. Opt-in through `SUPER_AGENT_ADAPTER=openai`. The model has no tools. |
| Departs from | The PH-00 data boundary (R-00.4, "personal microphone audio stays local") and cost limit (R-00.6, "$0 cap, no paid fallback"), [AGENTS.md](../../AGENTS.md) sections 5 and 6, [REQ-13](../../prd.md#req-13), and the open decision R-A.2 (see [DEC-18](../../descisions.md#dec-18)). |
| `jeevesh2515` | **Requested, 2026-11-15 and 2026-11-16**, in chat with Claude Code: asked for his OpenAI account to be added to the assistant, then said "Yes, start there" to building this adapter first. He has not yet confirmed the paid API cost in writing; that confirmation belongs in the PR review. |
| `abhishek3059` | Not asked. One maintainer's approval is enough ([DEC-21](../../descisions.md#dec-21)). |
| Effect | Nothing is ticked and no gate moves. The default adapter is still the fake one. |

## Conditions

1. Nobody speaks personal or sensitive topics.
2. Opt-in only. The fake adapter stays the default and CI never uses OpenAI.
3. The key comes from the process environment only. It is never logged, printed, committed, or sent to the browser. Transcripts are shown in the console for the session only and are never logged.
4. No tools. Any tool or hand-off to a background job needs its own approved design.
5. Cost is bounded by the existing limits in code: one active session and a 15 minute session budget. The maintainer sets a spending limit on the OpenAI account.
6. This exception expires when R-A.2 is decided. Until then it covers testing only, not users.

## Still open

- This work is not an item on [roadmap.md](../../roadmap.md). It needs a roadmap PR or a recorded exception before it merges ([AGENTS.md](../../AGENTS.md) section 11).
- The paid API cost needs the maintainer's explicit confirmation in the PR.
- OpenAI's current API data retention and training terms were not checked against a primary source for this record (unverified).
- No live run has been made. Protocol details were read from the OpenAI Realtime documentation on 2026-11-16; behaviour with real audio is unverified.
