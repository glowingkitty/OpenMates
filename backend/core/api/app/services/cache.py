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
                self._client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    socket_timeout=2,
                    socket_connect_timeout=2,
                    retry_on_timeout=True
                )
                # Test connection
                self._client.ping()
                logger.info("Successfully connected to Dragonfly cache")
            except Exception as e:
                logger.warning(f"Failed to connect to Dragonfly cache: {str(e)}")
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
                return json.loads(value)
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
