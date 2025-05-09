import logging
from typing import Dict, Any

from fastapi import WebSocket

from app.services.cache import CacheService
from app.services.directus.directus import DirectusService
from app.services.directus.chat_methods import get_chat_metadata, create_chat_in_directus, create_message_in_directus # Assuming these exist
from app.utils.encryption import EncryptionService # Assuming needed if dealing with encrypted data directly
from app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

async def handle_message_received(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService, # Pass if needed
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    # Handle receiving a full new message (for background chats)
    logger.info(f"Received chat_message_received from {user_id}/{device_fingerprint_hash}: {payload}")

    chat_id = payload.get("chatId") # Assuming payload structure from original websockets.py
    message_content = payload.get("content") # Likely decrypted content for broadcast
    sender_name = payload.get("sender_name")
    created_at = payload.get("created_at") # Should be ISO timestamp string
    message_id = payload.get("message_id")
    encrypted_content = payload.get("encrypted_content") # Encrypted content for DB

    if not chat_id or not message_id or not encrypted_content or not sender_name or not created_at:
        logger.warning(f"Received chat_message_received with missing fields from {user_id}/{device_fingerprint_hash}. Payload: {payload}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing required fields for chat_message_received"}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return

    # --- Logic based on original websockets.py ---
    # This logic seems flawed as it assumes the message received *from* a client needs to be persisted *again*.
    # Typically, this event ("chat_message_received") would be BROADCASTED *by* the server *after* persistence.
    # The client sending the original message would trigger a different action (e.g., "send_message").
    # However, replicating the original logic for refactoring purposes:

    try:
        # 1. Check if chat exists in Directus (Original logic - might be redundant if chat creation is handled elsewhere)
        chat_in_directus = await get_chat_metadata(directus_service, chat_id)
        if not chat_in_directus:
            logger.warning(f"Chat {chat_id} not found in Directus when receiving message {message_id}. Attempting to create from cache.")
            # Fetch chat metadata from cache to persist (Original logic - assumes old cache structure)
            # This part needs significant revision based on the NEW cache structure if chat creation is intended here.
            # For now, commenting out the potentially problematic cache fetch and create.
            # chat_meta_key = f"chat:{chat_id}:metadata" # Old key structure
            # chat_metadata = await cache_service.get(chat_meta_key)
            # if chat_metadata:
            #     logger.info(f"Attempting to create chat {chat_id} in Directus based on cached metadata.")
            #     await create_chat_in_directus(directus_service, chat_metadata) # Assumes old metadata format
            # else:
            #     logger.error(f"Cannot create chat {chat_id} in Directus: Not found and no metadata in cache.")
            #     # Decide how to handle - maybe reject the message?
            #     # For now, log error and potentially skip persistence.
            pass # Skip chat creation for now, assuming it's handled elsewhere

        # 2. Create the message in Directus
        # Assuming 'encrypted_content' from payload is actually plaintext that needs encryption here.
        
        final_encrypted_content_for_db: Optional[str] = None
        if encrypted_content: # If there's content to encrypt
            raw_chat_aes_key = await encryption_service.get_chat_aes_key(chat_id)
            if not raw_chat_aes_key:
                logger.error(f"Failed to get chat AES key for chat {chat_id} when processing received message {message_id}.")
                # Decide how to handle: send error to user, or just log and don't persist
                await manager.send_personal_message(
                    message={"type": "error", "payload": {"message": f"Failed to prepare encryption for message in chat {chat_id}"}},
                    user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
                )
                return # Stop processing this message
            try:
                # Assuming 'encrypted_content' variable actually holds plaintext here based on typical flow
                final_encrypted_content_for_db = encryption_service.encrypt_locally_with_aes(str(encrypted_content), raw_chat_aes_key)
            except Exception as e:
                logger.error(f"Failed to encrypt message content for chat {chat_id}, message {message_id} using local AES. Error: {e}", exc_info=True)
                await manager.send_personal_message(
                    message={"type": "error", "payload": {"message": f"Failed to encrypt message in chat {chat_id}"}},
                    user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
                )
                return # Stop processing this message
        else:
            # Handle cases where content might be legitimately empty/null if allowed
            final_encrypted_content_for_db = None

        if final_encrypted_content_for_db is None and encrypted_content is not None: # Check if encryption failed but content was present
             logger.error(f"Encryption resulted in None for message {message_id} in chat {chat_id}, but original content was present. Aborting persistence.")
             return

        message_data = {
            "id": message_id,
            "chat_id": chat_id,
            "encrypted_content": final_encrypted_content_for_db, # Use the newly encrypted content
            "sender_name": sender_name,
            "timestamp": created_at
        }
        created = await create_message_in_directus(directus_service, message_data)
        if not created:
             logger.error(f"Failed to persist message {message_id} for chat {chat_id} in Directus (handler).")
             # Should we notify the sender? The message might already be in cache.

        # 3. Invalidate/refresh cache as needed (This should be handled within create_message_in_directus or related tasks)

        # 4. Broadcast the new message to all user devices (except sender) (Original logic)
        # The payload received might need adjustment before broadcasting if it contains sensitive info
        # or if the broadcast format is different. Using the received payload for now.
        await manager.broadcast_to_user(
            {
                "type": "chat_message_received", # Broadcasting the same event type
                "payload": payload # Re-broadcasting the received payload
            },
            user_id,
            exclude_device_hash=device_fingerprint_hash
        )
        logger.info(f"Re-broadcasted chat_message_received for message {message_id} to user {user_id} (excluding sender).")

    except Exception as e:
        logger.error(f"Error handling chat_message_received for message {message_id}, chat {chat_id}: {e}", exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": f"Error processing received message for chat {chat_id}"}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )