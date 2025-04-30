import logging
import time
import json
import hashlib # <-- Add import
from typing import List, Dict, Any, Optional
from app.schemas.chat import ChatResponse, MessageResponse, ChatListItem # Import ChatListItem
from datetime import datetime, timezone # Import timezone

logger = logging.getLogger(__name__)

# Helper function to convert timestamp/datetime string/number to datetime object
def _to_datetime(value: Any) -> Optional[datetime]:
    """Converts various timestamp formats to timezone-aware datetime objects (UTC)."""
    # Explicitly handle None without warning, as it's expected for last_message_timestamp
    if value is None:
        return None
    if isinstance(value, datetime):
        # If already datetime, ensure it's timezone-aware (assume UTC if naive)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        try:
            # Assume timestamp is in seconds UTC
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, TypeError, OSError): # Added OSError for potential invalid timestamp values
            pass
    if isinstance(value, str):
        try:
            # Attempt ISO format parsing (handle 'Z' correctly)
            dt_str = value.replace('Z', '+00:00')
            dt = datetime.fromisoformat(dt_str)
            # Ensure timezone aware (assume UTC if naive)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass # Try other formats if needed, or return None
    logger.warning(f"Could not convert value to datetime: {value} (type: {type(value)})")
    return None # Return None if conversion fails

