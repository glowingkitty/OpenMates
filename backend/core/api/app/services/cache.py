import logging
import json # For serializing/deserializing metadata
from typing import Dict, Optional, List, Any # For type hinting

# Import base service and mixins
from .cache_base import CacheServiceBase
from .cache_user_mixin import UserCacheMixin
from .cache_chat_mixin import ChatCacheMixin
from .cache_order_mixin import OrderCacheMixin
from .cache_legacy_mixin import LegacyChatCacheMixin
from .cache_debug_mixin import DebugCacheMixin
from .cache_demo_chat_mixin import DemoChatCacheMixin
from .cache_stats_mixin import CacheStatsMixin
from .cache_reminder_mixin import ReminderCacheMixin
from .cache_inspiration_mixin import InspirationCacheMixin

# Import schemas used by mixins (if any are directly type hinted in method signatures)
# For example, if ChatCacheMixin methods directly hint at CachedChatVersions, etc.
# from backend.core.api.app.schemas.chat import CachedChatVersions, CachedChatListItemData # Already in ChatCacheMixin
from backend.shared.python_schemas.app_metadata_schemas import AppYAML # For discovered_apps_metadata
from backend.apps.ai.utils.mate_utils import MateConfig # For mates_configs caching

logger = logging.getLogger(__name__)

# Cache key for discovered apps metadata
DISCOVERED_APPS_METADATA_CACHE_KEY = "discovered_apps_metadata_v1"

# Cache key for most used apps (30-day window)
MOST_USED_APPS_CACHE_KEY = "app_usage:most_used:30d"

# Cache keys for AI processing configuration
BASE_INSTRUCTIONS_CACHE_KEY = "ai:base_instructions_v1"
MATES_CONFIGS_CACHE_KEY = "ai:mates_configs_v1"
CONTENT_SANITIZATION_MODEL_CACHE_KEY = "ai:content_sanitization_model_v1"
PROMPT_INJECTION_DETECTION_CONFIG_CACHE_KEY = "ai:prompt_injection_detection_config_v1"

