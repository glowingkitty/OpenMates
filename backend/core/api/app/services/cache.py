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
    USER_PROFILE_IMAGE_KEY_PREFIX = "user_profile_image:"
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
                return None
                
            value = self.client.get(key)
            if value:
                try:
                    return json.loads(value)
                except:
                    # Return raw value if not JSON
                    return value.decode('utf-8') if isinstance(value, bytes) else value
            return None
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {str(e)}")
            return None
            
    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Set a value in cache with TTL in seconds (default 1 hour)"""
        try:
            if not self.client:
                return False
                
            serialized = json.dumps(value)
            return self.client.setex(key, ttl, serialized)
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {str(e)}")
            return False
            
    async def delete(self, key: str) -> bool:
        """Delete a value from cache"""
        try:
            if not self.client:
                return False
                
            return bool(self.client.delete(key))
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {str(e)}")
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
            return await self.get(cache_key)
        except Exception as e:
            logger.error(f"Error getting user from cache by ID {user_id}: {str(e)}")
            return None
    
    async def get_user_by_token(self, refresh_token: str) -> Optional[Dict]:
        """Get user data from cache by refresh token"""
        try:
            if not refresh_token:
                return None
                
            # Generate token hash for cache key
            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            cache_key = f"{self.SESSION_KEY_PREFIX}{token_hash}"
            
            return await self.get(cache_key)
        except Exception as e:
            logger.error(f"Error getting user from cache by token: {str(e)}")
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
                logger.error("Cannot cache user data: no user_id provided or found in user_data")
                return False
                
            # Set TTL to default if not provided
            ttl = ttl or self.USER_TTL
            
            # Cache by user ID
            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            await self.set(user_cache_key, user_data, ttl=ttl)
            
            # If refresh token provided, also cache by token
            if refresh_token:
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                session_cache_key = f"{self.SESSION_KEY_PREFIX}{token_hash}"
                
                # For session cache, ensure we have token expiry
                session_data = user_data.copy()
                if "token_expiry" not in session_data:
                    session_data["token_expiry"] = int(time.time()) + ttl
                    
                await self.set(session_cache_key, session_data, ttl=ttl)
                
            return True
        except Exception as e:
            logger.error(f"Error caching user data for user {user_id}: {str(e)}")
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
            current_data = await self.get(user_cache_key)
            
            if not current_data:
                logger.warning(f"Cannot update user cache: no existing data for user {user_id}")
                return False
                
            # Update fields
            current_data.update(updated_fields)
            
            # Save updated data
            await self.set(user_cache_key, current_data, ttl=self.USER_TTL)
            
            # Update any session entries for this user
            session_keys = await self.get_keys_by_pattern(f"{self.SESSION_KEY_PREFIX}*")
            for key in session_keys:
                session_data = await self.get(key)
                if session_data and (session_data.get("user_id") == user_id or session_data.get("id") == user_id):
                    # Preserve token_expiry
                    token_expiry = session_data.get("token_expiry")
                    
                    # Update session data with new fields
                    session_data.update(updated_fields)
                    
                    # Restore token_expiry if it was overwritten
                    if token_expiry:
                        session_data["token_expiry"] = token_expiry
                        
                    await self.set(key, session_data, ttl=self.SESSION_TTL)
            
            return True
        except Exception as e:
            logger.error(f"Error updating cached user data for user {user_id}: {str(e)}")
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
                
            # Delete user data
            user_cache_key = f"{self.USER_KEY_PREFIX}{user_id}"
            await self.delete(user_cache_key)
            
            # Delete profile image
            profile_image_key = f"{self.USER_PROFILE_IMAGE_KEY_PREFIX}{user_id}"
            await self.delete(profile_image_key)
            
            # Delete any device entries
            device_keys = await self.get_keys_by_pattern(f"{self.USER_DEVICE_KEY_PREFIX}{user_id}:*")
            for key in device_keys:
                await self.delete(key)
            
            # Delete any session entries for this user
            session_keys = await self.get_keys_by_pattern(f"{self.SESSION_KEY_PREFIX}*")
            for key in session_keys:
                session_data = await self.get(key)
                if session_data and (session_data.get("user_id") == user_id or session_data.get("id") == user_id):
                    await self.delete(key)
            
            return True
        except Exception as e:
            logger.error(f"Error deleting cached user data for user {user_id}: {str(e)}")
            return False
    
    async def get_user_profile_image(self, user_id: str) -> Optional[str]:
        """Get user profile image URL from cache"""
        try:
            cache_key = f"{self.USER_PROFILE_IMAGE_KEY_PREFIX}{user_id}"
            return await self.get(cache_key)
        except Exception as e:
            logger.error(f"Error getting profile image from cache for user {user_id}: {str(e)}")
            return None
    
    async def set_user_profile_image(self, user_id: str, image_url: str) -> bool:
        """Cache user profile image URL"""
        try:
            if not user_id or not image_url:
                return False
                
            cache_key = f"{self.USER_PROFILE_IMAGE_KEY_PREFIX}{user_id}"
            success = await self.set(cache_key, image_url, ttl=self.USER_TTL)
            
            # Also update the profile_image_url in user cache
            await self.update_user(user_id, {"profile_image_url": image_url})
            
            return success
        except Exception as e:
            logger.error(f"Error caching profile image for user {user_id}: {str(e)}")
            return False