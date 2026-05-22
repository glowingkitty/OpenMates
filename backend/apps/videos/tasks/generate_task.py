# backend/apps/videos/tasks/generate_task.py
#
# Celery task for AI video generation. Generated MP4 files are encrypted before
# S3 storage, indexed for account storage, and exposed to REST callers through
# short-lived server-side decrypted download URLs.

import asyncio
import base64
import hashlib
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
from backend.shared.providers.google.gemini_video import generate_video_google_veo
from backend.shared.python_utils.billing_utils import (
    MINIMUM_CREDITS_CHARGED,
    calculate_total_credits,
    ensure_credit_headroom,
)
from backend.shared.python_utils.generated_assets import (
    build_download_url,
    cache_s3_file_keys,
    create_download_token,
    index_generated_asset,
)

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "https://api.dev.openmates.org")
USD_PER_CREDIT = 0.001
GENERATED_MEDIA_COST_MARKUP = 1.5
VEO_PRICE_USD_PER_SECOND_BY_MODEL_AND_RESOLUTION = {
    # Official Gemini API pricing, verified 2026-05-22:
    # https://ai.google.dev/gemini-api/docs/pricing
    "veo-3.1-generate-preview": {"720p": 0.40, "1080p": 0.40, "4k": 0.60},
    "veo-3.1-fast-generate-preview": {"720p": 0.10, "1080p": 0.12, "4k": 0.30},
    "veo-3.1-lite-generate-preview": {"720p": 0.05, "1080p": 0.08},
}


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _get_veo_duration_pricing(model_id: str, resolution: str) -> tuple[float, dict[str, dict[str, float | str]]]:
    """Return official Veo per-second cost and per-second credit config."""
    price_usd_per_second = VEO_PRICE_USD_PER_SECOND_BY_MODEL_AND_RESOLUTION.get(model_id, {}).get(resolution)
    if price_usd_per_second is None:
        price_usd_per_second = VEO_PRICE_USD_PER_SECOND_BY_MODEL_AND_RESOLUTION["veo-3.1-generate-preview"]["720p"]
    credits_per_second = (price_usd_per_second * GENERATED_MEDIA_COST_MARKUP) / USD_PER_CREDIT
    return price_usd_per_second, {"per_second": {"credits": credits_per_second, "unit_name": "video_second"}}


def _normalize_veo_duration_seconds(duration_seconds: Any) -> int:
    duration = max(4, min(int(duration_seconds or 8), 8))
    return duration if duration in {4, 6, 8} else 8


def _normalize_veo_resolution(resolution: Any) -> str:
    return resolution if resolution in {"720p", "1080p", "4k"} else "720p"


def _estimate_veo_generation_credits(model_id: str, resolution: str, duration_seconds: int) -> int:
    _, pricing_config = _get_veo_duration_pricing(model_id, resolution)
    return calculate_total_credits(pricing_config=pricing_config, duration_seconds=duration_seconds)


