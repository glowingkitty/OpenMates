# backend/apps/videos/tasks/generate_task.py
#
# Celery task for AI video generation. Generated MP4 files are encrypted before
# S3 storage, indexed for account storage, and exposed to REST callers through
# short-lived server-side decrypted download URLs.

import asyncio
import base64
import hashlib
import logging
import math
import time
from io import BytesIO
from dataclasses import dataclass
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
from backend.shared.providers.fal import h3_turbo
from backend.shared.python_utils.encrypted_embed_images import _load_embed_record, resolve_encrypted_image_embed
from backend.shared.python_utils.fresh_upload_images import FreshUploadImageUnavailable, recover_fresh_upload_image
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
from backend.shared.python_utils.media_generation_safety import (
    MediaGenerationSafetyRejection,
    validate_media_generation_request,
)
from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError

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


H3_PROMOTION_END = datetime(2026, 11, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class GeneratedH3Video:
    video_bytes: bytes
    duration_seconds: float
    aspect_ratio: str
    mime_type: str = "video/mp4"
    resolution: str = "480p"


def _get_h3_duration_pricing(now: Optional[datetime] = None) -> tuple[float, dict]:
    # Official fal model page, verified 2026-10-19; promotion ends October 31.
    # https://fal.ai/models/minimax/h3-max-turbo/image-to-video
    price = 0.01625 if (now or datetime.now(timezone.utc)) < H3_PROMOTION_END else 0.025
    return price, {"per_second": {"credits": price * GENERATED_MEDIA_COST_MARKUP / USD_PER_CREDIT, "unit_name": "video_second"}}


def _h3_duration(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 < value < 30 else 5.0


async def _resolve_h3_source(task: Any, *, embed_id: str, user_id: str) -> Any:
    """Authorize source ownership before reading/decrypting its image in memory."""
    async def request_internal(method: str, path: str, payload: dict) -> dict:
        headers = {"X-Internal-Service-Token": INTERNAL_API_SHARED_TOKEN or ""}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, f"{INTERNAL_API_BASE_URL}/{path}", json=payload, headers=headers)
            if response.status_code in {401, 403, 404}:
                raise FreshUploadImageUnavailable("First-frame image is unavailable to this caller")
            response.raise_for_status()
            return response.json()

    # Source uploads can already have a client-encrypted chat embed in cache.
    # Recover upload_files' owner-bound encrypted-file metadata first; its Vault
    # wrapped media key is usable without decrypting the client's embed content.
    try:
        record = await recover_fresh_upload_image(embed_id=embed_id, user_id=user_id, request_internal=request_internal)
    except FreshUploadImageUnavailable:
        record = await _load_embed_record(embed_id=embed_id, cache_client=task._cache_service, directus_service=task._directus_service)
        encrypted_content = record.get("encrypted_content")
        if not isinstance(encrypted_content, str) or not encrypted_content.startswith("vault:"):
            raise ValueError("First-frame image is no longer available for generation")
    owner_hash = _hash_value(user_id)
    if (not isinstance(record, dict)
            or not (record.get("user_id") == user_id or record.get("hashed_user_id") == owner_hash)
            or (record.get("user_id") and record["user_id"] != user_id)
            or (record.get("hashed_user_id") and record["hashed_user_id"] != owner_hash)):
        raise ValueError("First-frame image is unavailable to this caller")
    expiry = record.get("expires_at")
    if expiry is not None and (type(expiry) is not int or expiry <= time.time()):
        raise ValueError("First-frame image is no longer available")
    success, profile, _ = await task._directus_service.get_user_profile(user_id)
    vault_key_id = profile.get("vault_key_id") if success and isinstance(profile, dict) else None
    return await resolve_encrypted_image_embed(
        embed_id=embed_id, user_vault_key_id=vault_key_id,
        cache_client=task._cache_service, directus_service=task._directus_service,
        encryption_service=task._encryption_service, s3_service=task._s3_service,
        bucket_name=get_bucket_name("chatfiles"), preloaded_records={embed_id: record},
    )


async def _generate_h3_video(task: Any, *, prompt: str, user_id: str, embed_id: str, source_ids: list[str], seed: Any) -> GeneratedH3Video:
    source = await _resolve_h3_source(task, embed_id=source_ids[0], user_id=user_id) if source_ids else None
    aspect_ratio = "16:9"
    if source:
        from PIL import Image
        with Image.open(BytesIO(source.content)) as image:
            aspect_ratio = f"{image.width}:{image.height}"
    from backend.shared.testing.voice_call_fixture import isolated_voice_fixture_enabled
    if isolated_voice_fixture_enabled() and prompt == "Animate the exact saved camera image with a gentle camera movement.":
        if not source:
            raise ValueError("The isolated camera fixture requires its saved source image")
        import subprocess
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", "pipe:0",
                   "-t", "1", "-vf", "scale=640:-2", "-r", "12", "-an", "-c:v", "libx264",
                   "-pix_fmt", "yuv420p", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]
        rendered = await asyncio.to_thread(subprocess.run, command, input=source.content, capture_output=True, timeout=15, check=True)
        return GeneratedH3Video(rendered.stdout, 1.0, aspect_ratio)
    key = await task._secrets_manager.get_secret("kv/data/providers/fal", "api_key")
    if not key:
        raise RuntimeError("H3 video generation is temporarily unavailable")
    # Fail closed on redelivery/uncertain accepted jobs. Never retry a paid submit
    # or silently dispatch another provider. Reservation outlives the task limit.
    cache_client = await task._cache_service.client
    if not cache_client or not await cache_client.set(f"h3-generation:{_hash_value(user_id)}:{embed_id}", "submitted", nx=True, ex=86400):
        raise RuntimeError("This video generation was already submitted or its status is unavailable")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, read=80), follow_redirects=False) as client:
        job = await h3_turbo.submit_clip(client, key=key, prompt=prompt,
            image_jpeg=source.content if source else None,
            image_mime_type=source.mime_type if source else "image/jpeg", seed=seed)
        clip = await h3_turbo.await_clip(client, key=key, job=job)
    return GeneratedH3Video(clip.data, _h3_duration(clip.measured_duration or clip.reported_duration), aspect_ratio)


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
    duration_seconds: float,
    resolution: str,
    chat_id: Optional[str],
    message_id: Optional[str],
    log_prefix: str,
    team_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> None:
    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        is_h3 = model_id == h3_turbo.MODEL
        price_usd_per_second, pricing_config = _get_h3_duration_pricing() if is_h3 else _get_veo_duration_pricing(model_id, resolution)
        if not is_h3 and (model_id not in VEO_PRICE_USD_PER_SECOND_BY_MODEL_AND_RESOLUTION or resolution not in VEO_PRICE_USD_PER_SECOND_BY_MODEL_AND_RESOLUTION.get(model_id, {})):
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
                "server_provider": "fal.ai" if is_h3 else "Google Gemini API",
                "server_region": "US",
            },
        }
        from backend.shared.python_utils.team_skill_billing import skill_billing_request
        billing_path, charge_payload = skill_billing_request(charge_payload, team_id, event_id=event_id or "")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{INTERNAL_API_BASE_URL}{billing_path}",
                json=charge_payload,
                headers=headers,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.error("%s Failed to charge video generation credits: %s", log_prefix, exc, exc_info=True)
        if team_id:
            raise


