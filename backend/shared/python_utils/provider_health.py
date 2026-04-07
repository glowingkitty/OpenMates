# backend/shared/python_utils/provider_health.py
# Shared utilities for provider health status and provider name mapping.
# Used by the app store endpoint and AI preprocessor to gate skill availability
# based on cached health check results from Redis.

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Must match the prefix used in health_check_tasks.py (line 116)
HEALTH_CHECK_CACHE_KEY_PREFIX = "health_check:provider:"


async def is_provider_healthy(provider_id: str, cache_service: Any) -> bool:
    """
    Check if a provider is healthy based on cached health check data in Redis.

    Reads the health status from the background Celery health check task.
    Follows a fail-open policy: if no health data exists (fresh start, TTL expired,
    or health check task not running), the provider is considered healthy to avoid
    blocking skills unnecessarily.

    Args:
        provider_id: Provider ID (e.g., "protonmail", "brave", "youtube")
        cache_service: CacheService instance with a .client property for Redis access

    Returns:
        True if the provider is healthy or if no health data is available (fail-open).
        False only if the cached status is explicitly "unhealthy".
    """
    if not cache_service:
        return True  # Fail-open: no cache service available

    try:
        client = await cache_service.client
        if not client:
            return True  # Fail-open: no Redis client

        cache_key = f"{HEALTH_CHECK_CACHE_KEY_PREFIX}{provider_id}"
        raw = await client.get(cache_key)
        if not raw:
            return True  # Fail-open: no health data yet

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        health_data = json.loads(raw)
        status = health_data.get("status", "")

        if status == "unhealthy":
            logger.debug(
                f"Provider '{provider_id}' is unhealthy (last_error: {health_data.get('last_error', 'unknown')})"
            )
            return False

        return True  # "healthy", "degraded", or any other status → available

    except Exception as e:
        logger.debug(f"Error checking health for provider '{provider_id}': {e}")
        return True  # Fail-open on errors


def map_provider_name_to_id(provider_name: str, app_id: str) -> str:
    """
    Map provider name from app.yml to provider ID (provider YAML filename).

    This is the canonical location for this mapping. Previously duplicated in
    apps.py and apps_api.py — both now import from here.

    Args:
        provider_name: Provider name from app.yml (e.g., "Brave", "Google", "Firecrawl")
        app_id: App ID for context (e.g., "maps" for Google Maps)

    Returns:
        Provider ID (lowercase, matches provider YAML filename)
    """
    # Handle special cases
    if provider_name == "Google" and app_id == "maps":
        return "google_maps"
    elif provider_name == "YouTube":
        return "youtube"
    elif provider_name == "Brave" or provider_name == "Brave Search":
        return "brave"
    # Most providers just need to be lowercased
    return provider_name.lower().strip()
