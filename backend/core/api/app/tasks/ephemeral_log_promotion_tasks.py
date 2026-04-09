# backend/core/api/app/tasks/ephemeral_log_promotion_tasks.py
"""
Ephemeral Log Promotion Task — Error-Triggered Retention

Periodic Celery task that scans Redis for sessions with error-level console
logs and promotes their full log context from the ephemeral OpenObserve stream
(48h retention) to the error-context stream (14d retention).

This provides debugging context (the logs BEFORE and AFTER the error) without
requiring long-term storage of all user console logs.

Flow:
  1. SCAN Redis for 'ephemeral-error:*' keys (set by client_logs_ephemeral route)
  2. For each flagged session_pseudonym:
     a. Skip if already promoted (ephemeral-promoted:{pseudonym} exists)
     b. Query OpenObserve client-logs-ephemeral stream for all logs with that pseudonym
     c. Push results to client-logs-error-context stream
     d. Set ephemeral-promoted:{pseudonym} flag (48h TTL, prevents re-promotion)
     e. Delete the error flag
  3. Max 50 sessions per run to avoid overloading OpenObserve
"""

import logging
import asyncio
import os
import time

import aiohttp
from celery import shared_task

logger = logging.getLogger(__name__)

# OpenObserve connection config (same as openobserve_push_service)
OPENOBSERVE_BASE_URL = "http://openobserve:5080"
OPENOBSERVE_ORG = "default"

# Max sessions to promote per task run (prevents runaway queries)
MAX_SESSIONS_PER_RUN = 50

# Max log entries to fetch per session (safety limit)
MAX_ENTRIES_PER_SESSION = 5000


async def _query_ephemeral_logs(session_pseudonym: str) -> list:
    """
    Query OpenObserve for all logs from a specific session in the ephemeral stream.

    Uses the OpenObserve SQL search API to fetch all log entries for a session
    within the last 48 hours.
    """
    email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

    # Query the last 48h of logs for this session
    end_time = int(time.time() * 1_000_000)  # microseconds
    start_time = end_time - (48 * 3600 * 1_000_000)  # 48h ago

    query_payload = {
        "query": {
            "sql": (
                f'SELECT _timestamp, message FROM "client_console_ephemeral" '
                f"WHERE session_pseudonym = '{session_pseudonym}' "
                f"ORDER BY _timestamp ASC "
                f"LIMIT {MAX_ENTRIES_PER_SESSION}"
            ),
            "start_time": start_time,
            "end_time": end_time,
            "from": 0,
            "size": MAX_ENTRIES_PER_SESSION,
        }
    }

    url = f"{OPENOBSERVE_BASE_URL}/api/{OPENOBSERVE_ORG}/_search"
    timeout = aiohttp.ClientTimeout(total=30)

    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            auth=aiohttp.BasicAuth(email, password),
        ) as session:
            async with session.post(
                url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        f"OpenObserve search failed for session {session_pseudonym[:8]}... "
                        f"(status={response.status}): {error_text[:300]}"
                    )
                    return []

                data = await response.json()
                hits = data.get("hits", [])
                entries = []
                for hit in hits:
                    entries.append({
                        "_timestamp": hit.get("_timestamp", 0),
                        "message": hit.get("message", ""),
                    })
                return entries

    except Exception as e:
        logger.error(
            f"Error querying ephemeral logs for session {session_pseudonym[:8]}...: {e}",
            exc_info=True,
        )
        return []


async def _promote_session(session_pseudonym: str) -> bool:
    """Fetch ephemeral logs for a session and push them to the error-context stream."""
    from backend.core.api.app.services.openobserve_push_service import openobserve_push_service

    entries = await _query_ephemeral_logs(session_pseudonym)
    if not entries:
        logger.info(
            f"No ephemeral logs found for session {session_pseudonym[:8]}... — skipping promotion"
        )
        return True  # Not an error, just nothing to promote

    success = await openobserve_push_service.push_error_context_logs(
        entries=entries,
        session_pseudonym=session_pseudonym,
    )

    if success:
        logger.info(
            f"Promoted {len(entries)} log entries for session {session_pseudonym[:8]}... "
            f"to error-context stream"
        )
    else:
        logger.error(
            f"Failed to promote logs for session {session_pseudonym[:8]}... to error-context stream"
        )

    return success


async def _run_promotion() -> dict:
    """
    Main promotion logic — scan Redis for flagged sessions and promote their logs.

    Returns a summary dict with counts for logging.
    """
    from backend.core.api.app.services.cache import CacheService

    cache = CacheService()
    await cache.connect()
    redis = cache.redis

    promoted = 0
    skipped = 0
    failed = 0

    try:
        # SCAN for error-flagged sessions (never use KEYS in production)
        cursor = 0
        flagged_sessions = []
        while len(flagged_sessions) < MAX_SESSIONS_PER_RUN:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match="ephemeral-error:*",
                count=100,
            )
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                session_id = key.replace("ephemeral-error:", "")
                flagged_sessions.append(session_id)
                if len(flagged_sessions) >= MAX_SESSIONS_PER_RUN:
                    break
            if cursor == 0:
                break

        if not flagged_sessions:
            return {"promoted": 0, "skipped": 0, "failed": 0, "total_flagged": 0}

        for session_id in flagged_sessions:
            # Check if already promoted (idempotency guard)
            promoted_key = f"ephemeral-promoted:{session_id}"
            if await redis.exists(promoted_key):
                # Already promoted — clean up the error flag
                await redis.delete(f"ephemeral-error:{session_id}")
                skipped += 1
                continue

            success = await _promote_session(session_id)

            if success:
                # Mark as promoted (48h TTL) and remove the error flag
                await redis.set(promoted_key, "1", ex=172800)
                await redis.delete(f"ephemeral-error:{session_id}")
                promoted += 1
            else:
                failed += 1

    finally:
        await cache.disconnect()

    return {
        "promoted": promoted,
        "skipped": skipped,
        "failed": failed,
        "total_flagged": len(flagged_sessions),
    }


@shared_task(
    name="ephemeral_logs.promote_error_sessions",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    acks_late=True,
)
def promote_error_sessions(self) -> dict:
    """
    Celery task: promote ephemeral logs for sessions with errors.

    Runs every 15 minutes via beat_schedule. Scans Redis for sessions flagged
    with error-level console logs and copies their full log context to the
    long-retention error-context stream.
    """
    try:
        # asyncio.run() creates a fresh event loop for this Celery thread and
        # tears it down cleanly. Using asyncio.get_event_loop() here raised
        # `RuntimeError: There is no current event loop in thread` on every run
        # because Celery worker threads have no pre-existing loop.
        result = asyncio.run(_run_promotion())
        if result["promoted"] > 0 or result["failed"] > 0:
            logger.info(
                f"Ephemeral log promotion complete: "
                f"{result['promoted']} promoted, {result['skipped']} skipped, "
                f"{result['failed']} failed (of {result['total_flagged']} flagged)"
            )
        return result
    except Exception as e:
        logger.error(f"Ephemeral log promotion task failed: {e}", exc_info=True)
        raise self.retry(exc=e)
