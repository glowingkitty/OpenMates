import logging
import json
from typing import List, Dict, Any, Optional, Union
import hashlib

# Forward declaration for type hinting DirectusService
if False: # TYPE_CHECKING
    from .directus import DirectusService

logger = logging.getLogger(__name__)

# Define metadata fields to fetch (exclude large content fields)
CHAT_METADATA_FIELDS = "id,hashed_user_id,encrypted_title,created_at,updated_at,messages_v,title_v,last_edited_overall_timestamp,unread_count,encrypted_chat_summary,encrypted_chat_tags,encrypted_follow_up_request_suggestions,encrypted_active_focus_id,encrypted_chat_key"
CHAT_LIST_ITEM_FIELDS = "id,encrypted_title,unread_count,encrypted_chat_summary,encrypted_chat_tags,encrypted_chat_key"

# Fallback field sets for when encrypted fields are not accessible due to permissions
CHAT_METADATA_FIELDS_FALLBACK = "id,hashed_user_id,encrypted_title,created_at,updated_at,messages_v,title_v,last_edited_overall_timestamp,unread_count"
CHAT_LIST_ITEM_FIELDS_FALLBACK = "id,encrypted_title,unread_count"


# Fields required for get_core_chats_for_cache_warming from 'chats' collection
CORE_CHAT_FIELDS_FOR_WARMING = (
    "id,"
    "hashed_user_id,"
    "encrypted_title,"
    "encrypted_chat_key,"
    "created_at,"
    "updated_at,"
    "title_v,"
    "messages_v,"
    "unread_count,"
    "encrypted_chat_summary,"
    "encrypted_chat_tags,"
    "encrypted_follow_up_request_suggestions,"
    "last_edited_overall_timestamp"
)

# Fields required for get_full_chat_details_for_cache_warming from 'chats' collection
CHAT_FIELDS_FOR_FULL_WARMING = (
    "id,"
    "hashed_user_id,"
    "encrypted_title,"
    "created_at,"
    "updated_at,"
    "title_v,"
    "messages_v,"
    "unread_count,"
    "encrypted_chat_summary,"
    "encrypted_chat_tags,"
    "encrypted_follow_up_request_suggestions,"
    "last_edited_overall_timestamp"
)

# Fields for the new 'drafts' collection
DRAFT_FIELDS_FOR_WARMING = (
    "id," # draft_id
    "chat_id,"
    "hashed_user_id,"
    "encrypted_content,"
    "version,"
    "updated_at"
)

# Fields for messages based on backend/core/directus/schemas/messages.yml
MESSAGE_ALL_FIELDS = (
    "id,"
    "client_message_id,"
    "chat_id,"
    "encrypted_content,"
    "role," # Added role
    "encrypted_sender_name," # Added encrypted sender name
    "encrypted_category," # Added encrypted category
    # "sender_name," # Removed as per user feedback and to avoid permission issues
    "created_at"
)

# Minimal fields for basic message existence checks (avoids permission issues with encrypted fields)
MESSAGE_BASIC_FIELDS = (
    "id,"
    "chat_id,"
    "created_at"
)

