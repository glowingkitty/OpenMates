import logging

# Import base service and mixins
from .cache_base import CacheServiceBase
from .cache_user_mixin import UserCacheMixin
from .cache_chat_mixin import ChatCacheMixin
from .cache_order_mixin import OrderCacheMixin
from .cache_legacy_mixin import LegacyChatCacheMixin

# Import schemas used by mixins (if any are directly type hinted in method signatures)
# For example, if ChatCacheMixin methods directly hint at CachedChatVersions, etc.
# from app.schemas.chat import CachedChatVersions, CachedChatListItemData # Already in ChatCacheMixin

logger = logging.getLogger(__name__)

class CacheService(
    CacheServiceBase,
    UserCacheMixin,
    ChatCacheMixin,
    OrderCacheMixin,
    LegacyChatCacheMixin
):
    """
    Service for caching data using Dragonfly (Redis-compatible).
    This class combines a base service with various mixins for modular functionality.
    """
    def __init__(self):
        # Initialize the base class which sets up the Redis connection and constants
        super().__init__()
        logger.info("CacheService fully initialized with all mixins.")

    async def set_user_cache_primed_flag(self, user_id: str, expiry_seconds: int = 21600): # 6 hours
        """
        Sets a flag in Redis indicating the user's cache is primed.
        The flag expires to handle cases where a user might not log back in for a while,
        forcing a fresh cache warm on next login after expiry.
        """
        key = f"user:{user_id}:cache_status:primed_flag"
        try:
            await self.redis_client.set(key, "true", ex=expiry_seconds)
            logger.info(f"CacheService: Set primed_flag for user {user_id} with expiry {expiry_seconds}s.")
        except Exception as e:
            logger.error(f"CacheService: Failed to set primed_flag for user {user_id}: {e}", exc_info=True)
            raise # Re-raise the exception so the caller is aware

    async def is_user_cache_primed(self, user_id: str) -> bool:
        """Checks if the user's cache is flagged as primed in Redis."""
        key = f"user:{user_id}:cache_status:primed_flag"
        try:
            exists = await self.redis_client.exists(key)
            is_primed = bool(exists)
            logger.debug(f"CacheService: Checked primed_flag for user {user_id}. Exists: {is_primed}")
            return is_primed
        except Exception as e:
            logger.error(f"CacheService: Failed to check primed_flag for user {user_id}: {e}", exc_info=True)
            return False # Default to false on error to avoid incorrect assumptions

    async def clear_user_cache_primed_flag(self, user_id: str):
        """Clears the cache primed flag for a user from Redis."""
        key = f"user:{user_id}:cache_status:primed_flag"
        try:
            await self.redis_client.delete(key)
            logger.info(f"CacheService: Cleared primed_flag for user {user_id}.")
        except Exception as e:
            logger.error(f"CacheService: Failed to delete primed_flag for user {user_id}: {e}", exc_info=True)
            # Decide if to re-raise or just log based on how critical this operation is.

# Optional: Instantiate a global cache service instance if your application uses one.
# cache_service = CacheService()
# logger.info("Global CacheService instance created.")