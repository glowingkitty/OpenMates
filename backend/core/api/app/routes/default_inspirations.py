# backend/core/api/app/routes/default_inspirations.py
#
# Public REST endpoint for fetching default Daily Inspiration entries.
#
# GET /v1/default-inspirations?lang={code}
#
# Returns up to 10 default inspirations for the requested language, selected
# daily from the inspiration pool by the Celery task (see default_inspiration_tasks.py).
#
# Data source: daily_inspiration_defaults table (denormalized, pre-populated daily).
# Results are cached in Redis for 1 hour (key: public:default_inspirations:v6:{lang}).
# Cache is invalidated when the daily selection task runs.
#
# Authentication: NOT required — this endpoint is public so the banner works for
# unauthenticated users too.

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

from fastapi import APIRouter, Request, Depends
from fastapi import HTTPException

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.apps.ai.daily_inspiration.generator import AVAILABLE_CATEGORIES
from backend.apps.ai.daily_inspiration.feature_suggestions import (
    build_feature_inspirations,
    feature_requires_authentication,
)
from backend.apps.ai.daily_inspiration.wiki_suggestions import build_wiki_inspirations

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["Default Inspirations"],
)

# Redis cache key prefix and TTL (must match default_inspiration_tasks.py)
_CACHE_KEY_PREFIX = "public:default_inspirations:v6:"
_CACHE_TTL = 3600  # 1 hour
_DEFAULT_INSPIRATION_COUNT = 10
_DEFAULT_WIKI_COUNT = 3
_DEFAULT_FEATURE_COUNT = 4

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


def _get_feature_id(item: Dict[str, Any]) -> str | None:
    feature = item.get("feature")
    return feature.get("feature_id") if isinstance(feature, dict) else None


def _is_public_feature_item(item: Dict[str, Any]) -> bool:
    if item.get("content_type") != "feature":
        return True

    feature = item.get("feature")
    if not isinstance(feature, dict):
        return False

    if "requires_authentication" in feature:
        return not bool(feature.get("requires_authentication"))

    return not feature_requires_authentication(feature.get("feature_id"))


def _get_wiki_title(item: Dict[str, Any]) -> str | None:
    wiki = item.get("wiki")
    return wiki.get("wiki_title") if isinstance(wiki, dict) else None


def _normalize_category(category: Any) -> str:
    if isinstance(category, str) and category in AVAILABLE_CATEGORIES:
        return category
    return "general_knowledge"


