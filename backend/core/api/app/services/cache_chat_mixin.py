import logging
from typing import Any, Optional, Union, List, Tuple, Literal, Dict
from datetime import datetime, timezone
from backend.core.api.app.schemas.chat import CachedChatVersions, CachedChatListItemData, MessageInCache

logger = logging.getLogger(__name__)

class ChatCacheMixin:
    """Mixin for new chat sync architecture caching methods"""

    def get_chat_key(self, chat_id: str) -> str:
        """
        Returns a generic cache key for a chat, primarily identified by its chat_id.
        This key can be used for tasks or general references to a chat entity.
        """
        return f"chat:{chat_id}"
    
    # 1. user:{user_id}:chat_ids_versions (Sorted Set: score=last_edited_overall_timestamp, value=chat_id)
    def _get_user_chat_ids_versions_key(self, user_id: str) -> str:
        return f"user:{user_id}:chat_ids_versions"

    async def add_chat_to_ids_versions(self, user_id: str, chat_id: str, last_edited_overall_timestamp: int) -> bool:
        """Adds a chat_id to the sorted set, scored by its last_edited_overall_timestamp."""
        client = await self.client
        if not client: return False
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            logger.debug(f"CACHE_OP: ZADD for key '{key}', chat_id '{chat_id}', score '{float(last_edited_overall_timestamp)}'")
            await client.zadd(key, {chat_id: float(last_edited_overall_timestamp)})
            ttl_to_set = self.CHAT_IDS_VERSIONS_TTL
            logger.debug(f"CACHE_OP: EXPIRE for key '{key}' with TTL {ttl_to_set}s")
            await client.expire(key, ttl_to_set)
            logger.debug(f"CACHE_OP: Successfully added chat '{chat_id}' to sorted set '{key}' with score '{float(last_edited_overall_timestamp)}' and TTL {ttl_to_set}s.")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error adding chat {chat_id} to {key}: {e}", exc_info=True)
            return False

    async def remove_chat_from_ids_versions(self, user_id: str, chat_id: str) -> bool:
        """Removes a chat_id from the sorted set."""
        client = await self.client
        if not client: return False
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            removed_count = await client.zrem(key, chat_id)
            return removed_count > 0
        except Exception as e:
            logger.error(f"Error removing chat {chat_id} from {key}: {e}")
            return False

    async def get_chat_ids_versions(
        self, user_id: str, start: int = 0, end: int = -1, with_scores: bool = False, reverse: bool = True
    ) -> Union[List[str], List[Tuple[str, float]]]:
        """Gets chat_ids from the sorted set, optionally with scores. Sorted by score descending (most recent first) by default."""
        client = await self.client
        if not client: return []
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            if reverse:
                items = await client.zrange(key, start, end, desc=True, withscores=with_scores)
            else:
                items = await client.zrange(key, start, end, desc=False, withscores=with_scores)
            
            if with_scores:
                return [(item.decode('utf-8'), score) for item, score in items]
            else:
                return [item.decode('utf-8') for item in items]
        except Exception as e:
            logger.error(f"Error getting chat_ids_versions from {key}: {e}")
            return []

    async def update_chat_score_in_ids_versions(self, user_id: str, chat_id: str, new_last_edited_overall_timestamp: int) -> bool:
        """Updates the score (timestamp) for a chat_id in the sorted set. Effectively an alias for add."""
        return await self.add_chat_to_ids_versions(user_id, chat_id, new_last_edited_overall_timestamp)

    async def get_chat_last_edited_overall_timestamp(self, user_id: str, chat_id: str) -> Optional[int]:
        """Gets the last_edited_overall_timestamp (score) for a specific chat_id from the user's sorted set."""
        client = await self.client
        if not client:
            logger.error(f"CACHE_OP_ERROR: Redis client not available for get_chat_last_edited_overall_timestamp for user {user_id}, chat {chat_id}.")
            return None
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            score = await client.zscore(key, chat_id)
            if score is not None:
                logger.debug(f"CACHE_OP_HIT: Successfully retrieved score for chat '{chat_id}' in sorted set '{key}': {score}")
                return int(score)
            else:
                logger.warning(f"CACHE_OP_MISS: Score not found for chat '{chat_id}' in sorted set '{key}'.")
                return None
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error getting score for chat {chat_id} from {key}: {e}", exc_info=True)
            return None

    # 2. user:{user_id}:chat:{chat_id}:versions (Hash: messages_v, draft_v, title_v)
    def _get_chat_versions_key(self, user_id: str, chat_id: str) -> str:
        return f"user:{user_id}:chat:{chat_id}:versions"

    async def set_chat_versions(self, user_id: str, chat_id: str, versions: CachedChatVersions, ttl: Optional[int] = None) -> bool:
        """Sets the component versions for a chat."""
        client = await self.client
        if not client: return False
        key = self._get_chat_versions_key(user_id, chat_id)
        data_to_set = versions.model_dump()
        final_ttl = ttl if ttl is not None else self.CHAT_VERSIONS_TTL
        try:
            logger.debug(f"CACHE_OP: HMSET for key '{key}' with data: {data_to_set}")
            await client.hmset(key, data_to_set)
            logger.debug(f"CACHE_OP: EXPIRE for key '{key}' with TTL {final_ttl}s")
            await client.expire(key, final_ttl)
            logger.debug(f"CACHE_OP: Successfully set versions for key '{key}' with TTL {final_ttl}s. Data: {data_to_set}")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error setting versions for {key}. Data: {data_to_set}, TTL: {final_ttl}. Error: {e}", exc_info=True)
            return False

    async def get_chat_versions(self, user_id: str, chat_id: str) -> Optional[CachedChatVersions]:
        """Gets the component versions for a chat."""
        client = await self.client
        if not client: return None
        key = self._get_chat_versions_key(user_id, chat_id)
        logger.debug(f"CACHE_OP: HGETALL for key '{key}'")
        try:
            versions_data_bytes = await client.hgetall(key)
            if not versions_data_bytes:
                logger.warning(f"CACHE_OP_MISS: No versions data found for key '{key}'")
                return None
            versions_data = {k.decode('utf-8'): int(v.decode('utf-8')) for k, v in versions_data_bytes.items()}
            logger.debug(f"CACHE_OP_HIT: Successfully retrieved versions for key '{key}'. Data: {versions_data}")
            # Attempt to refresh TTL on successful get, if desired (can be added here or as a separate method)
            # await client.expire(key, self.CHAT_VERSIONS_TTL)
            return CachedChatVersions(**versions_data)
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error getting versions from {key}: {e}", exc_info=True)
            return None

    async def increment_chat_component_version(self, user_id: str, chat_id: str, component: str, increment_by: int = 1) -> Optional[int]:
        """
        Increments a specific component version for a chat in the versions hash.
        Returns the new version or None on error.
        The 'component' can be "messages_v", "title_v", or dynamic like f"user_draft_v:{specific_user_id}".
        """
        client = await self.client
        if not client: return None
        key = self._get_chat_versions_key(user_id, chat_id)
        final_ttl = self.CHAT_VERSIONS_TTL
        try:
            logger.debug(f"CACHE_OP: HINCRBY for key '{key}', component '{component}', increment_by '{increment_by}'")
            new_version = await client.hincrby(key, component, increment_by)
            
            # Ensure base fields (messages_v, title_v) exist in the hash, initializing to 0 if not.
            # This is crucial for CachedChatVersions model validation, especially if HINCRBY created the hash.
            # HSETNX will not overwrite existing values.
            await client.hsetnx(key, "messages_v", 0)
            await client.hsetnx(key, "title_v", 0)
            
            logger.debug(f"CACHE_OP: HINCRBY for key '{key}', component '{component}' returned new version '{new_version}'. Ensured base fields. EXPIRE with TTL {final_ttl}s.")
            await client.expire(key, final_ttl) # Ensure TTL is refreshed
            logger.debug(f"CACHE_OP: Successfully incremented component '{component}' for key '{key}' to '{new_version}'. Base fields ensured. TTL set to {final_ttl}s.")
            return new_version
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error incrementing component '{component}' for key '{key}'. Error: {e}", exc_info=True)
            return None

    async def set_chat_version_component(self, user_id: str, chat_id: str, component: str, value: int) -> bool:
        """
        Sets a specific component's version for a chat in the versions hash to an absolute value.
        Returns True on success, False on error.
        The 'component' can be "messages_v", "title_v", or dynamic like f"user_draft_v:{specific_user_id}".
        """
        client = await self.client
        if not client: return False
        key = self._get_chat_versions_key(user_id, chat_id)
        final_ttl = self.CHAT_VERSIONS_TTL
        try:
            logger.debug(f"CACHE_OP: HSET for key '{key}', component '{component}', value '{value}'")
            await client.hset(key, component, value)
            # Ensure base messages_v and title_v fields exist if the key itself is new or was missing fields.
            # This is important if hset is creating the hash for the first time with this component.
            await client.hsetnx(key, "messages_v", 0)
            await client.hsetnx(key, "title_v", 0)
            await client.expire(key, final_ttl) # Ensure TTL is set/refreshed
            logger.debug(f"CACHE_OP: Successfully set component '{component}' for key '{key}' to '{value}'. TTL set to {final_ttl}s.")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error setting component '{component}' for key '{key}' to '{value}'. Error: {e}", exc_info=True)
            return False

    # --- User-Specific Draft Cache Methods ---

    def _get_user_chat_draft_key(self, user_id: str, chat_id: str) -> str:
        """Returns the cache key for a user's specific draft in a chat."""
        return f"user:{user_id}:chat:{chat_id}:draft"

    async def increment_user_draft_version(self, user_id: str, chat_id: str, increment_by: int = 1) -> Optional[int]:
        """
        Increments the draft version for a specific user in a specific chat.
        This updates version in two places:
        1. `draft_v` in `user:{user_id}:chat:{chat_id}:draft` (the dedicated draft key)
        2. `user_draft_v:{user_id}` in `user:{user_id}:chat:{chat_id}:versions` (the general versions key for the chat)
        Attempts to be resilient to cache expiration of the dedicated draft key by checking the general versions key.
        Returns the new draft version or None on error.
        """
        client = await self.client
        if not client: return None

        draft_key = self._get_user_chat_draft_key(user_id, chat_id)
        versions_key = self._get_chat_versions_key(user_id, chat_id)
        user_specific_draft_version_field = f"user_draft_v:{user_id}"
        
        new_draft_version_for_dedicated_key: Optional[int] = None
        try:
            # Check if the dedicated draft key's draft_v field exists
            dedicated_draft_v_exists = await client.hexists(draft_key, "draft_v")

            current_version_base = 0 # Default base if no version info found
            if not dedicated_draft_v_exists:
                # Dedicated draft_v doesn't exist. Try to get a base from the general versions key.
                logger.debug(f"Dedicated draft_v missing for {draft_key}. Checking general versions key {versions_key} field {user_specific_draft_version_field}.")
                general_versions_data_bytes = await client.hget(versions_key, user_specific_draft_version_field)
                if general_versions_data_bytes:
                    try:
                        current_version_base = int(general_versions_data_bytes.decode('utf-8'))
                        logger.debug(f"Found base version {current_version_base} from general versions key for {draft_key}.")
                        # Explicitly set this base in the dedicated draft key.
                        # Hincrby will then increment this value.
                        await client.hset(draft_key, "draft_v", current_version_base)
                    except ValueError:
                        logger.warning(f"Could not parse version from general key for {draft_key}. Defaulting base to 0 for hincrby.")
                        # current_version_base remains 0, hincrby will effectively start from increment_by
                else:
                    logger.debug(f"No base version found in general versions key for {draft_key}. Hincrby will start from 0 + increment_by.")
                    # current_version_base remains 0, hincrby will effectively start from increment_by
            
            # Increment in the dedicated draft key.
            # If "draft_v" was just set from general key, hincrby increments it.
            # If "draft_v" existed, hincrby increments it.
            # If "draft_v" did not exist and no base found, hincrby creates it starting from 0 + increment_by.
            new_draft_version_for_dedicated_key = await client.hincrby(draft_key, "draft_v", increment_by)
            await client.expire(draft_key, self.USER_DRAFT_TTL)

            # Now, ensure the general versions key is also updated consistently to match the new authoritative version.
            await client.hset(versions_key, user_specific_draft_version_field, new_draft_version_for_dedicated_key)
            
            # Ensure base messages_v and title_v fields exist in the general versions key if the key itself is new or was missing fields.
            await client.hsetnx(versions_key, "messages_v", 0)
            await client.hsetnx(versions_key, "title_v", 0)
            await client.expire(versions_key, self.CHAT_VERSIONS_TTL) # Refresh TTL for the general versions key
            
            logger.debug(f"Incremented draft version for user {user_id}, chat {chat_id} to {new_draft_version_for_dedicated_key}. Synced with general versions key.")
            return new_draft_version_for_dedicated_key
        except Exception as e:
            logger.error(f"Error incrementing draft version for user {user_id}, chat {chat_id}: {e}", exc_info=True)
            return None

    async def update_user_draft_in_cache(self, user_id: str, chat_id: str, encrypted_draft_json: Optional[str], draft_version: int) -> bool:
        """
        Updates the user's draft content and version in their dedicated draft cache key.
        Sets TTL for the draft key.
        """
        client = await self.client
        if not client: return False
        key = self._get_user_chat_draft_key(user_id, chat_id)
        try:
            payload = {"draft_v": draft_version}
            if encrypted_draft_json is None:
                payload["draft_json"] = "null" # Store null as a string "null"
            else:
                payload["draft_json"] = encrypted_draft_json
            
            await client.hmset(key, payload)
            await client.expire(key, self.USER_DRAFT_TTL) # Assuming USER_DRAFT_TTL is defined
            logger.debug(f"Updated draft for user {user_id}, chat {chat_id} with version {draft_version}")
            return True
        except Exception as e:
            logger.error(f"Error updating draft for user {user_id}, chat {chat_id}: {e}")
            return False

    async def get_user_draft_from_cache(self, user_id: str, chat_id: str, refresh_ttl: bool = False) -> Optional[Tuple[Optional[str], int]]:
        """
        Gets the user's draft content (encrypted JSON string) and version from cache.
        Returns a tuple (encrypted_draft_json, draft_version) or None if not found or error.
        "null" string for draft_json is converted back to None.
        """
        client = await self.client
        if not client: return None
        key = self._get_user_chat_draft_key(user_id, chat_id)
        try:
            draft_data_bytes = await client.hgetall(key)
            if not draft_data_bytes:
                return None
            
            draft_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in draft_data_bytes.items()}
            
            encrypted_json = draft_data.get("draft_json")
            if encrypted_json == "null":
                encrypted_json = None
                
            version_str = draft_data.get("draft_v")
            if version_str is None: # Should not happen if set correctly
                logger.warning(f"Draft version missing for user {user_id}, chat {chat_id} in {key}")
                return None
            
            version = int(version_str)

            if refresh_ttl:
                await client.expire(key, self.USER_DRAFT_TTL)
            return encrypted_json, version
        except Exception as e:
            logger.error(f"Error getting draft for user {user_id}, chat {chat_id} from {key}: {e}")
            return None

    async def delete_user_draft_from_cache(self, user_id: str, chat_id: str) -> bool:
        """
        Deletes the user's specific draft cache key.
        Returns True if the key was deleted, False otherwise or on error.
        """
        client = await self.client
        if not client: return False
        key = self._get_user_chat_draft_key(user_id, chat_id)
        try:
            deleted_count = await client.delete(key)
            if deleted_count > 0:
                logger.debug(f"Successfully deleted draft cache key {key} for user {user_id}, chat {chat_id}.")
                return True
            else:
                logger.debug(f"Draft cache key {key} for user {user_id}, chat {chat_id} not found or already deleted.")
                return False # Or True, depending on if "not found" is a success for deletion
        except Exception as e:
            logger.error(f"Error deleting draft cache key {key} for user {user_id}, chat {chat_id}: {e}", exc_info=True)
            return False

    async def delete_user_draft_version_from_chat_versions(self, user_id: str, chat_id: str) -> bool:
        """
        Deletes the user-specific draft version field (e.g., user_draft_v:USER_ID)
        from the chat's general versions hash (user:{user_id}:chat:{chat_id}:versions).
        This is typically called when a draft is fully deleted to ensure its version
        counter doesn't persist and new drafts start from version 1.
        Returns True if the field was deleted or did not exist, False on Redis error.
        """
        client = await self.client
        if not client:
            logger.error("CACHE_OP_ERROR: Redis client not available for delete_user_draft_version_from_chat_versions.")
            return False

        versions_key = self._get_chat_versions_key(user_id, chat_id)
        user_specific_draft_version_field = f"user_draft_v:{user_id}"

        try:
            logger.debug(f"CACHE_OP: HDEL for key '{versions_key}', field '{user_specific_draft_version_field}'")
            # HDEL returns the number of fields that were removed.
            # If the field did not exist, it returns 0. This is a "successful" outcome for our purpose.
            # If the key does not exist, it is treated as an empty hash and HDEL returns 0.
            deleted_count = await client.hdel(versions_key, user_specific_draft_version_field)
            logger.info(f"CACHE_OP: Processed HDEL for field '{user_specific_draft_version_field}' in key '{versions_key}'. Fields removed: {deleted_count}.")
            return True
        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: Error deleting field '{user_specific_draft_version_field}' from key '{versions_key}'. Error: {e}", exc_info=True)
            return False
            
    # 3. user:{user_id}:chat:{chat_id}:list_item_data (Hash: title (enc), unread_count)
    # Note: draft_json removed from this key as per new architecture
    def _get_chat_list_item_data_key(self, user_id: str, chat_id: str) -> str:
        return f"user:{user_id}:chat:{chat_id}:list_item_data"

    async def set_chat_list_item_data(self, user_id: str, chat_id: str, data: CachedChatListItemData, ttl: Optional[int] = None) -> bool:
        """Sets the list item data for a chat."""
        client = await self.client
        if not client: return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            # Ensure draft_json is not part of the model_dump if CachedChatListItemData still has it
            # Or better, update CachedChatListItemData schema to remove draft_json
            data_to_set = data.model_dump(exclude_none=True)
            if 'draft_json' in data_to_set: # Defensively remove if schema not yet updated
                del data_to_set['draft_json']
            
            await client.hmset(key, data_to_set)
            await client.expire(key, ttl if ttl is not None else self.CHAT_LIST_ITEM_DATA_TTL)
            return True
        except Exception as e:
            logger.error(f"Error setting list_item_data for {key}: {e}")
            return False

    async def get_chat_list_item_data(self, user_id: str, chat_id: str, refresh_ttl: bool = False) -> Optional[CachedChatListItemData]:
        """Gets the list item data for a chat. Optionally refreshes TTL on access."""
        client = await self.client
        if not client: return None
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            data_bytes = await client.hgetall(key)
            if not data_bytes:
                return None
            
            data = {k.decode('utf-8'): v.decode('utf-8') for k, v in data_bytes.items()}
            if 'unread_count' in data:
                data['unread_count'] = int(data['unread_count'])
            # draft_json is no longer part of this key
            # Ensure the Pydantic model CachedChatListItemData is updated to not expect draft_json

            # Create a dictionary only with fields expected by the updated CachedChatListItemData
            filtered_data = {k: v for k, v in data.items() if k in CachedChatListItemData.model_fields}

            parsed_data = CachedChatListItemData(**filtered_data)
            if refresh_ttl:
                await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            return parsed_data
        except Exception as e:
            logger.error(f"Error getting list_item_data from {key}: {e}")
            return None

    async def update_chat_list_item_field(self, user_id: str, chat_id: str, field: Literal["title", "unread_count", "last_mate_category"], value: Any) -> bool:
        """
        Updates a specific field in the chat's list_item_data. Refreshes TTL.
        'draft_json' is no longer managed here.
        """
        client = await self.client
        if not client: return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        
        if field == "draft_json": # Should not be called for draft_json anymore
            logger.warning(f"Attempted to update 'draft_json' via update_chat_list_item_field for {key}. This field is now managed separately.")
            return False
            
        try:
            await client.hset(key, field, value)
            await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            return True
        except Exception as e:
            logger.error(f"Error updating field {field} for {key}: {e}")
            return False

    async def increment_chat_list_item_unread_count(self, user_id: str, chat_id: str, increment_by: int = 1) -> Optional[int]:
        """Increments the unread_count for a chat. Refreshes TTL. Returns new count or None."""
        client = await self.client
        if not client: return None
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            new_count = await client.hincrby(key, "unread_count", increment_by)
            await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            return new_count
        except Exception as e:
            logger.error(f"Error incrementing unread_count for {key}: {e}")
            return None
            
    async def refresh_chat_list_item_data_ttl(self, user_id: str, chat_id: str) -> bool:
        """Refreshes the TTL for the chat's list_item_data key."""
        client = await self.client
        if not client: return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            return await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
        except Exception as e:
            logger.error(f"Error refreshing TTL for {key}: {e}")
            return False

    # 4. user:{user_id}:chat:{chat_id}:messages (List of encrypted JSON Message strings)
    def _get_chat_messages_key(self, user_id: str, chat_id: str) -> str:
        return f"user:{user_id}:chat:{chat_id}:messages"

    async def add_message_to_chat_history(self, user_id: str, chat_id: str, encrypted_message_json: str, max_history_length: Optional[int] = None) -> bool:
        """Adds an encrypted message (JSON string) to the chat's history (prepends). Optionally trims list."""
        client = await self.client
        if not client: return False
        key = self._get_chat_messages_key(user_id, chat_id)
        try:
            await client.lpush(key, encrypted_message_json)
            if max_history_length is not None and max_history_length > 0:
                await client.ltrim(key, 0, max_history_length - 1)
            await client.expire(key, self.CHAT_MESSAGES_TTL)
            return True
        except Exception as e:
            logger.error(f"Error adding message to {key}: {e}")
            return False

    async def get_chat_messages_history(self, user_id: str, chat_id: str, start: int = 0, end: int = -1) -> List[str]:
        """Gets encrypted messages (JSON strings) from chat history. Returns newest first if LPUSHed."""
        client = await self.client
        if not client: return []
        key = self._get_chat_messages_key(user_id, chat_id)
        try:
            messages_bytes = await client.lrange(key, start, end)
            return [msg.decode('utf-8') for msg in messages_bytes]
        except Exception as e:
            logger.error(f"Error getting messages from {key}: {e}")
            return []

    async def set_chat_messages_history(self, user_id: str, chat_id: str, encrypted_messages_json_list: List[str], ttl: Optional[int] = None) -> bool:
        """Sets the entire message history for a chat. Overwrites existing history."""
        client = await self.client
        if not client: return False
        key = self._get_chat_messages_key(user_id, chat_id)
        try:
            await client.delete(key)
            if encrypted_messages_json_list:
                await client.rpush(key, *encrypted_messages_json_list)
            await client.expire(key, ttl if ttl is not None else self.CHAT_MESSAGES_TTL)
            return True
        except Exception as e:
            logger.error(f"Error setting messages for {key}: {e}")
            return False
            
    async def delete_chat_messages_history(self, user_id: str, chat_id: str) -> bool:
        """Deletes the message history for a specific chat."""
        client = await self.client
        if not client: return False
        key = self._get_chat_messages_key(user_id, chat_id)
        try:
            deleted_count = await client.delete(key)
            return deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting messages for {key}: {e}")
            return False

    async def save_chat_message_and_update_versions(
        self, user_id: str, chat_id: str, message_data: MessageInCache, max_history_length: Optional[int] = None, last_mate_category: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Serializes a MessageInCache object, adds it to the chat's history cache,
        increments the messages_v, updates the last_edited_overall_timestamp,
        and optionally updates the last_mate_category.
        Returns a dict with new versions on success, None on failure.
        """
        client = await self.client
        if not client:
            logger.error(f"CACHE_OP_ERROR: Redis client not available. Failed to save message for user {user_id}, chat {chat_id}.")
            return None

        try:
            # 1. Save the message to history
            message_json_str = message_data.model_dump_json()
            logger.debug(f"CACHE_OP: Serialized message for user {user_id}, chat {chat_id}, msg_id {message_data.id} to JSON: {message_json_str[:200]}...")

            save_success = await self.add_message_to_chat_history(
                user_id,
                chat_id,
                message_json_str,
                max_history_length=max_history_length
            )
            if not save_success:
                logger.error(f"CACHE_OP_ERROR: Failed to save message to history for user {user_id}, chat {chat_id}, msg_id {message_data.id} using add_message_to_chat_history.")
                return None
            logger.info(f"CACHE_OP_SUCCESS: Successfully saved message to history for user {user_id}, chat {chat_id}, msg_id {message_data.id}.")

            # 2. Increment messages_v
            new_messages_v = await self.increment_chat_component_version(user_id, chat_id, "messages_v")
            if new_messages_v is None:
                logger.error(f"CACHE_OP_ERROR: Failed to increment messages_v for user {user_id}, chat {chat_id} after saving message {message_data.id}.")
                # Potentially consider rollback or cleanup if critical, but for now, log and fail.
                return None
            logger.info(f"CACHE_OP_SUCCESS: Incremented messages_v to {new_messages_v} for user {user_id}, chat {chat_id}.")

            # 3. Update last_edited_overall_timestamp
            try:
                # message_data.created_at is already an integer Unix timestamp as per MessageInCache schema
                if not isinstance(message_data.created_at, int):
                    logger.warning(
                        f"CACHE_OP_WARNING: message_data.created_at was expected to be int for chat {chat_id}, msg {message_data.id}, "
                        f"but got {type(message_data.created_at)} with value '{message_data.created_at}'. "
                        f"Falling back to current UTC timestamp."
                    )
                    new_last_edited_overall_timestamp = int(datetime.now(timezone.utc).timestamp())
                else:
                    new_last_edited_overall_timestamp = message_data.created_at
            except Exception as e_ts: # Catch any unexpected error during access or type check
                logger.error(
                    f"CACHE_OP_ERROR: Error processing message_data.created_at ('{message_data.created_at}') "
                    f"for chat {chat_id}, msg {message_data.id}. Error: {e_ts}", exc_info=True
                )
                logger.warning(
                    f"CACHE_OP_WARNING: Falling back to current UTC timestamp for chat {chat_id}, msg {message_data.id} due to an unexpected error."
                )
                new_last_edited_overall_timestamp = int(datetime.now(timezone.utc).timestamp())

            score_update_success = await self.update_chat_score_in_ids_versions(
                user_id, chat_id, new_last_edited_overall_timestamp
            )
            if not score_update_success:
                logger.error(f"CACHE_OP_ERROR: Failed to update last_edited_overall_timestamp for user {user_id}, chat {chat_id} to {new_last_edited_overall_timestamp}.")
                # Potentially consider rollback or cleanup.
                return None
            logger.info(f"CACHE_OP_SUCCESS: Updated last_edited_overall_timestamp to {new_last_edited_overall_timestamp} for user {user_id}, chat {chat_id}.")

            # 4. Optionally update last_mate_category
            if last_mate_category is not None:
                category_update_success = await self.update_chat_list_item_field(
                    user_id, chat_id, "last_mate_category", last_mate_category
                )
                if not category_update_success:
                    # Log a warning but don't fail the whole operation, as this is less critical
                    logger.warning(f"CACHE_OP_WARNING: Failed to update last_mate_category to '{last_mate_category}' for user {user_id}, chat {chat_id}.")
                else:
                    logger.info(f"CACHE_OP_SUCCESS: Updated last_mate_category to '{last_mate_category}' for user {user_id}, chat {chat_id}.")


            return {
                "messages_v": new_messages_v,
                "last_edited_overall_timestamp": new_last_edited_overall_timestamp
            }

        except Exception as e:
            logger.error(f"CACHE_OP_ERROR: General error in save_chat_message_and_update_versions for user {user_id}, chat {chat_id}, msg_id {message_data.id}: {e}", exc_info=True)
            return None
