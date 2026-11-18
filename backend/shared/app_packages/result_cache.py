"""Short-lived cache of installed provider results.

The same search (same package version, provider, target skill and contract input)
is answered from the shared cache for ``result_cache_seconds()`` (default 15 minutes,
``OPENMATES_APP_PACKAGES_RESULT_CACHE_SECONDS``; 0 turns the cache off) instead of running
the provider again, so repeated and follow-up questions do not send new requests
to the provider's upstream. Secrets are never part of the key, and only
successful outcomes are stored; a cache miss or an unreachable cache simply runs
the provider (the provider is the source of truth).

Architecture: docs/architecture/apps/instance-app-packages.md ("Result cache").
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Mapping, Optional

from backend.shared.app_packages.loader import InstalledProvider

logger = logging.getLogger(__name__)

DEFAULT_RESULT_CACHE_SECONDS = 15 * 60
RESULT_CACHE_ENV = "OPENMATES_APP_PACKAGES_RESULT_CACHE_SECONDS"
RESULT_CACHE_PREFIX = "app_packages:results:v1:"


def result_cache_seconds() -> int:
    """Cache lifetime in seconds; 0 (or a negative or invalid value) turns caching off."""
    raw = os.getenv(RESULT_CACHE_ENV, "").strip()
    if not raw:
        return DEFAULT_RESULT_CACHE_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("[AppPackages] %s is not a whole number of seconds; result cache is off", RESULT_CACHE_ENV)
        return 0


def result_cache_key(provider: InstalledProvider, input_item: Mapping[str, Any]) -> str:
    """Cache key of one provider run; the input is hashed, never stored in the key."""
    identity = {
        "package": provider.package_id, "version": provider.package_version, "provider": provider.provider_id,
        "app": provider.app_id, "skill": provider.skill_id, "input": input_item,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return RESULT_CACHE_PREFIX + digest


async def cached_results(key: str) -> Optional[List[Dict[str, Any]]]:
    """Results stored for ``key``, or None on a miss (or when the cache is off or unreachable)."""
    if result_cache_seconds() <= 0:
        return None
    from backend.core.api.app.services.cache import CacheService

    cache = CacheService()
    try:
        value = await cache.get(key)
    finally:
        await cache.close()
    if isinstance(value, list) and all(isinstance(result, dict) for result in value):
        return value
    return None


async def store_results(key: str, results: List[Dict[str, Any]]) -> None:
    """Store a successful provider outcome; failures to store only cost a later provider run."""
    seconds = result_cache_seconds()
    if seconds <= 0:
        return
    from backend.core.api.app.services.cache import CacheService

    cache = CacheService()
    try:
        stored = await cache.set(key, results, ttl=seconds)
    finally:
        await cache.close()
    if not stored:
        logger.info("[AppPackages] Provider results were not cached")
