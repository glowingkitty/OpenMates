"""Loads the images a generation request refers to (the graphic to change, or pixel references).

A generated graphic is client-encrypted once the chat stores it, so the server
reads it through the owner-scoped media index (24-hour processing window)
instead of the chat embed cache. Every reference must load: a request that
names an input is never answered by silently drawing without it.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

import httpx
from cryptography.exceptions import InvalidTag

from backend.core.api.app.services.s3.config import get_bucket_name
from backend.shared.python_utils.encrypted_embed_images import (
    EncryptedEmbedImageError,
    decode_image_record_content,
)
from backend.shared.python_utils.fresh_upload_images import FreshUploadImageUnavailable
from backend.shared.python_utils.image_reference_resolver import (
    ImageReferenceUnavailable,
    load_owned_image_record,
)
from backend.shared.python_utils.media_encryption import decrypt_media_payload
# Shared with the owner-bound picture loader, so one failure type covers every picture input.
from backend.shared.python_utils.owned_pictures import ReferenceImageUnavailable

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
VECTOR_SCRIPT_TTL_SECONDS = 86400
REFERENCE_UNAVAILABLE_MESSAGE = (
    "The image this request refers to could not be loaded, so nothing was generated or charged. "
    "Please try again."
)


@dataclass
class LoadedReferences:
    """Everything read from the referenced embeds, in request order."""

    images: List[Tuple[bytes, str]] = field(default_factory=list)
    svg_sources: List[str] = field(default_factory=list)
    script_sources: List[str] = field(default_factory=list)


def _vector_script_key(embed_id: str) -> str:
    return f"images:vector_script:{embed_id}"


async def remember_vector_script(task: Any, *, embed_id: str, script: str, vault_key_id: str) -> None:
    """Keep a script-made drawing's generator readable for later changes (Vault-encrypted, 24 hours)."""
    ciphertext, _ = await task._encryption_service.encrypt_with_user_key(script, vault_key_id)
    if not ciphertext:
        raise RuntimeError("Failed to encrypt the generator script of a vector drawing")
    client = await task._cache_service.client
    await client.set(_vector_script_key(embed_id), ciphertext, ex=VECTOR_SCRIPT_TTL_SECONDS)


async def _recall_vector_script(task: Any, *, embed_id: str, vault_key_id: str) -> Optional[str]:
    client = await task._cache_service.client
    ciphertext = await client.get(_vector_script_key(embed_id))
    if not ciphertext:
        return None
    if isinstance(ciphertext, bytes):
        ciphertext = ciphertext.decode("utf-8")
    script = await task._encryption_service.decrypt_with_user_key(ciphertext, vault_key_id)
    if not script:
        raise ReferenceImageUnavailable("The generator script of the referenced drawing could not be decrypted")
    return script


