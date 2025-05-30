# backend/core/api/app/routes/handlers/websocket_handlers/chat_content_batch_handler.py
# Handles requests from clients to fetch message content for a batch of chats.

import logging
from typing import List, Dict, Any, Optional

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService, chat_methods
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.schemas.chat import MessageResponse # Assuming MessageResponse is the schema for client-facing messages

logger = logging.getLogger(__name__)

async def handle_chat_content_batch(
    cache_service: CacheService, # Included for completeness, though directus_service might be primary source
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    manager: Any, # ConnectionManager
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
) -> None:
    """
    Handles a client's request to fetch full message content for a batch of chat IDs.
    This is typically called after an initial sync if some chats were delivered without
    their full message history.
    """
    chat_ids: Optional[List[str]] = payload.get("chat_ids")

    if not chat_ids:
        logger.warning(f"User {user_id}, Device {device_fingerprint_hash}: Received 'request_chat_content_batch' with no chat_ids.")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "No chat_ids provided in request_chat_content_batch."}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"User {user_id}, Device {device_fingerprint_hash}: Handling 'request_chat_content_batch' for {len(chat_ids)} chats.")

    messages_by_chat_id: Dict[str, List[MessageResponse]] = {}
    errors_occurred = False

    for chat_id in chat_ids:
        try:
            messages_data: Optional[List[MessageResponse]] = await directus_service.chat.get_all_messages_for_chat(
                chat_id=chat_id,
                decrypt_content=True
            )
            if messages_data is not None: # Check for None explicitly, empty list is valid
                messages_by_chat_id[chat_id] = messages_data
                logger.debug(f"User {user_id}, Chat {chat_id}: Fetched {len(messages_data)} messages for batch response.")
            else:
                # This case means an issue fetching/decrypting, or chat has no messages (which is fine)
                # If get_all_messages_for_chat returns None on error, or empty list for no messages.
                # Assuming it returns empty list for "no messages" and None for "error".
                # If it returns None for "no messages", this logic needs adjustment.
                # For now, if None, we assume an issue or truly no messages.
                # If it's critical to distinguish "no messages" vs "error", the method signature/behavior of get_all_messages_for_chat would need to clarify.
                # Sending an empty list for a chat_id in the response is acceptable if it has no messages.
                messages_by_chat_id[chat_id] = [] # Ensure chat_id is in response even if no messages
                logger.info(f"User {user_id}, Chat {chat_id}: No messages found or returned for batch response (or an error occurred upstream).")

        except Exception as e:
            errors_occurred = True
            logger.error(f"User {user_id}, Device {device_fingerprint_hash}: Error fetching messages for chat {chat_id} in batch request: {e}", exc_info=True)
            # Optionally, include per-chat error status in response, or just rely on overall error
            messages_by_chat_id[chat_id] = [] # Send empty for this chat on error

    response_payload_data = {"messages_by_chat_id": messages_by_chat_id}
    
    # Optionally, include an error flag in the response if any individual fetch failed
    if errors_occurred:
        response_payload_data["partial_error"] = True # Custom flag to indicate some chats might have failed

    try:
        await manager.send_personal_message(
            message={"type": "chat_content_batch_response", "payload": response_payload_data},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        logger.info(f"User {user_id}, Device {device_fingerprint_hash}: Sent 'chat_content_batch_response' for {len(messages_by_chat_id)} chats.")
    except Exception as e:
        logger.error(f"User {user_id}, Device {device_fingerprint_hash}: Failed to send 'chat_content_batch_response': {e}", exc_info=True)
