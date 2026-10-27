"""Bounded native reminder cards matching the workspace and result-preview layout.

Only trusted bundled SVGs and fonts are read. Context is plain text; URLs and
HTML are never interpreted. The endpoint owns capability/auth and cache policy.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from functools import lru_cache
from io import BytesIO
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from babel.core import UnknownLocaleError
from babel.dates import format_date, format_datetime
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

ASSETS = Path(__file__).with_name("reminder_preview_assets")
FONTS = Path(__file__).with_name("fonts")
WIDTH, HEIGHT = 600, 400  # WorkspaceContinueCard: 300x200 CSS pixels at 2x.
MAX_IMAGE_BYTES = 128 * 1024
MAX_IMAGE_PIXELS = 4_000_000
MAX_OUTPUT_BYTES = 1_000_000
MAX_CONTEXT_BYTES = 256 * 1024


def _text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


@lru_cache(maxsize=1)
def _assets() -> dict:
    return json.loads((ASSETS / "cards.json").read_text())


@lru_cache(maxsize=16)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"LexendDeca-{'Bold' if bold else 'Regular'}.ttf"), size)


def _locale(language: str) -> str:
    candidate = _text(language, 20).replace("-", "_")
    try:
        format_date(datetime(2026, 1, 1), locale=candidate)
        return candidate
    except (ValueError, LookupError, UnknownLocaleError):
        return "en"


def reminder_local_datetime(context: dict, key: str = "starts_at") -> datetime | None:
    """Use the captured timezone, never the server's local timezone."""
    raw = _text(context.get(key), 80)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        zone = ZoneInfo(_text(context.get("timezone"), 100) or "UTC")
        return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)
    except (ValueError, ZoneInfoNotFoundError):
        return None


def reminder_datetime_label(context: dict, language: str = "en") -> str:
    """Accessible real-text date/time, including zone and an optional end."""
    start = reminder_local_datetime(context)
    if start is None:
        return ""
    locale = _locale(language)
    result = format_datetime(start, "EEE, d MMM y · HH:mm z", locale=locale)
    end = reminder_local_datetime(context, "ends_at")
    if end is not None:
        pattern = "HH:mm z" if end.date() == start.date() else "EEE, d MMM y · HH:mm z"
        result += " – " + format_datetime(end, pattern, locale=locale)
    return result


def _thumbnail(value: object) -> Image.Image | None:
    if not value:
        return None
    if not isinstance(value, str) or len(value) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError("Invalid reminder thumbnail")
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Invalid reminder thumbnail")
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG"} or source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Invalid reminder thumbnail")
            source.load()
            return source.convert("RGBA")
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("Invalid reminder thumbnail") from None


@lru_cache(maxsize=128)
def _glyph(name: str, size: int, app_icon: bool = False) -> Image.Image:
    # name only indexes a trusted, finite map. Never pass context SVG to CairoSVG.
    import cairosvg

    icons = _assets()["app_icons" if app_icon else "icons"]
    svg = icons.get(name) or _assets()["icons"].get("help-circle") or _assets()["icons"]["message-circle"]
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
    with Image.open(BytesIO(png)) as source:
        return source.convert("RGBA")


def _lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int, count: int) -> list[str]:
    """Wrap even unbroken Unicode strings with a finite amount of work."""
    result, line = [], ""
    truncated = False
    tokens = re.findall(r"\S+|\n", text)
    for token in tokens:
        if token == "\n":
            result.append(line)
            line = ""
        elif draw.textlength((line + " " + token).strip(), font=font) <= width:
            line = (line + " " + token).strip()
            continue
        elif line:
            result.append(line)
            line = token
        else:
            line = token
        # Split exceptional long unbroken identifiers; ordinary words stay whole.
        while draw.textlength(line, font=font) > width and len(result) < count:
            cut = 1
            while cut < len(line) and draw.textlength(line[:cut + 1], font=font) <= width:
                cut += 1
            result.append(line[:cut])
            line = line[cut:]
        if len(result) >= count:
            truncated = True
            break
    if line and len(result) < count:
        result.append(line)
    if truncated:
        line = result[count - 1]
        while line and draw.textlength(line + "…", font=font) > width:
            line = line[:-1]
        result[count - 1] = line + "…"
    return result[:count]


