"""Render the original silent landing-page film with Pillow and FFmpeg on macOS.

Run from any directory: python3 apps/landing/tools/make-media.py
"""

from math import cos, exp, pi, sin
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT, FPS = 1280, 720, 24
OUTPUT = Path(__file__).resolve().parents[1] / "media"
PAPER = "#ecedff"
MUTED = "#a5adc6"
ACCENT = "#a49fff"
HAIRLINE = "#29334e"

TITLE = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 62, index=2)
BODY = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 22, index=5)
MONO = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 16)
SMALL = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 13)

CHAPTERS = (
    (0.0, "REQUEST", "Compare the\ntwo build reports.", "A voice request becomes a visible job."),
    (4.5, "SCOPE", "Read only.\nTwo example files.", "The job lists exactly what it can open."),
    (9.0, "FINDING", "One new\nfailure found.", "The second build failed a new check."),
    (13.5, "STOP", "Stopped\non request.", "The timeline keeps the partial result."),
)


def ease(value):
    x = min(1, max(0, value))
    return x * x * (3 - 2 * x)


def make_background():
    pixels = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            light = exp(-((x - 950) / 480) ** 2 - ((y - 338) / 350) ** 2)
            grain = ((x * 179 + y * 103) ^ (x * y)) % 3
            pixels.extend((10 + int(13 * light) + grain,
                           16 + int(15 * light) + grain,
                           32 + int(29 * light) + grain))

    image = Image.frombytes("RGB", (WIDTH, HEIGHT), bytes(pixels))
    draw = ImageDraw.Draw(image)
    for y in range(106, 602, 42):
        for x in range(684, 1212, 42):
            draw.point((x, y), fill="#687192")
    draw.line((64, 89, 1216, 89), fill=HAIRLINE)
    draw.line((64, 628, 1216, 628), fill=HAIRLINE)
    draw.text((64, 53), "SUPER AGENT  /  FIELD RECORDING", font=SMALL, fill=MUTED, anchor="lm")
    draw.text((1216, 53), "SIMULATED RUN", font=SMALL, fill=ACCENT, anchor="rm")
    return image


def render_signal(draw, t):
    x, y = 914, 350
    for radius in (63, 111, 159, 207):
        box = (x - radius, y - radius, x + radius, y + radius)
        draw.ellipse(box, outline=HAIRLINE)
        for start in (35, 145, 225, 315):
            draw.arc(box, start, start + 8, fill="#74719d", width=2)

    for index in range(88):
        angle = index * 2 * pi / 88
        inner = 216
        outer = 225 if index % 11 == 0 else 220
        draw.line((x + cos(angle) * inner, y + sin(angle) * inner,
                   x + cos(angle) * outer, y + sin(angle) * outer),
                  fill=MUTED if index % 11 == 0 else HAIRLINE)

    scan = 17 + t * 34
    draw.arc((x - 207, y - 207, x + 207, y + 207), scan, scan + 36, fill=ACCENT, width=3)
    draw.line((x - 237, y, x + 237, y), fill="#5a6087")
    for index in range(73):
        position = (index - 36) / 36
        amplitude = exp(-position ** 2 * 3.9) * (0.65 + 0.35 * sin(t * 4.4 + index / 12))
        size = 4 + 69 * amplitude * abs(sin(index * 0.43 + t * 7))
        px = x + (index - 36) * 5
        draw.line((px, y - size, px, y + size), fill=ACCENT if size > 13 else "#656592", width=2)

    draw.text((1195, 591), "VOICE SIGNAL  /  EXAMPLE", font=SMALL, fill=MUTED, anchor="rm")


