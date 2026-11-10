"""Turn Ink/Stitch's realistic stitch render into the delivered WebP preview (Pillow)."""

from __future__ import annotations

import io

from PIL import Image

MAX_PREVIEW_PX = 1200
FABRIC_RGB = (244, 241, 234)
WEBP_QUALITY = 72


def render_dpi(width_mm: float, height_mm: float) -> int:
    """DPI at which the longer side renders at about MAX_PREVIEW_PX pixels."""
    longest_inches = max(width_mm, height_mm, 1.0) / 25.4
    return max(30, min(600, int(MAX_PREVIEW_PX / longest_inches)))


def to_webp(png: bytes) -> bytes:
    """Place the render on a fabric-coloured background, cap its size and encode WebP."""
    with Image.open(io.BytesIO(png)) as source:
        image = source.convert("RGBA")
    background = Image.new("RGBA", image.size, FABRIC_RGB + (255,))
    background.alpha_composite(image)
    flat = background.convert("RGB")
    flat.thumbnail((MAX_PREVIEW_PX, MAX_PREVIEW_PX), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    flat.save(output, format="WEBP", quality=WEBP_QUALITY, method=4)
    return output.getvalue()
