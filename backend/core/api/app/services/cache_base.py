import os
import json
import logging
import redis.asyncio as redis
from typing import Any, Optional

# Import constants from the new config file
from . import cache_config

logger = logging.getLogger(__name__)

class CacheServiceBase:
    """Base service for caching data using Dragonfly (Redis-compatible)"""

    def __init__(self):
        """Initialize the cache service with configuration from environment variables"""
        self.redis_url = os.getenv("DRAGONFLY_URL", "cache:6379")
        self.DRAGONFLY_PASSWORD = os.getenv("DRAGONFLY_PASSWORD", "openmates_cache")
        self._client = None
        self._connection_error = False

        # Extract host and port from DRAGONFLY_URL
        if "://" in self.redis_url:
            self.redis_url = self.redis_url.split("://")[1]

        parts = self.redis_url.split(":")
        self.host = parts[0]
        self.port = int(parts[1]) if len(parts) > 1 else 6379

        logger.info(f"CacheService initialized with host: {self.host}, port: {self.port}")

        # Initialize constants from cache_config
        self.DEFAULT_TTL = cache_config.DEFAULT_TTL
        self.USER_TTL = cache_config.USER_TTL
        self.SESSION_TTL = cache_config.SESSION_TTL
        self.USER_KEY_PREFIX = cache_config.USER_KEY_PREFIX
        self.SESSION_KEY_PREFIX = cache_config.SESSION_KEY_PREFIX
        self.USER_DEVICE_KEY_PREFIX = cache_config.USER_DEVICE_KEY_PREFIX
        self.USER_DEVICE_LIST_KEY_PREFIX = cache_config.USER_DEVICE_LIST_KEY_PREFIX
        self.ORDER_KEY_PREFIX = cache_config.ORDER_KEY_PREFIX
        self.CHAT_LIST_META_KEY_PREFIX = cache_config.CHAT_LIST_META_KEY_PREFIX
        self.USER_ACTIVE_CHATS_LRU_PREFIX = cache_config.USER_ACTIVE_CHATS_LRU_PREFIX
        self.USER_CHATS_SET_PREFIX = cache_config.USER_CHATS_SET_PREFIX
        self.CHAT_LIST_TTL = cache_config.CHAT_LIST_TTL
        self.CHAT_METADATA_TTL = cache_config.CHAT_METADATA_TTL
        self.USER_CHATS_SET_TTL = cache_config.USER_CHATS_SET_TTL
        self.DRAFT_TTL = cache_config.DRAFT_TTL
        self.CHAT_IDS_VERSIONS_TTL = cache_config.CHAT_IDS_VERSIONS_TTL
        self.CHAT_VERSIONS_TTL = cache_config.CHAT_VERSIONS_TTL
        self.CHAT_LIST_ITEM_DATA_TTL = cache_config.CHAT_LIST_ITEM_DATA_TTL
        self.CHAT_MESSAGES_TTL = cache_config.CHAT_MESSAGES_TTL
        self.TOP_N_MESSAGES_COUNT = cache_config.TOP_N_MESSAGES_COUNT


    @property
    async def client(self) -> Optional[redis.Redis]:
        """Get async Redis client, creating it if needed"""
        if self._client is None and not self._connection_error:
            try:
                self._client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    password=self.DRAGONFLY_PASSWORD,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30,
                    decode_responses=False
                )
                pong = await self._client.ping()
                logger.info(f"Successfully connected to async cache at {self.host}:{self.port} (PING={pong})")
                try:
                    info = await self._client.info()
                    logger.info(f"Cache server: {info.get('redis_version', 'unknown')}, "
                               f"clients: {info.get('connected_clients', 'unknown')}")
                except Exception:
                    logger.warning("Could not get Redis info")
            except Exception as e:
                logger.warning(f"Failed to connect to cache at {self.host}:{self.port}: {str(e)}")
                self._connection_error = True
                self._client = None
        return self._client

    async def get(self, key: str) -> Any:
        """Get a value from cache"""
        try:
            client = await self.client
            if not client:
                logger.debug(f"Cache GET skipped for key '{key}': client not connected.")
                return None

            logger.debug(f"Cache GET for key: '{key}'")
            value = await client.get(key)
            if value:
                logger.debug(f"Cache HIT for key: '{key}'")
                try:
                    return json.loads(value)
                except:
                    return value.decode('utf-8') if isinstance(value, bytes) else value
            logger.debug(f"Cache MISS for key: '{key}'")
            return None
        except Exception as e:
            logger.error(f"Cache GET error for key '{key}': {str(e)}")
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set a value in cache with TTL in seconds (default 1 hour or DEFAULT_TTL)"""
        try:
            client = await self.client
            if not client:
                logger.debug(f"Cache SET skipped for key '{key}': client not connected.")
                return False

            final_ttl = ttl if ttl is not None else self.DEFAULT_TTL
            serialized = json.dumps(value)
            logger.debug(f"Cache SET for key: '{key}', TTL: {final_ttl}s")
            result = await client.setex(key, final_ttl, serialized)
            logger.debug(f"Cache SET result for key '{key}': {result}")
            return result
        except Exception as e:
            logger.error(f"Cache SET error for key '{key}': {str(e)}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a value from cache"""
        try:
            client = await self.client
            if not client:
                logger.debug(f"Cache DELETE skipped for key '{key}': client not connected.")
                return False

            logger.debug(f"Cache DELETE for key: '{key}'")
            num_deleted = await client.delete(key)
            result = bool(num_deleted > 0)
            logger.debug(f"Cache DELETE result for key '{key}': {result} ({num_deleted} deleted)")
            return result
        except Exception as e:
            logger.error(f"Cache DELETE error for key '{key}': {str(e)}")
            return False

    async def get_keys_by_pattern(self, pattern: str) -> list:
        """Get all keys matching a pattern"""
        try:
            client = await self.client
            if not client:
                logger.debug(f"Cache get_keys_by_pattern skipped for pattern '{pattern}': client not connected.")
                return []

            logger.debug(f"Cache KEYS for pattern: '{pattern}'")
            keys = await client.keys(pattern)
            decoded_keys = [key.decode('utf-8') if isinstance(key, bytes) else key for key in keys]
            logger.debug(f"Cache KEYS result for pattern '{pattern}': Found {len(decoded_keys)} keys.")
            return decoded_keys
        except Exception as e:
            logger.error(f"Cache get_keys_by_pattern error for pattern {pattern}: {str(e)}")
            return []

    async def clear(self, prefix: str = "") -> bool:
        """Clear all cached values with optional prefix"""
        try:
            client = await self.client
            if not client:
                logger.debug(f"Cache CLEAR skipped: client not connected.")
                return False

            if prefix:
                logger.debug(f"Cache CLEAR for prefix: '{prefix}*'")
                keys = await client.keys(f"{prefix}*")
                if keys:
                    logger.debug(f"Found {len(keys)} keys with prefix '{prefix}' to delete.")
                    num_deleted = await client.delete(*keys)
                    result = bool(num_deleted > 0)
                    logger.debug(f"Cache CLEAR result for prefix '{prefix}': {result} ({num_deleted} deleted)")
                    return result
                else:
                    logger.debug(f"No keys found with prefix '{prefix}'. Clear successful (no-op).")
                    return True
            else:
                logger.debug("Cache CLEAR for all keys (FLUSHDB)")
                result = await client.flushdb()
                logger.debug(f"Cache CLEAR (FLUSHDB) result: {result}")
                return bool(result)
        except Exception as e:
            logger.error(f"Cache clear error (prefix='{prefix}'): {str(e)}")
            return False