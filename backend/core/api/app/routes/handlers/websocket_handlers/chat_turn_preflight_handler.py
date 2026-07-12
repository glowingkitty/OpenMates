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


logger = logging.getLogger(__name__)
COMMITMENT_VERSION = 1


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


async def enqueue_chat_turn(
    *,
    directus_service: Any,
    user_id_hash: str,
    device_fingerprint_hash: str,
    preflight_id: str,
    inference_request: dict[str, Any],
) -> dict[str, Any]:
    namespace = uuid.UUID(preflight_id)
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


async def handle_chat_turn_preflight(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    try:
        encrypted_user_message = dict(payload["encrypted_user_message"])
        encrypted_user_message["hashed_user_id"] = user_id_hash
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
            "inference_commitment": build_inference_commitment(payload["inference_request"]),
            "commitment_version": COMMITMENT_VERSION,
            "expected_messages_v": payload["expected_messages_v"],
            "encrypted_user_message": encrypted_user_message,
        }
        if payload.get("encrypted_chat_metadata") is not None:
            transaction_data["encrypted_chat_metadata"] = payload["encrypted_chat_metadata"]
        result = await ChatRecoveryService(directus_service).execute(
            "prepare_preflight",
            transaction_data,
        )
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
                },
            },
            user_id,
            device_fingerprint_hash,
        )
