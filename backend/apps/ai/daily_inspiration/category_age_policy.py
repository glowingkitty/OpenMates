# backend/apps/ai/daily_inspiration/category_age_policy.py
#
# Category-based maximum-age policy for Daily Inspiration YouTube videos.
#
# Problem this solves (OPE-350): inspiration cards were surfacing ~11-year-old
# videos for time-sensitive topics (finance, tech, news). A blanket cutoff would
# kill genuinely evergreen content (history, cooking, psychology), so we use
# a per-category maximum age instead, plus a blanket hard cutoff that applies
# to every category to prevent the LLM from mislabelling stale content.
#
# Buckets:
#   strict    (3y):  software_development, finance, marketing_sales,
#                    business_development, activism
#   medium    (5y):  science, medical_health, electrical_engineering,
#                    maker_prototyping
#   loose     (10y): design
#   evergreen (None / uncapped): history, movies_tv, life_coach_psychology,
#                    cooking_food, general_knowledge
#
# Hard cutoff (10y) is applied pre-LLM in video_processor.py and defends against
# the LLM picking "history" as a category cover to bypass caps.
#
# Fail-open policy: missing or unparseable `published_at` values are treated as
# "allowed". This prevents nuking legacy pool rows that lack YouTube API
# enrichment, and avoids dropping Brave-only candidates before enrichment.

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# Approximate seconds in a Julian year (365.25 days). Precision is sufficient
# for 3/5/10-year bucket comparisons.
_SECONDS_PER_YEAR = 365.25 * 24 * 3600

# Blanket floor applied pre-LLM to every candidate, regardless of category.
# Anything older than this never reaches the LLM candidate list.
HARD_CUTOFF_YEARS = 10

# Per-bucket limits (years).
STRICT_MAX_YEARS = 3
MEDIUM_MAX_YEARS = 5
LOOSE_MAX_YEARS = 10

# Unknown categories fall back to the loose cap — safer than evergreen when
# we don't actually know the topic.
DEFAULT_MAX_AGE_YEARS = LOOSE_MAX_YEARS

# Single source of truth mapping category → max age in years.
# None means evergreen (no cap).
#
# Must stay in sync with AVAILABLE_CATEGORIES in
# backend/apps/ai/daily_inspiration/generator.py. A unit test asserts the sets
# match.
CATEGORY_MAX_AGE_YEARS: dict[str, Optional[int]] = {
    # strict — time-sensitive: frameworks change, markets move, news cycles turn
    "software_development": STRICT_MAX_YEARS,
    "business_development": STRICT_MAX_YEARS,
    "marketing_sales": STRICT_MAX_YEARS,
    "finance": STRICT_MAX_YEARS,
    "activism": STRICT_MAX_YEARS,
    # medium — findings, recommendations, and hardware evolve but not weekly
    "science": MEDIUM_MAX_YEARS,
    "medical_health": MEDIUM_MAX_YEARS,
    "electrical_engineering": MEDIUM_MAX_YEARS,
    "maker_prototyping": MEDIUM_MAX_YEARS,
    # loose — fundamentals drift slowly
    "design": LOOSE_MAX_YEARS,
    # evergreen — genuinely timeless content
    "history": None,
    "movies_tv": None,
    "life_coach_psychology": None,
    "cooking_food": None,
    "general_knowledge": None,
}


PolicyBucket = Literal["strict", "medium", "loose", "evergreen", "unknown"]


