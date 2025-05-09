import logging
import json # Added for serializing messages
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

async def create_chat_in_directus(directus_service, chat_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Create a chat record in Directus. Only called when the first message is sent for a chat.
    """
    try:
        logger.info(f"Creating chat in Directus: {chat_metadata.get('id')}")
        # Use the create_item method from DirectusService
        created = await directus_service.create_item('chats', chat_metadata)
        if created:
            logger.info(f"Chat created in Directus: {created.get('id')}")
            # Invalidate or refresh cache as needed
            await directus_service.cache.delete(f"chat:{chat_metadata['id']}:metadata")
            return created
        else:
            logger.error(f"Failed to create chat in Directus for {chat_metadata.get('id')}")
            return None
    except Exception as e:
        logger.error(f"Error creating chat in Directus: {e}", exc_info=True)
        return None

async def create_message_in_directus(directus_service, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Create a message record in Directus.
    """
    try:
        logger.info(f"Creating message in Directus for chat: {message_data.get('chat_id')}")
        created = await directus_service.create_item('messages', message_data)
        if created:
            logger.info(f"Message created in Directus: {created.get('id')}")
            # Invalidate or refresh chat/message cache as needed
            await directus_service.cache.delete(f"chat:{message_data['chat_id']}:messages")
            return created
        else:
            logger.error(f"Failed to create message in Directus for chat {message_data.get('chat_id')}")
            return None
    except Exception as e:
        logger.error(f"Error creating message in Directus: {e}", exc_info=True)
        return None
        return None

async def update_chat_fields_in_directus(
    directus_service: Any, # Should be DirectusService instance
    chat_id: str,
    fields_to_update: Dict[str, Any]
) -> bool:
    """
    Updates specific fields for a chat item in Directus.
    This is a more generic update method compared to update_chat_metadata,
    as it doesn't enforce version checking here (versioning is handled by the calling Celery task logic).
    Args:
        directus_service: An instance of the DirectusService.
        chat_id: The ID of the chat to update.
        fields_to_update: A dictionary of fields and their new values.
    Returns:
        True if the update was successful (or at least no error was raised by update_item), False otherwise.
    """
    logger.info(f"Updating chat fields for chat_id: {chat_id} with data: {fields_to_update.keys()}")
    try:
        # DirectusService.update_item returns the updated item data or None on failure.
        updated_item_data = await directus_service.update_item(
            collection='chats',
            item_id=chat_id,
            data=fields_to_update
        )
        if updated_item_data:
            logger.info(f"Successfully updated fields for chat {chat_id} in Directus.")
            return True
        else:
            # update_item method in DirectusService should log specific errors.
            logger.warning(f"Update operation for chat {chat_id} returned no data, assuming update failed or no changes made.")
            return False # Or True if no data back but no error is also acceptable
    except Exception as e:
        logger.error(f"Error updating chat fields for {chat_id} in Directus: {e}", exc_info=True)
        return False

# Fields required for get_core_chats_for_cache_warming from 'chats' collection
# Based on user_cache_tasks.py comments:
# id, encrypted_title, encrypted_draft (draft_content), draft_version_db,
# title_version, messages_version, unread_count, last_edited_overall_timestamp
CORE_CHAT_FIELDS_FOR_WARMING = (
    "id,"
    "user_id," # For verification
    "encrypted_title,"
    "encrypted_draft," # Assumed to be 'draft_content' in Directus schema for chats
    "draft_version_db,"
    "title_version,"
    "messages_version,"
    "unread_count,"
    "last_edited_overall_timestamp,"
    "vault_key_id" # Needed for any decryption context
)

# Fields required for get_full_chat_details_for_cache_warming from 'chats' collection
# (excludes messages, which are fetched separately and added)
# Based on user_cache_tasks.py comments:
# id, encrypted_title, encrypted_draft, draft_version_db, title_version,
# messages_version, unread_count, last_edited_overall_timestamp
CHAT_FIELDS_FOR_FULL_WARMING = (
    "id,"
    "user_id,"
    "encrypted_title,"
    "encrypted_draft,"
    "draft_version_db,"
    "title_version,"
    "messages_version,"
    "unread_count,"
    "last_edited_overall_timestamp,"
    "vault_key_id"
)

# Fields for messages based on backend/core/directus/schemas/messages.yml
MESSAGE_ALL_FIELDS = (
    "id,"
    "chat_id,"
    "encrypted_content,"
    "sender_name,"
    "created_at"
)

async def get_all_messages_for_chat(directus_service, chat_id: str) -> Optional[List[str]]:
    """
    Fetches all messages for a given chat_id from Directus, returning them as a list of JSON strings.
    Orders messages by creation date.
    """
    logger.debug(f"Fetching all messages for chat_id: {chat_id}")
    params = {
        'filter[chat_id][_eq]': chat_id,
        'fields': MESSAGE_ALL_FIELDS,
        'sort': 'created_at', # Sort by creation time, oldest first
        'limit': -1 # Fetch all messages
    }
    try:
        response = await directus_service.get_items('messages', params=params)
        if response and isinstance(response, list):
            logger.debug(f"Successfully fetched {len(response)} messages for chat {chat_id}")
            # Serialize each message dictionary to a JSON string
            return [json.dumps(message) for message in response]
        elif isinstance(response, list) and not response: # Explicitly handle empty list
            logger.debug(f"No messages found for chat_id: {chat_id}")
            return []
        else: # Handle unexpected non-list responses
            logger.warning(f"Unexpected response type or no messages found for chat_id: {chat_id}. Response: {response}")
            return []
    except Exception as e:
        logger.error(f"Error fetching messages for chat {chat_id}: {e}", exc_info=True)
        return None # Return None on error

async def get_full_chat_details_for_cache_warming(directus_service, chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches comprehensive details for a specific chat for cache warming.
    Includes chat fields and all its messages (as JSON strings).
    """
    logger.debug(f"Fetching full chat details for cache warming, chat_id: {chat_id}")
    params = {
        'filter[id][_eq]': chat_id,
        'fields': CHAT_FIELDS_FOR_FULL_WARMING,
        'limit': 1
    }
    try:
        chat_data_list = await directus_service.get_items('chats', params=params)
        if not (chat_data_list and isinstance(chat_data_list, list) and len(chat_data_list) > 0):
            logger.warning(f"Chat not found for full cache warming: {chat_id}")
            return None
        
        chat_details = chat_data_list[0]
        
        messages_list_json = await get_all_messages_for_chat(directus_service, chat_id)
        if messages_list_json is None:
            logger.error(f"Failed to fetch messages for chat {chat_id} during full cache warming. Chat details will be returned without messages.")
            chat_details["messages"] = [] # Return empty list for messages on error
        else:
            chat_details["messages"] = messages_list_json
        
        logger.debug(f"Successfully fetched full details for chat {chat_id} for cache warming.")
        return chat_details
        
    except Exception as e:
        logger.error(f"Error fetching full chat details for {chat_id} for cache warming: {e}", exc_info=True)
        return None

async def get_core_chats_for_cache_warming(directus_service, user_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
    """
    Fetches core data for multiple chats for a user, ordered by last_edited_overall_timestamp desc.
    Used for Phase 2 cache warming.
    """
    logger.debug(f"Fetching core chats for cache warming for user_id: {user_id}, limit: {limit}")
    params = {
        'filter[user_id][_eq]': user_id,
        'fields': CORE_CHAT_FIELDS_FOR_WARMING,
        'sort': '-last_edited_overall_timestamp',
        'limit': limit
    }
    try:
        response = await directus_service.get_items('chats', params=params)
        if response and isinstance(response, list):
            logger.debug(f"Successfully fetched {len(response)} core chat items for user {user_id} for cache warming.")
            return response
        else:
            logger.warning(f"No core chats found or unexpected response for user_id: {user_id} for cache warming.")
            return []
    except Exception as e:
        logger.error(f"Error fetching core chats for user {user_id} for cache warming: {e}", exc_info=True)
        return []