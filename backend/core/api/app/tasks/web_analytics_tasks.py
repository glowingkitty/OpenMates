# backend/core/api/app/tasks/web_analytics_tasks.py
#
# Celery task to flush web analytics counters from Redis to Directus.
#
# Runs every 10 minutes on the server_stats queue (same schedule as flush-server-stats).
# Reads all daily Redis hashes, builds structured JSON fields, then upserts records
# in the web_analytics_daily Directus collection.
#
# Architecture:
# - Redis keys: web:analytics:daily:{YYYY-MM-DD} (hash), web:analytics:hll:{YYYY-MM-DD} (HyperLogLog)
# - Directus collection: web_analytics_daily (one row per day)
# - This task is idempotent — upsert by date is safe to run multiple times
#
# See docs/analytics.md for full data model.

import logging
import asyncio
from datetime import date, timedelta

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.services.web_analytics_service import (
    WebAnalyticsService,
    WEB_ANALYTICS_DAILY_KEY_PREFIX,
)

logger = logging.getLogger(__name__)


@app.task(name="web_analytics.flush_to_directus", base=BaseServiceTask, bind=True)
def flush_web_analytics(self):
    """
    Periodic task: flush web analytics counters from Redis → Directus.
    Runs every 10 minutes on the server_stats queue.
    """
    return asyncio.run(run_flush_web_analytics(self))


async def run_flush_web_analytics(task: BaseServiceTask) -> dict:
    """
    Main coroutine for the web analytics flush task.

    Finds all active day keys in Redis, builds structured records,
    and upserts them into the web_analytics_daily Directus collection.
    """
    log_prefix = "WebAnalyticsFlushTask:"
    logger.info(f"{log_prefix} Starting web analytics flush")

    try:
        await task.initialize_services()

        # Build WebAnalyticsService using the task's cache service
        analytics_service = WebAnalyticsService(task.cache_service)

        # Find all day keys currently in Redis
        # We flush today + yesterday to catch any stragglers from overnight runs
        today = date.today()
        days_to_flush = [
            today.isoformat(),
            (today - timedelta(days=1)).isoformat(),
        ]

        # Also discover any other keys still in Redis (e.g. from backup restore)
        client = await task.cache_service.client
        if client:
            try:
                pattern_keys = await client.keys(f"{WEB_ANALYTICS_DAILY_KEY_PREFIX}*")
                for key in pattern_keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    day = key_str.replace(WEB_ANALYTICS_DAILY_KEY_PREFIX, "")
                    if day not in days_to_flush:
                        days_to_flush.append(day)
            except Exception as e:
                logger.warning(f"{log_prefix} Could not scan Redis keys: {e}")

        flushed = 0
        for day in days_to_flush:
            try:
                await _flush_day(task, analytics_service, day, log_prefix)
                flushed += 1
            except Exception as e:
                logger.error(f"{log_prefix} Failed to flush {day}: {e}", exc_info=True)

        logger.info(f"{log_prefix} Completed — flushed {flushed}/{len(days_to_flush)} day(s)")
        return {"success": True, "flushed_days": flushed}

    except Exception as e:
        logger.error(f"{log_prefix} Task failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()


async def _flush_day(
    task: BaseServiceTask,
    analytics_service: WebAnalyticsService,
    day: str,
    log_prefix: str,
) -> None:
    """
    Flushes analytics counters for a single day from Redis → Directus.

    Reads the Redis hash for the given day, transforms flat keys into
    nested JSON fields, then upserts the record in web_analytics_daily.
    """
    # Read all counters for this day
    raw_counters = await analytics_service.get_daily_counters(day)

    if not raw_counters:
        logger.debug(f"{log_prefix} No data for {day}, skipping")
        return

    # Build structured JSON fields from flat Redis hash
    structured = analytics_service._build_json_fields(raw_counters)

    # Map field names to Directus schema field names
    # web:analytics:daily keys use prefixes like "countries:", "devices:", etc.
    # _build_json_fields converts these to nested dicts under the prefix key
    import json

    payload = {
        "date": day,
        "page_loads": structured.get("page_loads", 0),
        "unique_visits_approx": structured.get("unique_visits_approx", 0),
        # JSON fields — stored as JSON strings in Directus
        "countries": json.dumps(structured.get("countries", {})),
        "devices": json.dumps(structured.get("devices", {})),
        "browsers": json.dumps(structured.get("browsers", {})),
        "os_families": json.dumps(structured.get("os", {})),
        "referrer_domains": json.dumps(structured.get("referrers", {})),
        "screen_classes": json.dumps(structured.get("screen_classes", {})),
        "session_duration_buckets": json.dumps(structured.get("duration", {})),
    }

    # Upsert into Directus (get existing by date, then update or create)
    try:
        existing_records = await task.directus_service.get_items(
            "web_analytics_daily",
            params={"filter": {"date": {"_eq": day}}, "limit": 1}
        )
        if existing_records:
            await task.directus_service.update_item(
                "web_analytics_daily",
                existing_records[0]["id"],
                payload,
                admin_required=True,
            )
            logger.debug(f"{log_prefix} Updated web_analytics_daily for {day}")
        else:
            await task.directus_service.create_item(
                "web_analytics_daily",
                payload,
                admin_required=True,
            )
            logger.debug(f"{log_prefix} Created web_analytics_daily for {day}")
    except Exception as e:
        logger.error(f"{log_prefix} Directus upsert failed for {day}: {e}", exc_info=True)
        raise
