# backend/apps/ai/daily_inspiration/video_processor.py
# Video search and enrichment pipeline for the Daily Inspiration feature.
#
# Pipeline:
# 1. Brave video search → raw results (YouTube + others mixed)
# 2. Filter to YouTube-only results by extracting video IDs from URLs
# 3. Anti-corporate channel filtering (two layers):
#    a. Fast-path: check channel name against seed blocklist patterns
#    b. LLM-based: classify remaining channels as corporate or independent
#    Both layers ensure no company/brand PR channels reach the inspirations.
# 4. Attempt YouTube Data API enrichment (view counts, likes, duration)
#    — gracefully falls back to Brave-provided metadata if API is unavailable
# 5. Sort by view count descending
# 6. Return top N candidates for LLM selection
#
# Privacy: No user data is passed to or stored by Brave or YouTube.
#
# Architecture: Anti-corporate filtering is documented in
# docs/architecture/daily-inspiration-content-policy.md (if it exists).

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx
import yaml

from backend.apps.ai.utils.llm_utils import LLMPreprocessingCallResult, call_preprocessing_llm
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

# LLM model for lightweight channel classification (cheap, fast)
CHANNEL_CLASSIFIER_MODEL_ID = "mistral/mistral-small-2506"

# Path to the corporate channel seed blocklist YAML
_CORPORATE_PATTERNS_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "shared" / "config" / "corporate_channel_patterns.yml"
)

# Cache the loaded seed patterns so we don't re-parse the YAML on every request
_corporate_seed_patterns: Optional[List[str]] = None


