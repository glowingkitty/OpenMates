# backend/core/api/app/services/storage_management.py
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)


class StorageManagementService:
    """
    Manages storage limits and eviction policies for the sync architecture.
    Implements the storage strategy from sync.md:
    - Keep up to 100 most recent chats
    - Evict oldest chat when storage would overflow
    - Handle pinned chats (future feature)
    """
    
    # Storage limits as defined in sync.md
    MAX_CACHED_CHATS = 100
    MAX_STORAGE_SIZE_MB = 50  # Configurable storage limit
    
    def __init__(self, cache_service: CacheService, directus_service: DirectusService):
        self.cache_service = cache_service
        self.directus_service = directus_service
    
    async def check_storage_limits(self, user_id: str) -> Dict[str, Any]:
        """
        Check current storage usage and determine if eviction is needed.
        
        Returns:
            Dict with storage status and eviction recommendations
        """
        try:
            # Get current chat count
            chat_ids = await self.cache_service.get_chat_ids_versions(user_id, with_scores=False)
            current_count = len(chat_ids) if chat_ids else 0
            
            # Calculate storage usage (simplified - in real implementation, 
            # you'd calculate actual storage size)
            storage_usage_mb = await self._calculate_storage_usage(user_id)
            
            needs_eviction = (
                current_count > self.MAX_CACHED_CHATS or 
                storage_usage_mb > self.MAX_STORAGE_SIZE_MB
            )
            
            return {
                "current_chat_count": current_count,
                "max_chat_count": self.MAX_CACHED_CHATS,
                "storage_usage_mb": storage_usage_mb,
                "max_storage_mb": self.MAX_STORAGE_SIZE_MB,
                "needs_eviction": needs_eviction,
                "eviction_candidates": await self._get_eviction_candidates(user_id) if needs_eviction else []
            }
            
        except Exception as e:
            logger.error(f"Error checking storage limits for user {user_id}: {e}", exc_info=True)
            return {
                "current_chat_count": 0,
                "max_chat_count": self.MAX_CACHED_CHATS,
                "storage_usage_mb": 0,
                "max_storage_mb": self.MAX_STORAGE_SIZE_MB,
                "needs_eviction": False,
                "eviction_candidates": []
            }
    
    async def evict_oldest_chat(self, user_id: str) -> Optional[str]:
        """
        Evict the oldest chat from cache to make room for new data.
        
        Returns:
            chat_id of evicted chat, or None if no eviction needed
        """
        try:
            # Get chat IDs ordered by last updated timestamp (oldest first)
            chat_ids_with_scores = await self.cache_service.get_chat_ids_versions(
                user_id, with_scores=True
            )
            
            if not chat_ids_with_scores or len(chat_ids_with_scores) <= self.MAX_CACHED_CHATS:
                logger.info(f"No eviction needed for user {user_id}: {len(chat_ids_with_scores or [])} chats")
                return None
            
            # Find the oldest chat (lowest score = oldest timestamp)
            oldest_chat_id = min(chat_ids_with_scores, key=lambda x: x[1])[0]
            
            # Evict the oldest chat
            await self._evict_chat_from_cache(user_id, oldest_chat_id)
            
            logger.info(f"Evicted oldest chat {oldest_chat_id} for user {user_id}")
            return oldest_chat_id
            
        except Exception as e:
            logger.error(f"Error evicting oldest chat for user {user_id}: {e}", exc_info=True)
            return None
    
    async def handle_storage_overflow(self, user_id: str, new_chat_id: str) -> bool:
        """
        Handle storage overflow when adding a new chat.
        
        Args:
            user_id: User ID
            new_chat_id: ID of the new chat being added
            
        Returns:
            True if overflow was handled successfully, False otherwise
        """
        try:
            logger.info(f"Handling storage overflow for user {user_id}, new chat: {new_chat_id}")
            
            # Check if we need to evict
            storage_status = await self.check_storage_limits(user_id)
            
            if not storage_status["needs_eviction"]:
                logger.info(f"No eviction needed for user {user_id}")
                return True
            
            # Evict oldest chat
            evicted_chat_id = await self.evict_oldest_chat(user_id)
            
            if evicted_chat_id:
                logger.info(f"Successfully evicted chat {evicted_chat_id} for user {user_id}")
                return True
            else:
                logger.warning(f"Failed to evict chat for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error handling storage overflow for user {user_id}: {e}", exc_info=True)
            return False
    
    async def _calculate_storage_usage(self, user_id: str) -> float:
        """
        Calculate current storage usage in MB.
        This is a simplified calculation - in production, you'd want more accurate sizing.
        """
        try:
            # Get all cached data for the user
            chat_ids = await self.cache_service.get_chat_ids_versions(user_id, with_scores=False)
            if not chat_ids:
                return 0.0
            
            # Estimate storage usage based on chat count and average size
            # This is a rough estimate - in production, you'd calculate actual storage
            estimated_mb_per_chat = 0.5  # 500KB per chat estimate
            total_mb = len(chat_ids) * estimated_mb_per_chat
            
            return total_mb
            
        except Exception as e:
            logger.error(f"Error calculating storage usage for user {user_id}: {e}", exc_info=True)
            return 0.0
    
    async def _get_eviction_candidates(self, user_id: str) -> List[Tuple[str, float]]:
        """
        Get list of chat IDs that are candidates for eviction, ordered by priority.
        
        Returns:
            List of (chat_id, timestamp) tuples, ordered by eviction priority
        """
        try:
            chat_ids_with_scores = await self.cache_service.get_chat_ids_versions(
                user_id, with_scores=True
            )
            
            if not chat_ids_with_scores:
                return []
            
            # Sort by timestamp (oldest first = highest eviction priority)
            eviction_candidates = sorted(chat_ids_with_scores, key=lambda x: x[1])
            
            return eviction_candidates
            
        except Exception as e:
            logger.error(f"Error getting eviction candidates for user {user_id}: {e}", exc_info=True)
            return []
    
    async def _evict_chat_from_cache(self, user_id: str, chat_id: str) -> bool:
        """
        Evict a specific chat from cache.
        
        Args:
            user_id: User ID
            chat_id: Chat ID to evict
            
        Returns:
            True if eviction was successful, False otherwise
        """
        try:
            logger.info(f"Evicting chat {chat_id} from cache for user {user_id}")
            
            # Remove chat from various cache components
            await self.cache_service.remove_chat_from_ids_versions(user_id, chat_id)
            await self.cache_service.delete_chat_versions(user_id, chat_id)
            await self.cache_service.delete_chat_list_item_data(user_id, chat_id)
            await self.cache_service.delete_chat_messages_history(user_id, chat_id)
            await self.cache_service.delete_user_draft_from_cache(user_id, chat_id)
            
            logger.info(f"Successfully evicted chat {chat_id} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error evicting chat {chat_id} for user {user_id}: {e}", exc_info=True)
            return False
    
    async def get_storage_statistics(self, user_id: str) -> Dict[str, Any]:
        """
        Get detailed storage statistics for a user.
        
        Returns:
            Dict with storage statistics
        """
        try:
            chat_ids = await self.cache_service.get_chat_ids_versions(user_id, with_scores=False)
            chat_count = len(chat_ids) if chat_ids else 0
            
            storage_usage = await self._calculate_storage_usage(user_id)
            
            return {
                "user_id": user_id,
                "chat_count": chat_count,
                "max_chat_count": self.MAX_CACHED_CHATS,
                "storage_usage_mb": storage_usage,
                "max_storage_mb": self.MAX_STORAGE_SIZE_MB,
                "utilization_percent": (chat_count / self.MAX_CACHED_CHATS) * 100,
                "storage_utilization_percent": (storage_usage / self.MAX_STORAGE_SIZE_MB) * 100,
                "timestamp": int(datetime.now(timezone.utc).timestamp())
            }
            
        except Exception as e:
            logger.error(f"Error getting storage statistics for user {user_id}: {e}", exc_info=True)
            return {
                "user_id": user_id,
                "chat_count": 0,
                "max_chat_count": self.MAX_CACHED_CHATS,
                "storage_usage_mb": 0,
                "max_storage_mb": self.MAX_STORAGE_SIZE_MB,
                "utilization_percent": 0,
                "storage_utilization_percent": 0,
                "timestamp": int(datetime.now(timezone.utc).timestamp())
            }
