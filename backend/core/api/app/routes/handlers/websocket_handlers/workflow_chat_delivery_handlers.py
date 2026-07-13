"""WebSocket handlers for Workflow pending chat delivery claims.

Workflow send_chat_message output is stored as Vault ciphertext until an owner
device claims responsibility for first chat encryption. These handlers expose a
fenced claim/persist/ack protocol and never create regular chat keys.

Spec: docs/specs/workflows-cli-runtime/spec.yml
"""

from __future__ import annotations

import logging
import json
from typing import Any

from backend.core.api.app.services.workflow_chat_delivery_service import (
    DirectusWorkflowChatDeliveryRepository,
    WorkflowChatDelivery,
    WorkflowChatDeliveryClaim,
    WorkflowChatDeliveryError,
    WorkflowChatDeliveryService,
)


logger = logging.getLogger(__name__)


class _UnavailableDeliveryCipher:
    """Cipher placeholder for handler paths that never create deliveries."""

    def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict[str, str]) -> str:
        del owner_id, delivery_id, payload
        raise RuntimeError("Workflow chat delivery handlers cannot create encrypted deliveries")


def _service(directus_service: Any) -> WorkflowChatDeliveryService:
    return WorkflowChatDeliveryService(
        cipher=_UnavailableDeliveryCipher(),
        repository=DirectusWorkflowChatDeliveryRepository.from_directus_service(directus_service),
    )


def _request_id(payload: dict[str, Any]) -> str | None:
    request_id = payload.get("request_id")
    if isinstance(request_id, str) and request_id and len(request_id) <= 128:
        return request_id
    return None


def _delivery_payload(delivery: WorkflowChatDelivery) -> dict[str, Any]:
    return {
        "delivery_id": delivery.delivery_id,
        "chat_id": delivery.chat_id,
        "message_id": delivery.message_id,
        "status": delivery.status,
        "encrypted_payload": delivery.encrypted_payload,
        "created_at": delivery.created_at,
        "expires_at": delivery.expires_at,
        "claim_generation": delivery.claim_generation,
    }


def _claim_from_payload(payload: dict[str, Any]) -> WorkflowChatDeliveryClaim:
    return WorkflowChatDeliveryClaim(
        token=str(payload.get("claim_token") or ""),
        generation=int(payload.get("claim_generation") or 0),
        issued_at=int(payload.get("claim_issued_at") or 0),
        expires_at=int(payload.get("claim_expires_at") or 0),
    )


async def send_available_workflow_chat_deliveries(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
) -> None:
    """Notify a newly connected owner device about claimable deliveries."""
    try:
        deliveries = _service(directus_service).list_pending_for_owner(owner_id=user_id)
        if not deliveries:
            return
        await manager.send_personal_message(
            {
                "type": "workflow_chat_deliveries_available",
                "payload": {"deliveries": [_delivery_payload(delivery) for delivery in deliveries]},
            },
            user_id,
            device_fingerprint_hash,
        )
    except Exception:
        logger.exception("Workflow chat delivery discovery failed for user=%s", user_id[:8])


async def handle_workflow_chat_delivery_claim(
    *,
    manager: Any,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    request_id = _request_id(payload)
    delivery_id = payload.get("delivery_id")
    lock_key = f"workflow_chat_delivery_claim:{delivery_id}"
    lock_acquired = False
    try:
        lock_acquired = await _acquire_claim_lock(cache_service, lock_key)
        if not lock_acquired:
            raise ValueError("Workflow chat delivery is already being claimed")
        claim = _service(directus_service).claim_new_chat_delivery(
            delivery_id=str(delivery_id or ""),
            owner_id=user_id,
            device_id=device_fingerprint_hash,
        )
        delivery = _service(directus_service).get_delivery(delivery_id=str(delivery_id), owner_id=user_id)
        plaintext_payload = await _decrypt_claimed_payload(
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_id=user_id,
            encrypted_payload=delivery.encrypted_payload,
        )
        await manager.send_personal_message(
            {
                "type": "workflow_chat_delivery_claimed",
                "payload": {
                    **_delivery_payload(delivery),
                    "title": plaintext_payload["title"],
                    "message": plaintext_payload["message"],
                    "claim_token": claim.token,
                    "claim_generation": claim.generation,
                    "claim_issued_at": claim.issued_at,
                    "claim_expires_at": claim.expires_at,
                    "request_id": request_id,
                },
            },
            user_id,
            device_fingerprint_hash,
        )
    except (PermissionError, WorkflowChatDeliveryError, ValueError) as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, str(delivery_id or ""), request_id, exc)
    finally:
        if lock_acquired:
            await _release_claim_lock(cache_service, lock_key)


