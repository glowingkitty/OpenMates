# backend/shared/python_utils/encrypted_embed_images.py
#
# Resolve encrypted image embeds for server-side provider calls. The helper
# reads cache first, falls back to Directus, and only returns plaintext image
# bytes in worker memory after both Vault and AES-GCM decryption succeed.

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAX_IMAGE_INPUT_BYTES = 20 * 1024 * 1024
IMAGE_MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
logger = logging.getLogger(__name__)


class EncryptedEmbedImageError(RuntimeError):
    """A safe, actionable failure while resolving an encrypted image embed."""


@dataclass(frozen=True)
class ResolvedEncryptedImage:
    """One decrypted image that can be passed to an external provider in memory."""

    content: bytes
    mime_type: str


async def _load_embed_record(
    *,
    embed_id: str,
    cache_client: Any,
    directus_service: Any,
    preloaded_records: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if preloaded_records:
        preloaded = preloaded_records.get(embed_id)
        if isinstance(preloaded, dict):
            return preloaded

    cache_key = f"embed:{embed_id}"
    try:
        cached = await cache_client.get(cache_key)
    except Exception as exc:
        logger.warning("Encrypted image cache read failed: %s", type(exc).__name__)
        cached = None
    if cached:
        try:
            record = json.loads(cached)
        except (TypeError, json.JSONDecodeError):
            logger.warning("Encrypted image cache record is malformed; reading Directus")
            record = None
        if isinstance(record, dict):
            return record

    record = await directus_service.embed.get_embed_by_id(embed_id)
    if not isinstance(record, dict):
        raise EncryptedEmbedImageError("Referenced image is no longer available")
    try:
        await cache_client.set(cache_key, json.dumps(record), ex=24 * 60 * 60)
    except (TypeError, ValueError) as exc:
        logger.warning("Encrypted image cache write failed: %s", type(exc).__name__)
    return record


async def resolve_encrypted_image_embed(
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
) -> ResolvedEncryptedImage:
    """Resolve one encrypted image from cache or Directus and decrypt it in memory."""
    if not user_vault_key_id:
        raise EncryptedEmbedImageError("A vault key is required to access the referenced image")
    record = await _load_embed_record(
        embed_id=embed_id,
        cache_client=cache_client,
        directus_service=directus_service,
        preloaded_records=preloaded_records,
    )
    encrypted_content = record.get("encrypted_content")
    if isinstance(encrypted_content, str) and encrypted_content:
        if decode_toon is None:
            from toon_format import decode as decode_toon
        decrypted_toon = await encryption_service.decrypt_with_user_key(encrypted_content, user_vault_key_id)
        if not decrypted_toon:
            raise EncryptedEmbedImageError("Referenced image content could not be decrypted")
        content = decode_toon(decrypted_toon)
        if not isinstance(content, dict):
            raise EncryptedEmbedImageError("Referenced image content is invalid")
    else:
        # Fresh uploads are cached before their optional chat embed is persisted.
        content = record

    files = content.get("files")
    wrapped_key = content.get("vault_wrapped_aes_key")
    nonce_b64 = content.get("aes_nonce")
    if not isinstance(files, dict) or not isinstance(wrapped_key, str) or not isinstance(nonce_b64, str):
        raise EncryptedEmbedImageError("Referenced image is missing encryption metadata")
    variant = next(
        (
            files[name]
            for name in ("original", "full", "preview")
            if isinstance(files.get(name), dict) and files[name].get("s3_key")
        ),
        None,
    )
    if not isinstance(variant, dict):
        raise EncryptedEmbedImageError("Referenced image has no available file variant")

    aes_key_b64 = await encryption_service.decrypt_with_user_key(wrapped_key, user_vault_key_id)
    try:
        aes_key = base64.b64decode(aes_key_b64 or "", validate=True)
        nonce = base64.b64decode(nonce_b64, validate=True)
    except (TypeError, ValueError) as exc:
        raise EncryptedEmbedImageError("Referenced image encryption metadata is invalid") from exc
    if len(aes_key) != 32 or len(nonce) != 12:
        raise EncryptedEmbedImageError("Referenced image encryption metadata has an invalid size")

    encrypted_bytes = await s3_service.get_file(bucket_name=bucket_name, object_key=variant["s3_key"])
    if not encrypted_bytes:
        raise EncryptedEmbedImageError("Referenced image file is missing")
    try:
        plaintext = AESGCM(aes_key).decrypt(nonce, encrypted_bytes, None)
    except Exception as exc:
        raise EncryptedEmbedImageError("Referenced image file could not be decrypted") from exc
    if len(plaintext) > MAX_IMAGE_INPUT_BYTES:
        raise EncryptedEmbedImageError("Referenced image exceeds the provider input size limit")
    image_format = str(variant.get("format") or "").lower()
    mime_type = IMAGE_MIME_TYPES.get(image_format)
    if not mime_type:
        raise EncryptedEmbedImageError("Referenced image format is not supported")
    return ResolvedEncryptedImage(content=plaintext, mime_type=mime_type)
