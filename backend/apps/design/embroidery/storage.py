"""Encrypted storage of the nine design.embroidery result files.

All variants share one AES key per result, are encrypted like other generated
media (``encrypt_media_variants``) and carry their own download filename and
content type, so ``/v1/generated-assets/{embed_id}/files/{variant}/download``
saves every machine file under its matching extension.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.shared.python_utils.readable_title import readable_title
from backend.shared.python_utils.media_encryption import encrypt_media_variants, load_media_write_version

MACHINE_FORMATS: tuple[str, ...] = ("dst", "pes", "exp", "jef", "vp3")
RESULT_VARIANTS: tuple[str, ...] = (*MACHINE_FORMATS, "preview", "preview_transparent", "prepared_svg", "stitches")

# variant -> (file extension, MIME type)
VARIANT_TYPES: dict[str, tuple[str, str]] = {
    **{name: (name, "application/octet-stream") for name in MACHINE_FORMATS},
    "preview": ("webp", "image/webp"),
    "preview_transparent": ("png", "image/png"),
    "prepared_svg": ("svg", "image/svg+xml"),
    "stitches": ("json", "application/json"),
}
DEFAULT_TITLE = "Embroidery design"


class IncompleteEmbroideryFiles(RuntimeError):
    """The conversion did not return every result file; nothing may be delivered."""


@dataclass(frozen=True)
class StoredEmbroideryFiles:
    """Metadata written to the embed and the generated-asset index."""

    files_metadata: dict[str, dict[str, Any]]
    aes_key_b64: str
    nonce_b64: str
    s3_keys: list[str]


# File names that say nothing about the design (lower case, without extension and
# separators); a title is never one of these words (TASK-1610: "source").
GENERIC_NAME_WORDS = frozenset({
    "source", "src", "input", "file", "files", "image", "images", "img", "picture", "pic", "photo",
    "graphic", "graphics", "drawing", "vector", "vectors", "svg", "design", "artwork", "art", "logo",
    "untitled", "unnamed", "new", "copy", "download", "downloads", "upload", "export", "output", "final",
    "test", "temp", "tmp", "draft", "sample", "example", "document", "doc", "scan", "screenshot",
    "embroidery", "patch", "stitch", "stitches", "result", "edited", "version", "v",
    "at", "screen", "shot", "bildschirmfoto", "capture", "am", "um",
})
_EXTENSION = re.compile(r"\.(svg|png|jpe?g|webp|gif|bmp|tiff?|heic|pdf)$", re.IGNORECASE)
# Embed refs of uploaded files end in a short random suffix ("source.svg-x4F").
_EMBED_REF_SUFFIX = re.compile(r"(\.[a-z0-9]{2,4})-[A-Za-z0-9]{2,6}$", re.IGNORECASE)


def descriptive_title(label: str | None) -> str | None:
    """The readable title of ``label``, or ``None`` when it does not describe the design.

    Generic words ("source", "image", "untitled"), camera and download names
    ("IMG_1234", "Screenshot 2026-11-22"), bare numbers and ids are not titles.
    """
    text = " ".join(str(label or "").split())
    text = _EMBED_REF_SUFFIX.sub(r"\1", text)
    text = _EXTENSION.sub("", text)
    words = [word for word in re.split(r"[\s\-_.()\[\]]+", text.casefold()) if word]
    meaningful = [word for word in words
                  if word not in GENERIC_NAME_WORDS and not re.fullmatch(r"\d+|[0-9a-f]{6,}|v?\d+(\.\d+)*|(img|dsc|pxl|vid)\d*", word)]
    if not meaningful:
        return None
    return readable_title(text) or None


def result_title(*labels: str | None) -> str:
    """Readable title (at most ``MAX_TITLE_CHARS``): the first descriptive label, else ``DEFAULT_TITLE``.

    Callers pass the candidates in order of preference: the source graphic's
    title, prompt or file name, then the short name the assistant gave the design.
    """
    for label in labels:
        title = descriptive_title(label)
        if title:
            return title
    return DEFAULT_TITLE


def variant_filename(title: str, variant: str) -> str:
    """Download-safe ``<title>.<ext>`` for one variant."""
    extension = VARIANT_TYPES[variant][0]
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.casefold()).strip("-")[:48].rstrip("-")
    suffix = {"preview": "-preview", "preview_transparent": "-preview-transparent",
              "prepared_svg": "-prepared", "stitches": "-stitches"}.get(variant, "")
    return f"{slug or 'embroidery-design'}{suffix}.{extension}"


def require_complete_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Return the nine result files in order; raise when one is missing or empty."""
    missing = [name for name in RESULT_VARIANTS if not isinstance(files.get(name), (bytes, bytearray)) or not files[name]]
    if missing:
        raise IncompleteEmbroideryFiles(f"Embroidery conversion returned no {', '.join(missing)} file")
    return {name: bytes(files[name]) for name in RESULT_VARIANTS}


async def store_embroidery_files(
    *, s3_service: Any, user_id: str, embed_id: str, title: str, files: Mapping[str, bytes],
) -> StoredEmbroideryFiles:
    """Encrypt every variant before upload; remove already uploaded objects when one upload fails."""
    plaintext = require_complete_files(files)
    encrypted = encrypt_media_variants(plaintext, write_version=load_media_write_version())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    uploaded: list[str] = []
    metadata: dict[str, dict[str, Any]] = {}
    try:
        for variant in RESULT_VARIANTS:
            extension, mime_type = VARIANT_TYPES[variant]
            s3_key = f"{user_id}/{timestamp}_{embed_id[:8]}_embroidery_{variant}.{extension}.enc"
            await s3_service.upload_file(
                bucket_key="chatfiles", file_key=s3_key,
                content=encrypted.payloads[variant], content_type="application/octet-stream",
            )
            uploaded.append(s3_key)
            metadata[variant] = {
                "s3_key": s3_key,
                "size_bytes": len(plaintext[variant]),
                "format": extension,
                "mime_type": mime_type,
                "filename": variant_filename(title, variant),
                **encrypted.metadata[variant],
            }
    except BaseException:
        for s3_key in uploaded:
            await s3_service.delete_file(bucket_key="chatfiles", file_key=s3_key)
        raise
    return StoredEmbroideryFiles(
        files_metadata=metadata, aes_key_b64=encrypted.aes_key_b64,
        nonce_b64=encrypted.legacy_nonce_b64 or "", s3_keys=uploaded,
    )
