# backend/core/api/app/tasks/default_inspiration_tasks.py
#
# Celery task for selecting today's default daily inspirations from the pool.
#
# Runs daily at 06:30 UTC (30 min after personalized generation at 06:00).
# For each language present in the pool, picks the top 3 entries by score
# and writes them to the daily_inspiration_defaults table.
#
# Scoring formula:
#   score = interaction_count / (age_in_hours + 1)
#
# This favors entries that are both popular (high interaction) and recent.
# New entries with zero interactions still get a score > 0 via the "+1" term.
#
# If a language has fewer than 3 entries, remaining slots are filled from English.
#
# After writing, old defaults (date < today) are cleaned up, and the
# public Redis cache for /v1/default-inspirations is invalidated.

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

logger = logging.getLogger(__name__)

# Redis cache key prefix for the public default-inspirations endpoint
_PUBLIC_CACHE_KEY_PREFIX = "public:default_inspirations:"

# Supported languages — same as the public API endpoint
SUPPORTED_LANGUAGES = {
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it",
    "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv",
}


def _score_pool_entry(entry: Dict[str, Any], now_ts: float) -> float:
    """
    Compute the recency-weighted interaction score for a pool entry.

    Formula: interaction_count / (age_in_hours + 1)
    - Higher interaction_count → higher score
    - More recent entries get a boost (smaller denominator)
    - The "+1" prevents division by zero and gives new entries a non-zero score
    """
    interaction_count = entry.get("interaction_count", 0) or 0
    generated_at = entry.get("generated_at", 0) or 0
    age_seconds = max(now_ts - generated_at, 0)
    age_hours = age_seconds / 3600.0
    return interaction_count / (age_hours + 1)


def _entry_id(entry: Dict[str, Any]) -> str:
    """Return normalized pool entry ID as a string (or empty string)."""
    return str(entry.get("id", "") or "")


def _pick_top_entries_with_exclusions(
    entries: List[Dict[str, Any]],
    excluded_pool_entry_ids: set[str],
    max_count: int,
) -> List[Dict[str, Any]]:
    """
    Pick top entries while avoiding excluded IDs when possible.

    Strategy:
    1) Prefer entries whose IDs are NOT in excluded_pool_entry_ids.
    2) If fewer than max_count are available, fill remaining slots with excluded
       entries to avoid returning fewer than 3 defaults.
    """
    selected: List[Dict[str, Any]] = []
    selected_ids: set[str] = set()

    for entry in entries:
        if len(selected) >= max_count:
            break
        entry_id = _entry_id(entry)
        if not entry_id or entry_id in selected_ids:
            continue
        if entry_id in excluded_pool_entry_ids:
            continue
        selected.append(entry)
        selected_ids.add(entry_id)

    if len(selected) >= max_count:
        return selected

    for entry in entries:
        if len(selected) >= max_count:
            break
        entry_id = _entry_id(entry)
        if not entry_id or entry_id in selected_ids:
            continue
        selected.append(entry)
        selected_ids.add(entry_id)

    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Celery task: select daily defaults
# ─────────────────────────────────────────────────────────────────────────────

@app.task(name="daily_inspiration.select_defaults", base=BaseServiceTask, bind=True)
def select_daily_inspiration_defaults(self):
    """
    Daily Celery task: select top 3 pool entries per language and write them
    to the daily_inspiration_defaults table.

    Scheduled by Beat at 06:30 UTC (after the 06:00 personalized generation).
    Also callable manually via the trigger script.
    """
    return asyncio.run(_select_defaults_async(self))


