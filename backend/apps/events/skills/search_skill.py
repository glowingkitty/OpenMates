# backend/apps/events/skills/search_skill.py
#
# Events search skill — multi-provider event discovery.
#
# Searches for public events (meetups, conferences, hackathons, workshops, etc.)
# using one or more providers simultaneously. Supported providers:
#   - meetup:            Meetup.com internal GraphQL (lat/lon, global, includes descriptions)
#   - luma:              Luma.com internal REST API (78 featured cities, includes descriptions)
#   - eventbrite:        Eventbrite web API search (includes descriptions via event pages)
#   - google_events:     Google Events via SerpAPI (aggregates Eventbrite, Ticketmaster, etc.)
#   - resident_advisor:  RA (ra.co) scraping — electronic music, clubs, DJ events
#   - siegessaeule:      Siegessäule scraping — Berlin LGBTQ+ events (Berlin-only)
#
# Provider selection via the 'provider' request field:
#   "auto"              (default) — searches all applicable providers in parallel, merges results
#   "meetup"            — Meetup only
#   "luma"              — Luma only (requires city to be in Luma's 78 featured cities)
#   "eventbrite"        — Eventbrite only (caps at 10 results with descriptions)
#   "google_events"     — Google Events only (requires SerpAPI key)
#   "resident_advisor"  — Resident Advisor only (electronic music cities)
#   "siegessaeule"      — Siegessäule only (Berlin LGBTQ+ events)
#
# In "auto" mode, all providers are queried simultaneously. Results from all
# providers are merged, deduplicated by URL, sorted by date, and sliced to count.
#
# Architecture:
#   - Direct async execution in the app-events container (no Celery task dispatch)
#   - Each request in the 'requests' array is processed independently
#   - Multiple requests are processed in parallel via asyncio.gather
#   - Within each request, all providers run concurrently via asyncio.gather
#
# Pricing: 5 credits per request
#   Cost basis: Meetup ~200 KB via Webshare proxy + Luma list + description pages
#   The 5-credit price covers both provider costs with comfortable margin.
#
# See docs/apis/luma.md for Luma integration details.

import asyncio
from datetime import datetime
import logging
import os
import re
import unicodedata
import yaml
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery import Celery  # For type hinting only
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.events.providers import berlin_philharmonic as berlin_philharmonic_provider
from backend.apps.events.providers import eventbrite as eventbrite_provider
from backend.apps.events.providers import google_events as google_events_provider
from backend.apps.events.providers import luma as luma_provider
from backend.apps.events.providers import meetup as meetup_provider
from backend.apps.events.providers import pretalx as pretalx_provider
from backend.apps.events.providers import resident_advisor as ra_provider
from backend.apps.events.providers import siegessaeule as siegessaeule_provider
from backend.apps.events.providers.registry import filter_providers
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.search_relevance import (
    MAX_RELEVANCE_CRITERIA_CHARS,
    normalize_relevance_criteria,
    normalize_url_for_deduplication,
    rank_search_candidates,
    relevance_candidate_target,
    stable_deduplicate_candidates,
)

logger = logging.getLogger(__name__)

# Valid provider values. "auto" runs all applicable providers in parallel.
_VALID_PROVIDERS = {"auto", "meetup", "luma", "eventbrite", "google_events", "resident_advisor", "siegessaeule", "berlin_philharmonic", "pretalx"}

# Normalize provider names from LLM tool calls (e.g. "Google Events" -> "google_events").
_PROVIDER_ALIASES: Dict[str, str] = {
    "none": "auto",
    "google events": "google_events",
    "google": "google_events",
    "googleevents": "google_events",
    "serpapi": "google_events",
    "event brite": "eventbrite",
    "eventbrite.com": "eventbrite",
    "eb": "eventbrite",
    "resident advisor": "resident_advisor",
    "residentadvisor": "resident_advisor",
    "ra": "resident_advisor",
    "ra.co": "resident_advisor",
    "siegessäule": "siegessaeule",
    "siegessaule": "siegessaeule",
    "berlin philharmonic": "berlin_philharmonic",
    "berliner philharmoniker": "berlin_philharmonic",
    "bphil": "berlin_philharmonic",
    "pretalx": "pretalx",
    "gpn": "pretalx",
    "gpn24": "pretalx",
    "39c3": "pretalx",
    "38c3": "pretalx",
    "37c3": "pretalx",
    "chaos congress": "pretalx",
    "chaos communication congress": "pretalx",
}

_PROVIDER_LABELS: Dict[str, str] = {
    "meetup": "Meetup",
    "luma": "Luma",
    "eventbrite": "Eventbrite",
    "google_events": "Google Events",
    "resident_advisor": "Resident Advisor",
    "siegessaeule": "Siegessäule",
    "berlin_philharmonic": "Berlin Philharmonic",
    "pretalx": "GPN24/39C3/38C3/37C3",
}

# Platform-brand and generic filler words that narrow provider results unnecessarily.
# Providers use literal keyword matching — passing platform names like "meetup",
# "luma", or "eventbrite" narrows results unnecessarily. "event/events" is
# equally useless on an events platform.
_QUERY_STOPWORDS: frozenset = frozenset({
    "meetup", "meetups",
    "luma",
    "eventbrite",
    "event", "events",
    "google",
})


def _sanitize_query(query: str) -> str:
    """Strip platform-brand and filler stopwords from an event search query.

    Both Meetup and Luma do literal keyword matching, so including the platform
    name or generic words like "event" in the query dramatically reduces results.

    Examples:
        "AI meetup"        -> "AI"
        "tech meetup"      -> "tech"
        "Python events"    -> "Python"
        "luma tech events" -> "tech"
        "meetup"           -> ""  (caller falls back to original query)

    Returns empty string if every word is a stopword (caller preserves original).
    """
    words = query.strip().split()
    filtered = [w for w in words if w.lower() not in _QUERY_STOPWORDS]
    return " ".join(filtered).strip()

# Default number of events to return per request.
_DEFAULT_COUNT = 10

# When fetching from multiple providers in auto mode, request more than needed
# from each provider so we have enough after deduplication. Fetch 2x count per
# provider, then merge + deduplicate + slice to count.
_AUTO_PROVIDER_MULTIPLIER = 2

# Location-free online discovery is supported only by providers whose public
# search contracts do not require a city or coordinates.
_LOCATION_FREE_ONLINE_PROVIDERS = {"eventbrite", "google_events"}

# Jev's events rubric assigns 1 to a weak but defensible relationship. Results
# below that floor are omitted instead of padding the response with unrelated
# events. Ranking failures still use the deterministic unfiltered fallback.
_MIN_EVENT_RELEVANCE_SCORE = 1.0

_EVENT_TITLE_DEDUP_STOPWORDS = frozenset({
    "a", "an", "and", "at", "berlin", "event", "events", "in", "meetup",
    "new", "of", "on", "online", "paris", "san", "francisco", "sept",
    "september", "the", "tokyo", "workshop",
})


# ---------------------------------------------------------------------------
# Pydantic models (auto-discovered by apps_api.py for OpenAPI documentation)
# ---------------------------------------------------------------------------


