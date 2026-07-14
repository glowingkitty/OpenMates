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


def _start_ws_span(event_type: str, user_id: str, payload: dict[str, Any] | None, user_otel_attrs: dict | None):
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span

        return start_ws_handler_span(event_type, user_id, payload, user_otel_attrs)
    except Exception:
        return None, None


def _end_ws_span(otel_span: Any, otel_token: Any) -> None:
    if otel_span is None:
        return
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span

        end_ws_handler_span(otel_span, otel_token)
    except Exception:
        pass


def _request_id(payload: dict[str, Any]) -> str | None:
    request_id = payload.get("request_id")
    if isinstance(request_id, str) and request_id and len(request_id) <= 128:
        return request_id
    return None


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
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "send_available_recovery_jobs",
        user_id,
        None,
        user_otel_attrs,
    )
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
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def _send_protocol_error(
    manager: Any,
    user_id: str,
    device_hash: str,
    exc: ChatRecoveryProtocolError,
    job_id: str | None,
    request_id: str | None,
) -> None:
    await manager.send_personal_message(
        {
            "type": "error",
            "payload": {
                "code": exc.code,
                "message": "Encrypted completion recovery was rejected.",
                "job_id": job_id,
                "request_id": request_id,
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
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "recovery_job_claim",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
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
            {
                "type": "recovery_job_claimed",
                "payload": {**result, "request_id": request_id},
            },
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(
            manager,
            user_id,
            device_fingerprint_hash,
            exc,
            payload.get("job_id"),
            request_id,
        )
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def handle_recovery_job_renew(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "recovery_job_renew",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
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
            {
                "type": "recovery_job_renewed",
                "payload": {**result, "request_id": request_id},
            },
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(
            manager,
            user_id,
            device_fingerprint_hash,
            exc,
            payload.get("job_id"),
            request_id,
        )
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def handle_recovery_job_persist(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "recovery_job_persist",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
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
            {
                "type": "recovery_job_persisted",
                "payload": {**result, "request_id": request_id},
            },
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(
            manager,
            user_id,
            device_fingerprint_hash,
            exc,
            payload.get("job_id"),
            request_id,
        )
    finally:
        _end_ws_span(_otel_span, _otel_token)
