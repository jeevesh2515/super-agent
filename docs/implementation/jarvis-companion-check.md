# Jarvis companion check (R-H.9 and R-H.10)

Status: **macOS run recorded 2026-11-23.** R-H.9 and R-H.10 are ticked from
this record. R-H.11 (desktop overlay) is separate and stays unticked.

## Host and revision

| Field | Value |
| --- | --- |
| Host | macOS 27.2.1 (build 26B131) |
| Node | v22.22.3 |
| Revision | `9099a82` (web and server code is the same as `develop`; this commit changes only the desktop overlay and its CI step) |
| Build | `npm run build -w web`, 2250 modules, `dist/index.html` plus assets |
| Data | throwaway `HQ_DATA_DIR` under the temp folder, `HQ_NO_SCHEDULER=1`, no Hermes, no provider keys, synthetic rows only |
| Browser | Google Chrome through Playwright, 1280x900 and 700x800 |

One synthetic assistant message was inserted into the throwaway `rows` table
to test **Sketch latest reply**. It is not product data.

## Checks

| Check | Method | Result |
| --- | --- | --- |
| Companion opens | Open `/?companion` in a signed-in tab | `section.companion` visible, label "Jarvis companion" |
| Walkthrough starts | Click **Show me how** | "Step 1 of 2 · Select Ember" |
| Walkthrough waits | Read the step before acting | It stayed on step 1 until the highlighted control was activated |
| Keyboard activation | Focus the highlighted skin, press Enter | Step 2 of 2 · Select Arc |
| Walkthrough completes | Focus Arc, press Enter | "Walkthrough complete." |
| Explain a pasted excerpt | Paste seven sentences, click **Make sketch** | Five points, the cap in `sketchPoints` |
| Explain the latest reply | Open **Explain** with a synthetic assistant reply | Five points from that reply |
| Explain makes no model request | Record requests while sketching | 0 requests containing `/api/` |
| Saved appearance | Select Carbon, reload | `aria-pressed="true"` on Carbon and `data-look="carbon"` |
| Reduced motion | Emulate `prefers-reduced-motion: reduce` | Companion art `animation-name` is `none` |
| Small screen | Viewport 700x800 | Companion visible, sidebar hidden |
| Server self-checks | `npm test` in `apps/hq` | 54 passed, 0 failed, 16 skipped (pgvector and bubblewrap suites) |
| Repository checks | `npm run check` | 0 errors |

The explanation display is a bounded list of up to five steps beside the open
conversation. It is not a card inside the transcript. The R-H.10 wording says
"flow cards"; this record describes what shipped so a reviewer can judge that
difference.

## Not checked

- A live voice call driving the companion. The voice control is present but
  was not started.
- A real Hermes worker turn. The transcript was synthetic.
- Windows.
- A screen reader, touch input, and browser zoom beyond the 700x800 viewport.
- The desktop overlay, including the new sphere art. R-H.11 keeps its own
  record and still needs a macOS and Windows run on the merged revision.
