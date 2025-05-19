# backend/core/api/app/routes/handlers/websocket_handlers/delete_draft_handler.py
# This module handles the 'delete_draft' WebSocket message, responsible for deleting
# a chat draft from the Directus backend.

import logging
from typing import Dict, Any
import hashlib

from fastapi import WebSocket

from app.services.directus.directus import DirectusService
from app.routes.connection_manager import ConnectionManager
# CacheService and EncryptionService are not directly used in this handler
# as per the current requirements (draft cache expires, no specific encryption for deletion).

logger = logging.getLogger(__name__)

async def handle_delete_draft(
    websocket: WebSocket,
    manager: ConnectionManager,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """
    Handles the 'delete_draft' message from a WebSocket client.
    It attempts to delete a chat draft from Directus based on user_id and chat_id.
    """
    chat_id = payload.get("chatId")
    if not chat_id:
        logger.warning(
            f"User {user_id}, Device {device_fingerprint_hash}: Received delete_draft without chatId."
        )
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing chatId for delete_draft"}},
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(
        f"User {user_id}, Device {device_fingerprint_hash}: Received delete_draft request for chat_id: {chat_id}."
    )

    try:
        drafts_collection_name = "drafts"

        # Construct filter parameters for Directus API
        # Directus expects filters like: filter[field_name][_operator]=value
        # And fields as a comma-separated string or array.
        # The get_items method in DirectusService passes params directly.
        filter_params = {
            "filter[hashed_user_id][_eq]": hashlib.sha256(user_id.encode()).hexdigest(), # Hash user_id
            "filter[chat_id][_eq]": chat_id,
            "fields": "id", # Request only the ID
            "limit": 1 # We only need one if it exists
        }
        
        # Fetch existing draft(s) to get its ID for deletion.
        # directus_service.get_items returns a list of item data directly, or an empty list.
        existing_drafts_data = await directus_service.get_items(
            collection=drafts_collection_name,
            params=filter_params
        )

        if existing_drafts_data: # Check if the list is not empty
            # Assuming one draft per user per chat, take the first one found.
            draft_to_delete_id = existing_drafts_data[0]["id"]
            
            delete_successful = await directus_service.delete_item(
                collection=drafts_collection_name,
                item_id=draft_to_delete_id
            )
            
            if delete_successful:
                logger.info(
                    f"User {user_id}, Device {device_fingerprint_hash}: Successfully deleted draft {draft_to_delete_id} "
                )
                # Send confirmation receipt to the originating client
                await manager.send_personal_message(
                    message={"type": "draft_delete_receipt", "payload": {"chat_id": chat_id, "success": True}},
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash
                )
                # Broadcast to other devices of the same user that the draft was deleted
                await manager.broadcast_to_user(
                    message={
                        "type": "draft_deleted",
                        "payload": {"chat_id": chat_id}
                    },
                    user_id=user_id,
                    exclude_device_hash=device_fingerprint_hash
                )
            else:
                logger.error(
                    f"User {user_id}, Device {device_fingerprint_hash}: Failed to delete draft {draft_to_delete_id} "
                    f"(chat_id: {chat_id}) from Directus (delete_item returned False)."
                )
                await manager.send_personal_message(
                    message={"type": "error", "payload": {"message": f"Failed to delete draft {chat_id} on server.", "chat_id": chat_id}},
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash
                )
        else:
            logger.info(
                f"User {user_id}, Device {device_fingerprint_hash}: No draft found in Directus for chat_id: {chat_id} to delete."
            )
            await manager.send_personal_message(
                message={"type": "draft_delete_receipt", "payload": {"chat_id": chat_id, "success": False, "message": "Draft not found."}},
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
            # No broadcast needed if no draft was found

    except Exception as e:
        logger.error(
            f"User {user_id}, Device {device_fingerprint_hash}: Error processing delete_draft for chat_id {chat_id}: {e}",
            exc_info=True
        )
        # Attempt to send an error message to the client
        try:
            await manager.send_personal_message(
                message={"type": "error", "payload": {"message": f"Failed to process delete_draft for chat {chat_id}", "chat_id": chat_id}},
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
        except Exception as send_err:
            logger.error(
                f"User {user_id}, Device {device_fingerprint_hash}: Failed to send error message for delete_draft: {send_err}"
            )
# This section is now part of the conditional logic above.