async def handle_initial_sync(
    cache_service,
    directus_service, # Keep for potential future fallback or persistence check
    encryption_service,
    manager,
    user_id,
    device_fingerprint_hash,
    websocket
):
    chat_list_items: List[Dict[str, Any]] = [] # Use ChatListItem structure for the payload

    try:
        # 1. Get the hashed user ID
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        logger.debug(f"Fetching initial sync data for user {user_id} (hashed: {hashed_user_id[:8]}...)")

        # 2. Fetch the list of chat IDs associated with this user from the cache set
        user_chat_ids = await cache_service.get_chat_ids_for_user(hashed_user_id)
        logger.debug(f"Found {len(user_chat_ids)} chat IDs in user set for user {user_id}")

        # 3. Fetch metadata for each chat ID
        user_chat_metadata: List[Dict[str, Any]] = []
        for chat_id in user_chat_ids:
            metadata_key = f"chat:{chat_id}:metadata"
            metadata = await cache_service.get(metadata_key)
            if isinstance(metadata, dict):
                # Double-check the hashed_user_id just in case, though the set should be authoritative
                if metadata.get("hashed_user_id") == hashed_user_id:
                    user_chat_metadata.append(metadata)
                else:
                    logger.warning(f"Metadata for chat {chat_id} (from user set {hashed_user_id[:8]}) has mismatched hashed_user_id: {metadata.get('hashed_user_id')}. Skipping.")
            elif metadata is not None: # Log if we get something other than None or a dict
                 logger.warning(f"Invalid metadata found in cache for key {metadata_key}: {metadata}")
            # If metadata is None, it might have expired between getting the set and getting the key, which is acceptable.

        if not user_chat_metadata:
            logger.info(f"No valid chat metadata found in cache for user {user_id} (hashed: {hashed_user_id[:8]}...). Initial sync will be empty.")
            # Optional: Implement fallback to fetch from Directus if necessary,
            # but this won't include non-persisted drafts.

        logger.debug(f"Processing {len(user_chat_metadata)} chat metadata entries from cache for user {user_id}")

        # 3. Process each relevant metadata entry
        for chat_meta in user_chat_metadata:
            chat_id = chat_meta.get("id")
            if not chat_id:
                logger.warning(f"Skipping chat metadata entry with missing ID for user {user_id}. Metadata: {chat_meta}")
                continue

            vault_key_reference = chat_meta.get("vault_key_reference")
            encrypted_title = chat_meta.get("encrypted_title")
            # We don't need the encrypted_draft for the ChatListItem payload itself
            # version = chat_meta.get("version", 1) # Not needed for ChatListItem
            # created_at_val = chat_meta.get("created_at") # Not needed for ChatListItem
            updated_at_val = chat_meta.get("updated_at") # Needed for sorting
            last_message_timestamp_val = chat_meta.get("last_message_timestamp") # Needed for ChatListItem

            # Decrypt title
            decrypted_title = "Untitled Chat" # Default
            if encrypted_title and vault_key_reference:
                try:
                    # decrypt_with_chat_key returns Optional[str]
                    decrypted_title_str = await encryption_service.decrypt_with_chat_key(encrypted_title, vault_key_reference)
                    if decrypted_title_str:
                        decrypted_title = decrypted_title_str # Assign the string directly
                    else:
                        # If decryption returns None, keep the default or let the exception handler catch it
                        logger.warning(f"Decryption returned None for chat {chat_id} (user {user_id}). Using default title.")
                        # Keep decrypted_title as "Untitled Chat" (the default set earlier)
                except Exception as decrypt_err:
                    logger.error(f"Failed to decrypt title for chat {chat_id} (user {user_id}): {decrypt_err}")
                    decrypted_title = "Decryption Error" # Keep this fallback
            elif not encrypted_title:
                 logger.debug(f"Chat {chat_id} (user {user_id}) has no encrypted title in metadata.")


            # Determine last message timestamp for the list item payload
            last_message_timestamp_dt = _to_datetime(last_message_timestamp_val)

            # Prepare ChatListItem structure for the payload
            # Note: Frontend expects lastMessageTimestamp as ISO string or null
            try:
                list_item = ChatListItem(
                    id=chat_id,
                    title=decrypted_title,
                    lastMessageTimestamp=last_message_timestamp_dt.isoformat() if last_message_timestamp_dt else None,
                    # Add other fields expected by ChatListItem if necessary (e.g., hasUnread)
                )
                # Add the list item dictionary to our list
                chat_list_items.append(list_item.model_dump(mode='json')) # Use model_dump for correct serialization
            except Exception as pydantic_err:
                 logger.error(f"Failed to create ChatListItem for chat {chat_id} (user {user_id}): {pydantic_err}. Metadata: {chat_meta}", exc_info=True)


        # 4. Sort the list items based on the 'updated_at' field from the original metadata
        def get_sort_key(item_dict: Dict[str, Any]) -> float:
             item_id = item_dict.get("id")
             # Find the original metadata for the item_id
             original_meta = next((meta for meta in user_chat_metadata if meta.get("id") == item_id), None) # Use filtered list
             if original_meta:
                 # Use updated_at first, fallback to created_at
                 ts_val = original_meta.get("updated_at", original_meta.get("created_at"))
                 dt = _to_datetime(ts_val)
                 # Return timestamp float for sorting, 0 if conversion fails
                 return dt.timestamp() if dt else 0.0
             return 0.0 # Should not happen if item_dict came from user_chat_metadata

        # Sort by timestamp descending (most recent first)
        chat_list_items.sort(key=get_sort_key, reverse=True)

        # 5. Send the initial sync data
        #    Payload should match frontend expectation: { chats: ChatListItem[], lastOpenChatId?: string }
        payload = {
            "chats": chat_list_items,
            "lastOpenChatId": None # TODO: Implement fetching/storing last open chat ID if needed
        }
        logger.info(f"Sending initial_sync_data with {len(chat_list_items)} entries to {user_id}/{device_fingerprint_hash}")
        await manager.send_personal_message(
            {"type": "initial_sync_data", "payload": payload},
            user_id,
            device_fingerprint_hash
        )

    except Exception as sync_err:
        logger.error(f"Error preparing initial_sync_data for {user_id}/{device_fingerprint_hash}: {sync_err}", exc_info=True)
        # Send empty list on error
        await manager.send_personal_message(
            {"type": "initial_sync_data", "payload": {"chats": [], "lastOpenChatId": None, "error": "Failed to load chat list"}},
            user_id,
            device_fingerprint_hash
        )