def _paragraph(image: Image.Image, text: str, *, x: int, y: int, width: int, size: int,
               lines: int, color: str, bold: bool = False, center: bool = False) -> int:
    draw = ImageDraw.Draw(image)
    font = _font(size, bold)
    line_height = round(size * 1.3)
    for line in _lines(draw, text, font, width, lines):
        left = x + (width - draw.textlength(line, font=font)) / 2 if center else x
        draw.text((left, y), line, font=font, fill=color, anchor="lt")
        y += line_height
    return y


def _gradient(colors: dict) -> Image.Image:
    # CSS linear-gradient(135deg) on a 300x200 rectangle.
    start, end = (ImageColor.getrgb(colors[key]) for key in ("start", "end"))
    image = Image.new("RGBA", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    # Each diagonal shares a gradient value; 999 native line fills replace a
    # Python loop over every pixel, keeping capability responses inexpensive.
    for diagonal in range(WIDTH + HEIGHT - 1):
        t = diagonal / (WIDTH + HEIGHT - 2)
        color = tuple(round(a + (b - a) * t) for a, b in zip(start, end))
        left = max(0, diagonal - HEIGHT + 1)
        right = min(WIDTH - 1, diagonal)
        draw.line((left, diagonal - left, right, diagonal - right), fill=(*color, 255))
    return image


def _chat(context: dict) -> Image.Image:
    assets = _assets()
    category, app_id = _text(context.get("category"), 80), _text(context.get("app_id"), 80)
    colors = assets["apps"].get(app_id) if app_id else assets["categories"].get(category)
    image = _gradient(colors or {"start": "#4867cd", "end": "#a0beff"})
    # Chat metadata can contain a Lucide export name (Train/CalendarDays) or
    # the persisted kebab-case name. Resolve both against the bundled map.
    icon = re.sub(r"(?<!^)(?=[A-Z])", "-", _text(context.get("icon"), 80)).lower()
    app_icon = bool(app_id in assets["app_icons"] and icon in {"app", "skill"})
    icon = app_id if app_icon else icon if icon in assets["icons"] else assets["fallbacks"].get(category, "help-circle")
    for x, angle in ((-20, 15), (WIDTH - 140, -15)):
        deco = _glyph(icon, 160, app_icon).copy().rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        deco.putalpha(deco.getchannel("A").point(lambda v: round(v * .3)))
        image.alpha_composite(deco, (x - 18, HEIGHT - 150))
    draw = ImageDraw.Draw(image)
    title = _text(context.get("title"), 200)
    summary = _text(context.get("summary"), 500)
    title_lines = _lines(draw, title, _font(32, True), 472, 2)
    summary_lines = _lines(draw, summary, _font(24), 472, 4)
    total = 64 + 4 + len(title_lines) * 42 + (8 + len(summary_lines) * 32 if summary_lines else 0)
    y = max(16, (HEIGHT - total) // 2)
    image.alpha_composite(_glyph(icon, 64, app_icon), ((WIDTH - 64) // 2, y))
    y = _paragraph(image, title, x=64, y=y + 68, width=472, size=32, lines=2, color="white", bold=True, center=True)
    if summary:
        _paragraph(image, summary, x=64, y=y + 8, width=472, size=24, lines=4, color="#e6edff", center=True)
    return image


def _embed(context: dict, darkmode: bool, language: str, thumbnail: Image.Image | None) -> Image.Image:
    background, foreground, secondary = ("#171717", "#e6e6e6", "#cfcfcf") if darkmode else ("#ffffff", "#000000", "#6b6b6b")
    image = Image.new("RGBA", (WIDTH, HEIGHT), background)
    title = _text(context.get("title"), 200)
    draw = ImageDraw.Draw(image)
    title_lines = _lines(draw, title, _font(32, True), 408, 2)
    copy_y = HEIGHT - 20 - len(title_lines) * 42 - 40 if thumbnail else 104
    if thumbnail:
        media_height = max(150, copy_y - 8)
        media = ImageOps.contain(thumbnail, (WIDTH, media_height), Image.Resampling.LANCZOS)
        image.paste(media, ((WIDTH - media.width) // 2, (media_height - media.height) // 2), media)
        # Same bottom media fade as ResultEmbedCard.
        fade = Image.new("RGBA", (WIDTH, 40))
        fade_draw = ImageDraw.Draw(fade)
        rgb = ImageColor.getrgb(background)
        for y in range(40):
            fade_draw.line((0, y, WIDTH, y), fill=(*rgb, round(255 * y / 39)))
        image.alpha_composite(fade, (0, media_height - 40))
    app_id = _text(context.get("app_id"), 80) or ("calendar" if context.get("kind") == "appointment" else "events")
    colors = _assets()["apps"].get(app_id, _assets()["apps"]["events"])
    corner_mask = Image.new("L", (88, 88))
    ImageDraw.Draw(corner_mask).rounded_rectangle((0, 0, 88, 88), radius=44, fill=255)
    ImageDraw.Draw(corner_mask).rectangle((0, 0, 88, 44), fill=255)
    ImageDraw.Draw(corner_mask).rectangle((0, 0, 44, 88), fill=255)
    corner = _gradient(colors).resize((88, 88))
    corner.putalpha(corner_mask)
    image.alpha_composite(corner, (0, 0))
    image.alpha_composite(_glyph(app_id, 42, True), (23, 23))
    start = reminder_local_datetime(context)
    if start is not None:
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((108, 12, 184, 92), radius=20, fill=background)
        weekday = format_date(start, "EEE", locale=_locale(language))
        _paragraph(image, weekday, x=108, y=18, width=76, size=20, lines=1, color="#e74c3c", center=True)
        _paragraph(image, str(start.day), x=108, y=40, width=76, size=52, lines=1, color=foreground, center=True)
    y = _paragraph(image, title, x=96, y=copy_y, width=408, size=32, lines=2, color=foreground, bold=True)
    facts = context.get("facts") if isinstance(context.get("facts"), list) else []
    provider = next((_text(f.get("value"), 160) for f in facts[:8] if isinstance(f, dict) and _text(f.get("label"), 80).lower() in {"organizer", "provider", "by"}), "")
    time = start.strftime("%H:%M") if start else ""
    attribution = ", ".join(filter(None, (time, provider)))
    if attribution:
        y = _paragraph(image, attribution, x=96, y=y + 6, width=408, size=24, lines=1, color=secondary)
    if not thumbnail:
        description = _text(context.get("description"), 2000) or _text(context.get("summary"), 500)
        if description:
            _paragraph(image, description, x=96, y=y + 8, width=408, size=26, lines=max(1, min(3, (HEIGHT - y - 28) // 34)), color=secondary)
    return image


def render_reminder_preview(context: dict, *, darkmode: bool = False, language: str = "en") -> bytes:
    """Return a 600x400 PNG without network, browser, HTML or private logging.

    Invalid/oversized input raises a content-free ValueError. Optional thumbnails
    must be raw base64 PNG/JPEG; URL strings, SVG and decompression bombs fail.
    """
    if not isinstance(context, dict) or len(context) > 24:
        raise ValueError("Invalid reminder context")
    # Bound structure before serialization, image decoding or text shaping.
    for key, value in context.items():
        if not isinstance(key, str) or len(key) > 80:
            raise ValueError("Invalid reminder context")
        if isinstance(value, str):
            if len(value) > MAX_CONTEXT_BYTES:
                raise ValueError("Reminder context exceeds limit")
        elif key == "facts" and isinstance(value, list):
            if len(value) > 8 or any(not isinstance(f, dict) or len(f) > 2 or
                any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 512
                    for k, v in f.items()) for f in value):
                raise ValueError("Invalid reminder facts")
        elif value is not None and not isinstance(value, (int, float, bool)):
            raise ValueError("Invalid reminder context")
    try:
        size = len(json.dumps(context, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Invalid reminder context") from None
    if size > MAX_CONTEXT_BYTES:
        raise ValueError("Reminder context exceeds limit")
    thumbnail = _thumbnail(context.get("image_base64"))
    image = _chat(context) if context.get("kind") == "chat" else _embed(context, darkmode, language, thumbnail)
    mask = Image.new("L", image.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, WIDTH - 1, HEIGHT - 1), radius=60, fill=255)
    image.putalpha(mask)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    data = output.getvalue()
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("Reminder preview exceeds limit")
    return data
