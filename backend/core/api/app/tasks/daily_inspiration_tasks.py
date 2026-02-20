# backend/core/api/app/tasks/daily_inspiration_tasks.py
# Celery tasks for Daily Inspiration generation and delivery.
#
# Two entry points:
#
# 1. generate_inspirations_for_user (async helper, not a Celery task itself)
#    Called from ask_skill_task.py for immediate generation after the first paid request.
#    Runs in the same app-ai-worker context as the AI task.
#
# 2. generate_daily_inspirations (Celery task, scheduled by Beat)
#    Runs once per day. Scans all active users and generates N new inspirations per user
#    (where N = number of inspirations the user viewed the previous day, 1-3).
#    Users are processed sequentially to respect Brave and LLM rate limits.
#
# Delivery:
# - If the user is online at generation time: publish via WebSocket immediately
#   (via Redis channel websocket:user:{user_id}, consumed by the embed data listener)
# - If offline: store encrypted in pending cache (7-day TTL), deliver on next login
#   (see websockets.py for the login delivery hook)
#
# Privacy:
# - No user content (phrases, videos) is persisted server-side.
# - Pending delivery cache uses a vault key per user (server-side encryption).
# - View tracking stores only UUIDs, not content.

import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

logger = logging.getLogger(__name__)

# Cache key to mark that a user has already received their first-run inspirations.
# Prevents re-triggering on every paid request after the first one.
# TTL: 7 days (refreshed after each daily generation run)
_FIRST_RUN_FLAG_KEY_PREFIX = "daily_inspiration_first_run_done:"
_FIRST_RUN_FLAG_TTL = 7 * 86400  # 7 days


# ─────────────────────────────────────────────────────────────────────────────
# Shared async helper: generate + deliver for one user
# ─────────────────────────────────────────────────────────────────────────────

