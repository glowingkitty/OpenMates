"""Claim, result and delivery handlers for chat orchestration jobs.

Access model: first-party authenticated WebSocket only, for connections that
declared the ``chat_orchestration_jobs`` capability. The server never sees chat
keys: the claiming device performs the client-side effect and reports only
ok/error_code (plus a bounded result for read_chat, sealed in Redis).
Contract: backend/shared/python_utils/chat_orchestration_jobs.py.
"""

from __future__ import annotations

from typing import Any

from backend.shared.python_utils.chat_orchestration_jobs import (
    build_offer,
    claim_job,
    list_pending_offers,
    record_job_result,
)

AVAILABLE_MESSAGE = "chat_orchestration_job_available"
CLAIM_RESULT_MESSAGE = "chat_orchestration_job_claim_result"
RESULT_ACK_MESSAGE = "chat_orchestration_job_result_ack"


def _job_id(payload: Any) -> Any:
    return payload.get("job_id") if isinstance(payload, dict) else None


async def handle_chat_orchestration_job_claim(*, manager: Any, cache_service: Any, user_id: str,
                                              device_fingerprint_hash: str, payload: Any) -> None:
    if not manager.supports_chat_orchestration_jobs(user_id, device_fingerprint_hash):
        granted, reason = False, "executor_not_ready"
    else:
        granted, reason = await claim_job(cache_service=cache_service, user_id=user_id,
                                          device_hash=device_fingerprint_hash, job_id=_job_id(payload))
    await manager.send_personal_message(
        {"type": CLAIM_RESULT_MESSAGE, "payload": {"job_id": _job_id(payload), "granted": granted, "reason": reason}},
        user_id, device_fingerprint_hash)


async def handle_chat_orchestration_job_result(*, manager: Any, cache_service: Any, encryption_service: Any,
                                               user_id: str, device_fingerprint_hash: str, payload: Any) -> None:
    data = payload if isinstance(payload, dict) else {}
    accepted, reason = await record_job_result(
        cache_service=cache_service, encryption_service=encryption_service, user_id=user_id,
        device_hash=device_fingerprint_hash, job_id=data.get("job_id"), ok=data.get("ok"),
        error_code=data.get("error_code"), result=data.get("result"))
    await manager.send_personal_message(
        {"type": RESULT_ACK_MESSAGE, "payload": {"job_id": data.get("job_id"), "accepted": accepted, "reason": reason}},
        user_id, device_fingerprint_hash)


async def offer_job_to_devices(*, manager: Any, cache_service: Any, encryption_service: Any,
                               user_id: str, job_id: str) -> None:
    """Deliver one job to every capable connected device (first claim wins)."""
    offer = await build_offer(cache_service=cache_service, encryption_service=encryption_service,
                              user_id=user_id, job_id=job_id)
    if offer is None:
        return
    for device_hash in list(manager.get_connections_for_user(user_id)):
        if manager.supports_chat_orchestration_jobs(user_id, device_hash):
            await manager.send_personal_message({"type": AVAILABLE_MESSAGE, "payload": offer},
                                                user_id, device_hash)


async def send_pending_chat_orchestration_jobs(*, manager: Any, cache_service: Any, encryption_service: Any,
                                               user_id: str, device_fingerprint_hash: str) -> None:
    """Re-offer unclaimed start_chat/creator_event jobs to a device that just connected."""
    if not manager.supports_chat_orchestration_jobs(user_id, device_fingerprint_hash):
        return
    for offer in await list_pending_offers(cache_service=cache_service, encryption_service=encryption_service,
                                           user_id=user_id):
        await manager.send_personal_message({"type": AVAILABLE_MESSAGE, "payload": offer},
                                            user_id, device_fingerprint_hash)
