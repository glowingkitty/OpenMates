"""
Cache Service

Provides disk-based caching for images, favicons, and metadata.

Key features:
- Separate caches for images, favicons, and metadata
- Automatic LRU eviction when size limits are reached
- TTL-based expiration
- Thread-safe operations
"""

import logging
import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


class _SqliteCache:
    """Persistent TTL cache with LRU eviction and no pickle deserialization."""

    def __init__(self, directory: str, size_limit: int):
        os.makedirs(directory, exist_ok=True)
        self._size_limit = size_limit
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            os.path.join(directory, "cache.sqlite3"),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                key TEXT PRIMARY KEY,
                value BLOB NOT NULL,
                content_type TEXT,
                expires_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                size_bytes INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_entries_updated_at ON cache_entries(updated_at)"
        )
        self._conn.commit()

    def get_binary(self, key: str) -> Optional[tuple[bytes, str]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, content_type, expires_at FROM cache_entries WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None

            value, content_type, expires_at = row
            if expires_at <= time.time():
                self._conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                self._conn.commit()
                return None

            self._touch(key)
            return bytes(value), content_type or "application/octet-stream"

    def set_binary(self, key: str, data: bytes, content_type: str, ttl: int) -> None:
        self._set(key, data, content_type, ttl)

    def get_json(self, key: str) -> Optional[dict]:
        cached = self.get_binary(key)
        if cached is None:
            return None
        data, _content_type = cached
        return json.loads(data.decode("utf-8"))

    def set_json(self, key: str, value: dict, ttl: int) -> None:
        self._set(
            key,
            json.dumps(value, separators=(",", ":")).encode("utf-8"),
            "application/json",
            ttl,
        )

    def volume(self) -> int:
        with self._lock:
            self._delete_expired()
            row = self._conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM cache_entries"
            ).fetchone()
            return int(row[0] if row else 0)

    def count(self) -> int:
        with self._lock:
            self._delete_expired()
            row = self._conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()
            return int(row[0] if row else 0)

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM cache_entries")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _set(self, key: str, data: bytes, content_type: str, ttl: int) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO cache_entries
                    (key, value, content_type, expires_at, updated_at, size_bytes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, data, content_type, now + ttl, now, len(data)),
            )
            self._evict_if_needed()
            self._conn.commit()

    def _touch(self, key: str) -> None:
        self._conn.execute(
            "UPDATE cache_entries SET updated_at = ? WHERE key = ?",
            (time.time(), key),
        )
        self._conn.commit()

    def _delete_expired(self) -> None:
        self._conn.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (time.time(),))
        self._conn.commit()

    def _evict_if_needed(self) -> None:
        self._delete_expired()
        while True:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM cache_entries"
            ).fetchone()
            total_size = int(row[0] if row else 0)
            if total_size <= self._size_limit:
                return

            oldest = self._conn.execute(
                "SELECT key FROM cache_entries ORDER BY updated_at ASC LIMIT 1"
            ).fetchone()
            if oldest is None:
                return
            self._conn.execute("DELETE FROM cache_entries WHERE key = ?", (oldest[0],))


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
        
        self._image_cache = _SqliteCache(
            os.path.join(settings.cache_dir, "images"),
            size_limit=settings.cache_max_size_bytes,
        )

        self._favicon_cache = _SqliteCache(
            os.path.join(settings.cache_dir, "favicons"),
            size_limit=settings.cache_max_size_bytes // 10,  # 10% of image cache
        )

        self._metadata_cache = _SqliteCache(
            os.path.join(settings.cache_dir, "metadata"),
            size_limit=settings.metadata_cache_max_size_bytes,
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
            cached = self._image_cache.get_binary(key)
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
            self._image_cache.set_binary(key, data, content_type, ttl)
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
            cached = self._favicon_cache.get_binary(key)
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
            self._favicon_cache.set_binary(key, data, content_type, ttl)
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
            cached = self._metadata_cache.get_json(key)
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
            self._metadata_cache.set_json(key, metadata, ttl)
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
                "count": self._image_cache.count(),
                "size_limit_bytes": settings.cache_max_size_bytes
            },
            "favicons": {
                "size_bytes": self._favicon_cache.volume(),
                "count": self._favicon_cache.count(),
                "size_limit_bytes": settings.cache_max_size_bytes // 10
            },
            "metadata": {
                "size_bytes": self._metadata_cache.volume(),
                "count": self._metadata_cache.count(),
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
