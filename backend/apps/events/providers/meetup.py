# backend/apps/events/providers/meetup.py
#
# Meetup.com event search provider.
#
# Uses Meetup's internal GraphQL endpoint (gql2) which is publicly accessible
# without authentication. The approach was reverse-engineered from Meetup's web app:
#
#   POST https://www.meetup.com/gql2
#
# Key design decisions:
# - No API key needed — the endpoint accepts unauthenticated requests
# - Explicit lat/lon in the GraphQL filter bypasses server-side geo-IP resolution
#   (the old _next/data approach resolved location from the server's IP, not the
#    user's location string)
# - Description is returned inline — no extra requests needed (1–5 KB per event)
# - Relay cursor-based pagination via pageInfo.endCursor / hasNextPage
#
# Request cost estimation:
#   Typical response: ~50–200 KB per page (50 events)
#   Webshare proxy cost: $0.10/GB (rotating residential proxy)
#   Cost per request: 200 KB × ($0.10/1,000,000 KB) = $0.00002 ≈ 0.002 cents
#   → margin at 5 credits ($0.005 at $0.001/credit) is ~250× above raw proxy cost
#   → 5 credits covers compute + markup comfortably
#
# Rate limiting:
#   Meetup has undocumented server-side throttling. A 1.2s polite delay is added
#   between paginated requests. Single-page requests have no forced delay.

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAPHQL_URL = "https://www.meetup.com/gql2"

# Well-known city coordinates for fast local lookup (no network request needed).
# Format: city_key → (lat, lon, display_name, ISO 3166-1 alpha-2 country code)
CITY_COORDS: Dict[str, Tuple[float, float, str, str]] = {
    "berlin": (52.52, 13.405, "Berlin", "de"),
    "munich": (48.137, 11.576, "Munich", "de"),
    "hamburg": (53.551, 9.993, "Hamburg", "de"),
    "cologne": (50.938, 6.957, "Cologne", "de"),
    "frankfurt": (50.110, 8.682, "Frankfurt", "de"),
    "stuttgart": (48.775, 9.182, "Stuttgart", "de"),
    "dusseldorf": (51.227, 6.773, "Düsseldorf", "de"),
    "london": (51.507, -0.128, "London", "gb"),
    "manchester": (53.480, -2.242, "Manchester", "gb"),
    "birmingham": (52.480, -1.902, "Birmingham", "gb"),
    "paris": (48.857, 2.352, "Paris", "fr"),
    "lyon": (45.764, 4.836, "Lyon", "fr"),
    "amsterdam": (52.374, 4.898, "Amsterdam", "nl"),
    "rotterdam": (51.924, 4.477, "Rotterdam", "nl"),
    "zurich": (47.376, 8.548, "Zurich", "ch"),
    "vienna": (48.208, 16.373, "Vienna", "at"),
    "brussels": (50.851, 4.352, "Brussels", "be"),
    "stockholm": (59.333, 18.065, "Stockholm", "se"),
    "oslo": (59.913, 10.752, "Oslo", "no"),
    "copenhagen": (55.676, 12.568, "Copenhagen", "dk"),
    "helsinki": (60.169, 24.938, "Helsinki", "fi"),
    "madrid": (40.416, -3.703, "Madrid", "es"),
    "barcelona": (41.386, 2.170, "Barcelona", "es"),
    "rome": (41.902, 12.496, "Rome", "it"),
    "milan": (45.464, 9.189, "Milan", "it"),
    "lisbon": (38.716, -9.139, "Lisbon", "pt"),
    "warsaw": (52.229, 21.012, "Warsaw", "pl"),
    "prague": (50.087, 14.421, "Prague", "cz"),
    "budapest": (47.498, 19.040, "Budapest", "hu"),
    "new york": (40.713, -74.006, "New York", "us"),
    "los angeles": (34.052, -118.244, "Los Angeles", "us"),
    "chicago": (41.878, -87.630, "Chicago", "us"),
    "san francisco": (37.775, -122.418, "San Francisco", "us"),
    "seattle": (47.606, -122.332, "Seattle", "us"),
    "boston": (42.360, -71.059, "Boston", "us"),
    "austin": (30.267, -97.743, "Austin", "us"),
    "new york city": (40.713, -74.006, "New York", "us"),
    "nyc": (40.713, -74.006, "New York", "us"),
    "sf": (37.775, -122.418, "San Francisco", "us"),
    "toronto": (43.651, -79.347, "Toronto", "ca"),
    "vancouver": (49.283, -123.121, "Vancouver", "ca"),
    "montreal": (45.508, -73.588, "Montreal", "ca"),
    "sydney": (-33.868, 151.209, "Sydney", "au"),
    "melbourne": (-37.814, 144.963, "Melbourne", "au"),
    "tokyo": (35.689, 139.691, "Tokyo", "jp"),
    "osaka": (34.694, 135.502, "Osaka", "jp"),
    "seoul": (37.566, 126.978, "Seoul", "kr"),
    "beijing": (39.906, 116.391, "Beijing", "cn"),
    "shanghai": (31.228, 121.474, "Shanghai", "cn"),
    "singapore": (1.352, 103.820, "Singapore", "sg"),
    "bangalore": (12.972, 77.594, "Bangalore", "in"),
    "mumbai": (19.076, 72.877, "Mumbai", "in"),
    "delhi": (28.614, 77.209, "Delhi", "in"),
    "dubai": (25.204, 55.270, "Dubai", "ae"),
    "cape town": (-33.925, 18.424, "Cape Town", "za"),
    "sao paulo": (-23.548, -46.637, "São Paulo", "br"),
    "buenos aires": (-34.608, -58.437, "Buenos Aires", "ar"),
    "mexico city": (19.432, -99.133, "Mexico City", "mx"),
}

