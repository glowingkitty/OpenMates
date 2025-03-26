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
    
    # Cache key prefixes
    USER_KEY_PREFIX = "user:"
    SESSION_KEY_PREFIX = "session:"
    USER_DEVICE_KEY_PREFIX = "user_device:"
    
    def __init__(self):
        """Initialize the cache service with configuration from environment variables"""
        self.redis_url = os.getenv("DRAGONFLY_URL", "cache:6379")
        self.redis_password = os.getenv("REDIS_PASSWORD", "openmates_cache")
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
                    password=self.redis_password,
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
        """Get user data from cache by refresh token"""
        try:
            if not refresh_token:
                logger.debug("Attempted cache GET by token: No token provided.")
                return None
                
            # Generate token hash for cache key
            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            cache_key = f"{self.SESSION_KEY_PREFIX}{token_hash}"
            logger.debug(f"Attempting cache GET by token hash: {token_hash[:8]}... (Key: '{cache_key}')")
            
            return await self.get(cache_key)
        except Exception as e:
            logger.error(f"Error getting user from cache by token hash {token_hash[:8]}...: {str(e)}")
            return None
    
    async def set_user(self, user_data: Dict, user_id: str = None, refresh_token: str = None, ttl: int = None) -> bool:
        """
        Cache user data with optional token association
        
        Args:
            user_data: Dictionary containing user data
            user_id: User ID (optional if included in user_data)
            refresh_token: Refresh token to associate with user (optional)
            ttl: Time-to-live in seconds (defaults to USER_TTL)
            
        Returns:
            bool: Success status
        """
        try:
            if not user_data:
                return False
                
            # Use provided user_id or extract from user_data
            user_id = user_id or user_data.get("user_id") or user_data.get("id")
            if not user_id:
                logger.error("Cannot cache user data: no user_id provided or found in user_data.")
                return False
                
            logger.debug(f"Attempting cache SET for user ID: {user_id}")
            # Set TTL to default if not provided
            ttl = ttl or self.USER_TTL
            
            # Cache by user ID
            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            user_set_success = await self.set(user_cache_key, user_data, ttl=ttl)
            logger.debug(f"Cache SET result for user key '{user_cache_key}': {user_set_success}")
            
            # If refresh token provided, also cache by token
            session_set_success = False
            if refresh_token:
                logger.debug(f"Attempting cache SET for session token associated with user ID: {user_id}")
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                session_cache_key = f"{self.SESSION_KEY_PREFIX}{token_hash}"
                
                # For session cache, ensure we have token expiry
                session_data = user_data.copy()
                if "token_expiry" not in session_data:
                    session_data["token_expiry"] = int(time.time()) + ttl
                    
                session_set_success = await self.set(session_cache_key, session_data, ttl=ttl)
                logger.debug(f"Cache SET result for session key '{session_cache_key}': {session_set_success}")
                
            # Return True if at least one cache operation succeeded
            return user_set_success or session_set_success
        except Exception as e:
            logger.error(f"Error caching user data for user '{user_id}': {str(e)}")
            return False
    
    async def update_user(self, user_id: str, updated_fields: Dict) -> bool:
        """
        Update specific fields of cached user data
        
        Args:
            user_id: User ID
            updated_fields: Dictionary of fields to update
            
        Returns:
            bool: Success status
        """
        try:
            if not user_id or not updated_fields:
                return False
                
            # Get current user data
            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            logger.debug(f"Attempting cache UPDATE for user ID: {user_id} (Key: '{user_cache_key}')")
            current_data = await self.get(user_cache_key)
            
            if not current_data:
                # Log as warning, consistent with previous behavior
                logger.warning(f"Cannot update user cache: no existing data found for user '{user_id}' (Key: '{user_cache_key}')")
                return False
                
            # Update fields
            logger.debug(f"Updating fields for user '{user_id}': {list(updated_fields.keys())}")
            current_data.update(updated_fields)
            
            # Save updated data
            user_update_success = await self.set(user_cache_key, current_data, ttl=self.USER_TTL)
            logger.debug(f"Cache SET result for user key '{user_cache_key}' after update: {user_update_success}")
            
            # Update any session entries for this user
            logger.debug(f"Searching for session keys associated with user ID: {user_id}")
            session_keys = await self.get_keys_by_pattern(f"{self.SESSION_KEY_PREFIX}*")
            logger.debug(f"Found {len(session_keys)} potential session keys to update.")
            sessions_updated_count = 0
            for key in session_keys:
                session_data = await self.get(key)
                session_data = await self.get(key)
                if session_data and (session_data.get("user_id") == user_id or session_data.get("id") == user_id):
                    logger.debug(f"Updating session cache for key '{key}' (User: {user_id})")
                    # Preserve token_expiry
                    token_expiry = session_data.get("token_expiry")
                    
                    # Update session data with new fields
                    session_data.update(updated_fields)
                    
                    # Restore token_expiry if it was overwritten
                    if token_expiry:
                        session_data["token_expiry"] = token_expiry
                        
                    session_update_success = await self.set(key, session_data, ttl=self.SESSION_TTL)
                    if session_update_success:
                        sessions_updated_count += 1
                    logger.debug(f"Cache SET result for session key '{key}' after update: {session_update_success}")
            
            logger.debug(f"Finished updating session caches for user {user_id}. Updated {sessions_updated_count} sessions.")
            # Return True if the main user cache update succeeded
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
                session_data = await self.get(key)
                if session_data and (session_data.get("user_id") == user_id or session_data.get("id") == user_id):
                    logger.debug(f"Deleting session cache for key '{key}' (User: {user_id})")
                    delete_session_success = await self.delete(key)
                    if delete_session_success:
                        sessions_deleted_count += 1
                    logger.debug(f"Cache DELETE result for session key '{key}': {delete_session_success}")
            logger.debug(f"Finished deleting session caches for user {user_id}. Deleted {sessions_deleted_count} keys.")
            
            # Return True if the main user cache deletion was successful
            return delete_user_success
        except Exception as e:
            logger.error(f"Error deleting cached user data for user '{user_id}': {str(e)}")
            return False