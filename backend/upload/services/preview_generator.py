# backend/upload/services/preview_generator.py
#
# Image processing service for uploaded files.
#
# Produces the SAME three variants as the image generation pipeline (generate_task.py):
#
#   - original    — Re-encoded with preserved format (no XMP/C2PA for user uploads)
#   - full_webp   — Full-size WEBP at quality 90
#   - preview_webp — Cropped/resized WEBP matching generate_task.py logic:
#                     * Horizontal/Square: 600×400 px (aspect-crop)
#                     * Vertical: fixed 400px height, proportional width
#
# SVG files are rasterized server-side before Pillow processing:
#   - cairosvg converts SVG bytes → PNG bytes at a target resolution (1024×1024 max)
#   - The PNG bytes are then processed by the standard Pillow pipeline
#   - This produces correct WEBP previews and enables AI vision (images.view skill)
#   - Without server-side rasterization, SVG uploads fail because Pillow cannot
#     open SVG files natively.
#
# Intentionally mirrors process_image_for_storage() from the core API so both
# flows produce identical preview dimensions and quality settings. We do NOT
# import from backend.core because app-uploads must run standalone on a separate VM.
#
# All Pillow operations run inside asyncio.to_thread() to avoid blocking the event loop.

import asyncio
import io
import logging

logger = logging.getLogger(__name__)

# Preview target dimensions — must match process_image_for_storage() in the core API
PREVIEW_TARGET_W = 600
PREVIEW_TARGET_H = 400
FULL_WEBP_QUALITY = 90     # Same as generate_task.py
PREVIEW_WEBP_QUALITY = 80  # Same as process_image_for_storage() default

# SVG rasterization target — SVGs with no intrinsic dimensions are rendered at this
# resolution so they produce a usable image for AI vision.  1024 px is a good
# balance: large enough for Figma exports / diagrams / icons, but not so large
# that it causes slow uploads or large preview files.
SVG_DEFAULT_OUTPUT_SIZE = 1024


class ImagePreviewResult:
    """
    Result of image processing for a single uploaded file.

    Provides processed bytes and dimensions for the three variants that
    mirror the generate_task.py output (original, full, preview).
    """

    def __init__(
        self,
        original_bytes: bytes,
        full_webp_bytes: bytes,
        preview_webp_bytes: bytes,
        original_width: int,
        original_height: int,
        full_width: int,
        full_height: int,
        preview_width: int,
        preview_height: int,
    ) -> None:
        self.original_bytes = original_bytes
        self.full_webp_bytes = full_webp_bytes
        self.preview_webp_bytes = preview_webp_bytes
        self.original_width = original_width
        self.original_height = original_height
        self.full_width = full_width
        self.full_height = full_height
        self.preview_width = preview_width
        self.preview_height = preview_height


def _get_dims(data: bytes) -> tuple[int, int]:
    """Extract (width, height) from image bytes using Pillow."""
    from PIL import Image  # type: ignore[import]
    try:
        img = Image.open(io.BytesIO(data))
        return img.size
    except Exception:
        return (0, 0)


