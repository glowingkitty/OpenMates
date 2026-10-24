"""Coordinate HTTP attempts using the actual limit of each Brave credential.

Plan presets cannot describe every legacy key. Learn the provider's limit and
reserve evenly spaced slots in Redis across endpoints, processes and retries.
Only credential digests enter cache keys; no search content is stored here.
"""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import logging
import math
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)
LEARNED_LIMIT_TTL_SECONDS = 3600
MAX_QUEUE_WAIT_MS = 30_000
WINDOW_WITH_MARGIN_MS = 1100

RESERVE_SLOT = """
local interval = tonumber(redis.call('GET', KEYS[1]) or '0')
if interval <= 0 then return 0 end
local wait = math.max(0, redis.call('PTTL', KEYS[2]))
if wait > tonumber(ARGV[1]) then return -1 end
redis.call('SET', KEYS[2], '1', 'PX', wait + interval)
return wait
"""

LEARN_LIMIT = """
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3])
local remaining = redis.call('PTTL', KEYS[2])
if remaining < tonumber(ARGV[2]) then
  redis.call('SET', KEYS[2], '1', 'PX', ARGV[2])
end
return 1
"""


def _requests_per_second(response: httpx.Response) -> float | None:
    """Read Brave's per-second header, falling back to RATE_LIMITED metadata."""
    value: Any = response.headers.get("X-RateLimit-Limit", "").split(",")[0].strip()
    if not value and response.status_code == 429:
        try:
            body = response.json()
        except ValueError:
            return None
        error = body.get("error") if isinstance(body, dict) else None
        if not isinstance(error, dict) or error.get("code") != "RATE_LIMITED":
            return None
        meta = error.get("meta")
        value = meta.get("rate_limit") if isinstance(meta, dict) else None
    if isinstance(value, bool):
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate if math.isfinite(rate) and 0 < rate <= 10_000 else None


class BraveRateGate:
    """Reserve bounded shared slots without spending an HTTP retry while waiting."""

    def __init__(self, client: Any) -> None:
        self.client = client

    @staticmethod
    def _keys(headers: dict[str, str]) -> tuple[str, str]:
        token = headers.get("X-Subscription-Token") or headers.get("x-subscription-token", "")
        digest = hashlib.sha256(token.encode()).hexdigest()
        prefix = f"brave:rate:{{{digest}}}"
        return f"{prefix}:interval", f"{prefix}:queue"

    async def wait(self, headers: dict[str, str]) -> None:
        """Reserve one future slot atomically, with at most 30 seconds of queueing."""
        if self.client is None:
            return
        try:
            wait_ms = int(await self.client.eval(
                RESERVE_SLOT, 2, *self._keys(headers), MAX_QUEUE_WAIT_MS,
            ))
        except Exception:
            logger.warning("Brave shared rate admission unavailable; retaining bounded HTTP retries", exc_info=True)
            return
        if wait_ms < 0:
            raise httpx.TimeoutException("Brave shared request queue is temporarily full")
        if wait_ms:
            await asyncio.sleep(wait_ms / 1000)

    async def observe(self, headers: dict[str, str], response: httpx.Response, retry_after: float = 0) -> None:
        """Remember a credential's actual rate and preserve existing queued slots."""
        rate = _requests_per_second(response)
        if self.client is None or rate is None:
            return
        interval_ms = math.ceil(WINDOW_WITH_MARGIN_MS / rate)
        cooldown_ms = max(interval_ms, math.ceil(retry_after * 1000))
        try:
            await self.client.eval(
                LEARN_LIMIT, 2, *self._keys(headers), interval_ms,
                cooldown_ms, LEARNED_LIMIT_TTL_SECONDS,
            )
        except Exception:
            logger.warning("Brave provider rate could not be shared; retaining bounded HTTP retries", exc_info=True)


@asynccontextmanager
async def brave_rate_gate() -> AsyncIterator[BraveRateGate]:
    """Own and close this request's loop-bound cache connection."""
    from backend.core.api.app.services.cache import CacheService

    cache = CacheService()
    try:
        yield BraveRateGate(await cache.client)
    finally:
        await cache.close()
