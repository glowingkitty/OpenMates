import logging
from typing import List, Dict, Any, Optional

# Implementations for chat-related methods interacting with Directus.

logger = logging.getLogger(__name__)

# Define metadata fields to fetch (exclude large content fields)
CHAT_METADATA_FIELDS = "id,user_id,encrypted_title,vault_key_id,created_at,updated_at,_version"

async def get_chat_metadata(directus_service, chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches metadata for a specific chat from Directus, excluding content.
    """
    logger.debug(f"Fetching chat metadata for chat_id: {chat_id}")
    params = {
        'filter[id][_eq]': chat_id,
        'fields': CHAT_METADATA_FIELDS,
        'limit': 1
    }
    try:
        response = await directus_service.get_items('chats', params=params, no_cache=True) # Use no_cache for potentially stale versions
        if response and isinstance(response, list) and len(response) > 0:
            logger.debug(f"Successfully fetched metadata for chat {chat_id}")
            return response[0]
        else:
            logger.warning(f"Chat metadata not found for chat_id: {chat_id}")
            return None
    except Exception as e:
        logger.error(f"Error fetching chat metadata for {chat_id}: {e}", exc_info=True)
        return None

async def get_user_chats_metadata(directus_service, user_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Fetches metadata for all chats belonging to a user from Directus, excluding content.
    """
    logger.debug(f"Fetching chat metadata list for user_id: {user_id}, limit: {limit}, offset: {offset}")
    params = {
        'filter[user_id][_eq]': user_id,
        'fields': CHAT_METADATA_FIELDS,
        'limit': limit,
        'offset': offset,
        'sort': '-updated_at' # Sort by most recently updated
    }
    try:
        response = await directus_service.get_items('chats', params=params)
        if response and isinstance(response, list):
            logger.debug(f"Successfully fetched {len(response)} chat metadata items for user {user_id}")
            return response
        else:
            # Handle cases where the response might be None or not a list (though get_items should return list or raise)
            logger.warning(f"No chat metadata found or unexpected response for user_id: {user_id}")
            return []
    except Exception as e:
        logger.error(f"Error fetching user chats metadata for {user_id}: {e}", exc_info=True)
        return []

async def update_chat_metadata(directus_service, chat_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Updates metadata for a specific chat in Directus.
    Requires 'basedOnVersion' in the data payload for optimistic concurrency control.
    Increments the '_version' field on successful update.
    """
    logger.debug(f"Attempting to update chat metadata for chat_id: {chat_id} with data: {data}")

    based_on_version = data.pop('basedOnVersion', None)

    if based_on_version is None:
        logger.error(f"Update rejected for chat {chat_id}: 'basedOnVersion' is missing in the payload.")
        # Consider raising a specific exception here might be better for the caller
        return None # Indicate failure due to missing version

    try:
        # Fetch the current metadata (specifically the version) without using cache
        current_metadata = await get_chat_metadata(directus_service, chat_id)

        if not current_metadata:
            logger.error(f"Update rejected for chat {chat_id}: Chat not found.")
            return None # Indicate failure

        current_version = current_metadata.get('_version')

        logger.info(f"Version check for chat {chat_id}: Client version={based_on_version}, Server version={current_version}")

        if current_version is None:
             logger.error(f"Update rejected for chat {chat_id}: Server version (_version) is missing.")
             return None # Data integrity issue

        if based_on_version != current_version:
            logger.error(f"Version conflict for chat {chat_id}. Update rejected. Client version: {based_on_version}, Server version: {current_version}")
            # Optionally, return a specific conflict indicator or raise an exception
            # e.g., raise VersionConflictError("Version mismatch")
            return None # Indicate failure due to conflict

        # --- Version Match ---
        # Increment version and prepare data for update
        update_payload = data.copy() # Avoid modifying the original input dict directly
        update_payload['_version'] = current_version + 1
        # Ensure only metadata fields are updated (prevent accidental content update if passed)
        allowed_update_fields = {f for f in CHAT_METADATA_FIELDS.split(',') if f not in ['id', 'user_id', 'created_at']}
        update_payload = {k: v for k, v in update_payload.items() if k in allowed_update_fields or k == '_version'}


        logger.debug(f"Version match for chat {chat_id}. Proceeding with update. New version: {update_payload['_version']}")

        # Use the directus_service's update_item method
        # update_item should handle authentication and retries internally
        updated_item_data = await directus_service.update_item('chats', chat_id, update_payload)

        if updated_item_data:
            logger.info(f"Successfully updated chat metadata for {chat_id}. New version: {updated_item_data.get('_version')}")
            return updated_item_data # Return the updated data from Directus
        else:
            # update_item already logs errors, but we can log context here
            logger.error(f"Failed to update chat metadata for {chat_id} after version check passed.")
            return None # Indicate failure during the update API call

    except Exception as e:
        logger.error(f"Error updating chat metadata for {chat_id}: {e}", exc_info=True)
        return None