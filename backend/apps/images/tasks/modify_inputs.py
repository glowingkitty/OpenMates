"""Loads the pictures of an images.modify request at full resolution.

Each reference is read through the owner-bound image reference resolver (a
server-readable cache copy, the owner-filtered durable embed, or the owner's
generated-asset/upload index within its 24-hour processing window) and turned
into the file the editing program works on:

- an uploaded or generated pixel image: its ``original`` file (the stored full
  resolution), else the ``full`` variant when the original format cannot be
  read by the editor; never the reduced ``preview``;
- a vector graphic: its SVG source (the ``original`` SVG file or an SVG code embed);
- a design.embroidery result: its ``preview_transparent`` stitch preview (PNG with alpha).

An embroidery result is indexed with a machine-file content type, which the
generic upload resolver does not return, so it is read from the owner's index
record directly with the same owner and window checks. Every reference must
load; a request is never answered with a picture missing.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import httpx
from cryptography.exceptions import InvalidTag

from backend.apps.images.tasks.reference_images import ReferenceImageUnavailable
from backend.shared.python_utils.encrypted_embed_images import EncryptedEmbedImageError, decode_image_record_content
from backend.shared.python_utils.fresh_upload_images import FRESH_UPLOAD_WINDOW_SECONDS, FreshUploadImageUnavailable
from backend.shared.python_utils.image_reference_resolver import ImageReferenceUnavailable, load_owned_image_record
from backend.shared.python_utils.media_encryption import decrypt_media_payload

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
KIND_PIXEL = "pixel"
KIND_SVG = "svg"
KIND_EMBROIDERY = "embroidery"
EMBROIDERY_PREVIEW_VARIANT = "preview_transparent"
# Formats the editor reads as pixel input (modify_program.prepare_input).
EDITABLE_PIXEL_FORMATS = frozenset({"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"})


@dataclass(frozen=True)
class LoadedInput:
    """One referenced picture as the editing program receives it."""

    embed_id: str
    name: str
    data: bytes
    kind: str  # pixel | svg | embroidery (an embroidery preview is a pixel input for the editor)

    @property
    def program_kind(self) -> str:
        return KIND_SVG if self.kind == KIND_SVG else KIND_PIXEL


async def request_internal(method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Internal API call for the owner-scoped upload/generated-asset index lookup."""
    headers = {"X-Internal-Service-Token": os.getenv("INTERNAL_API_SHARED_TOKEN") or ""}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(method, f"{INTERNAL_API_BASE_URL}/{path}", json=payload, headers=headers)
    if response.status_code in {401, 403, 404}:
        raise FreshUploadImageUnavailable("Referenced picture is not available in the current processing window")
    response.raise_for_status()
    return response.json()


async def load_embroidery_index_record(*, directus_service: Any, embed_id: str, user_id: str) -> dict[str, Any]:
    """Read an embroidery result's owner-scoped index record within its 24-hour window."""
    rows = await directus_service.get_items(
        "upload_files",
        params={
            "filter": {"embed_id": {"_eq": embed_id}, "user_id": {"_eq": user_id}},
            "fields": "embed_id,user_id,created_at,original_filename,files_metadata,s3_base_url,aes_nonce,"
                      "vault_wrapped_aes_key",
            "limit": 1,
        },
        no_cache=True,
    )
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ReferenceImageUnavailable(f"Referenced picture {embed_id[:8]} is not available")
    row = rows[0]
    created_at = row.get("created_at")
    files = row.get("files_metadata")
    wrapped_key = row.get("vault_wrapped_aes_key")
    if (row.get("embed_id") != embed_id or row.get("user_id") != user_id
            or type(created_at) is not int or not 0 <= time.time() - created_at < FRESH_UPLOAD_WINDOW_SECONDS):
        raise ReferenceImageUnavailable(f"Referenced picture {embed_id[:8]} is no longer available")
    if (not isinstance(files, dict) or not isinstance(files.get(EMBROIDERY_PREVIEW_VARIANT), dict)
            or not isinstance(wrapped_key, str) or not wrapped_key):
        raise ReferenceImageUnavailable(f"Referenced picture {embed_id[:8]} is not an embroidery result")
    return {
        "embed_id": embed_id, "user_id": user_id, "files": files, "vault_wrapped_aes_key": wrapped_key,
        "aes_nonce": row.get("aes_nonce"), "filename": row.get("original_filename"),
    }


def _file(files: Mapping[str, Any], name: str) -> Optional[Mapping[str, Any]]:
    candidate = files.get(name)
    if isinstance(candidate, Mapping) and isinstance(candidate.get("s3_key"), str) and candidate["s3_key"]:
        return candidate
    return None