def _shuffle_daily_defaults(
    result: List[Dict[str, Any]],
    *,
    date_str: str,
    lang: str,
) -> None:
    random.Random(f"default-inspirations:{date_str}:{lang}").shuffle(result)


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
    Return up to 10 default Daily Inspirations for the given language.

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
    # Fall back to yesterday if today's defaults are missing (e.g. celery beat
    # restarted after the 06:30 UTC scheduled run and missed the task).
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    defaults = None
    selected_date_str = today_str
    for date_str in (today_str, yesterday_str):
        try:
            defaults = await directus_service.inspiration_defaults.get_defaults_for_date(
                date_str=date_str,
                language=lang,
            )
            if defaults:
                selected_date_str = date_str
                if date_str == yesterday_str:
                    logger.info(
                        "[DefaultInspirations] No defaults for today (%s), "
                        "using yesterday's (%s) for lang=%s",
                        today_str,
                        yesterday_str,
                        lang,
                    )
                break
        except Exception as e:
            logger.error(
                "[DefaultInspirations] Failed to fetch defaults for date=%s lang=%s: %s",
                date_str,
                lang,
                e,
                exc_info=True,
            )

    if not defaults:
        result = [
            insp.model_dump()
            for insp in build_wiki_inspirations(_DEFAULT_WIKI_COUNT)
        ]
        result.extend(
            insp.model_dump()
            for insp in build_feature_inspirations(
                _DEFAULT_INSPIRATION_COUNT - len(result),
                include_authenticated_only=False,
            )
        )
        if len(result) < _DEFAULT_INSPIRATION_COUNT:
            existing_wiki_titles = {_get_wiki_title(item) for item in result}
            for wiki_inspiration in build_wiki_inspirations(_DEFAULT_INSPIRATION_COUNT):
                wiki_title = wiki_inspiration.wiki.wiki_title if wiki_inspiration.wiki else None
                if wiki_title in existing_wiki_titles:
                    continue
                result.append(wiki_inspiration.model_dump())
                if len(result) >= _DEFAULT_INSPIRATION_COUNT:
                    break
        result = result[:_DEFAULT_INSPIRATION_COUNT]
        _shuffle_daily_defaults(result, date_str=today_str, lang=lang)
        return {"inspirations": result}

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
            "category": _normalize_category(record.get("category")),
            "content_type": record.get("content_type") or "video",
            "video": {
                "youtube_id": youtube_id,
                "title": record.get("video_title") or "",
                "thumbnail_url": thumbnail_url,
                "channel_name": record.get("video_channel_name"),
                "view_count": record.get("video_view_count"),
                "duration_seconds": record.get("video_duration_seconds"),
                "published_at": record.get("video_published_at"),
            } if youtube_id else None,
            "wiki": None,
            "feature": None,
            "generated_at": record.get("generated_at") or 0,
            "follow_up_suggestions": follow_up_suggestions,
        }
        for metadata_field, response_field in (
            ("wiki_metadata", "wiki"),
            ("feature_metadata", "feature"),
        ):
            raw_metadata = record.get(metadata_field)
            if isinstance(raw_metadata, str) and raw_metadata:
                try:
                    inspiration_obj[response_field] = json.loads(raw_metadata)
                except (json.JSONDecodeError, TypeError):
                    inspiration_obj[response_field] = None
            elif isinstance(raw_metadata, dict):
                inspiration_obj[response_field] = raw_metadata
        if _is_public_feature_item(inspiration_obj):
            result.append(inspiration_obj)

    wiki_count = sum(1 for item in result if item.get("content_type") == "wiki")
    if wiki_count < _DEFAULT_WIKI_COUNT:
        existing_wiki_titles = {_get_wiki_title(item) for item in result}
        for wiki_inspiration in build_wiki_inspirations(_DEFAULT_WIKI_COUNT):
            wiki_title = wiki_inspiration.wiki.wiki_title if wiki_inspiration.wiki else None
            if wiki_title in existing_wiki_titles:
                continue
            result.append(wiki_inspiration.model_dump())
            wiki_count = sum(
                1 for item in result if item.get("content_type") == "wiki"
            )
            if wiki_count >= _DEFAULT_WIKI_COUNT:
                break

    feature_count = sum(1 for item in result if item.get("content_type") == "feature")
    if feature_count < _DEFAULT_FEATURE_COUNT:
        existing_feature_ids = {_get_feature_id(item) for item in result}
        for feature_inspiration in build_feature_inspirations(
            _DEFAULT_FEATURE_COUNT,
            include_authenticated_only=False,
        ):
            feature_id = (
                feature_inspiration.feature.feature_id
                if feature_inspiration.feature
                else None
            )
            if feature_id in existing_feature_ids:
                continue
            result.append(feature_inspiration.model_dump())
            feature_count = sum(
                1 for item in result if item.get("content_type") == "feature"
            )
            if feature_count >= _DEFAULT_FEATURE_COUNT:
                break

    if len(result) < _DEFAULT_INSPIRATION_COUNT:
        existing_wiki_titles = {_get_wiki_title(item) for item in result}
        for wiki_inspiration in build_wiki_inspirations(_DEFAULT_INSPIRATION_COUNT):
            wiki_title = wiki_inspiration.wiki.wiki_title if wiki_inspiration.wiki else None
            if wiki_title in existing_wiki_titles:
                continue
            result.append(wiki_inspiration.model_dump())
            if len(result) >= _DEFAULT_INSPIRATION_COUNT:
                break

    if len(result) < _DEFAULT_INSPIRATION_COUNT:
        existing_feature_ids = {_get_feature_id(item) for item in result}
        for feature_inspiration in build_feature_inspirations(
            _DEFAULT_INSPIRATION_COUNT,
            include_authenticated_only=False,
        ):
            feature_id = (
                feature_inspiration.feature.feature_id
                if feature_inspiration.feature
                else None
            )
            if feature_id in existing_feature_ids:
                continue
            result.append(feature_inspiration.model_dump())
            if len(result) >= _DEFAULT_INSPIRATION_COUNT:
                break

    result = result[:_DEFAULT_INSPIRATION_COUNT]
    _shuffle_daily_defaults(result, date_str=selected_date_str, lang=lang)

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
