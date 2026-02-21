# backend/apps/ai/daily_inspiration/video_processor.py
# Video search and enrichment pipeline for the Daily Inspiration feature.
#
# Pipeline:
# 1. Brave video search → raw results (YouTube + others mixed)
# 2. Filter to YouTube-only results by extracting video IDs from URLs
# 3. Attempt YouTube Data API enrichment (view counts, likes, duration)
#    — gracefully falls back to Brave-provided metadata if API is unavailable
# 4. Sort by view count descending
# 5. Return top N candidates for LLM selection
#
# Privacy: No user data is passed to or stored by Brave or YouTube.

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.brave.brave_search import search_videos

logger = logging.getLogger(__name__)

# Number of raw Brave results to request per topic phrase
BRAVE_RESULTS_PER_QUERY = 20
# Top N candidates to pass to the LLM for selection (after enrichment and sort)
TOP_CANDIDATES_FOR_LLM = 20
# YouTube Data API endpoint
YOUTUBE_DATA_API_URL = "https://www.googleapis.com/youtube/v3/videos"
# Vault path for YouTube API key
YOUTUBE_SECRET_PATH = "kv/data/providers/youtube"
YOUTUBE_API_KEY_NAME = "api_key"


def _extract_youtube_id(url: str) -> Optional[str]:
    """
    Extract a YouTube video ID from a URL.

    Handles:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID

    Returns the 11-character video ID or None if not a YouTube URL.
    """
    if not url:
        return None

    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


