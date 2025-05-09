import logging
from typing import Any, Optional, Union, List, Tuple, Literal
from app.schemas.chat import CachedChatVersions, CachedChatListItemData

logger = logging.getLogger(__name__)

class ChatCacheMixin:
    """Mixin for new chat sync architecture caching methods"""

    # 1. user:{user_id}:chat_ids_versions (Sorted Set: score=last_edited_overall_timestamp, value=chat_id)
    def _get_user_chat_ids_versions_key(self, user_id: str) -> str:
        return f"user:{user_id}:chat_ids_versions"

    async def add_chat_to_ids_versions(self, user_id: str, chat_id: str, last_edited_overall_timestamp: int) -> bool:
        """Adds a chat_id to the sorted set, scored by its last_edited_overall_timestamp."""
        client = await self.client
        if not client: return False
        key = self._get_user_chat_ids_versions_key(user_id)
        try:
            await client.zadd(key, {chat_id: float(last_edited_overall_timestamp)})
            await client.expire(key, self.CHAT_IDS_VERSIONS_TTL)
            return True
        except Exception as e:
            logger.error(f"Error adding chat {chat_id} to {key}: {e}")
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

    # 2. user:{user_id}:chat:{chat_id}:versions (Hash: messages_v, draft_v, title_v)
    def _get_chat_versions_key(self, user_id: str, chat_id: str) -> str:
        return f"user:{user_id}:chat:{chat_id}:versions"

    async def set_chat_versions(self, user_id: str, chat_id: str, versions: CachedChatVersions, ttl: Optional[int] = None) -> bool:
        """Sets the component versions for a chat."""
        client = await self.client
        if not client: return False
        key = self._get_chat_versions_key(user_id, chat_id)
        try:
            await client.hmset(key, versions.model_dump())
            await client.expire(key, ttl if ttl is not None else self.CHAT_VERSIONS_TTL)
            return True
        except Exception as e:
            logger.error(f"Error setting versions for {key}: {e}")
            return False

    async def get_chat_versions(self, user_id: str, chat_id: str) -> Optional[CachedChatVersions]:
        """Gets the component versions for a chat."""
        client = await self.client
        if not client: return None
        key = self._get_chat_versions_key(user_id, chat_id)
        try:
            versions_data_bytes = await client.hgetall(key)
            if not versions_data_bytes:
                return None
            versions_data = {k.decode('utf-8'): int(v.decode('utf-8')) for k, v in versions_data_bytes.items()}
            return CachedChatVersions(**versions_data)
        except Exception as e:
            logger.error(f"Error getting versions from {key}: {e}")
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
        try:
            new_version = await client.hincrby(key, component, increment_by)
            await client.expire(key, self.CHAT_VERSIONS_TTL) # Ensure TTL is refreshed
            return new_version
        except Exception as e:
            logger.error(f"Error incrementing {component} for {key}: {e}")
            return None

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
        Returns the new draft version or None on error.
        """
        client = await self.client
        if not client: return None

        draft_key = self._get_user_chat_draft_key(user_id, chat_id)
        versions_key = self._get_chat_versions_key(user_id, chat_id) # This key is for the chat, user_id in path is the owner of the cache view
        
        new_draft_version: Optional[int] = None
        try:
            # Increment in the dedicated draft key
            # If the key or field doesn't exist, hincrby creates it with the increment value.
            new_draft_version = await client.hincrby(draft_key, "draft_v", increment_by)
            await client.expire(draft_key, self.USER_DRAFT_TTL) # Assuming USER_DRAFT_TTL is defined in base

            # Ensure base versions are initialized in the general versions key for the chat
            # HSETNX returns 1 if field is new and set, 0 if field already exists.
            await client.hsetnx(versions_key, "messages_v", 0) # Initialize to 0 if not exists
            await client.hsetnx(versions_key, "title_v", 0)    # Initialize to 0 if not exists

            # Increment the user-specific draft version in the general versions key
            user_specific_draft_version_field = f"user_draft_v:{user_id}"
            # new_draft_version_in_general_key = await client.hincrby(versions_key, user_specific_draft_version_field, increment_by)
            # For consistency, we can set it directly using the new_draft_version from the dedicated key,
            # or rely on hincrby if we are sure it's the only place this specific field is incremented.
            # Using hincrby is generally safer for counters.
            await client.hincrby(versions_key, user_specific_draft_version_field, increment_by)

            # We also ensure the versions key's TTL is refreshed
            await client.expire(versions_key, self.CHAT_VERSIONS_TTL)
            
            logger.debug(f"Incremented draft version for user {user_id}, chat {chat_id} to {new_draft_version}. Ensured base chat versions.")
            return new_draft_version
        except Exception as e:
            logger.error(f"Error incrementing draft version for user {user_id}, chat {chat_id}: {e}")
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

    async def update_chat_list_item_field(self, user_id: str, chat_id: str, field: Literal["title", "unread_count"], value: Any) -> bool:
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