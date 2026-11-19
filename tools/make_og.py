"""Render the static social card (assets/og.png, 1200x630). Run once; not part of the daily job.

Usage: uv run --with pillow python tools/make_og.py --font path/to/SpaceGrotesk[wght].ttf
(Space Grotesk: https://fonts.google.com/specimen/Space+Grotesk, OFL)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 630
SS = 2  # supersample for smooth edges
BG = (18, 18, 17)
TEXT = (240, 239, 236)
TEXT2 = (195, 194, 183)
MUTED = (143, 142, 135)
BLUE = (57, 135, 229)
VIOLET = (122, 92, 240)
UP = (63, 185, 80)
OUT = Path(__file__).resolve().parent.parent / "assets" / "og.png"


def font(path: str, size: int, weight: str) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size * SS)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def gradient(w: int, h: int, a: tuple, b: tuple) -> Image.Image:
    g = Image.new("RGB", (w, h))
    px = g.load()
    for x in range(w):
        t = x / max(1, w - 1)
        c = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
        for y in range(h):
            px[x, y] = c
    return g


def gradient_text(img: Image.Image, xy: tuple, text: str, f, a, b) -> None:
    d = ImageDraw.Draw(img)
    l, t, r, btm = d.textbbox(xy, text, font=f)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=f, fill=255)
    grad = gradient(r - l, btm - t, a, b)
    layer = Image.new("RGB", img.size)
    layer.paste(grad, (l, t))
    img.paste(layer, (0, 0), mask)


def main(font_path: str) -> None:
    s = SS
    img = Image.new("RGB", (W * s, H * s), BG)

    # soft glow behind the chart
    glow = Image.new("RGB", img.size, BG)
    ImageDraw.Draw(glow).ellipse((760 * s, 120 * s, 1300 * s, 700 * s), fill=(28, 44, 78))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(120 * s)), 1.0)
    d = ImageDraw.Draw(img)

    # rising chart motif (right side)
    pts = [(790, 525), (840, 508), (890, 514), (940, 462), (990, 474), (1045, 385), (1095, 334), (1150, 205)]
    sp = [(x * s, y * s) for x, y in pts]
    area = Image.new("L", img.size, 0)
    ImageDraw.Draw(area).polygon(sp + [(1150 * s, 630 * s), (790 * s, 630 * s)], fill=46)
    img.paste(Image.new("RGB", img.size, BLUE), (0, 0), area)
    d = ImageDraw.Draw(img)
    d.line(sp, fill=BLUE, width=7 * s, joint="curve")
    ex, ey = sp[-1]
    d.ellipse((ex - 13 * s, ey - 13 * s, ex + 13 * s, ey + 13 * s), fill=BLUE, outline=BG, width=5 * s)
    # delta pill near the peak
    pill_f = font(font_path, 30, "Bold")
    label = "+2,481"
    lw = d.textlength(label, font=pill_f)
    tri = 18 * s
    pw = 18 * s + tri + 10 * s + lw + 20 * s
    px, py = 1150 * s - pw + 14 * s, 128 * s
    d.rounded_rectangle((px, py, px + pw, py + 54 * s), radius=27 * s, fill=(22, 52, 30))
    tx, ty = px + 18 * s, py + 27 * s
    d.polygon([(tx, ty + tri * 0.45), (tx + tri, ty + tri * 0.45), (tx + tri / 2, ty - tri * 0.5)], fill=UP)
    d.text((tx + tri + 10 * s, py + 9 * s), label, font=pill_f, fill=UP)

    # brand mark
    x0, y0 = 72 * s, 72 * s
    d.rounded_rectangle((x0, y0, x0 + 52 * s, y0 + 52 * s), radius=13 * s, fill=BLUE)
    d.line([(x0 + 12 * s, y0 + 36 * s), (x0 + 22 * s, y0 + 26 * s), (x0 + 29 * s, y0 + 33 * s), (x0 + 41 * s, y0 + 18 * s)],
           fill=(255, 255, 255), width=5 * s, joint="curve")
    d.text((x0 + 70 * s, y0 + 6 * s), "Agent Trending", font=font(font_path, 32, "Bold"), fill=TEXT)

    # headline
    h_f = font(font_path, 74, "Bold")
    d.text((72 * s, 210 * s), "What's rising in the", font=h_f, fill=TEXT)
    gradient_text(img, (72 * s, 295 * s), "AI agent ecosystem", h_f, BLUE, VIOLET)
    d = ImageDraw.Draw(img)

    sub_f = font(font_path, 28, "Medium")
    d.text((72 * s, 410 * s), "Repos · MCP servers · Skills · Plugins", font=sub_f, fill=TEXT2)
    d.text((72 * s, 452 * s), "ranked by 7-day GitHub star growth", font=sub_f, fill=TEXT2)

    foot_f = font(font_path, 24, "Medium")
    d.text((72 * s, 548 * s), "mit2400.github.io/agent-trending", font=foot_f, fill=MUTED)
    d.text((520 * s, 548 * s), "·  updated daily", font=foot_f, fill=MUTED)

    img.resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    main(ap.parse_args().font)
