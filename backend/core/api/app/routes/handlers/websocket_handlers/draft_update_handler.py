import logging
import time
from typing import Dict, Any, Optional

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

# Define content limits (as per Section 2.3)
MAX_DRAFT_WORDS = 14000
MAX_DRAFT_CHARS = 100000

def _validate_draft_content(draft_json: Optional[Dict[str, Any]]) -> bool:
    """Validates draft content against limits."""
    if not draft_json:
        return True # Null/empty draft is valid

    # Basic text extraction for validation (might need refinement based on Tiptap structure)
    text_content = ""
    try:
        if draft_json.get("type") == "doc" and "content" in draft_json:
            for node in draft_json["content"]:
                if node.get("type") == "paragraph" and "content" in node:
                    for text_node in node["content"]:
                        if text_node.get("type") == "text" and "text" in text_node:
                            text_content += text_node["text"] + " " # Add space between paragraphs
    except Exception as e:
        logger.error(f"Error extracting text for draft validation: {e}")
        # Allow saving if extraction fails, rely on client-side validation primarily
        return True

    text_content = text_content.strip()
    char_count = len(text_content)
    word_count = len(text_content.split())

    if char_count > MAX_DRAFT_CHARS:
        logger.warning(f"Draft validation failed: Exceeds character limit ({char_count}/{MAX_DRAFT_CHARS})")
        return False
    if word_count > MAX_DRAFT_WORDS:
        logger.warning(f"Draft validation failed: Exceeds word limit ({word_count}/{MAX_DRAFT_WORDS})")
        return False

    return True


