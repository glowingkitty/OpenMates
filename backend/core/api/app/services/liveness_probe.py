"""Public liveness probe for GET /v1/health/liveness.

Unlike the cached /v1/health snapshot (filled by Celery tasks, so it stays
"healthy" while workers are dead), this dispatches the no-spend
``runtime_health.worker_probe`` task to the app_ai queue and reports whether a
worker answered. The outcome is cached for 30 s and a short lock makes sure
concurrent callers dispatch at most one probe per window.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict

logger = logging.getLogger(__name__)

LIVENESS_CACHE_KEY = "health:liveness:ai_worker"
LIVENESS_LOCK_KEY = "health:liveness:lock"
LIVENESS_CACHE_TTL_SECONDS = 30
LIVENESS_LOCK_TTL_SECONDS = 12
LIVENESS_PROBE_TIMEOUT_SECONDS = 8
LIVENESS_LOCK_WAIT_SECONDS = 10
PROBE_TASK_NAME = "runtime_health.worker_probe"


def _dispatch_probe_blocking() -> bool:
    """Send the probe and wait for its result (runs in a worker thread)."""
    from backend.core.api.app.tasks.celery_config import app

    probe_id = uuid.uuid4().hex
    result = app.send_task(PROBE_TASK_NAME, args=[probe_id], queue="app_ai")
    try:
        payload = result.get(timeout=LIVENESS_PROBE_TIMEOUT_SECONDS, propagate=True)
    finally:
        result.forget()
    return isinstance(payload, dict) and payload.get("probe_id") == probe_id


async def _probe_ai_worker() -> str:
    try:
        ok = await asyncio.wait_for(
            asyncio.to_thread(_dispatch_probe_blocking),
            timeout=LIVENESS_PROBE_TIMEOUT_SECONDS + 2,
        )
    except Exception as exc:  # broker/timeout/task errors all mean "no worker answered"
        logger.warning("Liveness probe failed: %s", type(exc).__name__)
        return "unavailable"
    return "ok" if ok else "unavailable"


async def get_liveness(cache: Any) -> Dict[str, Any]:
    """Return the public liveness payload, probing at most once per 30 s."""
    cached = await cache.get(LIVENESS_CACHE_KEY)
    ai_worker = cached if cached in ("ok", "unavailable") else None

    if ai_worker is None:
        client = await cache.client
        got_lock = True
        if client:
            got_lock = bool(await client.set(LIVENESS_LOCK_KEY, "1", nx=True, ex=LIVENESS_LOCK_TTL_SECONDS))
        if got_lock:
            ai_worker = await _probe_ai_worker()
            await cache.set(LIVENESS_CACHE_KEY, ai_worker, ttl=LIVENESS_CACHE_TTL_SECONDS)
            if client:
                await client.delete(LIVENESS_LOCK_KEY)
        else:
            deadline = time.monotonic() + LIVENESS_LOCK_WAIT_SECONDS
            while ai_worker is None and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                cached = await cache.get(LIVENESS_CACHE_KEY)
                ai_worker = cached if cached in ("ok", "unavailable") else None
            if ai_worker is None:
                ai_worker = "unavailable"

    return {
        "status": "ok" if ai_worker == "ok" else "degraded",
        "api": "ok",
        "ai_worker": ai_worker,
        "checked_at": int(time.time()),
    }
