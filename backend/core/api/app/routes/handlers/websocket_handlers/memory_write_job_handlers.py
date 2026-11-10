"""Claim and outcome reports for assistant-written personal Memories.

Access model: first-party authenticated WebSocket only, for a connection that
declared the ``memory_write_jobs`` capability and has the job's chat open. Not
reachable through the public REST API. No inference and no Memory text: the
client already holds the document and reports only ids, status and an error
code. Contract: backend/apps/ai/processing/memory_write_tool.py (protocol 1).
"""

from __future__ import annotations

from typing import Any

from backend.apps.ai.processing.memory_write_tool import (
    MEMORY_WRITE_CLAIM_RESULT_MESSAGE,
    MEMORY_WRITE_RESULT_ACK_MESSAGE,
    claim_memory_write_job,
    record_memory_write_result,
)


def _reply_ids(payload: Any) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    return {"job_id": payload.get("job_id"), "chat_id": payload.get("chat_id")}


async def handle_memory_write_job_claim(*, manager: Any, cache_service: Any, user_id: str,
                                        device_fingerprint_hash: str, payload: Any) -> None:
    chat_id = payload.get("chat_id") if isinstance(payload, dict) else None
    if not manager.supports_memory_write_jobs(user_id, device_fingerprint_hash) \
            or manager.get_active_chat(user_id, device_fingerprint_hash) != chat_id:
        granted, reason = False, "executor_not_ready"
    else:
        granted, reason = await claim_memory_write_job(
            cache_service, user_id=user_id, device_hash=device_fingerprint_hash, payload=payload)
    await manager.send_personal_message(
        {"type": MEMORY_WRITE_CLAIM_RESULT_MESSAGE,
         "payload": {**_reply_ids(payload), "granted": granted, "reason": reason}},
        user_id, device_fingerprint_hash,
    )


async def handle_memory_write_job_result(*, manager: Any, cache_service: Any, user_id: str,
                                         device_fingerprint_hash: str, payload: Any) -> None:
    accepted, reason = await record_memory_write_result(
        cache_service, user_id=user_id, device_hash=device_fingerprint_hash, payload=payload)
    await manager.send_personal_message(
        {"type": MEMORY_WRITE_RESULT_ACK_MESSAGE,
         "payload": {**_reply_ids(payload), "accepted": accepted, "reason": reason}},
        user_id, device_fingerprint_hash,
    )
