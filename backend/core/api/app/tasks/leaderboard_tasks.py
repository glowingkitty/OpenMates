# backend/core/api/app/tasks/leaderboard_tasks.py
#
# Celery tasks for updating AI model leaderboard data.
# Runs daily to aggregate rankings from LMArena, OpenRouter, and other sources.

import logging
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

# Cache key for leaderboard data
LEADERBOARD_CACHE_KEY = "leaderboard:models"

# TTL for leaderboard cache (25 hours - slightly longer than daily update interval)
LEADERBOARD_CACHE_TTL = 25 * 60 * 60


async def _aggregate_leaderboard_async(category: str = "text") -> Dict[str, Any]:
    """
    Asynchronously aggregate leaderboard data from multiple sources.

    Args:
        category: LMArena category to fetch (text, coding, math, etc.)

    Returns:
        Aggregated leaderboard data
    """
    # Import here to avoid circular imports
    from backend.scripts.aggregate_leaderboards import aggregate_leaderboards

    logger.info(f"[LEADERBOARD] Starting leaderboard aggregation for category: {category}")

    try:
        # Run aggregation (saves to file and returns data)
        data = await aggregate_leaderboards(
            category=category,
            dry_run=False,  # Save to file
            as_json=False   # Use YAML
        )

        ranked_count = len(data.get("rankings", []))
        logger.info(f"[LEADERBOARD] Aggregation complete. Ranked models: {ranked_count}")

        return data

    except Exception as e:
        logger.error(f"[LEADERBOARD] Aggregation failed: {e}", exc_info=True)
        raise


async def _update_cache_async(data: Dict[str, Any]) -> bool:
    """
    Update the leaderboard data in cache.

    Args:
        data: Aggregated leaderboard data

    Returns:
        True if cache was updated successfully
    """
    try:
        cache_service = CacheService()

        # Store full leaderboard data as JSON
        cache_value = json.dumps(data, ensure_ascii=False)
        await cache_service.async_set(
            key=LEADERBOARD_CACHE_KEY,
            value=cache_value,
            ttl=LEADERBOARD_CACHE_TTL
        )

        logger.info(f"[LEADERBOARD] Cache updated with {len(data.get('rankings', []))} ranked models")
        return True

    except Exception as e:
        logger.error(f"[LEADERBOARD] Failed to update cache: {e}", exc_info=True)
        return False


async def _get_cached_leaderboard_async() -> Optional[Dict[str, Any]]:
    """
    Get leaderboard data from cache.

    Returns:
        Cached leaderboard data or None if not found
    """
    try:
        cache_service = CacheService()
        cached = await cache_service.async_get(LEADERBOARD_CACHE_KEY)

        if cached:
            data = json.loads(cached)
            logger.debug(f"[LEADERBOARD] Retrieved {len(data.get('rankings', []))} models from cache")
            return data

        return None

    except Exception as e:
        logger.error(f"[LEADERBOARD] Failed to get from cache: {e}", exc_info=True)
        return None


@app.task(
    name='leaderboard.update_daily',
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minute retry delay
    soft_time_limit=600,  # 10 minute soft limit
    time_limit=660,  # 11 minute hard limit
)
def update_leaderboard_daily(self, category: str = "text"):
    """
    Daily task to update leaderboard data from external sources.

    This task:
    1. Fetches rankings from LMArena and OpenRouter
    2. Merges data using external_ids from provider YAMLs
    3. Saves aggregated data to backend/data/models_leaderboard.yml
    4. Updates the cache for fast access

    Runs daily at 2 AM UTC via Celery Beat.

    Args:
        category: LMArena category to fetch (default: "text")
    """
    task_id = self.request.id
    log_prefix = f"[Task ID: {task_id}]"

    logger.info(f"{log_prefix} [LEADERBOARD] Starting daily leaderboard update (category: {category})")

    try:
        # Run async aggregation
        data = asyncio.run(_aggregate_leaderboard_async(category))

        # Update cache
        cache_updated = asyncio.run(_update_cache_async(data))

        result = {
            "success": True,
            "category": category,
            "ranked_models": len(data.get("rankings", [])),
            "unranked_models": len(data.get("unranked", [])),
            "cache_updated": cache_updated,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"{log_prefix} [LEADERBOARD] Daily update completed. "
            f"Ranked: {result['ranked_models']}, Unranked: {result['unranked_models']}, "
            f"Cache updated: {cache_updated}"
        )

        return result

    except Exception as e:
        logger.error(f"{log_prefix} [LEADERBOARD] Daily update failed: {e}", exc_info=True)

        # Retry on failure
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"{log_prefix} [LEADERBOARD] Max retries exceeded for leaderboard update")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }


