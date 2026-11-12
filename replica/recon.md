# Recon map: a personal JARVIS (macOS and browser console)

Scope: the core loop of a private voice assistant: talk, get a fast natural reply, hand over a background job, hear the result.
For: the operator's own daily use. Not yet a product to sell.
Date: 2026-11-12

This is a study of what eight reference products do and how users move through
them, from public documentation only. No source code was read or copied, no
account was used, and nothing was installed. Two research agents (Claude
`sonnet`) did the reading through a summarising fetcher, so numbers such as
defaults and prices should be checked on the primary page before anyone relies
on them. Items marked "unverified" were not confirmed on a primary source. It
is a proposal input. It authorizes no work and ticks nothing on the roadmap.

## Sources

| # | source | URL | notes |
| --- | --- | --- | --- |
| 1 | Pipecat docs | https://docs.pipecat.ai | Turn detection, interruptions, TTS chunking, front and back models. BSD-2. |
| 2 | Pipecat Smart Turn | https://github.com/pipecat-ai/smart-turn | 8M-parameter end-of-turn model. BSD-2. |
| 3 | LiveKit Agents docs | https://docs.livekit.io/agents/ | Turn tuning, preemptive generation, async tools. Framework Apache-2.0; turn-detector models under a LiveKit-only licence (unverified). |
| 4 | Gemini Live API docs | https://aistudio.google.com/docs/live-api | Server VAD, interruption, non-blocking tools, session limits. Proprietary cloud. |
| 5 | OpenAI Realtime docs | https://developers.openai.com/api/docs/guides/realtime-vad | Semantic VAD, truncation on barge-in. Proprietary cloud. |
| 6 | OpenAI realtime agents | https://github.com/openai/openai-realtime-agents | Chat-supervisor pattern. MIT reference repo. |
| 7 | Open Interpreter docs | https://www.openinterpreter.com/docs/terminal | Sandbox modes, approval policies, desktop approval card. Apache-2.0. |
| 8 | 01 project | https://01.openinterpreter.com | Voice client to a host server, QR pairing. AGPL-3.0, developer preview. |
| 9 | Leon AI | https://github.com/leon-ai/leon | Skills, modes, layered memory, owner profile. MIT, 2.0 preview. |
| 10 | Claude Cowork and Dispatch | https://support.claude.com/en/articles/13947068-assign-tasks-to-claude-from-anywhere-in-cowork | Phone-to-desktop tasks, approval modes. Closed, paid, limited beta. |
| 11 | Claude computer use | https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool | Screenshot-action loop, confirm consequential actions. |
| 12 | Home Assistant Assist | https://www.home-assistant.io/voice_control/ | Wake word, satellites, expose list. |
| 13 | super-agent spike A4 | PR 36 of this repository | Our own measurements on the operator's Mac. |

## Core loop

You speak, it answers within about a second in a natural voice, and when you
ask for real work it says "on it", keeps talking with you, and reports back
when the job is done or needs your approval.

## Where super-agent stands today

Measured in spike A4 and tested by the operator on 2026-11-12, who rated it
66 out of 100 against a bar of 90.

