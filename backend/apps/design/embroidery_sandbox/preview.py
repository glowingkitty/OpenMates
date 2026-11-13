"""Turn Ink/Stitch's realistic stitch render into the delivered previews (Pillow, numpy).

The same render, cut free from its page, is delivered as a transparent PNG.

Ink/Stitch darkens and saturates light thread colours in its render so they stay
visible on a white page: cream thread comes out yellow and white thread grey.
The delivered preview must show the thread colours of the delivered files, so
the areas sewn with a light thread are brought back to their real colour. The
areas come from the stitch data itself; the render's stitch texture is kept.
"""

from __future__ import annotations

import colorsys
import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

MAX_PREVIEW_PX = 1200
# Longest side of the transparent PNG preview (for placing the design on other pictures).
MAX_TRANSPARENT_PX = 1600
# Ink/Stitch renders on the opaque page colour (FABRIC_RGB). For the transparent preview
# a pixel this close to it (largest channel difference) is page, this far is thread.
PAGE_TOLERANCE = 6.0
OPAQUE_DISTANCE = 48.0
FABRIC_RGB = (244, 241, 234)
WEBP_QUALITY = 72
# Ink/Stitch alters thread colours above this HLS lightness in its render.
LIGHT_THREAD_LIGHTNESS = 0.85
# Mean brightness of a corrected area relative to the thread colour.
CORRECTED_SHADE = 0.94
# Width painted per stitch line when marking a thread's area, in millimetres.
AREA_LINE_MM = 0.7
TENTHS_PER_INCH = 254.0
# Darkest shading kept inside a corrected area, relative to the thread colour.
MIN_SHADE = 0.6
LUMA = np.asarray((0.299, 0.587, 0.114), dtype=np.float32)

def render_dpi(width_mm: float, height_mm: float) -> int:
    """DPI at which the longer side renders at about MAX_PREVIEW_PX pixels."""
    longest_inches = max(width_mm, height_mm, 1.0) / 25.4
    return max(30, min(600, int(MAX_PREVIEW_PX / longest_inches)))

def _rgb(colour_hex: str) -> tuple[int, int, int]:
    value = colour_hex.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

def is_light_thread(colour_hex: str) -> bool:
    """True for thread colours Ink/Stitch does not render in their own colour."""
    red, green, blue = _rgb(colour_hex)
    return colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)[1] > LIGHT_THREAD_LIGHTNESS

def _thread_areas(size: tuple[int, int], stitches: dict[str, object], dpi: int) -> np.ndarray:
    """Per pixel, 1 + index of the colour block sewn last at that place (0 = no stitches).

    The render is the stitch extent centred in the image, at ``dpi``.
    """
    blocks = stitches["blocks"]
    scale = dpi / TENTHS_PER_INCH
    points = [point for block in blocks for point in block["points"] if point is not None]
    extent_x = max(point[0] for point in points)
    extent_y = max(point[1] for point in points)
    offset_x = (size[0] - extent_x * scale) / 2
    offset_y = (size[1] - extent_y * scale) / 2
    areas = Image.new("L", size, 0)
    draw = ImageDraw.Draw(areas)
    width = max(3, math.ceil(AREA_LINE_MM * 10 * scale))
    for index, block in enumerate(blocks[:254]):
        run: list[tuple[float, float]] = []
        for point in [*block["points"], None]:
            if point is None:
                if len(run) > 1:
                    draw.line(run, fill=index + 1, width=width, joint="curve")
                run = []
            else:
                run.append((offset_x + point[0] * scale, offset_y + point[1] * scale))
    return np.asarray(areas)

