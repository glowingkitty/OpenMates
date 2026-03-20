# backend/core/api/app/services/cache_short_url_mixin.py
#
# Redis storage for ephemeral short URL encrypted blobs.
# Part of the zero-knowledge short URL sharing system.
# The server stores opaque encrypted blobs it cannot decrypt — the decryption
# key lives only in the URL fragment, never sent to the server.
#
# Architecture reference: /docs/architecture/short_url_sharing.md

import logging
from typing import Optional

from . import cache_config

logger = logging.getLogger(__name__)


class ShortUrlCacheMixin:
    """Mixin for short URL ephemeral storage in Redis/Dragonfly."""

    async def store_short_url(self, token: str, encrypted_url: str, ttl_seconds: int) -> bool:
        """
        Store an encrypted short URL blob in cache.

        Args:
            token: The lookup token (8 base62 chars, sent to server).
            encrypted_url: The AES-GCM encrypted share URL blob (opaque to server).
            ttl_seconds: Time-to-live in seconds (clamped to MIN_TTL..MAX_TTL).

        Returns:
            True if stored successfully, False otherwise.
        """
        # Clamp TTL to allowed range
        ttl = max(
            cache_config.SHORT_URL_MIN_TTL,
            min(ttl_seconds, cache_config.SHORT_URL_MAX_TTL),
        )

        key = f"{cache_config.SHORT_URL_KEY_PREFIX}{token}"
        try:
            result = await self.set(key, encrypted_url, ttl=ttl)
            if result:
                logger.info(f"Stored short URL token={token} (TTL={ttl}s)")
            else:
                logger.error(f"Failed to store short URL token={token}")
            return bool(result)
        except Exception as e:
            logger.error(f"Error storing short URL token={token}: {e}", exc_info=True)
            return False

    async def resolve_short_url(self, token: str) -> Optional[str]:
        """
        Retrieve an encrypted short URL blob from cache.

        Args:
            token: The lookup token.

        Returns:
            The encrypted URL blob string, or None if expired/not found.
        """
        key = f"{cache_config.SHORT_URL_KEY_PREFIX}{token}"
        try:
            value = await self.get(key)
            if value is None:
                logger.debug(f"Short URL token={token} not found (expired or never created)")
                return None
            # The base get() auto-deserializes JSON; encrypted_url is stored as a string
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            logger.debug(f"Resolved short URL token={token}")
            return str(value)
        except Exception as e:
            logger.error(f"Error resolving short URL token={token}: {e}", exc_info=True)
            return None

    async def increment_resolve_count(self, token: str) -> int:
        """
        Increment and return the resolve counter for a token.
        The counter key has the same TTL as the short URL key.

        Args:
            token: The lookup token.

        Returns:
            The new resolve count, or -1 on error.
        """
        counter_key = f"{cache_config.SHORT_URL_RESOLVES_KEY_PREFIX}{token}"
        try:
            client = await self.client
            if not client:
                logger.error(f"Redis client not available for resolve count increment: token={token}")
                return -1

            count = await client.incr(counter_key)

            # On first increment, set TTL to match the short URL key's remaining TTL
            if count == 1:
                url_key = f"{cache_config.SHORT_URL_KEY_PREFIX}{token}"
                remaining_ttl = await client.ttl(url_key)
                if remaining_ttl > 0:
                    await client.expire(counter_key, remaining_ttl)
                else:
                    # URL key already expired; set a short fallback TTL
                    await client.expire(counter_key, cache_config.SHORT_URL_MAX_TTL)

            logger.debug(f"Short URL resolve count for token={token}: {count}")
            return int(count)
        except Exception as e:
            logger.error(f"Error incrementing resolve count for token={token}: {e}", exc_info=True)
            return -1

    async def get_resolve_count(self, token: str) -> int:
        """
        Get the current resolve count for a token.

        Returns:
            The resolve count, or 0 if not found/error.
        """
        counter_key = f"{cache_config.SHORT_URL_RESOLVES_KEY_PREFIX}{token}"
        try:
            value = await self.get(counter_key)
            if value is None:
                return 0
            return int(value)
        except Exception as e:
            logger.error(f"Error getting resolve count for token={token}: {e}", exc_info=True)
            return 0
