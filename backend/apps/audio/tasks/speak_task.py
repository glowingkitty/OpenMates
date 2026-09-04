# backend/apps/audio/tasks/speak_task.py
#
# Celery task for audio.speak text-to-speech generation.
# The worker runs deterministic/Groq speech safety before ElevenLabs, then writes
# successful MP3 output as encrypted generated media and charges credits only for
# completed audio.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.apps.audio.pricing import DEFAULT_SPEECH_MODEL, calculate_speech_credits, estimate_speech_duration_seconds
from backend.apps.audio.skills.speak_skill import classify_audio_speech_safety
from backend.apps.audio.tasks.common import (
    charge_audio_generation_credits,
    ensure_audio_credit_headroom,
    hash_value,
    send_audio_error_embed,
    store_generated_audio_asset,
)
from backend.apps.audio.voice_presets import VOICE_PRESET_TO_ELEVENLABS_ID
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.providers.elevenlabs import ElevenLabsClient
from backend.shared.python_utils.storage_availability import initialize_task_storage, require_storage_available

logger = logging.getLogger(__name__)


async def dispatch_async_skill_continuation(**kwargs: Any) -> Any:
    """Lazy import keeps audio task modules usable in lightweight unit tests."""
    from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation as _dispatch

    return await _dispatch(**kwargs)


@app.task(
    bind=True,
    name="apps.audio.tasks.skill_speak",
    base=BaseServiceTask,
    queue="app_music",
    soft_time_limit=180,
    time_limit=210,
)
def speak_audio_task(self, app_id: str, skill_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Generate one text-to-speech audio asset asynchronously."""
    return asyncio.run(_async_speak_audio(self, app_id, skill_id, arguments))


async def _async_speak_audio(
    task: BaseServiceTask,
    app_id: str,
    skill_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    task_id = task.request.id
    embed_id = arguments.get("embed_id")
    request_id = arguments.get("request_id") or 1
    text = str(arguments.get("text") or "").strip()
    text_preview = str(arguments.get("text_preview") or text[:160]).strip()
    user_id = str(arguments.get("user_id") or "")
    chat_id = arguments.get("chat_id")
    message_id = arguments.get("message_id")
    external_request = bool(arguments.get("external_request"))
    voice = str(arguments.get("voice") or "warm_neutral")
    accent = str(arguments.get("accent") or "en_us")
    style = str(arguments.get("style") or "natural")
    model = str(arguments.get("model") or DEFAULT_SPEECH_MODEL)
    model_ref = str(arguments.get("full_model_reference") or f"elevenlabs/{model}")
    log_prefix = f"[audio.speak] [task:{task_id[:8]}] [embed:{str(embed_id)[:8]}]"

    try:
        await task.initialize_core_services()
        if not text or not user_id or not embed_id:
            raise ValueError("Missing required audio.speak task context")

        s3_service = await initialize_task_storage(task)
        await require_storage_available(s3_service)

        safety = await classify_audio_speech_safety(
            text=text,
            voice=voice,
            accent=accent,
            style=style,
            secrets_manager=task._secrets_manager,
        )
        if not safety.approved:
            logger.info("%s audio.speak rejected before provider call: %s", log_prefix, safety.category)
            result_payload = {
                "id": request_id,
                "embed_id": embed_id,
                "user_id_hash": hash_value(user_id),
                "status": "error",
                "text_preview": text_preview,
                "generation_type": "speech",
                "voice": voice,
                "accent": accent,
                "style": style,
                "provider": "ElevenLabs",
                "model": model,
                "byte_length": 0,
                "credits_charged": None,
                "error": safety.user_facing_message,
            }
            await send_audio_error_embed(
                task,
                app_id=app_id,
                skill_id=skill_id,
                arguments=arguments,
                error_message=safety.user_facing_message,
                log_prefix=log_prefix,
            )
            await dispatch_async_skill_continuation(
                cache_service=task._cache_service,
                async_task_id=task_id,
                completed_results=[result_payload],
                result_status="error",
                request_metadata={"text_preview": text_preview, "provider": "ElevenLabs"},
            )
            return result_payload

        estimated_duration_seconds = estimate_speech_duration_seconds(text)
        estimated_credits = calculate_speech_credits(model=model, duration_seconds=estimated_duration_seconds)
        await ensure_audio_credit_headroom(
            user_id=user_id,
            estimated_credits=estimated_credits,
            operation_name="speech generation",
            log_prefix=log_prefix,
        )

        try:
            voice_id = VOICE_PRESET_TO_ELEVENLABS_ID[voice]
        except KeyError:
            result_payload = {
                "id": request_id,
                "embed_id": embed_id,
                "user_id_hash": hash_value(user_id),
                "status": "error",
                "text_preview": text_preview,
                "generation_type": "speech",
                "voice": voice,
                "accent": accent,
                "style": style,
                "provider": "ElevenLabs",
                "model": model,
                "byte_length": 0,
                "credits_charged": None,
                "error": "Selected voice preset is temporarily unavailable.",
            }
            await send_audio_error_embed(
                task,
                app_id=app_id,
                skill_id=skill_id,
                arguments=arguments,
                error_message=result_payload["error"],
                log_prefix=log_prefix,
            )
            return result_payload

        client = ElevenLabsClient(secrets_manager=task._secrets_manager)
        generated = await client.text_to_speech(
            text=text,
            voice_id=voice_id,
            model=model,
            output_format=str(arguments.get("output_format") or "mp3_44100_128"),
            speed=float(arguments.get("speed") or 1.0),
        )
        actual_duration_seconds = generated.duration_seconds
        if actual_duration_seconds is None:
            actual_duration_seconds = estimated_duration_seconds
            logger.warning("%s audio.speak could not derive provider audio duration; using pricing-page estimate", log_prefix)
        credits = calculate_speech_credits(model=model, duration_seconds=float(actual_duration_seconds))
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
            duration_seconds=float(actual_duration_seconds),
            model=generated.model or model,
            generation_type="speech",
            prompt=None,
            text_preview=text_preview,
            extra_content={"voice": voice, "accent": accent, "style": style},
            original_filename_prefix="openmates_generated_speech",
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
            duration_seconds=float(actual_duration_seconds),
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
            request_metadata={"text_preview": text_preview, "provider": "ElevenLabs"},
        )
        return result_payload
    except Exception as exc:
        logger.error("%s Speech generation task failed: %s", log_prefix, exc, exc_info=True)
        result_payload = {
            "id": request_id,
            "embed_id": embed_id,
            "user_id_hash": hash_value(user_id) if user_id else None,
            "status": "error",
            "text_preview": text_preview,
            "generation_type": "speech",
            "voice": voice,
            "accent": accent,
            "style": style,
            "provider": "ElevenLabs",
            "model": model,
            "byte_length": 0,
            "credits_charged": None,
            "error": "Speech generation is temporarily unavailable.",
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
                request_metadata={"text_preview": text_preview, "provider": "ElevenLabs"},
            )
        except Exception as embed_exc:
            logger.error("%s Failed to publish audio.speak error state: %s", log_prefix, embed_exc, exc_info=True)
        return result_payload
    finally:
        await task.cleanup_services()
