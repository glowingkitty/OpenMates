import logging
import json # For serializing/deserializing metadata
from typing import Dict, Optional # For type hinting

# Import base service and mixins
from .cache_base import CacheServiceBase
from .cache_user_mixin import UserCacheMixin
from .cache_chat_mixin import ChatCacheMixin
from .cache_order_mixin import OrderCacheMixin
from .cache_legacy_mixin import LegacyChatCacheMixin
from .cache_device_mixin import DeviceCacheMixin

# Import schemas used by mixins (if any are directly type hinted in method signatures)
# For example, if ChatCacheMixin methods directly hint at CachedChatVersions, etc.
# from backend.core.api.app.schemas.chat import CachedChatVersions, CachedChatListItemData # Already in ChatCacheMixin
from backend.shared.python_schemas.app_metadata_schemas import AppYAML # For discovered_apps_metadata

logger = logging.getLogger(__name__)

# Cache key for discovered apps metadata
DISCOVERED_APPS_METADATA_CACHE_KEY = "discovered_apps_metadata_v1"

class CacheService(
    CacheServiceBase,
    UserCacheMixin,
    ChatCacheMixin,
    OrderCacheMixin,
    LegacyChatCacheMixin,
    DeviceCacheMixin
):
    """
    Service for caching data using Dragonfly (Redis-compatible).
    This class combines a base service with various mixins for modular functionality.
    """
    def __init__(self):
        # Initialize the base class which sets up the Redis connection and constants
        super().__init__()
        logger.info("CacheService fully initialized with all mixins.")

    async def set_discovered_apps_metadata(self, metadata: Dict[str, AppYAML], ttl: int = 3600):
        """
        Serializes and stores the discovered applications metadata in the cache.

        Args:
            metadata (Dict[str, AppYAML]): A dictionary of app IDs to their AppYAML metadata.
            ttl (int): Time-to-live for the cached data in seconds. Defaults to 1 hour.
        """
        try:
            # Convert Pydantic models to dictionaries for JSON serialization
            serializable_metadata = {
                app_id: data.model_dump(mode='json') for app_id, data in metadata.items()
            }
            metadata_json = json.dumps(serializable_metadata)
            await self.set(DISCOVERED_APPS_METADATA_CACHE_KEY, metadata_json, ttl=ttl)
            logger.info(f"Successfully cached discovered_apps_metadata to Redis with key '{DISCOVERED_APPS_METADATA_CACHE_KEY}'.")
        except Exception as e:
            logger.error(f"Failed to set discovered_apps_metadata in cache: {e}", exc_info=True)
            # Optionally re-raise or handle as per application's error strategy

    async def get_discovered_apps_metadata(self) -> Optional[Dict[str, AppYAML]]:
        """
        Retrieves and deserializes the discovered applications metadata from the cache.

        Returns:
            Optional[Dict[str, AppYAML]]: A dictionary of app IDs to their AppYAML metadata,
                                          or None if not found or an error occurs.
        """
        try:
            metadata_json = await self.get(DISCOVERED_APPS_METADATA_CACHE_KEY)
            if not metadata_json:
                logger.info(f"Discovered apps metadata not found in cache with key '{DISCOVERED_APPS_METADATA_CACHE_KEY}'.")
                return None

            # Check if the data is already a dictionary
            if isinstance(metadata_json, dict):
                raw_metadata = metadata_json
            else:
                raw_metadata = json.loads(metadata_json)
                
            discovered_apps_metadata = {
                app_id: AppYAML(**meta_dict)
                for app_id, meta_dict in raw_metadata.items()
            }
            logger.info(f"Successfully retrieved and parsed discovered_apps_metadata from cache.")
            return discovered_apps_metadata
        except json.JSONDecodeError as jde:
            logger.error(f"Failed to parse discovered_apps_metadata from cache (JSONDecodeError) for key '{DISCOVERED_APPS_METADATA_CACHE_KEY}': {jde}", exc_info=True)
            return None
        except Exception as e: # Catches Pydantic ValidationError and others
            logger.error(f"Error retrieving or parsing discovered_apps_metadata from cache for key '{DISCOVERED_APPS_METADATA_CACHE_KEY}': {e}", exc_info=True)
            return None

    async def set_user_cache_primed_flag(self, user_id: str, expiry_seconds: int = 21600): # 6 hours
        """
        Sets a flag in Redis indicating the user's cache is primed.
        The flag expires to handle cases where a user might not log back in for a while,
        forcing a fresh cache warm on next login after expiry.
        """
        key = f"user:{user_id}:cache_status:primed_flag"
        try:
            redis_client = await self.client
            if not redis_client:
                logger.error(f"CacheService: Redis client not available. Failed to set primed_flag for user {user_id}.")
                # Re-raise a more specific error or handle as per application's error strategy
                raise ConnectionError(f"CacheService: Redis client not available when trying to set primed_flag for user {user_id}.")
            await redis_client.set(key, "true", ex=expiry_seconds)
            logger.info(f"CacheService: Set primed_flag for user {user_id} with expiry {expiry_seconds}s.")
        except Exception as e:
            logger.error(f"CacheService: Failed to set primed_flag for user {user_id}: {e}", exc_info=True)
            raise # Re-raise the exception so the caller is aware

    async def is_user_cache_primed(self, user_id: str) -> bool:
        """Checks if the user's cache is flagged as primed in Redis."""
        key = f"user:{user_id}:cache_status:primed_flag"
        try:
            redis_client = await self.client
            if not redis_client:
                logger.error(f"CacheService: Redis client not available. Failed to check primed_flag for user {user_id}.")
                return False # Default to false on error as per original logic
            exists = await redis_client.exists(key)
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
            redis_client = await self.client
            if not redis_client:
                logger.error(f"CacheService: Redis client not available. Failed to delete primed_flag for user {user_id}.")
                # Optionally raise an error or return a status
                return
            await redis_client.delete(key)
            logger.info(f"CacheService: Cleared primed_flag for user {user_id}.")
        except Exception as e:
            logger.error(f"CacheService: Failed to delete primed_flag for user {user_id}: {e}", exc_info=True)
            # Decide if to re-raise or just log based on how critical this operation is.

# Optional: Instantiate a global cache service instance if your application uses one.
# cache_service = CacheService()
# logger.info("Global CacheService instance created.")
