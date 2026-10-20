"""Sealed first-party voice request lane on the ordinary AI worker queue."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from backend.core.api.app.tasks import celery_config

logger = logging.getLogger(__name__)


async def _emit_voice_progress(event: dict, *, data: dict, cache, directus, encryption, key: str) -> None:
    """Deliver live progress without cancelling admitted output finalization."""
    from backend.apps.ai.processing.voice_call_broker import (
        transport_key, require_binding, MAX_RESULT_CHARS, TRANSPORT_TTL,
    )
    client = await cache.client
    if await client.exists(transport_key(data["operation_id"], "cancel")) or (
        data.get("request_cancel_id") and await client.exists(transport_key(data["request_cancel_id"], "cancel"))
    ):
        return
    try:
        await require_binding(cache, data)
    except (PermissionError, ValueError):
        # The live socket can disappear after an action executed. Its exact
        # sealed output authority still governs cache and main-socket delivery.
        from backend.apps.ai.processing.voice_async_skills import active_voice_worker_context, require_voice_publication
        context = active_voice_worker_context.get()
        if context is None or any(context.binding.get(field) != data.get(field) for field in (
            "user_id", "user_hash", "session_id", "chat_id", "call_id", "operation_id",
        )):
            raise
        await require_voice_publication(context=context, cache_service=cache,
            directus_service=directus, encryption_service=encryption,
            owner_hash=data["user_hash"])
        return
    payload = {"operation_id": data["operation_id"], "call_id": data["call_id"], "progress": event}
    if len(json.dumps(payload)) > MAX_RESULT_CHARS:
        raise ValueError("Voice progress exceeds transport bound")
    sealed, _ = await encryption.encrypt_with_user_key(json.dumps(payload), key)
    if not sealed:
        raise RuntimeError("Voice progress could not be sealed")
    result_key = transport_key(data["operation_id"], "result")
    await client.rpush(result_key, sealed)
    await client.expire(result_key, TRANSPORT_TTL)


async def run_voice_request(operation_id: str, user_id: str, ciphertext: str) -> None:
    from backend.apps.ai.processing.voice_call_broker import (
        transport_key, require_binding, user_vault_key, voice_operation_error_code,
        MAX_RESULT_CHARS, TRANSPORT_TTL,
    )
    from backend.apps.ai.processing.voice_call_broker_runtime import process_voice_request
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    cache = await celery_config.get_worker_cache_service()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    secrets_manager = SecretsManager()
    try:
        key = await user_vault_key(cache, directus, user_id)
        # Queue metadata carries ciphertext and opaque identity only. Errors never
        # return exceptions containing generated parameters or private user context.
        data = json.loads(await encryption.decrypt_with_user_key(ciphertext, key))
        if data.get("operation_id") != operation_id or data.get("user_id") != user_id or data.get("expires_at", 0) < time.time():
            raise PermissionError("Voice envelope binding invalid")
        await require_binding(cache, data)
        client = await cache.client
        if await client.exists(transport_key(operation_id, "cancel")) or (
            data.get("request_cancel_id") and await client.exists(transport_key(data["request_cancel_id"], "cancel"))
        ):
            return
        await secrets_manager.initialize()
        try:
            from backend.shared.python_utils.private_inference_logging import private_inference_logging
            async def emit_progress(event: dict) -> None:
                await _emit_voice_progress(event, data=data, cache=cache, directus=directus,
                    encryption=encryption, key=key)
            from backend.apps.ai.processing.voice_call_broker_runtime import voice_progress_emitter
            token = voice_progress_emitter.set(emit_progress)
            try:
                with private_inference_logging():
                    result = await process_voice_request(data, cache=cache, directus=directus,
                        encryption=encryption, secrets_manager=secrets_manager)
            finally:
                voice_progress_emitter.reset(token)
            response = {"operation_id": operation_id, "call_id": data["call_id"], "result": result}
            if len(json.dumps(response, ensure_ascii=False)) > MAX_RESULT_CHARS:
                raise ValueError("Voice result exceeds transport bound")
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Voice broker operation failed operation=%s category=%s", operation_id, type(exc).__name__)
            response = {"operation_id": operation_id, "call_id": data["call_id"],
                        "error": "Voice request could not be completed",
                        "error_code": voice_operation_error_code(exc)}
        if await client.exists(transport_key(operation_id, "cancel")):
            return
        sealed, _ = await encryption.encrypt_with_user_key(json.dumps(response), key)
        if not sealed:
            raise RuntimeError("Voice response could not be sealed")
        result_key = transport_key(operation_id, "result")
        await client.rpush(result_key, sealed)
        await client.expire(result_key, TRANSPORT_TTL)
    finally:
        await asyncio.gather(directus.close(), secrets_manager.aclose(), return_exceptions=True)


@celery_config.app.task(name="apps.ai.tasks.voice_call_request", ignore_result=True)
def voice_call_request(operation_id: str, user_id: str, ciphertext: str) -> None:
    """Execute private voice work; Celery's result backend never sees plaintext."""
    asyncio.run(run_voice_request(operation_id, user_id, ciphertext))


