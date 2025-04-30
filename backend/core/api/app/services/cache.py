import os
import json
import logging
import redis.asyncio as redis # Use asyncio client
import hashlib
import time
from typing import Any, Optional, Union, Dict, List

logger = logging.getLogger(__name__)

class CacheService:
    """Service for caching data using Dragonfly (Redis-compatible)"""
    
    # Default TTL values (in seconds)
    DEFAULT_TTL = 3600  # 1 hour
    USER_TTL = 86400    # 24 hours
    SESSION_TTL = 86400 # 24 hours
    CHAT_LIST_TTL = 3600 # 1 hour, adjust as needed
    
    # Cache key prefixes
    USER_KEY_PREFIX = "user_profile:"
    SESSION_KEY_PREFIX = "session:"
    USER_DEVICE_KEY_PREFIX = "user_device:"
    USER_DEVICE_LIST_KEY_PREFIX = "user_device_list:" # Added for consistency
    ORDER_KEY_PREFIX = "order_status:"
    CHAT_LIST_META_KEY_PREFIX = "chat_list_meta:"
# LRU key for tracking last 3 active chats per user
    USER_ACTIVE_CHATS_LRU_PREFIX = "user_active_chats_lru:"
    USER_CHATS_SET_PREFIX = "user_chats:" # <-- New prefix for user chat sets
    CHAT_METADATA_TTL = 1800  # 30 minutes (TTL for individual metadata)
    USER_CHATS_SET_TTL = 86400 # 24 hours (TTL for the set itself, longer lived)
    DRAFT_TTL = 1800  # 30 minutes

    async def update_user_active_chats_lru(self, user_id: str, chat_id: str):
        """
        Update the LRU list of last 3 active chats for a user.
        """
        try:
            client = await self.client
            if not client:
                return False
            lru_key = f"{self.USER_ACTIVE_CHATS_LRU_PREFIX}{user_id}"
            # Remove chat_id if it exists, then push to the left (most recent)
            await client.lrem(lru_key, 0, chat_id)
            await client.lpush(lru_key, chat_id)
            # Trim to last 3
            await client.ltrim(lru_key, 0, 2)
            # Set TTL for the LRU list as well
            await client.expire(lru_key, self.CHAT_METADATA_TTL)
            return True
        except Exception as e:
            logger.error(f"Error updating LRU for user {user_id}: {e}")
            return False

    async def get_user_active_chats_lru(self, user_id: str) -> list:
        """
        Get the list of last 3 active chat IDs for a user.
        """
        try:
            client = await self.client
            if not client:
                return []
            lru_key = f"{self.USER_ACTIVE_CHATS_LRU_PREFIX}{user_id}"
            chat_ids = await client.lrange(lru_key, 0, 2)
            return [cid.decode('utf-8') if isinstance(cid, bytes) else cid for cid in chat_ids]
        except Exception as e:
            logger.error(f"Error fetching LRU for user {user_id}: {e}")
            return []

    async def set_chat_metadata(self, chat_id: str, metadata: dict):
        """
        Set chat metadata with correct TTL and update LRU for the user.
        """
        try:
            user_id = metadata.get("hashed_user_id")
            key = f"chat:{chat_id}:metadata"
            set_meta_success = await self.set(key, metadata, ttl=self.CHAT_METADATA_TTL)
            if set_meta_success and user_id:
                # Also add chat_id to the user's set
                await self.add_chat_to_user_set(user_id, chat_id)
                # Update LRU as before
                await self.update_user_active_chats_lru(user_id, chat_id)
            return set_meta_success # Return success of setting metadata
        except Exception as e:
            logger.error(f"Error setting chat metadata for chat {chat_id}: {e}")
            return False

    # Removed obsolete set_draft method (drafts are now part of chat metadata)
    # async def set_draft(self, user_id: str, chat_id: str, draft_id: str, draft_data: dict): ...

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
        
    # Make property async to allow await for ping
    @property
    async def client(self) -> Optional[redis.Redis]: # Type hint updated implicitly by import change
        """Get async Redis client, creating it if needed"""
        if self._client is None and not self._connection_error:
            try:
                # Create async client
                self._client = redis.Redis( # Now refers to redis.asyncio.Redis
                    host=self.host,
                    port=self.port,
                    password=self.DRAGONFLY_PASSWORD,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30,  # Periodically check connection
                    decode_responses=False     # Raw bytes for compatibility with Celery
                )
                # Test connection with await
                pong = await self._client.ping() # Use await for async ping
                logger.info(f"Successfully connected to async cache at {self.host}:{self.port} (PING={pong})")

                # Show Redis info for debugging (Note: info() might also need await if used elsewhere)
                try:
                    info = await self._client.info() # Await the async info() call
                    logger.info(f"Cache server: {info.get('redis_version', 'unknown')}, "
                               f"clients: {info.get('connected_clients', 'unknown')}")
                except:
                    logger.warning("Could not get Redis info")
                    
            except Exception as e:
                logger.warning(f"Failed to connect to cache at {self.host}:{self.port}: {str(e)}")
                self._connection_error = True
                self._client = None
                
        return self._client
        
    async def get(self, key: str) -> Any:
        """Get a value from cache"""
        try:
            # Get the client instance by awaiting the async property
            client = await self.client
            if not client:
                logger.debug(f"Cache GET skipped for key '{key}': client not connected.")
                return None

            logger.debug(f"Cache GET for key: '{key}'")
            # Use the obtained client instance and await the async operation
            value = await client.get(key)
            if value:
                logger.debug(f"Cache HIT for key: '{key}'")
                try:
                    return json.loads(value)
                except:
                    # Return raw value if not JSON
                    return value.decode('utf-8') if isinstance(value, bytes) else value
            logger.debug(f"Cache MISS for key: '{key}'")
            return None
        except Exception as e:
            logger.error(f"Cache GET error for key '{key}': {str(e)}")
            return None
            
    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Set a value in cache with TTL in seconds (default 1 hour)"""
        try:
            # Get the client instance by awaiting the async property
            client = await self.client
            if not client:
                logger.debug(f"Cache SET skipped for key '{key}': client not connected.")
                return False

            serialized = json.dumps(value)
            logger.debug(f"Cache SET for key: '{key}', TTL: {ttl}s")
            # Use the obtained client instance and await the async operation
            result = await client.setex(key, ttl, serialized)
            logger.debug(f"Cache SET result for key '{key}': {result}")
            return result # setex returns bool
        except Exception as e:
            logger.error(f"Cache SET error for key '{key}': {str(e)}")
            return False
            
    async def delete(self, key: str) -> bool:
        """Delete a value from cache"""
        try:
            # Get the client instance by awaiting the async property
            client = await self.client
            if not client:
                logger.debug(f"Cache DELETE skipped for key '{key}': client not connected.")
                return False

            logger.debug(f"Cache DELETE for key: '{key}'")
            # Use the obtained client instance and await the async operation
            # delete returns the number of keys deleted (int)
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
            client = await self.client # Await the client property
            if not client:
                logger.debug(f"Cache get_keys_by_pattern skipped for pattern '{pattern}': client not connected.")
                return []

            logger.debug(f"Cache KEYS for pattern: '{pattern}'")
            # Use the obtained client instance and await the async operation
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
            client = await self.client # Await the client property
            if not client:
                logger.debug(f"Cache CLEAR skipped: client not connected.")
                return False

            if prefix:
                logger.debug(f"Cache CLEAR for prefix: '{prefix}*'")
                # Use the obtained client instance and await the async operation
                keys = await client.keys(f"{prefix}*")
                if keys:
                    logger.debug(f"Found {len(keys)} keys with prefix '{prefix}' to delete.")
                    # Use the obtained client instance and await the async operation
                    num_deleted = await client.delete(*keys)
                    result = bool(num_deleted > 0)
                    logger.debug(f"Cache CLEAR result for prefix '{prefix}': {result} ({num_deleted} deleted)")
                    return result
                else:
                    logger.debug(f"No keys found with prefix '{prefix}'. Clear successful (no-op).")
                    return True # No keys to delete is considered success
            else:
                logger.debug("Cache CLEAR for all keys (FLUSHDB)")
                # Use the obtained client instance and await the async operation
                result = await client.flushdb()
                logger.debug(f"Cache CLEAR (FLUSHDB) result: {result}")
                return bool(result) # flushdb usually returns True on success
        except Exception as e:
            logger.error(f"Cache clear error (prefix='{prefix}'): {str(e)}")
            return False
    
    # User-specific caching methods
    
    async def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user data from cache by user ID"""
        try:
            cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            logger.debug(f"Attempting cache GET for user ID: {user_id} (Key: '{cache_key}')")
            return await self.get(cache_key)
        except Exception as e:
            logger.error(f"Error getting user from cache by ID '{user_id}': {str(e)}")
            return None
    
    async def get_user_by_token(self, refresh_token: str) -> Optional[Dict]:
        """Get user data from cache by refresh token.
        Looks up user_id by token hash, then fetches user data by user_id."""
        try:
            if not refresh_token:
                logger.debug("Attempted cache GET by token: No token provided.")
                return None

            # Generate token hash for cache key
            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            session_cache_key = f"{self.SESSION_KEY_PREFIX}{token_hash}"
            logger.debug(f"Attempting cache GET for user_id by token hash: {token_hash[:8]}... (Key: '{session_cache_key}')")

            # Get the user_id associated with this token hash
            user_id_data = await self.get(session_cache_key) # Should return {"user_id": "some_id"} or just "some_id"

            user_id = None
            if isinstance(user_id_data, dict):
                user_id = user_id_data.get("user_id")
            elif isinstance(user_id_data, str): # Handle case where we stored only the string ID
                 user_id = user_id_data

            if not user_id:
                logger.debug(f"Cache MISS for user_id associated with token hash {token_hash[:8]}...")
                return None

            logger.debug(f"Cache HIT for user_id '{user_id}' associated with token hash {token_hash[:8]}...")
            # Now get the actual user data using the user_id
            return await self.get_user_by_id(user_id)
        except Exception as e:
            logger.error(f"Error getting user from cache by token hash {token_hash[:8]}...: {str(e)}")
            return None
    
    async def set_user(self, user_data: Dict, user_id: str = None, refresh_token: str = None, ttl: int = None) -> bool:
        """
        Cache user data by user_id and optionally associate a refresh token with the user_id.

        Args:
            user_data: Dictionary containing user data to cache under user_id key.
            user_id: User ID (optional if included in user_data).
            refresh_token: Refresh token to associate with the user_id (optional).
                           If provided, a separate cache entry {session_prefix}:{token_hash} -> {user_id} is created.
            ttl: Time-to-live in seconds for both user data and session link (defaults to USER_TTL/SESSION_TTL).

        Returns:
            bool: Success status (True if user data caching succeeded).
        """
        try:
            if not user_data:
                logger.warning("Attempted to cache empty user data.")
                return False

            # Use provided user_id or extract from user_data
            user_id = user_id or user_data.get("user_id") or user_data.get("id")
            if not user_id:
                logger.error("Cannot cache user data: no user_id provided or found in user_data.")
                return False

            logger.debug(f"Attempting cache SET for user ID: {user_id}")
            # Set TTLs
            user_ttl = ttl or self.USER_TTL
            session_ttl = ttl or self.SESSION_TTL # Use separate TTL for session link

            # 1. Cache the full user data by user ID
            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            user_set_success = await self.set(user_cache_key, user_data, ttl=user_ttl)
            logger.debug(f"Cache SET result for user key '{user_cache_key}': {user_set_success}")

            # 2. If refresh token provided, cache the user_id lookup by token hash
            session_set_success = True # Default to True if no token provided
            if refresh_token:
                logger.debug(f"Attempting cache SET for session token link to user ID: {user_id}")
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                session_cache_key = f"{self.SESSION_KEY_PREFIX}{token_hash}"

                # Store only the user_id (or a small dict containing it) for the session link
                session_link_data = {"user_id": user_id} # Store as dict for potential future expansion
                # Alternatively, store just the string: session_link_data = user_id

                session_set_success = await self.set(session_cache_key, session_link_data, ttl=session_ttl)
                logger.debug(f"Cache SET result for session link key '{session_cache_key}': {session_set_success}")

            # Return True only if the main user data caching succeeded
            return user_set_success
        except Exception as e:
            logger.error(f"Error caching user data for user '{user_id}': {str(e)}")
            return False
    
    async def update_user(self, user_id: str, updated_fields: Dict) -> bool:
        """
        Update specific fields of cached user data (stored by user_id).
        Session link entries are not affected as they only store the user_id.

        Args:
            user_id: User ID.
            updated_fields: Dictionary of fields to update.

        Returns:
            bool: Success status.
        """
        try:
            if not user_id or not updated_fields:
                logger.warning("Update user cache skipped: missing user_id or updated_fields.")
                return False

            # Get current user data
            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            logger.debug(f"Attempting cache UPDATE for user ID: {user_id} (Key: '{user_cache_key}')")
            current_data = await self.get(user_cache_key)

            if not current_data or not isinstance(current_data, dict):
                logger.warning(f"Cannot update user cache: no existing data found or data is not a dict for user '{user_id}' (Key: '{user_cache_key}')")
                return False

            # Update fields
            logger.debug(f"Updating fields for user '{user_id}': {list(updated_fields.keys())}")
            current_data.update(updated_fields)

            # Save updated data (use existing TTL or default USER_TTL)
            # Note: Redis SETEX updates TTL, SET does not. We use SETEX via self.set.
            user_update_success = await self.set(user_cache_key, current_data, ttl=self.USER_TTL)
            logger.debug(f"Cache SET result for user key '{user_cache_key}' after update: {user_update_success}")

            # No need to update session entries anymore as they only link to user_id

            return user_update_success
        except Exception as e:
            logger.error(f"Error updating cached user data for user '{user_id}': {str(e)}")
            return False
    
    async def delete_user_cache(self, user_id: str) -> bool:
        """
        Remove user from cache (all related entries)
        
        Args:
            user_id: User ID
            
        Returns:
            bool: Success status
        """
        try:
            if not user_id:
                return False
                
            logger.debug(f"Attempting cache DELETE for all data related to user ID: {user_id}")
            
            # Delete user data
            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            delete_user_success = await self.delete(user_cache_key)
            logger.debug(f"Cache DELETE result for user key '{user_cache_key}': {delete_user_success}")
            
            # Delete any device entries
            device_pattern = f"{self.USER_DEVICE_KEY_PREFIX}{user_id}:*"
            logger.debug(f"Searching for device keys with pattern: '{device_pattern}'")
            device_keys = await self.get_keys_by_pattern(device_pattern)
            logger.debug(f"Found {len(device_keys)} device keys to delete.")
            devices_deleted_count = 0
            for key in device_keys:
                delete_device_success = await self.delete(key)
                if delete_device_success:
                    devices_deleted_count += 1
                logger.debug(f"Cache DELETE result for device key '{key}': {delete_device_success}")
            logger.debug(f"Finished deleting device caches for user {user_id}. Deleted {devices_deleted_count} keys.")
            
            # Delete any session entries for this user
            session_pattern = f"{self.SESSION_KEY_PREFIX}*"
            logger.debug(f"Searching for session keys with pattern: '{session_pattern}'")
            session_keys = await self.get_keys_by_pattern(session_pattern)
            logger.debug(f"Found {len(session_keys)} potential session keys to check.")
            sessions_deleted_count = 0
            for key in session_keys:
                # Retrieve the session link data (should contain user_id)
                session_link_data = await self.get(key)
                linked_user_id = None
                if isinstance(session_link_data, dict):
                    linked_user_id = session_link_data.get("user_id")
                elif isinstance(session_link_data, str): # Handle case where we stored only the string ID
                    linked_user_id = session_link_data

                # Check if this session link belongs to the user being deleted
                if linked_user_id == user_id:
                    logger.debug(f"Deleting session link cache for key '{key}' (User: {user_id})")
                    delete_session_success = await self.delete(key)
                    if delete_session_success:
                        sessions_deleted_count += 1
                    logger.debug(f"Cache DELETE result for session link key '{key}': {delete_session_success}")
            logger.debug(f"Finished deleting session link caches for user {user_id}. Deleted {sessions_deleted_count} keys.")

            # Return True if the main user cache deletion was successful
            return delete_user_success
        except Exception as e:
            logger.error(f"Error deleting cached user data for user '{user_id}': {str(e)}")
            return False

    # --- Chat Set Management Methods ---

    async def add_chat_to_user_set(self, hashed_user_id: str, chat_id: str) -> bool:
        """Adds a chat ID to the set of chats belonging to a user."""
        try:
            client = await self.client
            if not client: return False
            set_key = f"{self.USER_CHATS_SET_PREFIX}{hashed_user_id}"
            logger.debug(f"Adding chat '{chat_id}' to user set '{set_key}'")
            # SADD returns number of elements added (1 if new, 0 if exists)
            added = await client.sadd(set_key, chat_id)
            # Set/update TTL for the set key itself
            await client.expire(set_key, self.USER_CHATS_SET_TTL)
            return True # Consider success even if element already existed
        except Exception as e:
            logger.error(f"Error adding chat '{chat_id}' to user set for user '{hashed_user_id}': {e}")
            return False

    async def remove_chat_from_user_set(self, hashed_user_id: str, chat_id: str) -> bool:
        """Removes a chat ID from the set of chats belonging to a user."""
        try:
            client = await self.client
            if not client: return False
            set_key = f"{self.USER_CHATS_SET_PREFIX}{hashed_user_id}"
            logger.debug(f"Removing chat '{chat_id}' from user set '{set_key}'")
            # SREM returns number of elements removed (1 if removed, 0 if not found)
            removed = await client.srem(set_key, chat_id)
            return removed > 0
        except Exception as e:
            logger.error(f"Error removing chat '{chat_id}' from user set for user '{hashed_user_id}': {e}")
            return False

    async def get_chat_ids_for_user(self, hashed_user_id: str) -> List[str]:
        """Gets all chat IDs from the set belonging to a user."""
        try:
            client = await self.client
            if not client: return []
            set_key = f"{self.USER_CHATS_SET_PREFIX}{hashed_user_id}"
            logger.debug(f"Fetching chat IDs from user set '{set_key}'")
            # SMEMBERS returns a set of bytes
            chat_ids_bytes = await client.smembers(set_key)
            chat_ids = [cid.decode('utf-8') for cid in chat_ids_bytes]
            logger.debug(f"Found {len(chat_ids)} chat IDs for user '{hashed_user_id}' in set '{set_key}'")
            return chat_ids
        except Exception as e:
            logger.error(f"Error getting chat IDs from user set for user '{hashed_user_id}': {e}")
            return []

    # --- Order-specific caching methods ---

    async def set_order(self, order_id: str, user_id: str, credits_amount: int, status: str = "created", ttl: int = 86400) -> bool:
        """
        Cache order metadata and status.
        Args:
            order_id: The payment order ID
            user_id: The user who created the order
            credits_amount: The amount of credits to be awarded
            status: Order status ("created", "completed", "failed", etc.)
            ttl: Time-to-live in seconds (default 24h)
        """
        try:
            if not order_id or not user_id or credits_amount is None:
                logger.error("Cannot cache order: missing order_id, user_id, or credits_amount.")
                return False
            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            order_data = {
                "order_id": order_id,
                "user_id": user_id,
                "credits_amount": credits_amount,
                "status": status,
                "timestamp": int(time.time())
            }
            logger.debug(f"Setting order in cache: {order_data}")
            return await self.set(order_cache_key, order_data, ttl=ttl)
        except Exception as e:
            logger.error(f"Error caching order {order_id}: {str(e)}")
            return False

    async def get_order(self, order_id: str) -> Optional[Dict]:
        """
        Get order metadata and status from cache.
        """
        try:
            if not order_id:
                return None
            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            logger.debug(f"Getting order from cache: {order_id}")
            return await self.get(order_cache_key)
        except Exception as e:
            logger.error(f"Error getting order {order_id} from cache: {str(e)}")
            return None

    async def update_order_status(self, order_id: str, status: str) -> bool:
        """
        Update the status of an order in cache.
        """
        try:
            if not order_id or not status:
                return False
            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            order_data = await self.get(order_cache_key)
            if not order_data:
                logger.warning(f"Cannot update order status: no existing data for order {order_id}")
                return False
            order_data["status"] = status
            logger.debug(f"Updating order {order_id} status to {status}")
            return await self.set(order_cache_key, order_data, ttl=86400)
        except Exception as e:
            logger.error(f"Error updating order {order_id} status in cache: {str(e)}")
            return False

    async def update_order(self, order_id: str, updated_fields: Dict) -> bool:
        """
        Update arbitrary fields of an order in cache.
        """
        try:
            if not order_id or not updated_fields:
                return False
            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            order_data = await self.get(order_cache_key)
            if not order_data:
                logger.warning(f"Cannot update order: no existing data for order {order_id}")
                return False
            order_data.update(updated_fields)
            logger.debug(f"Updating order {order_id} with fields {updated_fields}")
            return await self.set(order_cache_key, order_data, ttl=86400)
        except Exception as e:
            logger.error(f"Error updating order {order_id} in cache: {str(e)}")
            return False

    async def has_pending_orders(self, user_id: str) -> bool:
        """
        Check if a user has any orders in cache that are not in a final state (completed/failed).
        """
        try:
            if not self.client or not user_id:
                return False

            order_pattern = f"{self.ORDER_KEY_PREFIX}*"
            logger.debug(f"Searching for order keys with pattern: '{order_pattern}' for user {user_id}")
            order_keys = await self.get_keys_by_pattern(order_pattern)
            logger.debug(f"Found {len(order_keys)} potential order keys to check for user {user_id}.")

            final_statuses = {"completed", "failed"} # Define final states

            for key in order_keys:
                order_data = await self.get(key)
                if isinstance(order_data, dict):
                    order_user_id = order_data.get("user_id")
                    order_status = order_data.get("status", "").lower()

                    # Check if this order belongs to the user and is NOT in a final state
                    if order_user_id == user_id and order_status not in final_statuses:
                        logger.info(f"User {user_id} has a pending order: {order_data.get('order_id')} (Status: {order_status})")
                        return True # Found a pending order

            logger.debug(f"No pending orders found in cache for user {user_id}.")
            return False # No pending orders found for this user
        except Exception as e:
            logger.error(f"Error checking for pending orders for user '{user_id}': {str(e)}")
            return False # Assume no pending orders on error to avoid blocking logout unnecessarily

    # --- New Draft Update Method (within Chat Metadata) ---
 
    async def update_chat_draft(self, chat_id: str, encrypted_draft: str, expected_version: int) -> Union[int, bool]:
        """
        Update the encrypted draft content within the chat metadata using optimistic locking.
 
        Args:
            chat_id: The ID of the chat.
            encrypted_draft: The new encrypted draft content (as a JSON string or similar).
            expected_version: The version the client expects the chat metadata to be based on.
 
        Returns:
            int: The new version number on successful update.
            bool: False if update failed due to version conflict or other error.
        """
        client = await self.client
        if not client:
            logger.warning(f"Cannot update chat draft for {chat_id}: Cache client not connected.")
            return False
 
        metadata_key = f"chat:{chat_id}:metadata"
 
        # Use WATCH/MULTI/EXEC for atomic check-and-set on the chat metadata key
        async with client.pipeline(transaction=True) as pipe:
            try:
                # Watch the metadata key for changes
                await pipe.watch(metadata_key)
 
                # Get current metadata value within the transaction
                current_metadata_bytes = await pipe.get(metadata_key)
                current_version = -1 # Use -1 to indicate not found or invalid
                current_metadata = {}
 
                if current_metadata_bytes:
                    try:
                        current_metadata = json.loads(current_metadata_bytes)
                        if isinstance(current_metadata, dict):
                              current_version = current_metadata.get('version', 0) # Default to 0 if version missing
                        else:
                              logger.error(f"Chat metadata for {metadata_key} is not a dict. Treating as conflict.")
                              await pipe.unwatch()
                              return False
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode JSON for chat metadata key {metadata_key}. Treating as conflict.")
                        await pipe.unwatch()
                        return False # Cannot proceed if metadata is corrupt
                    except Exception as e:
                          logger.error(f"Unexpected error reading chat metadata {metadata_key}: {e}. Treating as conflict.")
                          await pipe.unwatch()
                          return False
                else:
                      logger.warning(f"Chat metadata not found for key {metadata_key} during draft update attempt.")
                      await pipe.unwatch()
                      return False # Cannot update if metadata doesn't exist
 
                # Optimistic Lock Check
                if current_version != expected_version:
                    logger.warning(f"Chat metadata update conflict for {metadata_key}. Expected version {expected_version}, found {current_version}.")
                    await pipe.unwatch() # Important to unwatch before returning
                    return False # Version mismatch
 
                # Prepare updated metadata
                new_version = current_version + 1
                now_ts = int(time.time())
 
                # Create a copy to modify
                updated_metadata = current_metadata.copy()
                updated_metadata['encrypted_draft'] = encrypted_draft # Update the draft
                updated_metadata['version'] = new_version           # Increment version
                updated_metadata['updated_at'] = now_ts             # Update timestamp
 
                serialized_updated_metadata = json.dumps(updated_metadata)
 
                # Start MULTI command block
                pipe.multi()
 
                # Set the updated metadata with the existing TTL (or default CHAT_METADATA_TTL)
                # We need the TTL. Let's try getting it first, or use the default.
                # Note: Getting TTL within MULTI/EXEC might be complex or not supported directly.
                # A simpler approach is to just reset the TTL using the standard duration.
                pipe.setex(metadata_key, self.CHAT_METADATA_TTL, serialized_updated_metadata)
 
                # Execute the transaction
                results = await pipe.execute()
 
                # Check results
                if results and results[0] is True: # Check if setex command was successful
                    logger.info(f"Chat metadata for {chat_id} updated successfully (draft change) to version {new_version}.")
                    # Update LRU *after* successful update (user_id needed)
                    user_id = updated_metadata.get("hashed_user_id")
                    if user_id:
                          await self.update_user_active_chats_lru(user_id, chat_id)
                    else:
                          logger.warning(f"Could not update LRU for chat {chat_id} after draft update: missing hashed_user_id in metadata.")
                    return new_version
                else:
                    logger.warning(f"Chat metadata update conflict (WATCH error) for {metadata_key}. Expected version {expected_version}, key changed before EXEC.")
                    return False
 
            except redis.WatchError:
                logger.warning(f"Chat metadata update conflict (WatchError) for {metadata_key}. Expected version {expected_version}.")
                return False
            except Exception as e:
                logger.error(f"Error updating chat metadata {metadata_key}: {e}", exc_info=True)
                try: await pipe.unwatch()
                except: pass
                return False
 
    # --- Chat List Metadata Caching ---
    # Store chat list metadata (IDs, titles, timestamps) for quick retrieval

    def _get_chat_list_meta_key(self, user_id: str) -> str:
        """Generate the cache key for a user's chat list metadata."""
        return f"{self.CHAT_LIST_META_KEY_PREFIX}{user_id}"

    async def get_chat_list_metadata(self, user_id: str) -> Optional[List[Dict]]:
        """
        Get the cached list of chat metadata for a user.
        Expected format: [{'chat_id': '...', 'title': '...', 'updated_at': '...', ...}, ...]
        """
        try:
            cache_key = self._get_chat_list_meta_key(user_id)
            logger.debug(f"Getting chat list metadata from cache: {cache_key}")
            metadata = await self.get(cache_key) # self.get handles JSON parsing
            if isinstance(metadata, list):
                return metadata
            elif metadata is not None:
                 logger.warning(f"Unexpected format for chat list metadata in cache for key {cache_key}: {type(metadata)}")
                 return None
            else:
                return None # Not found
        except Exception as e:
            logger.error(f"Error getting chat list metadata for user {user_id} from cache: {str(e)}")
            return None

    async def set_chat_list_metadata(self, user_id: str, metadata_list: List[Dict], ttl: int = None) -> bool:
        """
        Set the entire list of chat metadata for a user in the cache.
        """
        try:
            cache_key = self._get_chat_list_meta_key(user_id)
            ttl_to_use = ttl if ttl is not None else self.CHAT_LIST_TTL
            logger.debug(f"Setting chat list metadata in cache for user {user_id} (Key: {cache_key}, TTL: {ttl_to_use}s)")
            if not isinstance(metadata_list, list):
                 logger.error(f"Invalid metadata_list type for user {user_id}: Expected list, got {type(metadata_list)}")
                 return False
            return await self.set(cache_key, metadata_list, ttl=ttl_to_use)
        except Exception as e:
            logger.error(f"Error setting chat list metadata for user {user_id} in cache: {str(e)}")
            return False

    async def delete_chat_list_metadata(self, user_id: str) -> bool:
        """
        Delete the cached chat list metadata for a user.
        """
        try:
            cache_key = self._get_chat_list_meta_key(user_id)
            logger.debug(f"Deleting chat list metadata from cache: {cache_key}")
            return await self.delete(cache_key)
        except Exception as e:
            logger.error(f"Error deleting chat list metadata for user {user_id} from cache: {str(e)}")
            return False

    # Note: Updating individual items within the list atomically in Redis is complex.
    # For simplicity, the current approach is to fetch the list, modify it in the application,
    # and then use set_chat_list_metadata to overwrite the entire list.
    # For high-concurrency scenarios, consider using Redis hashes or other structures,
    # or implementing optimistic locking at the application level when updating the list.