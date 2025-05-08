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

    async def increment_chat_component_version(self, user_id: str, chat_id: str, component: Literal["messages_v", "draft_v", "title_v"], increment_by: int = 1) -> Optional[int]:
        """Increments a specific component version for a chat. Returns the new version or None on error."""
        client = await self.client
        if not client: return None
        key = self._get_chat_versions_key(user_id, chat_id)
        try:
            new_version = await client.hincrby(key, component, increment_by)
            await client.expire(key, self.CHAT_VERSIONS_TTL)
            return new_version
        except Exception as e:
            logger.error(f"Error incrementing {component} for {key}: {e}")
            return None

    # 3. user:{user_id}:chat:{chat_id}:list_item_data (Hash: title (enc), unread_count, draft_json (enc))
    def _get_chat_list_item_data_key(self, user_id: str, chat_id: str) -> str:
        return f"user:{user_id}:chat:{chat_id}:list_item_data"

    async def set_chat_list_item_data(self, user_id: str, chat_id: str, data: CachedChatListItemData, ttl: Optional[int] = None) -> bool:
        """Sets the list item data for a chat."""
        client = await self.client
        if not client: return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            await client.hmset(key, data.model_dump(exclude_none=True))
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
            if 'draft_json' not in data:
                data['draft_json'] = None

            parsed_data = CachedChatListItemData(**data)
            if refresh_ttl:
                await client.expire(key, self.CHAT_LIST_ITEM_DATA_TTL)
            return parsed_data
        except Exception as e:
            logger.error(f"Error getting list_item_data from {key}: {e}")
            return None

    async def update_chat_list_item_field(self, user_id: str, chat_id: str, field: Literal["title", "unread_count", "draft_json"], value: Any) -> bool:
        """Updates a specific field in the chat's list_item_data. Refreshes TTL."""
        client = await self.client
        if not client: return False
        key = self._get_chat_list_item_data_key(user_id, chat_id)
        try:
            if value is None and field == "draft_json":
                 await client.hset(key, field, "null") 
            else:
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