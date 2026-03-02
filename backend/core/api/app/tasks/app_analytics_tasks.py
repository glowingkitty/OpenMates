# backend/core/api/app/tasks/app_analytics_tasks.py
#
# Celery task to aggregate raw app_analytics events into daily summaries.
#
# The app_analytics collection stores one row per LLM usage event (from each skill/app call).
# This task runs daily at 3 AM UTC and aggregates yesterday's rows into app_analytics_daily,
# grouping by (date, app_id, skill_id, model_used, focus_mode_id, settings_memory_type).
#
# This avoids running expensive GROUP BY queries at dashboard render time.
# The raw app_analytics rows are not deleted — they may be kept for longer-term queries
# or cleaned up by a separate retention policy.
#
# Architecture: see docs/analytics.md

import logging
import asyncio
from datetime import date, timedelta

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

logger = logging.getLogger(__name__)


@app.task(name="app_analytics.aggregate_daily", base=BaseServiceTask, bind=True)
def aggregate_app_analytics_daily(self):
    """
    Daily task: aggregate yesterday's app_analytics events into app_analytics_daily.
    Runs at 03:00 UTC on the persistence queue.
    """
    return asyncio.run(run_aggregate_app_analytics(self))


async def run_aggregate_app_analytics(task: BaseServiceTask) -> dict:
    """
    Main coroutine for the app analytics daily aggregation task.

    Queries app_analytics for all events in yesterday's date range,
    groups by dimension tuple, and upserts records in app_analytics_daily.
    """
    log_prefix = "AppAnalyticsAggregateTask:"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    logger.info(f"{log_prefix} Aggregating app_analytics for {yesterday}")

    try:
        await task.initialize_services()

        # Build unix timestamp range for yesterday
        from datetime import datetime, timezone
        day_start = int(datetime.strptime(yesterday, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        day_end = day_start + 86400  # 24 hours later

        # Query all raw events for yesterday from app_analytics
        # Use timestamp range filtering (unix timestamps as stored in the collection)
        params = {
            "filter": {
                "_and": [
                    {"timestamp": {"_gte": day_start}},
                    {"timestamp": {"_lt": day_end}},
                ]
            },
            "limit": -1,  # All matching records
            "fields": ["app_id", "skill_id", "model_used", "focus_mode_id", "settings_memory_type"],
        }

        events = await task.directus_service.get_items("app_analytics", params=params)

        if not events:
            logger.info(f"{log_prefix} No app_analytics events found for {yesterday}")
            return {"success": True, "date": yesterday, "aggregated": 0}

        logger.info(f"{log_prefix} Found {len(events)} raw events for {yesterday}")

        # Group events by dimension tuple
        counts: dict = {}
        for event in events:
            key = (
                event.get("app_id") or "",
                event.get("skill_id") or "",
                event.get("model_used") or "",
                event.get("focus_mode_id") or "",
                event.get("settings_memory_type") or "",
            )
            counts[key] = counts.get(key, 0) + 1

        # Upsert each unique dimension combination into app_analytics_daily
        upserted = 0
        for dim_key, count in counts.items():
            (app_id, skill_id, model_used, focus_mode_id, settings_memory_type) = dim_key
            payload = {
                "date": yesterday,
                "app_id": app_id or None,
                "skill_id": skill_id or None,
                "model_used": model_used or None,
                "focus_mode_id": focus_mode_id or None,
                "settings_memory_type": settings_memory_type or None,
                "count": count,
            }

            try:
                # Check for existing record with same dimensions
                filter_params = {
                    "filter": {
                        "_and": [
                            {"date": {"_eq": yesterday}},
                            {"app_id": {"_eq": app_id} if app_id else {"_null": True}},
                            {"skill_id": {"_eq": skill_id} if skill_id else {"_null": True}},
                            {"model_used": {"_eq": model_used} if model_used else {"_null": True}},
                            {"focus_mode_id": {"_eq": focus_mode_id} if focus_mode_id else {"_null": True}},
                            {"settings_memory_type": {"_eq": settings_memory_type} if settings_memory_type else {"_null": True}},
                        ]
                    },
                    "limit": 1,
                }
                existing = await task.directus_service.get_items("app_analytics_daily", params=filter_params)

                if existing:
                    await task.directus_service.update_item(
                        "app_analytics_daily",
                        existing[0]["id"],
                        {"count": count},
                        admin_required=True,
                    )
                else:
                    await task.directus_service.create_item(
                        "app_analytics_daily",
                        payload,
                        admin_required=True,
                    )
                upserted += 1
            except Exception as row_err:
                logger.error(f"{log_prefix} Failed to upsert row for {dim_key}: {row_err}", exc_info=True)

        logger.info(f"{log_prefix} Aggregated {len(counts)} unique dimension combos → {upserted} upserted")
        return {"success": True, "date": yesterday, "events": len(events), "aggregated": upserted}

    except Exception as e:
        logger.error(f"{log_prefix} Aggregation task failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()
