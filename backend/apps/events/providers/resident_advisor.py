# backend/apps/events/providers/resident_advisor.py
#
# Resident Advisor (ra.co) event search provider.
#
# Scrapes RA's event listing pages for electronic music / club events.
# RA is a Next.js SSR app — event data is embedded in __NEXT_DATA__ JSON
# in the HTML, providing structured data without needing a headless browser.
#
# Key design decisions:
# - No API key needed — RA deprecated their public API years ago
# - Uses Firecrawl for scraping (RA blocks direct httpx and proxy requests with 403)
# - Parses __NEXT_DATA__ JSON for structured event data (lineup, genres, etc.)
# - Falls back to HTML/markdown parsing if __NEXT_DATA__ is not present
# - Currently supports city-based event listings only
#
# URL patterns:
#   Listing: https://ra.co/events/{country_code}/{city}
#   Event:   https://ra.co/events/{event_id}
#
# Coverage: Electronic music, clubs, DJ events. Strongest in Berlin, London,
# Amsterdam, Barcelona, and other major European cities.

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.shared.providers.firecrawl.firecrawl_scrape import scrape_url

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://ra.co"

# HTTP timeout for RA requests (seconds).
_HTTP_TIMEOUT = 25.0

# Maximum description length to return (characters).
_MAX_DESCRIPTION_CHARS = 2000