class CacheService(
    CacheServiceBase,
    UserCacheMixin,
    ChatCacheMixin,
    OrderCacheMixin,
    LegacyChatCacheMixin,
    DebugCacheMixin,
    DemoChatCacheMixin,
    CacheStatsMixin,
    ReminderCacheMixin,
    InspirationCacheMixin,
):
    """
    Service for caching data using Dragonfly (Redis-compatible).
    This class combines a base service with various mixins for modular functionality.
    """
    def __init__(self):
        # Initialize the base class which sets up the Redis connection and constants
        super().__init__()
        logger.info("CacheService fully initialized with all mixins.")

    async def set_discovered_apps_metadata(self, metadata: Dict[str, AppYAML]):
        """
        Serializes and stores the discovered applications metadata in the cache WITHOUT expiration.

        This data is static during server runtime - it only changes when the server restarts.
        No TTL is used because this data should persist indefinitely until the next server restart.
        CRITICAL: If this cache entry is missing, the LLM will have NO tools available for web search, etc.

        Args:
            metadata (Dict[str, AppYAML]): A dictionary of app IDs to their AppYAML metadata.
        """
        try:
            # Convert Pydantic models to dictionaries for JSON serialization
            # CRITICAL: Use by_alias=True to serialize using YAML field names (aliases) like 'systemprompt'
            # instead of Python field names like 'system_prompt'. This ensures deserialization works correctly.
            serializable_metadata = {
                app_id: data.model_dump(mode='json', by_alias=True) for app_id, data in metadata.items()
            }
            metadata_json = json.dumps(serializable_metadata)
            
            # Use Redis SET directly without TTL (no expiration)
            # The base self.set() method always uses SETEX which requires a TTL
            # For static data like discovered_apps_metadata, we want no expiration
            client = await self.client
            if client:
                await client.set(DISCOVERED_APPS_METADATA_CACHE_KEY, metadata_json)
                logger.info(f"Successfully cached discovered_apps_metadata to Redis with key '{DISCOVERED_APPS_METADATA_CACHE_KEY}' (no expiration).")
            else:
                logger.error("Failed to cache discovered_apps_metadata: Redis client not available.")
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
            logger.debug(f"Attempting to retrieve discovered_apps_metadata from cache with key '{DISCOVERED_APPS_METADATA_CACHE_KEY}'")
            metadata_json = await self.get(DISCOVERED_APPS_METADATA_CACHE_KEY)
            if not metadata_json:
                logger.warning(f"Discovered apps metadata not found in cache with key '{DISCOVERED_APPS_METADATA_CACHE_KEY}'. Cache may be empty or expired.")
                return None

            # Handle bytes response (Redis returns bytes when decode_responses=False)
            if isinstance(metadata_json, bytes):
                metadata_json = metadata_json.decode('utf-8')
                logger.debug(f"Decoded bytes response from cache to string (length: {len(metadata_json)})")

            # Check if the data is already a dictionary
            if isinstance(metadata_json, dict):
                raw_metadata = metadata_json
            else:
                raw_metadata = json.loads(metadata_json)
            
            # Log what we found before parsing
            app_ids_found = list(raw_metadata.keys()) if raw_metadata else []
            logger.debug(f"Found {len(app_ids_found)} app(s) in cache: {', '.join(app_ids_found) if app_ids_found else 'None'}")
            
            # Parse apps one by one, skipping invalid ones instead of failing entirely
            # This allows the system to work even if some apps have invalid metadata
            discovered_apps_metadata = {}
            invalid_apps = []
            for app_id, meta_dict in raw_metadata.items():
                try:
                    app_metadata = AppYAML(**meta_dict)
                    discovered_apps_metadata[app_id] = app_metadata
                except Exception as validation_error:
                    invalid_apps.append(app_id)
                    logger.warning(
                        f"Failed to validate app '{app_id}' from cache (skipping): {validation_error}. "
                        f"This app will not be available as a tool. Consider clearing cache or fixing app metadata."
                    )
            
            if invalid_apps:
                logger.error(
                    f"⚠️ CRITICAL: {len(invalid_apps)} app(s) failed validation and were skipped: {', '.join(invalid_apps)}. "
                    f"Only {len(discovered_apps_metadata)} valid app(s) loaded. "
                    f"Consider clearing the cache key '{DISCOVERED_APPS_METADATA_CACHE_KEY}' to force re-discovery."
                )
            
            if discovered_apps_metadata:
                logger.info(f"Successfully retrieved and parsed discovered_apps_metadata from cache. Found {len(discovered_apps_metadata)} valid app(s): {', '.join(discovered_apps_metadata.keys())}")
            else:
                logger.error(
                    f"⚠️ CRITICAL: No valid apps found in cache after parsing. "
                    f"All {len(raw_metadata)} app(s) failed validation or cache is corrupted. "
                    f"Consider clearing the cache key '{DISCOVERED_APPS_METADATA_CACHE_KEY}' to force re-discovery."
                )
            
            return discovered_apps_metadata if discovered_apps_metadata else None
        except json.JSONDecodeError as jde:
            logger.error(f"Failed to parse discovered_apps_metadata from cache (JSONDecodeError) for key '{DISCOVERED_APPS_METADATA_CACHE_KEY}': {jde}", exc_info=True)
            return None
        except Exception as e: # Catches other unexpected errors
            logger.error(f"Error retrieving or parsing discovered_apps_metadata from cache for key '{DISCOVERED_APPS_METADATA_CACHE_KEY}': {e}", exc_info=True)
            return None

    async def set_base_instructions(self, base_instructions: Dict, ttl: int = 86400):
        """
        Serializes and stores the base instructions (from base_instructions.yml) in the cache.
        
        This is preloaded on server startup to avoid disk I/O on every message processing request.
        
        Args:
            base_instructions (Dict): The base instructions dictionary loaded from base_instructions.yml.
            ttl (int): Time-to-live for the cached data in seconds. Defaults to 24 hours.
        """
        try:
            instructions_json = json.dumps(base_instructions)
            await self.set(BASE_INSTRUCTIONS_CACHE_KEY, instructions_json, ttl=ttl)
            logger.info(f"Successfully cached base_instructions to Redis with key '{BASE_INSTRUCTIONS_CACHE_KEY}' (TTL: {ttl}s).")
        except Exception as e:
            logger.error(f"Failed to set base_instructions in cache: {e}", exc_info=True)
            # Don't raise - allow fallback to disk loading

    async def get_base_instructions(self) -> Optional[Dict]:
        """
        Retrieves and deserializes the base instructions from the cache.
        
        Returns:
            Optional[Dict]: The base instructions dictionary, or None if not found or an error occurs.
        """
        try:
            logger.debug(f"Attempting to retrieve base_instructions from cache with key '{BASE_INSTRUCTIONS_CACHE_KEY}'")
            instructions_json = await self.get(BASE_INSTRUCTIONS_CACHE_KEY)
            if not instructions_json:
                logger.warning(f"Base instructions not found in cache with key '{BASE_INSTRUCTIONS_CACHE_KEY}'. Cache may be empty or expired.")
                return None

            # Handle bytes response (Redis returns bytes when decode_responses=False)
            if isinstance(instructions_json, bytes):
                instructions_json = instructions_json.decode('utf-8')
                logger.debug(f"Decoded bytes response from cache to string (length: {len(instructions_json)})")

            # Check if the data is already a dictionary
            if isinstance(instructions_json, dict):
                return instructions_json
            else:
                instructions = json.loads(instructions_json)
                logger.info("Successfully retrieved base_instructions from cache.")
                return instructions
        except json.JSONDecodeError as jde:
            logger.error(f"Failed to parse base_instructions from cache (JSONDecodeError) for key '{BASE_INSTRUCTIONS_CACHE_KEY}': {jde}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error retrieving or parsing base_instructions from cache for key '{BASE_INSTRUCTIONS_CACHE_KEY}': {e}", exc_info=True)
            return None

    async def set_mates_configs(self, mates_configs: List[MateConfig], ttl: int = 86400):
        """
        Serializes and stores the mates configurations (from mates.yml) in the cache.
        
        This is preloaded on server startup to avoid disk I/O on every message processing request.
        
        Args:
            mates_configs (List[MateConfig]): List of MateConfig Pydantic models loaded from mates.yml.
            ttl (int): Time-to-live for the cached data in seconds. Defaults to 24 hours.
        """
        try:
            # Convert Pydantic models to dictionaries for JSON serialization
            serializable_configs = [mate.model_dump(mode='json') for mate in mates_configs]
            configs_json = json.dumps(serializable_configs)
            await self.set(MATES_CONFIGS_CACHE_KEY, configs_json, ttl=ttl)
            logger.info(f"Successfully cached {len(mates_configs)} mates_configs to Redis with key '{MATES_CONFIGS_CACHE_KEY}' (TTL: {ttl}s).")
        except Exception as e:
            logger.error(f"Failed to set mates_configs in cache: {e}", exc_info=True)
            # Don't raise - allow fallback to disk loading

    async def get_mates_configs(self) -> Optional[List[MateConfig]]:
        """
        Retrieves and deserializes the mates configurations from the cache.
        
        Returns:
            Optional[List[MateConfig]]: List of MateConfig objects, or None if not found or an error occurs.
        """
        try:
            logger.debug(f"Attempting to retrieve mates_configs from cache with key '{MATES_CONFIGS_CACHE_KEY}'")
            configs_json = await self.get(MATES_CONFIGS_CACHE_KEY)
            if not configs_json:
                logger.warning(f"Mates configs not found in cache with key '{MATES_CONFIGS_CACHE_KEY}'. Cache may be empty or expired.")
                return None

            # Handle bytes response (Redis returns bytes when decode_responses=False)
            if isinstance(configs_json, bytes):
                configs_json = configs_json.decode('utf-8')
                logger.debug(f"Decoded bytes response from cache to string (length: {len(configs_json)})")

            # Parse JSON
            if isinstance(configs_json, list):
                raw_configs = configs_json
            else:
                raw_configs = json.loads(configs_json)
            
            # Parse mates one by one, skipping invalid ones instead of failing entirely
            mates_configs = []
            invalid_mates = []
            for mate_dict in raw_configs:
                try:
                    mate_config = MateConfig(**mate_dict)
                    mates_configs.append(mate_config)
                except Exception as validation_error:
                    invalid_mates.append(mate_dict.get('id', 'unknown'))
                    logger.warning(
                        f"Failed to validate mate '{mate_dict.get('id', 'unknown')}' from cache (skipping): {validation_error}. "
                        f"This mate will not be available. Consider clearing cache or fixing mates.yml."
                    )
            
            if invalid_mates:
                logger.error(
                    f"⚠️ CRITICAL: {len(invalid_mates)} mate(s) failed validation and were skipped: {', '.join(invalid_mates)}. "
                    f"Only {len(mates_configs)} valid mate(s) loaded. "
                    f"Consider clearing the cache key '{MATES_CONFIGS_CACHE_KEY}' to force re-loading from disk."
                )
            
            if mates_configs:
                logger.info(f"Successfully retrieved and parsed {len(mates_configs)} mates_configs from cache.")
            else:
                logger.error(
                    f"⚠️ CRITICAL: No valid mates found in cache after parsing. "
                    f"All {len(raw_configs)} mate(s) failed validation or cache is corrupted. "
                    f"Consider clearing the cache key '{MATES_CONFIGS_CACHE_KEY}' to force re-loading from disk."
                )
            
            return mates_configs if mates_configs else None
        except json.JSONDecodeError as jde:
            logger.error(f"Failed to parse mates_configs from cache (JSONDecodeError) for key '{MATES_CONFIGS_CACHE_KEY}': {jde}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error retrieving or parsing mates_configs from cache for key '{MATES_CONFIGS_CACHE_KEY}': {e}", exc_info=True)
            return None

    async def set_content_sanitization_model(self, model_id: str, ttl: int = 86400):
        """
        Stores the content sanitization model ID in the cache.
        
        This is preloaded on server startup to avoid disk I/O on every content sanitization request.
        
        Args:
            model_id (str): The model ID for content sanitization (e.g., "openai/gpt-oss-safeguard-20b").
            ttl (int): Time-to-live for the cached data in seconds. Defaults to 24 hours.
        """
        try:
            await self.set(CONTENT_SANITIZATION_MODEL_CACHE_KEY, model_id, ttl=ttl)
            logger.info(f"Successfully cached content_sanitization_model to Redis with key '{CONTENT_SANITIZATION_MODEL_CACHE_KEY}' (TTL: {ttl}s).")
        except Exception as e:
            logger.error(f"Failed to set content_sanitization_model in cache: {e}", exc_info=True)
            # Don't raise - allow fallback to disk loading

    async def get_content_sanitization_model(self) -> Optional[str]:
        """
        Retrieves the content sanitization model ID from the cache.
        
        Returns:
            Optional[str]: The model ID string, or None if not found or an error occurs.
        """
        try:
            logger.debug(f"Attempting to retrieve content_sanitization_model from cache with key '{CONTENT_SANITIZATION_MODEL_CACHE_KEY}'")
            model_id = await self.get(CONTENT_SANITIZATION_MODEL_CACHE_KEY)
            if not model_id:
                logger.warning(f"Content sanitization model not found in cache with key '{CONTENT_SANITIZATION_MODEL_CACHE_KEY}'. Cache may be empty or expired.")
                return None

            # Handle bytes response (Redis returns bytes when decode_responses=False)
            if isinstance(model_id, bytes):
                model_id = model_id.decode('utf-8')
                logger.debug("Decoded bytes response from cache to string")

            if isinstance(model_id, str):
                logger.debug(f"Successfully retrieved content_sanitization_model from cache: {model_id}")
                return model_id
            else:
                logger.error(f"Content sanitization model from cache is not a string: {type(model_id)}")
                return None
        except Exception as e:
            logger.error(f"Error retrieving content_sanitization_model from cache for key '{CONTENT_SANITIZATION_MODEL_CACHE_KEY}': {e}", exc_info=True)
            return None

    async def set_prompt_injection_detection_config(self, config: Dict[str, Any], ttl: int = 86400):
        """
        Serializes and stores the prompt injection detection configuration in the cache.
        
        This is preloaded on server startup to avoid disk I/O on every content sanitization request.
        
        Args:
            config (Dict[str, Any]): The prompt injection detection configuration dictionary.
            ttl (int): Time-to-live for the cached data in seconds. Defaults to 24 hours.
        """
        try:
            config_json = json.dumps(config)
            await self.set(PROMPT_INJECTION_DETECTION_CONFIG_CACHE_KEY, config_json, ttl=ttl)
            logger.info(f"Successfully cached prompt_injection_detection_config to Redis with key '{PROMPT_INJECTION_DETECTION_CONFIG_CACHE_KEY}' (TTL: {ttl}s).")
        except Exception as e:
            logger.error(f"Failed to set prompt_injection_detection_config in cache: {e}", exc_info=True)
            # Don't raise - allow fallback to disk loading

    async def get_prompt_injection_detection_config(self) -> Optional[Dict[str, Any]]:
        """
        Retrieves and deserializes the prompt injection detection configuration from the cache.
        
        Returns:
            Optional[Dict[str, Any]]: The configuration dictionary, or None if not found or an error occurs.
        """
        try:
            logger.debug(f"Attempting to retrieve prompt_injection_detection_config from cache with key '{PROMPT_INJECTION_DETECTION_CONFIG_CACHE_KEY}'")
            config_json = await self.get(PROMPT_INJECTION_DETECTION_CONFIG_CACHE_KEY)
            if not config_json:
                logger.warning(f"Prompt injection detection config not found in cache with key '{PROMPT_INJECTION_DETECTION_CONFIG_CACHE_KEY}'. Cache may be empty or expired.")
                return None

            # Handle bytes response (Redis returns bytes when decode_responses=False)
            if isinstance(config_json, bytes):
                config_json = config_json.decode('utf-8')
                logger.debug(f"Decoded bytes response from cache to string (length: {len(config_json)})")

            # Check if the data is already a dictionary
            if isinstance(config_json, dict):
                return config_json
            else:
                config = json.loads(config_json)
                logger.debug("Successfully retrieved prompt_injection_detection_config from cache.")
                return config
        except json.JSONDecodeError as jde:
            logger.error(f"Failed to parse prompt_injection_detection_config from cache (JSONDecodeError) for key '{PROMPT_INJECTION_DETECTION_CONFIG_CACHE_KEY}': {jde}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error retrieving or parsing prompt_injection_detection_config from cache for key '{PROMPT_INJECTION_DETECTION_CONFIG_CACHE_KEY}': {e}", exc_info=True)
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

    async def get_most_used_apps_cached(
        self,
        directus_service,
        limit: int = 20,
        cache_ttl: int = 3600  # 1 hour
    ) -> list:
        """
        Get most used apps from cache, or fetch from Directus if cache miss.
        
        This method provides a cached view of the most used apps in the last 30 days.
        Cache is refreshed every hour to keep data current while reducing database load.
        
        Args:
            directus_service: DirectusService instance for fetching from database
            limit: Maximum number of apps to return (default 20)
            cache_ttl: Cache TTL in seconds (default 1 hour)
        
        Returns:
            List of dicts with app_id and usage_count, sorted by count descending
        """
        try:
            # Try cache first
            cached_data = await self.get(MOST_USED_APPS_CACHE_KEY)
            if cached_data:
                try:
                    # Parse cached data
                    if isinstance(cached_data, str):
                        data = json.loads(cached_data)
                    else:
                        data = cached_data
                    
                    # Ensure it's a list
                    if isinstance(data, list):
                        logger.debug(f"Returning most used apps from cache: {len(data)} apps")
                        return data[:limit]  # Respect limit even for cached data
                    else:
                        logger.warning(f"Cached most used apps data is not a list: {type(data)}")
                except json.JSONDecodeError as e:
                    logger.warning(f"Error parsing cached most used apps: {e}")
                except Exception as e:
                    logger.warning(f"Error processing cached most used apps: {e}")
            
            # Cache miss - fetch from Directus
            logger.info("Cache miss for most used apps, fetching from Directus")
            apps = await directus_service.analytics.get_most_used_apps_last_30_days(limit=limit)
            
            # Cache the result
            if apps:
                try:
                    await self.set(MOST_USED_APPS_CACHE_KEY, json.dumps(apps), ttl=cache_ttl)
                    logger.debug(f"Cached most used apps for {cache_ttl} seconds")
                except Exception as e:
                    logger.warning(f"Failed to cache most used apps: {e}")
            
            return apps
            
        except Exception as e:
            logger.error(f"Error in get_most_used_apps_cached: {e}", exc_info=True)
            return []

# Optional: Instantiate a global cache service instance if your application uses one.
# cache_service = CacheService()
# logger.info("Global CacheService instance created.")