def _load_corporate_seed_patterns() -> List[str]:
    """
    Load and cache the flat list of corporate channel name patterns from YAML.

    Returns a list of lowercase patterns for case-insensitive substring matching.
    On failure, logs a warning and returns an empty list (degraded but non-breaking).
    """
    global _corporate_seed_patterns
    if _corporate_seed_patterns is not None:
        return _corporate_seed_patterns

    try:
        with open(_CORPORATE_PATTERNS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        patterns: List[str] = []
        # Flatten all category lists into a single list of lowercase patterns
        for category_patterns in data.values():
            if isinstance(category_patterns, list):
                for pattern in category_patterns:
                    if isinstance(pattern, str):
                        patterns.append(pattern.lower())

        _corporate_seed_patterns = patterns
        logger.info(
            f"[DailyInspiration] Loaded {len(patterns)} corporate channel seed patterns from YAML"
        )
        return patterns
    except Exception as e:
        logger.warning(
            f"[DailyInspiration] Failed to load corporate channel patterns from "
            f"{_CORPORATE_PATTERNS_PATH}: {e} — fast-path filter disabled"
        )
        _corporate_seed_patterns = []
        return []


def _is_corporate_channel_fast_path(channel_name: Optional[str]) -> bool:
    """
    Fast-path check: return True if the channel name matches a known corporate pattern.

    Uses case-insensitive substring matching against the seed blocklist. This catches
    the most obvious corporate channels (e.g. 'BMW', 'Shell', 'Pfizer') without needing
    an LLM call.

    Args:
        channel_name: The YouTube channel name, or None if not available.

    Returns:
        True if the channel is likely corporate, False otherwise (including when
        channel_name is None — unknown channels are passed to LLM classification).
    """
    if not channel_name:
        return False
    lower = channel_name.lower()
    patterns = _load_corporate_seed_patterns()
    return any(pattern in lower for pattern in patterns)


async def _classify_channels_with_llm(
    candidates: List[Dict[str, Any]],
    secrets_manager: SecretsManager,
    task_id: str = "daily_inspiration",
) -> Set[str]:
    """
    Use an LLM to classify YouTube channel names as 'corporate' or 'independent'.

    Sends a batch of (channel_name, video_title) pairs to a lightweight model and
    returns the set of youtube_ids whose channels were classified as corporate.

    This is the second layer of anti-corporate filtering — it catches channels that
    don't match the seed patterns but are still clearly corporate (e.g. 'Bayer Science',
    'Shell Energy', 'Google DeepMind PR', etc.).

    Args:
        candidates: List of candidate dicts with 'youtube_id', 'channel_name', 'title'.
        secrets_manager: For LLM API key retrieval.
        task_id: For logging context.

    Returns:
        Set of youtube_ids that were classified as corporate and should be rejected.
        Returns empty set on LLM failure (fail-open: prefer some corporate content
        over silently dropping all candidates).
    """
    # Only classify candidates where we actually have a channel name
    classifiable = [c for c in candidates if c.get("channel_name")]
    if not classifiable:
        logger.debug(f"[DailyInspiration][{task_id}] No channel names available for LLM classification")
        return set()

    # Build channel list for classification
    channel_entries = []
    for c in classifiable:
        channel_entries.append(
            f'- youtube_id: "{c["youtube_id"]}" | channel: "{c["channel_name"]}" | title: "{c["title"][:80]}"'
        )

    channel_list_text = "\n".join(channel_entries)

    messages = [
        {
            "role": "user",
            "content": (
                "Classify each YouTube channel as 'corporate' or 'independent'.\n\n"
                "A channel is CORPORATE if it is owned by or officially represents a company, "
                "brand, or corporation of any kind — car manufacturers, oil companies, pharma, "
                "tech giants, banks, retailers, defense contractors, chemical companies, food "
                "corporations, consumer brands, PR agencies, lobbying groups, etc.\n\n"
                "A channel is INDEPENDENT if it belongs to an individual creator, educator, "
                "journalist, university, non-profit, documentary maker, or research institution "
                "that is NOT commercially owned by a corporation.\n\n"
                "Examples of CORPORATE channels: BMW, Shell, Pfizer, Google, Ford, Bayer, "
                "ExxonMobil, Nestlé, McKinsey, 'Tesla Official', 'Shell Energy', 'Bayer Science'.\n\n"
                "Examples of INDEPENDENT channels: Kurzgesagt, Veritasium, 3Blue1Brown, "
                "TED-Ed, SciShow, National Geographic (editorially independent), universities.\n\n"
                f"Channels to classify:\n{channel_list_text}\n\n"
                "For each entry, return its youtube_id and whether it is 'corporate' or 'independent'."
            ),
        }
    ]

    tool_definition = {
        "type": "function",
        "function": {
            "name": "classify_channels",
            "description": "Classify YouTube channels as corporate or independent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "classifications": {
                        "type": "array",
                        "description": "Classification result for each channel.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "youtube_id": {
                                    "type": "string",
                                    "description": "The YouTube video ID.",
                                },
                                "classification": {
                                    "type": "string",
                                    "enum": ["corporate", "independent"],
                                    "description": "Whether the channel is corporate or independent.",
                                },
                            },
                            "required": ["youtube_id", "classification"],
                        },
                    }
                },
                "required": ["classifications"],
            },
        },
    }

    try:
        result: LLMPreprocessingCallResult = await call_preprocessing_llm(
            task_id=f"{task_id}_channel_classifier",
            model_id=CHANNEL_CLASSIFIER_MODEL_ID,
            message_history=messages,
            tool_definition=tool_definition,
            secrets_manager=secrets_manager,
        )

        if result.error_message or not result.arguments:
            logger.warning(
                f"[DailyInspiration][{task_id}] Channel classifier LLM call failed: "
                f"{result.error_message} — skipping LLM classification (fail-open)"
            )
            return set()

        classifications = result.arguments.get("classifications", [])
        corporate_ids: Set[str] = set()
        for item in classifications:
            if isinstance(item, dict) and item.get("classification") == "corporate":
                youtube_id = item.get("youtube_id")
                if youtube_id:
                    corporate_ids.add(youtube_id)

        logger.info(
            f"[DailyInspiration][{task_id}] LLM channel classifier: "
            f"{len(corporate_ids)} corporate / {len(classifiable) - len(corporate_ids)} independent "
            f"out of {len(classifiable)} classified"
        )
        return corporate_ids

    except Exception as e:
        logger.warning(
            f"[DailyInspiration][{task_id}] Channel classifier LLM call raised exception: {e} "
            f"— skipping LLM classification (fail-open)",
            exc_info=True,
        )
        return set()


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

    Uses the same two-argument get_secret(path, key) signature as the shared
    youtube_metadata.py provider.  Returns None (with a warning log) if the key
    is not configured — the caller falls back to Brave-provided metadata.
    """
    try:
        # get_secret requires both secret_path and secret_key
        api_key = await secrets_manager.get_secret(
            secret_path=YOUTUBE_SECRET_PATH,
            secret_key=YOUTUBE_API_KEY_NAME,
        )
        if api_key:
            logger.info("[DailyInspiration] YouTube API key retrieved from Vault")
            return api_key

        logger.warning("[DailyInspiration] YouTube API key not configured — skipping enrichment")
        return None
    except Exception as e:
        logger.warning(f"[DailyInspiration] Could not retrieve YouTube API key: {e}")
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
                    "part": "snippet,statistics,contentDetails",
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

            # Extract published_at from snippet (ISO 8601 format, e.g. "2024-06-15T10:30:00Z")
            snippet = item.get("snippet", {})
            published_at_iso: Optional[str] = snippet.get("publishedAt")

            enrichment[vid_id] = {
                "view_count": int(stats.get("viewCount", 0)) if stats.get("viewCount") else None,
                "duration_seconds": duration_seconds,
                "published_at": published_at_iso,
            }

        # Apply enrichment to candidates
        for candidate in candidates:
            vid_id = candidate.get("youtube_id")
            if vid_id and vid_id in enrichment:
                candidate.update(enrichment[vid_id])

        logger.info(
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
    task_id: str = "daily_inspiration",
) -> List[Dict[str, Any]]:
    """
    Find and enrich YouTube video candidates for a given topic phrase.

    Full pipeline:
    1. Brave video search for the phrase (using the user's locale for better results)
    2. Filter to YouTube-only results
    3. Anti-corporate channel filtering — two layers:
       a. Fast-path: reject channels matching known corporate seed patterns
       b. LLM classification: reject remaining corporate channels identified by LLM
    4. YouTube Data API enrichment (view count, duration)
    5. Sort by view count descending
    6. Return top TOP_CANDIDATES_FOR_LLM results

    Args:
        topic_phrase: The inspiration phrase to search for (e.g., "Why cats always land on feet")
        secrets_manager: For provider API key retrieval
        language: User's UI language code (e.g. "en", "de"). Used for logging only;
                  actual Brave params are passed via ``country`` and ``search_lang``.
        country: ISO 3166-1 alpha-2 country code for Brave search localisation
        search_lang: Language code for Brave search results
        task_id: For logging context (passed through from the generation task)

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
        # Append "independent creator" to bias search results toward individual educators
        # and away from corporate official channels. This doesn't fully prevent corporate
        # results, but reduces their prevalence in the raw Brave results.
        search_result = await search_videos(
            query=f"{topic_phrase} educational independent creator",
            secrets_manager=secrets_manager,
            count=BRAVE_RESULTS_PER_QUERY,
            country=country,
            search_lang=search_lang,
            safesearch="strict",  # Strict safe search — filters adult/explicit content at source
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
    skipped_not_family_friendly = 0
    for result in raw_results:
        url = result.get("url", "")
        youtube_id = _extract_youtube_id(url)
        if not youtube_id:
            continue  # Not a YouTube video — skip

        # Reject videos that Brave explicitly marks as not family-friendly.
        # Brave's `family_friendly` field defaults to True when absent, so we only
        # skip results where it is explicitly False. Combined with safesearch="strict"
        # at the query level, this gives us a two-layer content filter.
        if result.get("family_friendly") is False:
            skipped_not_family_friendly += 1
            continue

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

        # NOTE: Brave's "page_age"/"age" field contains relative human-readable strings
        # like "2 days ago", NOT ISO 8601 dates. We skip it here and rely on the
        # YouTube Data API enrichment (snippet.publishedAt) for a proper date.
        published_at: Optional[str] = None

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

    if skipped_not_family_friendly > 0:
        logger.info(
            f"[DailyInspiration] Filtered out {skipped_not_family_friendly} non-family-friendly "
            f"video(s) from Brave results for '{topic_phrase}'"
        )

    if not candidates:
        logger.warning(
            f"[DailyInspiration] No YouTube videos found in Brave results for '{topic_phrase}'"
        )
        return []

    logger.debug(
        f"[DailyInspiration] Found {len(candidates)} YouTube candidates for '{topic_phrase}'"
    )

    # ── Anti-corporate channel filtering (two layers) ────────────────────────
    # Principle: inspirations must come from independent humans (educators,
    # journalists, documentary makers, universities) — never from corporate
    # PR channels of any company or brand. This filtering happens BEFORE YouTube
    # enrichment to avoid wasting API quota on videos we'll reject anyway.

    # Layer 1: Fast-path seed blocklist — reject channels matching known corporate patterns
    # without needing an LLM call. Catches obvious cases like BMW, Shell, Pfizer, etc.
    fast_path_rejected: List[str] = []
    after_fast_path: List[Dict[str, Any]] = []
    for candidate in candidates:
        if _is_corporate_channel_fast_path(candidate.get("channel_name")):
            fast_path_rejected.append(
                f"{candidate.get('channel_name')} ({candidate['youtube_id']})"
            )
        else:
            after_fast_path.append(candidate)

    if fast_path_rejected:
        logger.info(
            f"[DailyInspiration][{task_id}] Fast-path blocked {len(fast_path_rejected)} "
            f"corporate channel(s) for '{topic_phrase}': {fast_path_rejected}"
        )
    candidates = after_fast_path

    if not candidates:
        logger.warning(
            f"[DailyInspiration][{task_id}] All candidates rejected by fast-path corporate filter "
            f"for '{topic_phrase}' — no independent creators found"
        )
        return []

    # Layer 2: LLM-based channel classification — classify remaining candidates as
    # corporate or independent. Catches channels not in the seed list but still clearly
    # corporate (e.g. 'Bayer Science', 'Shell Energy', 'Google DeepMind Official').
    # Fails open: if the LLM call fails, all remaining candidates proceed unfiltered.
    corporate_youtube_ids = await _classify_channels_with_llm(
        candidates, secrets_manager, task_id=task_id
    )
    if corporate_youtube_ids:
        llm_rejected = [
            f"{c.get('channel_name')} ({c['youtube_id']})"
            for c in candidates
            if c["youtube_id"] in corporate_youtube_ids
        ]
        logger.info(
            f"[DailyInspiration][{task_id}] LLM blocked {len(corporate_youtube_ids)} "
            f"corporate channel(s) for '{topic_phrase}': {llm_rejected}"
        )
        candidates = [c for c in candidates if c["youtube_id"] not in corporate_youtube_ids]

    if not candidates:
        logger.warning(
            f"[DailyInspiration][{task_id}] All candidates rejected by LLM corporate filter "
            f"for '{topic_phrase}' — no independent creators found"
        )
        return []

    logger.info(
        f"[DailyInspiration][{task_id}] {len(candidates)} independent channel candidates "
        f"remaining after anti-corporate filtering for '{topic_phrase}'"
    )
    # ── End anti-corporate channel filtering ─────────────────────────────────

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