def select_source(content: Mapping[str, Any]) -> tuple[str, Optional[str], Optional[Mapping[str, Any]]]:
    """Return ``(kind, inline_svg, file_variant)`` for one decoded reference; raise when none fits.

    Purely structural, so it runs before any download.
    """
    code = content.get("code")
    if isinstance(code, str) and "<svg" in code.lower():
        return KIND_SVG, code, None
    files = content.get("files")
    if not isinstance(files, Mapping):
        raise ReferenceImageUnavailable("Referenced picture has no readable file")
    stitch_preview = _file(files, EMBROIDERY_PREVIEW_VARIANT)
    if stitch_preview is not None:
        return KIND_EMBROIDERY, None, stitch_preview
    original = _file(files, "original")
    if original is not None and str(original.get("format") or "").lower() == "svg":
        return KIND_SVG, None, original
    if original is not None and str(original.get("format") or "").lower() in EDITABLE_PIXEL_FORMATS:
        return KIND_PIXEL, None, original
    full = _file(files, "full")
    if full is not None and str(full.get("format") or "").lower() in EDITABLE_PIXEL_FORMATS:
        return KIND_PIXEL, None, full
    raise ReferenceImageUnavailable("Referenced picture has no full-resolution file the editor can read")


async def _load_content(task: Any, *, embed_id: str, user_id: str, user_vault_key_id: str) -> dict[str, Any]:
    try:
        record = await load_owned_image_record(
            embed_id=embed_id, user_id=user_id, cache_client=await task._cache_service.client,
            directus_service=task._directus_service, request_internal=request_internal,
        )
    except (ImageReferenceUnavailable, FreshUploadImageUnavailable) as exc:
        # Not an image upload or generated image in its window: an embroidery result is the remaining kind.
        logger.info("Reference %s is not a readable image record (%s); checking embroidery results",
                    embed_id[:8], type(exc).__name__)
        record = await load_embroidery_index_record(
            directus_service=task._directus_service, embed_id=embed_id, user_id=user_id,
        )
    try:
        return await decode_image_record_content(
            record=record, user_vault_key_id=user_vault_key_id, encryption_service=task._encryption_service,
        )
    except EncryptedEmbedImageError as exc:
        raise ReferenceImageUnavailable(f"Referenced picture {embed_id[:8]} is unavailable: {exc}") from exc


async def _decrypt(task: Any, *, s3_service: Any, bucket: str, content: Mapping[str, Any],
                   variant: Mapping[str, Any], user_vault_key_id: str) -> bytes:
    wrapped_key = content.get("vault_wrapped_aes_key")
    if not isinstance(wrapped_key, str) or not wrapped_key:
        raise ReferenceImageUnavailable("Referenced picture is missing its encryption metadata")
    aes_key_b64 = await task._encryption_service.decrypt_with_user_key(wrapped_key, user_vault_key_id)
    try:
        aes_key = base64.b64decode(aes_key_b64 or "", validate=True)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise ReferenceImageUnavailable("Referenced picture encryption metadata is invalid") from exc
    if len(aes_key) != 32:
        raise ReferenceImageUnavailable("Referenced picture encryption metadata has an invalid size")
    encrypted = await s3_service.get_file(bucket_name=bucket, object_key=variant["s3_key"])
    if not encrypted:
        raise ReferenceImageUnavailable("A referenced picture file is missing")
    try:
        return decrypt_media_payload(
            encrypted_data=encrypted, aes_key=aes_key, variant=variant, legacy_nonce_b64=content.get("aes_nonce"),
        )
    except (InvalidTag, ValueError) as exc:
        raise ReferenceImageUnavailable("A referenced picture file could not be decrypted") from exc


def _display_name(ref: str, content: Mapping[str, Any], kind: str) -> str:
    for key in ("filename", "title"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return ref.strip()[:120] or kind


async def load_modify_inputs(
    task: Any, *, embed_ids: Sequence[str], refs: Sequence[str], user_id: str, user_vault_key_id: str,
    s3_service: Any, bucket: str, log_prefix: str,
) -> list[LoadedInput]:
    """Read every referenced picture in request order or raise ``ReferenceImageUnavailable``."""
    if not user_vault_key_id:
        raise ReferenceImageUnavailable("No vault key is available to read the referenced pictures")
    if len(refs) != len(embed_ids):
        raise ValueError("every input embed needs its reference name")
    loaded: list[LoadedInput] = []
    for embed_id, ref in zip(embed_ids, refs):
        content = await _load_content(task, embed_id=embed_id, user_id=user_id, user_vault_key_id=user_vault_key_id)
        kind, inline_svg, variant = select_source(content)
        if inline_svg is not None:
            data = inline_svg.encode("utf-8")
        else:
            data = await _decrypt(task, s3_service=s3_service, bucket=bucket, content=content,
                                  variant=variant or {}, user_vault_key_id=user_vault_key_id)
        loaded.append(LoadedInput(embed_id=embed_id, name=_display_name(ref, content, kind), data=data, kind=kind))
        logger.info("%s [input:%s] Loaded %s input: %d bytes", log_prefix, embed_id[:8], kind, len(data))
    return loaded
