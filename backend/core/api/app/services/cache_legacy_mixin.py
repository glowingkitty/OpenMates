import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

class LegacyChatCacheMixin:
    """Mixin for legacy chat-related caching methods"""

    async def update_user_active_chats_lru(self, user_id: str, chat_id: str):
        """
        Update the LRU list of last 3 active chats for a user.
        """
        try:
            client = await self.client
            if not client:
                return False
            lru_key = f"{self.USER_ACTIVE_CHATS_LRU_PREFIX}{user_id}"
            await client.lrem(lru_key, 0, chat_id)
            await client.lpush(lru_key, chat_id)
            await client.ltrim(lru_key, 0, 2)
            await client.expire(lru_key, self.CHAT_METADATA_TTL)
            return True
        except Exception as e:
            logger.error(f"Error updating LRU for user {user_id}: {e}")
            return False

    async def mark_chat_deleted(self, chat_id: str, hashed_user_id: str = None, ttl: int = None) -> bool:
        """
        Mark a chat as deleted (tombstone) in the cache with a TTL.
        """
        try:
            key = f"chat:{chat_id}:metadata" # This key structure is specific to legacy
            client = await self.client
            if not client:
                logger.error("Cache client not connected for mark_chat_deleted.")
                return False
            existing = await self.get(key)
            metadata = existing if existing else {
                "id": chat_id,
                "hashed_user_id": hashed_user_id,
            }
            metadata["deleted"] = True
            metadata["deleted_at"] = int(time.time())
            tombstone_ttl = ttl if ttl is not None else self.CHAT_METADATA_TTL
            await self.set(key, metadata, ttl=tombstone_ttl) # Uses base set method
            logger.info(f"Marked chat {chat_id} as deleted (tombstone) in cache with TTL {tombstone_ttl}s.")
            if hashed_user_id:
                await self.remove_chat_from_user_set(hashed_user_id, chat_id)
            return True
        except Exception as e:
            logger.error(f"Error marking chat {chat_id} as deleted (tombstone): {e}")
            return False

    async def remove_chat_from_user_set(self, hashed_user_id: str, chat_id: str) -> bool:
        """Removes a chat ID from the set of chats belonging to a user (legacy)."""
        try:
            client = await self.client
            if not client: return False
            set_key = f"{self.USER_CHATS_SET_PREFIX}{hashed_user_id}"
            logger.debug(f"Removing chat '{chat_id}' from user set '{set_key}'")
            removed = await client.srem(set_key, chat_id)
            return removed > 0
        except Exception as e:
            logger.error(f"Error removing chat '{chat_id}' from user set for user '{hashed_user_id}': {e}")
            return False