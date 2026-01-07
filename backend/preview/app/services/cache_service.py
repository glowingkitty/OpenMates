"""
Cache Service

Provides disk-based caching for images, favicons, and metadata.
Uses diskcache for efficient LRU eviction and persistence.

Key features:
- Separate caches for images, favicons, and metadata
- Automatic LRU eviction when size limits are reached
- TTL-based expiration
- Thread-safe operations
"""

import logging
import hashlib
import os
from typing import Optional

import diskcache

from ..config import settings

logger = logging.getLogger(__name__)


class CacheService:
    """
    Manages disk-based caching for the preview server.
    
    Uses separate caches for different content types to allow
    independent size limits and eviction policies.
    """
    
    def __init__(self):
        """Initialize cache service with separate caches for each content type."""
        # Ensure cache directory exists
        os.makedirs(settings.cache_dir, exist_ok=True)
        
        # Image cache (largest - 1GB default)
        self._image_cache = diskcache.Cache(
            directory=os.path.join(settings.cache_dir, "images"),
            size_limit=settings.cache_max_size_bytes,
            eviction_policy="least-recently-used"
        )
        
        # Favicon cache (shares image cache size limit but separate directory)
        self._favicon_cache = diskcache.Cache(
            directory=os.path.join(settings.cache_dir, "favicons"),
            size_limit=settings.cache_max_size_bytes // 10,  # 10% of image cache
            eviction_policy="least-recently-used"
        )
        
        # Metadata cache (smaller - 100MB default)
        self._metadata_cache = diskcache.Cache(
            directory=os.path.join(settings.cache_dir, "metadata"),
            size_limit=settings.metadata_cache_max_size_bytes,
            eviction_policy="least-recently-used"
        )
        
        logger.info(
            f"[CacheService] Initialized caches at {settings.cache_dir} "
            f"(images: {settings.cache_max_size_mb}MB, "
            f"metadata: {settings.metadata_cache_max_size_mb}MB)"
        )
    
    @staticmethod
    def _generate_key(url: str) -> str:
        """
        Generate a cache key from URL.
        
        Uses SHA256 hash to ensure consistent key length and avoid
        special characters that might cause filesystem issues.
        
        Args:
            url: The URL to generate a key for
            
        Returns:
            SHA256 hash of the URL as hex string
        """
        return hashlib.sha256(url.encode("utf-8")).hexdigest()
    
    # ===========================================
    # Image Cache Operations
    # ===========================================
    
    def get_image(self, url: str) -> Optional[tuple[bytes, str]]:
        """
        Get cached image data.
        
        Args:
            url: Original image URL
            
        Returns:
            Tuple of (image_bytes, content_type) or None if not cached
        """
        key = self._generate_key(url)
        try:
            cached = self._image_cache.get(key)
            if cached:
                logger.debug(f"[CacheService] Image cache HIT for {url[:50]}...")
                return cached
            logger.debug(f"[CacheService] Image cache MISS for {url[:50]}...")
            return None
        except Exception as e:
            logger.error(f"[CacheService] Error reading image cache: {e}")
            return None
    
    def set_image(
        self,
        url: str,
        data: bytes,
        content_type: str,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache image data.
        
        Args:
            url: Original image URL
            data: Image binary data
            content_type: MIME type of the image
            ttl: Time-to-live in seconds (uses default if not provided)
            
        Returns:
            True if cached successfully, False otherwise
        """
        key = self._generate_key(url)
        ttl = ttl or settings.image_cache_ttl_seconds
        
        try:
            self._image_cache.set(key, (data, content_type), expire=ttl)
            logger.debug(
                f"[CacheService] Cached image ({len(data)} bytes) for {url[:50]}... "
                f"TTL: {ttl}s"
            )
            return True
        except Exception as e:
            logger.error(f"[CacheService] Error caching image: {e}")
            return False
    
    # ===========================================
    # Favicon Cache Operations
    # ===========================================
    
    def get_favicon(self, url: str) -> Optional[tuple[bytes, str]]:
        """
        Get cached favicon data.
        
        Args:
            url: Website URL (not favicon URL)
            
        Returns:
            Tuple of (favicon_bytes, content_type) or None if not cached
        """
        key = self._generate_key(url)
        try:
            cached = self._favicon_cache.get(key)
            if cached:
                logger.debug(f"[CacheService] Favicon cache HIT for {url[:50]}...")
                return cached
            logger.debug(f"[CacheService] Favicon cache MISS for {url[:50]}...")
            return None
        except Exception as e:
            logger.error(f"[CacheService] Error reading favicon cache: {e}")
            return None
    
    def set_favicon(
        self,
        url: str,
        data: bytes,
        content_type: str,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache favicon data.
        
        Args:
            url: Website URL (not favicon URL)
            data: Favicon binary data
            content_type: MIME type of the favicon
            ttl: Time-to-live in seconds (uses default if not provided)
            
        Returns:
            True if cached successfully, False otherwise
        """
        key = self._generate_key(url)
        ttl = ttl or settings.favicon_cache_ttl_seconds
        
        try:
            self._favicon_cache.set(key, (data, content_type), expire=ttl)
            logger.debug(
                f"[CacheService] Cached favicon ({len(data)} bytes) for {url[:50]}... "
                f"TTL: {ttl}s"
            )
            return True
        except Exception as e:
            logger.error(f"[CacheService] Error caching favicon: {e}")
            return False
    
    # ===========================================
    # Metadata Cache Operations
    # ===========================================
    
    def get_metadata(self, url: str) -> Optional[dict]:
        """
        Get cached metadata.
        
        Args:
            url: Website URL
            
        Returns:
            Metadata dict or None if not cached
        """
        key = self._generate_key(url)
        try:
            cached = self._metadata_cache.get(key)
            if cached:
                logger.debug(f"[CacheService] Metadata cache HIT for {url[:50]}...")
                return cached
            logger.debug(f"[CacheService] Metadata cache MISS for {url[:50]}...")
            return None
        except Exception as e:
            logger.error(f"[CacheService] Error reading metadata cache: {e}")
            return None
    
    def set_metadata(
        self,
        url: str,
        metadata: dict,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache metadata.
        
        Args:
            url: Website URL
            metadata: Metadata dictionary
            ttl: Time-to-live in seconds (uses default if not provided)
            
        Returns:
            True if cached successfully, False otherwise
        """
        key = self._generate_key(url)
        ttl = ttl or settings.metadata_cache_ttl_seconds
        
        try:
            self._metadata_cache.set(key, metadata, expire=ttl)
            logger.debug(
                f"[CacheService] Cached metadata for {url[:50]}... TTL: {ttl}s"
            )
            return True
        except Exception as e:
            logger.error(f"[CacheService] Error caching metadata: {e}")
            return False
    
    # ===========================================
    # Cache Statistics
    # ===========================================
    
    def get_stats(self) -> dict:
        """
        Get cache statistics for monitoring.
        
        Returns:
            Dictionary with cache statistics
        """
        return {
            "images": {
                "size_bytes": self._image_cache.volume(),
                "count": len(self._image_cache),
                "size_limit_bytes": settings.cache_max_size_bytes
            },
            "favicons": {
                "size_bytes": self._favicon_cache.volume(),
                "count": len(self._favicon_cache),
                "size_limit_bytes": settings.cache_max_size_bytes // 10
            },
            "metadata": {
                "size_bytes": self._metadata_cache.volume(),
                "count": len(self._metadata_cache),
                "size_limit_bytes": settings.metadata_cache_max_size_bytes
            }
        }
    
    def clear_all(self) -> None:
        """Clear all caches. Use with caution!"""
        logger.warning("[CacheService] Clearing all caches!")
        self._image_cache.clear()
        self._favicon_cache.clear()
        self._metadata_cache.clear()
    
    def close(self) -> None:
        """Close all cache connections."""
        self._image_cache.close()
        self._favicon_cache.close()
        self._metadata_cache.close()
        logger.info("[CacheService] All caches closed")


# Global cache service instance (initialized on first import)
cache_service = CacheService()

