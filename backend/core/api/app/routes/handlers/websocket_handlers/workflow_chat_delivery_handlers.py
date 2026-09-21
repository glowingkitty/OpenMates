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
        "claim_expires_at": delivery.claim_expires_at,
        "workflow_id": delivery.workflow_id,
        "run_id": delivery.run_id,
        "client_persisted": delivery.client_persistence is not None,
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
    user_otel_attrs: dict | None = None,
) -> None:
    """Notify a newly connected owner device about claimable deliveries."""
    _otel_span, _otel_token = _start_ws_span(
        "send_available_workflow_chat_deliveries",
        user_id,
        None,
        user_otel_attrs,
    )
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
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def handle_workflow_chat_delivery_claim(
    *,
    manager: Any,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "workflow_chat_delivery_claim",
        user_id,
        payload,
        user_otel_attrs,
    )
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
        existing_chat = await _existing_delivery_chat(directus_service, delivery, user_id) if delivery.workflow_id else None
        if delivery.client_persistence is not None and not delivery.encrypted_payload:
            plaintext_payload = {"title": "Workflow results", "message": "Delivery already persisted", "embeds": []}
        else:
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
                    "embeds": plaintext_payload.get("embeds") or [],
                    "existing_chat": existing_chat,
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
        _end_ws_span(_otel_span, _otel_token)


async def handle_workflow_chat_delivery_persist(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
    cache_service: Any | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "workflow_chat_delivery_persist",
        user_id,
        payload,
        user_otel_attrs,
    )
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
        if delivery.workflow_id and cache_service is not None:
            await _project_committed_delivery(manager, cache_service, directus_service, delivery, user_id, device_fingerprint_hash)
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
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def handle_workflow_chat_delivery_ack(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
    cache_service: Any | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "workflow_chat_delivery_ack",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
    delivery_id = str(payload.get("delivery_id") or "")
    try:
        pending = _service(directus_service).get_delivery(delivery_id=delivery_id, owner_id=user_id)
        if pending.workflow_id and pending.client_persistence is not None and cache_service is not None:
            await _project_committed_delivery(manager, cache_service, directus_service, pending, user_id, device_fingerprint_hash)
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
    finally:
        _end_ws_span(_otel_span, _otel_token)


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
) -> dict[str, Any]:
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
    embeds = decoded.get("embeds") or []
    if not isinstance(embeds, list) or len(embeds) > 500 or any(
        not isinstance(embed, dict) or not isinstance(embed.get("embed_id"), str)
        or not isinstance(embed.get("content_type"), str) or not isinstance(embed.get("content"), dict)
        for embed in embeds
    ):
        raise ValueError("Workflow selected embeds are invalid")
    return {"title": title, "message": message, "embeds": embeds}


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


async def _existing_delivery_chat(directus_service: Any, delivery: WorkflowChatDelivery, user_id: str) -> dict[str, Any] | None:
    """Canonical owner-encrypted key wrapper; the server never unwraps this key."""
    import hashlib
    rows = await directus_service.get_items("chats", params={
        "filter[id][_eq]": delivery.chat_id,
        "fields": "id,hashed_user_id,hashed_team_id,encrypted_chat_key,encrypted_title,encrypted_category,messages_v,title_v,created_at,last_edited_overall_timestamp",
        "limit": 1,
    }, no_cache=True, raise_on_error=True)
    if not rows:
        return None
    chat = rows[0]
    if chat.get("hashed_user_id") != hashlib.sha256(user_id.encode()).hexdigest() or chat.get("hashed_team_id"):
        raise PermissionError("Workflow destination chat is not owned by this user")
    return {key: chat.get(key) for key in ("encrypted_chat_key", "encrypted_title", "encrypted_category", "messages_v", "title_v", "created_at", "last_edited_overall_timestamp")}


async def _project_committed_delivery(manager: Any, cache_service: Any, directus_service: Any,
                                      delivery: WorkflowChatDelivery, user_id: str, device_hash: str) -> None:
    """Idempotent normal encrypted sync after the SQL commit, including ACK recovery."""
    import hashlib
    if delivery.client_persistence is None:
        raise ValueError("Workflow ciphertext is not committed")
    chat = await _existing_delivery_chat(directus_service, delivery, user_id)
    if not chat:
        raise ValueError("Committed workflow chat is unavailable")
    message = json.loads(delivery.client_persistence.encrypted_message)
    timestamp = int(chat.get("last_edited_overall_timestamp") or delivery.client_persistence.persisted_at)
    # Use existing cache boundaries. Invalidate list metadata so cached readers
    # refill from canonical Directus; versions only increase and message append
    # deduplicates by the stable message ID.
    operations = [
        await cache_service.add_chat_to_ids_versions(user_id, delivery.chat_id, timestamp),
        await cache_service.delete_chat_list_item_data(user_id, delivery.chat_id),
        await cache_service.set_chat_version_component(user_id, delivery.chat_id, "messages_v", int(chat.get("messages_v") or 1)),
        await cache_service.set_chat_version_component(user_id, delivery.chat_id, "title_v", int(chat.get("title_v") or 1)),
        await cache_service.append_sync_message_to_history(user_id, delivery.chat_id, json.dumps({
            "id": delivery.message_id, "message_id": delivery.message_id, "chat_id": delivery.chat_id,
            "role": "assistant", "encrypted_content": message["encrypted_content"],
            "encrypted_category": chat.get("encrypted_category"), "created_at": delivery.client_persistence.persisted_at,
        })),
    ]
    if not all(operations):
        raise ValueError("Workflow encrypted chat sync is temporarily unavailable")
    def sha(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
    embeds = []
    for embed in message.get("embeds") or []:
        embeds.append({**embed, "embed_keys": [{**key, "hashed_embed_id": sha(embed["embed_id"]),
            "hashed_user_id": sha(user_id), "hashed_chat_id": sha(delivery.chat_id) if key["key_type"] == "chat" else None,
            "created_at": delivery.client_persistence.persisted_at} for key in embed["embed_keys"]]})
    await manager.broadcast_to_user(message={"type": "new_chat_message", "payload": {
        "chat_id": delivery.chat_id, "message_id": delivery.message_id, "role": "assistant", "content": "",
        "encrypted_content": message["encrypted_content"], "encrypted_chat_key": chat["encrypted_chat_key"],
        "encrypted_title": chat.get("encrypted_title"), "encrypted_category": chat.get("encrypted_category"),
        "created_at": delivery.client_persistence.persisted_at, "messages_v": chat.get("messages_v") or 1,
        "last_edited_overall_timestamp": timestamp, "workflow_embeds": embeds,
    }}, user_id=user_id, exclude_device_hash=device_hash)
