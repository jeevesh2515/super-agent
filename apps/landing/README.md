# Super Agent landing preview

This is the public-facing concept for Super Agent. The walkthrough compares two
fictional build reports in the browser. Approve it, decline it, or stop it before
showing the result. It does not use the microphone, open user files, or talk to the
assistant runtime. The [roadmap](../../roadmap.md) is the record of product status.

## Run it locally

From the repository root, with Node 22.12 or newer:

```sh
npm ci --prefix apps/landing --ignore-scripts
npm test --prefix apps/landing
npm run build --prefix apps/landing
npm run preview --prefix apps/landing -- --port 4177 --strictPort
```

Open `http://127.0.0.1:4177/`. For edits, use `npm run dev --prefix apps/landing`.
The built site is self-contained in `apps/landing/dist` and can be served by a
static host. It does not require credentials, an API, or a paid service.

## Implementation

- Vite (MIT) bundles and fingerprints the static assets. The landing package is
  separate from the voice application.
- [GSAP](https://gsap.com/standard-license/) handles the entrance and scroll
  reveals. It uses a custom, no-charge license. CSS handles smaller hover effects.
- [Three.js](https://github.com/mrdoob/three.js/blob/r180/LICENSE) (MIT) renders
  the hero as a textured depth mesh with limited pointer tilt. The still stays
  available on touch devices, with reduced motion, and without WebGL. The voice
  waveform also uses Three.js while the synthesized clip plays.
- The sound toggle enables short Web Audio tones for interface feedback. It
  starts off and is independent of the voice sample.
- The silent six-second background loop starts when its section is visible.
  It pauses offscreen and has an explicit play/pause control. With reduced motion
  it starts on the poster and loads the video only when requested.
- Instrument Sans and IBM Plex Mono (SIL OFL 1.1) are served locally.
  [Third-party notices](public/notices.txt) ship with the build.

The original helmet was generated as concept photography. Its WebP is both the
still fallback and the texture on the depth mesh. The background loop is a
procedural metal study [rendered locally](tools/make-armor-loop.py) with NumPy,
Pillow, and FFmpeg. The 18-second silent concept film was rendered with
[Pillow and FFmpeg](tools/make-media.py); the render uses macOS system fonts.
The 8.44-second voice clip was synthesized offline with the stock Ryan preset
from [Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
(Apache 2.0), using MLX-Audio 0.6.3. The browser ships only the rendered media
and a level envelope computed from that clip, with a description and transcript
in the page.

See the [reference audit and review](../../docs/design/landing-preview.md) for
the design choices and verification scope.
