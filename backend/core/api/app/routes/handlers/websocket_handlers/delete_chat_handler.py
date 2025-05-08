import logging
from typing import Dict, Any

from fastapi import WebSocket

from app.services.cache import CacheService
from app.services.directus.directus import DirectusService # Keep if needed for future DB interaction
from app.utils.encryption import EncryptionService # Keep if needed
from app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

async def handle_delete_chat(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService, # Pass if needed
    encryption_service: EncryptionService, # Pass if needed
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    chat_id = payload.get("chatId") # Assuming payload structure from original websockets.py
    if not chat_id:
        logger.warning(f"Received delete_chat without chatId from {user_id}/{device_fingerprint_hash}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing chatId for delete_chat"}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"Received delete_chat request for chat {chat_id} from {user_id}/{device_fingerprint_hash}")

    try:
        # --- Logic based on original websockets.py ---
        # Mark chat as deleted (tombstone) in cache instead of hard delete
        # This uses the *new* cache structure methods.

        # 1. Mark as deleted in cache (tombstone)
        # We need to remove the chat from the user's sorted set and delete the specific chat keys.
        # a) Remove from sorted set
        removed_from_set = await cache_service.remove_chat_from_ids_versions(user_id, chat_id)
        if removed_from_set:
             logger.info(f"Removed chat {chat_id} from user:{user_id}:chat_ids_versions sorted set.")
        else:
             logger.warning(f"Chat {chat_id} not found in user:{user_id}:chat_ids_versions sorted set during delete.")

        # b) Delete specific chat keys (:versions, :list_item_data, :messages)
        # Use pipeline for efficiency
        client = await cache_service.client
        if client:
            async with client.pipeline(transaction=False) as pipe: # No transaction needed for deletes
                pipe.delete(cache_service._get_chat_versions_key(user_id, chat_id))
                pipe.delete(cache_service._get_chat_list_item_data_key(user_id, chat_id))
                pipe.delete(cache_service._get_chat_messages_key(user_id, chat_id))
                results = await pipe.execute()
                # results will be a list of delete counts (0 or 1 for each key)
                logger.info(f"Deleted specific cache keys for chat {chat_id} (user: {user_id}). Results: {results}")
                tombstone_success = sum(results) > 0 # Consider success if any key was deleted
        else:
             logger.error(f"Cache client not available, cannot delete specific keys for chat {chat_id}.")
             tombstone_success = False # Indicate failure if client is down

        # Note: The original code used cache_service.mark_chat_deleted which operated on the old
        # 'chat:{chat_id}:metadata' key. The new logic directly removes the relevant keys
        # associated with the new architecture. Directus deletion is NOT handled here,
        # that would be a separate process (e.g., triggered by a different event or background task).

        # 2. Broadcast deletion confirmation
        # Send tombstone=True to indicate it's a deletion event for the client list
        await manager.broadcast_to_user(
            {
                "type": "chat_deleted", # Use a consistent event type
                "payload": {"chat_id": chat_id, "tombstone": True}
            },
            user_id,
            exclude_device_hash=None # Send to all devices, including sender
        )
        logger.info(f"Broadcasted chat_deleted event for chat {chat_id} to user {user_id}.")

    except Exception as e:
        logger.error(f"Error processing delete_chat for chat {chat_id}, user {user_id}: {e}", exc_info=True)
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": f"Failed to process delete request for chat {chat_id}", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )