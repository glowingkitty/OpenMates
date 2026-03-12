# backend/apps/events/providers/luma.py
#
# Luma.com (lu.ma) event search provider.
#
# Uses Luma's internal API at api2.luma.com — discovered by intercepting
# browser network traffic on luma.com. No API key or auth required.
#
# Proxy fallback: All HTTP requests are attempted without a proxy first.
# If Luma rejects the direct request (HTTP 403/429/5xx or connection error),
# the request is retried once via the Webshare rotating residential proxy
# (same credentials used for Meetup). proxy_url is passed in from the skill
# layer. This makes the provider future-proof against Cloudflare bot-protection
# being enabled on luma.com or api2.luma.com.
#
# Architecture: Reverse-engineered from luma.com web app (March 2026).
# See docs/apis/luma.md for full integration summary.
#
# Tests: scripts/api_tests/test_luma_api.py

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.shared.python_utils.geo_utils import geocode_address

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://api2.luma.com"
_EVENTS_ENDPOINT = f"{API_BASE}/discover/get-paginated-events"

# Maximum events per page Luma returns (empirically confirmed; 40 is safe).
_MAX_PAGE_SIZE = 40

# Polite inter-page delay between paginated requests.
_PAGE_DELAY_SECONDS = 1.2

# Timeout for all HTTP requests (seconds).
_HTTP_TIMEOUT = 20.0

# Maximum description length to return (characters). ProseMirror docs can be large.
_MAX_DESCRIPTION_CHARS = 2000

# HTTP status codes indicating Luma is rejecting direct (non-proxy) requests.
# On these codes, the request is retried once via the Webshare proxy.
# 429 = rate-limited, 403 = bot-blocked, 5xx = server-side rejection.
_REJECTION_STATUS_CODES = {403, 429, 500, 502, 503, 504}

# Headers mimicking what luma.com sends. Origin+Referer are required for CORS.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://luma.com",
    "Referer": "https://luma.com/discover",
}

_HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ---------------------------------------------------------------------------
# City slug -> discover_place_api_id mapping
# Source: GET api2.luma.com/discover/bootstrap-page (scraped March 2026, 78 cities)
# ---------------------------------------------------------------------------
CITY_PLACE_IDS: Dict[str, str] = {
    "helsinki": "discplace-gEii5B2Ju5KKRNH",
    "stockholm": "discplace-e7EG0Ef6S2aQnvN",
    "copenhagen": "discplace-CmmHAjPdBSsqmJf",
    "warsaw": "discplace-BSpBjLlnFdGp6E5",
    "berlin": "discplace-gCfX0s3E9Hgo3rG",
    "hamburg": "discplace-kFH1oo7VN0HmF4E",
    "prague": "discplace-jWzqmfVkPFSf2vB",
    "vienna": "discplace-v9JQWP1l4KJGfOZ",
    "budapest": "discplace-VwI6bKrN1Mxv22k",
    "amsterdam": "discplace-R1gEkZRLUTG3bBX",
    "munich": "discplace-4bTrg3iQ3rfv3a9",
    "brussels": "discplace-jlBIvqwnuCzJM3c",
    "zurich": "discplace-1HZTRY0ZijTqV2c",
    "london": "discplace-AQ5IMCGOOTyNRue",
    "paris": "discplace-IK8LsBfq0oRHKTj",
    "lausanne": "discplace-LRFHt5Bc0xY2bGp",
    "milan": "discplace-dRAGxr11HCxJnO0",
    "geneva": "discplace-Kv2OPBqMNRtOkB7",
    "dublin": "discplace-bRGm0QsXOl5Kk3b",
    "istanbul": "discplace-QNBFkOSR6m7OjpH",
    "rome": "discplace-YfRz2KSnQ7xhcJu",
    "barcelona": "discplace-H3dAFV5WDGCjJZ7",
    "madrid": "discplace-03jiEcS4mvwJuDa",
    "tel-aviv": "discplace-fHkSoyCyugTZSbr",
    "lisbon": "discplace-mgGFFo5EDdyekyE",
    "dubai": "discplace-d3kg1aLIJ5ROF6S",
    "new-delhi": "discplace-CzipmKodUYN2Dfx",
    "mumbai": "discplace-Q5hkYsjZs1ZDJcU",
    "montreal": "discplace-CXKKcJmNkbj6ikW",
    "lagos": "discplace-ARF3ZNcu47bs56x",
    "boston": "discplace-VWeZ1zUvnawYHMj",
    "toronto": "discplace-Cx3JMS6vXKAbhV5",
    "nyc": "discplace-Izx1rQVSh8njYpP",
    "new-york": "discplace-Izx1rQVSh8njYpP",
    "waterloo": "discplace-idpnif8MiNuyYI7",
    "philadelphia": "discplace-VGLZZfVwOKRD1Yd",
    "bengaluru": "discplace-G0tGUVYwl7T17Sb",
    "bangalore": "discplace-G0tGUVYwl7T17Sb",
    "nairobi": "discplace-YSx1DPerjjIyq7M",
    "washington-dc": "discplace-AANPgOymN6bqFn8",
    "dc": "discplace-AANPgOymN6bqFn8",
    "minneapolis": "discplace-IHi0OqR5c6t4Hb3",
    "seoul": "discplace-eQieweHXBFCWbCj",
    "calgary": "discplace-7AxSBoZHQy3igIZ",
    "chicago": "discplace-NdGm35qFD0vaXNF",
    "vancouver": "discplace-4fa7ldlAkBTTivm",
    "seattle": "discplace-FQ4E58PeBMHGTKK",
    "atlanta": "discplace-C6hWuH5suHJIUqC",
    "tokyo": "discplace-9H7asQEvWiv6DA9",
    "hong-kong": "discplace-z9B5Guglh2WINA1",
    "hongkong": "discplace-z9B5Guglh2WINA1",
    "bangkok": "discplace-1bk5q2gBJbv7Ngw",
    "portland": "discplace-HthnjGVBzGh90sQ",
    "taipei": "discplace-fi7MDZq99wfKWfa",
    "denver": "discplace-I94ZmQKKyVnCQKv",
    "salt-lake-city": "discplace-gxZJbB572Ls8RRu",
    "miami": "discplace-fSrrRYurTwydAGK",
    "dallas": "discplace-Ez9iuaZfs6AZDls",
    "ho-chi-minh-city": "discplace-3ixpMOGpQaA4dWG",
    "houston": "discplace-aQeJaEtqg3shHZ1",
    "austin": "discplace-0tPy8KGz3xMycnt",
    "las-vegas": "discplace-RF9Yq9JDUxmcpTr",
    "san-francisco": "discplace-BDj7GNbGlsF7Cka",
    "sf": "discplace-BDj7GNbGlsF7Cka",
    "phoenix": "discplace-Vk9M1gTb4AMVXuD",
    "manila": "discplace-XeAvnK62YmCW54R",
    "kuala-lumpur": "discplace-O15L1VZiYe0GYGm",
    "los-angeles": "discplace-OgfEAh5KgfMzise",
    "la": "discplace-OgfEAh5KgfMzise",
    "san-diego": "discplace-MNBATdzid940kqJ",
    "sd": "discplace-MNBATdzid940kqJ",
    "singapore": "discplace-mUbtdfNjfWaLQ72",
    "mexico-city": "discplace-ntiNB0E437TyRqt",
    "medellin": "discplace-K11Mq0Pw6sbManZ",
    "bogota": "discplace-Rac9aE9RdKypLVS",
    "jakarta": "discplace-D0vMN5ttALav9XP",
    "cape-town": "discplace-YBoSEMjeIijj03X",
    "capetown": "discplace-YBoSEMjeIijj03X",
    "honolulu": "discplace-Ce0yAAavKebPHcB",
    "rio-de-janeiro": "discplace-EWglyhh4fsHKo2F",
    "rio": "discplace-EWglyhh4fsHKo2F",
    "sao-paulo": "discplace-AQZnCu9wl4LmOIp",
    "buenos-aires": "discplace-wX2J5xGwAJpznew",
    "brisbane": "discplace-SQBjjDiskwFZwtG",
    "sydney": "discplace-TPdKGPI56hGfOdi",
    "melbourne": "discplace-DlA8FnyHTxhIkN2",
    "auckland": "discplace-NvBaYaVTkHmsPVy",
}