# HTTP headers that mimic what the Meetup web application sends.
# Necessary to avoid being treated as an automated bot.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://www.meetup.com/find/",
    "apollographql-client-name": "nextjs-web",
}

# GraphQL query for event search.
# Fields selected to match what Meetup's web app fetches (visible in __APOLLO_STATE__).
# Description is included inline — no extra per-event requests needed.
_EVENT_SEARCH_QUERY = """
query eventSearch(
    $filter: EventSearchFilter!,
    $sort: KeywordSort,
    $first: Int,
    $after: String
) {
    eventSearch(filter: $filter, sort: $sort, first: $first, after: $after) {
        pageInfo {
            hasNextPage
            endCursor
        }
        totalCount
        edges {
            node {
                id
                title
                dateTime
                endTime
                eventType
                eventUrl
                description
                rsvps { totalCount }
                venue {
                    name
                    address
                    city
                    state
                    country
                    lat
                    lon
                }
                group {
                    id
                    name
                    urlname
                    timezone
                }
                feeSettings {
                    amount
                    currency
                }
            }
        }
    }
}
"""

# Polite delay between consecutive paginated requests to avoid triggering
# Meetup's undocumented rate limiter.
_PAGE_DELAY_SECONDS = 1.2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_location(location_str: str) -> Tuple[float, float, str, str]:
    """
    Resolve a location string to (lat, lon, city, country_code).

    Tries the built-in CITY_COORDS table first (no network request).
    Falls back to Meetup's _next/data geocoder for unknown cities.

    Args:
        location_str: City name, e.g. "Berlin, Germany" or "berlin"

    Returns:
        Tuple of (lat, lon, city_name, country_code)

    Raises:
        ValueError: If the location cannot be resolved
    """
    # Normalise: take only the city portion before any comma, lowercase.
    key = location_str.lower().split(",")[0].strip()

    if key in CITY_COORDS:
        lat, lon, city, country = CITY_COORDS[key]
        logger.debug(
            "Resolved location %r from local lookup: %s (%.4f, %.4f)",
            location_str,
            city,
            lat,
            lon,
        )
        return lat, lon, city, country

    # Fall back to Meetup's internal geocoder via the _next/data endpoint.
    # This endpoint accepts a location string and returns the resolved coordinates.
    logger.info(
        "Location %r not in local cache — resolving via Meetup geocoder...",
        location_str,
    )
    try:
        return _resolve_via_meetup_geocoder(location_str)
    except Exception as exc:
        raise ValueError(
            f"Could not resolve location {location_str!r}: {exc}. "
            "Try providing explicit lat/lon values instead."
        ) from exc


