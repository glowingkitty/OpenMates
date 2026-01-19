import logging
import json
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Cache keys for public demo chats
DEMO_CHATS_LIST_CACHE_KEY = "public:demo_chats:list"
DEMO_CHATS_CATEGORY_LIST_CACHE_KEY_PREFIX = "public:demo_chats:category:"
DEMO_CHAT_DATA_CACHE_KEY_PREFIX = "public:demo_chat:data:"

class DemoChatCacheMixin:
    """Mixin for demo chat caching methods"""

    async def set_demo_chat_data(self, demo_id: str, data: Dict[str, Any], ttl: int = 3600) -> bool:
        """
        Cache full demo chat data (including messages and encryption key).
        """
        client = await self.client
        if not client:
            return False
        
        key = f"{DEMO_CHAT_DATA_CACHE_KEY_PREFIX}{demo_id}"
        try:
            await client.set(key, json.dumps(data), ex=ttl)
            logger.debug(f"Cached demo chat data for {demo_id} with TTL {ttl}s")
            return True
        except Exception as e:
            logger.error(f"Error caching demo chat data: {e}", exc_info=True)
            return False

    async def get_demo_chat_data(self, demo_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached full demo chat data.
        """
        client = await self.client
        if not client:
            return None
        
        key = f"{DEMO_CHAT_DATA_CACHE_KEY_PREFIX}{demo_id}"
        try:
            data = await client.get(key)
            if data:
                return json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
            return None
        except Exception as e:
            logger.error(f"Error retrieving demo chat data from cache: {e}", exc_info=True)
            return None

    async def set_demo_chats_list(self, demo_chats: List[Dict[str, Any]], category: Optional[str] = None, ttl: int = 3600) -> bool:
        """
        Cache the list of approved demo chats.
        
        Args:
            demo_chats: List of demo chat metadata dictionaries
            category: Optional category filter
            ttl: Time to live in seconds (default: 1 hour)
        
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            return False
        
        key = f"{DEMO_CHATS_CATEGORY_LIST_CACHE_KEY_PREFIX}{category}" if category else DEMO_CHATS_LIST_CACHE_KEY
        try:
            await client.set(key, json.dumps(demo_chats), ex=ttl)
            logger.debug(f"Cached {len(demo_chats)} demo chats for key '{key}' with TTL {ttl}s")
            return True
        except Exception as e:
            logger.error(f"Error caching demo chats list: {e}", exc_info=True)
            return False

    async def get_demo_chats_list(self, category: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Get the cached list of approved demo chats.
        
        Args:
            category: Optional category filter
        
        Returns:
            List of demo chat metadata if cached, None otherwise
        """
        client = await self.client
        if not client:
            return None
        
        key = f"{DEMO_CHATS_CATEGORY_LIST_CACHE_KEY_PREFIX}{category}" if category else DEMO_CHATS_LIST_CACHE_KEY
        try:
            data = await client.get(key)
            if data:
                return json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
            return None
        except Exception as e:
            logger.error(f"Error retrieving demo chats list from cache: {e}", exc_info=True)
            return None

    async def clear_demo_chats_cache(self) -> bool:
        """
        Invalidate all demo chat list caches.
        Should be called when a demo chat is approved or deactivated.
        """
        client = await self.client
        if not client:
            return False
        
        try:
            # Clear main list
            await client.delete(DEMO_CHATS_LIST_CACHE_KEY)
            
            # Clear all category lists using SCAN
            pattern = f"{DEMO_CHATS_CATEGORY_LIST_CACHE_KEY_PREFIX}*"
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor, match=pattern, count=100)
                if keys:
                    await client.delete(*keys)
                if cursor == 0:
                    break
            
            # Clear all single chat data using SCAN
            pattern = f"{DEMO_CHAT_DATA_CACHE_KEY_PREFIX}*"
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor, match=pattern, count=100)
                if keys:
                    await client.delete(*keys)
                if cursor == 0:
                    break
            
            logger.info("Invalidated all demo chat caches (lists and single chats)")
            return True
        except Exception as e:
            logger.error(f"Error clearing demo chats cache: {e}", exc_info=True)
            return False