def _rasterize_svg(svg_bytes: bytes) -> bytes:
    """
    Rasterize SVG bytes to PNG bytes using cairosvg.

    SVGs often have no intrinsic width/height (e.g. Figma exports use viewBox only).
    We force the output size to SVG_DEFAULT_OUTPUT_SIZE on the largest axis so that
    dimension-less SVGs produce a usable raster image.

    Returns PNG bytes suitable for passing to Pillow for WEBP conversion.

    Raises:
        RuntimeError: If cairosvg is not installed or rasterization fails.
    """
    try:
        import cairosvg  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "cairosvg is not installed — SVG rasterization is unavailable. "
            "Add 'cairosvg' to requirements.txt and the required system libs "
            "(libcairo2, libpango-1.0-0, libpangocairo-1.0-0, libgdk-pixbuf2.0-0) "
            "to the Dockerfile."
        ) from exc

    try:
        # Parse the SVG to determine its intrinsic dimensions so we can decide
        # whether to pass an explicit output size.  Many SVGs from design tools
        # (Figma, Inkscape) have only a viewBox without explicit width/height
        # attributes; cairosvg renders these at 1×1 px when no output size is given.
        import xml.etree.ElementTree as ET

        root = ET.fromstring(svg_bytes.decode("utf-8", errors="replace"))
        svg_w_str = root.get("width", "")
        svg_h_str = root.get("height", "")

        # Strip trailing units (px, pt, em, etc.) and parse as float
        def _parse_dim(s: str) -> float | None:
            s = s.strip()
            for suffix in ("px", "pt", "em", "rem", "mm", "cm", "in", "%"):
                s = s.removesuffix(suffix)
            try:
                v = float(s)
                return v if v > 0 else None
            except ValueError:
                return None

        intrinsic_w = _parse_dim(svg_w_str)
        intrinsic_h = _parse_dim(svg_h_str)
        has_intrinsic = intrinsic_w is not None and intrinsic_h is not None

        if has_intrinsic:
            # SVG has explicit dimensions — let cairosvg use them but still cap at
            # SVG_DEFAULT_OUTPUT_SIZE to avoid enormous uploads from high-res SVGs.
            assert intrinsic_w is not None and intrinsic_h is not None  # type narrowing
            largest = max(intrinsic_w, intrinsic_h)
            if largest > SVG_DEFAULT_OUTPUT_SIZE:
                scale = SVG_DEFAULT_OUTPUT_SIZE / largest
                out_w = int(intrinsic_w * scale)
                out_h = int(intrinsic_h * scale)
            else:
                out_w = int(intrinsic_w)
                out_h = int(intrinsic_h)
            png_bytes: bytes = cairosvg.svg2png(
                bytestring=svg_bytes,
                output_width=out_w,
                output_height=out_h,
            )
            logger.info(
                f"[PreviewGenerator] SVG rasterized (intrinsic {int(intrinsic_w)}×{int(intrinsic_h)} "
                f"→ output {out_w}×{out_h})"
            )
        else:
            # No intrinsic dimensions — render at default square resolution.
            # cairosvg scales viewBox-only SVGs to fill the requested output box.
            png_bytes = cairosvg.svg2png(
                bytestring=svg_bytes,
                output_width=SVG_DEFAULT_OUTPUT_SIZE,
                output_height=SVG_DEFAULT_OUTPUT_SIZE,
            )
            logger.info(
                f"[PreviewGenerator] SVG rasterized (no intrinsic dims → "
                f"{SVG_DEFAULT_OUTPUT_SIZE}×{SVG_DEFAULT_OUTPUT_SIZE} square)"
            )

        return png_bytes

    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"SVG rasterization failed: {exc}") from exc


