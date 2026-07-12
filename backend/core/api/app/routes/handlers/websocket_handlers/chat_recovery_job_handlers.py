"""
WebSocket handlers for sealed completion recovery jobs.

Only authenticated owner and server-derived device identities reach the
transaction service. Clients receive sealed payloads after a fenced lease and
terminal acknowledgement only after encrypted assistant persistence commits.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)


logger = logging.getLogger(__name__)


async def invalidate_recovery_leases_for_device(
    *,
    directus_service: Any,
    user_id_hash: str,
    device_fingerprint_hash: str,
) -> dict[str, Any]:
    return await ChatRecoveryService(directus_service).execute(
        "invalidate_deletion",
        {
            "protocol_version": 1,
            "hashed_user_id": user_id_hash,
            "scope": "device",
            "device_hash": device_fingerprint_hash,
        },
    )


async def invalidate_recovery_jobs_for_chat_deletion(
    *,
    directus_service: Any,
    user_id_hash: str,
    chat_id: str,
) -> dict[str, Any]:
    return await ChatRecoveryService(directus_service).execute(
        "invalidate_deletion",
        {
            "protocol_version": 1,
            "hashed_user_id": user_id_hash,
            "scope": "chat",
            "chat_id": chat_id,
        },
    )


async def invalidate_recovery_jobs_for_account_deletion(
    *,
    directus_service: Any,
    user_id_hash: str,
) -> dict[str, Any]:
    return await ChatRecoveryService(directus_service).execute(
        "invalidate_deletion",
        {
            "protocol_version": 1,
            "hashed_user_id": user_id_hash,
            "scope": "account",
        },
    )


async def cleanup_expired_recovery_jobs(*, directus_service: Any) -> dict[str, Any]:
    return await ChatRecoveryService(directus_service).execute(
        "cleanup_expired",
        {"protocol_version": 1},
    )


async def send_available_recovery_jobs(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
) -> None:
    try:
        result = await ChatRecoveryService(directus_service).execute(
            "list_available_jobs",
            {
                "protocol_version": 1,
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
            },
        )
        jobs = result.get("jobs")
        if jobs:
            await manager.send_personal_message(
                {"type": "recovery_jobs_available", "payload": {"jobs": jobs}},
                user_id,
                device_fingerprint_hash,
            )
    except ChatRecoveryProtocolError as exc:
        if exc.status_code != 404:
            logger.warning(
                "Recovery job discovery failed for user=%s device=%s code=%s",
                user_id[:8],
                device_fingerprint_hash[:8],
                exc.code,
            )


async def _send_protocol_error(
    manager: Any,
    user_id: str,
    device_hash: str,
    exc: ChatRecoveryProtocolError,
) -> None:
    await manager.send_personal_message(
        {
            "type": "error",
            "payload": {
                "code": exc.code,
                "message": "Encrypted completion recovery was rejected.",
            },
        },
        user_id,
        device_hash,
    )


async def handle_recovery_job_claim(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    try:
        result = await ChatRecoveryService(directus_service).execute(
            "lease_job",
            {
                "protocol_version": payload.get("protocol_version"),
                "job_id": payload.get("job_id"),
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
            },
        )
        await manager.send_personal_message(
            {"type": "recovery_job_claimed", "payload": result},
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, exc)


async def handle_recovery_job_renew(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    try:
        result = await ChatRecoveryService(directus_service).execute(
            "renew_lease",
            {
                "protocol_version": payload.get("protocol_version"),
                "job_id": payload.get("job_id"),
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
                "lease_generation": payload.get("lease_generation"),
                "lease_token": payload.get("lease_token"),
            },
        )
        await manager.send_personal_message(
            {"type": "recovery_job_renewed", "payload": result},
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, exc)


async def handle_recovery_job_persist(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    try:
        encrypted_message = dict(payload.get("encrypted_assistant_message") or {})
        encrypted_message["hashed_user_id"] = user_id_hash
        result = await ChatRecoveryService(directus_service).execute(
            "persist_terminal",
            {
                "protocol_version": payload.get("protocol_version"),
                "job_id": payload.get("job_id"),
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
                "lease_generation": payload.get("lease_generation"),
                "lease_token": payload.get("lease_token"),
                "expected_messages_v": payload.get("expected_messages_v"),
                "encrypted_assistant_message": encrypted_message,
            },
        )
        await manager.send_personal_message(
            {"type": "recovery_job_persisted", "payload": result},
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, exc)
