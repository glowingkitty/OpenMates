"""Atomic, fail-closed credit and rolling request limits for the shared API key.

Counts all outbound calls through the Geoapify wrapper, including failures.
Cached results cost nothing. Other applications using the same account outside
this wrapper are not counted; the default 2,500 cap leaves free-plan headroom.
"""

import asyncio
import hashlib
import inspect
import os
import uuid
from datetime import datetime, timezone
from typing import Any

# Redis TIME avoids rate windows depending on the clocks of different workers.
RESERVE_SCRIPT = """
local now = redis.call('TIME')
local ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
if spent + tonumber(ARGV[1]) > tonumber(ARGV[2]) then return {1, 0} end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ms - 1000)
if redis.call('ZCARD', KEYS[2]) >= 5 then
  local first = redis.call('ZRANGE', KEYS[2], 0, 0, 'WITHSCORES')
  return {2, math.max(1, tonumber(first[2]) + 1000 - ms)}
end
redis.call('INCRBY', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('ZADD', KEYS[2], ms, ARGV[4])
redis.call('PEXPIRE', KEYS[2], 2000)
return {0, 0}
"""


async def reserve_credit(cache_service: Any, api_key: str) -> str:
    """Reserve one basic API credit, or return a safe public failure status."""
    try:
        configured = int(os.getenv("GEOAPIFY_DAILY_CREDIT_LIMIT", "2500"))
        limit = max(0, min(3000, configured))
        client = cache_service.client
        if inspect.isawaitable(client):
            client = await client
        if client is None:
            return "quota_unavailable"
        fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:20]
        now = datetime.now(timezone.utc)
        prefix = f"geoapify:budget:{{{fingerprint}}}"
        daily_key = f"{prefix}:{now:%Y-%m-%d}"
        ttl = 86400 - (now.hour * 3600 + now.minute * 60 + now.second) + 3600
        for attempt in range(2):
            result = await client.eval(
                RESERVE_SCRIPT, 2, daily_key, f"{prefix}:rate", 1, limit, ttl, uuid.uuid4().hex,
            )
            code, retry_ms = int(result[0]), int(result[1])
            if code == 0:
                return "ok"
            if code == 1:
                return "quota_exhausted"
            if code != 2:
                return "quota_unavailable"
            if attempt == 0:
                await asyncio.sleep(min(1.05, max(0.001, retry_ms / 1000 + 0.01)))
        return "rate_limited"
    except Exception:
        # Never make an unmetered request when the shared guard cannot be read.
        return "quota_unavailable"
