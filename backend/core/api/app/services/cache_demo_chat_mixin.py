import logging
import json
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Cache keys for public demo chats
DEMO_CHATS_LIST_CACHE_KEY_PREFIX = "public:demo_chats:list:" # Prefix for language-specific lists
DEMO_CHATS_CATEGORY_LIST_CACHE_KEY_PREFIX = "public:demo_chats:category:"
DEMO_CHAT_DATA_CACHE_KEY_PREFIX = "public:demo_chat:data:" # Prefix for language-specific chat data

class DemoChatCacheMixin:
    """Mixin for demo chat caching methods"""

    async def set_demo_chat_data(self, demo_id: str, language: str, data: Dict[str, Any], ttl: int = 86400) -> bool:
        """
        Cache full demo chat data for a specific language.
        """
        client = await self.client
        if not client:
            return False
        
        key = f"{DEMO_CHAT_DATA_CACHE_KEY_PREFIX}{demo_id}:{language}"
        try:
            await client.set(key, json.dumps(data), ex=ttl)
            logger.debug(f"Cached demo chat data for {demo_id} ({language}) with TTL {ttl}s")
            return True
        except Exception as e:
            logger.error(f"Error caching demo chat data: {e}", exc_info=True)
            return False

    async def get_demo_chat_data(self, demo_id: str, language: str) -> Optional[Dict[str, Any]]:
        """
        Get cached full demo chat data for a specific language.
        """
        client = await self.client
        if not client:
            return None
        
        key = f"{DEMO_CHAT_DATA_CACHE_KEY_PREFIX}{demo_id}:{language}"
        try:
            data = await client.get(key)
            if data:
                return json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
            return None
        except Exception as e:
            logger.error(f"Error retrieving demo chat data from cache: {e}", exc_info=True)
            return None

    async def set_demo_chats_list(self, language: str, demo_chats: List[Dict[str, Any]], category: Optional[str] = None, ttl: int = 86400) -> bool:
        """
        Cache the list of approved demo chats for a specific language.
        """
        client = await self.client
        if not client:
            return False
        
        if category:
            key = f"{DEMO_CHATS_CATEGORY_LIST_CACHE_KEY_PREFIX}{category}:{language}"
        else:
            key = f"{DEMO_CHATS_LIST_CACHE_KEY_PREFIX}{language}"
            
        try:
            await client.set(key, json.dumps(demo_chats), ex=ttl)
            logger.debug(f"Cached {len(demo_chats)} demo chats for key '{key}' with TTL {ttl}s")
            return True
        except Exception as e:
            logger.error(f"Error caching demo chats list: {e}", exc_info=True)
            return False

    async def get_demo_chats_list(self, language: str, category: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Get the cached list of approved demo chats for a specific language.
        """
        client = await self.client
        if not client:
            return None
        
        if category:
            key = f"{DEMO_CHATS_CATEGORY_LIST_CACHE_KEY_PREFIX}{category}:{language}"
        else:
            key = f"{DEMO_CHATS_LIST_CACHE_KEY_PREFIX}{language}"
            
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
            # Clear main lists for all languages
            pattern_list = f"{DEMO_CHATS_LIST_CACHE_KEY_PREFIX}*"
            # Clear all category lists using SCAN
            pattern_cat = f"{DEMO_CHATS_CATEGORY_LIST_CACHE_KEY_PREFIX}*"
            # Clear all single chat data using SCAN
            pattern_data = f"{DEMO_CHAT_DATA_CACHE_KEY_PREFIX}*"
            
            for pattern in [pattern_list, pattern_cat, pattern_data]:
                cursor = 0
                while True:
                    cursor, keys = await client.scan(cursor, match=pattern, count=100)
                    if keys:
                        await client.delete(*keys)
                    if cursor == 0:
                        break
            
            logger.info("Invalidated all demo chat caches (lists and single chats) for all languages")
            return True
        except Exception as e:
            logger.error(f"Error clearing demo chats cache: {e}", exc_info=True)
            return False
