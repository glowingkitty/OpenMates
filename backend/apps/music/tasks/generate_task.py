# backend/apps/music/tasks/generate_task.py
#
# Celery task for AI music generation. Mirrors the generated-image storage
# model: local AES-GCM encryption for S3 files plus client-encrypted embed
# metadata delivered over WebSocket.

import asyncio
import base64
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.providers.google.gemini_music import generate_music_google_lyria
from backend.shared.python_utils.billing_utils import MINIMUM_CREDITS_CHARGED, calculate_total_credits

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extension_for_mime(mime_type: str) -> str:
    normalized = (mime_type or "").split(";")[0].lower()
    if normalized in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    if normalized in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return "wav"
    if normalized in {"audio/mp4", "audio/m4a"}:
        return "m4a"
    if normalized == "audio/ogg":
        return "ogg"
    return "wav"


async def _charge_music_generation_credits(
    user_id: str,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    model_ref: Optional[str],
    chat_id: Optional[str],
    message_id: Optional[str],
    log_prefix: str,
) -> None:
    """Charge one generated-track unit. Billing failures are logged only."""
    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN

        pricing_config = None
        if model_ref and "/" in model_ref:
            provider_id, model_suffix = model_ref.split("/", 1)
            endpoint = f"{INTERNAL_API_BASE_URL}/internal/config/provider_model_pricing/{provider_id}/{model_suffix}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(endpoint, headers=headers)
                if response.status_code == 200:
                    pricing_config = response.json()

        credits_charged = (
            calculate_total_credits(pricing_config=pricing_config, units_processed=1)
            if pricing_config
            else MINIMUM_CREDITS_CHARGED
        )
        if credits_charged <= 0:
            return

        charge_payload = {
            "user_id": user_id,
            "user_id_hash": user_id_hash,
            "credits": credits_charged,
            "skill_id": skill_id,
            "app_id": app_id,
            "usage_details": {
                "chat_id": chat_id,
                "message_id": message_id,
                "units_processed": 1,
                "model_used": model_ref,
                "server_provider": "Google Vertex AI",
                "server_region": "global",
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{INTERNAL_API_BASE_URL}/internal/billing/charge", json=charge_payload, headers=headers)
            response.raise_for_status()
        logger.info("%s Charged %s credits for music generation", log_prefix, credits_charged)
    except Exception as exc:
        logger.error("%s Failed to charge music generation credits: %s", log_prefix, exc, exc_info=True)


@app.task(
    bind=True,
    name="apps.music.tasks.skill_generate",
    base=BaseServiceTask,
    queue="app_music",
    soft_time_limit=300,
    time_limit=330,
)
def generate_music_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    return asyncio.run(_async_generate_music(self, app_id, skill_id, arguments))


async def _async_generate_music(task: BaseServiceTask, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    task_id = task.request.id
    log_prefix = f"[Task ID: {task_id}]"
    logger.info("%s Starting music generation task", log_prefix)

    try:
        await task.initialize_services()

        prompt = arguments.get("prompt")
        user_id = arguments.get("user_id")
        chat_id = arguments.get("chat_id")
        message_id = arguments.get("message_id")
        external_request = bool(arguments.get("external_request"))
        embed_id = arguments.get("embed_id") or str(uuid.uuid4())
        mode = arguments.get("mode") or "background"
        lyrics = arguments.get("lyrics")
        style = arguments.get("style")
        duration_seconds = int(arguments.get("duration_seconds") or 30)
        negative_prompt = arguments.get("negative_prompt")
        seed = arguments.get("seed")
        model = arguments.get("model") or "lyria-3-pro-preview"
        model_ref = arguments.get("full_model_reference") or f"google/{model}"

        if not prompt or not user_id:
            raise ValueError("Missing required prompt or user_id")

        enriched_prompt_parts = [str(prompt)]
        if mode:
            enriched_prompt_parts.append(f"Use case: {mode}.")
        if style:
            enriched_prompt_parts.append(f"Style: {style}.")
        if lyrics:
            enriched_prompt_parts.append(f"Lyrics:\n{lyrics}")
        enriched_prompt = "\n".join(enriched_prompt_parts)

        generated = await generate_music_google_lyria(
            prompt=enriched_prompt,
            secrets_manager=task._secrets_manager,
            model_id=model,
            duration_seconds=duration_seconds,
            negative_prompt=negative_prompt,
            seed=seed,
        )

        hashed_user_id = _hash_value(user_id)
        if not external_request:
            await _charge_music_generation_credits(
                user_id=user_id,
                user_id_hash=hashed_user_id,
                app_id=app_id,
                skill_id=skill_id,
                model_ref=model_ref,
                chat_id=chat_id,
                message_id=message_id,
                log_prefix=log_prefix,
            )

        success, user_profile, error_msg = await task._directus_service.get_user_profile(user_id)
        if not success or not isinstance(user_profile, dict):
            raise RuntimeError(f"User profile not found for {user_id}: {error_msg}")
        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            raise RuntimeError(f"Vault key ID not found for user {user_id}")

        aes_key = os.urandom(32)
        nonce = os.urandom(12)
        aesgcm = AESGCM(aes_key)
        aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
        vault_wrapped_aes_key, _ = await task._encryption_service.encrypt_with_user_key(aes_key_b64, vault_key_id)
        if not vault_wrapped_aes_key:
            raise RuntimeError("Failed to wrap music AES key with Vault")
        nonce_b64 = base64.b64encode(nonce).decode("utf-8")

        encrypted_audio = aesgcm.encrypt(nonce, generated.audio_bytes, None)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        audio_format = _extension_for_mime(generated.mime_type)
        s3_key = f"{user_id}/{timestamp}_{unique_id}_music_original.{audio_format}"
        await task._s3_service.upload_file(
            bucket_key="chatfiles",
            file_key=s3_key,
            content=encrypted_audio,
            content_type="application/octet-stream",
        )

        files_metadata = {
            "original": {
                "s3_key": s3_key,
                "size_bytes": len(generated.audio_bytes),
                "format": audio_format,
                "mime_type": generated.mime_type,
                "duration_seconds": duration_seconds,
            }
        }
        chatfiles_bucket = get_bucket_name("chatfiles")
        s3_base_url = f"https://{chatfiles_bucket}.{task._s3_service.base_domain}"
        generated_at = datetime.now(timezone.utc).isoformat()

        embed_content = {
            "app_id": app_id,
            "skill_id": skill_id,
            "type": "music",
            "status": "finished",
            "prompt": prompt,
            "mode": mode,
            "lyrics": lyrics,
            "style": style,
            "duration_seconds": duration_seconds,
            "model": model,
            "provider": "Google Vertex AI",
            "files": files_metadata,
            "s3_base_url": s3_base_url,
            "aes_key": aes_key_b64,
            "aes_nonce": nonce_b64,
            "vault_wrapped_aes_key": vault_wrapped_aes_key,
            "generated_at": generated_at,
            "watermarking": "SynthID",
        }

        s3_file_keys = [{"bucket": "chatfiles", "key": s3_key}]
        try:
            client = await task._cache_service.client
            if client:
                await client.set(f"embed:{embed_id}:s3_file_keys", json.dumps(s3_file_keys), ex=3600)
        except Exception as exc:
            logger.warning("%s Failed to cache music S3 keys for cleanup: %s", log_prefix, exc)

        from toon_format import encode as toon_encode
        from backend.core.api.app.services.embed_service import EmbedService

        if chat_id and message_id:
            embed_service = EmbedService(
                cache_service=task._cache_service,
                directus_service=task._directus_service,
                encryption_service=task._encryption_service,
            )
            now_ts = int(datetime.now(timezone.utc).timestamp())
            await embed_service.send_embed_data_to_client(
                embed_id=embed_id,
                embed_type="app_skill_use",
                content_toon=toon_encode(embed_content),
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_id_hash=hashed_user_id,
                status="finished",
                encryption_mode="client",
                created_at=now_ts,
                updated_at=now_ts,
                log_prefix=log_prefix,
                check_cache_status=False,
            )

        return {
            "embed_id": embed_id,
            "type": "music",
            "status": "finished",
            "prompt": prompt,
            "mode": mode,
            "duration_seconds": duration_seconds,
            "model": model,
            "provider": "Google Vertex AI",
            "files": files_metadata,
            "s3_base_url": s3_base_url,
            "aes_key": aes_key_b64,
            "aes_nonce": nonce_b64,
            "vault_wrapped_aes_key": vault_wrapped_aes_key,
            "generated_at": generated_at,
            "watermarking": "SynthID",
        }

    except Exception as exc:
        logger.error("%s Music generation task failed: %s", log_prefix, exc, exc_info=True)
        try:
            await _send_error_embed(task, app_id, skill_id, arguments, str(exc), log_prefix)
        except Exception as embed_exc:
            logger.error("%s Failed to send music error embed: %s", log_prefix, embed_exc, exc_info=True)
        raise
    finally:
        await task.cleanup_services()


async def _send_error_embed(
    task: BaseServiceTask,
    app_id: str,
    skill_id: str,
    arguments: Dict[str, Any],
    error: str,
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
        "type": "music",
        "status": "error",
        "error": "Music generation failed. Please try again.",
        "prompt": arguments.get("prompt", ""),
        "model": arguments.get("model", "lyria-3-pro-preview"),
        "debug_error": error[:300],
    }
    await task.initialize_services()
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
        user_id_hash=_hash_value(user_id),
        status="error",
        encryption_mode="client",
        created_at=now_ts,
        updated_at=now_ts,
        log_prefix=f"{log_prefix} [ERROR_EMBED]",
        check_cache_status=False,
    )