_CITY_NAMES: Dict[str, str] = {
    "helsinki": "Helsinki", "stockholm": "Stockholm", "copenhagen": "Copenhagen",
    "warsaw": "Warsaw", "berlin": "Berlin", "hamburg": "Hamburg", "prague": "Prague",
    "vienna": "Vienna", "budapest": "Budapest", "amsterdam": "Amsterdam",
    "munich": "Munich", "brussels": "Brussels", "zurich": "Zurich",
    "london": "London", "paris": "Paris", "lausanne": "Lausanne", "milan": "Milan",
    "geneva": "Geneva", "dublin": "Dublin", "istanbul": "Istanbul", "rome": "Rome",
    "barcelona": "Barcelona", "madrid": "Madrid", "tel-aviv": "Tel Aviv-Yafo",
    "lisbon": "Lisbon", "dubai": "Dubai", "new-delhi": "New Delhi",
    "mumbai": "Mumbai", "montreal": "Montreal", "lagos": "Lagos",
    "boston": "Boston", "toronto": "Toronto", "nyc": "New York",
    "new-york": "New York", "waterloo": "Waterloo", "philadelphia": "Philadelphia",
    "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "nairobi": "Nairobi",
    "washington-dc": "Washington, DC", "dc": "Washington, DC",
    "minneapolis": "Minneapolis", "seoul": "Seoul", "calgary": "Calgary",
    "chicago": "Chicago", "vancouver": "Vancouver", "seattle": "Seattle",
    "atlanta": "Atlanta", "tokyo": "Tokyo", "hong-kong": "Hong Kong",
    "hongkong": "Hong Kong", "bangkok": "Bangkok", "portland": "Portland",
    "taipei": "Taipei", "denver": "Denver", "salt-lake-city": "Salt Lake City",
    "miami": "Miami", "dallas": "Dallas", "ho-chi-minh-city": "Ho Chi Minh City",
    "houston": "Houston", "austin": "Austin", "las-vegas": "Las Vegas",
    "san-francisco": "San Francisco", "sf": "San Francisco", "phoenix": "Phoenix",
    "manila": "Manila", "kuala-lumpur": "Kuala Lumpur", "los-angeles": "Los Angeles",
    "la": "Los Angeles", "san-diego": "San Diego", "sd": "San Diego",
    "singapore": "Singapore", "mexico-city": "Mexico City", "medellin": "Medellin",
    "bogota": "Bogota", "jakarta": "Jakarta", "cape-town": "Cape Town",
    "capetown": "Cape Town", "honolulu": "Honolulu", "rio-de-janeiro": "Rio de Janeiro",
    "rio": "Rio de Janeiro", "sao-paulo": "Sao Paulo", "buenos-aires": "Buenos Aires",
    "brisbane": "Brisbane", "sydney": "Sydney", "melbourne": "Melbourne",
    "auckland": "Auckland",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_city(city_input: str) -> Tuple[str, str, str]:
    """
    Resolve a city name or slug to (place_api_id, city_slug, city_display_name).

    Accepts: "Berlin", "berlin", "san francisco", "san-francisco", "sf", "nyc"

    Raises:
        ValueError: City is not in Luma's 78 featured city list.
    """
    slug = city_input.lower().strip().replace(" ", "-").replace("_", "-")
    place_id = CITY_PLACE_IDS.get(slug)
    if not place_id:
        seen_ids: set = set()
        canonical_slugs = []
        for s, pid in CITY_PLACE_IDS.items():
            if pid not in seen_ids:
                seen_ids.add(pid)
                canonical_slugs.append(s)
        raise ValueError(
            f"City {city_input!r} is not a Luma featured city (slug={slug!r}). "
            f"Supported slugs ({len(canonical_slugs)}): {', '.join(sorted(canonical_slugs))}"
        )
    display_name = _CITY_NAMES.get(slug, slug.replace("-", " ").title())
    return place_id, slug, display_name


async def search_events_async(
    city: str,
    query: Optional[str] = None,
    count: int = 10,
    fetch_descriptions: bool = True,
    proxy_url: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Search Luma.com for events in a specific city (async).

    Uses reverse-engineered api2.luma.com — no API key required.
    Results are sorted by start_at ascending (future events first).
    Descriptions are fetched in parallel from lu.ma/<slug> pages.

    Args:
        city:               City slug or name (e.g. "berlin", "San Francisco", "nyc").
                            Must be one of the 78 Luma featured cities.
        query:              Optional keyword filter (e.g. "AI", "startup").
                            When None, all upcoming events in the city are returned.
        count:              Maximum number of events to return (default 10).
        fetch_descriptions: If True (default), fetch full descriptions from event
                            pages in parallel. Adds 1 HTTP request per event.
                            Set to False for faster results without descriptions.
        proxy_url:          Optional Webshare rotating residential proxy URL
                            (e.g. "http://user-rotate:pass@p.webshare.io:80/").
                            Used as fallback if the direct request is rejected.
                            When None, no proxy fallback is attempted.

    Returns:
        Tuple of (events_list, total_available).

    Raises:
        ValueError: City not supported by Luma.
        RuntimeError: HTTP or API error from Luma (after proxy retry if applicable).
    """
    place_id, _slug, city_name = resolve_city(city)
    count = max(1, count)

    raw_entries: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    total_available = 0
    has_more = False

    # Fetch enough raw entries to satisfy count (with pagination if needed).
    while len(raw_entries) < count:
        page_limit = min(_MAX_PAGE_SIZE, count - len(raw_entries))
        params: Dict[str, Any] = {
            "discover_place_api_id": place_id,
            "pagination_limit": page_limit,
        }
        if query:
            params["query"] = query
        if cursor:
            params["pagination_cursor"] = cursor
            await asyncio.sleep(_PAGE_DELAY_SECONDS)

        t0 = time.time()
        try:
            resp = await _get_with_proxy_fallback(
                url=_EVENTS_ENDPOINT,
                params=params,
                headers=_HEADERS,
                proxy_url=proxy_url,
                label="Luma API",
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f"HTTP request to Luma API failed: {exc}") from exc

        if resp.status_code != 200:
            raise RuntimeError(
                f"Luma API returned HTTP {resp.status_code} "
                f"after {time.time() - t0:.2f}s. Body: {resp.text[:300]}"
            )

        data = resp.json()
        entries = data.get("entries", [])
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")

        raw_entries.extend(entries)

        if not has_more or not cursor:
            break

    total_available = len(raw_entries) if not has_more else len(raw_entries) + 20

    # Take only as many as requested.
    raw_entries = raw_entries[:count]

    # Normalise all entries into canonical event dicts (async for geocoding).
    events = list(await asyncio.gather(*[_normalise_event(e, city_name) for e in raw_entries]))

    # Fetch descriptions in parallel from lu.ma/<slug> pages.
    if fetch_descriptions and events:
        slugs = [ev.get("_url_slug") for ev in events]
        descriptions = await _fetch_descriptions_parallel(slugs, proxy_url=proxy_url)
        for ev, desc in zip(events, descriptions):
            ev["description"] = desc
            ev.pop("_url_slug", None)
    else:
        for ev in events:
            ev.pop("_url_slug", None)

    logger.info(
        "Luma search: city=%r query=%r -> %d events (total=%d, desc=%s)",
        city,
        query,
        len(events),
        total_available,
        "fetched" if fetch_descriptions else "skipped",
    )

    return events, total_available


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _normalise_event(entry: Dict[str, Any], city_fallback: str = "") -> Dict[str, Any]:
    """
    Normalise a raw Luma API entry into the canonical event provider schema.

    Async because: when Luma omits lat/lon from the coordinate field (common
    for many events), we geocode the venue address via geo_utils.geocode_address
    so the frontend can show an interactive map in EventEmbedFullscreen.

    Geocoding strategy (cheapest-first):
    1. Use Luma's coordinate field if present.
    2. Fall back to geo_utils city table (zero network cost).
    3. Fall back to Nominatim (OpenStreetMap) for full street addresses.
    4. Leave lat/lon as None if all strategies fail — no map is shown.

    RSVP display logic:
    - show_guest_list=True  -> show guest_count (0 means genuinely 0 RSVPs)
    - show_guest_list=False -> None (organiser hidden; 0 is API default, not real count)
    """
    ev = entry.get("event") or {}
    geo = ev.get("geo_address_info") or {}
    coord = ev.get("coordinate") or {}
    cal = entry.get("calendar") or {}
    hosts = entry.get("hosts") or []

    url_slug = ev.get("url", "")
    full_url = f"https://lu.ma/{url_slug}" if url_slug else None

    # Build venue only for offline/in-person events with location data.
    venue: Optional[Dict[str, Any]] = None
    if ev.get("location_type") == "offline" and (geo.get("city") or coord.get("latitude")):
        lat: Optional[float] = coord.get("latitude")
        lon: Optional[float] = coord.get("longitude")

        # Geocode when Luma omits coordinates — use full address for precision,
        # falling back to city-level if the address lookup fails.
        if lat is None or lon is None:
            coords = await geocode_address(
                address=geo.get("full_address") or geo.get("short_address"),
                city=geo.get("city") or city_fallback or None,
                country=geo.get("country"),
            )
            if coords:
                lat, lon = coords

        venue = {
            "name": geo.get("address"),
            "full_address": geo.get("full_address"),
            "short_address": geo.get("short_address"),
            "city": geo.get("city") or city_fallback,
            "state": geo.get("region"),
            "country": geo.get("country"),
            "country_code": geo.get("country_code"),
            "lat": lat,
            "lon": lon,
        }

    # When show_guest_list=False the API returns 0 by default — not a real zero.
    show_guest_list = ev.get("show_guest_list", True)
    rsvp_count: Optional[int] = entry.get("guest_count") if show_guest_list else None

    return {
        "id": ev.get("api_id") or entry.get("api_id"),
        "provider": "luma",
        "title": ev.get("name"),
        "description": None,  # Populated by _fetch_descriptions_parallel()
        "_url_slug": url_slug,  # Internal; removed before returning to caller
        "url": full_url,
        "date_start": ev.get("start_at"),
        "date_end": ev.get("end_at"),
        "timezone": ev.get("timezone"),
        "event_type": ev.get("location_type"),  # "offline" | "online" | "hybrid"
        "venue": venue,
        "organizer": {
            "name": cal.get("name"),
            "avatar_url": cal.get("avatar_url"),
            "slug": cal.get("slug"),
        },
        "hosts": [
            {"name": h.get("name"), "avatar_url": h.get("avatar_url")}
            for h in hosts if isinstance(h, dict)
        ],
        "rsvp_count": rsvp_count,
        "is_paid": bool((entry.get("ticket_info") or {}).get("is_paid")),
        "cover_url": ev.get("cover_url"),
        "city": geo.get("city") or city_fallback,
        "country": geo.get("country"),
    }


async def _get_with_proxy_fallback(
    url: str,
    headers: Dict[str, str],
    proxy_url: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    label: str = "",
) -> httpx.Response:
    """
    Perform an async GET request, retrying via proxy on rejection.

    Strategy:
      1. Attempt the request without a proxy (direct).
      2. If the response status is in _REJECTION_STATUS_CODES (403/429/5xx),
         OR a connection/network error occurs, AND proxy_url is provided:
         retry exactly once via the Webshare rotating residential proxy.
      3. Return the response from whichever attempt last completed (or raise
         if both attempts failed with network errors).

    This keeps Luma requests direct (cheaper, faster) under normal conditions
    while providing automatic fallback if Cloudflare bot-protection activates.

    Args:
        url:       Full URL to GET.
        headers:   HTTP headers dict to send with the request.
        proxy_url: Optional Webshare rotating proxy URL. If None, no retry is done.
        params:    Optional query parameters dict.
        label:     Short description for log messages (e.g. "Luma API", "lu.ma/abc").

    Returns:
        httpx.Response from the successful (or last) attempt.

    Raises:
        httpx.RequestError: If the direct request fails with a network error and
                            proxy_url is None, or if the proxy retry also fails.
    """
    # --- Attempt 1: direct (no proxy) ---
    direct_error: Optional[Exception] = None
    direct_resp: Optional[httpx.Response] = None
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            direct_resp = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as exc:
        direct_error = exc
        logger.debug("%s: direct request network error: %s", label, exc)

    # Return immediately if direct request returned a non-rejection HTTP status.
    if direct_resp is not None and direct_resp.status_code not in _REJECTION_STATUS_CODES:
        return direct_resp

    # No proxy configured — either re-raise the network error or return the response.
    if not proxy_url:
        if direct_error:
            raise direct_error
        return direct_resp  # type: ignore[return-value]

    # Log reason for proxy retry.
    if direct_error:
        logger.info(
            "%s: direct request failed (%s) — retrying via Webshare proxy", label, direct_error
        )
    else:
        logger.info(
            "%s: direct request returned HTTP %d — retrying via Webshare proxy",
            label,
            direct_resp.status_code,  # type: ignore[union-attr]
        )

    # --- Attempt 2: via Webshare rotating residential proxy ---
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
        ) as client:
            proxy_resp = await client.get(url, params=params, headers=headers)
        logger.debug("%s: proxy retry returned HTTP %d", label, proxy_resp.status_code)
        return proxy_resp
    except httpx.RequestError as proxy_exc:
        logger.warning("%s: proxy retry also failed with network error: %s", label, proxy_exc)
        # Proxy network error: if direct also had a network error, raise proxy error.
        # If direct returned a rejection status, return that so caller sees the HTTP status.
        if direct_error:
            raise proxy_exc
        return direct_resp  # type: ignore[return-value]


async def _fetch_descriptions_parallel(
    slugs: List[Optional[str]],
    proxy_url: Optional[str] = None,
) -> List[Optional[str]]:
    """
    Fetch event descriptions in parallel from lu.ma/<slug> pages.

    Extracts from __NEXT_DATA__ -> description_mirror (ProseMirror AST).
    Falls back to og:description meta tag (truncated ~155 chars).
    Returns None for any slug that fails. Proxy fallback applied per-request.

    Args:
        slugs:     List of Luma URL slugs (None entries return None immediately).
        proxy_url: Optional proxy URL passed to each individual fetch for fallback.
    """
    tasks = [_fetch_single_description(slug, proxy_url=proxy_url) for slug in slugs]
    return list(await asyncio.gather(*tasks))


async def _fetch_single_description(
    slug: Optional[str],
    proxy_url: Optional[str] = None,
) -> Optional[str]:
    """
    Fetch description for a single Luma event page. Returns None on error.

    Tries direct request first; retries via proxy on rejection if proxy_url set.
    """
    if not slug:
        return None

    url = f"https://lu.ma/{slug}"
    try:
        resp = await _get_with_proxy_fallback(
            url=url,
            headers=_HEADERS_HTML,
            proxy_url=proxy_url,
            label=f"lu.ma/{slug}",
        )
    except (httpx.RequestError, RuntimeError) as exc:
        logger.debug("Luma description fetch failed for %r: %s", slug, exc)
        return None

    if resp.status_code != 200:
        logger.debug("Luma description HTTP %d for slug %r", resp.status_code, slug)
        return None

    return _extract_description_from_html(resp.text, slug)


def _extract_description_from_html(html: str, slug: str = "") -> Optional[str]:
    """
    Extract event description from a lu.ma event page.

    Primary: __NEXT_DATA__ JSON -> description_mirror (ProseMirror AST, full text).
    Fallback: og:description meta tag (truncated at ~155 chars by Luma).
    """
    # Primary: full description from __NEXT_DATA__ JSON
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if m:
        try:
            nd = json.loads(m.group(1))
            dm = (
                nd.get("props", {})
                .get("pageProps", {})
                .get("initialData", {})
                .get("data", {})
                .get("description_mirror")
            )
            if dm and isinstance(dm, dict):
                text = _prosemirror_to_text(dm).strip()
                if text:
                    return text[:_MAX_DESCRIPTION_CHARS]
        except (json.JSONDecodeError, AttributeError) as exc:
            logger.debug("Failed to parse __NEXT_DATA__ for Luma slug %r: %s", slug, exc)

    # Fallback: og:description meta tag
    m2 = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']',
        html,
    )
    if m2:
        text = m2.group(1).strip()
        if text:
            return text

    return None


def _prosemirror_to_text(node: Any, _depth: int = 0) -> str:
    """
    Recursively convert a ProseMirror JSON document node to plain text.

    Block-level nodes get a trailing newline; inline text nodes are concatenated
    directly. Recursion depth is capped at 50 to prevent infinite loops on
    malformed input.
    """
    if not isinstance(node, dict) or _depth > 50:
        return ""

    node_type = node.get("type", "")

    if node_type == "text":
        return node.get("text", "")

    children = node.get("content") or []
    text = "".join(_prosemirror_to_text(c, _depth + 1) for c in children)

    _BLOCK_TYPES = {
        "paragraph", "heading", "blockquote", "listItem",
        "bulletList", "orderedList", "codeBlock", "horizontalRule",
    }
    if node_type in _BLOCK_TYPES:
        text = text.rstrip() + "\n"

    return text