async def _request_internal(method: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Internal API call for the owner-scoped media index lookup."""
    headers = {"X-Internal-Service-Token": os.getenv("INTERNAL_API_SHARED_TOKEN") or ""}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(method, f"{INTERNAL_API_BASE_URL}/{path}", json=payload, headers=headers)
    if response.status_code in {401, 403, 404}:
        raise FreshUploadImageUnavailable("Referenced image is not available in the current processing window")
    response.raise_for_status()
    return response.json()


def _variant(files: Mapping[str, Any], names: Tuple[str, ...]) -> Optional[Mapping[str, Any]]:
    for name in names:
        candidate = files.get(name)
        if isinstance(candidate, Mapping) and candidate.get("s3_key"):
            return candidate
    return None


async def _decrypt_variant(*, s3_service: Any, bucket: str, variant: Mapping[str, Any], aes_key: bytes,
                           legacy_nonce_b64: Optional[str]) -> bytes:
    encrypted = await s3_service.get_file(bucket_name=bucket, object_key=variant["s3_key"])
    if not encrypted:
        raise ReferenceImageUnavailable("A referenced image file is missing")
    try:
        return decrypt_media_payload(
            encrypted_data=encrypted, aes_key=aes_key, variant=variant, legacy_nonce_b64=legacy_nonce_b64,
        )
    except (InvalidTag, ValueError) as exc:
        raise ReferenceImageUnavailable("A referenced image file could not be decrypted") from exc


async def load_reference_images(
    task: Any,
    *,
    embed_ids: List[str],
    user_id: str,
    user_vault_key_id: Optional[str],
    s3_service: Any,
    want_vector_sources: bool,
    log_prefix: str,
) -> LoadedReferences:
    """Read every referenced embed or raise ``ReferenceImageUnavailable``.

    Each reference yields its raster preview (safety check and pixel input).
    With ``want_vector_sources`` an SVG reference also yields its source text
    and a script-made drawing its generator script.
    """
    loaded = LoadedReferences()
    if not embed_ids:
        return loaded
    if not user_vault_key_id:
        raise ReferenceImageUnavailable("No vault key is available to read the referenced images")

    cache_client = await task._cache_service.client
    bucket = get_bucket_name("chatfiles", s3_service.environment)
    for embed_id in embed_ids:
        embed_log = f"{log_prefix} [ref_embed:{embed_id[:8]}...]"
        try:
            record = await load_owned_image_record(
                embed_id=embed_id, user_id=user_id, cache_client=cache_client,
                directus_service=task._directus_service, request_internal=_request_internal,
            )
            content = await decode_image_record_content(
                record=record, user_vault_key_id=user_vault_key_id,
                encryption_service=task._encryption_service,
            )
        except (EncryptedEmbedImageError, ImageReferenceUnavailable, FreshUploadImageUnavailable) as exc:
            raise ReferenceImageUnavailable(f"Referenced image {embed_id[:8]} is unavailable: {exc}") from exc

        embedded_code = content.get("code")
        if isinstance(embedded_code, str) and "<svg" in embedded_code.lower():
            if not want_vector_sources:
                raise ReferenceImageUnavailable("An SVG code reference can only be used for vector output")
            loaded.svg_sources.append(embedded_code)
            logger.info("%s Using SVG code embed as editable vector source", embed_log)
            continue

        files = content.get("files")
        wrapped_key = content.get("vault_wrapped_aes_key")
        if not isinstance(files, Mapping) or not isinstance(wrapped_key, str) or not wrapped_key:
            raise ReferenceImageUnavailable(f"Referenced image {embed_id[:8]} has no readable file metadata")
        aes_key_b64 = await task._encryption_service.decrypt_with_user_key(wrapped_key, user_vault_key_id)
        try:
            aes_key = base64.b64decode(aes_key_b64 or "", validate=True)
        except (TypeError, ValueError, binascii.Error) as exc:
            raise ReferenceImageUnavailable("Referenced image encryption metadata is invalid") from exc
        if len(aes_key) != 32:
            raise ReferenceImageUnavailable("Referenced image encryption metadata has an invalid size")
        nonce = content.get("aes_nonce")

        raster = _variant(files, ("preview", "full")) or _variant(files, ("original",))
        if raster is None:
            raise ReferenceImageUnavailable(f"Referenced image {embed_id[:8]} has no file")
        raster_format = str(raster.get("format") or "webp").lower()
        original = files.get("original") if isinstance(files.get("original"), Mapping) else None
        is_vector = bool(original and str(original.get("format") or "").lower() == "svg" and original.get("s3_key"))
        if raster_format != "svg":
            image = await _decrypt_variant(
                s3_service=s3_service, bucket=bucket, variant=raster, aes_key=aes_key, legacy_nonce_b64=nonce,
            )
            mime_type = "image/jpeg" if raster_format in {"jpg", "jpeg"} else f"image/{raster_format}"
            loaded.images.append((image, mime_type))
            logger.info("%s Loaded reference image: %d bytes (%s)", embed_log, len(image), mime_type)

        if want_vector_sources and is_vector:
            svg_bytes = await _decrypt_variant(
                s3_service=s3_service, bucket=bucket, variant=original, aes_key=aes_key, legacy_nonce_b64=nonce,
            )
            loaded.svg_sources.append(svg_bytes.decode("utf-8"))
            logger.info("%s Loaded SVG source of vector reference", embed_log)
            script = await _recall_vector_script(task, embed_id=embed_id, vault_key_id=user_vault_key_id)
            if script:
                loaded.script_sources.append(script)
                logger.info("%s Loaded generator script of vector reference", embed_log)
        elif raster_format == "svg":
            raise ReferenceImageUnavailable(f"Referenced image {embed_id[:8]} has no raster preview")

    logger.info("%s Loaded %d reference image(s)", log_prefix, len(embed_ids))
    return loaded
