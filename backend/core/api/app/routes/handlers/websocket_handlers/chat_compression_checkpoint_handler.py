# backend/core/api/app/routes/handlers/websocket_handlers/chat_compression_checkpoint_handler.py
# WebSocket handlers for client-encrypted chat compression checkpoints.
# The server proposes summaries, but only the client may encrypt and persist
# checkpoint content into Directus zero-knowledge storage.

import logging
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _validate_client_encrypted_chat_payload
from backend.shared.python_utils.tracing.ws_span_helper import (
    end_ws_handler_span,
    start_ws_handler_span,
)

logger = logging.getLogger(__name__)

CHECKPOINT_COLLECTION = "chat_compression_checkpoints"
DEFAULT_OLD_MESSAGE_LIMIT = 100
MAX_OLD_MESSAGE_LIMIT = 250


async def get_latest_chat_compression_checkpoint(
    directus_service: DirectusService,
    chat_id: str,
    hashed_user_id: str,
) -> Optional[Dict[str, Any]]:
    rows = await directus_service.get_items(
        CHECKPOINT_COLLECTION,
        params={
            "filter": {
                "chat_id": {"_eq": chat_id},
                "hashed_user_id": {"_eq": hashed_user_id},
            },
            "sort": "-created_at",
            "limit": 1,
        },
        admin_required=True,
    )
    if rows and isinstance(rows, list):
        return rows[0]
    return None


async def handle_store_chat_compression_checkpoint(
    cache_service: CacheService,
    directus_service: DirectusService,
    manager: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
) -> None:
    _otel_span, _otel_token = start_ws_handler_span(
        "store_chat_compression_checkpoint",
        user_id,
        payload,
        user_otel_attrs,
    )
    try:
        await _handle_store_chat_compression_checkpoint(
            cache_service,
            directus_service,
            manager,
            user_id,
            user_id_hash,
            device_fingerprint_hash,
            payload,
            user_otel_attrs,
        )
    finally:
        end_ws_handler_span(_otel_span, _otel_token)


async def _handle_store_chat_compression_checkpoint(
    cache_service: CacheService,
    directus_service: DirectusService,
    manager: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
) -> None:
    del cache_service, user_otel_attrs
    chat_id = payload.get("chat_id")
    checkpoint_id = payload.get("checkpoint_id")
    encrypted_summary = payload.get("encrypted_summary")

    if not chat_id or not checkpoint_id or not encrypted_summary:
        await manager.send_personal_message(
            {"type": "error", "payload": {"message": "Missing compression checkpoint fields."}},
            user_id,
            device_fingerprint_hash,
        )
        return

    if not await directus_service.chat.check_chat_ownership(chat_id, user_id):
        await manager.send_personal_message(
            {"type": "error", "payload": {"message": "You do not have permission to access this chat.", "chat_id": chat_id}},
            user_id,
            device_fingerprint_hash,
        )
        return

    _validate_client_encrypted_chat_payload(checkpoint_id, encrypted_summary)

    existing = await directus_service.get_items(
        CHECKPOINT_COLLECTION,
        params={"filter": {"id": {"_eq": checkpoint_id}}, "limit": 1},
        admin_required=True,
    )
    if existing:
        checkpoint = existing[0]
    else:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        checkpoint_payload = {
            "id": checkpoint_id,
            "chat_id": chat_id,
            "hashed_user_id": user_id_hash,
            "encrypted_summary": encrypted_summary,
            "compressed_up_to_timestamp": payload.get("compressed_up_to_timestamp") or 0,
            "compressed_message_count": payload.get("compressed_message_count") or 0,
            "summary_token_estimate": payload.get("summary_token_estimate") or 0,
            "key_version": payload.get("key_version"),
            "created_at": payload.get("created_at") or now_ts,
            "updated_at": now_ts,
        }
        success, created = await directus_service.create_item(
            CHECKPOINT_COLLECTION,
            checkpoint_payload,
            admin_required=True,
        )
        if not success:
            logger.error("Failed to persist chat compression checkpoint %s: %s", checkpoint_id, created)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "Failed to persist compression checkpoint.", "chat_id": chat_id}},
                user_id,
                device_fingerprint_hash,
            )
            return
        checkpoint = created

    response = {"chat_id": chat_id, "checkpoint": checkpoint}
    await manager.send_personal_message(
        {"type": "chat_compression_checkpoint_stored", "payload": response},
        user_id,
        device_fingerprint_hash,
    )


