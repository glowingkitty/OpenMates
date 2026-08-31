# backend/apps/audio/assistant_speech/segment_task.py
#
# Celery execution for one transient assistant-response speech segment. The task
# resolves a server-only voice profile, encrypts one chatfiles object through the
# existing generated-asset helper, and publishes content-free status updates.
# Speakable source text is never written to Directus or task logs.

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Any

from backend.apps.audio.assistant_speech.persistence import (
    claim_speech_segment_execution,
    cleanup_generated_speech_asset,
    finalize_speech_segment_execution,
    get_speech_segment,
    safe_segment_status,
    update_segment_status,
)
from backend.apps.audio.assistant_speech.voice_profiles import resolve_assistant_voice_profile
from backend.apps.audio.assistant_speech.worker import generate_speech_segment
from backend.apps.audio.pricing import calculate_speech_credits, estimate_speech_duration_seconds
from backend.apps.audio.tasks.common import (
    charge_audio_generation_credits,
    ensure_audio_credit_headroom,
    store_generated_audio_asset,
)
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.providers.elevenlabs import ElevenLabsClient
from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available

logger = logging.getLogger(__name__)
class SpeechExecutionInProgress(Exception):
    """A concurrent delivery owns the provider call for this segment."""


async def _delete_generated_speech_asset(task: BaseServiceTask, generated_asset_id: str) -> None:
    """Compensate storage when cancellation wins after an upload completes."""
    await cleanup_generated_speech_asset(
        task._directus_service,
        generated_asset_id,
        delete_file=lambda file_key: task._s3_service.delete_file(bucket_key="chatfiles", file_key=file_key),
    )


@app.task(bind=True, name="apps.audio.tasks.assistant_speech_segment", base=BaseServiceTask, queue="app_music", soft_time_limit=180, time_limit=210)
def assistant_speech_segment_task(self: BaseServiceTask, arguments: dict[str, Any]) -> dict[str, object]:
    """Generate exactly one approved assistant speech segment."""
    return asyncio.run(_async_generate_assistant_speech_segment(self, arguments))


