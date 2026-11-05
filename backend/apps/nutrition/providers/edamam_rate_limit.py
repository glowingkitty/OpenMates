# backend/apps/nutrition/providers/edamam_rate_limit.py
#
# Cross-worker request spacing for Edamam Recipe Search v2.
#
# Edamam enforces a small per-minute request window (see rate_limits in
# backend/providers/edamam.yml). Parallel recipe searches therefore
# used to burst past the window, so all but the first request failed with HTTP
# 429 (issue 4VXWM). Every Edamam HTTP call now reserves a slot in the shared
# cache first; slots are spaced 60 / requests_per_minute seconds apart across
# all API and worker processes.

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

EDAMAM_SLOT_KEY = "provider_slot:edamam:recipes_v2"
DEFAULT_REQUESTS_PER_MINUTE = 4
MIN_POLL_SECONDS = 0.05


def configured_min_interval_seconds() -> float:
    """Return the request spacing from backend/providers/edamam.yml."""
    from backend.core.api.app.utils.config_manager import ConfigManager

    config = ConfigManager().get_provider_config("edamam") or {}
    rate_limits = config.get("rate_limits") or {}
    requests_per_minute = rate_limits.get("requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE)
    if not isinstance(requests_per_minute, (int, float)) or requests_per_minute <= 0:
        raise ValueError(f"Invalid Edamam rate_limits.requests_per_minute: {requests_per_minute!r}")
    return 60.0 / float(requests_per_minute)


async def acquire_request_slot(
    cache_client: Any,
    *,
    min_interval_seconds: float,
    max_wait_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bool:
    """Wait for the next free Edamam request slot.

    The slot is a cache key that lives for ``min_interval_seconds``; whoever
    creates it may send one request. Returns False when no slot frees up within
    ``max_wait_seconds`` so callers can stop instead of provoking a 429.
    """
    deadline = clock() + max_wait_seconds
    token = uuid.uuid4().hex
    interval_ms = max(1, int(min_interval_seconds * 1000))
    while True:
        if await cache_client.set(EDAMAM_SLOT_KEY, token, nx=True, px=interval_ms):
            return True
        remaining_ms = await cache_client.pttl(EDAMAM_SLOT_KEY)
        wait_seconds = max(MIN_POLL_SECONDS, (remaining_ms if remaining_ms and remaining_ms > 0 else 0) / 1000)
        if clock() + wait_seconds > deadline:
            return False
        await sleep(wait_seconds)


async def resolve_cache_client(cache_service: Optional[Any]) -> Any:
    """Return the shared cache client used for slot reservations."""
    if cache_service is None:
        from backend.core.api.app.services.cache import CacheService

        cache_service = CacheService()
    client = await cache_service.client
    if client is None:
        raise RuntimeError("Edamam request spacing requires the shared cache")
    return client