# Map city names to RA URL slugs: {normalised_city: (country_code, city_slug)}
# RA uses 2-letter ISO country codes in URLs.
CITY_SLUGS: Dict[str, Tuple[str, str]] = {
    "berlin": ("de", "berlin"),
    "hamburg": ("de", "hamburg"),
    "munich": ("de", "munich"),
    "cologne": ("de", "cologne"),
    "frankfurt": ("de", "frankfurt"),
    "dusseldorf": ("de", "dusseldorf"),
    "london": ("uk", "london"),
    "manchester": ("uk", "manchester"),
    "amsterdam": ("nl", "amsterdam"),
    "rotterdam": ("nl", "rotterdam"),
    "paris": ("fr", "paris"),
    "barcelona": ("es", "barcelona"),
    "madrid": ("es", "madrid"),
    "lisbon": ("pt", "lisbon"),
    "rome": ("it", "rome"),
    "milan": ("it", "milan"),
    "vienna": ("at", "vienna"),
    "prague": ("cz", "prague"),
    "budapest": ("hu", "budapest"),
    "warsaw": ("pl", "warsaw"),
    "zurich": ("ch", "zurich"),
    "brussels": ("be", "brussels"),
    "copenhagen": ("dk", "copenhagen"),
    "stockholm": ("se", "stockholm"),
    "oslo": ("no", "oslo"),
    "helsinki": ("fi", "helsinki"),
    "new york": ("us", "newyork"),
    "los angeles": ("us", "losangeles"),
    "san francisco": ("us", "sanfrancisco"),
    "chicago": ("us", "chicago"),
    "detroit": ("us", "detroit"),
    "miami": ("us", "miami"),
    "tokyo": ("jp", "tokyo"),
    "sydney": ("au", "sydney"),
    "melbourne": ("au", "melbourne"),
    "toronto": ("ca", "toronto"),
    "montreal": ("ca", "montreal"),
    "seoul": ("kr", "seoul"),
    "bangkok": ("th", "bangkok"),
    "singapore": ("sg", "singapore"),
    "tbilisi": ("ge", "tbilisi"),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_city(location: str) -> Tuple[str, str]:
    """
    Resolve a location string to RA's (country_code, city_slug) tuple.

    Args:
        location: City name or "city, country" string.

    Returns:
        Tuple of (country_code, city_slug) for URL construction.

    Raises:
        ValueError: If the city is not in RA's supported cities.
    """
    # Normalise: lowercase, strip country suffix, strip whitespace.
    normalised = location.lower().strip()
    # Handle "Berlin, Germany" -> "berlin"
    if "," in normalised:
        normalised = normalised.split(",")[0].strip()

    if normalised in CITY_SLUGS:
        return CITY_SLUGS[normalised]

    # Try partial match (e.g., "new york city" -> "new york")
    for key, value in CITY_SLUGS.items():
        if key in normalised or normalised in key:
            return value

    raise ValueError(
        f"Resident Advisor does not have a listing page for '{location}'. "
        f"Supported cities: {', '.join(sorted(CITY_SLUGS.keys()))}"
    )


async def _fetch_page(
    url: str,
    secrets_manager: Optional["SecretsManager"] = None,
) -> str:
    """
    Fetch an RA page via Firecrawl.

    RA blocks direct httpx requests and proxy requests with 403.
    Firecrawl uses a headless browser which bypasses this protection.

    Args:
        url:             The RA URL to scrape.
        secrets_manager: Required for Firecrawl API key retrieval.

    Returns:
        HTML content of the page.

    Raises:
        ValueError: If secrets_manager is not provided or Firecrawl fails.
    """
    if not secrets_manager:
        raise ValueError(
            "Resident Advisor requires Firecrawl (secrets_manager) for scraping. "
            "RA blocks direct HTTP requests."
        )

    logger.debug("[ra] Fetching via Firecrawl: %s", url)
    result = await scrape_url(
        url=url,
        secrets_manager=secrets_manager,
        formats=["html", "markdown"],
        only_main_content=False,
        sanitize_output=False,
        wait_for=3000,  # Wait 3s for Next.js hydration
    )

    if result.get("error"):
        raise ValueError(f"Firecrawl scrape failed for {url}: {result['error']}")

    data = result.get("data", {})
    # Prefer HTML (for __NEXT_DATA__ parsing), fall back to markdown
    html = data.get("html") or ""
    if not html:
        # If no HTML, construct minimal wrapper around markdown for fallback parser
        markdown = data.get("markdown") or ""
        if not markdown:
            raise ValueError(f"Firecrawl returned empty content for {url}")
        html = markdown  # _parse_events_from_html handles plain text too

    return html


def _extract_next_data(html: str) -> Optional[Dict[str, Any]]:
    """Extract __NEXT_DATA__ JSON from a Next.js SSR page."""
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("[ra] Failed to parse __NEXT_DATA__ JSON")
        return None


def _parse_events_from_next_data(
    next_data: Dict[str, Any],
    city: str,
    country_code: str,
) -> List[Dict[str, Any]]:
    """
    Extract normalized event dicts from RA's __NEXT_DATA__ JSON.

    The structure varies but typically lives under:
      props.pageProps.dehydratedState.queries[].state.data.listing.data[]
    or similar paths. We search recursively for event-like objects.
    """
    events: List[Dict[str, Any]] = []

    # Try the common Next.js data path
    try:
        page_props = next_data.get("props", {}).get("pageProps", {})

        # RA uses Apollo/urql — look for dehydrated state with event data
        dehydrated = page_props.get("dehydratedState", {})
        queries = dehydrated.get("queries", [])

        for query in queries:
            state_data = query.get("state", {}).get("data", {})
            # Look for listing data (events are usually in a listing object)
            _extract_events_from_data(state_data, events, city, country_code)

        # Also check direct pageProps for event arrays
        if not events:
            _extract_events_from_data(page_props, events, city, country_code)

    except Exception as exc:
        logger.warning("[ra] Error parsing __NEXT_DATA__: %s", exc)

    return events


def _extract_events_from_data(
    data: Any,
    events: List[Dict[str, Any]],
    city: str,
    country_code: str,
    depth: int = 0,
) -> None:
    """
    Recursively search a data structure for event-like objects.

    An event-like object has at least 'title' (or 'name') and some date field.
    Limits recursion depth to avoid infinite loops.
    """
    if depth > 8 or data is None:
        return

    if isinstance(data, dict):
        # Check if this dict looks like an event
        if _is_event_like(data):
            normalized = _normalize_event(data, city, country_code)
            if normalized:
                events.append(normalized)
            return

        # Recurse into dict values
        for value in data.values():
            _extract_events_from_data(value, events, city, country_code, depth + 1)

    elif isinstance(data, list):
        for item in data:
            _extract_events_from_data(item, events, city, country_code, depth + 1)


def _is_event_like(obj: Dict[str, Any]) -> bool:
    """Check if a dict looks like an RA event object."""
    # RA events typically have: title/name, startTime/date, venue
    has_title = bool(obj.get("title") or obj.get("name"))
    has_date = bool(
        obj.get("startTime") or obj.get("date") or obj.get("start_time")
    )
    has_venue_or_type = bool(
        obj.get("venue") or obj.get("contentUrl") or obj.get("__typename") == "Event"
    )
    return has_title and (has_date or has_venue_or_type)


def _normalize_event(
    raw: Dict[str, Any],
    city: str,
    country_code: str,
) -> Optional[Dict[str, Any]]:
    """Normalize an RA event object into our standard EventResult format."""
    title = raw.get("title") or raw.get("name") or ""
    if not title:
        return None

    # Event URL
    event_id = raw.get("id") or raw.get("contentUrl", "").split("/")[-1]
    content_url = raw.get("contentUrl") or ""
    if content_url and not content_url.startswith("http"):
        url = f"{_BASE_URL}{content_url}"
    elif content_url:
        url = content_url
    elif event_id:
        url = f"{_BASE_URL}/events/{event_id}"
    else:
        url = ""

    # Date
    date_start = raw.get("startTime") or raw.get("date") or raw.get("start_time")
    date_end = raw.get("endTime") or raw.get("end_time")

    # Venue
    venue_raw = raw.get("venue") or {}
    if isinstance(venue_raw, dict):
        venue = {
            "name": venue_raw.get("name", ""),
            "address": venue_raw.get("address", ""),
            "city": city.title(),
            "state": None,
            "country": country_code.upper(),
            "lat": venue_raw.get("lat") or venue_raw.get("latitude"),
            "lon": venue_raw.get("lng") or venue_raw.get("longitude"),
        }
    else:
        venue = {
            "name": str(venue_raw) if venue_raw else "",
            "address": "",
            "city": city.title(),
            "state": None,
            "country": country_code.upper(),
            "lat": None,
            "lon": None,
        }

    # Artists / lineup
    artists = raw.get("artists") or raw.get("lineup") or []
    if isinstance(artists, list):
        artist_names = [
            a.get("name") or a.get("title") or str(a)
            for a in artists
            if isinstance(a, dict)
        ]
    else:
        artist_names = []

    # Genres
    genres = []
    for genre in (raw.get("genres") or []):
        if isinstance(genre, dict):
            genres.append(genre.get("name", ""))
        elif isinstance(genre, str):
            genres.append(genre)

    # Description — combine lineup + genres into a useful description
    description_parts = []
    if artist_names:
        description_parts.append(f"Lineup: {', '.join(artist_names[:10])}")
    if genres:
        description_parts.append(f"Genres: {', '.join(genres)}")
    raw_desc = raw.get("description") or raw.get("content") or ""
    if raw_desc:
        if len(raw_desc) > _MAX_DESCRIPTION_CHARS:
            raw_desc = raw_desc[:_MAX_DESCRIPTION_CHARS] + "..."
        description_parts.append(raw_desc)
    description = "\n".join(description_parts)

    # Attendance
    rsvp_count = (
        raw.get("interestedCount")
        or raw.get("attending")
        or raw.get("goingCount")
    )

    # Tickets / pricing
    tickets = raw.get("tickets") or []
    is_paid = bool(tickets) or bool(raw.get("cost"))
    fee = None
    if raw.get("cost"):
        fee = {"amount": raw.get("cost"), "currency": "EUR"}

    # Image
    images = raw.get("images") or []
    image_url = None
    if images and isinstance(images, list):
        first_img = images[0]
        if isinstance(first_img, dict):
            image_url = first_img.get("filename") or first_img.get("url")
        elif isinstance(first_img, str):
            image_url = first_img
    if not image_url:
        image_url = raw.get("flyerFront") or raw.get("image")

    return {
        "id": str(event_id) if event_id else "",
        "provider": "resident_advisor",
        "title": title,
        "description": description,
        "url": url,
        "date_start": date_start,
        "date_end": date_end,
        "timezone": None,
        "event_type": "PHYSICAL",
        "venue": venue,
        "organizer": None,
        "rsvp_count": rsvp_count,
        "is_paid": is_paid,
        "fee": fee,
        "image_url": image_url,
        "artists": artist_names[:10] if artist_names else None,
        "genres": genres if genres else None,
    }


def _parse_events_from_html(
    html: str,
    city: str,
    country_code: str,
) -> List[Dict[str, Any]]:
    """
    Fallback parser: extract events from RA HTML when __NEXT_DATA__ is absent.

    Looks for event links and metadata in the rendered HTML. Less reliable than
    __NEXT_DATA__ but covers cases where RA changes their rendering approach.
    """
    events: List[Dict[str, Any]] = []

    # Find event links: /events/NNNNNN pattern
    event_blocks = re.findall(
        r'<a[^>]*href="(/events/\d+)"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    )

    seen_ids: set = set()
    for href, inner_html in event_blocks:
        event_id = href.split("/")[-1]
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)

        # Extract title from link text (strip HTML tags)
        title = re.sub(r"<[^>]+>", "", inner_html).strip()
        if not title or len(title) < 3:
            continue

        events.append({
            "id": event_id,
            "provider": "resident_advisor",
            "title": title,
            "description": "",
            "url": f"{_BASE_URL}/events/{event_id}",
            "date_start": None,
            "date_end": None,
            "timezone": None,
            "event_type": "PHYSICAL",
            "venue": {
                "name": "",
                "address": "",
                "city": city.title(),
                "state": None,
                "country": country_code.upper(),
                "lat": None,
                "lon": None,
            },
            "organizer": None,
            "rsvp_count": None,
            "is_paid": None,
            "fee": None,
            "image_url": None,
        })

    return events


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_events_async(
    *,
    city: str,
    query: str = "",
    count: int = 10,
    secrets_manager: Optional["SecretsManager"] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Search for events on Resident Advisor by city.

    RA does not support keyword search on listing pages — results are all
    upcoming events for the city. The query parameter is used for client-side
    filtering after fetching.

    Args:
        city:            City name or "city, country" string.
        query:           Optional keyword filter (applied client-side after fetching).
        count:           Maximum number of events to return (default 10, max 50).
        secrets_manager: Required for Firecrawl API key (RA blocks direct HTTP).

    Returns:
        Tuple of (events_list, total_available).

    Raises:
        ValueError: If the city is not supported by RA or Firecrawl is unavailable.
    """
    country_code, city_slug = _resolve_city(city)
    url = f"{_BASE_URL}/events/{country_code}/{city_slug}"

    logger.debug("[ra] Fetching events: url=%s query=%r count=%d", url, query, count)

    html = await _fetch_page(url, secrets_manager=secrets_manager)

    # Try __NEXT_DATA__ first (structured, rich data)
    next_data = _extract_next_data(html)
    if next_data:
        events = _parse_events_from_next_data(next_data, city_slug, country_code)
        logger.debug("[ra] Parsed %d events from __NEXT_DATA__", len(events))
    else:
        # Fallback to HTML parsing
        events = _parse_events_from_html(html, city_slug, country_code)
        logger.debug("[ra] Parsed %d events from HTML fallback", len(events))

    total_available = len(events)

    # Client-side keyword filtering (RA doesn't support server-side search)
    if query:
        query_lower = query.lower()
        query_tokens = query_lower.split()
        events = [
            e for e in events
            if any(
                token in (e.get("title", "") + " " + e.get("description", "")).lower()
                for token in query_tokens
            )
        ]

    # Sort by date ascending (soonest first); None dates to end.
    events.sort(key=lambda e: (e.get("date_start") or "9999"))

    # Trim to requested count.
    events = events[:count]

    logger.info(
        "[ra] Search complete: %d events returned (total=%d) city=%r query=%r",
        len(events),
        total_available,
        city_slug,
        query,
    )

    return events, total_available