async def run_voice_metadata(request_id: str, user_id: str, ciphertext: str) -> None:
    from backend.shared.python_utils import voice_chat_metadata as metadata
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.python_utils.private_inference_logging import private_inference_logging
    cache = await celery_config.get_worker_cache_service()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    secrets_manager = SecretsManager()
    try:
        vault = await metadata._vault(cache, directus, user_id)
        data = json.loads(await encryption.decrypt_with_user_key(ciphertext, vault))
        if data.get("request_id") != request_id or data.get("user_id") != user_id or data.get("expires_at", 0) < time.time():
            raise PermissionError("Metadata envelope binding invalid")
        await metadata._owned_chat(directus, data["chat_id"], data["user_hash"])
        client = await cache.client
        # A redelivery must never pay for the same accepted snapshot twice.
        if not await client.set(metadata.key("execution", user_id, request_id), "started", ex=metadata.TTL, nx=True):
            return
        try:
            from backend.shared.testing.voice_broker_fixture import chat_metadata_fixture
            result = chat_metadata_fixture(data)
            if result is None:
                from backend.shared.python_utils.billing_utils import ensure_credit_headroom
                from backend.apps.ai.processing.postprocessor import generate_chat_metadata
                await ensure_credit_headroom(user_id=user_id, estimated_credits=1,
                    log_prefix="[VoiceMetadata]", operation_name="chat metadata")
                await secrets_manager.initialize()
                profile = await directus.get_user_profile(user_id)
                language = profile[1].get("language", "en") if profile and profile[0] else "en"
                with private_inference_logging():
                    result = await generate_chat_metadata(task_id=request_id,
                        message_history=data["context"]["messages"],
                        current_chat_title=data["current_title"] or None,
                        prior_summary=data["current_summary"] or None,
                        conversation_checkpoint=data["context"]["summary"] or None,
                        user_system_language=language, secrets_manager=secrets_manager)
        except Exception as exc:
            logger.warning("Voice metadata failed request=%s category=%s", request_id, type(exc).__name__)
            result = {"error": "metadata_unavailable"}
        await metadata.publish_result(cache=cache, directus=directus, encryption=encryption, data=data, result=result)
    finally:
        await asyncio.gather(directus.close(), secrets_manager.aclose(), return_exceptions=True)


@celery_config.app.task(name="apps.ai.tasks.voice_chat_metadata", ignore_result=True)
def voice_chat_metadata(request_id: str, user_id: str, ciphertext: str) -> None:
    """Accepted metadata survives call closure; queue/result backend see no plaintext."""
    asyncio.run(run_voice_metadata(request_id, user_id, ciphertext))