async def _charge_video_generation_credits(
    user_id: str,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    model_ref: Optional[str],
    model_id: str,
    duration_seconds: int,
    resolution: str,
    chat_id: Optional[str],
    message_id: Optional[str],
    log_prefix: str,
) -> None:
    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        price_usd_per_second, pricing_config = _get_veo_duration_pricing(model_id, resolution)
        if model_id not in VEO_PRICE_USD_PER_SECOND_BY_MODEL_AND_RESOLUTION or resolution not in VEO_PRICE_USD_PER_SECOND_BY_MODEL_AND_RESOLUTION.get(model_id, {}):
            logger.warning(
                "%s Unknown Veo pricing for model=%s resolution=%s; falling back to standard 720p rate",
                log_prefix,
                model_id,
                resolution,
            )
        credits_charged = (
            calculate_total_credits(pricing_config=pricing_config, duration_seconds=duration_seconds)
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
                "units_processed": duration_seconds,
                "duration_seconds": duration_seconds,
                "unit_name": "generated_video_second",
                "model_used": model_ref,
                "resolution": resolution,
                "provider_price_usd_per_second": price_usd_per_second,
                "server_provider": "Google Gemini API",
                "server_region": "US",
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{INTERNAL_API_BASE_URL}/internal/billing/charge",
                json=charge_payload,
                headers=headers,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.error("%s Failed to charge video generation credits: %s", log_prefix, exc, exc_info=True)


@app.task(bind=True, name="apps.videos.tasks.skill_generate", base=BaseServiceTask, queue="app_videos", soft_time_limit=600, time_limit=660)
def generate_video_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    return asyncio.run(_async_generate_video(self, app_id, skill_id, arguments))


async def _async_generate_video(task: BaseServiceTask, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    task_id = task.request.id
    log_prefix = f"[Task ID: {task_id}]"
    try:
        await task.initialize_services()
        prompt = str(arguments.get("prompt") or "").strip()
        user_id = arguments.get("user_id")
        chat_id = arguments.get("chat_id")
        message_id = arguments.get("message_id")
        external_request = bool(arguments.get("external_request"))
        embed_id = arguments.get("embed_id") or str(uuid.uuid4())
        model = arguments.get("model") or "veo-3.1-generate-preview"
        model_ref = arguments.get("full_model_reference") or f"google/{model}"
        if not prompt or not user_id:
            raise ValueError("Missing required prompt or user_id")

        requested_duration_seconds = _normalize_veo_duration_seconds(arguments.get("duration_seconds"))
        requested_resolution = _normalize_veo_resolution(arguments.get("resolution", "720p"))
        estimated_credits = _estimate_veo_generation_credits(model, requested_resolution, requested_duration_seconds)
        await ensure_credit_headroom(
            user_id=user_id,
            estimated_credits=estimated_credits,
            log_prefix=log_prefix,
            operation_name="video generation",
        )

        generated = await generate_video_google_veo(
            prompt=prompt,
            secrets_manager=task._secrets_manager,
            model_id=model,
            aspect_ratio=arguments.get("aspect_ratio", "16:9"),
            duration_seconds=requested_duration_seconds,
            resolution=requested_resolution,
            seed=arguments.get("seed"),
        )
        generated_at = datetime.now(timezone.utc).isoformat()
        hashed_user_id = _hash_value(user_id)
        if not external_request:
            await _charge_video_generation_credits(
                user_id,
                hashed_user_id,
                app_id,
                skill_id,
                model_ref,
                model,
                generated.duration_seconds,
                generated.resolution,
                chat_id,
                message_id,
                log_prefix,
            )

        success, user_profile, error_msg = await task._directus_service.get_user_profile(user_id)
        if not success or not isinstance(user_profile, dict):
            raise RuntimeError(f"User profile not found for {user_id}: {error_msg}")
        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            raise RuntimeError(f"Vault key ID not found for user {user_id}")

        aes_key = os.urandom(32)
        nonce = os.urandom(12)
        aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
        vault_wrapped_aes_key, _ = await task._encryption_service.encrypt_with_user_key(aes_key_b64, vault_key_id)
        if not vault_wrapped_aes_key:
            raise RuntimeError("Failed to wrap video AES key with Vault")
        nonce_b64 = base64.b64encode(nonce).decode("utf-8")
        encrypted_video = AESGCM(aes_key).encrypt(nonce, generated.video_bytes, None)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        s3_key = f"{user_id}/{timestamp}_{uuid.uuid4().hex[:8]}_video_original.mp4"
        await task._s3_service.upload_file("chatfiles", s3_key, encrypted_video, "application/octet-stream")
        files_metadata = {
            "original": {
                "s3_key": s3_key,
                "size_bytes": len(generated.video_bytes),
                "format": "mp4",
                "mime_type": generated.mime_type,
                "duration_seconds": generated.duration_seconds,
            }
        }
        chatfiles_bucket = get_bucket_name("chatfiles")
        s3_base_url = f"https://{chatfiles_bucket}.{task._s3_service.base_domain}"
        now_ts = int(datetime.now(timezone.utc).timestamp())
        stored = await index_generated_asset(
            task,
            user_id=user_id,
            embed_id=embed_id,
            media_type="video",
            files_metadata=files_metadata,
            s3_base_url=s3_base_url,
            aes_key_b64=aes_key_b64,
            nonce_b64=nonce_b64,
            vault_wrapped_aes_key=vault_wrapped_aes_key,
            created_at=now_ts,
            content_hash_source=generated.video_bytes,
            original_filename=f"openmates_generated_video_{embed_id[:8]}.mp4",
            content_type=generated.mime_type,
            log_prefix=log_prefix,
        )
        if not stored:
            await task._s3_service.delete_file("chatfiles", s3_key)
            raise RuntimeError("Failed to index generated video in account storage")
        await cache_s3_file_keys(task, embed_id=embed_id, files_metadata=files_metadata, log_prefix=log_prefix)

        embed_content = {
            "app_id": app_id,
            "skill_id": skill_id,
            "type": "video",
            "status": "finished",
            "prompt": prompt,
            "duration_seconds": generated.duration_seconds,
            "aspect_ratio": generated.aspect_ratio,
            "resolution": generated.resolution,
            "model": model,
            "provider": "Google Gemini API",
            "files": files_metadata,
            "s3_base_url": s3_base_url,
            "aes_key": aes_key_b64,
            "aes_nonce": nonce_b64,
            "vault_wrapped_aes_key": vault_wrapped_aes_key,
            "generated_at": generated_at,
            "watermarking": "SynthID",
        }
        if chat_id and message_id:
            from toon_format import encode as toon_encode
            from backend.core.api.app.services.embed_service import EmbedService

            embed_service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
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

        rest_files = {
            name: {
                **meta,
                "download_url": build_download_url(
                    base_url=PUBLIC_API_BASE_URL,
                    asset_id=embed_id,
                    variant=name,
                    token=create_download_token(asset_id=embed_id, user_id=user_id, variant=name),
                ),
                "download_expires_at": int(datetime.now(timezone.utc).timestamp()) + 900,
            }
            for name, meta in files_metadata.items()
        }
        result = {
            "embed_id": embed_id,
            "type": "video",
            "status": "finished",
            "prompt": prompt,
            "duration_seconds": generated.duration_seconds,
            "aspect_ratio": generated.aspect_ratio,
            "resolution": generated.resolution,
            "model": model,
            "provider": "Google Gemini API",
            "files": rest_files if external_request else files_metadata,
            "s3_base_url": s3_base_url,
            "generated_at": generated_at,
            "watermarking": "SynthID",
        }
        if not external_request:
            result["aes_key"] = aes_key_b64
            result["aes_nonce"] = nonce_b64
            result["vault_wrapped_aes_key"] = vault_wrapped_aes_key
        return result
    finally:
        await task.cleanup_services()
