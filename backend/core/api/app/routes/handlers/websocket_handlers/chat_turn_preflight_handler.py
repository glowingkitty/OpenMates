"""
WebSocket handler for durable encrypted chat-turn preflight.

The client provides both encrypted durable user content and the transient
inference request. Only a server-keyed commitment to plaintext crosses the
Directus persistence boundary, and inference remains blocked until this handler
returns a committed acknowledgement.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any

from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)
from backend.core.api.app.services.chat_recovery_telemetry import (
    record_recovery_duration,
    start_recovery_timing,
)


logger = logging.getLogger(__name__)
COMMITMENT_VERSION = 1


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


def canonicalize_inference_request(inference_request: dict[str, Any]) -> bytes:
    if not isinstance(inference_request, dict) or not inference_request:
        raise ValueError("inference_request must be a non-empty object")
    return json.dumps(
        inference_request,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _commitment_key() -> bytes:
    commitment_key = os.getenv("CHAT_RECOVERY_COMMITMENT_KEY")
    if commitment_key:
        return commitment_key.encode("utf-8")

    # Existing deployments already require this secret for internal transactions.
    # Derive a purpose-bound key so an API restart cannot disable all saved-chat
    # sends when the optional recovery-specific variable has not been provisioned.
    internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if internal_token:
        return hmac.new(
            internal_token.encode("utf-8"),
            b"openmates:chat-recovery-commitment:v1",
            hashlib.sha256,
        ).digest()
    raise RuntimeError("CHAT_RECOVERY_COMMITMENT_KEY or INTERNAL_API_SHARED_TOKEN is required")


def build_inference_commitment(inference_request: dict[str, Any]) -> str:
    return hmac.new(
        _commitment_key(),
        canonicalize_inference_request(inference_request),
        hashlib.sha256,
    ).hexdigest()


def server_client_capabilities(manager: Any, user_id: str, device_fingerprint_hash: str) -> list[str]:
    capabilities: list[str] = []
    if manager.supports_task_update_jobs(user_id, device_fingerprint_hash):
        capabilities.append("task_update_jobs")
    return capabilities


async def enqueue_chat_turn(
    *,
    directus_service: Any,
    user_id_hash: str,
    device_fingerprint_hash: str,
    preflight_id: str,
    inference_request: dict[str, Any],
) -> dict[str, Any]:
    namespace = uuid.UUID(preflight_id)
    started_at = start_recovery_timing()
    try:
        return await ChatRecoveryService(directus_service).execute(
            "enqueue_inference",
            {
                "protocol_version": 1,
                "preflight_id": preflight_id,
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
                "inference_commitment": build_inference_commitment(inference_request),
                "inference_task_id": str(uuid.uuid5(namespace, "inference-task")),
                "billing_identity": str(uuid.uuid5(namespace, "billing-identity")),
                "outbox_id": str(uuid.uuid5(namespace, "inference-outbox")),
            },
        )
    finally:
        record_recovery_duration("enqueue_inference", started_at)


async def handle_chat_turn_preflight(
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
        "chat_turn_preflight",
        user_id,
        payload,
        user_otel_attrs,
    )
    try:
        recovery_service = ChatRecoveryService(directus_service)
        cutover_state = await recovery_service.execute(
            "get_cutover_state",
            {"protocol_version": 1},
        )
        if cutover_state.get("protocol_epoch") == 0:
            legacy_preflight_id = str(
                uuid.uuid5(uuid.UUID(payload["turn_id"]), "legacy-preflight")
            )
            await manager.send_personal_message(
                {
                    "type": "chat_turn_preflight_ack",
                    "payload": {
                        "preflight_id": legacy_preflight_id,
                        "state": "LEGACY",
                        "turn_id": payload["turn_id"],
                    },
                },
                user_id,
                device_fingerprint_hash,
            )
            return
        encrypted_user_message = dict(payload["encrypted_user_message"])
        encrypted_user_message["hashed_user_id"] = user_id_hash
        inference_request = dict(payload["inference_request"])
        inference_request["client_capabilities"] = server_client_capabilities(
            manager,
            user_id,
            device_fingerprint_hash,
        )
        transaction_data = {
            "protocol_version": payload["protocol_version"],
            "hashed_user_id": user_id_hash,
            "chat_id": payload["chat_id"],
            "turn_id": payload["turn_id"],
            "user_message_id": payload["message_id"],
            "device_hash": device_fingerprint_hash,
            "chat_key_version": payload["chat_key_version"],
            "wrapped_chat_key": payload["encrypted_chat_key"],
            "recovery_public_key": payload["recovery_public_key"],
            "inference_commitment": build_inference_commitment(inference_request),
            "commitment_version": COMMITMENT_VERSION,
            "expected_messages_v": payload["expected_messages_v"],
            "encrypted_user_message": encrypted_user_message,
        }
        if payload.get("encrypted_chat_metadata") is not None:
            transaction_data["encrypted_chat_metadata"] = payload["encrypted_chat_metadata"]
        started_at = start_recovery_timing()
        try:
            result = await recovery_service.execute(
                "prepare_preflight",
                transaction_data,
            )
        finally:
            record_recovery_duration("durable_preflight", started_at)
        result["turn_id"] = payload["turn_id"]
        await manager.send_personal_message(
            {"type": "chat_turn_preflight_ack", "payload": result},
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await manager.send_personal_message(
            {
                "type": "error",
                "payload": {
                    "code": exc.code,
                    "message": "Encrypted chat preflight was rejected.",
                    "turn_id": payload.get("turn_id"),
                },
            },
            user_id,
            device_fingerprint_hash,
        )
    except Exception:
        # WebSocket boundary: fail closed and keep ciphertext/plaintext out of logs.
        logger.exception(
            "Encrypted chat preflight failed for user=%s device=%s",
            user_id[:8],
            device_fingerprint_hash[:8],
        )
        await manager.send_personal_message(
            {
                "type": "error",
                "payload": {
                    "code": "durable_preflight_failed",
                    "message": "Encrypted chat preflight is temporarily unavailable.",
                    "turn_id": payload.get("turn_id"),
                },
            },
            user_id,
            device_fingerprint_hash,
        )
    finally:
        _end_ws_span(_otel_span, _otel_token)
