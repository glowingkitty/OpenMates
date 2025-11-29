import logging
import json
import time
from typing import Dict, Any, Optional

from fastapi import WebSocket

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService # Keep if needed for validation?
from backend.core.api.app.services.directus import chat_methods
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.connection_manager import ConnectionManager
# No Celery task needed for immediate draft persistence

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

    # Update encrypted draft_json in user:{user_id}:chat:{chat_id}:draft cache key
    update_success = await cache_service.update_user_draft_in_cache(user_id, chat_id, encrypted_draft_str, new_user_draft_v)
    if not update_success:
        logger.error(f"Failed to update user draft in cache for user {user_id}, chat {chat_id}.")
        # Log error but continue, version was incremented.

    # CRITICAL: Don't update last_edited_overall_timestamp for drafts
    # Only messages should update this timestamp for proper sorting
    # Chats with drafts will appear at the top via frontend sorting logic, but won't affect message-based sorting
    # now_ts = int(time.time())
    # update_score_success = await cache_service.update_chat_score_in_ids_versions(user_id, chat_id, now_ts)
    # if not update_score_success:
    #      logger.error(f"Failed to update last_edited_overall_timestamp score for chat {chat_id}. User: {user_id}")
    # --- Top N Message Cache Maintenance (Section 9.1) ---
    # NOTE: Top N cache maintenance removed since we're not updating the score anymore
    # Chats with drafts will still appear in the list, but won't affect Top N cache ordering
    # if update_score_success: # Only proceed if the score update was likely successful
    if False:  # Disabled - Top N maintenance not needed for draft updates
        try:
            top_n_chat_ids = await cache_service.get_chat_ids_versions(
                user_id, start=0, end=cache_service.TOP_N_MESSAGES_COUNT - 1
            )

            if chat_id in top_n_chat_ids:
                # Check if messages are already cached for this chat (check SYNC cache, not AI cache)
                messages_key = cache_service._get_sync_messages_key(user_id, chat_id)
                client = await cache_service.client
                if client and not await client.exists(messages_key):
                    logger.info(f"Chat {chat_id} entered Top N, caching messages to sync cache.")
                    try:
                        # First check if messages exist to avoid permission issues with encrypted fields
                        messages_exist = await directus_service.chat.check_messages_exist_for_chat(chat_id)
                        if messages_exist:
                            # Fetch client-encrypted messages from Directus
                            messages_list = await directus_service.chat.get_all_messages_for_chat(
                                chat_id=chat_id
                                )
                            if messages_list:
                                # Store to SYNC cache (client-encrypted, for client sync)
                                await cache_service.set_sync_messages_history(user_id, chat_id, messages_list, ttl=3600)
                                logger.info(f"Successfully cached client-encrypted messages to sync cache for Top N chat {chat_id}.")
                            else:
                                logger.info(f"No messages found in Directus for Top N chat {chat_id} to cache. This is normal for new chats.")
                        else:
                            logger.info(f"No messages exist for Top N chat {chat_id}. This is normal for new chats.")
                    except Exception as e_fetch:
                        # Handle permission errors or other issues gracefully
                        logger.warning(f"Failed to fetch messages for Top N chat {chat_id}: {e_fetch}. This may be a new chat with no messages yet.")
                        # Don't raise the exception, just log it and continue
                # else: # Optional: log if messages already cached or client unavailable
                #      logger.debug(f"Messages for chat {chat_id} already cached or client unavailable.")

            # Evict messages for chats that fell out of Top N
            # Get N+1 chats to find the one to evict (if any)
            # Note: This simple eviction assumes only one chat drops out at a time.
            # A more robust approach might involve checking all keys matching the pattern
            # user:{user_id}:chat:*:messages:sync and comparing against the current Top N set.
            
            # Simple eviction: Check the (N+1)th chat ID if it exists
            if len(top_n_chat_ids) >= cache_service.TOP_N_MESSAGES_COUNT:
                 # Get the ID just outside the top N
                 potential_evict_candidates = await cache_service.get_chat_ids_versions(
                     user_id, start=cache_service.TOP_N_MESSAGES_COUNT, end=cache_service.TOP_N_MESSAGES_COUNT
                 )
                 if potential_evict_candidates:
                     evict_chat_id = potential_evict_candidates[0]
                     # Check if this chat actually had messages cached before evicting (from SYNC cache)
                     messages_key_to_evict = cache_service._get_sync_messages_key(user_id, evict_chat_id)
                     if client and await client.exists(messages_key_to_evict):
                          logger.info(f"Chat {evict_chat_id} fell out of Top N. Evicting its sync cache messages.")
                          await cache_service.delete_sync_messages_history(user_id, evict_chat_id)

        except Exception as e_top_n:
            logger.error(f"Error during Top N message cache maintenance for chat {chat_id}: {e_top_n}", exc_info=True)
            # Log error but continue - don't let Top N cache issues break draft saving
    # --- End Top N Logic ---

    # NO immediate Celery task dispatched for draft persistence

    # Broadcast to all connected devices for this user
    broadcast_payload = {
        "event": "chat_draft_updated", # As per chat_sync_architecture.md Section 7
        "chat_id": chat_id,
        "data": {"encrypted_draft_md": encrypted_draft_str}, # Send encrypted draft (or null)
        "versions": {"draft_v": new_user_draft_v}, # Send new user-specific draft version, renamed to draft_v
        # REMOVED: "last_edited_overall_timestamp": now_ts # Don't send timestamp update for drafts
    }
    # Broadcast only to the current user's other connected devices
    await manager.broadcast_to_user(
        message=broadcast_payload,
        user_id=user_id,
        exclude_device_hash=device_fingerprint_hash # Exclude the sender device
    )
    logger.info(f"Broadcasted chat_draft_updated for user {user_id}, chat {chat_id}, new draft_v: {new_user_draft_v}")
