# backend/core/api/app/routes/handlers/websocket_handlers/delete_draft_handler.py
# This module handles the 'delete_draft' WebSocket message, responsible for deleting
# a chat draft from the Directus backend.

import logging
from typing import Dict, Any
import hashlib

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

async def handle_delete_draft(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
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
    
    # Verify chat ownership
    # CRITICAL: Allow draft deletion for chats that don't exist in Directus yet
    # When a user starts typing in a new chat, the chat may only exist locally and not in Directus.
    # The chat is only created in Directus when the first message is sent.
    # This mirrors the behavior in message_received_handler.py where non-existent chats are treated
    # as new chat creation instead of a permission error.
    try:
        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        if not is_owner:
            # Check if the chat exists at all - if not, treat as new chat (allowed)
            chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
            if chat_metadata:
                # Chat exists but user doesn't own it - reject
                logger.warning(
                    f"User {user_id} attempted to delete draft for existing chat {chat_id} they don't own. Rejecting."
                )
                await manager.send_personal_message(
                    message={
                        "type": "error",
                        "payload": {
                            "message": "You do not have permission to modify this chat.",
                            "chat_id": chat_id,
                        },
                    },
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                )
                return
            else:
                # Chat doesn't exist in Directus - treat as new/local chat, allow draft deletion
                logger.debug(
                    f"Chat {chat_id} not found in Directus during delete_draft - treating as new/local chat (allowed)."
                )
    except Exception as ownership_error:
        # On error while checking ownership, attempt to see if chat exists
        # If chat exists, fail closed and return an error. If it doesn't, allow delete to proceed.
        logger.error(
            f"Error verifying ownership for chat {chat_id}, user {user_id} during delete_draft: {ownership_error}",
            exc_info=True,
        )
        try:
            chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
            if chat_metadata:
                # Existing chat but ownership check failed - reject for security
                await manager.send_personal_message(
                    message={
                        "type": "error",
                        "payload": {
                            "message": "Unable to verify chat permissions. Please try again.",
                            "chat_id": chat_id,
                        },
                    },
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash,
                )
                return
            else:
                # Chat doesn't exist in Directus - allow delete_draft to continue
                logger.debug(
                    f"Chat {chat_id} not found in Directus after ownership check error - treating as new/local chat for delete_draft."
                )
        except Exception as metadata_error:
            # Could not determine if chat exists - fail closed
            logger.error(
                f"Error checking existence of chat {chat_id} for user {user_id} during delete_draft: {metadata_error}",
                exc_info=True,
            )
            await manager.send_personal_message(
                message={
                    "type": "error",
                    "payload": {
                        "message": "Unable to verify chat permissions. Please try again.",
                        "chat_id": chat_id,
                    },
                },
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash,
            )
            return

    # Attempt to delete from cache
    cache_delete_success = await cache_service.delete_user_draft_from_cache(
        user_id=user_id,
        chat_id=chat_id
    )
    if cache_delete_success:
        logger.info(f"User {user_id}, Device {device_fingerprint_hash}: Successfully deleted draft from cache for chat_id: {chat_id}.")
    else:
        logger.warning(f"User {user_id}, Device {device_fingerprint_hash}: Draft cache key not found or failed to delete from cache for chat_id: {chat_id}.")

    # Also attempt to delete the user-specific draft version from the general chat versions key
    version_delete_success = await cache_service.delete_user_draft_version_from_chat_versions(
        user_id=user_id,
        chat_id=chat_id
    )
    if version_delete_success:
        logger.info(f"User {user_id}, Device {device_fingerprint_hash}: Successfully processed deletion of user-specific draft version from general chat versions for chat_id: {chat_id}.")
    else:
        # This is not critical enough to stop the whole process, but should be logged.
        logger.warning(f"User {user_id}, Device {device_fingerprint_hash}: Failed to delete user-specific draft version from general chat versions for chat_id: {chat_id}.")

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
                    f"(chat_id: {chat_id}) from Directus."
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
                return  # Exit early on Directus deletion failure
        else:
            logger.info(
                f"User {user_id}, Device {device_fingerprint_hash}: No draft found in Directus for chat_id: {chat_id} to delete."
            )
        
        # CRITICAL FIX: ALWAYS send confirmation and broadcast draft_deleted, even if no draft existed in Directus
        # This ensures consistent state across all user devices. Other devices might have a locally cached draft
        # that needs to be cleared, even if the draft was never synced to the server (e.g., server cache expired,
        # or draft was only saved locally on the other device).
        # Previously, the broadcast only happened if a draft was found and deleted from Directus, causing stale
        # drafts to persist on other devices.
        
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
        logger.info(
            f"User {user_id}, Device {device_fingerprint_hash}: Broadcasted draft_deleted to other devices for chat_id: {chat_id}."
        )

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