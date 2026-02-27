# backend/core/api/app/routes/default_inspirations.py
#
# Public REST endpoint for fetching default Daily Inspiration entries.
#
# GET /v1/default-inspirations?lang={code}
#
# Returns up to 3 default inspirations for the requested language, selected
# daily from the inspiration pool by the Celery task (see default_inspiration_tasks.py).
#
# Data source: daily_inspiration_defaults table (denormalized, pre-populated daily).
# Results are cached in Redis for 1 hour (key: public:default_inspirations:{lang}).
# Cache is invalidated when the daily selection task runs.
#
# Authentication: NOT required — this endpoint is public so the banner works for
# unauthenticated users too.

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from fastapi import APIRouter, Request, Depends
from fastapi import HTTPException

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["Default Inspirations"],
)

# Redis cache key prefix and TTL (must match default_inspiration_tasks.py)
_CACHE_KEY_PREFIX = "public:default_inspirations:"
_CACHE_TTL = 3600  # 1 hour

# Supported languages (same as SUPPORTED_LANGUAGES in default_inspiration_tasks.py)
_SUPPORTED_LANGUAGES = {
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it",
    "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv",
}


# ---- Service dependencies ------------------------------------------------


def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, "directus_service"):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def get_cache_service(request: Request) -> CacheService:
    if not hasattr(request.app.state, "cache_service"):
        logger.error("CacheService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.cache_service


# ---- Endpoint ------------------------------------------------------------


@router.get("/default-inspirations")
@limiter.limit("60/minute")
async def get_default_inspirations(
    request: Request,
    lang: str = "en",
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Return up to 3 default Daily Inspirations for the given language.

    The data comes from the daily_inspiration_defaults table, which is
    populated once per day by the daily selection Celery task.  Content is
    denormalized (no JOINs needed).

    The response is cached in Redis for 1 hour.  Cache is invalidated
    whenever the daily selection task runs.

    Query params:
    - lang: ISO 639-1 language code (default: 'en'). Falls back to 'en' if not supported.

    Returns:
    ```json
    {
      "inspirations": [
        {
          "inspiration_id": "pool_entry_id",
          "phrase": "...",
          "title": "...",
          "assistant_response": "...",
          "category": "...",
          "content_type": "video",
          "video": {
            "youtube_id": "...",
            "title": "...",
            "thumbnail_url": "...",
            "channel_name": "...",
            "view_count": 12345,
            "duration_seconds": 220,
            "published_at": "2024-01-01T00:00:00Z"
          },
          "generated_at": 1700000000,
          "follow_up_suggestions": ["...", "..."]
        }
      ]
    }
    ```
    """
    # Normalize language code -- fall back to 'en' if unsupported
    lang = lang.lower().strip()
    if lang not in _SUPPORTED_LANGUAGES:
        logger.debug(
            "[DefaultInspirations] Unsupported lang=%r, falling back to 'en'",
            lang,
        )
        lang = "en"

    cache_key = f"{_CACHE_KEY_PREFIX}{lang}"

    # ---- Try Redis cache -------------------------------------------------
    try:
        client = await cache_service.client
        if client:
            cached = await client.get(cache_key)
            if cached:
                data = json.loads(cached)
                logger.debug(
                    "[DefaultInspirations] Cache hit for lang=%s (%d items)",
                    lang,
                    len(data),
                )
                return {"inspirations": data}
    except Exception as e:
        logger.warning(
            "[DefaultInspirations] Cache read failed for lang=%s: %s", lang, e
        )

    # ---- Fetch today's defaults from daily_inspiration_defaults table -----
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        defaults = await directus_service.inspiration_defaults.get_defaults_for_date(
            date_str=today_str,
            language=lang,
        )
    except Exception as e:
        logger.error(
            "[DefaultInspirations] Failed to fetch defaults for date=%s lang=%s: %s",
            today_str,
            lang,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to fetch default inspirations"
        )

    if not defaults:
        return {"inspirations": []}

    # ---- Transform records to the DailyInspiration response shape ---------
    result: List[Dict[str, Any]] = []

    for record in defaults:
        youtube_id = record.get("youtube_id") or ""
        thumbnail_url = record.get("video_thumbnail_url") or (
            f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg"
            if youtube_id
            else ""
        )

        # Parse follow_up_suggestions (stored as JSON string in Directus)
        follow_up_raw = record.get("follow_up_suggestions", "[]")
        if isinstance(follow_up_raw, str):
            try:
                follow_up_suggestions = json.loads(follow_up_raw)
            except (json.JSONDecodeError, TypeError):
                follow_up_suggestions = []
        elif isinstance(follow_up_raw, list):
            follow_up_suggestions = follow_up_raw
        else:
            follow_up_suggestions = []

        inspiration_obj: Dict[str, Any] = {
            "inspiration_id": record.get("pool_entry_id") or record.get("id", ""),
            "phrase": record.get("phrase") or "",
            "title": record.get("title") or "",
            "assistant_response": record.get("assistant_response") or "",
            "category": record.get("category") or "",
            "content_type": record.get("content_type") or "video",
            "video": {
                "youtube_id": youtube_id,
                "title": record.get("video_title") or "",
                "thumbnail_url": thumbnail_url,
                "channel_name": record.get("video_channel_name"),
                "view_count": record.get("video_view_count"),
                "duration_seconds": record.get("video_duration_seconds"),
                "published_at": record.get("video_published_at"),
            },
            "generated_at": record.get("generated_at") or 0,
            "follow_up_suggestions": follow_up_suggestions,
        }
        result.append(inspiration_obj)

    # ---- Cache the response -----------------------------------------------
    try:
        client = await cache_service.client
        if client:
            await client.set(cache_key, json.dumps(result), ex=_CACHE_TTL)
            logger.debug(
                "[DefaultInspirations] Cached %d inspirations for lang=%s",
                len(result),
                lang,
            )
    except Exception as e:
        logger.warning(
            "[DefaultInspirations] Cache write failed for lang=%s: %s", lang, e
        )

    return {"inspirations": result}
