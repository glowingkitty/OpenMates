# backend/apps/uploads/services/preview_generator.py
#
# Image preview generation service using Pillow.
#
# For uploaded images, we generate a WEBP preview at a fixed maximum dimension.
# The preview is used:
#   - As a fast-loading thumbnail in the message embed card UI
#   - By the images 'view' skill (which prefers the smaller version to reduce
#     token usage when sending to vision LLMs)
#
# Preview spec (matches the generated-images pattern in generate_task.py):
#   - Max width: 600px, max height: 600px (maintains aspect ratio)
#   - Format: WEBP at quality 85 (good balance of size vs. fidelity)
#
# All processing runs in asyncio.to_thread() to avoid blocking the event loop.

import asyncio
import io
import logging


logger = logging.getLogger(__name__)

# Preview dimensions — matches the existing image generation pipeline
PREVIEW_MAX_WIDTH = 600
PREVIEW_MAX_HEIGHT = 600
PREVIEW_WEBP_QUALITY = 85


class ImagePreviewResult:
    """Result of preview generation for a single image."""

    def __init__(
        self,
        preview_bytes: bytes,
        original_bytes: bytes,
        width: int,
        height: int,
        preview_width: int,
        preview_height: int,
        original_format: str,
    ) -> None:
        self.preview_bytes = preview_bytes          # WEBP-encoded preview
        self.original_bytes = original_bytes        # Re-encoded original (normalised)
        self.width = width                          # Original image width (px)
        self.height = height                        # Original image height (px)
        self.preview_width = preview_width          # Preview width (px)
        self.preview_height = preview_height        # Preview height (px)
        self.original_format = original_format      # Detected format: "jpeg", "png", etc.


def _generate_image_preview_sync(file_bytes: bytes) -> ImagePreviewResult:
    """
    Synchronous Pillow processing — called via asyncio.to_thread().

    Steps:
      1. Open and validate the image with Pillow (raises on corrupt/unsupported input).
      2. Convert to RGB (strips alpha for JPEG compatibility; WEBP handles alpha natively).
      3. Generate a thumbnail copy scaled to PREVIEW_MAX_WIDTH × PREVIEW_MAX_HEIGHT.
      4. Export both original and preview as WEBP.
    """
    from PIL import Image, UnidentifiedImageError  # type: ignore[import]

    try:
        img = Image.open(io.BytesIO(file_bytes))
    except UnidentifiedImageError as e:
        raise ValueError(f"Cannot identify image format: {e}") from e

    original_format = (img.format or "unknown").lower()
    original_width, original_height = img.size

    logger.debug(
        f"[PreviewGenerator] Processing {original_format} image "
        f"{original_width}x{original_height}"
    )

    # Convert RGBA/P to RGB for consistent output (WebP supports RGBA but we normalise)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGBA")  # Keep alpha in WEBP
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # --- Original re-encoding ---
    original_buf = io.BytesIO()
    img.save(original_buf, format="WEBP", quality=90, method=6)
    original_bytes = original_buf.getvalue()

    # --- Preview generation ---
    preview_img = img.copy()
    preview_img.thumbnail(
        (PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    preview_width, preview_height = preview_img.size

    preview_buf = io.BytesIO()
    preview_img.save(preview_buf, format="WEBP", quality=PREVIEW_WEBP_QUALITY, method=6)
    preview_bytes = preview_buf.getvalue()

    logger.debug(
        f"[PreviewGenerator] Original WEBP: {len(original_bytes)} bytes | "
        f"Preview {preview_width}x{preview_height} WEBP: {len(preview_bytes)} bytes"
    )

    return ImagePreviewResult(
        preview_bytes=preview_bytes,
        original_bytes=original_bytes,
        width=original_width,
        height=original_height,
        preview_width=preview_width,
        preview_height=preview_height,
        original_format=original_format,
    )


class PreviewGeneratorService:
    """
    Async service for generating image previews from uploaded file bytes.
    All Pillow operations run in a thread pool to avoid blocking the event loop.
    """

    async def generate_image_preview(self, file_bytes: bytes) -> ImagePreviewResult:
        """
        Generate a WEBP preview thumbnail for an uploaded image.

        Args:
            file_bytes: Raw uploaded image bytes (any Pillow-supported format).

        Returns:
            ImagePreviewResult containing preview bytes, original WEBP bytes, and dimensions.

        Raises:
            ValueError: If the bytes do not represent a valid image.
            Exception: If Pillow processing fails.
        """
        return await asyncio.to_thread(_generate_image_preview_sync, file_bytes)
