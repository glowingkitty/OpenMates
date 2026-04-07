"""
backend/shared/python_utils/celery_dedup.py

Idempotency dedup lock for Celery tasks (OPE-338 follow-up).

Why this exists
---------------
With `task_acks_late=True` + `task_reject_on_worker_lost=True` (set globally in
celery_config.py), the broker is allowed — and is *expected* — to redeliver an
unacked message if the worker connection cycles, autoreload restarts the
worker, or kombu's `restore_unacked_once` runs. We accept that trade-off
because losing a task is worse than running it twice. The compensator for
"running it twice" is consumer-side idempotency, which is what this module
provides.

Why sync redis (not the pooled async CacheService)
--------------------------------------------------
Each Celery task creates a fresh `asyncio.new_event_loop()`, but the worker's
pooled `CacheService` caches a `redis.asyncio.Redis` client bound to the loop
that first awaited its `client` property. On the next task, any direct
`await client.set(...)` raises "Event loop is closed" — exactly how the
previous async dedup guard (commit 04d3994cf) silently failed in production
on 2026-04-06 (chat 7929b948 was processed twice as a result).

A fresh sync `redis.Redis` connection has no event-loop affinity, runs
immediately, and is closed in `finally`. It's the only reliable place to do
the dedup *before* the asyncio loop is even created.

Fail-closed
-----------
If the redis call raises (cache outage, wrong password, etc.) we re-raise as
`RuntimeError`. Callers MUST treat this as a hard failure and refuse to run
the task. Silently proceeding is what created the OPE-338 incident in the
first place.
"""

import logging
import os
from typing import Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# Key prefix used in Dragonfly/Redis. Keep stable — changing it would let
# pre-rollout duplicates slip through during a deploy.
DEDUP_KEY_PREFIX = "celery_task_dedup:"

# Default TTL must be > the longest task's `time_limit` with margin so a
# legitimately long-running task doesn't get its lock evicted before completion
# (which would let a redelivery slip through). 600s covers our current longest
# task (`apps.ai.tasks.skill_ask` at 360s) with comfortable headroom.
DEFAULT_DEDUP_TTL_SECONDS = 600


def acquire_celery_task_dedup_lock(
    task_id: str,
    broker_url: Optional[str] = None,
    ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS,
) -> bool:
    """
    Try to claim the per-task_id dedup lock with a fresh synchronous redis
    connection.

    Args:
        task_id: Celery task id (`self.request.id`). Must be non-empty.
        broker_url: Redis URL. Defaults to env `CELERY_BROKER_URL`. Pass the
            value resolved by celery_config when calling from a worker so we
            hit the same Dragonfly instance the broker uses.
        ttl_seconds: Lock TTL. Use a value larger than the task's hard
            time_limit; defaults to `DEFAULT_DEDUP_TTL_SECONDS`.

    Returns:
        True  — first execution, proceed normally.
        False — duplicate redelivery, caller MUST skip the task body.

    Raises:
        RuntimeError — redis is unreachable / authn failure / bad URL.
            Callers MUST fail-closed (do NOT run the task) so we never silently
            double-process. The previous async guard "logged a warning and
            proceeded" which is what allowed chat 7929b948 to be processed
            twice on 2026-04-06.
    """
    if not task_id:
        # No task_id means we cannot dedup. Let the task run — this only
        # happens for direct/eager invocations, not real broker delivery.
        return True

    # Local import: keep `redis` out of any module that imports this helper
    # transitively but never calls it (e.g. tests).
    import redis  # sync client; already a transitive dep via redis>=5.2

    url = broker_url or os.getenv("CELERY_BROKER_URL")
    if not url:
        raise RuntimeError(
            "Celery broker URL unavailable; cannot acquire dedup lock"
        )

    parsed = urlparse(url)
    host = parsed.hostname or "cache"
    port = parsed.port or 6379
    password = unquote(parsed.password) if parsed.password else None
    try:
        db = int((parsed.path or "/0").lstrip("/") or "0")
    except ValueError:
        db = 0

    client = None
    try:
        client = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=db,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=False,
        )
        was_set = client.set(
            f"{DEDUP_KEY_PREFIX}{task_id}",
            b"1",
            ex=ttl_seconds,
            nx=True,
        )
        return bool(was_set)
    except Exception as e:
        # Re-raise as RuntimeError so callers can fail-closed via Ignore().
        raise RuntimeError(f"sync redis dedup lock failed: {e}") from e
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