def _process_sync(file_bytes: bytes) -> ImagePreviewResult:
    """
    Synchronous image processing — called via asyncio.to_thread().

    Mirrors process_image_for_storage() from backend.core.api.app.utils.image_processing
    but is self-contained so app-uploads can run on a separate VM without importing
    from the core API package.

    No XMP/C2PA metadata is injected for user uploads since the images are not
    AI-generated by our platform.
    """
    from PIL import Image, UnidentifiedImageError  # type: ignore[import]

    # --- SVG pre-processing: rasterize to PNG before Pillow ---
    # Pillow cannot open SVG files natively.  Detect SVG by sniffing the first
    # bytes (XML declaration or <svg tag) rather than relying on the caller to
    # pass MIME metadata.  cairosvg converts SVG → PNG which Pillow then processes
    # through the standard WEBP preview pipeline.
    is_svg = False
    stripped = file_bytes.lstrip()
    if stripped.startswith(b"<") and (
        b"<svg" in stripped[:1024].lower() or
        stripped[:5] == b"<?xml"
    ):
        is_svg = True

    if is_svg:
        logger.info("[PreviewGenerator] SVG detected — rasterizing with cairosvg before Pillow processing")
        try:
            file_bytes = _rasterize_svg(file_bytes)
            logger.info(
                f"[PreviewGenerator] SVG rasterized to PNG ({len(file_bytes) / 1024:.1f} KB)"
            )
        except RuntimeError as exc:
            raise ValueError(f"SVG rasterization failed: {exc}") from exc

    try:
        img = Image.open(io.BytesIO(file_bytes))
    except UnidentifiedImageError as exc:
        raise ValueError(f"Cannot identify image format: {exc}") from exc

    # SVGs are rasterized to PNG; treat orig_format as PNG for correct re-encoding.
    orig_format = "PNG" if is_svg else (img.format or "JPEG")
    original_width, original_height = img.size

    logger.debug(
        f"[PreviewGenerator] Processing {orig_format} image {original_width}x{original_height}"
    )

    # --- Re-encode original (preserve format, no metadata injection for uploads) ---
    orig_buf = io.BytesIO()
    fmt_upper = orig_format.upper()
    if fmt_upper == "PNG":
        img.save(orig_buf, format="PNG")
    elif fmt_upper in ("JPEG", "JPG"):
        img.save(orig_buf, format="JPEG", quality=98)
    elif fmt_upper == "WEBP":
        img.save(orig_buf, format="WEBP", quality=98)
    else:
        # Fallback: convert to WEBP for any other format (GIF, BMP, HEIC, etc.)
        rgb = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
        rgb.save(orig_buf, format="WEBP", quality=95)
    original_bytes = orig_buf.getvalue()

    # --- Full-size WEBP (same as process_image_for_storage quality=90) ---
    full_buf = io.BytesIO()
    img.save(full_buf, format="WEBP", quality=FULL_WEBP_QUALITY)
    full_webp_bytes = full_buf.getvalue()

    # --- Preview WEBP — mirrors process_image_for_storage() preview logic ---
    #
    # Horizontal/Square: crop to 600×400 (aspect-ratio crop, centred)
    # Vertical: resize to 400px height, proportional width
    width, height = img.size
    is_vertical = height > width

    if is_vertical:
        # Vertical: fixed 400px height, proportional width
        new_height = PREVIEW_TARGET_H
        new_width = int(width * (new_height / height))
        preview_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    else:
        # Horizontal/Square: crop to 600×400
        target_ratio = PREVIEW_TARGET_W / PREVIEW_TARGET_H
        current_ratio = width / height

        if current_ratio > target_ratio:
            # Wider than target: crop sides
            new_width = int(height * target_ratio)
            left = (width - new_width) / 2
            img_cropped = img.crop((left, 0, left + new_width, height))
        else:
            # Taller than target: crop top/bottom
            new_height = int(width / target_ratio)
            top = (height - new_height) / 2
            img_cropped = img.crop((0, top, width, top + new_height))

        preview_img = img_cropped.resize(
            (PREVIEW_TARGET_W, PREVIEW_TARGET_H), Image.Resampling.LANCZOS
        )

    preview_buf = io.BytesIO()
    preview_img.save(preview_buf, format="WEBP", quality=PREVIEW_WEBP_QUALITY)
    preview_webp_bytes = preview_buf.getvalue()

    full_width, full_height = _get_dims(full_webp_bytes)
    preview_width, preview_height = _get_dims(preview_webp_bytes)

    logger.info(
        f"[PreviewGenerator] Done: "
        f"original={original_width}x{original_height} ({len(original_bytes)}B), "
        f"full={full_width}x{full_height} ({len(full_webp_bytes)}B), "
        f"preview={preview_width}x{preview_height} ({len(preview_webp_bytes)}B)"
    )

    return ImagePreviewResult(
        original_bytes=original_bytes,
        full_webp_bytes=full_webp_bytes,
        preview_webp_bytes=preview_webp_bytes,
        original_width=original_width,
        original_height=original_height,
        full_width=full_width,
        full_height=full_height,
        preview_width=preview_width,
        preview_height=preview_height,
    )


class PreviewGeneratorService:
    """
    Async service for processing uploaded images into multiple variants.

    Uses the same processing logic as the image generation skill to ensure
    consistent output quality and preview dimensions across all flows.
    """

    async def generate_image_preview(self, file_bytes: bytes) -> ImagePreviewResult:
        """
        Process an uploaded image into original, full, and preview WEBP variants.

        Runs Pillow processing in a thread pool to avoid blocking the event loop.

        Args:
            file_bytes: Raw uploaded image bytes (any Pillow-supported format).

        Returns:
            ImagePreviewResult with processed bytes and dimensions for all three variants.

        Raises:
            ValueError: If the bytes do not represent a valid image.
            Exception: If Pillow processing fails unexpectedly.
        """
        return await asyncio.to_thread(_process_sync, file_bytes)