async def _get_youtube_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieve the YouTube Data API key from Vault or environment.

    Returns None (with a debug log) if the key is not configured — the caller
    falls back to Brave-provided metadata in that case.
    """
    try:
        secret = await secrets_manager.get_secret(YOUTUBE_SECRET_PATH)
        if secret and isinstance(secret, dict):
            key = secret.get("data", {}).get("data", {}).get(YOUTUBE_API_KEY_NAME)
            if key:
                return key

        # Try environment variable fallback
        import os
        env_key = os.getenv("SECRET__YOUTUBE__API_KEY")
        if env_key:
            return env_key

        logger.debug("[DailyInspiration] YouTube API key not configured — skipping enrichment")
        return None
    except Exception as e:
        logger.debug(f"[DailyInspiration] Could not retrieve YouTube API key: {e}")
        return None


async def _enrich_with_youtube(
    candidates: List[Dict[str, Any]],
    secrets_manager: SecretsManager,
) -> List[Dict[str, Any]]:
    """
    Enrich candidate videos with YouTube Data API metadata (views, likes, duration).

    If the API key is unavailable or the request fails, returns candidates unchanged.
    Candidates are updated in-place with `view_count`, `duration_seconds`, and
    `published_at` fields where available.

    Args:
        candidates: List of candidate dicts with `youtube_id` key
        secrets_manager: For retrieving the YouTube API key

    Returns:
        Enriched (or unchanged) list of candidate dicts
    """
    api_key = await _get_youtube_api_key(secrets_manager)
    if not api_key:
        return candidates

    video_ids = [c["youtube_id"] for c in candidates if c.get("youtube_id")]
    if not video_ids:
        return candidates

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                YOUTUBE_DATA_API_URL,
                params={
                    "part": "statistics,contentDetails",
                    "id": ",".join(video_ids),
                    "key": api_key,
                },
            )
            response.raise_for_status()
            data = response.json()

        # Build lookup by video ID
        enrichment: Dict[str, Dict[str, Any]] = {}
        for item in data.get("items", []):
            vid_id = item.get("id")
            if not vid_id:
                continue
            stats = item.get("statistics", {})
            content_details = item.get("contentDetails", {})

            # Parse ISO 8601 duration → seconds (e.g. PT4M33S → 273)
            duration_seconds: Optional[int] = None
            iso_duration = content_details.get("duration", "")
            if iso_duration:
                match = re.match(
                    r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration
                )
                if match:
                    hours = int(match.group(1) or 0)
                    minutes = int(match.group(2) or 0)
                    seconds = int(match.group(3) or 0)
                    duration_seconds = hours * 3600 + minutes * 60 + seconds

            enrichment[vid_id] = {
                "view_count": int(stats.get("viewCount", 0)) if stats.get("viewCount") else None,
                "duration_seconds": duration_seconds,
            }

        # Apply enrichment to candidates
        for candidate in candidates:
            vid_id = candidate.get("youtube_id")
            if vid_id and vid_id in enrichment:
                candidate.update(enrichment[vid_id])

        logger.debug(
            f"[DailyInspiration] YouTube enrichment completed for {len(enrichment)}/{len(video_ids)} videos"
        )
    except Exception as e:
        logger.warning(
            f"[DailyInspiration] YouTube Data API enrichment failed (using Brave metadata): {e}"
        )

    return candidates


async def find_video_candidates(
    topic_phrase: str,
    secrets_manager: SecretsManager,
    language: str = "en",
    country: str = "us",
    search_lang: str = "en",
) -> List[Dict[str, Any]]:
    """
    Find and enrich YouTube video candidates for a given topic phrase.

    Full pipeline:
    1. Brave video search for the phrase (using the user's locale for better results)
    2. Filter to YouTube-only results
    3. YouTube Data API enrichment (view count, duration)
    4. Sort by view count descending
    5. Return top TOP_CANDIDATES_FOR_LLM results

    Args:
        topic_phrase: The inspiration phrase to search for (e.g., "Why cats always land on feet")
        secrets_manager: For provider API key retrieval
        language: User's UI language code (e.g. "en", "de"). Used for logging only;
                  actual Brave params are passed via ``country`` and ``search_lang``.
        country: ISO 3166-1 alpha-2 country code for Brave search localisation
        search_lang: Language code for Brave search results

    Returns:
        List of enriched candidate dicts (up to TOP_CANDIDATES_FOR_LLM), each with:
        - youtube_id: str
        - title: str
        - thumbnail_url: Optional[str]
        - channel_name: Optional[str]
        - view_count: Optional[int]
        - duration_seconds: Optional[int]
        - published_at: Optional[str]
    """
    logger.info(
        f"[DailyInspiration] Searching videos for phrase: '{topic_phrase}' "
        f"(lang={language}, country={country}, search_lang={search_lang})"
    )

    try:
        search_result = await search_videos(
            query=f"{topic_phrase} educational",
            secrets_manager=secrets_manager,
            count=BRAVE_RESULTS_PER_QUERY,
            country=country,
            search_lang=search_lang,
            safesearch="moderate",
            sanitize_output=False,  # No LLM sanitization needed for internal use
        )
    except Exception as e:
        logger.error(
            f"[DailyInspiration] Brave video search failed for '{topic_phrase}': {e}",
            exc_info=True,
        )
        return []

    raw_results = search_result.get("results", [])
    if not raw_results:
        logger.warning(f"[DailyInspiration] No Brave video results for '{topic_phrase}'")
        return []

    # Filter to YouTube-only and extract structured candidates
    candidates: List[Dict[str, Any]] = []
    for result in raw_results:
        url = result.get("url", "")
        youtube_id = _extract_youtube_id(url)
        if not youtube_id:
            continue  # Not a YouTube video — skip

        # Extract Brave-provided thumbnail
        thumbnail_url: Optional[str] = None
        thumb = result.get("thumbnail")
        if isinstance(thumb, dict):
            thumbnail_url = thumb.get("original")

        # Extract channel from video data (creator/channel field from Brave search result)
        channel_name: Optional[str] = None
        video_data = result.get("video")
        if isinstance(video_data, dict):
            channel_name = video_data.get("creator") or video_data.get("channel")

        # Parse published_at from page_age or similar
        published_at: Optional[str] = None
        page_age = result.get("page_age") or result.get("age")
        if page_age and isinstance(page_age, str):
            published_at = page_age[:10] if len(page_age) >= 10 else page_age

        candidates.append(
            {
                "youtube_id": youtube_id,
                "title": result.get("title", ""),
                "thumbnail_url": thumbnail_url,
                "channel_name": channel_name,
                "view_count": None,  # Will be filled by YouTube enrichment
                "duration_seconds": None,  # Will be filled by YouTube enrichment
                "published_at": published_at,
            }
        )

    if not candidates:
        logger.warning(
            f"[DailyInspiration] No YouTube videos found in Brave results for '{topic_phrase}'"
        )
        return []

    logger.debug(
        f"[DailyInspiration] Found {len(candidates)} YouTube candidates for '{topic_phrase}'"
    )

    # Enrich with YouTube Data API (view counts, duration)
    candidates = await _enrich_with_youtube(candidates, secrets_manager)

    # Sort by view count descending (None = 0 for sorting purposes)
    candidates.sort(
        key=lambda c: c.get("view_count") or 0,
        reverse=True,
    )

    top_candidates = candidates[:TOP_CANDIDATES_FOR_LLM]
    logger.info(
        f"[DailyInspiration] Returning {len(top_candidates)} enriched candidates for '{topic_phrase}'"
    )
    return top_candidates