async def _async_generate_assistant_speech_segment(task: BaseServiceTask, arguments: dict[str, Any]) -> dict[str, object]:
    segment_id = str(arguments.get("segment_id") or "")
    user_id = str(arguments.get("user_id") or "")
    text = str(arguments.get("speakable_text") or "").strip()
    if not segment_id or not user_id:
        raise ValueError("Missing assistant speech task context")
    log_prefix = f"[assistant-speech segment:{segment_id[:8]}]"
    generated_asset_id = ""
    try:
        await task.initialize_core_services()
        existing = await get_speech_segment(task._directus_service, segment_id)
        if existing and existing.get("status") == "ready":
            return safe_segment_status(existing)
        if existing is None:
            return {"segment_id": segment_id, "status": "cancelled"}
        if not text and existing.get("status") != "settlement_pending":
            raise ValueError("Missing assistant speech task context")
        lease_id = uuid.uuid4().hex
        claimed = await claim_speech_segment_execution(task._directus_service, segment_id, lease_id=lease_id)
        if claimed is None:
            raise SpeechExecutionInProgress
        storage = await initialize_task_storage(task)
        await require_storage_available(storage)
        profile = resolve_assistant_voice_profile(
            str(arguments.get("voice_profile_key") or ""),
            version=int(arguments.get("voice_profile_version") or 0),
        )

        async def ensure_active() -> None:
            current = await get_speech_segment(task._directus_service, segment_id)
            if current is None or current.get("status") != "generating" or current.get("lease_id") != lease_id:
                raise SpeechExecutionInProgress

        async def safety_check(*, text: str) -> dict[str, object]:
            # Resolve the optional safeguard SDK only when a worker executes a segment.
            from backend.apps.audio.skills.speak_skill import classify_audio_speech_safety

            decision = await classify_audio_speech_safety(
                text=text,
                voice=profile.key,
                accent="en_us",
                style="natural",
                secrets_manager=task._secrets_manager,
            )
            return {"approved": decision.approved, "safe_error": decision.user_facing_message}

        async def provider_generate(*, text: str, voice_profile: dict[str, object]) -> dict[str, object]:
            await ensure_active()
            request = profile.elevenlabs_request()
            generated = await ElevenLabsClient(secrets_manager=task._secrets_manager).text_to_speech(
                text=text,
                voice_id=str(request["voice_id"]),
                model=str(request["model"]),
                output_format=str(request["output_format"]),
                speed=float(dict(request["voice_settings"])["speed"]),
            )
            duration = generated.duration_seconds or estimate_speech_duration_seconds(text)
            return {"audio_bytes": generated.audio_bytes, "duration_seconds": duration, "mime_type": generated.mime_type}

        async def store_encrypted(*, audio_bytes: bytes, segment_id: str) -> dict[str, object]:
            nonlocal generated_asset_id
            await ensure_active()
            await store_generated_audio_asset(
                task,
                app_id="assistant_response_speech",
                skill_id="segment",
                user_id=user_id,
                user_vault_key_id=arguments.get("user_vault_key_id"),
                chat_id=str(arguments.get("chat_id") or ""),
                message_id=str(arguments.get("assistant_message_id") or ""),
                external_request=False,
                embed_id=segment_id,
                audio_bytes=audio_bytes,
                mime_type="audio/mpeg",
                duration_seconds=0,
                model=profile.model,
                generation_type="assistant_response_speech_segment",
                prompt=None,
                text_preview=None,
                extra_content={},
                original_filename_prefix="assistant_speech_segment",
                log_prefix=log_prefix,
            )
            # Encryption material remains in upload_files and its owner-scoped
            # generated-asset event; segment metadata stores only this reference.
            generated_asset_id = segment_id
            return {"generated_asset_id": generated_asset_id}

        async def charge_usage(*, idempotency_key: str, duration_seconds: float) -> dict[str, str]:
            await ensure_active()
            credits = calculate_speech_credits(model=profile.model, duration_seconds=duration_seconds)
            await charge_audio_generation_credits(
                user_id=user_id,
                app_id="assistant_response_speech",
                skill_id="segment",
                task_id=idempotency_key,
                request_id="success",
                credits=credits,
                model_ref=f"elevenlabs/{profile.model}",
                duration_seconds=duration_seconds,
                chat_id=str(arguments.get("chat_id") or ""),
                message_id=str(arguments.get("assistant_message_id") or ""),
                external_request=False,
                api_key_hash=None,
                device_hash=None,
                api_key_name=None,
                log_prefix=log_prefix,
                raise_on_failure=True,
            )
            return {"usage_id": f"audio:{idempotency_key}:success"}

        if existing.get("status") == "settlement_pending":
            pending_generated_asset_id = existing.get("pending_generated_asset_id")
            pending_duration = existing.get("pending_duration_seconds")
            if not isinstance(pending_generated_asset_id, str) or not isinstance(pending_duration, (int, float)):
                raise RuntimeError("Assistant speech settlement data is unavailable")
            await charge_usage(
                idempotency_key=f"assistant-speech:{arguments.get('chat_id')}:{arguments.get('assistant_message_id')}:{segment_id}:{arguments.get('source_hash')}:{profile.key}-v{profile.version}",
                duration_seconds=float(pending_duration),
            )
            await ensure_active()
            result = {"segment_id": segment_id, "status": "ready", "generated_asset_id": pending_generated_asset_id, "duration_seconds": float(pending_duration)}
        else:
            await ensure_audio_credit_headroom(
                user_id=user_id,
                estimated_credits=calculate_speech_credits(model=profile.model, duration_seconds=estimate_speech_duration_seconds(text)),
                operation_name="assistant response speech",
                log_prefix=log_prefix,
            )
            result = await generate_speech_segment(
                segment={
                    "segment_id": segment_id,
                    "chat_id": str(arguments.get("chat_id") or ""),
                    "assistant_message_id": str(arguments.get("assistant_message_id") or ""),
                    "source_hash": str(arguments.get("source_hash") or ""),
                    "speakable_text": text,
                },
                voice_profile={"profile_id": f"{profile.key}-v{profile.version}", "provider": profile.provider},
                safety_check=safety_check,
                provider_generate=provider_generate,
                store_encrypted=store_encrypted,
                charge_usage=charge_usage,
            )
        await ensure_active()
    except SpeechExecutionInProgress:
        if generated_asset_id:
            try:
                await _delete_generated_speech_asset(task, generated_asset_id)
            except Exception:
                logger.exception("%s Failed to compensate cancelled assistant speech asset", log_prefix)
        current = await get_speech_segment(task._directus_service, segment_id)
        return {"segment_id": segment_id, "status": "cancelled" if not current or current.get("status") == "cancelled" else "queued"}
    except Exception:
        logger.exception("%s Assistant speech segment failed", log_prefix)
        result = {"segment_id": segment_id, "status": "error", "error": "Speech is temporarily unavailable.", "retryable": True}
    if result.get("status") == "ready":
        finalized = await finalize_speech_segment_execution(
            task._directus_service,
            segment_id,
            result,
            lease_id=lease_id,
            execution_version=int(claimed["execution_version"]),
        )
        if not finalized:
            if generated_asset_id:
                try:
                    await _delete_generated_speech_asset(task, generated_asset_id)
                except Exception:
                    logger.exception("%s Failed to compensate unfinalized assistant speech asset", log_prefix)
            return {"segment_id": segment_id, "status": "cancelled"}
    else:
        await update_segment_status(task._directus_service, segment_id, result)
    status = safe_segment_status(result)
    await task._cache_service.publish_event(
        f"chat_stream::{arguments.get('chat_id')}",
        {
            "type": "assistant_speech_status",
            "chat_id": str(arguments.get("chat_id") or ""),
            "user_id_hash": hashlib.sha256(user_id.encode()).hexdigest(),
            "message_id": str(arguments.get("assistant_message_id") or ""),
            "payload": status,
        },
    )
    return status