| Part of the loop | Today | Reference behaviour |
| --- | --- | --- |
| End of your turn | Fixed 0.7 s of silence | 0.2 s voice detection plus a small model that judges whether you finished (Pipecat, LiveKit); semantic VAD (OpenAI) |
| First reply audio | 2.0 to 2.2 s after the last frame, plus the 0.7 s above | Under a second for native speech models; cascaded stacks use speculation and fillers |
| Voice | macOS `say` | Neural voices (Kokoro in Pipecat's docs; native audio in Gemini and OpenAI) |
| Barge-in | Browser volume threshold; server cancels on real words | Minimum duration and word count, resume after a false interruption, context keeps only what was heard |
| States shown | listening, speaking, muted | listening, thinking, speaking, interrupted (LiveKit) |
| Work | Talk only (tier T0) | Non-blocking tools with an immediate acknowledgement |
| Memory | Last 12 messages, session only | Owner profile and layered memory (Leon); viewable and deletable memory (Dispatch) |

## Screens

Surfaces seen across the references. IDs are stable.

| ID | screen | how to reach | purpose | key components | states seen |
| --- | --- | --- | --- | --- | --- |
| S01 | First-run setup | Install, then open | Check mic, speaker, model | Wizard steps, test buttons | not started, checking, failed, ready (Assist wizard, Leon check) |
| S02 | Pairing | Settings on the host | Link a phone or second device | QR code, device list | waiting, paired, unreachable (01, Dispatch) |
| S03 | Voice session | Main view | Talk | Orb or ring, level meter, mute | idle, listening, thinking, speaking, interrupted, muted, error |
| S04 | Job list | Sidebar or tab | See all work | Rows with state, step, age | empty, running, waiting for approval, done, failed, cancelled (Cowork) |
| S05 | Job detail | Tap a job | Outcome first, log on demand | Summary, step log, steer box, stop | running, done, unknown outcome |
| S06 | Approval card | Appears when a job needs it | Decide one action | Tool, exact parameters, diff or preview, irreversibility warning | pending, approved, denied, expired (OI desktop) |
| S07 | Capability settings | Settings | What it may touch | Tier switches, app and folder allow list | default deny, exposed (Assist expose list, Cowork per-app) |
| S08 | Memory | Settings | What it knows about you | Owner profile editor, memory list, delete | empty, filled (Leon, Dispatch) |
| S09 | Activity log | Settings or job detail | Audit | Searchable list | empty, filled |
| S10 | Notification | System or phone | Job finished or needs you | Title, action | finished, needs approval (Dispatch) |

## Flows

```
F01 First run
    S01 install -> S01 checks -> S03 first conversation
    happy path steps: 1 command plus a wizard (Open Interpreter: 1; Assist hardware: 1 cable plus wizard; 01: 4; Leon: 6)
    edge: mic denied, model missing, port in use, not enough memory

F02 Ask a question
    S03 speak -> S03 thinking -> S03 speaking
    happy path steps: 0 clicks after start
    edge: pause mid-thought, cough, speaker echo, talking over the reply

F03 Hand over a job
    S03 speak -> S03 "on it" -> S04 job appears -> S10 or spoken result
    happy path steps: 0 clicks (Dispatch: 1 message)
    edge: vague request needs a question, job fails, host asleep

F04 Approve a risky action
    S10 notification -> S06 card -> approve or deny
    happy path steps: 2 taps (Dispatch: tap the notification)
    edge: voice says "yes" (must not count), card expires, action changed since the card was shown

F05 Check on or stop a job
    S04 list -> S05 detail -> stop
    happy path steps: 2 clicks, or one spoken command
    edge: stop arrives after the action ran, unknown outcome, stop all

F06 Pair a phone
    S02 show QR -> scan -> S03 on the phone
    happy path steps: 2 (01: scan a QR; Dispatch: 8 documented steps)
    edge: host unreachable, credential revoked
```

## Components

| component | variants | states | used on |
| --- | --- | --- | --- |
| Voice orb | large, compact | idle, listening, thinking, speaking, interrupted, muted, error | S03 |
| Level meter | bars | flat, active | S03 |
| Mute control | button, hotkey | on, off | S03 |
| Job row | compact, expanded | each job state | S04, S05 |
| Approval card | reversible, irreversible | pending, approved, denied, expired | S06 |
| Tier switch | T0 to T3 | off, on, locked | S07 |
| Allow list | apps, folders | empty, filled | S07 |
| Memory item | profile, fact | view, edit, deleted | S08 |
| Log row | action, decision, error | default | S09 |
| Toast or notification | info, needs you | shown, dismissed | S10 |

## Inferred data model

```
Job        id, title, state (the eight canonical states in prd.md), step, created_at, updated_at, revision, tier
           evidence: Cowork job sidebar, Dispatch outcomes, our architecture.md
           confidence: high
Receipt    id, job_id, action, parameters, result, at
           evidence: OI approval card fields, our REQ-05
           confidence: high
Approval   id, job_id, action, parameters_hash, decision, decided_at, device
           evidence: OI desktop approvals, Cowork modes
           confidence: medium
Capability tier, scope (app, folder, account), exposed (bool)
           evidence: Assist expose list, Cowork per-app permission
           confidence: medium
Memory     id, layer (profile, persistent, daily, recent), text, source, expires_at
           evidence: Leon README (four layers, facts expire)
           confidence: guess (Leon does not state its storage)
Device     id, name, credential_id, last_seen, revoked
           evidence: 01 QR pairing, Dispatch pairing
           confidence: guess
Turn       session only: transcript, heard_ms, interrupted
           evidence: OpenAI truncation, Pipecat spoken-text commit
           confidence: high; never stored (REQ-14)
```

Relationships: Job 1-n Receipt, Job 1-n Approval, Capability gates Job.tier, Device 1-n Approval.

## Feature matrix

See `features.csv`. Must: 24, should: 14, could: 6, skip: 5.

## What the references do badly

1. Approvals are by voice, optional, or absent. 01 runs voice commands without showing them. No reference documents a policy layer outside the model with on-device approval. This is super-agent's design already.
2. Job visibility from a phone is thin: Dispatch shows outcomes in one thread.
3. Reachability is unreliable ("Can't reach your desktop" reports, unverified; Assist's first-arriving satellite wins, unverified).
4. Setup is brittle: install failures fill the 01 and Leon issue trackers.
5. Memory is opaque: where it lives is not stated for Dispatch or Leon.

## Out of scope (cannot or should not be cloned)

- Hosted frontier models and their server-side safety classifiers.
- Native speech-to-speech quality: no such model fits a 16 GB Mac next to a language model.
- Cloud sessions that keep running with the laptop closed.
- Dedicated microphone hardware and Home Assistant's device catalogue.
- LiveKit's turn-detector models (licence limits them to LiveKit Agents, unverified).
- Paid cloud features, under the $0 cap.

## Size

Screens 10, flows 6, entities 7. Hard parts: sub-second turn-taking on a 16 GB
Mac, non-blocking jobs with honest stop semantics, on-device approval that
voice cannot bypass. Size: L (a quarter) for the whole loop. The voice-quality
slice alone is M (a few weeks) and is where the 66 to 90 gap most likely sits.
