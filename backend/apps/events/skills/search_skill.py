# backend/apps/events/skills/search_skill.py
#
# Events search skill — multi-provider event discovery.
#
# Searches for public events (meetups, conferences, hackathons, workshops, etc.)
# using one or more providers simultaneously. Supported providers:
#   - meetup:            Meetup.com internal GraphQL (lat/lon, global, includes descriptions)
#   - luma:              Luma.com internal REST API (78 featured cities, includes descriptions)
#   - google_events:     Google Events via SerpAPI (aggregates Eventbrite, Ticketmaster, etc.)
#   - resident_advisor:  RA (ra.co) scraping — electronic music, clubs, DJ events
#   - siegessaeule:      Siegessäule scraping — Berlin LGBTQ+ events (Berlin-only)
#
# Provider selection via the 'provider' request field:
#   "auto"              (default) — searches all applicable providers in parallel, merges results
#   "meetup"            — Meetup only
#   "luma"              — Luma only (requires city to be in Luma's 78 featured cities)
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
import logging
import os
import yaml
from typing import Any, Dict, List, Optional, Tuple

from celery import Celery  # For type hinting only
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.ai.processing.external_result_sanitizer import sanitize_long_text_fields_in_payload
from backend.apps.events.providers import google_events as google_events_provider
from backend.apps.events.providers import luma as luma_provider
from backend.apps.events.providers import meetup as meetup_provider
from backend.apps.events.providers import resident_advisor as ra_provider
from backend.apps.events.providers import siegessaeule as siegessaeule_provider
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Valid provider values. "auto" runs all applicable providers in parallel.
_VALID_PROVIDERS = {"auto", "meetup", "luma", "google_events", "resident_advisor", "siegessaeule"}

# Normalize provider names from LLM tool calls (e.g. "Google Events" -> "google_events").
_PROVIDER_ALIASES: Dict[str, str] = {
    "google events": "google_events",
    "google": "google_events",
    "googleevents": "google_events",
    "serpapi": "google_events",
    "resident advisor": "resident_advisor",
    "residentadvisor": "resident_advisor",
    "ra": "resident_advisor",
    "ra.co": "resident_advisor",
    "siegessäule": "siegessaeule",
    "siegessaule": "siegessaeule",
}