async def handle_workflow_chat_delivery_persist(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    request_id = _request_id(payload)
    delivery_id = str(payload.get("delivery_id") or "")
    try:
        delivery = _service(directus_service).persist_client_ciphertext(
            delivery_id=delivery_id,
            owner_id=user_id,
            claim=_claim_from_payload(payload),
            encrypted_chat_metadata=str(payload.get("encrypted_chat_metadata") or ""),
            encrypted_message=str(payload.get("encrypted_message") or ""),
            device_id=device_fingerprint_hash,
        )
        await manager.send_personal_message(
            {
                "type": "workflow_chat_delivery_persisted",
                "payload": {**_delivery_payload(delivery), "request_id": request_id},
            },
            user_id,
            device_fingerprint_hash,
        )
    except (PermissionError, WorkflowChatDeliveryError, ValueError) as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, delivery_id, request_id, exc)


async def handle_workflow_chat_delivery_ack(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    request_id = _request_id(payload)
    delivery_id = str(payload.get("delivery_id") or "")
    try:
        delivery = _service(directus_service).acknowledge_delivery(
            delivery_id=delivery_id,
            owner_id=user_id,
            claim=_claim_from_payload(payload),
            device_id=device_fingerprint_hash,
        )
        await manager.send_personal_message(
            {
                "type": "workflow_chat_delivery_acknowledged",
                "payload": {**_delivery_payload(delivery), "request_id": request_id},
            },
            user_id,
            device_fingerprint_hash,
        )
    except (PermissionError, WorkflowChatDeliveryError, ValueError) as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, delivery_id, request_id, exc)


async def _send_protocol_error(
    manager: Any,
    user_id: str,
    device_hash: str,
    delivery_id: str,
    request_id: str | None,
    exc: Exception,
) -> None:
    await manager.send_personal_message(
        {
            "type": "error",
            "payload": {
                "code": "workflow_chat_delivery_rejected",
                "message": "Workflow chat delivery was rejected.",
                "delivery_id": delivery_id,
                "request_id": request_id,
                "reason": exc.__class__.__name__,
            },
        },
        user_id,
        device_hash,
    )


async def _decrypt_claimed_payload(
    *,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    user_id: str,
    encrypted_payload: str,
) -> dict[str, str]:
    try:
        envelope = json.loads(encrypted_payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Workflow chat delivery payload is not a Vault envelope") from exc
    if not isinstance(envelope, dict):
        raise ValueError("Workflow chat delivery payload envelope is invalid")
    ciphertext = envelope.get("ciphertext")
    vault_key_id = envelope.get("vault_key_id") or await cache_service.get_user_vault_key_id(user_id)
    if not vault_key_id:
        profile = await directus_service.get_user_fields_direct(user_id, ["vault_key_id"])
        vault_key_id = profile.get("vault_key_id") if isinstance(profile, dict) else None
    if not isinstance(ciphertext, str) or not ciphertext or not isinstance(vault_key_id, str) or not vault_key_id:
        raise ValueError("Workflow chat delivery payload envelope is incomplete")
    plaintext = await encryption_service.decrypt_with_user_key(ciphertext, vault_key_id)
    if not plaintext:
        raise ValueError("Workflow chat delivery payload could not be decrypted")
    try:
        decoded = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise ValueError("Workflow chat delivery plaintext payload is invalid") from exc
    title = decoded.get("title") if isinstance(decoded, dict) else None
    message = decoded.get("message") if isinstance(decoded, dict) else None
    if not isinstance(title, str) or not title or not isinstance(message, str) or not message:
        raise ValueError("Workflow chat delivery plaintext payload is incomplete")
    return {"title": title, "message": message}


async def _acquire_claim_lock(cache_service: Any, lock_key: str) -> bool:
    client = await cache_service.client
    if client is None:
        raise ValueError("Workflow chat delivery claim lock is unavailable")
    return bool(await client.set(lock_key, "1", nx=True, ex=10))


async def _release_claim_lock(cache_service: Any, lock_key: str) -> None:
    try:
        client = await cache_service.client
        if client is not None:
            await client.delete(lock_key)
    except Exception:
        logger.debug("Workflow chat delivery claim lock release failed", exc_info=True)
