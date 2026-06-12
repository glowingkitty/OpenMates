# backend/shared/python_utils/image_mime.py
#
# Purpose: lightweight image MIME detection from bytes and filenames.
# Used by backend skills that pass images to providers requiring an accurate
# MIME declaration, especially multimodal LLM adapters.
# Keep this module dependency-free so unit tests can run without app workers.

import os


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
