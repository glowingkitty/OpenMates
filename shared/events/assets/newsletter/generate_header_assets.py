#!/usr/bin/env python3
"""Generate OpenMates events newsletter header assets.

The design source is local JSON, not Figma. The script always writes SVG files
that match the approved red gradient newsletter direction, and it can also write
PNG files when cairosvg is installed in the export environment. This keeps the
email header reproducible and reviewable in the repository.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DESIGN_PATH = HERE / "header_design.json"


def _load_design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _svg(design: dict[str, Any], language: str) -> str:
    canvas = design["canvas"]
    colors = design["colors"]
    text = design["text"][language]
    width = int(canvas["width"])
    height = int(canvas["height"])
    radius = int(canvas["corner_radius"])
    title = html.escape(text["title"])
    subtitle = html.escape(text["subtitle"])
    eyebrow = html.escape(text["eyebrow"])

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{colors['background_start']}"/>
      <stop offset="48%" stop-color="{colors['background_mid']}"/>
      <stop offset="100%" stop-color="{colors['background_end']}"/>
    </linearGradient>
    <radialGradient id="glow" cx="48%" cy="42%" r="70%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.38"/>
      <stop offset="55%" stop-color="#ffffff" stop-opacity="0.08"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
    </radialGradient>
    <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="10" stdDeviation="18" flood-color="#681227" flood-opacity="0.28"/>
    </filter>
  </defs>
  <rect width="{width}" height="{height}" rx="{radius}" fill="url(#bg)"/>
  <rect width="{width}" height="{height}" rx="{radius}" fill="url(#glow)"/>
  <circle cx="585" cy="58" r="112" fill="#fff0df" opacity="0.18"/>
  <circle cx="74" cy="248" r="128" fill="#681227" opacity="0.24"/>
  <path d="M448 42c58 34 98 82 118 142 10 31-13 62-46 62H276c-35 0-58-36-42-67 32-62 82-108 150-139 20-9 45-8 64 2Z" fill="#fff0df" opacity="0.18"/>
  <g filter="url(#softShadow)">
    <rect x="52" y="54" width="176" height="176" rx="42" fill="#fff0df" opacity="0.96"/>
    <circle cx="118" cy="119" r="23" fill="{colors['background_start']}"/>
    <circle cx="164" cy="119" r="23" fill="{colors['background_mid']}"/>
    <circle cx="141" cy="166" r="23" fill="{colors['background_end']}"/>
    <path d="M118 119l46 0-23 47Z" fill="none" stroke="{colors['dark_red']}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" opacity="0.72"/>
  </g>
  <text x="260" y="82" font-family="Lexend Deca, Arial, Helvetica, sans-serif" font-size="18" font-weight="800" letter-spacing="2.2" fill="{colors['pink']}">{eyebrow}</text>
  <text x="260" y="142" font-family="Lexend Deca, Arial, Helvetica, sans-serif" font-size="42" font-weight="800" fill="#ffffff">{title}</text>
  <foreignObject x="260" y="166" width="350" height="86">
    <div xmlns="http://www.w3.org/1999/xhtml" style="font-family: Lexend Deca, Arial, Helvetica, sans-serif; font-size: 21px; font-weight: 600; line-height: 1.28; color: #fff0df;">{subtitle}</div>
  </foreignObject>
  <path d="M260 244h258" stroke="#fff0df" stroke-width="3" stroke-linecap="round" opacity="0.58"/>
</svg>
'''


def _write_png(svg_path: Path, png_path: Path) -> None:
    design = _load_design()
    try:
        _write_png_with_pillow(design, png_path)
        return
    except ImportError:
        pass

    try:
        import cairosvg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("PNG export requires Pillow or cairosvg; SVG files were still generated") from exc
    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path))


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (_lerp(a[0], b[0], t), _lerp(a[1], b[1], t), _lerp(a[2], b[2], t))


def _rounded_mask(width: int, height: int, radius: int):
    from PIL import Image, ImageDraw

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
    return mask


def _write_wrapped(draw: Any, xy: tuple[int, int], text: str, font: Any, fill: str, *, max_width: int, line_gap: int) -> None:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)

    x, y = xy
    line_height = font.size + line_gap
    for index, line in enumerate(lines):
        draw.text((x, y + index * line_height), line, font=font, fill=fill)


def _write_png_with_pillow(design: dict[str, Any], png_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    canvas = design["canvas"]
    colors = design["colors"]
    width = int(canvas["width"])
    height = int(canvas["height"])
    radius = int(canvas["corner_radius"])
    lang = "de" if png_path.name.endswith("_de.png") else "en"
    text = design["text"][lang]

    start = _hex_to_rgb(colors["background_start"])
    mid = _hex_to_rgb(colors["background_mid"])
    end = _hex_to_rgb(colors["background_end"])
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            t = (x / width * 0.68) + (y / height * 0.32)
            base = _blend(start, mid, t / 0.48) if t < 0.48 else _blend(mid, end, (t - 0.48) / 0.52)
            glow_dx = (x - width * 0.48) / width
            glow_dy = (y - height * 0.42) / height
            glow = max(0.0, 1.0 - math.sqrt(glow_dx * glow_dx + glow_dy * glow_dy) / 0.7)
            pixels[x, y] = (*_blend(base, (255, 255, 255), glow * 0.24), 255)
    image.putalpha(_rounded_mask(width, height, radius))

    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((473, -54, 697, 170), fill=(255, 240, 223, 46))
    draw.ellipse((-54, 120, 202, 376), fill=(104, 18, 39, 61))
    draw.polygon([(384, 40), (542, 110), (518, 246), (286, 246), (232, 182)], fill=(255, 240, 223, 36))

    icon_shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(icon_shadow)
    shadow_draw.rounded_rectangle((52, 54, 228, 230), radius=42, fill=(104, 18, 39, 80))
    icon_shadow = icon_shadow.filter(ImageFilter.GaussianBlur(14))
    image.alpha_composite(icon_shadow)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((52, 54, 228, 230), radius=42, fill=(255, 240, 223, 245))
    draw.ellipse((95, 96, 141, 142), fill=(*start, 255))
    draw.ellipse((141, 96, 187, 142), fill=(*mid, 255))
    draw.ellipse((118, 143, 164, 189), fill=(*end, 255))
    draw.line((118, 119, 164, 119, 141, 166, 118, 119), fill=(*_hex_to_rgb(colors["dark_red"]), 184), width=10, joint="curve")

    eyebrow_font = _font(18, bold=True)
    title_font = _font(40, bold=True)
    subtitle_font = _font(21, bold=True)
    draw.text((260, 64), text["eyebrow"], font=eyebrow_font, fill=colors["pink"])
    draw.text((260, 108), text["title"], font=title_font, fill="#ffffff")
    _write_wrapped(draw, (260, 162), text["subtitle"], subtitle_font, colors["cream"], max_width=350, line_gap=6)
    draw.line((260, 244, 518, 244), fill=(255, 240, 223, 148), width=3)

    rgb = Image.new("RGB", image.size, "white")
    rgb.paste(image, mask=image.getchannel("A"))
    rgb.save(png_path, format="PNG", optimize=True)


def generate(*, png: bool) -> list[Path]:
    design = _load_design()
    written: list[Path] = []
    for language, filename in design["output"]["svg"].items():
        svg_path = HERE / filename
        svg_path.write_text(_svg(design, language), encoding="utf-8")
        written.append(svg_path)
        if png:
            png_path = HERE / design["output"]["png"][language]
            _write_png(svg_path, png_path)
            written.append(png_path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OpenMates events newsletter header assets")
    parser.add_argument("--png", action="store_true", help="Also export PNG files using cairosvg")
    args = parser.parse_args()
    try:
        written = generate(png=args.png)
    except RuntimeError as exc:
        print(str(exc))
        return 2
    for path in written:
        print(path.relative_to(HERE.parent.parent.parent.parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