async def _select_defaults_async(task: BaseServiceTask) -> Dict[str, Any]:
    """Async implementation of select_daily_inspiration_defaults."""
    task_id = "daily_defaults_selection"
    logger.info(f"[DefaultsSelection][{task_id}] Daily defaults selection started")

    try:
        await task.initialize_services()
    except Exception as e:
        logger.error(
            f"[DefaultsSelection][{task_id}] Failed to initialize services: {e}",
            exc_info=True,
        )
        return {"success": False, "error": str(e)}

    directus = task._directus_service
    cache_service = task._cache_service

    if not directus:
        logger.error(f"[DefaultsSelection][{task_id}] DirectusService unavailable")
        return {"success": False, "error": "DirectusService not initialized"}

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    now_ts = time.time()

    # ── Discover which languages have pool entries ─────────────────────────
    try:
        pool_languages = await directus.inspiration_pool.get_pool_languages()
    except Exception as e:
        logger.error(
            f"[DefaultsSelection][{task_id}] Failed to get pool languages: {e}",
            exc_info=True,
        )
        return {"success": False, "error": str(e)}

    if not pool_languages:
        logger.info(f"[DefaultsSelection][{task_id}] Pool is empty — no defaults to select")
        return {"success": True, "languages_processed": 0, "message": "Pool empty"}

    logger.info(
        f"[DefaultsSelection][{task_id}] Pool has entries in {len(pool_languages)} language(s): "
        f"{', '.join(sorted(pool_languages))}"
    )

    # ── Fetch English pool entries (used as fallback) ─────────────────────
    en_entries: List[Dict[str, Any]] = []
    if "en" in pool_languages:
        en_entries = await directus.inspiration_pool.get_pool_entries_by_language("en", limit=50)

    # Score and sort English entries
    en_scored = sorted(
        en_entries,
        key=lambda e: _score_pool_entry(e, now_ts),
        reverse=True,
    )

    languages_processed = 0
    total_defaults_written = 0

    # ── Process each language ─────────────────────────────────────────────
    # Process all supported languages, not just those in pool_languages.
    # Languages not in the pool will get English fallback entries.
    all_languages = sorted(SUPPORTED_LANGUAGES)

    for lang in all_languages:
        try:
            previous_defaults = await directus.inspiration_defaults.get_defaults_for_date(
                date_str=yesterday_str,
                language=lang,
            )
            excluded_pool_entry_ids = {
                str(item.get("pool_entry_id", "") or "")
                for item in previous_defaults
                if item.get("pool_entry_id")
            }

            if lang in pool_languages:
                entries = await directus.inspiration_pool.get_pool_entries_by_language(
                    lang, limit=50
                )
            else:
                entries = []

            # Score and sort
            scored = sorted(
                entries,
                key=lambda e: _score_pool_entry(e, now_ts),
                reverse=True,
            )

            # Pick top 3 while avoiding yesterday's defaults when possible.
            selected = _pick_top_entries_with_exclusions(
                scored,
                excluded_pool_entry_ids,
                3,
            )

            if len(selected) < 3 and lang != "en":
                # Fill remaining slots from English, avoiding duplicate youtube_ids
                selected_yt_ids = {e.get("youtube_id") for e in selected}
                en_candidates = _pick_top_entries_with_exclusions(
                    en_scored,
                    excluded_pool_entry_ids,
                    len(en_scored),
                )
                for en_entry in en_candidates:
                    if len(selected) >= 3:
                        break
                    if en_entry.get("youtube_id") not in selected_yt_ids:
                        selected.append(en_entry)
                        selected_yt_ids.add(en_entry.get("youtube_id"))

            logger.info(
                "[DefaultsSelection][%s] lang=%s yesterday_excluded=%d selected=%d",
                task_id,
                lang,
                len(excluded_pool_entry_ids),
                len(selected),
            )

            if not selected:
                logger.debug(
                    f"[DefaultsSelection][{task_id}] No entries available for lang={lang} — skipping"
                )
                continue

            # Write to defaults table
            written = await directus.inspiration_defaults.set_defaults_for_date(
                date_str=today_str,
                language=lang,
                pool_entries=selected,
            )
            total_defaults_written += written
            languages_processed += 1

        except Exception as e:
            logger.error(
                f"[DefaultsSelection][{task_id}] Error processing lang={lang}: {e}",
                exc_info=True,
            )

    # ── Clean up old defaults ─────────────────────────────────────────────
    try:
        deleted = await directus.inspiration_defaults.delete_old_defaults(today_str)
        if deleted > 0:
            logger.info(
                f"[DefaultsSelection][{task_id}] Cleaned up {deleted} old default entries"
            )
    except Exception as e:
        logger.warning(
            f"[DefaultsSelection][{task_id}] Old defaults cleanup failed: {e}"
        )

    # ── Invalidate public Redis cache ──────────────────────────────────────
    await _invalidate_public_cache(cache_service)

    result = {
        "success": True,
        "date": today_str,
        "languages_processed": languages_processed,
        "total_defaults_written": total_defaults_written,
    }
    logger.info(
        f"[DefaultsSelection][{task_id}] Completed: {languages_processed} languages, "
        f"{total_defaults_written} defaults written for {today_str}"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _invalidate_public_cache(cache_service: Any) -> None:
    """
    Invalidate all per-language Redis cache entries for the public
    default-inspirations endpoint.
    """
    try:
        if not cache_service:
            return
        client = await cache_service.client
        if not client:
            return

        pattern = f"{_PUBLIC_CACHE_KEY_PREFIX}*"
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=50)
            for key in keys:
                await client.delete(key)
                deleted += 1
            if cursor == 0:
                break

        if deleted > 0:
            logger.info(
                f"[DefaultsSelection] Invalidated {deleted} public cache entries"
            )
    except Exception as e:
        logger.warning(f"[DefaultsSelection] Failed to invalidate public cache: {e}")