async def handle_get_compressed_chat_old_messages(
    cache_service: CacheService,
    directus_service: DirectusService,
    manager: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
) -> None:
    _otel_span, _otel_token = start_ws_handler_span(
        "get_compressed_chat_old_messages",
        user_id,
        payload,
        user_otel_attrs,
    )
    try:
        await _handle_get_compressed_chat_old_messages(
            cache_service,
            directus_service,
            manager,
            user_id,
            user_id_hash,
            device_fingerprint_hash,
            payload,
            user_otel_attrs,
        )
    finally:
        end_ws_handler_span(_otel_span, _otel_token)


async def _handle_get_compressed_chat_old_messages(
    cache_service: CacheService,
    directus_service: DirectusService,
    manager: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict = None,
) -> None:
    del cache_service, user_otel_attrs
    chat_id = payload.get("chat_id")
    checkpoint_id = payload.get("checkpoint_id")
    before_timestamp = payload.get("before_timestamp")
    before_message_id = payload.get("before_message_id")
    target_message_id = payload.get("target_message_id")
    limit = min(int(payload.get("limit") or DEFAULT_OLD_MESSAGE_LIMIT), MAX_OLD_MESSAGE_LIMIT)

    if not chat_id or not checkpoint_id or before_timestamp is None:
        await manager.send_personal_message(
            {"type": "error", "payload": {"message": "Missing old-message request fields."}},
            user_id,
            device_fingerprint_hash,
        )
        return

    if not await directus_service.chat.check_chat_ownership(chat_id, user_id):
        await manager.send_personal_message(
            {"type": "error", "payload": {"message": "You do not have permission to access this chat.", "chat_id": chat_id}},
            user_id,
            device_fingerprint_hash,
        )
        return

    checkpoint_rows = await directus_service.get_items(
        CHECKPOINT_COLLECTION,
        params={
            "filter": {
                "id": {"_eq": checkpoint_id},
                "chat_id": {"_eq": chat_id},
                "hashed_user_id": {"_eq": user_id_hash},
            },
            "limit": 1,
        },
        admin_required=True,
    )
    if not checkpoint_rows:
        await manager.send_personal_message(
            {"type": "error", "payload": {"message": "Compression checkpoint not found.", "chat_id": chat_id}},
            user_id,
            device_fingerprint_hash,
        )
        return

    if target_message_id:
        target_message = await directus_service.chat.get_message_for_chat_by_client_id(
            chat_id=chat_id,
            message_id=target_message_id,
        )
        if target_message:
            before_timestamp = min(int(before_timestamp), int(target_message.get("created_at") or before_timestamp))

    messages: List[str] = await directus_service.chat.get_messages_for_chat_before_timestamp(
        chat_id=chat_id,
        before_timestamp=int(before_timestamp),
        before_message_id=before_message_id,
        limit=limit + 1,
    )
    has_more = len(messages) > limit
    if has_more:
        messages = messages[1:]
    next_before_timestamp = None
    next_before_message_id = None
    if has_more and messages:
        try:
            first_message = json.loads(messages[0])
            next_before_timestamp = int(first_message.get("created_at"))
            next_before_message_id = first_message.get("message_id") or first_message.get("client_message_id") or first_message.get("id")
        except Exception:
            next_before_timestamp = None
            next_before_message_id = None
    await manager.send_personal_message(
        {
            "type": "compressed_chat_old_messages_response",
            "payload": {
                "chat_id": chat_id,
                "checkpoint_id": checkpoint_id,
                "messages": messages,
                "has_more": has_more,
                "next_before_timestamp": next_before_timestamp,
                "next_before_message_id": next_before_message_id,
                "target_message_id": target_message_id,
            },
        },
        user_id,
        device_fingerprint_hash,
    )
