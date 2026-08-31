# backend/apps/audio/tasks/common.py
#
# Shared generated-audio task helpers.
# Audio generate/speak workers use this module to write encrypted MP3 variants
# to private chatfiles storage, index them in upload_files, update client embeds,
# and charge usage only after successful provider generation.

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

import httpx

from backend.shared.python_utils.billing_utils import ensure_credit_headroom
from backend.shared.python_utils.generated_assets import (
    GeneratedAssetVariant,
    TOKEN_TTL_SECONDS,
    build_download_url,
    cache_s3_file_keys,
    create_download_token,
    index_generated_asset,
)
from backend.shared.python_utils.media_encryption import encrypt_media_variants, load_media_write_version

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from backend.core.api.app.tasks.base_task import BaseServiceTask

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "https://api.dev.openmates.org")


def hash_value(value: str) -> str:
    """Hash user IDs for usage metadata without exposing raw identifiers."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extension_for_mime(mime_type: str) -> str:
    normalized = (mime_type or "").split(";", 1)[0].lower()
    if normalized in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    if normalized in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return "wav"
    if normalized in {"audio/mp4", "audio/m4a"}:
        return "m4a"
    if normalized == "audio/ogg":
        return "ogg"
    return "mp3"


async def resolve_user_vault_key_id(
    task: BaseServiceTask,
    *,
    user_id: str,
    supplied_vault_key_id: Optional[str],
) -> str:
    if supplied_vault_key_id:
        return supplied_vault_key_id
    success, user_profile, error_msg = await task._directus_service.get_user_profile(user_id)
    if not success or not isinstance(user_profile, dict):
        raise RuntimeError(f"User profile not found for {user_id}: {error_msg}")
    vault_key_id = user_profile.get("vault_key_id")
    if not vault_key_id:
        raise RuntimeError(f"Vault key ID not found for user {user_id}")
    return str(vault_key_id)


async def charge_audio_generation_credits(
    *,
    user_id: str,
    app_id: str,
    skill_id: str,
    task_id: str,
    request_id: Any,
    credits: int,
    model_ref: str,
    duration_seconds: float,
    chat_id: Optional[str],
    message_id: Optional[str],
    external_request: bool,
    api_key_hash: Optional[str],
    device_hash: Optional[str],
    api_key_name: Optional[str],
    log_prefix: str,
    raise_on_failure: bool = False,
) -> None:
    """Charge generated-audio usage after successful provider output."""
    if credits <= 0:
        return

    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        usage_details = {
            "chat_id": chat_id,
            "message_id": message_id,
            "external_request": external_request,
            "api_key_name": api_key_name,
            "units_processed": 1,
            "model_used": model_ref,
            "server_provider": "ElevenLabs",
            "server_region": "US",
            "duration_seconds": duration_seconds,
        }
        payload = {
            "user_id": user_id,
            "user_id_hash": hash_value(user_id),
            "credits": credits,
            "skill_id": skill_id,
            "app_id": app_id,
            "idempotency_key": f"audio:{task_id}:{request_id}",
            "usage_details": usage_details,
            "api_key_hash": api_key_hash,
            "device_hash": device_hash,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{INTERNAL_API_BASE_URL}/internal/billing/charge",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        logger.info("%s Charged %s credits for audio generation", log_prefix, credits)
    except Exception as exc:
        logger.error("%s Failed to charge audio generation credits: %s", log_prefix, exc, exc_info=True)
        if raise_on_failure:
            raise


async def ensure_audio_credit_headroom(
    *,
    user_id: str,
    estimated_credits: int,
    operation_name: str,
    log_prefix: str,
) -> None:
    await ensure_credit_headroom(
        user_id=user_id,
        estimated_credits=estimated_credits,
        log_prefix=log_prefix,
        operation_name=operation_name,
    )


async def store_generated_audio_asset(
    task: BaseServiceTask,
    *,
    app_id: str,
    skill_id: str,
    user_id: str,
    user_vault_key_id: Optional[str],
    chat_id: Optional[str],
    message_id: Optional[str],
    external_request: bool,
    embed_id: str,
    audio_bytes: bytes,
    mime_type: str,
    duration_seconds: float,
    model: str,
    generation_type: str,
    prompt: Optional[str],
    text_preview: Optional[str],
    extra_content: dict[str, Any],
    original_filename_prefix: str,
    log_prefix: str,
) -> dict[str, Any]:
    """Store encrypted generated audio and return result/embed metadata."""
    if not user_id:
        raise ValueError("Generated audio storage requires user_id")
    if not audio_bytes:
        raise ValueError("Generated audio bytes are empty")

    vault_key_id = await resolve_user_vault_key_id(
        task,
        user_id=user_id,
        supplied_vault_key_id=user_vault_key_id,
    )
    encrypted = encrypt_media_variants(
        {"original": audio_bytes},
        write_version=load_media_write_version(),
    )
    vault_wrapped_aes_key, _ = await task._encryption_service.encrypt_with_user_key(
        encrypted.aes_key_b64,
        vault_key_id,
    )
    if not vault_wrapped_aes_key:
        raise RuntimeError("Failed to wrap generated audio AES key with Vault")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    extension = extension_for_mime(mime_type)
    s3_key = f"{user_id}/{timestamp}_{unique_id}_{skill_id}_original.{extension}"
    await task._s3_service.upload_file(
        bucket_key="chatfiles",
        file_key=s3_key,
        content=encrypted.payloads["original"],
        content_type="application/octet-stream",
    )

    variant = GeneratedAssetVariant(
        s3_key=s3_key,
        size_bytes=len(audio_bytes),
        format=extension,
        mime_type=mime_type or "audio/mpeg",
        duration_seconds=duration_seconds if duration_seconds else None,
    ).to_metadata()
    variant.update(encrypted.metadata.get("original") or {})
    files_metadata = {"original": variant}
    from backend.core.api.app.services.s3.config import get_bucket_name

    chatfiles_bucket = get_bucket_name("chatfiles")
    s3_base_url = f"https://{chatfiles_bucket}.{task._s3_service.base_domain}"
    now_ts = int(datetime.now(timezone.utc).timestamp())
    original_filename = f"{original_filename_prefix}_{embed_id[:8]}.{extension}"

    upload_record_stored = await index_generated_asset(
        task,
        user_id=user_id,
        embed_id=embed_id,
        media_type="audio",
        files_metadata=files_metadata,
        s3_base_url=s3_base_url,
        aes_key_b64=encrypted.aes_key_b64,
        nonce_b64=encrypted.legacy_nonce_b64 or "",
        vault_wrapped_aes_key=vault_wrapped_aes_key,
        created_at=now_ts,
        content_hash_source=audio_bytes,
        original_filename=original_filename,
        content_type=mime_type or "audio/mpeg",
        log_prefix=log_prefix,
        provenance_metadata={
            "labeling": "audio_container_metadata",
            "visual_watermark": False,
            "provider_watermarking": "none",
        },
    )
    if not upload_record_stored:
        try:
            await task._s3_service.delete_file(bucket_key="chatfiles", file_key=s3_key)
        except Exception as cleanup_exc:
            logger.warning("%s Failed to clean up audio S3 object after index failure: %s", log_prefix, cleanup_exc)
        raise RuntimeError("Failed to index generated audio in account storage")

    await cache_s3_file_keys(task, embed_id=embed_id, files_metadata=files_metadata, log_prefix=log_prefix)
    generated_at = datetime.now(timezone.utc).isoformat()
    content = {
        "app_id": app_id,
        "skill_id": skill_id,
        "type": "audio",
        "status": "finished",
        "generation_type": generation_type,
        "provider": "ElevenLabs",
        "model": model,
        "mime_type": mime_type or "audio/mpeg",
        "duration_seconds": duration_seconds,
        "byte_length": len(audio_bytes),
        "files": files_metadata,
        "s3_base_url": s3_base_url,
        "aes_key": encrypted.aes_key_b64,
        "aes_nonce": encrypted.legacy_nonce_b64 or "",
        "vault_wrapped_aes_key": vault_wrapped_aes_key,
        "generated_at": generated_at,
        "watermarking": "metadata_only",
        "provenance": {
            "ai_generated": True,
            "labeling": "audio_container_metadata",
            "visual_watermark": False,
            "provider_watermarking": "none",
        },
        **extra_content,
    }
    if prompt is not None:
        content["prompt"] = prompt
    if text_preview is not None:
        content["text_preview"] = text_preview

    if chat_id and message_id and not external_request:
        from toon_format import encode as toon_encode
        from backend.core.api.app.services.embed_service import EmbedService

        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
        )
        await embed_service.send_embed_data_to_client(
            embed_id=embed_id,
            embed_type="app_skill_use",
            content_toon=toon_encode(content),
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=hash_value(user_id),
            status="finished",
            encryption_mode="client",
            created_at=now_ts,
            updated_at=now_ts,
            log_prefix=log_prefix,
            check_cache_status=False,
        )

    rest_files_metadata = {
        name: {
            **metadata,
            "download_url": build_download_url(
                base_url=PUBLIC_API_BASE_URL,
                asset_id=embed_id,
                variant=name,
                token=create_download_token(asset_id=embed_id, user_id=user_id, variant=name),
            ),
            "download_expires_at": int(datetime.now(timezone.utc).timestamp()) + TOKEN_TTL_SECONDS,
        }
        for name, metadata in files_metadata.items()
    }
    result_payload = dict(content)
    result_payload["embed_id"] = embed_id
    result_payload["user_id_hash"] = hash_value(user_id)
    result_payload["files"] = rest_files_metadata if external_request else files_metadata
    if external_request:
        result_payload.pop("aes_key", None)
        result_payload.pop("aes_nonce", None)
        result_payload.pop("vault_wrapped_aes_key", None)
    return result_payload


async def send_audio_error_embed(
    task: BaseServiceTask,
    *,
    app_id: str,
    skill_id: str,
    arguments: dict[str, Any],
    error_message: str,
    log_prefix: str,
) -> None:
    embed_id = arguments.get("embed_id")
    user_id = arguments.get("user_id")
    chat_id = arguments.get("chat_id")
    message_id = arguments.get("message_id")
    if not embed_id or not user_id or not chat_id or not message_id:
        return

    from toon_format import encode as toon_encode
    from backend.core.api.app.services.embed_service import EmbedService

    content = {
        "app_id": app_id,
        "skill_id": skill_id,
        "type": "audio",
        "status": "error",
        "error": error_message,
        "prompt": arguments.get("prompt"),
        "text_preview": arguments.get("text_preview"),
        "model": arguments.get("model"),
    }
    embed_service = EmbedService(
        cache_service=task._cache_service,
        directus_service=task._directus_service,
        encryption_service=task._encryption_service,
    )
    now_ts = int(datetime.now(timezone.utc).timestamp())
    await embed_service.send_embed_data_to_client(
        embed_id=embed_id,
        embed_type="app_skill_use",
        content_toon=toon_encode(content),
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=hash_value(str(user_id)),
        status="error",
        encryption_mode="client",
        created_at=now_ts,
        updated_at=now_ts,
        log_prefix=f"{log_prefix} [ERROR_EMBED]",
        check_cache_status=False,
    )
