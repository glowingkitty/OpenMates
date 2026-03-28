# backend/apps/events/providers/google_events.py
#
# Google Events search provider via SerpAPI.
#
# Uses the SerpAPI google_events engine to search Google's event knowledge
# panel. This aggregates events from multiple ticketing platforms (Eventbrite,
# Ticketmaster, Meetup, etc.) into a single unified search.
#
# Key design decisions:
# - Requires SerpAPI API key (stored in Vault, shared with travel/images apps)
# - Location is passed via both the query string and SerpAPI's location param
#   for best geo-relevance
# - Date filtering uses Google's htichips parameter (predefined ranges only:
#   today, tomorrow, this week, this weekend, this month, next month)
# - Pagination via start=0,10,20,... (10 results per page from Google)
# - No proxy needed — SerpAPI handles the Google request
#
# API docs: https://serpapi.com/google-events-api

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import httpx

from backend.shared.providers.serpapi import (
    SERPAPI_BASE,
    get_serpapi_key_async,
)

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# SerpAPI engine name for Google Events.
_ENGINE = "google_events"

# Results per page returned by Google Events via SerpAPI.
_RESULTS_PER_PAGE = 10

# HTTP timeout for SerpAPI requests (seconds).
_HTTP_TIMEOUT = 30.0

# Polite inter-page delay between paginated requests (seconds).
_PAGE_DELAY_SECONDS = 0.5

# Maximum description length to return (characters).
_MAX_DESCRIPTION_CHARS = 2000

# Map our date filter strings to Google's htichips values.
# The skill layer maps user intent (e.g., "this week") to these keys.
HTICHIPS_DATE_MAP: Dict[str, str] = {
    "today": "date:today",
    "tomorrow": "date:tomorrow",
    "week": "date:week",
    "this_week": "date:week",
    "weekend": "date:weekend",
    "this_weekend": "date:weekend",
    "next_week": "date:next_week",
    "month": "date:month",
    "this_month": "date:month",
    "next_month": "date:next_month",
}

# Map our event_type values to Google's htichips values.
HTICHIPS_TYPE_MAP: Dict[str, str] = {
    "ONLINE": "event_type:Virtual-Event",
    "online": "event_type:Virtual-Event",
}


# ---------------------------------------------------------------------------
# Date range -> htichips mapping
# ---------------------------------------------------------------------------

def _date_range_to_htichips(
    start_date: Optional[str],
    end_date: Optional[str],
    event_type: Optional[str],
) -> Optional[str]:
    """
    Convert date range and event type filters to Google's htichips parameter.

    Google Events doesn't support arbitrary date ranges — only predefined
    chips (today, tomorrow, week, weekend, month, next_month). This function
    picks the best-fit chip based on the requested date range.

    Args:
        start_date: ISO 8601 start date string (or None).
        end_date:   ISO 8601 end date string (or None).
        event_type: "PHYSICAL" or "ONLINE" (or None).

    Returns:
        htichips string (e.g., "date:week,event_type:Virtual-Event") or None.
    """
    chips: List[str] = []

    # Event type chip
    if event_type and event_type.upper() in ("ONLINE",):
        chips.append("event_type:Virtual-Event")

    # Date chip — try to map the date range to the closest predefined chip.
    # If no date range is specified, don't add a date chip (returns all upcoming).
    if start_date:
        try:
            # Parse ISO 8601 date (handle timezone offsets)
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta_days = (start_dt.date() - now.date()).days

            if delta_days <= 0:
                chips.append("date:today")
            elif delta_days == 1:
                chips.append("date:tomorrow")
            elif delta_days <= 7:
                chips.append("date:week")
            elif delta_days <= 14:
                chips.append("date:next_week")
            elif delta_days <= 30:
                chips.append("date:month")
            elif delta_days <= 60:
                chips.append("date:next_month")
            # Beyond 60 days — no date chip, let Google return all upcoming.
        except (ValueError, TypeError):
            logger.debug("Could not parse start_date %r for htichips mapping", start_date)

    return ",".join(chips) if chips else None


# ---------------------------------------------------------------------------
# Event normalization
# ---------------------------------------------------------------------------

