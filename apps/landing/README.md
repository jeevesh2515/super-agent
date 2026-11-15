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
- [GSAP](https://gsap.com/standard-license/) supplies entry reveals and pointer
  easing. It uses a custom, no-charge license. CSS supplies hover feedback and,
  where supported, scroll-linked hero parallax.
- [Three.js](https://github.com/mrdoob/three.js/blob/r180/LICENSE) (MIT) renders the
  voice waveform. It loads only when audio plays with motion enabled. A static
  SVG is visible if WebGL is unavailable. The visualizer pauses when playback,
  page visibility, or motion preferences require it.
- Space Grotesk and IBM Plex Mono (SIL OFL 1.1) are served locally.
  [Third-party notices](public/notices.txt) ship with the build.

The hero image is original generated concept art, exported as two WebP sizes.
The original 18-second silent film was rendered with
[Pillow and FFmpeg](tools/make-media.py); the render uses macOS system fonts.
The 8.44-second voice clip was synthesized offline with the stock Ryan preset
from [Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
(Apache 2.0), using MLX-Audio 0.6.3. The browser ships only the rendered media
and a level envelope computed from that clip, with a description and transcript
in the page.

See the [reference audit and review](../../docs/design/landing-preview.md) for
the design choices and verification scope.
