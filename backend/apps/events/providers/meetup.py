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

import logging
import time
import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.shared.testing.caching_http_transport import create_http_client
from backend.shared.python_utils.geo_utils import CITY_COORDS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAPHQL_URL = "https://www.meetup.com/gql2"

# CITY_COORDS is imported from backend.shared.python_utils.geo_utils — shared with Luma.

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
_IMAGE_FETCH_TIMEOUT_SECONDS = 10.0
_IMAGE_FETCH_CONCURRENCY = 6
_OG_IMAGE_META_PATTERNS = (
    re.compile(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]*name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']twitter:image["\']', re.IGNORECASE),
)


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
    count: int = 10,
    proxy_url: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
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
        count:        Maximum number of events to return (default 10, max 50)
        proxy_url:    Optional HTTP proxy URL (e.g. Webshare rotating residential).
                      Format: "http://user:pass@p.webshare.io:80"
                      When provided, all requests are routed through this proxy
                      to avoid Meetup IP-based rate limiting.

    Returns:
        Tuple of:
          - List of normalised event dicts. Each dict contains:
            id, provider, title, description, url, date_start, date_end,
            timezone, event_type, venue (or None), organizer, rsvp_count,
            is_paid, fee (or None), image_url (always None — not available on gql2)
          - total_count: Total number of matching events on Meetup (may exceed the
            returned list if count < totalCount). Useful for informing the user that
            more events exist beyond the requested count.

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

    logger.debug(
        "Meetup search: keywords=%r lat=%.4f lon=%.4f count=%d proxy=%s",
        keywords,
        lat,
        lon,
        count,
        "yes" if proxy_url else "no",
    )
    t0 = time.time()

    # Use httpx instead of requests — httpx correctly handles proxy authentication
    # for HTTPS targets via HTTP CONNECT tunnels (avoids 407 Proxy Auth Required that
    # occurs with the requests library when using Webshare's rotating residential proxy
    # endpoint at p.webshare.io:80).
    try:
        with httpx.Client(
            proxy=proxy_url,  # httpx accepts None cleanly; handles HTTPS CONNECT auth correctly
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            resp = client.post(GRAPHQL_URL, json=payload, headers=_HEADERS)
    except httpx.ProxyError as exc:
        raise RuntimeError(f"Proxy error connecting to Meetup: {exc}") from exc
    except httpx.RequestError as exc:
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

    return ([_normalise_event(edge.get("node", {})) for edge in edges], total_count)


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
    count: int = 10,
    proxy_url: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Async implementation of event search using httpx.AsyncClient.

    Uses httpx.AsyncClient directly for non-blocking async HTTP — avoids
    spawning a thread pool executor. httpx handles HTTPS-over-proxy CONNECT
    tunnels correctly, resolving the 407 Proxy Authentication Required error
    that occurred with the synchronous requests library.

    Args:
        keywords:     Search keyword(s), e.g. "AI", "Python", "hackathon"
        lat:          Latitude of search centre (required)
        lon:          Longitude of search centre (required)
        city:         City display name (optional)
        country:      ISO 3166-1 alpha-2 country code (optional)
        start_date:   ISO 8601 datetime string
        end_date:     ISO 8601 datetime string
        event_type:   "PHYSICAL", "ONLINE", or None (both)
        radius_miles: Search radius in miles (default 25)
        count:        Maximum number of events to return (default 10, max 50)
        proxy_url:    Optional HTTP proxy URL (e.g. "http://user:pass@p.webshare.io:80").
                      Typically a Webshare rotating residential proxy URL.
                      httpx correctly passes credentials in the CONNECT tunnel for HTTPS targets.

    Returns:
        Tuple of:
          - List of normalised event dicts (same schema as search_events())
          - total_count: Total number of matching events on Meetup (may exceed returned list)
    """
    count = max(1, min(count, 50))

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

    logger.debug(
        "Meetup async search: keywords=%r lat=%.4f lon=%.4f count=%d proxy=%s",
        keywords,
        lat,
        lon,
        count,
        "yes" if proxy_url else "no",
    )
    t0 = time.time()

    try:
        async with create_http_client(
            "meetup",
            proxy=proxy_url,
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            resp = await client.post(GRAPHQL_URL, json=payload, headers=_HEADERS)
    except httpx.ProxyError as exc:
        raise RuntimeError(f"Proxy error connecting to Meetup: {exc}") from exc
    except httpx.RequestError as exc:
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
        "Meetup async search complete in %.2fs: %d events returned (totalCount=%d)",
        duration,
        len(edges),
        total_count,
    )

    normalised_events = [_normalise_event(edge.get("node", {})) for edge in edges]
    await _enrich_events_with_image_urls_async(
        events=normalised_events,
        proxy_url=proxy_url,
    )
    return (normalised_events, total_count)


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
        "image_url": None,
    }


async def _enrich_events_with_image_urls_async(
    *,
    events: List[Dict[str, Any]],
    proxy_url: Optional[str],
) -> None:
    """Populate missing Meetup event image URLs by scraping event page metadata."""
    events_needing_images = [event for event in events if event.get("url") and not event.get("image_url")]
    if not events_needing_images:
        return

    semaphore = asyncio.Semaphore(_IMAGE_FETCH_CONCURRENCY)

    async with create_http_client(
        "meetup",
        proxy=proxy_url,
        timeout=_IMAGE_FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        async def fetch_and_attach(event: Dict[str, Any]) -> None:
            async with semaphore:
                image_url = await _fetch_event_image_url_async(client, event["url"])
                if image_url:
                    event["image_url"] = image_url

        await asyncio.gather(*(fetch_and_attach(event) for event in events_needing_images))


async def _fetch_event_image_url_async(client: httpx.AsyncClient, event_url: str) -> Optional[str]:
    """Fetch an event page and extract og:image/twitter:image URL."""
    try:
        response = await client.get(
            event_url,
            headers={
                "User-Agent": _HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://www.meetup.com/find/",
            },
        )
        if response.status_code != 200:
            return None

        return _extract_social_image_url(response.text)
    except Exception as exc:
        logger.debug("Failed to fetch Meetup event image from %s: %s", event_url, exc)
        return None


def _extract_social_image_url(html: str) -> Optional[str]:
    """Extract first og:image/twitter:image URL from page HTML."""
    if not html:
        return None

    for pattern in _OG_IMAGE_META_PATTERNS:
        match = pattern.search(html)
        if match:
            image_url = match.group(1).strip()
            if image_url:
                return image_url
    return None


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

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        # Step 1: Fetch the main /find/ page to extract the Next.js buildId.
        r = client.get(
            "https://www.meetup.com/find/",
            headers={**headers_html, "Accept": "text/html"},
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
        data_r = client.get(
            f"https://www.meetup.com/_next/data/{build_id}/find.json",
            headers=headers_html,
            params={"keywords": "test", "location": location_str, "source": "EVENTS"},
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