def _normalize_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a SerpAPI Google Events result into our standard EventResult format.

    Maps Google's event object fields to the unified schema used by all providers:
    provider, title, description, url, date_start, date_end, timezone, event_type,
    venue, organizer, rsvp_count, is_paid, fee, image_url.

    Args:
        raw: A single event dict from SerpAPI's events_results array.

    Returns:
        Normalized event dict matching the EventResult schema.
    """
    # --- Date parsing ---
    date_info = raw.get("date") or {}
    when_str = date_info.get("when", "")
    start_date_str = date_info.get("start_date", "")

    # SerpAPI returns human-readable dates like "Sat, Dec 7, 8 PM".
    # We store the raw "when" string as date_start since parsing every locale
    # variant is fragile. The UI already handles display formatting.
    date_start = when_str or start_date_str or None

    # --- Address / venue ---
    address_parts = raw.get("address") or []
    address_str = ", ".join(address_parts) if isinstance(address_parts, list) else str(address_parts)

    venue_info = raw.get("venue") or {}
    venue: Optional[Dict[str, Any]] = None
    if venue_info.get("name") or address_str:
        venue = {
            "name": venue_info.get("name", ""),
            "address": address_str,
            "city": None,
            "state": None,
            "country": None,
            "lat": None,
            "lon": None,
        }
        # Try to extract city from address parts (typically last element: "Austin, TX")
        if address_parts and len(address_parts) >= 2:
            last_part = address_parts[-1]
            if "," in last_part:
                city_candidate = last_part.split(",")[0].strip()
                venue["city"] = city_candidate

    # --- Ticket info ---
    ticket_info = raw.get("ticket_info") or []
    is_paid = False
    for ticket in ticket_info:
        if ticket.get("link_type") == "tickets":
            is_paid = True
            break

    # --- Description ---
    description = raw.get("description", "") or ""
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[:_MAX_DESCRIPTION_CHARS] + "..."

    # --- Event type ---
    # Google Events doesn't explicitly label PHYSICAL vs ONLINE in the response,
    # but virtual events are typically in the htichips filter results.
    event_type = "PHYSICAL"  # Default — Google Events are mostly in-person

    # --- Image ---
    image_url = raw.get("image") or raw.get("thumbnail")

    return {
        "id": _generate_event_id(raw),
        "provider": "google_events",
        "title": raw.get("title", ""),
        "description": description,
        "url": raw.get("link", ""),
        "date_start": date_start,
        "date_end": None,  # Google Events doesn't reliably provide end times
        "timezone": None,  # Not provided by SerpAPI Google Events
        "event_type": event_type,
        "venue": venue,
        "organizer": None,  # Google Events doesn't provide organizer info
        "rsvp_count": None,
        "is_paid": is_paid,
        "fee": None,  # Google doesn't provide pricing details
        "image_url": image_url,
        "ticket_info": ticket_info,  # Preserve ticket sources for UI
    }


def _generate_event_id(raw: Dict[str, Any]) -> str:
    """Generate a stable ID from the event's URL or title."""
    import hashlib
    key = raw.get("link") or raw.get("title") or ""
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_events_async(
    *,
    query: str,
    location: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    event_type: Optional[str] = None,
    count: int = 10,
    secrets_manager: Optional["SecretsManager"] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Search for events via SerpAPI's Google Events engine.

    Args:
        query:           Search keywords (e.g., "tech meetup", "concert").
        location:        City or location string (e.g., "Berlin, Germany").
        start_date:      ISO 8601 start date (mapped to nearest htichips preset).
        end_date:        ISO 8601 end date (used for chip selection heuristic).
        event_type:      "PHYSICAL" or "ONLINE" (ONLINE adds Virtual-Event chip).
        count:           Maximum number of events to return (default 10, max 50).
        secrets_manager: For retrieving SerpAPI key from Vault.

    Returns:
        Tuple of (events_list, total_available).

    Raises:
        ValueError: If the SerpAPI key is not available.
    """
    api_key = await get_serpapi_key_async(secrets_manager)
    if not api_key:
        raise ValueError(
            "SerpAPI key not available. Cannot search Google Events. "
            "Configure the key in Vault at kv/data/providers/serpapi."
        )

    # Build the search query — include location for better geo-relevance.
    # Google Events works best when location is part of the query itself.
    search_query = f"{query} in {location}" if location else query

    # Build htichips for date/type filtering.
    htichips = _date_range_to_htichips(start_date, end_date, event_type)

    # Calculate pages needed (10 results per page from Google).
    pages_needed = min((count + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE, 5)

    all_events: List[Dict[str, Any]] = []
    total_available = 0

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        for page_idx in range(pages_needed):
            params: Dict[str, Any] = {
                "engine": _ENGINE,
                "q": search_query,
                "api_key": api_key,
                "hl": "en",
            }

            # Add location parameter for geo-targeting.
            if location:
                params["location"] = location

            # Add date/type filter chips.
            if htichips:
                params["htichips"] = htichips

            # Pagination offset.
            if page_idx > 0:
                params["start"] = page_idx * _RESULTS_PER_PAGE

            logger.debug(
                "[google_events] Fetching page %d: q=%r location=%r htichips=%r",
                page_idx + 1,
                search_query,
                location,
                htichips,
            )

            try:
                response = await client.get(SERPAPI_BASE, params=params)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "[google_events] SerpAPI HTTP error: %d — %s",
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                break
            except httpx.RequestError as exc:
                logger.error("[google_events] SerpAPI request error: %s", exc)
                break

            # Extract events from response.
            raw_events = data.get("events_results") or []
            if not raw_events:
                logger.debug(
                    "[google_events] No events on page %d — stopping pagination",
                    page_idx + 1,
                )
                break

            for raw in raw_events:
                all_events.append(_normalize_event(raw))

            # Update total — Google doesn't give an exact total, so estimate
            # from whether a full page was returned.
            if len(raw_events) < _RESULTS_PER_PAGE:
                # Partial page — no more results.
                total_available = len(all_events)
                break

            # Polite delay between pages (SerpAPI is a paid service, but
            # being polite helps avoid any rate limiting).
            if page_idx < pages_needed - 1:
                import asyncio
                await asyncio.sleep(_PAGE_DELAY_SECONDS)

    # Estimate total_available if we got full pages.
    if total_available == 0:
        total_available = len(all_events)

    # Trim to requested count.
    events = all_events[:count]

    logger.info(
        "[google_events] Search complete: %d events returned (total~%d) "
        "query=%r location=%r",
        len(events),
        total_available,
        query,
        location,
    )

    return events, total_available