def search_events(
    keywords: str,
    lat: float,
    lon: float,
    city: str = "",
    country: str = "",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    event_type: Optional[str] = None,
    radius_miles: float = 25.0,
    count: int = 20,
    proxy_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search Meetup.com for events matching the given criteria.

    This is a synchronous function intended to be run in a thread pool executor
    from async callers (to avoid blocking the async event loop).

    Args:
        keywords:     Search keyword(s), e.g. "AI", "Python", "hackathon"
        lat:          Latitude of search centre (required)
        lon:          Longitude of search centre (required)
        city:         City display name (optional — doesn't affect geo-resolution)
        country:      ISO 3166-1 alpha-2 country code (optional, e.g. "de")
        start_date:   ISO 8601 datetime with timezone offset, e.g.
                      "2026-03-01T00:00:00+01:00[Europe/Berlin]"
        end_date:     ISO 8601 datetime with timezone offset (same format)
        event_type:   "PHYSICAL", "ONLINE", or None (both)
        radius_miles: Search radius in miles (default 25, ~40 km)
        count:        Maximum number of events to return (1–50)
        proxy_url:    Optional HTTP proxy URL (e.g. Webshare rotating residential).
                      Format: "http://user:pass@p.webshare.io:80"
                      When provided, all requests are routed through this proxy
                      to avoid Meetup IP-based rate limiting.

    Returns:
        List of normalised event dicts. Each dict contains:
            id, provider, title, description, url, date_start, date_end,
            timezone, event_type, venue (or None), organizer, rsvp_count,
            is_paid, fee (or None), image_url (always None — not available on gql2)

    Raises:
        RuntimeError: On HTTP or GraphQL errors
        ValueError:   If the response structure is unexpected
    """
    count = max(1, min(count, 50))  # Clamp to valid range

    gql_filter: Dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "query": keywords,
        "radius": radius_miles,
        "doConsolidateEvents": False,
    }
    if city:
        gql_filter["city"] = city
    if country:
        gql_filter["country"] = country
    if start_date:
        gql_filter["startDateRange"] = start_date
    if end_date:
        gql_filter["endDateRange"] = end_date
    if event_type:
        gql_filter["eventType"] = event_type

    variables: Dict[str, Any] = {
        "filter": gql_filter,
        "sort": {"sortField": "RELEVANCE"},
        "first": count,
    }
    payload = {
        "operationName": "eventSearch",
        "variables": variables,
        "query": _EVENT_SEARCH_QUERY,
    }

    # Build proxies dict for requests library (None = no proxy)
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    logger.debug(
        "Meetup search: keywords=%r lat=%.4f lon=%.4f count=%d proxy=%s",
        keywords,
        lat,
        lon,
        count,
        "yes" if proxy_url else "no",
    )
    t0 = time.time()

    try:
        resp = requests.post(
            GRAPHQL_URL,
            json=payload,
            headers=_HEADERS,
            timeout=20,
            proxies=proxies,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"HTTP request to Meetup failed: {exc}") from exc

    duration = time.time() - t0

    if resp.status_code != 200:
        raise RuntimeError(
            f"Meetup GraphQL returned HTTP {resp.status_code} "
            f"after {duration:.2f}s. Body: {resp.text[:300]}"
        )

    data = resp.json()

    if "errors" in data:
        import json as _json
        raise RuntimeError(
            f"Meetup GraphQL errors: {_json.dumps(data['errors'], indent=2)}"
        )

    event_search = data.get("data", {}).get("eventSearch")
    if event_search is None:
        raise ValueError(
            "No 'eventSearch' field in Meetup GraphQL response. "
            f"Response keys: {list(data.get('data', {}).keys())}"
        )

    edges = event_search.get("edges", [])
    total_count = event_search.get("totalCount", 0)

    logger.info(
        "Meetup search complete in %.2fs: %d events returned (totalCount=%d)",
        duration,
        len(edges),
        total_count,
    )

    return [_normalise_event(edge.get("node", {})) for edge in edges]


async def search_events_async(
    keywords: str,
    lat: float,
    lon: float,
    city: str = "",
    country: str = "",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    event_type: Optional[str] = None,
    radius_miles: float = 25.0,
    count: int = 20,
    proxy_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Async wrapper around search_events().

    Runs the synchronous HTTP call in a thread pool executor to avoid blocking
    the FastAPI async event loop.

    Args:
        proxy_url: Optional HTTP proxy URL forwarded to search_events().
                   Typically a Webshare rotating residential proxy URL.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: search_events(
            keywords=keywords,
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
        ),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _normalise_event(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalise a single Meetup GraphQL event node into the canonical EventResult schema.

    Args:
        node: Raw event node dict from GraphQL response

    Returns:
        Normalised event dict with consistent field names
    """
    venue_raw = node.get("venue") or {}
    group_raw = node.get("group") or {}
    fee_raw = node.get("feeSettings")

    venue: Optional[Dict[str, Any]] = None
    if venue_raw:
        venue = {
            "name": venue_raw.get("name"),
            "address": venue_raw.get("address"),
            "city": venue_raw.get("city"),
            "state": venue_raw.get("state"),
            "country": venue_raw.get("country"),
            "lat": venue_raw.get("lat"),
            "lon": venue_raw.get("lon"),
        }

    fee: Optional[Dict[str, Any]] = None
    if fee_raw:
        fee = {
            "amount": fee_raw.get("amount"),
            "currency": fee_raw.get("currency"),
        }

    return {
        "id": node.get("id"),
        "provider": "meetup",
        "title": node.get("title"),
        "description": node.get("description", ""),
        "url": node.get("eventUrl"),
        "date_start": node.get("dateTime"),
        "date_end": node.get("endTime"),
        "timezone": group_raw.get("timezone"),
        "event_type": node.get("eventType"),  # "PHYSICAL" | "ONLINE"
        "venue": venue,
        "organizer": {
            "id": group_raw.get("id"),
            "name": group_raw.get("name"),
            "slug": group_raw.get("urlname"),
        },
        "rsvp_count": (node.get("rsvps") or {}).get("totalCount", 0),
        "is_paid": fee is not None,
        "fee": fee,
        "image_url": None,  # imageUrl field not available on Meetup Event type via gql2
    }


def _resolve_via_meetup_geocoder(location_str: str) -> Tuple[float, float, str, str]:
    """
    Resolve a location string using Meetup's internal geocoder.

    Fetches the Next.js buildId from the /find/ page, then queries the
    _next/data endpoint which accepts a location string and returns resolved
    coordinates from Meetup's server-side geocoder.

    This is a fallback for cities not in the built-in CITY_COORDS table.

    Args:
        location_str: Location string such as "Zurich" or "Kyoto, Japan"

    Returns:
        Tuple of (lat, lon, city_name, country_code)

    Raises:
        ValueError: If coordinates cannot be resolved
    """
    headers_html = {
        "User-Agent": _HEADERS["User-Agent"],
        "Accept": "application/json, */*;q=0.1",
        "Referer": "https://www.meetup.com/find/",
        "x-nextjs-data": "1",
    }

    # Step 1: Fetch the main /find/ page to extract the Next.js buildId.
    r = requests.get(
        "https://www.meetup.com/find/",
        headers={**headers_html, "Accept": "text/html"},
        timeout=15,
    )
    build_id = r.headers.get("X-Build-Version", "")
    if not build_id:
        marker = '"buildId":"'
        idx = r.text.find(marker)
        if idx != -1:
            end_idx = r.text.index('"', idx + len(marker))
            build_id = r.text[idx + len(marker) : end_idx]

    if not build_id:
        raise ValueError(
            "Could not extract Next.js buildId from Meetup /find/ page. "
            "The page structure may have changed."
        )

    # Step 2: Query _next/data with the location string.
    data_r = requests.get(
        f"https://www.meetup.com/_next/data/{build_id}/find.json",
        headers=headers_html,
        params={"keywords": "test", "location": location_str, "source": "EVENTS"},
        timeout=15,
    )
    page_props = data_r.json().get("pageProps", {})
    loc = page_props.get("userLocation", {})

    if not loc or not loc.get("lat") or not loc.get("lon"):
        raise ValueError(
            f"Meetup geocoder returned no coordinates for {location_str!r}."
        )

    return (
        float(loc["lat"]),
        float(loc["lon"]),
        loc.get("city", ""),
        loc.get("country", ""),
    )
