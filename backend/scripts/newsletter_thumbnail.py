"""
Render the newsletter video thumbnail from a local intro-frame image.

Takes the first-frame webp from the web app (intro-frames/frame-00_{LANG}.webp),
scales it to a reasonable email width, draws a centered play button, rounds
the corners, and returns a JPEG byte string ready to attach inline as CID.

JPEG is used (not PNG) because email clients render it most reliably and the
file size stays small. Rounded corners are baked into the pixels (on a white
background) rather than relying on CSS — many clients strip border-radius.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger(__name__)

DEFAULT_MAX_WIDTH = 900
DEFAULT_CORNER_RADIUS_RATIO = 0.025
DEFAULT_PLAY_BUTTON_RATIO = 0.16
JPEG_QUALITY = 88
# Light neutral backdrop that matches the newsletter container on both light
# and dark email clients. Pure white would glow against dark themes; this
# shade reads as "transparent-ish" against both.
FLATTEN_BG = (255, 255, 255)


def _fit_max_width(image: Image.Image, max_width: int) -> Image.Image:
    """Downscale so width <= max_width while preserving aspect ratio."""
    if image.width <= max_width:
        return image
    ratio = max_width / image.width
    new_size = (max_width, int(round(image.height * ratio)))
    return image.resize(new_size, Image.LANCZOS)


def _rounded_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    """Build an alpha mask that rounds the image's corners."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _draw_play_button(
    image: Image.Image,
    diameter: int,
    shadow_blur: int = 16,
) -> None:
    """Overlay a soft-shadowed white play button at the center, in place."""
    w, h = image.size
    center = (w // 2, h // 2)
    r = diameter // 2

    # ── Shadow layer (blurred dark ellipse behind the button) ─────────────
    shadow_pad = shadow_blur * 3
    shadow_size = (diameter + shadow_pad * 2, diameter + shadow_pad * 2)
    shadow_layer = Image.new("RGBA", shadow_size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_draw.ellipse(
        (shadow_pad, shadow_pad, shadow_pad + diameter, shadow_pad + diameter),
        fill=(0, 0, 0, 120),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
    shadow_pos = (center[0] - shadow_size[0] // 2, center[1] - shadow_size[1] // 2)
    image.alpha_composite(shadow_layer, dest=shadow_pos)

    # ── Circle (white, slightly translucent to feel glassy, but mostly opaque) ─
    button_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    button_draw = ImageDraw.Draw(button_layer)
    button_draw.ellipse(
        (center[0] - r, center[1] - r, center[0] + r, center[1] + r),
        fill=(255, 255, 255, 240),
    )

    # ── Play triangle (dark, optically centered — shifted right by ~6% of r) ──
    tri_height = int(r * 1.05)
    tri_half = int(tri_height * 0.5)
    shift_x = int(r * 0.08)
    triangle = [
        (center[0] - tri_half + shift_x, center[1] - tri_half),
        (center[0] - tri_half + shift_x, center[1] + tri_half),
        (center[0] + tri_half + shift_x, center[1]),
    ]
    button_draw.polygon(triangle, fill=(20, 22, 48, 255))

    image.alpha_composite(button_layer)


def render_thumbnail(
    source_path: Path,
    max_width: int = DEFAULT_MAX_WIDTH,
    corner_radius_ratio: float = DEFAULT_CORNER_RADIUS_RATIO,
    play_button_ratio: float = DEFAULT_PLAY_BUTTON_RATIO,
) -> bytes:
    """Render the source frame into a JPEG with play button + rounded corners.

    Returns the raw JPEG bytes (ready for base64 + CID attachment).
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Thumbnail source not found: {source_path}")

    with Image.open(source_path) as src:
        image = src.convert("RGBA")

    image = _fit_max_width(image, max_width).convert("RGBA")

    # Round the corners via an alpha mask.
    radius = max(8, int(image.width * corner_radius_ratio))
    mask = _rounded_mask(image.size, radius)
    image.putalpha(mask)

    # Draw the play button on top while we still have alpha.
    diameter = max(64, int(image.width * play_button_ratio))
    _draw_play_button(image, diameter=diameter)

    # Flatten onto a neutral background so JPEG doesn't lose the rounded
    # corners (JPEG has no alpha channel).
    flattened = Image.new("RGB", image.size, FLATTEN_BG)
    flattened.paste(image, mask=image.split()[-1])

    buf = io.BytesIO()
    flattened.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def resolve_intro_frame(repo_root: Path, lang: str) -> Optional[Path]:
    """Return the path to the localized intro frame-00 webp, or None."""
    lang_upper = lang.upper()
    candidate = (
        repo_root
        / "frontend"
        / "apps"
        / "web_app"
        / "static"
        / "intro-frames"
        / f"frame-00_{lang_upper}.webp"
    )
    if candidate.exists():
        return candidate
    fallback = candidate.with_name("frame-00_EN.webp")
    if fallback.exists():
        logger.warning(
            "Intro frame for lang=%s not found (%s); falling back to EN frame.",
            lang,
            candidate.name,
        )
        return fallback
    return None


def regenerate_intro_thumbnails(repo_root: Path) -> None:
    """Re-render intro-thumbnail-{EN,DE}.jpg and write them into the web app.

    Call this once per intro-frame change. The emitted JPEGs are committed
    to the repo and served by SvelteKit at ``/newsletter-assets/…`` — the
    newsletter email references them by URL, so CID-inline quirks in Gmail
    and other clients don't matter.
    """
    out_dir = repo_root / "frontend" / "apps" / "web_app" / "static" / "newsletter-assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    for lang in ("en", "de"):
        src = resolve_intro_frame(repo_root, lang)
        if not src:
            logger.warning("No intro frame for lang=%s; skipping.", lang)
            continue
        data = render_thumbnail(src)
        out = out_dir / f"intro-thumbnail-{lang.upper()}.jpg"
        out.write_bytes(data)
        logger.info("Wrote %s (%d bytes) from %s", out, len(data), src.name)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Regenerate the intro video thumbnail JPEGs used by the newsletter email.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("/app"),
        help="Repository root (default: /app, i.e. inside the api container).",
    )
    args = parser.parse_args()
    regenerate_intro_thumbnails(args.repo_root)
