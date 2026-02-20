# backend/core/api/app/routes/default_inspirations.py
#
# Public REST endpoint for fetching default Daily Inspiration entries.
#
# GET /v1/default-inspirations?lang={code}
#
# Returns up to 3 published inspirations translated into the requested language.
# Results are cached in Redis for 1 hour (key: public:default_inspirations:{lang}).
# Cache is invalidated when a new inspiration is published (see default_inspiration_tasks.py).
#
# Authentication: NOT required — this endpoint is public so the banner works for
# unauthenticated users too.

import json
import logging
from typing import Dict, Any, List, Optional

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

# Supported languages (same as TARGET_LANGUAGES in default_inspiration_tasks.py)
_SUPPORTED_LANGUAGES = {
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it",
    "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv",
}


# ─── Service dependencies ─────────────────────────────────────────────────────

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


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.get("/default-inspirations")
@limiter.limit("60/minute")
async def get_default_inspirations(
    request: Request,
    lang: str = "en",
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Return up to 3 published default Daily Inspirations for the given language.

    The response is cached for 1 hour. Cache is invalidated whenever an admin
    publishes a new default inspiration.

    Query params:
    - lang: ISO 639-1 language code (default: 'en'). Falls back to 'en' if not supported.

    Returns:
    ```json
    {
      "inspirations": [
        {
          "inspiration_id": "uuid",
          "phrase": "...",
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
          "generated_at": 1700000000
        }
      ]
    }
    ```
    """
    # Normalize language code — fall back to 'en' if unsupported
    lang = lang.lower().strip()
    if lang not in _SUPPORTED_LANGUAGES:
        logger.debug(
            f"[DefaultInspirations] Unsupported lang={lang!r}, falling back to 'en'"
        )
        lang = "en"

    cache_key = f"{_CACHE_KEY_PREFIX}{lang}"

    # ── Try Redis cache ───────────────────────────────────────────────────────
    try:
        client = await cache_service.client
        if client:
            cached = await client.get(cache_key)
            if cached:
                data = json.loads(cached)
                logger.debug(
                    f"[DefaultInspirations] Cache hit for lang={lang} ({len(data)} items)"
                )
                return {"inspirations": data}
    except Exception as e:
        logger.warning(f"[DefaultInspirations] Cache read failed for lang={lang}: {e}")

    # ── Fetch published inspirations from Directus ───────────────────────────
    try:
        published = await directus_service.suggested_inspiration.get_published_inspirations()
    except Exception as e:
        logger.error(
            f"[DefaultInspirations] Failed to fetch published inspirations: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch default inspirations")

    if not published:
        return {"inspirations": []}

    # ── For each record, load the translation for the requested language ──────
    result: List[Dict[str, Any]] = []

    for record in published:
        inspiration_id = record.get("id") or ""

        # Fetch translations for this inspiration
        try:
            translations = await directus_service.suggested_inspiration.get_translations(
                inspiration_id
            )
        except Exception as e:
            logger.warning(
                f"[DefaultInspirations] Could not fetch translations for {inspiration_id}: {e}"
            )
            translations = []

        # Build a lookup: language → translation row
        trans_by_lang: Dict[str, Dict[str, Any]] = {
            t.get("language", ""): t for t in translations
        }

        # Pick the best available translation: requested lang → 'en' → any
        trans = (
            trans_by_lang.get(lang)
            or trans_by_lang.get("en")
            or (translations[0] if translations else None)
        )

        phrase = (trans or {}).get("phrase") or record.get("phrase") or ""
        assistant_response = (trans or {}).get("assistant_response") or record.get("assistant_response") or ""

        # Build the DailyInspiration object (matches frontend DailyInspiration interface)
        video_id = record.get("video_id") or ""
        thumbnail_url = record.get("video_thumbnail") or (
            f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
        )

        inspiration_obj: Dict[str, Any] = {
            "inspiration_id": inspiration_id,
            "phrase": phrase,
            "category": record.get("category") or "",
            "content_type": "video",
            "assistant_response": assistant_response,
            "video": {
                "youtube_id": video_id,
                "title": record.get("video_title") or "",
                "thumbnail_url": thumbnail_url,
                "channel_name": record.get("video_channel_name"),
                "view_count": record.get("video_view_count"),
                "duration_seconds": record.get("video_duration_seconds"),
                "published_at": record.get("video_published_at"),
            },
            "generated_at": _iso_to_unix(record.get("approved_at")),
        }
        result.append(inspiration_obj)

    # ── Cache the response ────────────────────────────────────────────────────
    try:
        client = await cache_service.client
        if client:
            await client.set(cache_key, json.dumps(result), ex=_CACHE_TTL)
            logger.debug(
                f"[DefaultInspirations] Cached {len(result)} inspirations for lang={lang}"
            )
    except Exception as e:
        logger.warning(f"[DefaultInspirations] Cache write failed for lang={lang}: {e}")

    return {"inspirations": result}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _iso_to_unix(iso_str: Optional[str]) -> int:
    """Convert an ISO 8601 timestamp string to a Unix timestamp (seconds). Returns 0 on failure."""
    if not iso_str:
        return 0
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return 0