def parse_published_at(value: Optional[str]) -> Optional[datetime]:
    """
    Parse an ISO 8601 publication date string into a UTC-aware datetime.

    Accepts both the `Z` suffix (normalised to `+00:00`) and explicit offsets.
    Naive datetimes are assumed UTC. Returns None on empty/None/garbage —
    never raises.

    Args:
        value: ISO 8601 date string (e.g. "2024-06-15T10:30:00Z") or None.

    Returns:
        UTC-aware datetime, or None if the input is missing or unparseable.
    """
    if not value:
        return None
    try:
        normalised = value.strip()
        if normalised.endswith("Z"):
            normalised = normalised[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        logger.debug("[CategoryAgePolicy] Unparseable published_at value: %r", value)
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def video_age_years(
    published_at: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """
    Compute a video's age in (fractional) years.

    Future-dated videos (negative age — e.g. clock skew) are clamped to 0.0.
    Returns None when the date is missing or unparseable so callers can
    apply their own fail-open handling.

    Args:
        published_at: ISO 8601 date string or None.
        now: Injectable reference timestamp for tests. Defaults to
             `datetime.now(timezone.utc)`.

    Returns:
        Fractional years (>= 0.0), or None if unknown.
    """
    parsed = parse_published_at(published_at)
    if parsed is None:
        return None
    reference = now or datetime.now(timezone.utc)
    delta_seconds = (reference - parsed).total_seconds()
    if delta_seconds < 0:
        return 0.0
    return delta_seconds / _SECONDS_PER_YEAR


def get_max_age_years(category: Optional[str]) -> Optional[int]:
    """
    Return the max-age cap (in years) for a category, or None for evergreen.

    Unknown categories fall back to `DEFAULT_MAX_AGE_YEARS` (loose, 10y) —
    safer than evergreen when we don't actually know the topic.
    """
    if category and category in CATEGORY_MAX_AGE_YEARS:
        return CATEGORY_MAX_AGE_YEARS[category]
    return DEFAULT_MAX_AGE_YEARS


def is_within_hard_cutoff(
    published_at: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> bool:
    """
    Blanket pre-LLM filter: is this video within the global hard cutoff?

    Fails open on missing/unparseable dates (returns True). Applied to every
    candidate regardless of category, so evergreen categories can't be abused
    to smuggle a 15-year-old video into the feed — anything over
    `HARD_CUTOFF_YEARS` is rejected before the LLM ever sees it.
    """
    age = video_age_years(published_at, now=now)
    if age is None:
        return True  # fail open
    return age <= HARD_CUTOFF_YEARS


def is_within_category_policy(
    category: Optional[str],
    published_at: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> bool:
    """
    Category-specific policy check: is this video within its category's cap?

    Evergreen categories (cap=None) always pass. Missing/unparseable
    `published_at` always passes (fail open — prevents nuking legacy pool rows
    that were stored before enrichment was reliable).
    """
    max_age = get_max_age_years(category)
    if max_age is None:
        return True  # evergreen
    age = video_age_years(published_at, now=now)
    if age is None:
        return True  # fail open on missing/unparseable dates
    return age <= max_age


def policy_bucket_for_category(category: Optional[str]) -> PolicyBucket:
    """
    Classify a category into a bucket name for structured logging.
    """
    if not category or category not in CATEGORY_MAX_AGE_YEARS:
        return "unknown"
    cap = CATEGORY_MAX_AGE_YEARS[category]
    if cap is None:
        return "evergreen"
    if cap == STRICT_MAX_YEARS:
        return "strict"
    if cap == MEDIUM_MAX_YEARS:
        return "medium"
    return "loose"


def describe_policy_for_prompt() -> str:
    """
    Return a human-readable policy description suitable for LLM prompts.

    Kept English-only because the LLM tool definitions and instruction blocks
    in generator.py are already written in English even when the user-facing
    output is in another language.
    """
    return (
        "VIDEO AGE POLICY: Strongly prefer the most recent video available. "
        "For software development, finance, marketing, business, and activism "
        "topics, avoid videos older than 3 years. For science, health, "
        "engineering, and maker topics, prefer videos within 5 years. For "
        "design topics, within 10 years. For history, movies/TV, psychology, "
        "cooking, and general knowledge, any age is acceptable — classic and "
        "timeless content is welcome. Each candidate's publication date is "
        "shown in the list; use it when choosing."
    )
