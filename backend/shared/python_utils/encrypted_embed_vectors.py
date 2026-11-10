# backend/shared/python_utils/encrypted_embed_vectors.py
#
# Resolve the SVG source text of a vector embed for server-side processing.
# Two embeds carry a readable vector source: an SVG made by images.generate or
# images.vectorize (its encrypted ``files.original`` variant with format svg)
# and an SVG code embed (``content.code``). Everything else, including pixel
# images and uploads whose vector source is not kept, fails explicitly.
# Record loading and decryption reuse encrypted_embed_images, so the cache-first
# Directus fallback and the Vault/AES-GCM rules stay identical.

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidTag

from backend.shared.python_utils.encrypted_embed_images import (
    EncryptedEmbedImageError,
    _load_embed_record,
    decode_image_record_content,
)
from backend.shared.python_utils.media_encryption import decrypt_media_payload

# Kept equal to the largest SVG the vector author accepts (vector_author.MAX_SVG_CHARS).
MAX_VECTOR_SOURCE_CHARS = 400_000

ORIGIN_GENERATED = "generated_svg"
ORIGIN_CODE = "svg_code"


class VectorSourceError(RuntimeError):
    """The referenced embed has no vector source the server can read."""


@dataclass(frozen=True)
class ResolvedVectorSource:
    """The SVG text of one vector embed plus a short human label for it."""

    svg: str
    origin: str
    label: str


def _label_from_content(content: Mapping[str, Any]) -> str:
    for key in ("title", "prompt", "filename", "file_path"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def classify_vector_content(content: Mapping[str, Any]) -> tuple[str, Any] | None:
    """Return ``(origin, payload)`` for a readable vector source, else ``None``.

    The payload is the SVG text for a code embed and the encrypted ``original``
    file descriptor for a generated SVG. The check is purely structural so it
    can run before any download.
    """
    code = content.get("code")
    if isinstance(code, str) and "<svg" in code.lower():
        return ORIGIN_CODE, code
    files = content.get("files")
    original = files.get("original") if isinstance(files, Mapping) else None
    if (isinstance(original, Mapping) and str(original.get("format") or "").lower() == "svg"
            and isinstance(original.get("s3_key"), str) and original["s3_key"]):
        return ORIGIN_GENERATED, original
    return None


def _checked_svg(svg: str) -> str:
    if "<svg" not in svg.lower():
        raise VectorSourceError("Referenced vector graphic does not contain an SVG document")
    if len(svg) > MAX_VECTOR_SOURCE_CHARS:
        raise VectorSourceError(
            f"Referenced vector graphic is larger than {MAX_VECTOR_SOURCE_CHARS} characters"
        )
    return svg


async def resolve_vector_source_embed(
    *,
    embed_id: str,
    user_vault_key_id: str,
    cache_client: Any,
    directus_service: Any,
    encryption_service: Any,
    s3_service: Any,
    bucket_name: str = "chatfiles",
    decode_toon: Callable[[str], Any] | None = None,
    preloaded_records: Mapping[str, Any] | None = None,
) -> ResolvedVectorSource:
    """Read the SVG text of a generated SVG or SVG code embed; raise ``VectorSourceError`` otherwise."""
    if not user_vault_key_id:
        raise VectorSourceError("A vault key is required to read the referenced graphic")
    try:
        record = await _load_embed_record(
            embed_id=embed_id, cache_client=cache_client,
            directus_service=directus_service, preloaded_records=preloaded_records,
        )
        content = await decode_image_record_content(
            record=record, user_vault_key_id=user_vault_key_id,
            encryption_service=encryption_service, decode_toon=decode_toon,
        )
    except EncryptedEmbedImageError as exc:
        raise VectorSourceError(str(exc)) from exc

    classified = classify_vector_content(content)
    if classified is None:
        raise VectorSourceError("Referenced embed is not a vector graphic")
    origin, payload = classified
    label = _label_from_content(content)
    if origin == ORIGIN_CODE:
        return ResolvedVectorSource(svg=_checked_svg(payload), origin=origin, label=label)

    wrapped_key = content.get("vault_wrapped_aes_key")
    if not isinstance(wrapped_key, str) or not wrapped_key:
        raise VectorSourceError("Referenced vector graphic is missing encryption metadata")
    aes_key_b64 = await encryption_service.decrypt_with_user_key(wrapped_key, user_vault_key_id)
    try:
        aes_key = base64.b64decode(aes_key_b64 or "", validate=True)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise VectorSourceError("Referenced vector graphic encryption metadata is invalid") from exc
    if len(aes_key) != 32:
        raise VectorSourceError("Referenced vector graphic encryption metadata has an invalid size")
    encrypted = await s3_service.get_file(bucket_name=bucket_name, object_key=payload["s3_key"])
    if not encrypted:
        raise VectorSourceError("Referenced vector graphic file is missing")
    try:
        plaintext = decrypt_media_payload(
            encrypted_data=encrypted, aes_key=aes_key, variant=payload,
            legacy_nonce_b64=content.get("aes_nonce"),
        )
        svg = plaintext.decode("utf-8")
    except (InvalidTag, ValueError) as exc:
        raise VectorSourceError("Referenced vector graphic file could not be decrypted") from exc
    return ResolvedVectorSource(svg=_checked_svg(svg), origin=origin, label=label)
