import logging
import json
from typing import List, Dict, Any, Optional, Union

from app.utils.encryption import EncryptionService # Added for decryption

# Implementations for chat-related methods interacting with Directus.

logger = logging.getLogger(__name__)

# Define metadata fields to fetch (exclude large content fields)
CHAT_METADATA_FIELDS = "id,hashed_user_id,encrypted_title,created_at,updated_at" # Use hashed_user_id, removed _version

async def get_chat_metadata(directus_service, chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches metadata for a specific chat from Directus, excluding content.
    """
    logger.info(f"Fetching chat metadata for chat_id: {chat_id}")
    params = {
        'filter[id][_eq]': chat_id,
        'fields': CHAT_METADATA_FIELDS,
        'limit': 1
    }
    try:
        response = await directus_service.get_items('chats', params=params, no_cache=True) # Use no_cache for potentially stale versions
        if response and isinstance(response, list) and len(response) > 0:
            logger.info(f"Successfully fetched metadata for chat {chat_id}")
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
    logger.info(f"Fetching chat metadata list for user_id: {user_id}, limit: {limit}, offset: {offset}")
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
            logger.info(f"Successfully fetched {len(response)} chat metadata items for user {user_id}")
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
    logger.info(f"Attempting to update chat metadata for chat_id: {chat_id} with data: {data}")

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


        logger.info(f"Version match for chat {chat_id}. Proceeding with update. New version: {update_payload['_version']}")

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
        success, result_data = await directus_service.create_item('chats', chat_metadata)
        if success and result_data:
            logger.info(f"Chat created in Directus: {result_data.get('id')}")
            # Invalidate or refresh cache as needed
            # Ensure chat_metadata has 'id' before using it for cache deletion
            if chat_metadata and 'id' in chat_metadata:
                await directus_service.cache.delete(f"chat:{chat_metadata['id']}:metadata")
            return result_data # Return the created item data
        else:
            # result_data contains error details if success is False
            logger.error(f"Failed to create chat in Directus for {chat_metadata.get('id')}. Details: {result_data}")
            return None
    except Exception as e:
        logger.error(f"Error creating chat in Directus: {e}", exc_info=True)
        return None

async def create_message_in_directus(directus_service, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Create a message record in Directus.
    """
    try:
        logger.info(f"Attempting to create message in Directus for chat: {message_data.get('chat_id')}")
        
        # Prepare the payload for Directus
        payload_to_directus = {
            "client_message_id": message_data.get("id"), # Map original 'id' to 'client_message_id'
            "chat_id": message_data.get("chat_id"),
            "hashed_user_id": message_data.get("hashed_user_id"),
            "sender_name": message_data.get("sender_name"),
            "encrypted_content": message_data.get("encrypted_content"),
            "created_at": message_data.get("created_at"),
        }
        
        # Remove None values from payload, as Directus might not like explicit nulls for some fields
        # unless they are specifically designed to be nullable.
        payload_to_directus = {k: v for k, v in payload_to_directus.items() if v is not None}
        success, result_data = await directus_service.create_item('messages', payload_to_directus)
        
        if success and result_data:
            logger.info(f"Message created in Directus. Directus ID: {result_data.get('id')}, Client Message ID: {result_data.get('client_message_id')}")
            # Invalidate or refresh chat/message cache as needed
            chat_id = message_data.get('chat_id') # Use original chat_id for cache key
            if chat_id:
                await directus_service.cache.delete(f"chat:{chat_id}:messages")
            return result_data # Return the created item data
        else:
            # result_data contains error details if success is False
            logger.error(f"Failed to create message in Directus for chat {message_data.get('chat_id')}. Details: {result_data}")
            return None
    except Exception as e:
        logger.error(f"Error creating message in Directus: {e}", exc_info=True)
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
CORE_CHAT_FIELDS_FOR_WARMING = (
    "id,"
    "hashed_user_id,"
    "encrypted_title,"
    "title_version,"
    "messages_version,"
    "unread_count,"
    "last_edited_overall_timestamp"
)

# Fields required for get_full_chat_details_for_cache_warming from 'chats' collection
CHAT_FIELDS_FOR_FULL_WARMING = (
    "id,"
    "hashed_user_id,"
    "encrypted_title,"
    "title_version,"
    "messages_version,"
    "unread_count,"
    "last_edited_overall_timestamp"
)

# Fields for the new 'drafts' collection
DRAFT_FIELDS_FOR_WARMING = (
    "id," # draft_id
    "chat_id,"
    "hashed_user_id," # Assuming this field name from drafts.yml
    "encrypted_content,"
    "version," # draft version for this user/chat
    "updated_at"
)

# Fields for messages based on backend/core/directus/schemas/messages.yml
MESSAGE_ALL_FIELDS = (
    "id,"  # This will be the Directus auto-generated PK
    "client_message_id," # Our application-generated ID
    "chat_id,"
    "encrypted_content,"
    "sender_name,"
    "created_at" # Application-provided timestamp
)

async def get_all_messages_for_chat(
    directus_service,
    encryption_service: EncryptionService, # Added
    chat_id: str,
    decrypt_content: bool = False
) -> Optional[List[Union[str, Dict[str, Any]]]]:
    """
    Fetches all messages for a given chat_id from Directus.
    Orders messages by creation date.
    If decrypt_content is True, decrypts 'encrypted_content' using local AES and returns list of dicts.
    Otherwise, returns list of JSON strings with content still encrypted.
    """
    logger.info(f"Fetching all messages for chat_id: {chat_id}, decrypt: {decrypt_content}")
    params = {
        'filter[chat_id][_eq]': chat_id,
        'fields': MESSAGE_ALL_FIELDS,
        'sort': 'created_at',
        'limit': -1
    }
    try:
        messages_from_db = await directus_service.get_items('messages', params=params)
        if not messages_from_db or not isinstance(messages_from_db, list):
            logger.info(f"No messages found or unexpected response for chat_id: {chat_id}")
            return []

        logger.info(f"Successfully fetched {len(messages_from_db)} messages for chat {chat_id} from DB.")
        
        processed_messages = []
        if decrypt_content:
            raw_chat_aes_key = await encryption_service.get_chat_aes_key(chat_id)
            if not raw_chat_aes_key:
                logger.error(f"Cannot decrypt messages for chat {chat_id}: Failed to retrieve chat AES key.")
                # Depending on desired behavior, could return messages with encrypted content or raise/return error indicator
                # For now, returning them encrypted if key is missing, with a warning.
                # This block is now unreachable if raw_chat_aes_key is None due to the check above.
                # However, to be safe, if it were reached, we'd return encrypted.
                # For now, the logic proceeds assuming raw_chat_aes_key is available if this point is reached.
                pass # Fall through to decryption loop

            for message_dict in messages_from_db:
                if message_dict.get("encrypted_content"):
                    try:
                        # Use the new decrypt_with_chat_key method
                        decrypted_text = await encryption_service.decrypt_with_chat_key(
                            ciphertext=message_dict["encrypted_content"],
                            key_id=chat_id # chat_id is the key_id for chat messages
                        )
                        message_dict["content"] = json.loads(decrypted_text) if decrypted_text else None
                    except Exception as e:
                        logger.error(f"Failed to decrypt message content for message {message_dict.get('id')} in chat {chat_id} using decrypt_with_chat_key: {e}", exc_info=True)
                        message_dict["content"] = None
                        message_dict["decryption_error"] = True
                else:
                    message_dict["content"] = None # No content to decrypt
                processed_messages.append(message_dict)
            return processed_messages
        else:
            # Return as list of JSON strings if not decrypting (original behavior)
            return [json.dumps(msg) for msg in messages_from_db]

    except Exception as e:
        logger.error(f"Error fetching messages for chat {chat_id}: {e}", exc_info=True)
        return None

async def _get_user_draft_for_chat(directus_service, user_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches a specific user's draft for a specific chat from the 'drafts' collection.
    """
    logger.info(f"Fetching draft for user_id: {user_id}, chat_id: {chat_id}")
    # Assuming user_id in Directus 'drafts' table is stored as 'hashed_user_id'
    # Adjust field name if it's different (e.g., 'user_id' directly)
    params = {
        'filter[chat_id][_eq]': chat_id,
        'filter[hashed_user_id][_eq]': user_id, # Match against the hashed_user_id field
        'fields': DRAFT_FIELDS_FOR_WARMING,
        'limit': 1
    }
    try:
        response = await directus_service.get_items('drafts', params=params)
        if response and isinstance(response, list) and len(response) > 0:
            logger.info(f"Successfully fetched draft for user {user_id}, chat {chat_id}")
            return response[0]
        else:
            logger.info(f"No draft found for user {user_id}, chat {chat_id}")
            return None
    except Exception as e:
        logger.error(f"Error fetching draft for user {user_id}, chat {chat_id}: {e}", exc_info=True)
        return None

async def get_full_chat_and_user_draft_details_for_cache_warming(
    directus_service, user_id: str, chat_id: str
) -> Optional[Dict[str, Any]]:
    """
    Fetches comprehensive details for a specific chat for cache warming.
    Includes chat fields, all its messages (as JSON strings), and the current user's draft.
    """
    logger.info(f"Fetching full chat and user draft details for cache warming, user_id: {user_id}, chat_id: {chat_id}")
    
    chat_params = {
        'filter[id][_eq]': chat_id,
        # 'filter[user_id][_eq]': user_id, # Assuming chat ownership/access is already verified or handled by Directus permissions
        'fields': CHAT_FIELDS_FOR_FULL_WARMING,
        'limit': 1
    }
    try:
        chat_data_list = await directus_service.get_items('chats', params=chat_params)
        if not (chat_data_list and isinstance(chat_data_list, list) and len(chat_data_list) > 0):
            logger.warning(f"Chat not found for full cache warming: {chat_id}")
            return None
        
        chat_details = chat_data_list[0]
        
        messages_list_json = await get_all_messages_for_chat(directus_service, chat_id)
        chat_details["messages"] = messages_list_json if messages_list_json is not None else []
        
        user_draft_details = await _get_user_draft_for_chat(directus_service, user_id, chat_id)
        
        result = {
            "chat_details": chat_details,
            "user_encrypted_draft_content": user_draft_details.get("encrypted_content") if user_draft_details else None,
            "user_draft_version_db": user_draft_details.get("version", 0) if user_draft_details else 0
        }
        
        logger.info(f"Successfully fetched full details for chat {chat_id} and user draft for user {user_id}.")
        return result
        
    except Exception as e:
        logger.error(f"Error fetching full chat and user draft details for {chat_id}, user {user_id}: {e}", exc_info=True)
        return None

async def get_core_chats_and_user_drafts_for_cache_warming(
    directus_service, user_id: str, limit: int = 1000
) -> List[Dict[str, Any]]:
    """
    Fetches core data for multiple chats for a user, ordered by last_edited_overall_timestamp desc,
    and includes each user's specific draft for those chats.
    Used for Phase 2 cache warming.
    """
    logger.info(f"Fetching core chats and user drafts for cache warming for user_id: {user_id}, limit: {limit}")
    
    # 1. Fetch core chat data
    # Assuming 'user_id' in 'chats' table refers to the owner or a relevant user context for filtering.
    # If chats are shared, this filter might need adjustment or rely on Directus permissions.
    chat_params = {
        'filter[hashed_user_id][_eq]': user_id, # Corrected field name to hashed_user_id
        'fields': CORE_CHAT_FIELDS_FOR_WARMING,
        'sort': '-last_edited_overall_timestamp',
        'limit': limit
    }
    
    results_list = []
    try:
        logger.info(f"Directus 'chats' query params for user {user_id} (cache warming): {json.dumps(chat_params)}")
        # get_items now directly returns the list of items (chats) or an empty list on error/no data.
        core_chats_list = await directus_service.get_items('chats', params=chat_params)
        
        # Log the received data. core_chats_list is expected to be a list of dicts.
        logger.info(f"Directus 'chats' response data for user {user_id} (cache warming): {json.dumps(core_chats_list)}")

        if not core_chats_list: # Handles None or empty list
            logger.warning(f"No core chats found for user_id: {user_id} for cache warming.")
            return []
        
        # Ensure it's a list, though get_items should guarantee this or an empty list.
        if not isinstance(core_chats_list, list):
            logger.error(f"Unexpected data type for core_chats_list for user_id: {user_id}. Expected list, got {type(core_chats_list)}. Data: {core_chats_list}")
            return []

        logger.info(f"Successfully fetched {len(core_chats_list)} core chat items for user {user_id}.")

        # 2. For each chat, fetch the user's draft
        for chat_data in core_chats_list:
            chat_id = chat_data["id"]
            user_draft_details = await _get_user_draft_for_chat(directus_service, user_id, chat_id)
            
            results_list.append({
                "chat_details": chat_data,
                "user_encrypted_draft_content": user_draft_details.get("encrypted_content") if user_draft_details else None,
                "user_draft_version_db": user_draft_details.get("version", 0) if user_draft_details else 0
            })
            
        logger.info(f"Processed {len(results_list)} chats with their user-specific drafts for user {user_id}.")
        return results_list
            
    except Exception as e:
        logger.error(f"Error fetching core chats and user drafts for user {user_id}: {e}", exc_info=True)
        return []

# --- Methods for interacting with the 'Drafts' collection ---

async def get_user_draft_from_directus(directus_service, hashed_user_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches a specific user's draft for a specific chat from the 'drafts' collection in Directus.
    Uses DRAFT_FIELDS_FOR_WARMING to specify fields.
    """
    logger.info(f"Fetching Directus draft for hashed_user_id: {hashed_user_id}, chat_id: {chat_id}")
    params = {
        'filter[chat_id][_eq]': chat_id,
        'filter[hashed_user_id][_eq]': hashed_user_id,
        'fields': DRAFT_FIELDS_FOR_WARMING, # Defined earlier, includes id, version, encrypted_content etc.
        'limit': 1
    }
    try:
        response = await directus_service.get_items('drafts', params=params)
        if response and isinstance(response, list) and len(response) > 0:
            logger.info(f"Successfully fetched Directus draft for user {hashed_user_id}, chat {chat_id}")
            return response[0]
        else:
            logger.info(f"No Directus draft found for user {hashed_user_id}, chat {chat_id}")
            return None
    except Exception as e:
        logger.error(f"Error fetching Directus draft for user {hashed_user_id}, chat {chat_id}: {e}", exc_info=True)
        return None

async def create_user_draft_in_directus(directus_service, draft_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Creates a new user draft record in the 'drafts' collection in Directus.
    """
    chat_id = draft_data.get("chat_id")
    hashed_user_id = draft_data.get("hashed_user_id")
    logger.info(f"Creating Directus draft for user {hashed_user_id}, chat {chat_id}")
    try:
        # 'id' for the draft itself should be auto-generated by Directus if not provided.
        # Ensure draft_data contains all required fields for the 'drafts' collection.
        # create_item returns a tuple: (success_bool, data_or_error_dict)
        success, result_data = await directus_service.create_item('drafts', draft_data)
        if success and result_data:
            # result_data is the created draft dictionary
            draft_id = result_data.get('id')
            logger.info(f"Successfully created Directus draft ID {draft_id} for user {hashed_user_id}, chat {chat_id}")
            return result_data # Return the created draft data
        else:
            # result_data contains error details if success is False
            logger.error(f"Failed to create Directus draft for user {hashed_user_id}, chat {chat_id}. Details: {result_data}")
            return None
    except Exception as e:
        logger.error(f"Exception during Directus draft creation for user {hashed_user_id}, chat {chat_id}: {e}", exc_info=True)
        return None

async def update_user_draft_in_directus(directus_service, draft_id: str, fields_to_update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Updates an existing user draft record in the 'drafts' collection in Directus by its ID.
    """
    logger.info(f"Updating Directus draft ID {draft_id} with fields: {list(fields_to_update.keys())}")
    try:
        updated_draft = await directus_service.update_item(
            collection='drafts',
            item_id=draft_id,
            data=fields_to_update
        )
        if updated_draft:
            logger.info(f"Successfully updated Directus draft ID {draft_id}.")
            return updated_draft
        else:
            logger.error(f"Failed to update Directus draft ID {draft_id}. Response was empty or indicated failure.")
            return None
    except Exception as e:
        logger.error(f"Error updating Directus draft ID {draft_id}: {e}", exc_info=True)
        return None

async def delete_all_drafts_for_chat(directus_service: Any, chat_id: str) -> bool:
    """
    Deletes ALL draft items for a specific chat_id from the 'drafts' collection in Directus.
    Args:
        directus_service: An instance of the DirectusService.
        chat_id: The ID of the chat for which all drafts should be deleted.
    Returns:
        True if all drafts were successfully deleted or if no drafts existed.
        False if any error occurred during the deletion of any draft.
    """
    logger.info(f"Attempting to delete all drafts for chat_id: {chat_id} from Directus.")
    try:
        # Step 1: Find all draft IDs for the given chat_id
        draft_params = {
            'filter[chat_id][_eq]': chat_id,
            'fields': 'id',  # We only need the draft's ID
            'limit': -1      # Ensure all drafts are fetched
        }
        drafts_to_delete_list = await directus_service.get_items('drafts', params=draft_params)

        if not drafts_to_delete_list:
            logger.info(f"No drafts found for chat_id: {chat_id} in Directus. Nothing to delete.")
            return True

        logger.info(f"Found {len(drafts_to_delete_list)} drafts to delete for chat_id: {chat_id}.")
        
        all_deleted_successfully = True
        for draft_item in drafts_to_delete_list:
            draft_item_id = draft_item.get('id')
            if not draft_item_id:
                logger.error(f"Found draft entry for chat_id: {chat_id} but it has no 'id'. Cannot delete. Entry: {draft_item}")
                all_deleted_successfully = False
                continue  # Skip to the next draft

            # Step 2: Delete the draft item by its primary ID
            success = await directus_service.delete_item(collection='drafts', item_id=draft_item_id)
            if success:
                logger.info(f"Successfully deleted draft (ID: {draft_item_id}) for chat_id: {chat_id} from Directus.")
            else:
                logger.warning(f"Failed to delete draft (ID: {draft_item_id}) for chat_id: {chat_id} from Directus.")
                all_deleted_successfully = False # Mark overall success as false if any deletion fails
        
        if all_deleted_successfully:
            logger.info(f"Successfully deleted all found drafts for chat_id: {chat_id}.")
        else:
            logger.warning(f"One or more drafts could not be deleted for chat_id: {chat_id}.")
        return all_deleted_successfully

    except Exception as e:
        logger.error(f"Error deleting all drafts for chat_id: {chat_id} from Directus: {e}", exc_info=True)
        return False

async def persist_delete_chat(directus_service, chat_id: str) -> bool:
    """
    Deletes a chat item from the 'chats' collection in Directus.
    Args:
        directus_service: An instance of the DirectusService.
        chat_id: The ID of the chat to delete.
    Returns:
        True if the deletion was successful, False otherwise.
    """
    logger.info(f"Attempting to delete chat {chat_id} from Directus.")
    try:
        # delete_item returns True on success, False on failure (e.g., item not found or API error)
        success = await directus_service.delete_item(collection='chats', item_id=chat_id)
        if success:
            logger.info(f"Successfully deleted chat {chat_id} from Directus.")
            return True
        else:
            logger.warning(f"Failed to delete chat {chat_id} from Directus. It might not exist or an API error occurred.")
            return False
    except Exception as e:
        logger.error(f"Error deleting chat {chat_id} from Directus: {e}", exc_info=True)
        return False

async def delete_user_draft_from_directus(directus_service, user_id: str, chat_id: str) -> bool:
    """
    Deletes a specific user's draft for a specific chat from the 'drafts' collection in Directus.
    It first fetches the draft's primary ID using user_id and chat_id, then deletes it.
    Args:
        directus_service: An instance of the DirectusService.
        user_id: The hashed user ID.
        chat_id: The ID of the chat for which the draft should be deleted.
    Returns:
        True if the deletion was successful, False otherwise.
    """
    logger.info(f"Attempting to delete draft for user {user_id}, chat {chat_id} from Directus.")
    try:
        # Step 1: Find the draft's own ID based on user_id and chat_id
        # Assuming 'hashed_user_id' is the field name in the 'drafts' table for the user identifier.
        draft_params = {
            'filter[hashed_user_id][_eq]': user_id,
            'filter[chat_id][_eq]': chat_id,
            'fields': 'id', # We only need the draft's own ID
            'limit': 1
        }
        draft_to_delete_list = await directus_service.get_items('drafts', params=draft_params)

        if not (draft_to_delete_list and isinstance(draft_to_delete_list, list) and len(draft_to_delete_list) > 0):
            logger.info(f"No draft found for user {user_id}, chat {chat_id} in Directus. Nothing to delete.")
            return True # Considered success as the state is "no draft exists"
        
        draft_item_id = draft_to_delete_list[0].get('id')
        if not draft_item_id:
            logger.error(f"Found draft entry for user {user_id}, chat {chat_id} but it has no 'id'. Cannot delete.")
            return False

        # Step 2: Delete the draft item by its primary ID
        success = await directus_service.delete_item(collection='drafts', item_id=draft_item_id)
        if success:
            logger.info(f"Successfully deleted draft (ID: {draft_item_id}) for user {user_id}, chat {chat_id} from Directus.")
            return True
        else:
            logger.warning(f"Failed to delete draft (ID: {draft_item_id}) for user {user_id}, chat {chat_id} from Directus.")
            return False
    except Exception as e:
        logger.error(f"Error deleting draft for user {user_id}, chat {chat_id} from Directus: {e}", exc_info=True)
        return False