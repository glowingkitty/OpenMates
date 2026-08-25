# backend/apps/audio/tasks/generate_task.py
#
# Celery task for audio.generate sound effects.
# The task owns ElevenLabs provider calls, success-only credit charging, encrypted
# chatfiles storage, generated-asset download metadata, and in-place embed
# completion for chat clients.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.apps.audio.pricing import calculate_sound_effect_credits
from backend.apps.audio.tasks.common import (
    charge_audio_generation_credits,
    ensure_audio_credit_headroom,
    hash_value,
    send_audio_error_embed,
    store_generated_audio_asset,
)
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.providers.elevenlabs import ElevenLabsClient
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request
from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available

logger = logging.getLogger(__name__)


async def dispatch_async_skill_continuation(**kwargs: Any) -> Any:
    """Lazy import keeps audio task modules usable in lightweight unit tests."""
    from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation as _dispatch

    return await _dispatch(**kwargs)


@app.task(
    bind=True,
    name="apps.audio.tasks.skill_generate",
    base=BaseServiceTask,
    queue="app_music",
    soft_time_limit=180,
    time_limit=210,
)
def generate_audio_task(self, app_id: str, skill_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Generate one sound effect asynchronously."""
    return asyncio.run(_async_generate_audio(self, app_id, skill_id, arguments))


async def _async_generate_audio(
    task: BaseServiceTask,
    app_id: str,
    skill_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    task_id = task.request.id
    embed_id = arguments.get("embed_id")
    request_id = arguments.get("request_id") or 1
    prompt = str(arguments.get("prompt") or "").strip()
    user_id = str(arguments.get("user_id") or "")
    chat_id = arguments.get("chat_id")
    message_id = arguments.get("message_id")
    external_request = bool(arguments.get("external_request"))
    model = str(arguments.get("model") or "eleven_text_to_sound_v2")
    duration_seconds = float(arguments.get("duration_seconds") or 1.0)
    model_ref = str(arguments.get("full_model_reference") or f"elevenlabs/{model}")
    log_prefix = f"[audio.generate] [task:{task_id[:8]}] [embed:{str(embed_id)[:8]}]"

    try:
        await task.initialize_core_services()
        if not prompt or not user_id or not embed_id:
            raise ValueError("Missing required audio.generate task context")

        safety = validate_media_generation_request(
            media_type="sound_effect",
            prompt=prompt,
            request_count=1,
        )
        if not safety.allowed:
            result_payload = {
                "id": request_id,
                "embed_id": embed_id,
                "user_id_hash": hash_value(user_id),
                "status": "error",
                "prompt": prompt,
                "generation_type": "sound_effect",
                "provider": "ElevenLabs",
                "model": model,
                "duration_seconds": duration_seconds,
                "byte_length": 0,
                "credits_charged": None,
                "error": safety.user_facing_message or "This sound effect request could not be generated.",
            }
            await send_audio_error_embed(
                task,
                app_id=app_id,
                skill_id=skill_id,
                arguments=arguments,
                error_message=result_payload["error"],
                log_prefix=log_prefix,
            )
            await dispatch_async_skill_continuation(
                cache_service=task._cache_service,
                async_task_id=task_id,
                completed_results=[result_payload],
                result_status="error",
                request_metadata={"prompt": prompt, "provider": "ElevenLabs"},
            )
            return result_payload

        s3_service = await initialize_task_storage(task)
        await require_storage_available(s3_service)

        estimated_credits = calculate_sound_effect_credits(duration_seconds=duration_seconds)
        await ensure_audio_credit_headroom(
            user_id=user_id,
            estimated_credits=estimated_credits,
            operation_name="sound effect generation",
            log_prefix=log_prefix,
        )

        client = ElevenLabsClient(secrets_manager=task._secrets_manager)
        generated = await client.generate_sound_effect(
            prompt=prompt,
            duration_seconds=duration_seconds,
            prompt_influence=float(arguments.get("prompt_influence") or 0.3),
            loop=bool(arguments.get("loop")),
            output_format=str(arguments.get("output_format") or "mp3_44100_128"),
            model=model,
        )
        actual_duration_seconds = float(generated.duration_seconds or duration_seconds)
        credits = calculate_sound_effect_credits(duration_seconds=actual_duration_seconds)
        result_payload = await store_generated_audio_asset(
            task,
            app_id=app_id,
            skill_id=skill_id,
            user_id=user_id,
            user_vault_key_id=arguments.get("user_vault_key_id"),
            chat_id=chat_id,
            message_id=message_id,
            external_request=external_request,
            embed_id=str(embed_id),
            audio_bytes=generated.audio_bytes,
            mime_type=generated.mime_type or "audio/mpeg",
            duration_seconds=actual_duration_seconds,
            model=generated.model or model,
            generation_type="sound_effect",
            prompt=prompt,
            text_preview=None,
            extra_content={},
            original_filename_prefix="openmates_generated_sound_effect",
            log_prefix=log_prefix,
        )
        result_payload.update({"id": request_id, "credits_charged": credits})
        await charge_audio_generation_credits(
            user_id=user_id,
            app_id=app_id,
            skill_id=skill_id,
            task_id=task_id,
            request_id=request_id,
            credits=credits,
            model_ref=model_ref,
            duration_seconds=actual_duration_seconds,
            chat_id=chat_id,
            message_id=message_id,
            external_request=external_request,
            api_key_hash=arguments.get("api_key_hash"),
            device_hash=arguments.get("device_hash"),
            api_key_name=arguments.get("api_key_name"),
            log_prefix=log_prefix,
        )
        await dispatch_async_skill_continuation(
            cache_service=task._cache_service,
            async_task_id=task_id,
            completed_results=[result_payload],
            request_metadata={"prompt": prompt, "provider": "ElevenLabs"},
        )
        return result_payload
    except Exception as exc:
        logger.error("%s Audio generation task failed: %s", log_prefix, exc, exc_info=True)
        result_payload = {
            "id": request_id,
            "embed_id": embed_id,
            "user_id_hash": hash_value(user_id) if user_id else None,
            "status": "error",
            "prompt": prompt,
            "generation_type": "sound_effect",
            "provider": "ElevenLabs",
            "model": model,
            "duration_seconds": duration_seconds,
            "byte_length": 0,
            "credits_charged": None,
            "error": "Audio generation is temporarily unavailable.",
        }
        try:
            await send_audio_error_embed(
                task,
                app_id=app_id,
                skill_id=skill_id,
                arguments=arguments,
                error_message=result_payload["error"],
                log_prefix=log_prefix,
            )
            await dispatch_async_skill_continuation(
                cache_service=task._cache_service,
                async_task_id=task_id,
                completed_results=[result_payload],
                result_status="error",
                request_metadata={"prompt": prompt, "provider": "ElevenLabs"},
            )
        except Exception as embed_exc:
            logger.error("%s Failed to publish audio.generate error state: %s", log_prefix, embed_exc, exc_info=True)
        return result_payload
    finally:
        await task.cleanup_services()