class SearchRequestItem(BaseModel):
    """A single event search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    query: Optional[str] = Field(
        default=None,
        description="Topic or theme of events to search for (e.g. 'AI', 'Python', 'hackathon', "
        "'startup', 'networking'). Required for city searches; optional when conference is set. "
        "Do NOT include platform names like 'meetup', 'luma', or 'eventbrite'."
    )
    location: Optional[str] = Field(
        default=None,
        description="City name or 'city, country' string (e.g. 'Berlin, Germany', 'New York'). "
        "Used if lat/lon are not provided. Optional for location-free ONLINE searches.",
    )
    lat: Optional[float] = Field(
        default=None,
        description="Latitude of search center (decimal degrees). Overrides location string if provided.",
    )
    lon: Optional[float] = Field(
        default=None,
        description="Longitude of search center (decimal degrees). Overrides location string if provided.",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start of date range in ISO 8601 format with optional matching IANA timezone annotation. Defaults to now if omitted.",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End of date range in ISO 8601 format. No upper bound if omitted.",
    )
    event_type: Optional[str] = Field(
        default=None,
        description="Filter by event type: 'PHYSICAL' (default for city searches) or 'ONLINE' (virtual events).",
    )
    radius_miles: float = Field(
        default=25,
        description="Search radius in miles from the center coordinates (default: 25, ~40 km). Only for PHYSICAL events.",
    )
    count: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of events to return (default: 10, max: 50).",
    )
    relevance_criteria: Optional[str] = Field(
        default=None,
        max_length=MAX_RELEVANCE_CRITERIA_CHARS,
        description=(
            "Optional concise natural-language event-selection goal used to rank a larger "
            "candidate pool. Populate it when the user states a material purpose such as "
            "networking, promoting a product, or finding future speaking opportunities; "
            "omit it for a plain event search and never invent preferences."
        ),
    )
    provider: Optional[str] = Field(
        default=None,
        description="Provider to use for this request. Overrides top-level provider if set.",
    )
    providers: Optional[List[str]] = Field(
        default=None,
        description="Provider list to use for this request. Overrides top-level providers if set.",
    )
    concert_tags: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional tag filters for the Berlin Philharmonic provider. "
            "Known values: Piano, Chamber Music, Jazz, Organ, Modern, "
            "Lunch Concerts, Singers, Children and Family, World. "
            "Ignored by all other providers."
        ),
    )
    conference: Optional[str] = Field(
        default=None,
        description=(
            "Known conference schedule to search with the Conference Schedule provider. "
            "Supported values include GPN24, 39C3, 38C3, and 37C3."
        ),
    )
    past_events: bool = Field(
        default=False,
        description=(
            "When false, conference schedule searches return only current and upcoming sessions. "
            "Set true to include sessions that have already ended."
        ),
    )


class SearchRequest(BaseModel):
    """
    Request model for event search skill.

    Always uses 'requests' array format for consistency and parallel processing.
    Each request specifies its own parameters; defaults are defined in tool_schema.
    """

    requests: List[SearchRequestItem] = Field(
        ...,
        description=(
            "Array of event search request objects. Each object must contain 'query' "
            "and 'location' (or 'lat'/'lon') for physical city searches, 'event_type=ONLINE' "
            "for location-free online discovery, or 'conference' for Conference Schedule "
            "searches. Optional: start_date, end_date, event_type, "
            "radius_miles, count, past_events."
        ),
    )
    provider: Optional[str] = Field(
        default=None,
        description="Top-level provider applied to every request unless overridden per request.",
    )
    providers: Optional[List[str]] = Field(
        default=None,
        description="Top-level provider list applied to every request unless overridden per request.",
    )


class SearchResponse(BaseModel):
    """Response model for event search skill."""

    # Results grouped by request ID. Each entry: {'id': ..., 'results': [...]}
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of request results. Each entry contains 'id' (matching the "
            "request id) and 'results' array with event dicts."
        ),
    )
    provider: str = Field(
        default="auto",
        description=(
            "The provider(s) used. 'auto' means all applicable providers were searched."
        ),
    )
    providers: List[str] = Field(
        default_factory=list,
        description=(
            "List of provider IDs searched for the request "
            "(e.g. ['meetup', 'luma', 'eventbrite', 'google_events']). "
            "Providers can be present even when they returned zero results."
        ),
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on search results.",
    )
    error: Optional[str] = Field(None, description="Error message if the skill failed.")
    warnings: List[str] = Field(default_factory=list, description="Providers that failed during a partial search.")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "cover_url",    # Image URL — not useful for LLM reasoning
            "image_url",    # Image URL — not useful for LLM reasoning
        ],
        description=(
            "Fields excluded from LLM inference to reduce token usage. "
            "Preserved in chat history for UI rendering."
        ),
    )


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------


class SearchSkill(BaseSkill):
    """
    Events search skill — multi-provider event discovery.

    Supports multiple parallel search requests via the 'requests' array pattern.
    Each request can specify its own provider, location, date range, and filters.

    In "auto" mode (default), all applicable providers are queried simultaneously.
    Results are merged, deduplicated by URL, sorted by start date, and limited to
    the requested count.

    Execution model: direct async in app-events FastAPI container.
    No Celery dispatch — search completes in 1-5s, well within sync timeout.
    """

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve selected event providers before provider calls start."""
        raw_providers = request.get("providers")
        if isinstance(raw_providers, list) and raw_providers:
            provider_ids = [
                _PROVIDER_ALIASES.get(str(provider).lower().strip(), str(provider).lower().strip())
                for provider in raw_providers
            ]
        else:
            provider_choice = str(request.get("provider", "auto")).lower().strip()
            provider_choice = _PROVIDER_ALIASES.get(provider_choice, provider_choice)
            provider_ids = (
                [provider_choice]
                if provider_choice in _VALID_PROVIDERS and provider_choice != "auto"
                else [provider_id for provider_id in _PROVIDER_LABELS]
            )

        providers = [provider_id for provider_id in provider_ids if provider_id in _PROVIDER_LABELS]
        provider = providers[0] if len(providers) == 1 else "auto"
        return {"provider": provider, "providers": providers}

    def __init__(
        self,
        app: Any,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer: Optional[Celery] = None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialise SearchSkill.

        Args:
            app:                        BaseApp instance (required by BaseSkill)
            app_id:                     App identifier ('events')
            skill_id:                   Skill identifier ('search')
            skill_name:                 Display name for the skill
            skill_description:          Description of what the skill does
            stage:                      Deployment stage ('development' / 'production')
            full_model_reference:       Unused for this skill (no LLM calls)
            pricing_config:             Pricing configuration (5 credits per request)
            celery_producer:            Unused for this skill (direct async execution)
            skill_operational_defaults: Optional per-skill config from app.yml
        """
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
        )

        if skill_operational_defaults:
            logger.debug(
                "SearchSkill '%s' received operational_defaults: %s",
                self.skill_name,
                skill_operational_defaults,
            )

        self.suggestions_follow_up_requests: List[str] = []
        self._providers_meta: List[Dict[str, Any]] = []
        self._load_config_from_app_yml()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_event_type(value: Any) -> Optional[str]:
        """Normalize provider-specific event type values to the shared contract."""
        if not value:
            return None
        normalized = str(value).strip().lower().replace("-", "_")
        if normalized in {"online", "virtual", "virtual_event", "remote"}:
            return "ONLINE"
        if normalized in {"physical", "offline", "in_person", "in_person_event", "venue"}:
            return "PHYSICAL"
        return str(value).strip().upper()

    @staticmethod
    def _infer_result_event_type(event: Dict[str, Any]) -> Optional[str]:
        """Infer event type when provider payloads omit the canonical field."""
        explicit_type = SearchSkill._normalize_event_type(event.get("event_type"))
        if explicit_type:
            return explicit_type

        text_parts = [str(event.get("location") or "")]
        venue = event.get("venue")
        if isinstance(venue, dict):
            text_parts.extend(str(value or "") for value in venue.values())
            has_physical_venue = any(
                venue.get(key) for key in ("name", "address", "city", "country", "lat", "lon")
            )
        else:
            text_parts.append(str(venue or ""))
            has_physical_venue = bool(venue)

        text = " ".join(text_parts).lower()
        if any(term in text for term in ("online", "virtual", "remote", "webinar")):
            return "ONLINE"
        if has_physical_venue:
            return "PHYSICAL"
        return None

    @staticmethod
    def _parse_event_datetime(value: Any) -> Optional[datetime]:
        if not value or not isinstance(value, str):
            return None
        try:
            timestamp, separator, zone_suffix = value.strip().partition("[")
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if separator:
                if not zone_suffix.endswith("]"):
                    raise ValueError("Unclosed timezone annotation")
                zone = ZoneInfo(zone_suffix[:-1])
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=zone)
                elif parsed.astimezone(zone).utcoffset() != parsed.utcoffset():
                    raise ValueError("Timezone annotation conflicts with UTC offset")
            return parsed
        except (ValueError, ZoneInfoNotFoundError):
            logger.warning("[events:search] Invalid event datetime")
            return None

    @staticmethod
    def _align_event_datetime(value: datetime, reference: datetime) -> datetime:
        """Avoid naive/aware comparison errors from provider-local date strings."""
        if value.tzinfo is None and reference.tzinfo is not None:
            return value.replace(tzinfo=reference.tzinfo)
        if value.tzinfo is not None and reference.tzinfo is None:
            return value.replace(tzinfo=None)
        return value

    @staticmethod
    def _event_start(event: Dict[str, Any]) -> Optional[datetime]:
        """Parse an event start and attach its declared timezone when needed."""
        parsed = SearchSkill._parse_event_datetime(event.get("date_start"))
        if parsed is None or parsed.tzinfo is not None:
            return parsed
        timezone_name = event.get("timezone")
        if isinstance(timezone_name, str) and timezone_name:
            try:
                return parsed.replace(tzinfo=ZoneInfo(timezone_name))
            except ZoneInfoNotFoundError:
                logger.warning("[events:search] Invalid provider timezone")
        return parsed

    @staticmethod
    def _dedup_text(value: Any) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()

    @staticmethod
    def _title_tokens(event: Dict[str, Any]) -> set[str]:
        return {
            token
            for token in SearchSkill._dedup_text(event.get("title")).split()
            if token not in _EVENT_TITLE_DEDUP_STOPWORDS and not token.isdigit()
        }

    @staticmethod
    def _venue_identity(event: Dict[str, Any]) -> str:
        venue = event.get("venue")
        if isinstance(venue, dict):
            return SearchSkill._dedup_text(
                " ".join(str(venue.get(field) or "") for field in ("name", "address", "city"))
            )
        return SearchSkill._dedup_text(venue or event.get("location"))

    @staticmethod
    def _description_identity(event: Dict[str, Any]) -> str:
        return SearchSkill._dedup_text(event.get("description"))[:800]

    @staticmethod
    def _description_urls(event: Dict[str, Any]) -> set[str]:
        urls = re.findall(r"https?://[^\s\])>]+", str(event.get("description") or ""))
        return {
            normalized
            for url in urls
            if (normalized := normalize_url_for_deduplication(url.rstrip(".,;")))
        }

    @classmethod
    def _events_are_duplicates(cls, first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        first_url = normalize_url_for_deduplication(_event_result_url(first))
        second_url = normalize_url_for_deduplication(_event_result_url(second))
        if first_url and first_url == second_url:
            return True

        first_start = cls._event_start(first)
        second_start = cls._event_start(second)
        if first_start is None or second_start is None:
            return False
        second_start = cls._align_event_datetime(second_start, first_start)
        if abs((first_start - second_start).total_seconds()) > 90 * 60:
            return False

        if cls._description_urls(first) & cls._description_urls(second):
            return True

        first_tokens = cls._title_tokens(first)
        second_tokens = cls._title_tokens(second)
        if first_tokens and second_tokens:
            overlap = len(first_tokens & second_tokens) / min(len(first_tokens), len(second_tokens))
            if overlap >= 0.75:
                return True

        first_description = cls._description_identity(first)
        second_description = cls._description_identity(second)
        if (
            len(first_description) >= 80
            and first_description == second_description
            and cls._venue_identity(first) == cls._venue_identity(second)
        ):
            return True
        return False

    @classmethod
    def _deduplicate_events(cls, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep one stable representative for each real-world event."""
        unique: List[Dict[str, Any]] = []
        for event in events:
            if any(cls._events_are_duplicates(existing, event) for existing in unique):
                continue
            unique.append(event)
        return unique

    @staticmethod
    def _parse_money(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"\d+(?:[.,]\d+)?", str(value))
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", "."))
        except ValueError:
            return None

    @staticmethod
    def _extract_price_amount(event: Dict[str, Any]) -> Optional[float]:
        """Extract a comparable event price when provider data exposes one."""
        for candidate in (event.get("price"), event.get("fee")):
            if candidate in (None, ""):
                continue
            if isinstance(candidate, dict):
                for key in ("amount", "min", "display"):
                    amount = SearchSkill._parse_money(candidate.get(key))
                    if amount is not None:
                        return amount
                continue
            amount = SearchSkill._parse_money(candidate)
            if amount is not None:
                return amount
        if event.get("is_paid") is False:
            return 0.0
        return None

    @staticmethod
    def _has_price_intent(query: Optional[str]) -> bool:
        if not query:
            return False
        lowered = query.lower()
        return any(term in lowered for term in ("free", "cheap", "budget", "low cost", "low-cost", "affordable"))

    @staticmethod
    def _has_accessibility_intent(query: Optional[str]) -> bool:
        if not query:
            return False
        lowered = query.lower()
        return any(term in lowered for term in ("wheelchair", "accessible", "accessibility", "barrier-free", "barrier free"))

    @staticmethod
    def _accessibility_match(event: Dict[str, Any]) -> str:
        text_parts = [str(event.get(field) or "") for field in ("title", "description", "location")]
        venue = event.get("venue")
        if isinstance(venue, dict):
            text_parts.extend(str(value or "") for value in venue.values())
        else:
            text_parts.append(str(venue or ""))
        text = " ".join(text_parts).lower()
        if any(term in text for term in ("wheelchair", "accessible", "barrier-free", "barrier free")):
            return "mentioned"
        return "unknown"

    @staticmethod
    def _apply_quality_filters(
        events: List[Dict[str, Any]],
        *,
        event_type: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        query: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Apply deterministic post-provider filters and ranking guardrails."""
        normalized_type = SearchSkill._normalize_event_type(event_type)
        start_dt = SearchSkill._parse_event_datetime(start_date)
        end_dt = SearchSkill._parse_event_datetime(end_date)
        price_intent = SearchSkill._has_price_intent(query)
        accessibility_intent = SearchSkill._has_accessibility_intent(query)
        applied_filters: List[str] = []
        filtered: List[Dict[str, Any]] = []
        filtered_out_count = 0

        if normalized_type:
            applied_filters.append("event_type")
        if start_dt or end_dt:
            applied_filters.append("date_window")

        for event in events:
            result = dict(event)
            result_type = SearchSkill._infer_result_event_type(result)
            if result_type:
                result["event_type"] = result_type
            if normalized_type and result_type and result_type != normalized_type:
                filtered_out_count += 1
                continue

            event_start = SearchSkill._event_start(result)
            if (start_dt or end_dt) and event_start is None:
                filtered_out_count += 1
                continue
            if start_dt and event_start and SearchSkill._align_event_datetime(event_start, start_dt) < start_dt:
                filtered_out_count += 1
                continue
            if end_dt and event_start and SearchSkill._align_event_datetime(event_start, end_dt) >= end_dt:
                filtered_out_count += 1
                continue

            constraint_matches = dict(result.get("constraint_matches") or {})
            if price_intent:
                price = SearchSkill._extract_price_amount(result)
                if price is None:
                    constraint_matches["price"] = "unknown"
                elif price == 0:
                    constraint_matches["price"] = "free"
                elif price <= 15:
                    constraint_matches["price"] = "cheap"
                else:
                    constraint_matches["price"] = "paid"
                result["price_amount"] = price
            if accessibility_intent:
                constraint_matches["accessibility"] = SearchSkill._accessibility_match(result)
            if constraint_matches:
                result["constraint_matches"] = constraint_matches
            filtered.append(result)

        if price_intent:
            def price_rank(event: Dict[str, Any]) -> tuple[int, float]:
                match = (event.get("constraint_matches") or {}).get("price")
                rank = {"free": 0, "cheap": 1, "unknown": 2, "paid": 3}.get(match, 4)
                amount = event.get("price_amount")
                numeric_amount = float(amount) if isinstance(amount, (int, float)) else float("inf")
                return rank, numeric_amount

            filtered.sort(key=price_rank)

        metadata: Dict[str, Any] = {
            "applied_filters": applied_filters,
            "filtered_out_count": filtered_out_count,
            "price_intent": "free_or_cheap" if price_intent else None,
            "accessibility_intent": accessibility_intent,
            "no_result_reason": "filtered_out" if events and not filtered else None,
        }
        if metadata["no_result_reason"]:
            metadata["suggestions"] = [
                "Relax one or more filters",
                "Try a wider date range",
                "Search another provider or nearby city",
            ]
        return filtered, metadata

    def _load_config_from_app_yml(self) -> None:
        """Load follow-up suggestions and provider metadata from app.yml."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            app_yml_path = os.path.join(os.path.dirname(current_dir), "app.yml")

            if not os.path.exists(app_yml_path):
                logger.error(
                    "app.yml not found at %s — config will use defaults",
                    app_yml_path,
                )
                return

            with open(app_yml_path, "r", encoding="utf-8") as fh:
                config = yaml.safe_load(fh)

            for skill in (config or {}).get("skills", []):
                if skill.get("id", "").strip() == "search":
                    suggestions = skill.get("suggestions_follow_up_requests", [])
                    if isinstance(suggestions, list):
                        self.suggestions_follow_up_requests = [str(s) for s in suggestions]

                    providers = skill.get("providers", [])
                    if isinstance(providers, list):
                        self._providers_meta = providers
                        logger.debug(
                            "Loaded %d provider metadata entries from app.yml",
                            len(self._providers_meta),
                        )
                    return

            logger.warning(
                "Search skill not found in app.yml — config will use defaults"
            )

        except Exception as exc:
            logger.error(
                "Error loading config from app.yml: %s",
                exc,
                exc_info=True,
            )

    def _validate_event_requests(
        self,
        requests: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Validate event requests without letting one bad LLM item poison the batch."""
        if not requests:
            return [], [], (
                "No search requests provided. 'requests' array must contain at "
                "least one request with 'query' and 'location' (or 'lat'/'lon')."
            )

        valid_requests: List[Dict[str, Any]] = []
        invalid_results: List[Dict[str, Any]] = []
        request_ids: set[Any] = set()
        total_requests = len(requests)

        for i, req in enumerate(requests):
            request_id, error = self._validate_and_normalize_request_id(
                req=req,
                request_index=i,
                total_requests=total_requests,
                request_ids=request_ids,
                logger=logger,
            )
            if error:
                logger.error("Request %d validation failed: %s", i + 1, error)
                return [], [], error

            if not req.get("query"):
                error_message = f"Request {i + 1} (id: {request_id}) is missing required 'query' field"
                logger.warning("[events:search] %s; preserving as per-request error", error_message)
                invalid_results.append({
                    "id": request_id,
                    "results": [],
                    "error": error_message,
                    "total_available": 0,
                })
                continue

            # Normalize before provider dispatch: providers accept ISO offsets, while
            # the tool schema also permits an IANA timezone annotation.
            normalized = dict(req)
            bounds: Dict[str, datetime] = {}
            date_error = None
            for field in ("start_date", "end_date"):
                if req.get(field) is None:
                    continue
                parsed = self._parse_event_datetime(req[field])
                if parsed is None:
                    date_error = f"Invalid {field}: expected an ISO 8601 datetime"
                    break
                bounds[field] = parsed
                normalized[field] = parsed.isoformat()
            if not date_error and len(bounds) == 2:
                start = bounds["start_date"]
                end = self._align_event_datetime(bounds["end_date"], start)
                if end <= start:
                    date_error = "Invalid date range: end_date must be after start_date"
            if date_error:
                logger.warning("[events:search] Request %s: %s", request_id, date_error)
                invalid_results.append({
                    "id": request_id, "results": [], "error": date_error,
                    "total_available": 0,
                })
                continue
            valid_requests.append(normalized)

        if not valid_requests:
            return [], invalid_results, invalid_results[0]["error"] if invalid_results else None

        return valid_requests, invalid_results, None

    async def _search_meetup(
        self,
        query: str,
        lat: float,
        lon: float,
        city: str,
        country: str,
        start_date: Optional[str],
        end_date: Optional[str],
        event_type: Optional[str],
        radius_miles: float,
        count: int,
        proxy_url: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Meetup and return (events, total_available, error_or_None).
        Never raises — errors are returned as the third tuple element.
        """
        try:
            events, total = await meetup_provider.search_events_async(
                keywords=query,
                lat=lat,
                lon=lon,
                city=city,
                country=country,
                start_date=start_date,
                end_date=end_date,
                event_type=event_type,
                radius_miles=radius_miles,
                count=count,
                proxy_url=proxy_url,
            )
            return events, total, None
        except Exception as exc:
            logger.warning("Meetup search failed for query=%r: %s", query, exc)
            return [], 0, str(exc)

    async def _search_luma(
        self,
        query: str,
        location_str: str,
        count: int,
        proxy_url: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Luma and return (events, total_available, error_or_None).
        Never raises — errors are returned as the third tuple element.

        If the city is not in Luma's 78 featured cities, returns empty list
        (not an error — Luma simply doesn't cover that city).

        proxy_url is passed to luma_provider.search_events_async() for use as a
        fallback if Luma rejects the direct request. See luma.py for retry logic.
        """
        try:
            events, total = await luma_provider.search_events_async(
                city=location_str,
                query=query,
                count=count,
                fetch_descriptions=True,
                proxy_url=proxy_url,
            )
            return events, total, None
        except ValueError:
            # City not supported by Luma — not an error, just no results.
            logger.debug(
                "Luma does not support city %r — skipping Luma for this request",
                location_str,
            )
            return [], 0, None
        except Exception as exc:
            logger.warning("Luma search failed for query=%r city=%r: %s", query, location_str, exc)
            return [], 0, str(exc)

    async def _search_google_events(
        self,
        query: str,
        location_str: str,
        start_date: Optional[str],
        end_date: Optional[str],
        event_type: Optional[str],
        count: int,
        secrets_manager: Optional[SecretsManager] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Google Events via SerpAPI and return (events, total_available, error_or_None).
        Never raises — errors are returned as the third tuple element.

        Requires SerpAPI key in Vault. Returns empty results with error message
        if the key is not configured.
        """
        try:
            events, total = await google_events_provider.search_events_async(
                query=query,
                location=location_str,
                start_date=start_date,
                end_date=end_date,
                event_type=event_type,
                count=count,
                secrets_manager=secrets_manager,
            )
            return events, total, None
        except ValueError as exc:
            # Missing API key — not a transient error.
            logger.warning("Google Events search unavailable: %s", exc)
            return [], 0, str(exc)
        except Exception as exc:
            logger.warning("Google Events search failed for query=%r: %s", query, exc)
            return [], 0, str(exc)

    async def _search_eventbrite(
        self,
        query: str,
        location_str: str,
        event_type: Optional[str],
        count: int,
        proxy_url: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Eventbrite and return (events, total_available, error_or_None).
        Never raises — errors are returned as the third tuple element.

        Eventbrite caps provider fetches to 10 results because each result is
        enriched with a direct event-page fetch for full descriptions.
        """
        try:
            provider_query = query
            if event_type == "ONLINE" and "online" not in query.lower():
                provider_query = f"{query} online"
            events, total = await eventbrite_provider.search_events_async(
                location=location_str,
                query=provider_query,
                count=count,
                proxy_url=proxy_url,
            )
            return events, total, None
        except Exception as exc:
            logger.warning(
                "Eventbrite search failed for query=%r city=%r: %s",
                query,
                location_str,
                exc,
            )
            return [], 0, str(exc)

    async def _search_resident_advisor(
        self,
        query: str,
        location_str: str,
        start_date: Optional[str],
        end_date: Optional[str],
        count: int,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Resident Advisor via GraphQL and return (events, total_available, error_or_None).
        Never raises — errors are returned as the third tuple element.

        If the city is not in RA's supported cities, returns empty list (not an error).
        No API key or proxy needed — RA's GraphQL endpoint is publicly accessible.
        """
        try:
            events, total = await ra_provider.search_events_async(
                city=location_str,
                query=query,
                count=count,
                start_date=start_date,
                end_date=end_date,
            )
            return events, total, None
        except ValueError:
            # City not supported by RA — not an error, just no results.
            logger.debug("Resident Advisor does not support city %r — skipping", location_str)
            return [], 0, None
        except Exception as exc:
            logger.warning("Resident Advisor search failed for query=%r: %s", query, exc)
            return [], 0, str(exc)

    async def _search_siegessaeule(
        self,
        query: str,
        location_str: str,
        start_date: Optional[str],
        end_date: Optional[str],
        count: int,
        proxy_url: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Siegessäule and return (events, total_available, error_or_None).
        Never raises — errors are returned as the third tuple element.

        Berlin-only. Returns empty list for non-Berlin cities (not an error).
        Uses Webshare residential proxy (Siegessäule blocks datacenter IPs).
        """
        if "berlin" not in location_str.lower():
            # Siegessäule is Berlin-only — silently skip for other cities.
            return [], 0, None

        try:
            events, total = await siegessaeule_provider.search_events_async(
                city=location_str,
                query=query,
                count=count,
                start_date=start_date,
                end_date=end_date,
                proxy_url=proxy_url,
            )
            return events, total, None
        except Exception as exc:
            logger.warning("Siegessäule search failed for query=%r: %s", query, exc)
            return [], 0, str(exc)

    async def _search_berlin_philharmonic(
        self,
        query: str,
        location_str: str,
        concert_tags: Optional[List[str]],
        start_date: Optional[str],
        end_date: Optional[str],
        count: int,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Berlin Philharmonic calendar and return (events, total, error_or_None).
        Never raises — errors are returned as the third tuple element.

        Berlin-only. Returns empty list for non-Berlin cities (not an error).
        Uses Typesense full-text search via q= plus optional tag filters.
        """
        if "berlin" not in location_str.lower():
            return [], 0, None

        try:
            events, total = await berlin_philharmonic_provider.search_events_async(
                location=location_str,
                query=query,
                tags=concert_tags or [],
                count=count,
                start_date=start_date,
                end_date=end_date,
            )
            return events, total, None
        except Exception as exc:
            logger.warning("Berlin Philharmonic search failed for query=%r: %s", query, exc)
            return [], 0, str(exc)

    async def _search_pretalx(
        self,
        query: str,
        location_str: str,
        conference: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        count: int,
        past_events: bool,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search known pretalx/C3VOC conference schedules and return (events, total, error_or_None).
        Never raises — errors are returned as the third tuple element.
        """
        try:
            events, total = await pretalx_provider.search_events_async(
                query=query,
                conference=conference,
                location=location_str,
                start_date=start_date,
                end_date=end_date,
                count=count,
                past_events=past_events,
            )
            return events, total, None
        except ValueError:
            # No known conference was requested. In auto mode this is not an error.
            return [], 0, None
        except Exception as exc:
            logger.warning("Conference schedule search failed for query=%r: %s", query, exc)
            return [], 0, str(exc)

    @staticmethod
    def _merge_and_sort(
        *provider_results: List[Dict[str, Any]],
        count: int,
    ) -> List[Dict[str, Any]]:
        """
        Merge results from multiple providers, deduplicate by URL, and sort by date.

        Deduplication key: lowercased event URL. When two events have the same URL
        (e.g. cross-listed on Meetup and Luma), the first occurrence is kept.

        Sorting: ascending by date_start (soonest first). Events with no date_start
        are placed at the end.

        Args:
            *provider_results: Variable number of event lists from different providers.
            count:             Maximum number of events to return.

        Returns:
            Merged, deduplicated, sorted list limited to count.
        """
        seen_urls: set = set()
        merged: List[Dict[str, Any]] = []

        for events in provider_results:
            for event in events:
                url = (event.get("url") or "").lower().strip()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                merged.append(event)

        # Sort by start date ascending; None dates go to end.
        merged.sort(key=lambda e: (e.get("date_start") or "9999"))

        return merged[:count]

    @staticmethod
    def _relevance_deduplication_key(event: Dict[str, Any]) -> str:
        """Identify cross-provider copies before relevance ranking."""

        title = re.sub(r"\s+", " ", str(event.get("title") or "")).strip().lower()
        date_start = str(event.get("date_start") or "").strip().lower()
        venue = event.get("venue")
        if isinstance(venue, dict):
            venue_text = "|".join(
                str(venue.get(field) or "").strip().lower()
                for field in ("name", "address", "city")
            )
        else:
            venue_text = str(venue or event.get("location") or "").strip().lower()
        if title and date_start:
            return f"event:{title}|{date_start}|{venue_text}"
        url = normalize_url_for_deduplication(_event_result_url(event))
        if url:
            return f"url:{url}"
        return ""

    async def _process_single_search_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,  # noqa: ARG002
        proxy_url: Optional[str] = None,
    ) -> tuple:
        """
        Process a single event search request across the requested provider(s).

        In "auto" mode both Meetup and Luma are queried in parallel.
        Results are merged, deduplicated, sorted, and limited to count.

        Args:
            req:             Request dict — must contain 'query' and 'location' (or
                             'lat'/'lon'). Optional: provider, start_date, end_date,
                             event_type, radius_miles, count.
            request_id:      ID for matching this request in the grouped response.
            secrets_manager: Injected by BaseSkill helper (required by base signature).
            proxy_url:       Optional Webshare rotating proxy URL for Meetup requests.

        Returns:
            Tuple (request_id, results_list, error_or_None, total_available, searched_provider_ids).
        """
        provider_warnings: List[str] = []
        provider_hint = req.get("provider") or " ".join(req.get("providers") or [])
        conference: Optional[str] = req.get("conference") or None
        if not conference:
            conference = pretalx_provider.resolve_conference(str(provider_hint))

        query = req.get("query") or req.get("q") or conference
        if not query:
            return (request_id, [], "Missing 'query' parameter", 0, [])
        relevance_criteria = normalize_relevance_criteria(req.get("relevance_criteria"))

        # Strip platform-brand and filler stopwords before passing to providers.
        # e.g. "AI meetup" -> "AI", "tech events" -> "tech". Falls back to the
        # original query if sanitization would produce an empty string.
        sanitized = _sanitize_query(query)
        if sanitized:
            if sanitized != query:
                logger.debug(
                    "[events:search] Sanitized query %r -> %r (stopwords removed)",
                    query, sanitized,
                )
            query = sanitized

        # --- Provider selection ---
        # Support both new per-request 'providers' array and legacy 'provider' string.
        raw_providers = req.get("providers")
        if isinstance(raw_providers, list) and raw_providers:
            # New format: per-request providers array from LLM
            provider_choice = "auto"  # triggers multi-provider path
            requested_providers = [
                _PROVIDER_ALIASES.get(str(p).lower().strip(), str(p).lower().strip())
                for p in raw_providers
            ]
        else:
            # Legacy format: single provider string (or "auto")
            provider_choice = str(req.get("provider", "auto")).lower().strip()
            provider_choice = _PROVIDER_ALIASES.get(provider_choice, provider_choice)
            if provider_choice not in _VALID_PROVIDERS:
                logger.warning(
                    "Unknown provider %r for request %s — refusing provider fallback",
                    provider_choice,
                    request_id,
                )
                return (request_id, [], f"Unknown events provider: {provider_choice}", 0, [])
            # Single specific provider → use directly (no registry filtering)
            requested_providers = None if provider_choice == "auto" else None

        searched_provider_ids: List[str] = [] if provider_choice == "auto" else [provider_choice]

        # Parse the type before resolving location: ONLINE searches can be
        # location-free when routed only to providers that support that mode.
        event_type_raw = req.get("event_type")
        event_type: Optional[str] = self._normalize_event_type(event_type_raw)
        if event_type not in (None, "PHYSICAL", "ONLINE"):
            logger.warning(
                "Invalid event_type %r for request %s — ignoring",
                event_type_raw,
                request_id,
            )
            event_type = None

        # --- Resolve location ---
        lat: Optional[float] = req.get("lat")
        lon: Optional[float] = req.get("lon")
        city: str = ""
        country: str = ""
        # Use "or" to handle None from Pydantic model_dump() — prevents AttributeError on .strip()
        location_str: str = (req.get("location") or "").strip()
        location_free_online = (
            event_type == "ONLINE"
            and not location_str
            and lat is None
            and lon is None
        )

        if (
            location_free_online
            and provider_choice != "auto"
            and provider_choice not in _LOCATION_FREE_ONLINE_PROVIDERS
        ):
            return (
                request_id,
                [],
                f"Provider {provider_choice} requires a location; use eventbrite, "
                "google_events, or auto for location-free ONLINE searches.",
                0,
                searched_provider_ids,
            )

        if lat is not None and lon is not None:
            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError) as exc:
                return (request_id, [], f"Invalid lat/lon values: {exc}", 0, searched_provider_ids)
        else:
            if location_free_online:
                city, country = "", ""
            elif not location_str:
                if provider_choice == "pretalx" or pretalx_provider.is_conference_query(query):
                    lat, lon = 0.0, 0.0
                    city, country = "", ""
                else:
                    return (
                        request_id,
                        [],
                        "Missing 'location' parameter. Provide a city name or explicit lat/lon.",
                        0,
                        searched_provider_ids,
                    )
            if not location_free_online and (lat is None or lon is None):
                if not location_str:
                    return (
                        request_id,
                        [],
                        "Missing 'location' parameter. Provide a city name or explicit lat/lon.",
                        0,
                        searched_provider_ids,
                    )
                try:
                    lat, lon, city, country = meetup_provider.resolve_location(location_str)
                except ValueError as exc:
                    # Location cannot be resolved for Meetup geocoder.
                    # If provider is location-text based only, we don't need Meetup coordinates.
                    if provider_choice in {"luma", "eventbrite", "pretalx"}:
                        lat, lon = 0.0, 0.0
                    else:
                        return (request_id, [], f"Location resolution failed: {exc}", 0, searched_provider_ids)

        # Use provided location string as city for Luma if city wasn't set by geocoder.
        luma_city = city or location_str

        # --- Optional parameters ---
        start_date: Optional[str] = req.get("start_date")
        end_date: Optional[str] = req.get("end_date")
        radius_miles: float = float(req.get("radius_miles", 25.0))
        count: int = int(req.get("count", _DEFAULT_COUNT))
        candidate_target = relevance_candidate_target(count) if relevance_criteria else count
        concert_tags: Optional[List[str]] = req.get("concert_tags") or None
        past_events: bool = bool(req.get("past_events", False))

        logger.debug(
            "Events search (id=%s): provider=%r query=%r location=%r count=%d",
            request_id,
            provider_choice,
            query,
            luma_city or f"({lat},{lon})",
            count,
        )

        # --- Execute provider(s) ---
        if provider_choice == "meetup":
            # Meetup only
            meetup_events, total, meetup_err = await self._search_meetup(
                query=query,
                lat=lat,
                lon=lon,
                city=city,
                country=country,
                start_date=start_date,
                end_date=end_date,
                event_type=event_type,
                radius_miles=radius_miles,
                count=candidate_target,
                proxy_url=proxy_url,
            )
            if meetup_err and not meetup_events:
                return (request_id, [], f"Meetup search failed: {meetup_err}", 0, searched_provider_ids)
            all_events = meetup_events
            total_available = total

        elif provider_choice == "luma":
            # Luma only
            luma_events, total, luma_err = await self._search_luma(
                query=query,
                location_str=luma_city,
                count=candidate_target,
                proxy_url=proxy_url,
            )
            if luma_err and not luma_events:
                return (request_id, [], f"Luma search failed: {luma_err}", 0, searched_provider_ids)
            all_events = luma_events
            total_available = total

        elif provider_choice == "google_events":
            # Google Events only (via SerpAPI)
            ge_events, total, ge_err = await self._search_google_events(
                query=query,
                location_str=luma_city,
                start_date=start_date,
                end_date=end_date,
                event_type=event_type,
                count=candidate_target,
                secrets_manager=secrets_manager,
            )
            if ge_err and not ge_events:
                return (request_id, [], f"Google Events search failed: {ge_err}", 0, searched_provider_ids)
            all_events = ge_events
            total_available = total

        elif provider_choice == "eventbrite":
            # Eventbrite only (web app API, full descriptions via event pages)
            eb_events, total, eb_err = await self._search_eventbrite(
                query=query,
                location_str=luma_city,
                event_type=event_type,
                count=candidate_target,
                proxy_url=proxy_url,
            )
            if eb_err and not eb_events:
                return (request_id, [], f"Eventbrite search failed: {eb_err}", 0, searched_provider_ids)
            all_events = eb_events
            total_available = total

        elif provider_choice == "resident_advisor":
            # Resident Advisor only (electronic music / clubs)
            ra_events, total, ra_err = await self._search_resident_advisor(
                query=query,
                location_str=luma_city,
                start_date=start_date,
                end_date=end_date,
                count=candidate_target,
            )
            if ra_err and not ra_events:
                return (request_id, [], f"Resident Advisor search failed: {ra_err}", 0, searched_provider_ids)
            all_events = ra_events
            total_available = total

        elif provider_choice == "siegessaeule":
            # Siegessäule only (Berlin LGBTQ+ events)
            ss_events, total, ss_err = await self._search_siegessaeule(
                query=query,
                location_str=luma_city,
                start_date=start_date,
                end_date=end_date,
                count=candidate_target,
                proxy_url=proxy_url,
            )
            if ss_err and not ss_events:
                return (request_id, [], f"Siegessäule search failed: {ss_err}", 0, searched_provider_ids)
            all_events = ss_events
            total_available = total

        elif provider_choice == "berlin_philharmonic":
            # Berlin Philharmonic only (classical concerts, Berlin-only)
            bp_events, total, bp_err = await self._search_berlin_philharmonic(
                query=query,
                location_str=luma_city,
                concert_tags=concert_tags,
                start_date=start_date,
                end_date=end_date,
                count=candidate_target,
            )
            if bp_err and not bp_events:
                return (request_id, [], f"Berlin Philharmonic search failed: {bp_err}", 0, searched_provider_ids)
            all_events = bp_events
            total_available = total

        elif provider_choice == "pretalx":
            # Conference Schedule only (known pretalx/C3VOC schedules)
            pretalx_events, total, pretalx_err = await self._search_pretalx(
                query=query,
                location_str=luma_city,
                conference=conference,
                start_date=start_date,
                end_date=end_date,
                count=candidate_target,
                past_events=past_events,
            )
            if pretalx_err and not pretalx_events:
                return (request_id, [], f"Conference schedule search failed: {pretalx_err}", 0, searched_provider_ids)
            all_events = pretalx_events
            total_available = total

        else:
            # "auto" or per-request providers list: query applicable providers
            # in parallel with extra headroom for deduplication.
            # Safety filter: validate LLM's provider choices against region scope
            applicable_ids = filter_providers(
                requested_providers=requested_providers,
                city=luma_city,
                providers_meta=self._providers_meta,
            )
            if location_free_online:
                applicable_ids = [
                    provider_id
                    for provider_id in applicable_ids
                    if provider_id in _LOCATION_FREE_ONLINE_PROVIDERS
                ]
            if relevance_criteria:
                provider_count = max(1, len(applicable_ids))
                per_provider_count = max(
                    count,
                    (candidate_target + provider_count - 1) // provider_count,
                )
            else:
                per_provider_count = count * _AUTO_PROVIDER_MULTIPLIER

            logger.info(
                "Auto mode for request %s: %d applicable providers for city=%r: %s",
                request_id, len(applicable_ids), luma_city, applicable_ids,
            )

            # Build dispatch: provider ID → coroutine (each has different params)
            dispatch = {
                "meetup": lambda: self._search_meetup(
                    query=query, lat=lat, lon=lon, city=city, country=country,
                    start_date=start_date, end_date=end_date, event_type=event_type,
                    radius_miles=radius_miles, count=per_provider_count, proxy_url=proxy_url,
                ),
                "luma": lambda: self._search_luma(
                    query=query, location_str=luma_city,
                    count=per_provider_count, proxy_url=proxy_url,
                ),
                "eventbrite": lambda: self._search_eventbrite(
                    query=query, location_str=luma_city,
                    event_type=event_type,
                    count=per_provider_count, proxy_url=proxy_url,
                ),
                "google_events": lambda: self._search_google_events(
                    query=query, location_str=luma_city,
                    start_date=start_date, end_date=end_date, event_type=event_type,
                    count=per_provider_count, secrets_manager=secrets_manager,
                ),
                "resident_advisor": lambda: self._search_resident_advisor(
                    query=query, location_str=luma_city,
                    start_date=start_date, end_date=end_date, count=per_provider_count,
                ),
                "siegessaeule": lambda: self._search_siegessaeule(
                    query=query, location_str=luma_city,
                    start_date=start_date, end_date=end_date,
                    count=per_provider_count, proxy_url=proxy_url,
                ),
                "berlin_philharmonic": lambda: self._search_berlin_philharmonic(
                    query=query, location_str=luma_city,
                    concert_tags=concert_tags, start_date=start_date,
                    end_date=end_date, count=per_provider_count,
                ),
                "pretalx": lambda: self._search_pretalx(
                    query=query, location_str=luma_city, conference=conference,
                    start_date=start_date, end_date=end_date, count=per_provider_count,
                    past_events=past_events,
                ),
            }

            if (
                "pretalx" not in applicable_ids
                and pretalx_provider.is_conference_query(query, luma_city)
            ):
                applicable_ids.append("pretalx")

            # Execute only applicable providers in parallel
            task_entries = [
                (pid, dispatch[pid]())
                for pid in applicable_ids
                if pid in dispatch
            ]
            searched_provider_ids = [pid for pid, _ in task_entries]

            if not task_entries:
                error = (
                    "No selected provider supports location-free ONLINE searches"
                    if location_free_online
                    else "No applicable providers for this location"
                )
                return (request_id, [], error, 0, [])

            results_tuples = await asyncio.gather(*[t[1] for t in task_entries])

            # Log errors, collect results
            all_event_lists = []
            total_available = 0
            for (pid, _), (events, total, err) in zip(task_entries, results_tuples):
                if err:
                    logger.warning(
                        "%s failed in auto mode for request %s: %s", pid, request_id, err
                    )
                    provider_warnings.append(f"{pid} search unavailable")
                all_event_lists.append(events)
                total_available += total

            # Merge: all providers, deduplicate by URL, re-sort by date.
            if len(provider_warnings) == len(task_entries):
                return (request_id, [], "All selected event providers failed", 0, searched_provider_ids, provider_warnings)
            # Apply the date/type window to every bounded fetched candidate before
            # limiting. Earlier out-of-window events must not hide next week's events.
            all_events = self._merge_and_sort(*all_event_lists, count=sum(map(len, all_event_lists)))

        # Add 'type' field and content hash for UI rendering consistency.
        results: List[Dict[str, Any]] = []
        for event in all_events:
            result = {"type": "event_result", **event}
            event_url = _event_result_url(result)
            if not event_url:
                logger.debug(
                    "Dropping events/search result without URL: provider=%r id=%r title=%r",
                    result.get("provider"),
                    result.get("id"),
                    result.get("title") or result.get("name"),
                )
                continue
            result["url"] = event_url
            if not result.get("image_url"):
                result["image_url"] = result.get("cover_url")
            result["hash"] = self._generate_result_hash(
                event_url
            )
            results.append(result)

        results, quality_metadata = self._apply_quality_filters(
            results,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            query=query,
        )
        before_dedup_count = len(results)
        results = self._deduplicate_events(results)
        duplicate_count = before_dedup_count - len(results)
        if duplicate_count:
            quality_metadata["filtered_out_count"] = (
                quality_metadata.get("filtered_out_count", 0) + duplicate_count
            )
            quality_metadata.setdefault("applied_filters", []).append("semantic_deduplication")
        if relevance_criteria:
            results = stable_deduplicate_candidates(
                results,
                key=self._relevance_deduplication_key,
            )[:candidate_target]
            projections = []
            for result in results:
                projections.append({
                    "title": result.get("title"),
                    "description": result.get("description"),
                    "date_start": result.get("date_start"),
                    "date_end": result.get("date_end"),
                    "event_type": result.get("event_type"),
                    "venue": result.get("venue") or result.get("location"),
                    "organizer": result.get("organizer"),
                    "provider": result.get("provider"),
                    "price": result.get("price") or result.get("fee"),
                    "constraint_matches": result.get("constraint_matches"),
                    "url": result.get("url"),
                })
            ranking = await rank_search_candidates(
                candidates=results,
                candidate_projections=projections,
                relevance_criteria=relevance_criteria,
                search_parameters={
                    "query": query,
                    "location": luma_city,
                    "start_date": start_date,
                    "end_date": end_date,
                    "event_type": event_type,
                    "radius_miles": radius_miles,
                    "conference": conference,
                    "providers": searched_provider_ids,
                },
                profile="events",
                secrets_manager=secrets_manager,
            )
            results = ranking.candidates
            if ranking.applied and len(ranking.scores) == len(results):
                scored_results = list(zip(results, ranking.scores))
                results = [
                    result
                    for result, score in scored_results
                    if score >= _MIN_EVENT_RELEVANCE_SCORE
                ]
                omitted_count = len(scored_results) - len(results)
                if omitted_count:
                    quality_metadata["filtered_out_count"] = (
                        quality_metadata.get("filtered_out_count", 0) + omitted_count
                    )
                    quality_metadata.setdefault("applied_filters", []).append(
                        "relevance_floor"
                    )
        results = results[:count]
        if quality_metadata.get("filtered_out_count"):
            logger.info(
                "Events quality filters removed %d result(s) for request %s: %s",
                quality_metadata["filtered_out_count"],
                request_id,
                quality_metadata.get("applied_filters"),
            )

        logger.info(
            "Events search (id=%s) done: %d results (total=%d) provider=%r query=%r",
            request_id,
            len(results),
            total_available,
            provider_choice,
            query,
        )
        return (request_id, results, None, total_available, searched_provider_ids, provider_warnings)

    # ------------------------------------------------------------------
    # Public execute() — called by BaseApp/route handler
    # ------------------------------------------------------------------

    async def execute(
        self,
        request: SearchRequest,
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs: Any,
    ) -> SearchResponse:
        """
        Execute the events search skill.

        Processes all requests in parallel. Each request queries the configured
        provider(s) and returns merged, sorted event results.

        Args:
            request:         SearchRequest Pydantic model (validated by FastAPI)
            secrets_manager: Injected by app (used for Webshare proxy credentials)

        Returns:
            SearchResponse with grouped results and optional follow-up suggestions
        """
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="SearchSkill",
            error_response_factory=lambda msg: SearchResponse(results=[], error=msg),
            logger=logger,
        )
        if error_response:
            return error_response

        # Serialize Pydantic items to plain dicts so _validate_requests_array helpers
        # can call req.get("id") without AttributeError on Pydantic model objects.
        requests_list = [
            r.model_dump() if hasattr(r, "model_dump") else r
            for r in request.requests
        ]
        top_level_providers = request.providers
        top_level_provider = request.provider
        if top_level_providers or top_level_provider:
            for req in requests_list:
                if not req.get("providers") and not req.get("provider"):
                    if top_level_providers:
                        req["providers"] = top_level_providers
                    elif top_level_provider:
                        req["provider"] = top_level_provider
        for req in requests_list:
            if req.get("query") or req.get("q"):
                continue
            provider_hint = req.get("provider") or " ".join(req.get("providers") or [])
            conference = req.get("conference") or pretalx_provider.resolve_conference(str(provider_hint))
            if conference:
                req["conference"] = conference
                req["query"] = conference
        validated_requests, invalid_results, error = self._validate_event_requests(requests_list)
        if error:
            return SearchResponse(results=invalid_results, error=error)

        # Load Webshare rotating residential proxy credentials from Vault.
        # Used for Meetup requests to avoid server-side IP rate limiting.
        # Also passed to direct-first providers as a fallback proxy; they use it
        # only if direct requests are rejected (HTTP 403/429/5xx). See provider files.
        proxy_url: Optional[str] = None
        if secrets_manager:
            try:
                ws_username = await secrets_manager.get_secret(
                    secret_path="kv/data/providers/webshare",
                    secret_key="proxy_username",
                )
                ws_password = await secrets_manager.get_secret(
                    secret_path="kv/data/providers/webshare",
                    secret_key="proxy_password",
                )
                if ws_username and ws_password:
                    # Webshare rotating residential proxies require the "-rotate" suffix.
                    # Without it the proxy returns 407 even with correct credentials.
                    proxy_url = f"http://{ws_username}-rotate:{ws_password}@p.webshare.io:80/"
                    logger.debug("[events:search] Using Webshare rotating proxy for Meetup")
            except Exception as exc:
                logger.warning(
                    "[events:search] Could not load proxy credentials: %s — proceeding without proxy",
                    exc,
                )

        # Process all search requests in parallel (one task per request in 'requests' array).
        results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_search_request,
            logger=logger,
            secrets_manager=secrets_manager,
            proxy_url=proxy_url,
        )

        # Group by request ID — handle 4-tuples (request_id, items, error, total_available).
        grouped_results: List[Dict[str, Any]] = [*invalid_results]
        errors: List[str] = []
        warnings: List[str] = []
        request_order = {req.get("id"): i for i, req in enumerate(requests_list or [])}
        searched_provider_ids: List[str] = []
        seen_searched_provider_ids: set[str] = set()

        for result in results:
            if isinstance(result, Exception):
                error_msg = f"Unexpected error processing request: {str(result)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                continue

            if len(result) == 6:
                request_id, items, err, total_available, result_provider_ids, result_warnings = result
                warnings.extend(result_warnings)
            elif len(result) == 5:
                request_id, items, err, total_available, result_provider_ids = result
            else:
                request_id, items, err, total_available = result
                result_provider_ids = []

            for provider_id in result_provider_ids:
                if provider_id and provider_id not in seen_searched_provider_ids:
                    seen_searched_provider_ids.add(provider_id)
                    searched_provider_ids.append(provider_id)

            if err:
                errors.append(err)
                grouped_results.append({
                    "id": request_id,
                    "results": [],
                    "error": err,
                    "total_available": 0,
                })
            else:
                grouped_results.append({
                    "id": request_id,
                    "results": items,
                    "total_available": total_available,
                })

        grouped_results.sort(key=lambda x: request_order.get(x["id"], 999))

        # Determine provider label for response metadata.
        # If all requests used the same provider, report that; otherwise "auto".
        provider_choices = {
            str(r.get("provider", "auto")).lower() for r in (validated_requests or [])
        }
        provider_label = provider_choices.pop() if len(provider_choices) == 1 else "auto"

        # Prefer providers actually dispatched for this request. Fall back to
        # result contributors for legacy tests/embeds without request metadata.
        contributing_providers: List[str] = []
        seen_providers: set[str] = set(searched_provider_ids)
        contributing_providers.extend(searched_provider_ids)
        for gr in grouped_results:
            for item in gr.get("results", []):
                p = item.get("provider")
                if p and p not in seen_providers:
                    seen_providers.add(p)
                    contributing_providers.append(p)

        response = self._build_response_with_errors(
            response_class=SearchResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider=provider_label,
            providers=contributing_providers,
            warnings=list(dict.fromkeys(warnings)),
            suggestions=self.suggestions_follow_up_requests,
            logger=logger,
        )

        return response


def _event_result_url(event: Dict[str, Any]) -> str:
    for key in ("url", "booking_url"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
