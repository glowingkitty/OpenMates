# backend/apps/events/providers/resident_advisor.py
#
# Resident Advisor (ra.co) event search provider.
#
# Uses RA's internal GraphQL API at ra.co/graphql for structured event data.
# The GraphQL endpoint is publicly accessible without authentication — no API
# key, no proxy, no headless browser needed.
#
# Key design decisions:
# - Direct GraphQL queries via httpx (no auth, no proxy required)
# - Rich structured data: title, date, venue, artists, genres, cost, flyer
# - City-based area IDs map cities to RA's internal area identifiers
# - Client-side keyword filtering (RA GraphQL doesn't support text search)
# - Polite usage: request only the fields and page sizes we need
#
# GraphQL endpoint: POST https://ra.co/graphql
# Introspection is enabled (schema is discoverable).
#
# Coverage: Electronic music, clubs, DJ events. Strongest in Berlin, London,
# Amsterdam, Barcelona, and other major European cities.

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.shared.testing.caching_http_transport import create_http_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://ra.co"
_GRAPHQL_URL = f"{_BASE_URL}/graphql"

# HTTP timeout for GraphQL requests (seconds).
_HTTP_TIMEOUT = 25.0

# Maximum description length to return (characters).
_MAX_DESCRIPTION_CHARS = 2000

# Headers required by RA's GraphQL endpoint.
_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://ra.co",
    "Referer": "https://ra.co/events",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}

# GraphQL query for event listings with full detail.
_EVENT_LISTINGS_QUERY = """
query GET_EVENT_LISTINGS($filters: FilterInputDtoInput, $pageSize: Int) {
  eventListings(filters: $filters, pageSize: $pageSize) {
    data {
      event {
        id
        title
        date
        startTime
        endTime
        content
        contentUrl
        flyerFront
        isTicketed
        cost
        minimumAge
        attending
        interestedCount
        isFestival
        venue {
          name
          address
          contentUrl
          capacity
          area { name }
          location { latitude longitude }
        }
        artists {
          name
        }
        genres {
          name
        }
        promoters {
          name
        }
        pick {
          blurb
        }
        images {
          filename
        }
      }
    }
    totalResults
  }
}
"""

# Map city names to RA's internal area IDs.
# Discovered via GraphQL introspection and RA's web app network traffic.
CITY_AREA_IDS: Dict[str, int] = {
    "berlin": 34,
    "hamburg": 45,
    "munich": 74,
    "cologne": 76,
    "frankfurt": 43,
    "dusseldorf": 170,
    "london": 13,
    "manchester": 100,
    "amsterdam": 29,
    "rotterdam": 163,
    "paris": 44,
    "barcelona": 8,
    "madrid": 49,
    "lisbon": 77,
    "rome": 150,
    "milan": 47,
    "vienna": 35,
    "prague": 60,
    "budapest": 41,
    "warsaw": 110,
    "zurich": 145,
    "brussels": 37,
    "copenhagen": 40,
    "stockholm": 66,
    "oslo": 151,
    "helsinki": 115,
    "new york": 8,
    "los angeles": 18,
    "san francisco": 14,
    "chicago": 15,
    "detroit": 11,
    "miami": 22,
    "tokyo": 27,
    "sydney": 5,
    "melbourne": 48,
    "toronto": 28,
    "montreal": 79,
    "seoul": 97,
    "bangkok": 107,
    "singapore": 80,
    "tbilisi": 126,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_area_id(location: str) -> Tuple[int, str]:
    """
    Resolve a location string to RA's (area_id, city_name) tuple.

    Args:
        location: City name or "city, country" string.

    Returns:
        Tuple of (area_id, normalised_city_name).

    Raises:
        ValueError: If the city is not in RA's supported cities.
    """
    normalised = location.lower().strip()
    if "," in normalised:
        normalised = normalised.split(",")[0].strip()

    if normalised in CITY_AREA_IDS:
        return CITY_AREA_IDS[normalised], normalised

    # Partial match
    for key, area_id in CITY_AREA_IDS.items():
        if key in normalised or normalised in key:
            return area_id, key

    raise ValueError(
        f"Resident Advisor does not cover '{location}'. "
        f"Supported cities: {', '.join(sorted(CITY_AREA_IDS.keys()))}"
    )


def _normalize_event(raw: Dict[str, Any], city: str) -> Dict[str, Any]:
    """
    Normalize an RA GraphQL event object into the standard EventResult format.

    Args:
        raw:  Event dict from the GraphQL response.
        city: Normalised city name (e.g., "berlin").

    Returns:
        Normalized event dict.
    """
    event_id = raw.get("id", "")
    content_url = raw.get("contentUrl") or ""
    url = f"{_BASE_URL}{content_url}" if content_url else f"{_BASE_URL}/events/{event_id}"

    # Venue (with lat/lon from venue.location)
    venue_raw = raw.get("venue") or {}
    area = venue_raw.get("area") or {}
    venue_location = venue_raw.get("location") or {}
    venue = {
        "name": venue_raw.get("name", ""),
        "address": venue_raw.get("address", ""),
        "city": area.get("name") or city.title(),
        "state": None,
        "country": None,
        "lat": venue_location.get("latitude"),
        "lon": venue_location.get("longitude"),
    }

    # Artists
    artists_raw = raw.get("artists") or []
    artist_names = [a.get("name", "") for a in artists_raw if a.get("name")]

    # Genres
    genres_raw = raw.get("genres") or []
    genres = [g.get("name", "") for g in genres_raw if g.get("name")]

    # Description — combine lineup + genres + content
    description_parts = []
    if artist_names:
        description_parts.append(f"Lineup: {', '.join(artist_names[:10])}")
    if genres:
        description_parts.append(f"Genres: {', '.join(genres)}")
    content = raw.get("content") or ""
    if content:
        if len(content) > _MAX_DESCRIPTION_CHARS:
            content = content[:_MAX_DESCRIPTION_CHARS] + "..."
        description_parts.append(content)
    description = "\n".join(description_parts)

    # Cost / pricing
    cost_str = raw.get("cost") or ""
    is_paid = raw.get("isTicketed", False) or bool(cost_str)
    fee = None
    if cost_str:
        fee = {"amount": cost_str, "currency": "EUR"}

    # Image — prefer flyerFront, fall back to images array
    image_url = raw.get("flyerFront")
    if not image_url:
        images = raw.get("images") or []
        if images and isinstance(images[0], dict):
            image_url = images[0].get("filename")

    # Attendance (RA uses "attending" for going count, "interestedCount" for interested)
    attending = raw.get("attending")
    interested = raw.get("interestedCount")
    rsvp_count = attending or interested

    # Promoter as organizer
    promoters = raw.get("promoters") or []
    organizer = None
    if promoters:
        organizer = {"name": promoters[0].get("name", ""), "slug": None, "id": None}

    # RA Pick editorial blurb — append to description if present
    pick = raw.get("pick") or {}
    if pick.get("blurb") and pick["blurb"] not in description:
        description = f"RA Pick: {pick['blurb']}\n{description}"

    return {
        "id": str(event_id),
        "provider": "resident_advisor",
        "title": raw.get("title", ""),
        "description": description,
        "url": url,
        "date_start": raw.get("startTime") or raw.get("date"),
        "date_end": raw.get("endTime"),
        "timezone": None,
        "event_type": "PHYSICAL",
        "venue": venue,
        "organizer": organizer,
        "rsvp_count": rsvp_count,
        "is_paid": is_paid,
        "fee": fee,
        "image_url": image_url,
        "artists": artist_names[:10] if artist_names else None,
        "genres": genres if genres else None,
        "minimum_age": raw.get("minimumAge"),
        "is_festival": raw.get("isFestival", False),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_events_async(
    *,
    city: str,
    query: str = "",
    count: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    secrets_manager: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Search for events on Resident Advisor by city via GraphQL.

    Args:
        city:            City name or "city, country" string.
        query:           Optional keyword filter (applied client-side — RA GraphQL
                         does not support text search).
        count:           Maximum number of events to return (default 10, max 50).
        start_date:      ISO 8601 start date (defaults to today).
        end_date:        ISO 8601 end date (defaults to 14 days from start).
        secrets_manager: Not required (RA GraphQL is public), accepted for
                         interface compatibility with other providers.

    Returns:
        Tuple of (events_list, total_available).

    Raises:
        ValueError: If the city is not supported by RA.
    """
    area_id, city_name = _resolve_area_id(city)

    # Default date range: today + 14 days
    now = datetime.now(timezone.utc)
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            start_dt = now
    else:
        start_dt = now

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            end_dt = start_dt + timedelta(days=14)
    else:
        end_dt = start_dt + timedelta(days=14)

    # Request more than needed for client-side keyword filtering.
    fetch_count = min(count * 3, 50) if query else min(count, 50)

    variables = {
        "filters": {
            "areas": {"eq": area_id},
            "listingDate": {
                "gte": start_dt.strftime("%Y-%m-%d"),
                "lte": end_dt.strftime("%Y-%m-%d"),
            },
        },
        "pageSize": fetch_count,
    }

    logger.debug(
        "[ra] GraphQL query: area=%d (%s) dates=%s..%s count=%d",
        area_id,
        city_name,
        variables["filters"]["listingDate"]["gte"],
        variables["filters"]["listingDate"]["lte"],
        fetch_count,
    )

    async with create_http_client("ra_graphql", timeout=_HTTP_TIMEOUT) as client:
        response = await client.post(
            _GRAPHQL_URL,
            json={"query": _EVENT_LISTINGS_QUERY, "variables": variables},
            headers=_HEADERS,
        )
        response.raise_for_status()
        data = response.json()

    # Extract events from GraphQL response.
    listings = data.get("data", {}).get("eventListings", {})
    raw_events = listings.get("data", [])
    total_available = listings.get("totalResults", 0)

    events = []
    for listing in raw_events:
        event_data = listing.get("event")
        if not event_data:
            continue
        events.append(_normalize_event(event_data, city_name))

    # Client-side keyword filtering using word-boundary matching.
    # Substring matching (e.g. "ai" in text) produces false positives like
    # "entertainment", "again", "paid". Word boundaries ensure we only match
    # whole words (e.g. "AI" but not "p-ai-d").
    if query:
        token_patterns = [
            re.compile(r"\b" + re.escape(token) + r"\b", re.IGNORECASE)
            for token in query.lower().split()
        ]
        events = [
            e for e in events
            if any(
                pattern.search(e.get("title", "") + " " + e.get("description", ""))
                for pattern in token_patterns
            )
        ]

    # Sort by date ascending; None dates to end.
    events.sort(key=lambda e: (e.get("date_start") or "9999"))

    events = events[:count]

    logger.info(
        "[ra] Search complete: %d events (total=%d) city=%r query=%r",
        len(events),
        total_available,
        city_name,
        query,
    )

    return events, total_available
