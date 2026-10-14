# backend/shared/python_utils/image_mime.py
#
# Purpose: lightweight image MIME detection from bytes and filenames.
# Used by backend skills that pass images to providers requiring an accurate
# MIME declaration, especially multimodal LLM adapters.
# Keep this module dependency-free so unit tests can run without app workers.

import os


def validate_raster_image(image_bytes: bytes) -> tuple[str, str]:
    """Decode supported raster bytes and return their actual format and MIME.

    Unlike the lightweight provider hint below, publication/storage must not
    trust a filename or default unknown bytes to PNG. Bytes are never rewritten.
    Pillow is imported only by callers needing this stricter validation.
    """
    from io import BytesIO
    import warnings

    from PIL import Image

    formats = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "WEBP": ("webp", "image/webp")}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes)) as image:
                actual = formats.get(image.format or "")
                if actual is None:
                    raise ValueError("Unsupported raster image format")
                image.verify()
            # verify checks containers; loading also rejects truncated pixels.
            with Image.open(BytesIO(image_bytes)) as image:
                image.load()
        return actual
    except Exception as exc:
        raise ValueError("Invalid or unsupported raster image bytes") from exc


def detect_image_mime_type(image_bytes: bytes, filename: str = "") -> str:
    """Infer MIME type from image magic bytes, with filename fallback."""
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"

    ext = os.path.splitext(filename.lower())[1]
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".gif":
        return "image/gif"
    if ext == ".webp":
        return "image/webp"
    return "image/png"
