"""First-party session/device WebSocket metadata recovery; no public REST surface.

Owner identity comes exclusively from the authenticated socket. No paid work is
created; discovery is bounded to 100 jobs. Payloads stay sealed/client encrypted.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError, ChatRecoveryService

logger = logging.getLogger(__name__)


async def send_available_metadata_jobs(*, manager: Any, directus_service: Any,
                                       user_id: str, user_id_hash: str,
                                       device_fingerprint_hash: str) -> None:
    try:
        result = await ChatRecoveryService(directus_service).execute("list_metadata_jobs", {
            "protocol_version": 1, "hashed_user_id": user_id_hash,
        })
    except Exception:
        # This is also called while opening an otherwise valid chat socket.
        # Durable discovery outage must not prevent its ordinary chat traffic.
        logger.warning("Metadata discovery unavailable; durable jobs remain pending")
        return
    # Empty responses also settle a client's explicit reconnect discovery.
    await manager.send_personal_message({"type": "metadata_jobs_available", "payload": result},
                                        user_id, device_fingerprint_hash)


async def handle_metadata_recovery(*, manager: Any, cache_service: Any, directus_service: Any,
                                   user_id: str, user_id_hash: str, device_fingerprint_hash: str,
                                   payload: dict[str, Any], persist: bool) -> None:
    request_id = payload.get("request_id")
    request_id = request_id if isinstance(request_id, str) and 0 < len(request_id) <= 128 else None
    job_id = payload.get("job_id")
    try:
        data = {"protocol_version": payload.get("protocol_version"), "job_id": job_id,
                "hashed_user_id": user_id_hash}
        if persist:
            data.update({field: payload.get(field) for field in (
                "chat_key_version", "wrapped_chat_key", "encrypted_metadata",
            )})
        result = await ChatRecoveryService(directus_service).execute(
            "persist_metadata_job" if persist else "claim_metadata_job", data,
        )
        if persist and result.get("encrypted_metadata"):
            # Directus commit and receipt precede best-effort cache refresh.
            # Eviction ensures stale cache rows cannot conceal committed metadata.
            try:
                await cache_service.delete_chat_list_item_data(user_id, result["chat_id"])
                for field, version in result["versions"].items():
                    await cache_service.set_chat_version_component(user_id, result["chat_id"], field, version)
            except Exception:
                logger.warning("Metadata recovery cache refresh failed")
            await manager.broadcast_to_user(message={"type": "encrypted_chat_metadata", "payload": {
                "chat_id": result["chat_id"], "versions": result["versions"], **result["encrypted_metadata"],
            }}, user_id=user_id, exclude_device_hash=device_fingerprint_hash)
        await manager.send_personal_message({
            "type": "metadata_job_persisted" if persist else "metadata_job_claimed",
            "payload": {**result, "request_id": request_id},
        }, user_id, device_fingerprint_hash)
    except ChatRecoveryProtocolError as exc:
        await manager.send_personal_message({"type": "error", "payload": {
            "code": exc.code, "job_id": job_id, "request_id": request_id,
        }}, user_id, device_fingerprint_hash)


async def has_durable_metadata(*, directus_service: Any, user_id_hash: str,
                               chat_id: Any, task_id: Any) -> bool:
    if not isinstance(chat_id, str) or not isinstance(task_id, str):
        return False
    try:
        result = await ChatRecoveryService(directus_service).execute("metadata_job_admitted", {
            "protocol_version": 1, "hashed_user_id": user_id_hash, "chat_id": chat_id, "task_id": task_id,
        })
        return result.get("admitted") is True
    except Exception:
        # Preserve the compatible path when durable admission is unavailable.
        return False


async def filter_generated_metadata_storage(*, payload: dict[str, Any], supports_recovery: bool,
                                           directus_service: Any, user_id_hash: str) -> dict[str, Any]:
    """Suppress compatible generated writes only after exact durable admission."""
    if (supports_recovery and payload.get("encrypted_content")
            and await has_durable_metadata(directus_service=directus_service,
                user_id_hash=user_id_hash, chat_id=payload.get("chat_id"), task_id=payload.get("task_id"))):
        return {key: value for key, value in payload.items()
                if key not in {"encrypted_title", "encrypted_icon", "encrypted_chat_category"}}
    return payload
