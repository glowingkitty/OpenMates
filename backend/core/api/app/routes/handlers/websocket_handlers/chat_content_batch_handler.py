# backend/core/api/app/routes/handlers/websocket_handlers/chat_content_batch_handler.py
# Handles requests from clients to fetch message content for a batch of chats.
# Used for immediate re-sync when data inconsistency is detected (local message
# count < server message count). This handler fetches encrypted messages from
# sync cache (or Directus fallback) and includes per-chat messages_v so the
# client can update its local version tracking.

import logging
from typing import List, Dict, Any, Optional

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)


async def handle_chat_content_batch(
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    manager: Any,  # ConnectionManager
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
) -> None:
    """
    Handles a client's request to fetch full message content for a batch of chat IDs.
    Triggered when the client detects a data inconsistency (local message count < server count)
    during Phase 2/3 sync. Fetches encrypted messages (zero-knowledge architecture) and includes
    per-chat messages_v so the client can update its version tracking.

    Response format:
    {
        "messages_by_chat_id": {
            "<chat_id>": [<JSON-serialized encrypted message strings>],
            ...
        },
        "versions_by_chat_id": {
            "<chat_id>": { "messages_v": <int>, "server_message_count": <int> },
            ...
        },
        "partial_error": true  // optional, only if some chats failed
    }
    """
    chat_ids: Optional[List[str]] = payload.get("chat_ids")

    if not chat_ids:
        logger.warning(
            f"User {user_id}, Device {device_fingerprint_hash}: "
            f"Received 'request_chat_content_batch' with no chat_ids."
        )
        await manager.send_personal_message(
            message={
                "type": "error",
                "payload": {"message": "No chat_ids provided in request_chat_content_batch."},
            },
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        return

    logger.info(
        f"User {user_id}, Device {device_fingerprint_hash}: "
        f"Handling 'request_chat_content_batch' for {len(chat_ids)} chats."
    )

    messages_by_chat_id: Dict[str, List[str]] = {}
    versions_by_chat_id: Dict[str, Dict[str, Any]] = {}
    errors_occurred = False

    for chat_id in chat_ids:
        try:
            # Verify chat ownership
            is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
            if not is_owner:
                logger.warning(
                    f"User {user_id} attempted to fetch messages for chat {chat_id} they don't own. Skipping."
                )
                messages_by_chat_id[chat_id] = []
                continue

            # --- Fetch messages: try sync cache first, fall back to Directus ---
            messages_data: List[str] = []

            # 1. Try sync cache (pre-serialized JSON strings with encrypted fields)
            cached_messages = await cache_service.get_sync_messages_history(user_id, chat_id)
            if cached_messages:
                messages_data = cached_messages
                logger.debug(
                    f"User {user_id}, Chat {chat_id}: "
                    f"Fetched {len(messages_data)} messages from sync cache for batch response."
                )
            else:
                # 2. Fall back to Directus (also returns JSON-serialized strings)
                directus_messages = await directus_service.chat.get_all_messages_for_chat(
                    chat_id=chat_id,
                    decrypt_content=False,  # Zero-knowledge: keep encrypted
                )
                if directus_messages is not None:
                    messages_data = directus_messages
                    logger.debug(
                        f"User {user_id}, Chat {chat_id}: "
                        f"Fetched {len(messages_data)} messages from Directus for batch response."
                    )
                else:
                    logger.info(
                        f"User {user_id}, Chat {chat_id}: "
                        f"No messages found for batch response."
                    )

            messages_by_chat_id[chat_id] = messages_data

            # --- Fetch messages_v: try cache first, fall back to Directus ---
            messages_v = 0
            cached_versions = await cache_service.get_chat_versions(user_id, chat_id)
            if cached_versions and cached_versions.messages_v is not None:
                messages_v = cached_versions.messages_v
            else:
                # Fall back to Directus chat metadata for messages_v
                chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
                if chat_metadata:
                    messages_v = chat_metadata.get("messages_v", 0)

            # Use max of messages_v and actual message count to handle async gaps
            # (Celery may have updated messages but not yet incremented messages_v)
            server_message_count = len(messages_data)
            effective_messages_v = max(messages_v, server_message_count)

            versions_by_chat_id[chat_id] = {
                "messages_v": effective_messages_v,
                "server_message_count": server_message_count,
            }

        except Exception as e:
            errors_occurred = True
            logger.error(
                f"User {user_id}, Device {device_fingerprint_hash}: "
                f"Error fetching messages for chat {chat_id} in batch request: {e}",
                exc_info=True,
            )
            messages_by_chat_id[chat_id] = []

    response_payload_data: Dict[str, Any] = {
        "messages_by_chat_id": messages_by_chat_id,
        "versions_by_chat_id": versions_by_chat_id,
    }

    if errors_occurred:
        response_payload_data["partial_error"] = True

    try:
        await manager.send_personal_message(
            message={"type": "chat_content_batch_response", "payload": response_payload_data},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
        )
        logger.info(
            f"User {user_id}, Device {device_fingerprint_hash}: "
            f"Sent 'chat_content_batch_response' for {len(messages_by_chat_id)} chats."
        )
    except Exception as e:
        logger.error(
            f"User {user_id}, Device {device_fingerprint_hash}: "
            f"Failed to send 'chat_content_batch_response': {e}",
            exc_info=True,
        )
