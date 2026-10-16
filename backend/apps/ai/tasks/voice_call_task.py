"""Sealed first-party voice request lane on the ordinary AI worker queue."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from backend.core.api.app.tasks import celery_config

logger = logging.getLogger(__name__)


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
            with private_inference_logging():
                result = await process_voice_request(data, cache=cache, directus=directus,
                    encryption=encryption, secrets_manager=secrets_manager)
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
