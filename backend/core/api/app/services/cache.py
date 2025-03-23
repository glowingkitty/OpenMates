import os
import json
import logging
import redis
from typing import Any, Optional, Union, Dict

logger = logging.getLogger(__name__)

class CacheService:
    """Service for caching data using Dragonfly (Redis-compatible)"""
    
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