# Platform-brand and generic filler words that narrow provider results unnecessarily.
# Both Meetup and Luma use literal keyword matching — passing "meetup" to Meetup or
# "luma" to Luma filters out any event that doesn't contain that word in its title,
# dramatically reducing results. "event/events" is equally useless on an events platform.
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

    query: str = Field(
        description="Topic or theme of events to search for (e.g. 'AI', 'Python', 'hackathon', "
        "'startup', 'networking'). Do NOT include platform names like 'meetup' or 'luma'."
    )
    location: Optional[str] = Field(
        default=None,
        description="City name or 'city, country' string (e.g. 'Berlin, Germany', 'New York'). "
        "Used if lat/lon are not provided.",
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
        description="Start of date range in ISO 8601 format. Defaults to now if omitted.",
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
        description="Maximum number of events to return (default: 10, max: 50).",
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
            "and 'location' (or 'lat'/'lon'). Optional: start_date, end_date, event_type, "
            "radius_miles, count."
        ),
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
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on search results.",
    )
    error: Optional[str] = Field(None, description="Error message if the skill failed.")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "description",  # Full event description (1-5 KB) — too large for LLM context
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

    In "auto" mode (default), Meetup, Luma, and Google Events are queried
    simultaneously. Results are merged, deduplicated by URL, sorted by start
    date, and limited to the requested count.

    Execution model: direct async in app-events FastAPI container.
    No Celery dispatch — search completes in 1-5s, well within sync timeout.
    """

    def __init__(
        self,
        app: Any,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
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
            stage=stage,
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
        self._load_suggestions_from_app_yml()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_suggestions_from_app_yml(self) -> None:
        """Load follow-up suggestion strings from the app.yml file."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            app_yml_path = os.path.join(os.path.dirname(current_dir), "app.yml")

            if not os.path.exists(app_yml_path):
                logger.error(
                    "app.yml not found at %s — suggestions_follow_up_requests will be empty",
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
                        logger.debug(
                            "Loaded %d follow-up suggestions from app.yml",
                            len(self.suggestions_follow_up_requests),
                        )
                    return

            logger.warning(
                "Search skill not found in app.yml — suggestions_follow_up_requests will be empty"
            )

        except Exception as exc:
            logger.error(
                "Error loading follow-up suggestions from app.yml: %s",
                exc,
                exc_info=True,
            )

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

    async def _search_resident_advisor(
        self,
        query: str,
        location_str: str,
        count: int,
        proxy_url: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Resident Advisor and return (events, total_available, error_or_None).
        Never raises — errors are returned as the third tuple element.

        If the city is not in RA's supported cities, returns empty list (not an error).
        """
        try:
            events, total = await ra_provider.search_events_async(
                city=location_str,
                query=query,
                count=count,
                proxy_url=proxy_url,
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
        count: int,
        proxy_url: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search Siegessäule and return (events, total_available, error_or_None).
        Never raises — errors are returned as the third tuple element.

        Berlin-only. Returns empty list for non-Berlin cities (not an error).
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
                proxy_url=proxy_url,
            )
            return events, total, None
        except Exception as exc:
            logger.warning("Siegessäule search failed for query=%r: %s", query, exc)
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

    async def _process_single_search_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,  # noqa: ARG002
        proxy_url: Optional[str] = None,
    ) -> Tuple[Any, List[Dict[str, Any]], Optional[str], int]:
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
            Tuple (request_id, results_list, error_or_None, total_available).
        """
        query = req.get("query") or req.get("q")
        if not query:
            return (request_id, [], "Missing 'query' parameter", 0)

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
        provider_choice = str(req.get("provider", "auto")).lower().strip()
        # Normalize aliases (e.g. "Google Events" from LLM -> "google_events").
        provider_choice = _PROVIDER_ALIASES.get(provider_choice, provider_choice)
        if provider_choice not in _VALID_PROVIDERS:
            logger.warning(
                "Unknown provider %r for request %s — falling back to 'auto'",
                provider_choice,
                request_id,
            )
            provider_choice = "auto"

        # --- Resolve location ---
        lat: Optional[float] = req.get("lat")
        lon: Optional[float] = req.get("lon")
        city: str = ""
        country: str = ""
        # Use "or" to handle None from Pydantic model_dump() — prevents AttributeError on .strip()
        location_str: str = (req.get("location") or "").strip()

        if lat is not None and lon is not None:
            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError) as exc:
                return (request_id, [], f"Invalid lat/lon values: {exc}", 0)
        else:
            if not location_str:
                return (
                    request_id,
                    [],
                    "Missing 'location' parameter. Provide a city name or explicit lat/lon.",
                    0,
                )
            try:
                lat, lon, city, country = meetup_provider.resolve_location(location_str)
            except ValueError as exc:
                # Location cannot be resolved for Meetup geocoder.
                # If provider is "luma" only, we don't need Meetup coordinates.
                if provider_choice == "luma":
                    lat, lon = 0.0, 0.0
                else:
                    return (request_id, [], f"Location resolution failed: {exc}", 0)

        # Use provided location string as city for Luma if city wasn't set by geocoder.
        luma_city = city or location_str

        # --- Optional parameters ---
        start_date: Optional[str] = req.get("start_date")
        end_date: Optional[str] = req.get("end_date")
        event_type: Optional[str] = req.get("event_type")
        radius_miles: float = float(req.get("radius_miles", 25.0))
        count: int = int(req.get("count", _DEFAULT_COUNT))

        if event_type and event_type not in ("PHYSICAL", "ONLINE"):
            logger.warning(
                "Invalid event_type %r for request %s — ignoring",
                event_type,
                request_id,
            )
            event_type = None

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
                count=count,
                proxy_url=proxy_url,
            )
            if meetup_err and not meetup_events:
                return (request_id, [], f"Meetup search failed: {meetup_err}", 0)
            all_events = meetup_events
            total_available = total

        elif provider_choice == "luma":
            # Luma only
            luma_events, total, luma_err = await self._search_luma(
                query=query,
                location_str=luma_city,
                count=count,
                proxy_url=proxy_url,
            )
            if luma_err and not luma_events:
                return (request_id, [], f"Luma search failed: {luma_err}", 0)
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
                count=count,
                secrets_manager=secrets_manager,
            )
            if ge_err and not ge_events:
                return (request_id, [], f"Google Events search failed: {ge_err}", 0)
            all_events = ge_events
            total_available = total

        elif provider_choice == "resident_advisor":
            # Resident Advisor only (electronic music / clubs)
            ra_events, total, ra_err = await self._search_resident_advisor(
                query=query,
                location_str=luma_city,
                count=count,
                proxy_url=proxy_url,
            )
            if ra_err and not ra_events:
                return (request_id, [], f"Resident Advisor search failed: {ra_err}", 0)
            all_events = ra_events
            total_available = total

        elif provider_choice == "siegessaeule":
            # Siegessäule only (Berlin LGBTQ+ events)
            ss_events, total, ss_err = await self._search_siegessaeule(
                query=query,
                location_str=luma_city,
                start_date=start_date,
                count=count,
                proxy_url=proxy_url,
            )
            if ss_err and not ss_events:
                return (request_id, [], f"Siegessäule search failed: {ss_err}", 0)
            all_events = ss_events
            total_available = total

        else:
            # "auto": query all providers in parallel with extra headroom.
            per_provider_count = count * _AUTO_PROVIDER_MULTIPLIER
            meetup_task = self._search_meetup(
                query=query,
                lat=lat,
                lon=lon,
                city=city,
                country=country,
                start_date=start_date,
                end_date=end_date,
                event_type=event_type,
                radius_miles=radius_miles,
                count=per_provider_count,
                proxy_url=proxy_url,
            )
            luma_task = self._search_luma(
                query=query,
                location_str=luma_city,
                count=per_provider_count,
                proxy_url=proxy_url,
            )
            google_events_task = self._search_google_events(
                query=query,
                location_str=luma_city,
                start_date=start_date,
                end_date=end_date,
                event_type=event_type,
                count=per_provider_count,
                secrets_manager=secrets_manager,
            )
            ra_task = self._search_resident_advisor(
                query=query,
                location_str=luma_city,
                count=per_provider_count,
                proxy_url=proxy_url,
            )
            siegessaeule_task = self._search_siegessaeule(
                query=query,
                location_str=luma_city,
                start_date=start_date,
                count=per_provider_count,
                proxy_url=proxy_url,
            )

            (
                (meetup_events, meetup_total, meetup_err),
                (luma_events, luma_total, _luma_err),
                (ge_events, ge_total, ge_err),
                (ra_events, ra_total, ra_err),
                (ss_events, ss_total, ss_err),
            ) = await asyncio.gather(
                meetup_task, luma_task, google_events_task, ra_task, siegessaeule_task,
            )

            if meetup_err:
                logger.warning(
                    "Meetup failed in auto mode for request %s: %s", request_id, meetup_err
                )
            if ge_err:
                logger.warning(
                    "Google Events failed in auto mode for request %s: %s", request_id, ge_err
                )
            if ra_err:
                logger.warning(
                    "Resident Advisor failed in auto mode for request %s: %s", request_id, ra_err
                )
            if ss_err:
                logger.warning(
                    "Siegessäule failed in auto mode for request %s: %s", request_id, ss_err
                )

            # Merge: all providers, deduplicate by URL, re-sort by date.
            all_events = self._merge_and_sort(
                luma_events, meetup_events, ge_events, ra_events, ss_events,
                count=count,
            )
            total_available = meetup_total + luma_total + ge_total + ra_total + ss_total

        # Add 'type' field and content hash for UI rendering consistency.
        results: List[Dict[str, Any]] = []
        for event in all_events:
            result = {"type": "event_result", **event}
            if not result.get("image_url"):
                result["image_url"] = result.get("cover_url")
            result["hash"] = self._generate_result_hash(
                event.get("url") or event.get("id") or ""
            )
            results.append(result)

        try:
            results = await sanitize_long_text_fields_in_payload(
                payload=results,
                task_id=f"events_search_{request_id}",
                secrets_manager=secrets_manager,
                cache_service=None,
            )
        except Exception as sanitize_error:
            logger.error(
                "Events content sanitization failed for request %s: %s",
                request_id,
                sanitize_error,
                exc_info=True,
            )
            return (request_id, [], "Content sanitization failed", 0)

        logger.info(
            "Events search (id=%s) done: %d results (total=%d) provider=%r query=%r",
            request_id,
            len(results),
            total_available,
            provider_choice,
            query,
        )
        return (request_id, results, None, total_available)

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
        validated_requests, error = self._validate_requests_array(
            requests=requests_list,
            required_field="query",
            field_display_name="query",
            empty_error_message=(
                "No search requests provided. 'requests' array must contain at "
                "least one request with 'query' and 'location' (or 'lat'/'lon')."
            ),
            logger=logger,
        )
        if error:
            return SearchResponse(results=[], error=error)

        # Load Webshare rotating residential proxy credentials from Vault.
        # Used for Meetup requests to avoid server-side IP rate limiting.
        # Also passed to Luma as a fallback proxy — Luma uses it only if the
        # direct request is rejected (HTTP 403/429/5xx). See luma.py for details.
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
        grouped_results: List[Dict[str, Any]] = []
        errors: List[str] = []
        request_order = {req.get("id"): i for i, req in enumerate(validated_requests or [])}

        for result in results:
            if isinstance(result, Exception):
                error_msg = f"Unexpected error processing request: {str(result)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                continue

            request_id, items, err, total_available = result

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

        response = self._build_response_with_errors(
            response_class=SearchResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider=provider_label,
            suggestions=self.suggestions_follow_up_requests,
            logger=logger,
        )

        return response