class ChatMethods:
    def __init__(self, directus_service_instance: 'DirectusService'):
        self.directus_service = directus_service_instance
        # encryption_service and cache can be accessed via self.directus_service if needed

    async def get_chat_list_item_data_from_db(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the specific fields required for a chat list item directly from Directus.
        This is a fallback for when cache is inconsistent.
        """
        logger.info(f"DB Fallback: Fetching chat list item data for chat_id: {chat_id}")
        params = {
            'filter[id][_eq]': chat_id,
            'fields': CHAT_LIST_ITEM_FIELDS,
            'limit': 1
        }
        try:
            response = await self.directus_service.get_items('chats', params=params, no_cache=True)
            if response and isinstance(response, list) and len(response) > 0:
                logger.info(f"DB Fallback: Successfully fetched list item data for chat {chat_id}")
                return response[0]
            else:
                logger.warning(f"DB Fallback: Chat list item data not found for chat_id: {chat_id}")
                return None
        except Exception as e:
            logger.error(f"DB Fallback: Error fetching chat list item data for {chat_id}: {e}", exc_info=True)
            return None

    async def get_chat_metadata(self, chat_id: str) -> Optional[Dict[str, Any]]:
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
            response = await self.directus_service.get_items('chats', params=params, no_cache=True)
            if response and isinstance(response, list) and len(response) > 0:
                logger.info(f"Successfully fetched metadata for chat {chat_id}")
                return response[0]
            else:
                logger.warning(f"Chat metadata not found for chat_id: {chat_id}")
                return None
        except Exception as e:
            logger.error(f"Error fetching chat metadata for {chat_id}: {e}", exc_info=True)
            return None

    async def get_user_chats_metadata(self, user_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Fetches metadata for all chats belonging to a user from Directus, excluding content.
        """
        logger.info(f"Fetching chat metadata list for user_id: {user_id}, limit: {limit}, offset: {offset}")
        params = {
            'filter[user_id][_eq]': user_id, # Assuming 'user_id' field exists in 'chats'
            'fields': CHAT_METADATA_FIELDS,
            'limit': limit,
            'offset': offset,
            'sort': '-updated_at'
        }
        try:
            response = await self.directus_service.get_items('chats', params=params)
            if response and isinstance(response, list):
                logger.info(f"Successfully fetched {len(response)} chat metadata items for user {user_id}")
                return response
            else:
                logger.warning(f"No chat metadata found or unexpected response for user_id: {user_id}")
                return []
        except Exception as e:
            logger.error(f"Error fetching user chats metadata for {user_id}: {e}", exc_info=True)
            return []

    async def update_chat_metadata(self, chat_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Updates metadata for a specific chat in Directus.
        Requires 'basedOnVersion' in the data payload for optimistic concurrency control.
        Increments the '_version' field on successful update.
        """
        logger.info(f"Attempting to update chat metadata for chat_id: {chat_id} with data: {data}")
        based_on_version = data.pop('basedOnVersion', None)
        if based_on_version is None:
            logger.error(f"Update rejected for chat {chat_id}: 'basedOnVersion' is missing.")
            return None

        try:
            current_metadata = await self.get_chat_metadata(chat_id) # Use self.get_chat_metadata
            if not current_metadata:
                logger.error(f"Update rejected for chat {chat_id}: Chat not found.")
                return None
            current_version = current_metadata.get('_version')
            if current_version is None:
                 logger.error(f"Update rejected for chat {chat_id}: Server version (_version) is missing.")
                 return None
            if based_on_version != current_version:
                logger.error(f"Version conflict for chat {chat_id}. Client: {based_on_version}, Server: {current_version}")
                return None

            update_payload = data.copy()
            update_payload['_version'] = current_version + 1
            allowed_update_fields = {f for f in CHAT_METADATA_FIELDS.split(',') if f not in ['id', 'user_id', 'created_at']}
            update_payload = {k: v for k, v in update_payload.items() if k in allowed_update_fields or k == '_version'}

            updated_item_data = await self.directus_service.update_item('chats', chat_id, update_payload)
            if updated_item_data:
                logger.info(f"Successfully updated chat metadata for {chat_id}. New version: {updated_item_data.get('_version')}")
                return updated_item_data
            else:
                logger.error(f"Failed to update chat metadata for {chat_id} after version check.")
                return None
        except Exception as e:
            logger.error(f"Error updating chat metadata for {chat_id}: {e}", exc_info=True)
            return None

    async def create_chat_in_directus(self, chat_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a chat record in Directus.
        """
        try:
            chat_id_val = chat_metadata.get('id')
            logger.info(f"Creating chat in Directus: {chat_id_val}")
            success, result_data = await self.directus_service.create_item('chats', chat_metadata)
            if success and result_data:
                logger.info(f"Chat created in Directus: {result_data.get('id')}")
                if chat_id_val: # Check if chat_id_val is not None
                    await self.directus_service.cache.delete(f"chat:{chat_id_val}:metadata")
                return result_data
            else:
                logger.error(f"Failed to create chat in Directus for {chat_id_val}. Details: {result_data}")
                return None
        except Exception as e:
            logger.error(f"Error creating chat in Directus: {e}", exc_info=True)
            return None

    async def create_message_in_directus(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a message record in Directus.
        """
        try:
            chat_id_val = message_data.get('chat_id')
            logger.info(f"Attempting to create message in Directus for chat: {chat_id_val}")
            payload_to_directus = {
                "client_message_id": message_data.get("id"), # This should be message_id from the input
                "chat_id": chat_id_val,
                "hashed_user_id": message_data.get("hashed_user_id"),
                "role": message_data.get("role"), # Added role
                "encrypted_sender_name": message_data.get("encrypted_sender_name"), # Encrypted sender name
                "encrypted_category": message_data.get("encrypted_category"), # Encrypted category
                "encrypted_content": message_data.get("encrypted_content"),
                "created_at": message_data.get("created_at"),
            }
            payload_to_directus = {k: v for k, v in payload_to_directus.items() if v is not None}
            success, result_data = await self.directus_service.create_item('messages', payload_to_directus)
            
            if success and result_data:
                logger.info(f"Message created in Directus. Directus ID: {result_data.get('id')}, Client Message ID: {result_data.get('client_message_id')}")
                if chat_id_val: # Check if chat_id_val is not None
                    await self.directus_service.cache.delete(f"chat:{chat_id_val}:messages")
                return result_data
            else:
                logger.error(f"Failed to create message in Directus for chat {chat_id_val}. Details: {result_data}")
                return None
        except Exception as e:
            logger.error(f"Error creating message in Directus: {e}", exc_info=True)
            return None

    async def update_chat_fields_in_directus(self, chat_id: str, fields_to_update: Dict[str, Any]) -> bool:
        """
        Updates specific fields for a chat item in Directus.
        """
        logger.info(f"Updating chat fields for chat_id: {chat_id} with data: {list(fields_to_update.keys())}")
        try:
            updated_item_data = await self.directus_service.update_item(
                collection='chats',
                item_id=chat_id,
                data=fields_to_update
            )
            if updated_item_data:
                logger.info(f"Successfully updated fields for chat {chat_id} in Directus.")
                return True
            else:
                logger.warning(f"Update operation for chat {chat_id} returned no data, assuming update failed or no changes made.")
                return False
        except Exception as e:
            logger.error(f"Error updating chat fields for {chat_id} in Directus: {e}", exc_info=True)
            return False

    async def get_all_messages_for_chat(
        self,
        chat_id: str,
        decrypt_content: bool = False
    ) -> Optional[List[Union[str, Dict[str, Any]]]]:
        """
        Fetches all messages for a given chat_id from Directus.
        DEPRECATED in favor of get_messages_for_chats.
        """
        result_dict = await self.get_messages_for_chats([chat_id], decrypt_content)
        return result_dict.get(chat_id)

    async def check_messages_exist_for_chat(self, chat_id: str) -> bool:
        """
        Check if any messages exist for a chat without requesting encrypted fields.
        This avoids permission issues with encrypted_sender_name and encrypted_category.
        """
        try:
            params = {
                'filter[chat_id][_eq]': chat_id,
                'fields': MESSAGE_BASIC_FIELDS,
                'limit': 1  # We only need to know if at least one exists
            }
            messages_from_db = await self.directus_service.get_items('messages', params=params)
            return bool(messages_from_db and len(messages_from_db) > 0)
        except Exception as e:
            logger.warning(f"Error checking if messages exist for chat {chat_id}: {e}")
            return False

    async def get_messages_for_chats(
        self,
        chat_ids: List[str],
        decrypt_content: bool = False
    ) -> Dict[str, List[Union[str, Dict[str, Any]]]]:
        """
        Fetches all messages for a given list of chat_ids from Directus.
        Orders messages by creation date.
        Returns a dictionary mapping chat_id to its list of messages.
        """
        if not chat_ids:
            return {}
        logger.info(f"Fetching all messages for {len(chat_ids)} chats, decrypt: {decrypt_content}")
        params = {
            'filter[chat_id][_in]': ','.join(chat_ids),
            'fields': MESSAGE_ALL_FIELDS,
            'sort': 'created_at',
            'limit': -1
        }
        try:
            messages_from_db = await self.directus_service.get_items('messages', params=params)
            if not messages_from_db or not isinstance(messages_from_db, list):
                logger.info(f"No messages found for chat_ids: {chat_ids}")
                return {}

            logger.info(f"Successfully fetched {len(messages_from_db)} total messages for {len(chat_ids)} chats from DB.")
            
            messages_by_chat: Dict[str, List[Dict[str, Any]]] = {chat_id: [] for chat_id in chat_ids}
            for msg in messages_from_db:
                # Alias 'id' to 'message_id' to match client-side expectations
                msg['message_id'] = msg.get('id')
                messages_by_chat[msg['chat_id']].append(msg)

            processed_messages_by_chat: Dict[str, List[Union[str, Dict[str, Any]]]] = {}

            if decrypt_content:
                # Note: Server-side decryption removed - chat encryption now happens client-side
                # Messages are returned encrypted and must be decrypted on the client
                logger.warning("Server-side decryption requested but no longer supported. Messages returned encrypted.")
                for chat_id, messages in messages_by_chat.items():
                    processed_messages_by_chat[chat_id] = [json.dumps(msg) for msg in messages]
                return processed_messages_by_chat
            else:
                for chat_id, messages in messages_by_chat.items():
                    processed_messages_by_chat[chat_id] = [json.dumps(msg) for msg in messages]
                return processed_messages_by_chat
        except Exception as e:
            logger.error(f"Error fetching messages for chats {chat_ids}: {e}", exc_info=True)
            return {}

    async def get_all_user_drafts(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Fetches all of a user's drafts from the 'drafts' collection.
        Returns a dictionary mapping chat_id to the draft details.
        """
        logger.info(f"Fetching all drafts for user_id: {user_id}")
        params = {
            'filter[hashed_user_id][_eq]': hashlib.sha256(user_id.encode()).hexdigest(),
            'fields': DRAFT_FIELDS_FOR_WARMING,
            'limit': -1
        }
        try:
            response = await self.directus_service.get_items('drafts', params=params)
            if response and isinstance(response, list):
                logger.info(f"Successfully fetched {len(response)} drafts for user {user_id}")
                return {item['chat_id']: item for item in response}
            else:
                logger.info(f"No drafts found for user {user_id}")
                return {}
        except Exception as e:
            logger.error(f"Error fetching all drafts for user {user_id}: {e}", exc_info=True)
            return {}

    async def _get_user_draft_for_chat(self, user_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches a specific user's draft for a specific chat from the 'drafts' collection.
        """
        logger.info(f"Fetching draft for user_id: {user_id}, chat_id: {chat_id}")
        params = {
            'filter[chat_id][_eq]': chat_id,
            'filter[hashed_user_id][_eq]': hashlib.sha256(user_id.encode()).hexdigest(),
            'fields': DRAFT_FIELDS_FOR_WARMING,
            'limit': 1
        }
        try:
            response = await self.directus_service.get_items('drafts', params=params)
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
        self, user_id: str, chat_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches comprehensive details for a specific chat for cache warming.
        """
        logger.info(f"Fetching full chat and user draft details for cache warming, user_id: {user_id}, chat_id: {chat_id}")
        chat_params = {
            'filter[id][_eq]': chat_id,
            'fields': CHAT_FIELDS_FOR_FULL_WARMING,
            'limit': 1
        }
        try:
            chat_data_list = await self.directus_service.get_items('chats', params=chat_params)
            if not (chat_data_list and isinstance(chat_data_list, list) and len(chat_data_list) > 0):
                logger.warning(f"Chat not found for full cache warming: {chat_id}")
                return None
            
            chat_details = chat_data_list[0]
            messages_map = await self.get_messages_for_chats([chat_id])
            messages_list_json = messages_map.get(chat_id, [])
            chat_details["messages"] = messages_list_json if messages_list_json is not None else []
            
            user_draft_details = await self._get_user_draft_for_chat(user_id, chat_id)
            
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
        self, user_id: str, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Fetches core data for multiple chats and all user drafts in a batched manner.
        """
        logger.info(f"Fetching core chats and user drafts for cache warming for user_id: {user_id}, limit: {limit}")
        chat_params = {
            'filter[hashed_user_id][_eq]': hashlib.sha256(user_id.encode()).hexdigest(),
            'fields': CORE_CHAT_FIELDS_FOR_WARMING,
            'sort': '-last_edited_overall_timestamp',
            'limit': limit
        }
        results_list = []
        try:
            # 1. Fetch all core chat metadata in one request
            core_chats_list = await self.directus_service.get_items('chats', params=chat_params)
            if not core_chats_list or not isinstance(core_chats_list, list):
                logger.warning(f"No core chats found for user_id: {user_id} for cache warming.")
                return []
            logger.info(f"Successfully fetched {len(core_chats_list)} core chat items for user {user_id}.")

            # 2. Fetch all user drafts in one request
            all_user_drafts = await self.get_all_user_drafts(user_id)
            logger.info(f"Fetched {len(all_user_drafts)} drafts for user {user_id}.")

            # 3. Combine the data in memory
            for chat_data in core_chats_list:
                chat_id = chat_data["id"]
                user_draft_details = all_user_drafts.get(chat_id)
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

    async def get_user_draft_from_directus(self, hashed_user_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches a specific user's draft for a specific chat from 'drafts' collection.
        """
        logger.info(f"Fetching Directus draft for hashed_user_id: {hashed_user_id}, chat_id: {chat_id}")
        params = {
            'filter[chat_id][_eq]': chat_id,
            'filter[hashed_user_id][_eq]': hashed_user_id,
            'fields': DRAFT_FIELDS_FOR_WARMING,
            'limit': 1
        }
        try:
            response = await self.directus_service.get_items('drafts', params=params)
            if response and isinstance(response, list) and len(response) > 0:
                logger.info(f"Successfully fetched Directus draft for user {hashed_user_id}, chat {chat_id}")
                return response[0]
            else:
                logger.info(f"No Directus draft found for user {hashed_user_id}, chat {chat_id}")
                return None
        except Exception as e:
            logger.error(f"Error fetching Directus draft for user {hashed_user_id}, chat {chat_id}: {e}", exc_info=True)
            return None

    async def create_user_draft_in_directus(self, draft_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Creates a new user draft record in the 'drafts' collection.
        """
        chat_id_val = draft_data.get("chat_id")
        hashed_user_id_val = draft_data.get("hashed_user_id")
        logger.info(f"Creating Directus draft for user {hashed_user_id_val}, chat {chat_id_val}")
        try:
            success, result_data = await self.directus_service.create_item('drafts', draft_data)
            if success and result_data:
                draft_id = result_data.get('id')
                logger.info(f"Successfully created Directus draft ID {draft_id} for user {hashed_user_id_val}, chat {chat_id_val}")
                return result_data
            else:
                logger.error(f"Failed to create Directus draft for user {hashed_user_id_val}, chat {chat_id_val}. Details: {result_data}")
                return None
        except Exception as e:
            logger.error(f"Exception during Directus draft creation for user {hashed_user_id_val}, chat {chat_id_val}: {e}", exc_info=True)
            return None

    async def update_user_draft_in_directus(self, draft_id: str, fields_to_update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Updates an existing user draft record in the 'drafts' collection.
        """
        logger.info(f"Updating Directus draft ID {draft_id} with fields: {list(fields_to_update.keys())}")
        try:
            updated_draft = await self.directus_service.update_item(
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

    async def delete_all_drafts_for_chat(self, chat_id: str) -> bool:
        """
        Deletes ALL draft items for a specific chat_id from the 'drafts' collection.
        """
        logger.info(f"Attempting to delete all drafts for chat_id: {chat_id} from Directus.")
        try:
            draft_params = {
                'filter[chat_id][_eq]': chat_id,
                'fields': 'id',
                'limit': -1
            }
            drafts_to_delete_list = await self.directus_service.get_items('drafts', params=draft_params)
            if not drafts_to_delete_list:
                logger.info(f"No drafts found for chat_id: {chat_id}. Nothing to delete.")
                return True

            logger.info(f"Found {len(drafts_to_delete_list)} drafts to delete for chat_id: {chat_id}.")
            all_deleted_successfully = True
            for draft_item in drafts_to_delete_list:
                draft_item_id = draft_item.get('id')
                if not draft_item_id:
                    logger.error(f"Found draft entry for chat_id: {chat_id} with no 'id'. Cannot delete. Entry: {draft_item}")
                    all_deleted_successfully = False
                    continue
                success = await self.directus_service.delete_item(collection='drafts', item_id=draft_item_id)
                if success:
                    logger.info(f"Successfully deleted draft (ID: {draft_item_id}) for chat_id: {chat_id}.")
                else:
                    logger.warning(f"Failed to delete draft (ID: {draft_item_id}) for chat_id: {chat_id}.")
                    all_deleted_successfully = False
            
            if all_deleted_successfully:
                logger.info(f"Successfully deleted all found drafts for chat_id: {chat_id}.")
            else:
                logger.warning(f"One or more drafts could not be deleted for chat_id: {chat_id}.")
            return all_deleted_successfully
        except Exception as e:
            logger.error(f"Error deleting all drafts for chat_id: {chat_id}: {e}", exc_info=True)
            return False

    async def delete_all_messages_for_chat(self, chat_id: str) -> bool:
        """
        Deletes ALL message items for a specific chat_id from the 'messages' collection.
        """
        logger.info(f"Attempting to delete all messages for chat_id: {chat_id} from Directus.")
        try:
            # Query for all messages belonging to this chat
            message_params = {
                'filter[chat_id][_eq]': chat_id,
                'fields': 'id',
                'limit': -1  # Get all messages for this chat
            }
            messages_to_delete_list = await self.directus_service.get_items('messages', params=message_params)
            if not messages_to_delete_list:
                logger.info(f"No messages found for chat_id: {chat_id}. Nothing to delete.")
                return True

            logger.info(f"Found {len(messages_to_delete_list)} messages to delete for chat_id: {chat_id}.")
            all_deleted_successfully = True
            for message_item in messages_to_delete_list:
                message_item_id = message_item.get('id')
                if not message_item_id:
                    logger.error(f"Found message entry for chat_id: {chat_id} with no 'id'. Cannot delete. Entry: {message_item}")
                    all_deleted_successfully = False
                    continue
                success = await self.directus_service.delete_item(collection='messages', item_id=message_item_id)
                if success:
                    logger.debug(f"Successfully deleted message (ID: {message_item_id}) for chat_id: {chat_id}.")
                else:
                    logger.warning(f"Failed to delete message (ID: {message_item_id}) for chat_id: {chat_id}.")
                    all_deleted_successfully = False
            
            if all_deleted_successfully:
                logger.info(f"Successfully deleted all {len(messages_to_delete_list)} messages for chat_id: {chat_id}.")
            else:
                logger.warning(f"One or more messages could not be deleted for chat_id: {chat_id}.")
            return all_deleted_successfully
        except Exception as e:
            logger.error(f"Error deleting all messages for chat_id: {chat_id}: {e}", exc_info=True)
            return False

    async def persist_delete_chat(self, chat_id: str) -> bool:
        """
        Deletes a chat item from the 'chats' collection.
        NOTE: This method ONLY deletes the chat record itself.
        Messages and drafts should be deleted separately before calling this method.
        """
        logger.info(f"Attempting to delete chat {chat_id} from Directus.")
        try:
            success = await self.directus_service.delete_item(collection='chats', item_id=chat_id)
            if success:
                logger.info(f"Successfully deleted chat {chat_id} from Directus.")
                return True
            else:
                logger.warning(f"Failed to delete chat {chat_id}. It might not exist or an API error occurred.")
                return False
        except Exception as e:
            logger.error(f"Error deleting chat {chat_id} from Directus: {e}", exc_info=True)
            return False

    async def update_chat_read_status(self, chat_id: str, unread_count: int) -> bool:
        """
        Updates the read status (unread count) for a chat in Directus.
        This is used for immediate updates when user marks chat as read.
        """
        logger.info(f"Updating read status for chat {chat_id}: unread_count = {unread_count}")
        try:
            import time
            current_timestamp = int(time.time())
            update_data = {
                "unread_count": unread_count,
                "updated_at": current_timestamp
            }
            
            success = await self.directus_service.update_item('chats', chat_id, update_data)
            if success:
                logger.info(f"Successfully updated read status for chat {chat_id}")
                return True
            else:
                logger.error(f"Failed to update read status for chat {chat_id}")
                return False
        except Exception as e:
            logger.error(f"Error updating read status for chat {chat_id}: {e}", exc_info=True)
            return False