def restore_light_threads(image: Image.Image, stitches: dict[str, object], dpi: int) -> Image.Image:
    """Bring the areas sewn with light thread back to the thread's real colour."""
    blocks = stitches.get("blocks") or []
    light = [index for index, block in enumerate(blocks[:254]) if is_light_thread(block["colour_hex"])]
    if not light:
        return image
    pixels = np.asarray(image, dtype=np.float32).copy()
    areas = _thread_areas(image.size, stitches, dpi)
    drawn = pixels[..., 3] > 0
    for index in light:
        mask = (areas == index + 1) & drawn
        if not mask.any():
            continue
        # Keep each pixel's brightness relative to the area (the stitch shading) and
        # take the hue from the real thread colour.
        brightness = pixels[..., :3][mask] @ LUMA
        shade = np.clip(brightness / max(float(brightness.mean()), 1.0) * CORRECTED_SHADE, MIN_SHADE, 1.0)
        thread = np.asarray(_rgb(blocks[index]["colour_hex"]), dtype=np.float32)
        pixels[..., :3][mask] = shade[:, None] * thread[None, :]
    return Image.fromarray(pixels.astype(np.uint8), "RGBA")

def _corrected_render(png: bytes, stitches: dict[str, object] | None, dpi: int) -> Image.Image:
    with Image.open(io.BytesIO(png)) as source:
        image = source.convert("RGBA")
    if stitches is not None and dpi > 0:
        image = restore_light_threads(image, stitches, dpi)
    return image

def _thread_alpha(raw: Image.Image, stitches: dict[str, object], dpi: int) -> Image.Image:
    """Opacity of the stitches in Ink/Stitch's render, which is drawn on an opaque fabric-coloured page.

    Inside the area the stitches cover (shrunk by one pixel) everything is
    thread. At its edge the opacity follows how far a pixel is from the page
    colour, so anti-aliased thread edges stay soft and the page disappears;
    outside the area (grown by one pixel) nothing is kept. Light threads are
    darkened in the raw render, so no thread is mistaken for the page.
    """
    areas = Image.fromarray(((_thread_areas(raw.size, stitches, dpi) > 0) * 255).astype(np.uint8), "L")
    inner = np.asarray(areas.filter(ImageFilter.MinFilter(3)), dtype=np.float32) / 255
    outer = np.asarray(areas.filter(ImageFilter.MaxFilter(3)), dtype=np.float32) / 255
    rgb = np.asarray(raw.convert("RGB"), dtype=np.float32)
    distance = np.abs(rgb - np.asarray(FABRIC_RGB, dtype=np.float32)).max(axis=2)
    keyed = np.clip((distance - PAGE_TOLERANCE) / (OPAQUE_DISTANCE - PAGE_TOLERANCE), 0.0, 1.0)
    alpha = np.maximum(inner, keyed) * outer
    return Image.fromarray((alpha * 255).round().astype(np.uint8), "L")

def to_transparent_png(png: bytes, stitches: dict[str, object], dpi: int) -> bytes:
    """The stitch render without the page: light threads corrected, transparent around, PNG."""
    with Image.open(io.BytesIO(png)) as source:
        raw = source.convert("RGBA")
    alpha = _thread_alpha(raw, stitches, dpi)
    image = restore_light_threads(raw, stitches, dpi)
    # A soft edge pixel is thread blended with the page: take the page back out.
    opacity = np.asarray(alpha, dtype=np.float32)[..., None] / 255
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    page = np.asarray(FABRIC_RGB, dtype=np.float32)
    unblended = np.where(opacity > 0, (pixels - (1 - opacity) * page) / np.maximum(opacity, 1e-3), pixels)
    image = Image.fromarray(np.clip(unblended, 0, 255).round().astype(np.uint8), "RGB")
    image.putalpha(alpha)
    image.thumbnail((MAX_TRANSPARENT_PX, MAX_TRANSPARENT_PX), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()

def to_webp(png: bytes, stitches: dict[str, object] | None = None, dpi: int = 0) -> bytes:
    """Correct light thread colours, place the render on fabric colour, cap its size and encode WebP."""
    image = _corrected_render(png, stitches, dpi)
    background = Image.new("RGBA", image.size, FABRIC_RGB + (255,))
    background.alpha_composite(image)
    flat = background.convert("RGB")
    flat.thumbnail((MAX_PREVIEW_PX, MAX_PREVIEW_PX), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    flat.save(output, format="WEBP", quality=WEBP_QUALITY, method=4)
    return output.getvalue()
