"""
replace_withdrawn_message_handler.py

Client -> server op `replace_withdrawn_assistant_message`: after the postprocessing
answer check withdrew an answer that the client had already persisted, the client
re-encrypts the localized notice with the chat key and sends it here. The server
only accepts it for a message id it withdrew itself (Redis marker set in
answer_safety.withdraw_answer), so a client cannot rewrite other assistant
messages. The ciphertext replaces the stored row and is broadcast to all devices
as `assistant_message_replaced`. Spec: answer-safety-check.
"""
import logging
from typing import Any, Dict

from fastapi import WebSocket

from backend.apps.ai.processing.answer_safety import withdrawn_marker_key
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService

logger = logging.getLogger(__name__)


async def _reject(manager: ConnectionManager, user_id: str, device: str, chat_id: Any, message: str) -> None:
    await manager.send_personal_message(
        message={"type": "error", "payload": {"message": message, "chat_id": chat_id}},
        user_id=user_id, device_fingerprint_hash=device,
    )


async def handle_replace_withdrawn_message(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
) -> None:
    """Store the client's sealed notice as the content of a server-withdrawn message."""
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")
    sealed = payload.get("encrypted_content")
    if not (isinstance(chat_id, str) and isinstance(message_id, str) and isinstance(sealed, str)
            and chat_id and message_id and sealed):
        await _reject(manager, user_id, device_fingerprint_hash, chat_id, "Missing chat_id, message_id or encrypted_content")
        return
    if not await directus_service.chat.check_chat_ownership(chat_id, user_id):
        await _reject(manager, user_id, device_fingerprint_hash, chat_id, "You do not own this chat.")
        return
    marker = withdrawn_marker_key(chat_id, message_id)
    if not await cache_service.get(marker):
        logger.warning("Refused replace of message %s in chat %s: not withdrawn by the server", message_id, chat_id)
        await _reject(manager, user_id, device_fingerprint_hash, chat_id, "This message was not withdrawn.")
        return
    row = await directus_service.chat.get_message_for_chat_by_client_id(chat_id, message_id)
    if not row or row.get("role") != "assistant" or not row.get("id"):
        await _reject(manager, user_id, device_fingerprint_hash, chat_id, "Assistant message not found.")
        return
    await directus_service.update_item(
        "messages", row["id"], {"encrypted_content": sealed}, admin_required=True,
    )
    # The sync cache copy is stale now; the next read reloads the durable row.
    await cache_service.delete_sync_messages_history(user_id, chat_id)
    await manager.broadcast_to_user(
        {"type": "assistant_message_replaced",
         "payload": {"chat_id": chat_id, "message_id": message_id, "encrypted_content": sealed}},
        user_id, exclude_device_hash=None,
    )