@app.task(bind=True, name="apps.videos.tasks.skill_generate", base=BaseServiceTask, queue="app_videos", soft_time_limit=2100, time_limit=2160)
def generate_video_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    from backend.shared.python_utils.generated_media_graph import run_generated_media_batch
    return asyncio.run(run_generated_media_batch(
        self, app_id=app_id, skill_id=skill_id, arguments=arguments,
        generate_one=_async_generate_video,
    )) if arguments.get("requests") else asyncio.run(_async_generate_video(self, app_id, skill_id, arguments))


async def _async_generate_video(task: BaseServiceTask, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    task_id = task.request.id
    log_prefix = f"[Task ID: {task_id}]"
    try:
        await task.initialize_core_services()
        prompt = str(arguments.get("prompt") or "").strip()
        user_id = arguments.get("user_id")
        chat_id = arguments.get("chat_id")
        message_id = arguments.get("message_id")
        external_request = bool(arguments.get("external_request"))
        embed_id = arguments.get("embed_id") or str(uuid.uuid4())
        model = arguments.get("model") or "veo-3.1-generate-preview"
        is_h3 = model == h3_turbo.MODEL
        provider_name = "fal.ai" if is_h3 else "Google Gemini API"
        watermarking = "not_reported" if is_h3 else "SynthID"
        model_ref = f"fal/{model}" if is_h3 else arguments.get("full_model_reference") or f"google/{model}"
        source_ids = arguments.get("input_embed_ids") or []
        if not isinstance(source_ids, list) or len(source_ids) > 1:
            raise ValueError("Provide at most one first-frame image")
        source_ids = [str(uuid.UUID(value)) for value in source_ids]
        if source_ids and not is_h3:
            raise ValueError("First-frame images currently require H3")
        if is_h3 and external_request:
            raise ValueError("H3 is available in authenticated chats and calls; REST currently supports Veo only")
        if not prompt or not user_id:
            raise ValueError("Missing required prompt or user_id")
        from backend.core.api.app.services.embed_service import EmbedService
        await EmbedService.assert_registered_output_can_generate(
            task._directus_service, embed_id=arguments.get("producer_embed_id") or embed_id, chat_id=chat_id,
            message_id=message_id, owner_hash=_hash_value(user_id),
        )

        media_decision = validate_media_generation_request(
            media_type="video",
            prompt=prompt,
            request_count=1,
        )
        if not media_decision.allowed:
            logger.warning(
                "%s [MediaSafety] REJECTED category=%s reason=%s",
                log_prefix,
                media_decision.category,
                media_decision.reason,
            )
            raise MediaGenerationSafetyRejection(media_decision)

        s3_service = await initialize_task_storage(task)
        await require_storage_available(s3_service)

        requested_duration_seconds = 5 if is_h3 else _normalize_veo_duration_seconds(arguments.get("duration_seconds"))
        requested_resolution = "480p" if is_h3 else _normalize_veo_resolution(arguments.get("resolution", "720p"))
        estimated_credits = (calculate_total_credits(pricing_config=_get_h3_duration_pricing()[1], duration_seconds=5.7)
                             if is_h3 else _estimate_veo_generation_credits(model, requested_resolution, requested_duration_seconds))
        if arguments.get("team_id"):
            from backend.shared.python_utils.team_skill_billing import ensure_team_skill_credit_headroom
            await ensure_team_skill_credit_headroom(task._directus_service, arguments["team_id"], user_id, estimated_credits)
        else:
            await ensure_credit_headroom(
                user_id=user_id,
                estimated_credits=estimated_credits,
                log_prefix=log_prefix,
                operation_name="video generation",
            )

        if is_h3:
            try:
                generated = await _generate_h3_video(task, prompt=prompt, user_id=user_id, embed_id=embed_id, source_ids=source_ids, seed=arguments.get("seed"))
            except h3_turbo.FalCompletedMediaError as exc:
                # Provider completion is billable even if CDN media delivery fails.
                await _charge_video_generation_credits(user_id, _hash_value(user_id), app_id, skill_id,
                    model_ref, model, _h3_duration(exc.reported_duration), "480p", chat_id, message_id,
                    log_prefix, team_id=arguments.get("team_id"), event_id=str(embed_id))
                raise
        else:
            generated = await generate_video_google_veo(
                prompt=prompt, secrets_manager=task._secrets_manager, model_id=model,
                aspect_ratio=arguments.get("aspect_ratio", "16:9"), duration_seconds=requested_duration_seconds,
                resolution=requested_resolution, seed=arguments.get("seed"),
            )
        generated_at = datetime.now(timezone.utc).isoformat()
        hashed_user_id = _hash_value(user_id)
        if not external_request or arguments.get("team_id"):
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
                team_id=arguments.get("team_id"),
                event_id=str(arguments.get("embed_id") or task.request.id),
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
            provenance_metadata={
                "labeling": "metadata_only",
                "visual_watermark": False,
                "provider_watermarking": watermarking,
            },
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
            "input_embed_ids": source_ids,
            "duration_seconds": generated.duration_seconds,
            "aspect_ratio": generated.aspect_ratio,
            "resolution": generated.resolution,
            "model": model,
            "provider": provider_name,
            "files": files_metadata,
            "s3_base_url": s3_base_url,
            "aes_key": aes_key_b64,
            "aes_nonce": nonce_b64,
            "vault_wrapped_aes_key": vault_wrapped_aes_key,
            "generated_at": generated_at,
            "watermarking": watermarking,
            "provenance": {
                "ai_generated": True,
                "labeling": "metadata_only",
                "visual_watermark": False,
                "provider_watermarking": watermarking,
            },
        }
        if chat_id and message_id:
            from backend.core.api.app.services.embed_service import EmbedService
            from backend.shared.python_utils.generated_media_graph import send_generated_media_child

            embed_service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
            child_embed_id = embed_id
            await send_generated_media_child(
                embed_service,
                parent_embed_id=arguments.get("producer_embed_id") or embed_id,
                child_embed_id=child_embed_id,
                child_index=int(arguments.get("media_child_index") or 0),
                content=embed_content,
                chat_id=chat_id, message_id=message_id, user_id=user_id,
                user_id_hash=hashed_user_id, created_at=now_ts, log_prefix=log_prefix,
            )
        else:
            child_embed_id = None

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
            "child_embed_id": child_embed_id,
            "child_embed_ids": [child_embed_id] if child_embed_id else [],
            "embed_ref": f"generated-videos-{child_embed_id.replace('-', '')[:12]}" if child_embed_id else None,
            "type": "video",
            "status": "finished",
            "prompt": prompt,
            "input_embed_ids": source_ids,
            "duration_seconds": generated.duration_seconds,
            "aspect_ratio": generated.aspect_ratio,
            "resolution": generated.resolution,
            "model": model,
            "provider": provider_name,
            "files": rest_files if external_request else files_metadata,
            "s3_base_url": s3_base_url,
            "generated_at": generated_at,
            "watermarking": watermarking,
            "provenance": {
                "ai_generated": True,
                "labeling": "metadata_only",
                "visual_watermark": False,
                "provider_watermarking": watermarking,
            },
            **({"team_id": arguments["team_id"]} if arguments.get("team_id") else {}),
        }
        if not external_request:
            result["aes_key"] = aes_key_b64
            result["aes_nonce"] = nonce_b64
            result["vault_wrapped_aes_key"] = vault_wrapped_aes_key
        return result
    except MediaGenerationSafetyRejection as exc:
        try:
            await _send_video_safety_rejection_embed(task, app_id, skill_id, arguments, exc, log_prefix)
        except RequiredRecoveryOutputError:
            raise
        except Exception as embed_exc:
            logger.error(
                "%s Failed to send video safety rejection embed: %s",
                log_prefix,
                embed_exc,
                exc_info=True,
            )
        return {
            "embed_id": arguments.get("embed_id"),
            "status": "rejected",
            **exc.decision.to_rejection_payload(),
        }
    finally:
        await task.cleanup_services()


async def _send_video_safety_rejection_embed(
    task: BaseServiceTask,
    app_id: str,
    skill_id: str,
    arguments: Dict[str, Any],
    rejection: MediaGenerationSafetyRejection,
    log_prefix: str,
) -> None:
    if arguments.get("media_batch"):
        return
    embed_id = arguments.get("embed_id")
    user_id = arguments.get("user_id")
    chat_id = arguments.get("chat_id")
    message_id = arguments.get("message_id")
    if not embed_id or not user_id or not chat_id or not message_id:
        return

    from toon_format import encode as toon_encode
    from backend.core.api.app.services.embed_service import EmbedService

    payload = rejection.decision.to_rejection_payload()
    content = {
        "app_id": app_id,
        "skill_id": skill_id,
        "type": "video",
        "status": "error",
        "error": payload["user_facing_message"],
        "safety_rejection": True,
    }
    embed_service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
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
        log_prefix=f"{log_prefix} [MEDIA_SAFETY_REJECT]",
        check_cache_status=False,
    )
