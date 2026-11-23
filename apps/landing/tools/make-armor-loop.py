"""Render a seamless armor material study as a poster and small, silent loop."""

from pathlib import Path
import math
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter

WIDTH, HEIGHT = 960, 540
FPS, SECONDS = 24, 6
OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("apps/landing/media")


def smooth(start, end, values):
    x = np.clip((values - start) / (end - start), 0, 1)
    return x * x * (3 - 2 * x)


def gaussian(values, center, width):
    return np.exp(-((values - center) / width) ** 2)


def plate_surface():
    y, x = np.indices((HEIGHT, WIDTH), dtype=np.float32)
    # Rotate the concentric plate edges around the mounting point.
    a = math.radians(-32)
    dx, dy = (x - 928), (y - 559)
    u = (dx * math.cos(a) + dy * math.sin(a)) / 760
    v = (dy * math.cos(a) - dx * math.sin(a)) / 372
    radius = np.hypot(u, v)
    around = np.arctan2(v, u)
    rng = np.random.default_rng(26)

    grit = rng.normal(0, 1, radius.shape).astype(np.float32)
    # Radial sampling of a fixed noise table gives the brushed metal direction.
    lines = rng.normal(0, 1, 2048).astype(np.float32)
    brushed = np.interp(radius * 530, np.arange(len(lines)), lines).astype(np.float32)
    brushed *= .70 + .26 * np.sin(around * 13)
    pitting = np.where(grit > 2.5, grit * .80, 0)

    base = 3.6 + 6.2 * gaussian(x, 918, 495) + grit * .37
    hue = np.zeros_like(base)
    specular = np.zeros_like(base)

    # Graphite plates are separated by narrow channels and folded metal lips.
    for outer, inner, tone, warmth in [
        (1.19, 1.58, 13, .20),
        (1.02, 1.175, 24, .30),
        (.873, 1.007, 31, .37),
        (.794, .863, 27, .98),
        (.655, .782, 28, .31),
        (.508, .642, 21, .20),
        (.398, .493, 15, .19),
        (.07, .388, 11, .18),
    ]:
        t = (radius - outer) / (inner - outer)
        cover = smooth(0, .020, t) * (1 - smooth(.993, 1.009, t))
        slope = gaussian(t, .36, .53)
        lip = 1.12 * gaussian(t, .946, .014) + .56 * gaussian(t, .047, .031)
        shadow = gaussian(t, .875, .056)
        machining = (brushed * 1.65 + grit * .80 + pitting) * (1 + .28 * slope)
        shade = tone * (.51 + slope * .75) + 21 * lip - 12 * shadow + machining
        base = base * (1 - cover) + shade * cover
        hue = np.maximum(hue, warmth * cover)
        specular = np.maximum(specular, cover * (lip + .22 * slope * (1 - shadow)))

    # The inset fasteners are milled into the broadest titanium plate.
    for cx, cy, scale in [(840, 206, 1.0), (695, 292, .91), (565, 394, .81)]:
        bx, by = (x - cx) / (18 * scale), (y - cy) / (12 * scale)
        screw_u = bx * .83 - by * .56
        screw_v = by * .83 + bx * .56
        screw_r = np.hypot(screw_u, screw_v)
        screw_a = np.arctan2(screw_v, screw_u)
        well = 1 - smooth(.81, .98, screw_r)
        bevel = gaussian(screw_r, .91, .05) * (.59 + .41 * np.cos(screw_a + 2))
        socket = screw_r * np.cos(np.mod(screw_a, math.pi / 3) - math.pi / 6)
        hole = 1 - smooth(.35, .48, socket)
        base = base * (1 - well * .67) + bevel * 38 - well * hole * 8
        specular += bevel * .6

    # Studio lighting falls away to leave clean space for the overlay copy.
    focus = .30 + .70 * smooth(260, 830, x)
    focus *= .74 + .26 * gaussian(y, 288, 280)
    falloff = smooth(230, 728, x + .38 * y) * .98 + .02
    return x, y, around, base, hue, specular, focus, falloff


def render(surface, phase):
    x, y, around, base, hue, specular, focus, falloff = surface
    sweep = -1.52 + .08 * math.cos(phase) + .31 * math.sin(phase)
    reflection = gaussian(around, sweep, .18)
    ambient = gaussian(around, -1.29, .60)
    bloom = gaussian(x, 807 - 80 * math.sin(phase), 274) * gaussian(y, 223, 229)
    intensity = (base * (.65 + .31 * ambient) + specular * (124 * reflection + 41 * ambient)) * focus
    intensity = (intensity + bloom * 8.8) * falloff + 4.8
    rust = hue * (.12 + .76 * bloom + .27 * reflection) * falloff
    rgb = np.stack((intensity + 27 * rust, intensity + 9 * rust, intensity - 3 * rust), axis=-1)
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    # A soft falloff on the far edge suggests a close-focus lens.
    soft = image.filter(ImageFilter.GaussianBlur(1.35))
    mask = Image.fromarray(np.uint8(160 * (1 - smooth(435, 874, x))))
    return Image.composite(soft, image, mask)


def main():
    OUTPUT.mkdir(exist_ok=True, parents=True)
    surface = plate_surface()
    poster = render(surface, 0)
    poster.save(OUTPUT / "armor-loop.webp", "WEBP", quality=86)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-map_metadata", "-1",
        str(OUTPUT / "armor-loop.mp4"),
    ]
    count = FPS * SECONDS
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as encoder:
        try:
            for frame in range(count):
                image = render(surface, math.tau * frame / count)
                encoder.stdin.write(image.tobytes())
        finally:
            encoder.stdin.close()
        if encoder.wait():
            raise SystemExit("FFmpeg could not encode the loop.")


if __name__ == "__main__":
    main()