async def handle_update_draft(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService, # Keep for potential future use
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    """Handles the 'update_draft' action for a user-specific draft,
    based on the revised chat_sync_architecture.md Section 7."""
    chat_id = payload.get("chat_id")
    # encrypted_draft_md is expected to be an encrypted markdown string or null
    encrypted_draft_md: Optional[str] = payload.get("encrypted_draft_md")

    if not chat_id:
        logger.warning(f"Received update_draft with missing chat_id from {user_id}/{device_fingerprint_hash}")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Missing chat_id for update_draft", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return

    logger.info(f"Processing update_draft for user {user_id}, chat {chat_id} from device {device_fingerprint_hash}")

    # Verify chat ownership
    # CRITICAL: Allow drafts for new chats that don't exist in Directus yet
    # When a user starts typing in a new chat, the chat is created locally but not yet in Directus.
    # The chat is only created in Directus when the first message is sent.
    # This matches the behavior in message_received_handler.py (lines 108-110)
    try:
        is_owner = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        if not is_owner:
            # Check if chat exists at all - if not, treat as new chat creation (allowed)
            chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
            if chat_metadata:
                # Chat exists but user doesn't own it - reject
                logger.warning(f"User {user_id} attempted to update draft for chat {chat_id} they don't own. Rejecting.")
                await manager.send_personal_message(
                    message={"type": "error", "payload": {"message": "You do not have permission to modify this chat.", "chat_id": chat_id}},
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash
                )
                return
            else:
                # Chat doesn't exist - this is a new chat creation, which is allowed
                logger.debug(f"Chat {chat_id} not found in database - treating as new chat draft (allowed)")
    except Exception as e_ownership:
        # On error checking ownership, check if chat exists
        # If chat doesn't exist, allow draft save (new chat creation)
        # If chat exists, reject for security (fail closed)
        try:
            chat_metadata = await directus_service.chat.get_chat_metadata(chat_id)
            if chat_metadata:
                # Chat exists but we couldn't verify ownership - reject for security
                logger.error(f"Error verifying ownership for existing chat {chat_id}, user {user_id}: {e_ownership}", exc_info=True)
                await manager.send_personal_message(
                    message={"type": "error", "payload": {"message": "Unable to verify chat ownership. Please try again.", "chat_id": chat_id}},
                    user_id=user_id,
                    device_fingerprint_hash=device_fingerprint_hash
                )
                return
            else:
                # Chat doesn't exist - treat as new chat creation (allowed)
                logger.debug(f"Chat {chat_id} not found in database during ownership check error - treating as new chat draft (allowed)")
        except Exception as e_metadata:
            # Couldn't check if chat exists - reject for security
            logger.error(f"Error checking if chat {chat_id} exists for user {user_id}: {e_metadata}", exc_info=True)
            await manager.send_personal_message(
                message={"type": "error", "payload": {"message": "Unable to verify chat permissions. Please try again.", "chat_id": chat_id}},
                user_id=user_id,
                device_fingerprint_hash=device_fingerprint_hash
            )
            return

    # Basic validation - check length limits for encrypted content
    if encrypted_draft_md and len(encrypted_draft_md) > MAX_DRAFT_CHARS:  # Use existing limit for encrypted content, NOTE: does this make sense? needs update?
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Draft content exceeds limits.", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return # Reject update

    # Content is already encrypted on client side, so we just store it directly
    encrypted_draft_str: Optional[str] = encrypted_draft_md

    # Increment user-specific draft_version in cache
    # This method needs to handle incrementing draft_v in user:{user_id}:chat:{chat_id}:draft
    # and user_draft_v:{user_id} in user:{user_id}:chat:{chat_id}:versions
    new_user_draft_v = await cache_service.increment_user_draft_version(user_id, chat_id)
    if new_user_draft_v is None:
        logger.error(f"Failed to increment user_draft_v in cache for user {user_id}, chat {chat_id}.")
        await manager.send_personal_message(
            message={"type": "error", "payload": {"message": "Failed to update draft version in cache.", "chat_id": chat_id}},
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash
        )
        return # Cannot proceed without new version

    # Update encrypted draft content and preview in user:{user_id}:chat:{chat_id}:draft cache key
    draft_preview_from_payload: Optional[str] = payload.get("encrypted_draft_preview")
    update_success = await cache_service.update_user_draft_in_cache(
        user_id, chat_id, encrypted_draft_str, new_user_draft_v,
        encrypted_draft_preview=draft_preview_from_payload
    )
    if not update_success:
        logger.error(f"Failed to update user draft in cache for user {user_id}, chat {chat_id}.")
        # Log error but continue, version was incremented.

    # --- Draft-only chat discoverability for cross-device sync ---
    # For draft-only NEW chats (not yet in the sorted set), we add them so that
    # initial_sync and reconnect can discover them on other devices.
    # We do NOT update the score for existing chats — only messages should change
    # last_edited_overall_timestamp for proper sorting. The frontend sorts chats
    # with drafts above non-draft chats via hasNonEmptyDraft() in chatSortUtils.ts.
    now_ts = int(time.time())
    chat_exists_in_sorted_set = await cache_service.check_chat_exists_for_user(user_id, chat_id)
    if not chat_exists_in_sorted_set:
        # This is a draft-only new chat — add it to the sorted set so other devices
        # can discover it during initial sync or reconnect.
        add_success = await cache_service.add_chat_to_ids_versions(user_id, chat_id, now_ts)
        if add_success:
            logger.info(f"Added draft-only new chat {chat_id} to chat_ids_versions for user {user_id}")
        else:
            logger.error(f"Failed to add draft-only new chat {chat_id} to chat_ids_versions for user {user_id}")

    # Get the current score for this chat (for the broadcast payload).
    # Other devices need this timestamp when creating the chat entry locally.
    chat_timestamp = await cache_service.get_chat_last_edited_overall_timestamp(user_id, chat_id)
    if chat_timestamp is None:
        chat_timestamp = now_ts

    # Broadcast to all connected devices for this user.
    # Include encrypted_draft_preview so other devices can show preview text in chat list.
    # Include last_edited_overall_timestamp so new chats can be created with correct sorting.
    broadcast_payload = {
        "event": "chat_draft_updated",
        "chat_id": chat_id,
        "data": {
            "encrypted_draft_md": encrypted_draft_str,
            "encrypted_draft_preview": draft_preview_from_payload,
        },
        "versions": {"draft_v": new_user_draft_v},
        "last_edited_overall_timestamp": chat_timestamp,
    }
    # Broadcast only to the current user's other connected devices
    await manager.broadcast_to_user(
        message=broadcast_payload,
        user_id=user_id,
        exclude_device_hash=device_fingerprint_hash # Exclude the sender device
    )
    logger.info(f"Broadcasted chat_draft_updated for user {user_id}, chat {chat_id}, new draft_v: {new_user_draft_v}")
