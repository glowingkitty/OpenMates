import os
import json
import logging
import asyncio # Add asyncio for CancelledError
import redis.asyncio as redis
from redis import exceptions as redis_exceptions # Import exceptions from the main redis library
from typing import Any, Optional, List

# Import constants from the new config file
from . import cache_config

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)  # Set to DEBUG for detailed logging, adjust as needed

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

        logger.debug(f"CacheService initialized with host: {self.host}, port: {self.port}")

        # Initialize constants from cache_config
        self.DEFAULT_TTL = cache_config.DEFAULT_TTL
        self.USER_TTL = cache_config.USER_TTL
        self.SESSION_TTL = cache_config.SESSION_TTL
        self.USER_DEVICE_TTL = cache_config.USER_DEVICE_TTL
        self.USER_KEY_PREFIX = cache_config.USER_KEY_PREFIX
        self.SESSION_KEY_PREFIX = cache_config.SESSION_KEY_PREFIX
        self.USER_DEVICE_KEY_PREFIX = cache_config.USER_DEVICE_KEY_PREFIX
        self.USER_DEVICE_LIST_KEY_PREFIX = cache_config.USER_DEVICE_LIST_KEY_PREFIX
        self.ORDER_KEY_PREFIX = cache_config.ORDER_KEY_PREFIX
        # self.USER_APP_MEMORY_KEY_PREFIX = cache_config.USER_APP_MEMORY_KEY_PREFIX # Old, removed
        # self.USER_APP_SETTINGS_KEY_PREFIX = cache_config.USER_APP_SETTINGS_KEY_PREFIX # Old, removed
        self.USER_APP_SETTINGS_AND_MEMORIES_KEY_PREFIX = cache_config.USER_APP_SETTINGS_AND_MEMORIES_KEY_PREFIX # New combined prefix
        self.CHAT_LIST_META_KEY_PREFIX = cache_config.CHAT_LIST_META_KEY_PREFIX
        self.USER_ACTIVE_CHATS_LRU_PREFIX = cache_config.USER_ACTIVE_CHATS_LRU_PREFIX
        self.USER_CHATS_SET_PREFIX = cache_config.USER_CHATS_SET_PREFIX
        self.CHAT_LIST_TTL = cache_config.CHAT_LIST_TTL
        self.CHAT_METADATA_TTL = cache_config.CHAT_METADATA_TTL
        self.USER_CHATS_SET_TTL = cache_config.USER_CHATS_SET_TTL
        self.CHAT_IDS_VERSIONS_TTL = cache_config.CHAT_IDS_VERSIONS_TTL
        self.CHAT_VERSIONS_TTL = cache_config.CHAT_VERSIONS_TTL
        self.CHAT_LIST_ITEM_DATA_TTL = cache_config.CHAT_LIST_ITEM_DATA_TTL
        self.USER_DRAFT_TTL = cache_config.USER_DRAFT_TTL
        self.CHAT_MESSAGES_TTL = cache_config.CHAT_MESSAGES_TTL
        self.USER_APP_DATA_TTL = cache_config.USER_APP_DATA_TTL # Added
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
                logger.debug(f"Successfully connected to async cache at {self.host}:{self.port} (PING={pong})")
                try:
                    info = await self._client.info()
                    logger.debug(f"Cache server: {info.get('redis_version', 'unknown')}, "
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
                except (json.JSONDecodeError, TypeError, ValueError):
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
            
            # Serialize dicts and lists with json.dumps
            if isinstance(value, (dict, list)):
                serialized_value = json.dumps(value)
            # Convert booleans to strings
            elif isinstance(value, bool):
                serialized_value = str(value).lower()  # 'true' or 'false'
            # Handle other primitive types
            elif not isinstance(value, (str, bytes, int, float)):
                serialized_value = str(value)  # Convert any other types to string
            else:
                serialized_value = value  # Already a string, bytes, int, or float

            logger.debug(f"Cache SET for key: '{key}', TTL: {final_ttl}s")
            result = await client.setex(key, final_ttl, serialized_value)
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
                logger.debug("Cache CLEAR skipped: client not connected.")
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

    async def publish_event(self, channel: str, event_data: dict) -> bool:
        """Publish an event to a Redis channel."""
        try:
            client = await self.client
            if not client:
                logger.warning(f"Cache PUBLISH skipped for channel '{channel}': client not connected.")
                return False
            
            message = json.dumps(event_data)
            logger.debug(f"Publishing to channel '{channel}': {message}")
            await client.publish(channel, message)
            return True
        except Exception as e:
            logger.error(f"Cache PUBLISH error for channel '{channel}': {str(e)}")
            return False

    async def subscribe_to_channel(self, channel_pattern: str):
        """Subscribe to a Redis channel pattern and yield messages."""
        client = await self.client
        if not client:
            logger.error(f"Cannot subscribe to channel pattern '{channel_pattern}': client not connected.")
            return

        pubsub = client.pubsub()
        await pubsub.psubscribe(channel_pattern)
        logger.debug(f"Subscribed to Redis channel pattern: {channel_pattern}")
        
        try:
            while True:
                # CRITICAL: Use shorter timeout (0.1s) for faster message processing
                # This ensures chunks are forwarded immediately without delay
                # The timeout is only for periodic checks, messages return immediately when available
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if message and message.get("type") == "pmessage": # pmessage for psubscribe
                    channel = message.get("channel")
                    if isinstance(channel, bytes):
                        channel = channel.decode('utf-8')
                    
                    data = message.get("data")
                    if isinstance(data, bytes):
                        data = data.decode('utf-8')
                    
                    logger.debug(f"Received message from Redis channel '{channel}': {data}")
                    try:
                        parsed_data = json.loads(data)
                        payload_to_yield = {"channel": channel, "data": parsed_data}
                        yield payload_to_yield
                    except json.JSONDecodeError as e_json:
                        logger.error(f"Failed to parse JSON from message on channel '{channel}': {data}. Error: {e_json}", exc_info=True)
                        # Optionally yield an error message
                        yield {"channel": channel, "data": data, "error": "json_decode_error"}
                        
                elif message:
                    logger.debug(f"Received other type of message on pubsub: {message}")
        except asyncio.CancelledError:
            logger.debug(f"Redis PubSub listener for pattern '{channel_pattern}' was cancelled.")
            raise # Re-raise for the main lifespan handler to catch
        except redis_exceptions.ConnectionError as e:
            logger.error(f"Redis PubSub connection error for pattern '{channel_pattern}': {e}", exc_info=True)
            # Potentially attempt to re-subscribe or handle error
        except Exception as e:
            logger.error(f"Error in Redis PubSub listener for pattern '{channel_pattern}': {e}", exc_info=True)
        finally:
            logger.debug(f"Unsubscribing from Redis channel pattern: {channel_pattern}")
            if pubsub:
                try:
                    await pubsub.punsubscribe(channel_pattern)
                    await pubsub.close() # Ensure the pubsub connection is closed
                except Exception as e_close:
                    logger.error(f"Error during pubsub close/unsubscribe for '{channel_pattern}': {e_close}")

    async def execute_pipeline_operations(self, operations: List[tuple]) -> bool:
        """
        Execute multiple cache operations in a Redis pipeline for better performance.

        Args:
            operations: List of tuples (method_name, *args) representing cache operations

        Returns:
            bool: True if all operations succeeded, False otherwise
        """
        try:
            client = await self.client
            if not client:
                logger.warning("Redis pipeline skipped: client not connected")
                return False

            # Create a pipeline
            pipe = client.pipeline()

            logger.debug(f"Executing {len(operations)} operations in Redis pipeline")

            for operation in operations:
                method_name = operation[0]
                args = operation[1:]

                # Map operation names to Redis commands based on cache service methods
                if method_name == 'add_chat_to_ids_versions':
                    # This is a sorted set operation: ZADD
                    user_id, chat_id, timestamp = args
                    key = f"{self.USER_CHATS_SET_PREFIX}:{user_id}"
                    pipe.zadd(key, {chat_id: timestamp})

                elif method_name == 'set_chat_versions':
                    # This stores JSON data: HSET
                    user_id, chat_id, versions = args
                    key = f"chat_versions:{user_id}:{chat_id}"
                    pipe.hset(key, mapping={
                        "messages_v": versions.messages_v,
                        "title_v": versions.title_v
                    })

                elif method_name == 'set_chat_version_component':
                    # This stores a single field: HSET
                    user_id, chat_id, component_key, version = args
                    key = f"chat_versions:{user_id}:{chat_id}"
                    pipe.hset(key, component_key, version)

                elif method_name == 'set_chat_list_item' or method_name == 'set_chat_list_item_data':
                    # This stores JSON data: SET
                    user_id, chat_id, list_item = args
                    key = f"chat_list:{user_id}:{chat_id}"
                    pipe.set(key, json.dumps(list_item.model_dump()) if hasattr(list_item, 'model_dump') else json.dumps(list_item.__dict__))

                elif method_name == 'update_user_draft_in_cache':
                    # This stores draft data: HSET
                    user_id, chat_id, content, version = args
                    key = f"user_draft:{user_id}:{chat_id}"
                    pipe.hset(key, mapping={
                        "content": content or "",
                        "version": version
                    })

                else:
                    logger.warning(f"Unknown pipeline operation: {method_name}")
                    continue

            # Execute the pipeline
            results = await pipe.execute()

            # Check if all operations succeeded
            success_count = sum(1 for result in results if result)
            total_operations = len(operations)

            if success_count == total_operations:
                logger.debug(f"Redis pipeline completed successfully: {success_count}/{total_operations} operations")
                return True
            else:
                logger.warning(f"Redis pipeline partial success: {success_count}/{total_operations} operations succeeded")
                return False

        except Exception as e:
            logger.error(f"Redis pipeline execution error: {str(e)}", exc_info=True)
            return False