@app.task(
    name='leaderboard.refresh_cache',
    bind=True,
    soft_time_limit=60,
    time_limit=120,
)
def refresh_leaderboard_cache(self):
    """
    Refresh leaderboard cache from the saved YAML file.

    This task is useful for:
    - Startup cache warming
    - Manual cache refresh without re-fetching external data
    - Recovery after cache loss

    Does NOT fetch new data from external sources - use update_leaderboard_daily for that.
    """
    task_id = self.request.id
    log_prefix = f"[Task ID: {task_id}]"

    logger.info(f"{log_prefix} [LEADERBOARD] Refreshing cache from saved file")

    try:
        import yaml

        leaderboard_file = Path("/app/backend/data/models_leaderboard.yml")

        if not leaderboard_file.exists():
            logger.warning(f"{log_prefix} [LEADERBOARD] No saved leaderboard file found")
            return {
                "success": False,
                "error": "No saved leaderboard file",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        with open(leaderboard_file, 'r') as f:
            data = yaml.safe_load(f)

        if not data:
            logger.warning(f"{log_prefix} [LEADERBOARD] Empty leaderboard file")
            return {
                "success": False,
                "error": "Empty leaderboard file",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Update cache
        cache_updated = asyncio.run(_update_cache_async(data))

        result = {
            "success": True,
            "ranked_models": len(data.get("rankings", [])),
            "cache_updated": cache_updated,
            "source_timestamp": data.get("metadata", {}).get("generated_at"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"{log_prefix} [LEADERBOARD] Cache refreshed. "
            f"Ranked: {result['ranked_models']}, Cache updated: {cache_updated}"
        )

        return result

    except Exception as e:
        logger.error(f"{log_prefix} [LEADERBOARD] Cache refresh failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions for Other Services
# ═══════════════════════════════════════════════════════════════════════════════

async def get_leaderboard_data() -> Optional[Dict[str, Any]]:
    """
    Get leaderboard data from cache or file.

    This is the main entry point for services that need leaderboard data.
    Tries cache first, falls back to file if cache miss.

    Returns:
        Leaderboard data dict or None if not available
    """
    # Try cache first
    cached = await _get_cached_leaderboard_async()
    if cached:
        return cached

    # Fall back to file
    try:
        import yaml

        leaderboard_file = Path("/app/backend/data/models_leaderboard.yml")

        if leaderboard_file.exists():
            with open(leaderboard_file, 'r') as f:
                data = yaml.safe_load(f)

            # Update cache for next time
            if data:
                await _update_cache_async(data)

            return data

        return None

    except Exception as e:
        logger.error(f"[LEADERBOARD] Failed to load from file: {e}")
        return None


def get_ranked_models_for_task_area(
    leaderboard_data: Dict[str, Any],
    task_area: str,
    exclude_cn: bool = False
) -> list:
    """
    Get ranked model IDs filtered by task area and optionally exclude CN models.

    Args:
        leaderboard_data: Full leaderboard data
        task_area: Task area (code, math, creative, instruction, general)
        exclude_cn: If True, exclude models with country_origin=CN

    Returns:
        List of model_ids sorted by composite score (highest first)
    """
    rankings = leaderboard_data.get("rankings", [])

    if exclude_cn:
        rankings = [r for r in rankings if r.get("country_origin") != "CN"]

    # Return model IDs sorted by rank (already sorted in leaderboard)
    return [r["model_id"] for r in rankings if r.get("composite_score", 0) > 0]
