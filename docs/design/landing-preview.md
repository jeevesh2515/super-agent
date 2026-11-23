# Super Agent landing preview: reference and review

15 November 2026. This is a standalone concept preview, not phase evidence or
a change to the implementation order. The job states demonstrate intended
behavior with fictional data. No roadmap ticks changed.

## Reference inventory and first preview

An independent agent inspected the live [Aller Studio home page](https://www.allerstudio.com/)
in Chromium at 1440 × 900 and 390 × 844, and inspected the relevant production bundles.

| Reference component | What it contributes | Super Agent response |
| --- | --- | --- |
| Loader, city clocks, availability, Services menu, booking CTA | Builds the studio’s identity and provides several routes to engage. The first-load overlay postpones access. | Show the product immediately. Give the simulation the primary CTA and put the source in the navigation. |
| Portrait hero and custom cursor/particle effects | Establishes an immediately identifiable visual. The lazy hero uses [Three.js r186](https://www.allerstudio.com/_next/static/immutable/chunks/27163zsgosw73.js) and a [custom shader renderer](https://www.allerstudio.com/_next/static/immutable/chunks/3ztpwzxd7xmfr.js), with a static WebP fallback. | Use a machined optical core, a dark blue palette, and restrained parallax. The first render needs no WebGL. |
| Client logos, problem and sector sections, selected cases and testimonials | Shows the range of work, then substantiates it with detailed examples and named customers. | Use one explorable job with a ledger. Link to the real voice scaffold and label the demonstration as a simulation. |
| Oversized typography, services, engagement formats, four-step process | Changes pace, then turns studio capabilities into a concrete working sequence. | Alternate dark and paper sections. Let the visitor move through request, scope, run, and receipt. |
| Scroll reveals, CSS transitions, Canvas 2D and WebGL effects | Brings attention to selected elements; production code uses scroll and pointer input. | Use GSAP reveals, small hover reactions, and scroll-linked hero parallax. Honor reduced motion. |
| Sound effects, independent music tray, decorative embeds | Adds a second sensory layer with separate effects/music controls. The checked home page had no native video element. | Provide a silent concept film and an opt-in synthetic voice clip with native controls and text alternatives. Use Three.js for the audio visualizer. |
| FAQ and contact footer | Answers predictable questions and gives a next step. | Explain what runs today and link to the source and roadmap. |

The audit observed Next.js/React, Tailwind-style utility classes, Rajdhani and
Inter, responsive images, and Web Audio interaction sounds. GSAP and Lenis were
not identified in the inspected bundles; that is not proof of absence.

## Independent UI judgement of the first preview

The reference auditor visited both pages and scored each for its own primary
visitor task. The scores are qualitative, not user research or an accessibility
certification.

| Criterion | Super Agent preview | Aller Studio |
| --- | ---: | ---: |
| Art direction | 8.6 | 9.0 |
| Depth and pacing of motion | 8.0 | 9.2 |
| Clarity and first action | 8.6 | 7.6 |
| Evidence and trust | 8.2 | 9.2 |
| Observed accessibility and fallbacks | 8.8 | 7.7 |

The reviewer found the preview clearer about what to do first. Aller had richer
motion and stronger real-world proof through its case studies. The reviewer
found that the primary CTA initially landed above the actual simulation control
on desktop. It now links directly to the console. The site also links to the
voice scaffold beside the simulation.

## Verification of the first preview

- Chromium, desktop and emulated mobile: checked widths from 320 to 1440 CSS px.
  Tested approve/complete, decline, stop, reset, focus recovery, and FAQ.
- Observed actual audio and video playback, mutual pause, and lazy Three.js
  loading. With reduced motion enabled the audio still played and no visualizer
  bundle was requested.
- In a cold desktop load, the original hero image transferred about 179 kB.
  Media payloads and the Three.js chunk were absent from the initial request list.
- The repository guard, two simulation tests, production build, and npm audit
  passed. Physical-device Safari, longitudinal performance, and screen-reader
  user tests were not run.

## Revised preview

The maintainer asked for an original armor hero with pointer response, an
understated palette, sound effects, and a background video below the hero.
The revised page uses graphite, bone, and oxide, with Instrument Sans for
display type and IBM Plex Mono for the job states and ledger. The warm
palette extends to the concept film and audio visualization.

The helmet is an original textured relief rendered with Three.js. Its pointer
orbit is intentionally limited. The locally rendered six-second loop is silent
and plays in the media section with a pause control. Website sound starts off.
The simulation still uses fictional reports and runs in the browser.