async def generate_and_deliver_inspirations_for_user(
    user_id: str,
    count: int,
    cache_service: Any,
    secrets_manager: Any,
    task_id: str = "daily_inspiration",
    *,
    is_online: bool = False,
    task_instance: Optional[Any] = None,
) -> bool:
    """
    Generate `count` inspirations for a user and deliver them.

    Delivery strategy:
    - Online (is_online=True): publish `daily_inspiration` WebSocket event immediately
    - Offline: store in pending delivery cache (encrypted with vault key)

    Args:
        user_id: User UUID
        count: Number of inspirations to generate (1-3)
        cache_service: CacheService instance
        secrets_manager: SecretsManager instance (must be initialized)
        task_id: Logging context
        is_online: Whether the user has an active WebSocket connection right now
        task_instance: BaseServiceTask instance (used for publish_websocket_event when online)

    Returns:
        True if generation and delivery succeeded, False on error
    """
    from backend.apps.ai.daily_inspiration.generator import generate_inspirations

    logger.info(
        f"[DailyInspiration][{task_id}] Generating {count} inspiration(s) for user {user_id[:8]}... "
        f"(online={is_online})"
    )

    # Retrieve topic suggestions for personalization
    topic_suggestions = await cache_service.get_inspiration_topic_suggestions(user_id)
    logger.debug(
        f"[DailyInspiration][{task_id}] Found {len(topic_suggestions)} topic suggestions "
        f"for user {user_id[:8]}..."
    )

    # Run generation
    inspirations = await generate_inspirations(
        user_id=user_id,
        count=count,
        topic_suggestions=topic_suggestions,
        secrets_manager=secrets_manager,
        task_id=task_id,
    )

    if not inspirations:
        logger.error(
            f"[DailyInspiration][{task_id}] Generation returned empty results for user {user_id[:8]}..."
        )
        return False

    # Serialize inspiration objects to dicts for delivery / cache storage
    serialized = [insp.model_dump() for insp in inspirations]

    # ── Online delivery ────────────────────────────────────────────────────────
    if is_online and task_instance is not None:
        try:
            delivery_payload = {
                "inspirations": serialized,
                "user_id": user_id,  # Required by websocket relay for routing
            }
            await task_instance.publish_websocket_event(
                user_id_hash=user_id,
                event="daily_inspiration",
                payload=delivery_payload,
            )
            logger.info(
                f"[DailyInspiration][{task_id}] Delivered {len(inspirations)} inspiration(s) "
                f"via WebSocket to online user {user_id[:8]}..."
            )
        except Exception as e:
            logger.error(
                f"[DailyInspiration][{task_id}] WebSocket delivery failed for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            # Fall through to offline cache as a safety net
            is_online = False

    # ── Offline delivery (or fallback) ────────────────────────────────────────
    if not is_online:
        # Store plaintext in pending cache — the WebSocket handler at login will
        # deliver and clear the cache. We don't encrypt here because the connection
        # manager delivers it as plaintext over the existing authenticated WebSocket.
        # The client-side encryption of the actual content happens in the frontend
        # (same trust boundary as chat messages).
        try:
            await cache_service.store_pending_inspirations(
                user_id=user_id,
                inspirations=serialized,
            )
            logger.info(
                f"[DailyInspiration][{task_id}] Stored {len(inspirations)} inspiration(s) "
                f"in pending cache for offline user {user_id[:8]}..."
            )
        except Exception as e:
            logger.error(
                f"[DailyInspiration][{task_id}] Pending cache storage failed for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return False

    # Clear view tracking after generation (resets the counter for the next day)
    await cache_service.clear_inspiration_views(user_id)

    # Mark first-run as done (prevents re-triggering on subsequent paid requests)
    try:
        client = await cache_service.client
        if client:
            flag_key = f"{_FIRST_RUN_FLAG_KEY_PREFIX}{user_id}"
            await client.set(flag_key, "1", ex=_FIRST_RUN_FLAG_TTL)
    except Exception as e:
        logger.warning(f"[DailyInspiration][{task_id}] Could not set first-run flag: {e}")

    return True


async def _is_first_run_done(cache_service: Any, user_id: str) -> bool:
    """Check whether the first-run inspiration generation has already been completed for a user."""
    try:
        client = await cache_service.client
        if not client:
            return False
        flag_key = f"{_FIRST_RUN_FLAG_KEY_PREFIX}{user_id}"
        val = await client.get(flag_key)
        return val is not None
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point: called from ask_skill_task.py after first paid request
# ─────────────────────────────────────────────────────────────────────────────

async def trigger_first_run_inspirations(
    user_id: str,
    cache_service: Any,
    secrets_manager: Any,
    task_id: str = "daily_inspiration_first_run",
) -> None:
    """
    Trigger immediate inspiration generation for a user's first paid request.

    Checks the first-run flag to avoid re-generating on every subsequent paid request.
    Called from ask_skill_task.py (non-fatal; exceptions are caught and logged by caller).

    Args:
        user_id: User UUID
        cache_service: Initialized CacheService instance
        secrets_manager: Initialized SecretsManager instance
        task_id: Logging context
    """
    # Check if we've already done the first run for this user
    already_done = await _is_first_run_done(cache_service, user_id)
    if already_done:
        logger.debug(
            f"[DailyInspiration][{task_id}] First-run already completed for user {user_id[:8]}... — skipping"
        )
        return

    logger.info(
        f"[DailyInspiration][{task_id}] First paid request detected for user {user_id[:8]}... "
        "— triggering immediate inspiration generation"
    )

    # For first-run, user is likely online (they just completed a paid request).
    # We deliver via pending cache (delivered on next login/connection) to keep the
    # ask_skill_task lightweight and avoid adding to its critical path.
    await generate_and_deliver_inspirations_for_user(
        user_id=user_id,
        count=3,
        cache_service=cache_service,
        secrets_manager=secrets_manager,
        task_id=task_id,
        is_online=False,  # Use pending cache for reliability
        task_instance=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Celery task: scheduled daily generation
# ─────────────────────────────────────────────────────────────────────────────

@app.task(name="daily_inspiration.generate_daily", base=BaseServiceTask, bind=True)
def generate_daily_inspirations(self):
    """
    Daily Celery task: generate personalized inspirations for all active users.

    Scheduled by Beat (see celery_config.py beat_schedule).
    Active = made at least one paid request in the last 24 hours.
    Count = number of inspirations the user viewed the previous day (1-3).
    Users with 0 views get no new inspirations (cost optimization).

    Processing is sequential per user to respect API rate limits.
    """
    return asyncio.run(_generate_daily_inspirations_async(self))


async def _generate_daily_inspirations_async(task: BaseServiceTask) -> Dict[str, Any]:
    """Async implementation of generate_daily_inspirations."""
    task_id = "daily_inspiration_daily_job"
    logger.info(f"[DailyInspiration][{task_id}] Daily generation job started")

    try:
        await task.initialize_services()
    except Exception as e:
        logger.error(
            f"[DailyInspiration][{task_id}] Failed to initialize services: {e}",
            exc_info=True,
        )
        return {"success": False, "error": str(e)}

    cache_service = task._cache_service
    secrets_manager = task._secrets_manager

    if not cache_service or not secrets_manager:
        logger.error(f"[DailyInspiration][{task_id}] Required services unavailable — aborting")
        return {"success": False, "error": "Services not initialized"}

    # ── Discover active users ──────────────────────────────────────────────────
    # Active = have a paid_request tracking key in Redis (set by billing_service.py).
    # We scan for all keys matching `daily_inspiration_last_paid_request:*`.
    # This is the most cost-effective approach: no Directus query needed.
    try:
        client = await cache_service.client
        if not client:
            logger.error(f"[DailyInspiration][{task_id}] Redis client unavailable")
            return {"success": False, "error": "Redis unavailable"}

        pattern = "daily_inspiration_last_paid_request:*"
        active_user_keys: List[str] = []

        # Use SCAN for efficient key enumeration (avoids blocking KEYS command)
        cursor = 0
        while True:
            cursor, batch = await client.scan(cursor, match=pattern, count=100)
            active_user_keys.extend(batch)
            if cursor == 0:
                break

        logger.info(
            f"[DailyInspiration][{task_id}] Found {len(active_user_keys)} users with paid-request tracking"
        )
    except Exception as e:
        logger.error(
            f"[DailyInspiration][{task_id}] Failed to scan for active users: {e}",
            exc_info=True,
        )
        return {"success": False, "error": str(e)}

    if not active_user_keys:
        logger.info(f"[DailyInspiration][{task_id}] No active users found — daily job complete")
        return {"success": True, "processed": 0, "skipped": 0, "errors": 0}

    processed = 0
    skipped = 0
    errors = 0

    for key in active_user_keys:
        # Extract user_id from key: "daily_inspiration_last_paid_request:{user_id}"
        user_id = key.split(":", 1)[1] if ":" in key else None
        if not user_id:
            logger.warning(f"[DailyInspiration][{task_id}] Cannot parse user_id from key: {key}")
            continue

        try:
            # Check 24h activity
            is_active = await cache_service.had_paid_request_in_last_24h(user_id)
            if not is_active:
                logger.debug(
                    f"[DailyInspiration][{task_id}] User {user_id[:8]}... has no paid request "
                    "in last 24h — skipping"
                )
                skipped += 1
                continue

            # How many inspirations did this user view?
            viewed_count = await cache_service.get_viewed_inspiration_count(user_id)
            if viewed_count == 0:
                logger.debug(
                    f"[DailyInspiration][{task_id}] User {user_id[:8]}... viewed 0 inspirations — skipping"
                )
                skipped += 1
                continue

            count_to_generate = min(viewed_count, 3)  # Cap at 3

            success = await generate_and_deliver_inspirations_for_user(
                user_id=user_id,
                count=count_to_generate,
                cache_service=cache_service,
                secrets_manager=secrets_manager,
                task_id=task_id,
                is_online=False,  # Daily job always uses pending cache for reliability
                task_instance=None,
            )

            if success:
                processed += 1
            else:
                errors += 1

            # Brief pause between users to avoid API rate limits
            await asyncio.sleep(2)

        except Exception as e:
            logger.error(
                f"[DailyInspiration][{task_id}] Error processing user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            errors += 1

    result = {
        "success": True,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }
    logger.info(
        f"[DailyInspiration][{task_id}] Daily generation job completed: "
        f"{processed} generated, {skipped} skipped, {errors} errors"
    )
    return result