def render_ledger(draw, chapter, t):
    x, right = 652, 1216
    draw.rounded_rectangle((x, 172, right, 531), radius=18, fill="#131a2e", outline="#4c5376")
    draw.line((x, 226, right, 226), fill=HAIRLINE)
    draw.text((x + 26, 199), "JOB 01  /  BUILD COMPARISON", font=SMALL, fill=PAPER, anchor="lm")
    state = ("SCOPED", "RESULT", "STOPPED")[chapter - 1]
    draw.text((right - 26, 199), state, font=SMALL, fill=ACCENT, anchor="rm")

    if chapter == 1:
        rows = (("01", "Build report A", "READ ONLY"),
                ("02", "Build report B", "READ ONLY"),
                ("—", "Write access", "NONE"))
    elif chapter == 2:
        rows = (("01", "Build report A", "PASS"),
                ("02", "Build report B", "1 NEW FAILURE"),
                ("↳", "Cache integrity check", "FAILED"))
    else:
        rows = (("01", "Open two example reports", "LOGGED"),
                ("02", "Find new failure", "LOGGED"),
                ("03", "Stop job", "STOPPED"))

    for index, (number, label, status) in enumerate(rows):
        front = ease((t - index * 0.22 - 0.18) * 2.5)
        if not front:
            continue
        y = 288 + index * 82 + 13 * (1 - front)
        selected = index == 1 and chapter == 2 or index == 2 and chapter == 3
        draw.rounded_rectangle((x + 16, y - 29, right - 16, y + 29), radius=9,
                               fill="#232750" if selected else "#181f36",
                               outline="#53598d" if selected else "#252d47")
        draw.text((x + 34, y), number, font=SMALL, fill=ACCENT, anchor="lm")
        draw.text((x + 83, y), label, font=BODY, fill=PAPER, anchor="lm")
        draw.text((right - 31, y), status, font=SMALL,
                  fill=ACCENT if selected else MUTED, anchor="rm")

    draw.text((1195, 591), "REPORTS  /  EXAMPLE DATA", font=SMALL, fill=MUTED, anchor="rm")


def render(background, time):
    chapter = min(int(time / 4.5), len(CHAPTERS) - 1)
    start, name, title, body = CHAPTERS[chapter]
    t = time - start
    frame = background.copy()
    overlay = background.copy()
    draw = ImageDraw.Draw(overlay)
    offset = round(20 * (1 - ease(t / 0.55)))
    y = 244 + offset
    draw.text((64, y), f"0{chapter + 1}  /  {name}", font=MONO, fill=ACCENT, anchor="lm")
    for index, line in enumerate(title.splitlines()):
        draw.text((61, y + 36 + index * 71), line, font=TITLE, fill=PAPER, anchor="lt")
    draw.text((64, y + 194), body, font=BODY, fill=MUTED, anchor="lm")
    if chapter:
        render_ledger(draw, chapter, t)
    else:
        render_signal(draw, t)

    enter = ease((t + (0.32 if chapter == 0 else 0.04)) / 0.5)
    leave = ease((4.5 - t) / 0.36) if chapter < 3 else 1
    frame = Image.blend(frame, overlay, enter * leave)
    draw = ImageDraw.Draw(frame)
    for index in range(4):
        x = 64 + index * 85
        fill = 71 * min(1, max(0, (time - index * 4.5) / 4.5))
        draw.line((x, 671, x + 71, 671), width=2, fill=HAIRLINE)
        if fill:
            draw.line((x, 671, x + fill, 671), width=2, fill=ACCENT)
    draw.text((1216, 670), f"00:{int(time):02d}  /  00:18", font=MONO, fill=MUTED, anchor="rm")
    return frame


def main():
    OUTPUT.mkdir(exist_ok=True)
    background = make_background()
    render(background, 2).save(OUTPUT / "film-poster.webp", quality=88)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
        "-pixel_format", "rgb24", "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate",
        str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "21",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-map_metadata", "-1",
        str(OUTPUT / "film.mp4"),
    ]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as encoder:
        try:
            for frame in range(18 * FPS):
                encoder.stdin.write(render(background, frame / FPS).tobytes())
        finally:
            encoder.stdin.close()
        if encoder.wait():
            raise SystemExit("FFmpeg could not encode the film.")


if __name__ == "__main__":
    main()
