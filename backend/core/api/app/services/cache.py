import os
import json
import logging
import redis
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
        
    @property
    def client(self) -> Optional[redis.Redis]:
        """Get Redis client, creating it if needed"""
        if self._client is None and not self._connection_error:
            try:
                # Create with more resilient settings
                self._client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    password=self.DRAGONFLY_PASSWORD,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30,  # Periodically check connection
                    decode_responses=False     # Raw bytes for compatibility with Celery
                )
                # Test connection with verbose logging
                pong = self._client.ping()
                logger.info(f"Successfully connected to cache at {self.host}:{self.port} (PING={pong})")
                
                # Show Redis info for debugging
                try:
                    info = self._client.info()
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
            if not self.client:
                logger.debug(f"Cache GET skipped for key '{key}': client not connected.")
                return None
                
            logger.debug(f"Cache GET for key: '{key}'")
            value = self.client.get(key)
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
            if not self.client:
                logger.debug(f"Cache SET skipped for key '{key}': client not connected.")
                return False
                
            serialized = json.dumps(value)
            logger.debug(f"Cache SET for key: '{key}', TTL: {ttl}s")
            result = self.client.setex(key, ttl, serialized)
            logger.debug(f"Cache SET result for key '{key}': {result}")
            return result
        except Exception as e:
            logger.error(f"Cache SET error for key '{key}': {str(e)}")
            return False
            
    async def delete(self, key: str) -> bool:
        """Delete a value from cache"""
        try:
            if not self.client:
                logger.debug(f"Cache DELETE skipped for key '{key}': client not connected.")
                return False
                
            logger.debug(f"Cache DELETE for key: '{key}'")
            result = bool(self.client.delete(key))
            logger.debug(f"Cache DELETE result for key '{key}': {result}")
            return result
        except Exception as e:
            logger.error(f"Cache DELETE error for key '{key}': {str(e)}")
            return False
            
    async def get_keys_by_pattern(self, pattern: str) -> list:
        """Get all keys matching a pattern"""
        try:
            if not self.client:
                return []
                
            keys = self.client.keys(pattern)
            return [key.decode('utf-8') if isinstance(key, bytes) else key for key in keys]
        except Exception as e:
            logger.error(f"Cache get_keys_by_pattern error for pattern {pattern}: {str(e)}")
            return []
            
    async def clear(self, prefix: str = "") -> bool:
        """Clear all cached values with optional prefix"""
        try:
            if not self.client:
                return False
                
            if prefix:
                keys = self.client.keys(f"{prefix}*")
                if keys:
                    return bool(self.client.delete(*keys))
                return True
            else:
                return bool(self.client.flushdb())
        except Exception as e:
            logger.error(f"Cache clear error: {str(e)}")
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

    # --- Draft-specific caching methods ---

    def _get_draft_key(self, user_id: str, chat_id: str, draft_id: str) -> str:
        """Generate a consistent cache key for a draft."""
        return f"draft:{user_id}:{chat_id}:{draft_id}"

    async def get_draft_with_version(self, user_id: str, chat_id: str, draft_id: str) -> Optional[Dict]:
        """
        Get draft content and its version from cache.
        Returns a dictionary like {'content': '...', 'version': 1} or None if not found.
        """
        try:
            cache_key = self._get_draft_key(user_id, chat_id, draft_id)
            logger.debug(f"Getting draft from cache: {cache_key}")
            draft_data = await self.get(cache_key) # self.get already handles JSON parsing
            if draft_data and isinstance(draft_data, dict) and 'content' in draft_data and 'version' in draft_data:
                return draft_data
            elif draft_data:
                 logger.warning(f"Found draft data for {cache_key}, but format is unexpected: {type(draft_data)}")
                 # Attempt backward compatibility if it was stored as just content string before versioning
                 if isinstance(draft_data, str):
                     logger.info(f"Found old format draft for {cache_key}. Returning with version 0.")
                     return {"content": draft_data, "version": 0} # Assign version 0 to old drafts
                 return None # Invalid format
            else:
                return None # Not found
        except Exception as e:
            logger.error(f"Error getting draft {draft_id} for chat {chat_id} from cache: {str(e)}")
            return None

    async def update_draft_content(self, user_id: str, chat_id: str, draft_id: str, content: str, expected_version: Optional[int], ttl: int = 86400 * 7) -> Union[int, bool]:
        """
        Atomically update draft content in cache if the expected version matches.
        Uses Redis WATCH/MULTI/EXEC for atomic check-and-set.

        Args:
            user_id: User ID.
            chat_id: Chat ID.
            draft_id: Draft ID.
            content: New draft content.
            expected_version: The version the client based the update on.
                              If None, creates the draft (version 1) if it doesn't exist.
                              If 0, creates the draft (version 1) or updates if current version is 0.
            ttl: Time-to-live in seconds (default 7 days).

        Returns:
            - The new version number (int) if the update was successful.
            - False (bool) if the version check failed (conflict) or another error occurred.
            - True (bool) if creating a new draft with expected_version=None succeeded (returns new version 1 implicitly).
        """
        if not self.client:
            logger.error("Cannot update draft: Cache client not connected.")
            return False

        cache_key = self._get_draft_key(user_id, chat_id, draft_id)
        new_version = 1 # Default for creation

        try:
            # Use a pipeline for WATCH/MULTI/EXEC
            async with self.client.pipeline(transaction=True) as pipe:
                await pipe.watch(cache_key) # Watch the key for changes

                # Get current value within the transaction
                current_value_bytes = await pipe.get(cache_key)
                current_data = None
                current_version = 0 # Default if key doesn't exist

                if current_value_bytes:
                    try:
                        current_data = json.loads(current_value_bytes)
                        if isinstance(current_data, dict) and 'version' in current_data:
                            current_version = current_data.get('version', 0)
                        elif isinstance(current_data, str): # Handle old format
                            current_version = 0 # Treat old string format as version 0
                        else:
                             logger.warning(f"Unexpected data format in cache for {cache_key}: {type(current_data)}. Treating as version 0.")
                             current_version = 0
                    except json.JSONDecodeError:
                        logger.warning(f"Could not decode JSON for {cache_key}. Treating as version 0.")
                        current_version = 0 # Treat as version 0 if decode fails

                logger.debug(f"Update draft check: Key={cache_key}, Expected={expected_version}, Current={current_version}")

                # --- Version Check Logic ---
                if expected_version is None: # Intent: Create if not exists
                    if current_data is not None:
                        logger.warning(f"Draft creation requested for {cache_key}, but it already exists (Version: {current_version}). Update rejected.")
                        await pipe.unwatch()
                        return False # Conflict: Already exists when creation was intended
                    # Proceed to create with version 1
                    new_version = 1
                elif expected_version == 0: # Intent: Create or update from version 0
                    if current_data is None:
                        new_version = 1 # Create with version 1
                    elif current_version == 0:
                        new_version = 1 # Update from version 0 to 1
                    else:
                        logger.warning(f"Draft update conflict for {cache_key}. Expected version 0, but found {current_version}.")
                        await pipe.unwatch()
                        return False # Conflict: Expected 0, found something else
                else: # Intent: Update based on a specific version
                    if current_version != expected_version:
                        logger.warning(f"Draft update conflict for {cache_key}. Expected version {expected_version}, but found {current_version}.")
                        await pipe.unwatch()
                        return False # Conflict: Versions don't match
                    # Proceed to update, incrementing version
                    new_version = current_version + 1

                # --- Perform Update ---
                pipe.multi() # Start transaction block
                new_data = {"content": content, "version": new_version}
                pipe.setex(cache_key, ttl, json.dumps(new_data))

                # Execute the transaction
                results = await pipe.execute()
                logger.debug(f"Pipeline execution results for {cache_key}: {results}")

                # Check results: execute() returns a list of results for commands in MULTI.
                # If the transaction failed due to WATCH, it raises WatchError or returns None list.
                if results is None or not all(results): # Check if execute failed or any command within failed
                    logger.warning(f"Draft update failed for {cache_key}, likely due to a concurrent modification (WATCH error).")
                    return False # Transaction aborted

                logger.info(f"Successfully updated draft {cache_key} to version {new_version}")
                return new_version # Success, return the new version

        except redis.exceptions.WatchError:
            logger.warning(f"WatchError during draft update for {cache_key}. Concurrent modification detected.")
            return False # Conflict detected by WATCH
        except Exception as e:
            logger.error(f"Error updating draft {cache_key}: {str(e)}", exc_info=True)
            return False # Other error

    async def delete_draft(self, user_id: str, chat_id: str, draft_id: str) -> bool:
        """Delete a draft from cache."""
        try:
            cache_key = self._get_draft_key(user_id, chat_id, draft_id)
            logger.debug(f"Deleting draft from cache: {cache_key}")
            return await self.delete(cache_key)
        except Exception as e:
            logger.error(f"Error deleting draft {draft_id} for chat {chat_id} from cache: {str(e)}")
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