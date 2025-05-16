# backend/core/api/app/routes/handlers/websocket_handlers/delete_draft_handler.py
# This module handles the 'delete_draft' WebSocket message, responsible for deleting
# a chat draft from the Directus backend.

import logging
from typing import Dict, Any

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
        drafts_collection_name = "drafts"  # Standard Directus collection name for drafts
        drafts_handler = directus_service.get_items_handler(drafts_collection_name)

        # Filter to find the specific draft for the user and chat
        filter_criteria = {
            "user_id": {"_eq": user_id},
            "chat_id": {"_eq": chat_id}
        }
        
        # Fetch existing draft(s) to get its ID for deletion.
        # This ensures we only attempt to delete if it exists and we target the specific item.
        existing_drafts_response = await drafts_handler.get_items(
            filter=filter_criteria,
            fields=["id"]  # We only need the ID for deletion
        )

        if existing_drafts_response and existing_drafts_response.data:
            # Assuming one draft per user per chat, take the first one found.
            draft_to_delete_id = existing_drafts_response.data[0]["id"]
            await drafts_handler.delete_item(item_id=draft_to_delete_id)
            
            logger.info(
                f"User {user_id}, Device {device_fingerprint_hash}: Successfully deleted draft {draft_to_delete_id} "
                f"(chat_id: {chat_id}) from Directus."
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
                    "type": "draft_deleted",  # Frontend listens for this to remove draft display
                    "payload": {"chat_id": chat_id}
                },
                user_id=user_id,
                exclude_device_hash=device_fingerprint_hash  # Don't send to the originator again
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
            # No broadcast needed if no draft was found, as other clients should not have it or it's already gone.

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