#!/usr/bin/env python3
"""
Luma.com (lu.ma) event search via reverse-engineered internal API.

How it works:
  Luma's official public API requires a paid Luma Plus subscription and is
  organiser-scoped only (no global event discovery). However, luma.com's own
  web app uses an internal API at api2.luma.com — discovered by intercepting
  browser network requests. No auth is required.

Key endpoints (api2.luma.com):
  GET /discover/get-paginated-events
      ?discover_place_api_id=<place-id>
      &pagination_limit=25
      [&query=AI]
      [&pagination_cursor=...]
  GET /discover/bootstrap-page?featured_place_api_id=<any-valid-id>
      -> returns all 78 featured city place objects (slug/name/api_id)

Coverage: 78 featured cities (hardcoded in CITY_PLACE_IDS).
Auth: None required. Standard browser User-Agent + Origin/Referer.
Pagination: cursor-based (has_more + next_cursor fields).

Usage:
  python scripts/api_tests/test_luma_api.py --city berlin --query AI
  python scripts/api_tests/test_luma_api.py --list-cities
  python scripts/api_tests/test_luma_api.py --test search_berlin_ai
  python scripts/api_tests/test_luma_api.py --list

Architecture: Reverse-engineered from luma.com web app network traffic (March 2026).
See docs/apis/luma.md for full integration summary.
"""

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://api2.luma.com"
EVENTS_ENDPOINT = f"{API_BASE}/discover/get-paginated-events"
BOOTSTRAP_ENDPOINT = f"{API_BASE}/discover/bootstrap-page"
PLACE_ENDPOINT = f"{API_BASE}/discover/get-place-v2"

# Bootstrap place ID (Berlin) used to seed the full city list on first call.
_BOOTSTRAP_PLACE_ID = "discplace-gCfX0s3E9Hgo3rG"

# Maximum events per page (empirically confirmed; 25 is the web app default).
MAX_PAGE_SIZE = 40

# Polite inter-page delay.
PAGE_DELAY_SECONDS = 1.2

# Headers that mimic what luma.com sends. Origin+Referer are required for CORS.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://luma.com",
    "Referer": "https://luma.com/discover",
}

# ---------------------------------------------------------------------------
# City slug -> discover_place_api_id mapping
# Source: GET api2.luma.com/discover/bootstrap-page (scraped March 2026, 78 cities)
# These IDs are stable; they identify Luma's curated featured discovery cities.
# ---------------------------------------------------------------------------
CITY_PLACE_IDS: Dict[str, str] = {
    "helsinki": "discplace-gEii5B2Ju5KKRNH",
    "stockholm": "discplace-e7EG0Ef6S2aQnvN",
    "copenhagen": "discplace-CmmHAjPdBSsqmJf",
    "warsaw": "discplace-PTcuEQVHuySJe8N",
    "berlin": "discplace-gCfX0s3E9Hgo3rG",
    "hamburg": "discplace-xZzD6rDcDK12oi7",
    "prague": "discplace-6xx9LRci5NFgdJ5",
    "vienna": "discplace-3YgdIjqj7Pveid3",
    "budapest": "discplace-zS3rBqHSdNGTSZB",
    "amsterdam": "discplace-FC4SDMUVXiFtMOr",
    "munich": "discplace-P00kEGGGHNLEYGe",
    "brussels": "discplace-CMxOe3Mv06uUk7l",
    "zurich": "discplace-tSRc3NkTycobe0w",
    "london": "discplace-QCcNk3HXowOR97j",
    "paris": "discplace-NdLrh1xJfeotJZC",
    "lausanne": "discplace-SmrXTBH5rgPvd1h",
    "milan": "discplace-9AyCYUvGH7xiqhh",
    "geneva": "discplace-RnVxN1SH4HYTeqF",
    "dublin": "discplace-ffI8KmAB4gC5LMC",
    "istanbul": "discplace-0vKyo1D6kdT4ml6",
    "rome": "discplace-CLGg2G8Q96daz0w",
    "barcelona": "discplace-WcS4REeayDPXV4n",
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

# City display names (slug -> display name, for output formatting)
CITY_NAMES: Dict[str, str] = {
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
# Core functions
# ---------------------------------------------------------------------------

def resolve_city(city_input: str) -> Tuple[str, str, str]:
    """
    Resolve a city name or slug to (place_api_id, city_slug, city_display_name).

    Accepts: "Berlin", "berlin", "san francisco", "san-francisco", "sf", "nyc"
    Raises ValueError for unsupported cities (not in Luma's featured city list).
    """
    slug = city_input.lower().strip().replace(" ", "-").replace("_", "-")
    place_id = CITY_PLACE_IDS.get(slug)
    if not place_id:
        # Build list excluding aliases for a cleaner error message
        seen_ids = set()
        canonical_slugs = []
        for s, pid in CITY_PLACE_IDS.items():
            if pid not in seen_ids:
                seen_ids.add(pid)
                canonical_slugs.append(s)
        raise ValueError(
            f"City {city_input!r} is not a Luma featured city (slug={slug!r}).\n"
            f"Supported city slugs ({len(canonical_slugs)}): {', '.join(sorted(canonical_slugs))}"
        )
    display_name = CITY_NAMES.get(slug, slug.replace("-", " ").title())
    return place_id, slug, display_name


def search_events(
    city: str,
    query: Optional[str] = None,
    count: int = 10,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Search Luma.com for events in a specific city.

    Uses reverse-engineered api2.luma.com. No API key required.
    Results are sorted by start_at ascending (future events first).
    Pagination is handled automatically.

    Args:
        city:   City slug or name (e.g. "berlin", "San Francisco", "nyc").
                Must be one of the 78 Luma featured cities.
        query:  Optional keyword filter (e.g. "AI", "startup", "hackathon").
                When None, all upcoming events in the city are returned.
        count:  Max events to return (default 10, automatically paginated).

    Returns:
        (events_list, has_more) where has_more=True means more events exist.

    Raises:
        ValueError: City not supported.
        RuntimeError: HTTP or API error.
    """
    place_id, slug, city_name = resolve_city(city)
    count = max(1, count)

    all_events: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    has_more = False

    while len(all_events) < count:
        page_limit = min(MAX_PAGE_SIZE, count - len(all_events))
        params: Dict[str, Any] = {
            "discover_place_api_id": place_id,
            "pagination_limit": page_limit,
        }
        if query:
            params["query"] = query
        if cursor:
            params["pagination_cursor"] = cursor
            time.sleep(PAGE_DELAY_SECONDS)

        t0 = time.time()
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(EVENTS_ENDPOINT, params=params, headers=_HEADERS)
        except httpx.RequestError as exc:
            raise RuntimeError(f"HTTP request to Luma failed: {exc}") from exc

        duration = time.time() - t0
        if resp.status_code != 200:
            raise RuntimeError(
                f"Luma API HTTP {resp.status_code} after {duration:.2f}s. "
                f"Body: {resp.text[:300]}"
            )

        data = resp.json()
        entries = data.get("entries", [])
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")

        all_events.extend(_normalise_event(e, city_name) for e in entries)
        if not has_more or not cursor:
            break

    return all_events[:count], has_more


async def search_events_async(
    city: str,
    query: Optional[str] = None,
    count: int = 10,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Async version of search_events for use in FastAPI async context.
    Uses httpx.AsyncClient. Semantics identical to search_events().
    """
    import asyncio

    place_id, slug, city_name = resolve_city(city)
    count = max(1, count)

    all_events: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    has_more = False

    while len(all_events) < count:
        page_limit = min(MAX_PAGE_SIZE, count - len(all_events))
        params: Dict[str, Any] = {
            "discover_place_api_id": place_id,
            "pagination_limit": page_limit,
        }
        if query:
            params["query"] = query
        if cursor:
            params["pagination_cursor"] = cursor
            await asyncio.sleep(PAGE_DELAY_SECONDS)

        t0 = time.time()
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(EVENTS_ENDPOINT, params=params, headers=_HEADERS)
        except httpx.RequestError as exc:
            raise RuntimeError(f"HTTP request to Luma failed: {exc}") from exc

        duration = time.time() - t0
        if resp.status_code != 200:
            raise RuntimeError(
                f"Luma API HTTP {resp.status_code} after {duration:.2f}s. "
                f"Body: {resp.text[:300]}"
            )

        data = resp.json()
        entries = data.get("entries", [])
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")

        all_events.extend(_normalise_event(e, city_name) for e in entries)
        if not has_more or not cursor:
            break

    return all_events[:count], has_more


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _normalise_event(entry: Dict[str, Any], city_fallback: str = "") -> Dict[str, Any]:
    """
    Normalise a raw Luma API entry into the canonical event provider schema.

    Luma entries have a nested `event` object with geo, coordinate, and
    calendar (organiser) subfields. The event URL is a short slug that needs
    prefixing with https://lu.ma/.

    Note: description is NOT returned by the list endpoint — fetch the
    individual event page (lu.ma/<slug>) for full description if needed.
    """
    ev = entry.get("event") or {}
    geo = ev.get("geo_address_info") or {}
    coord = ev.get("coordinate") or {}
    cal = entry.get("calendar") or {}
    hosts = entry.get("hosts") or []

    url_slug = ev.get("url", "")
    full_url = f"https://lu.ma/{url_slug}" if url_slug else None

    # Build venue only for offline/in-person events with location data
    venue: Optional[Dict[str, Any]] = None
    if ev.get("location_type") == "offline" and (geo.get("city") or coord.get("latitude")):
        venue = {
            "name": geo.get("address"),
            "full_address": geo.get("full_address"),
            "short_address": geo.get("short_address"),
            "city": geo.get("city") or city_fallback,
            "state": geo.get("region"),
            "country": geo.get("country"),
            "country_code": geo.get("country_code"),
            "lat": coord.get("latitude"),
            "lon": coord.get("longitude"),
        }

    return {
        "id": ev.get("api_id") or entry.get("api_id"),
        "provider": "luma",
        "title": ev.get("name"),
        "description": None,  # Not available on list endpoint; requires individual fetch
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
        "rsvp_count": entry.get("guest_count"),  # May be None if hidden by organiser
        "is_paid": bool((entry.get("ticket_info") or {}).get("is_paid")),
        "cover_url": ev.get("cover_url"),
        "city": geo.get("city") or city_fallback,
        "country": geo.get("country"),
    }


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

def test_search_berlin_ai() -> Dict[str, Any]:
    """Test: search AI events in Berlin."""
    print("\n" + "=" * 60)
    print("TEST: search_berlin_ai")
    print("=" * 60)
    print("Searching 'AI' events in Berlin...")
    start = time.time()
    try:
        events, has_more = search_events(city="berlin", query="AI", count=10)
        duration = time.time() - start
        print(f"\n[OK] {len(events)} events ({duration:.2f}s) | has_more={has_more}")
        for ev in events:
            venue = ev.get("venue") or {}
            print(f"  - {ev['title']}")
            print(f"      start:   {ev['date_start']}")
            print(f"      city:    {ev.get('city')}")
            print(f"      address: {venue.get('full_address', 'N/A')}")
            print(f"      url:     {ev['url']}")
            print(f"      guests:  {ev.get('rsvp_count')}")
        return {"status": "pass", "duration": duration, "count": len(events)}
    except Exception as e:
        duration = time.time() - start
        print(f"[FAIL] {e} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(e)}


def test_search_london_startup() -> Dict[str, Any]:
    """Test: search startup events in London."""
    print("\n" + "=" * 60)
    print("TEST: search_london_startup")
    print("=" * 60)
    print("Searching 'startup' events in London...")
    start = time.time()
    try:
        events, has_more = search_events(city="london", query="startup", count=5)
        duration = time.time() - start
        print(f"\n[OK] {len(events)} events ({duration:.2f}s)")
        for ev in events:
            print(f"  - {ev['title']} | {ev['date_start']} | paid={ev.get('is_paid')}")
        return {"status": "pass", "duration": duration, "count": len(events)}
    except Exception as e:
        duration = time.time() - start
        print(f"[FAIL] {e} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(e)}


def test_search_sf_all_events() -> Dict[str, Any]:
    """Test: browse all upcoming events in San Francisco (no keyword)."""
    print("\n" + "=" * 60)
    print("TEST: search_sf_all_events")
    print("=" * 60)
    print("Browsing upcoming SF events (no keyword filter)...")
    start = time.time()
    try:
        events, has_more = search_events(city="sf", query=None, count=8)
        duration = time.time() - start
        print(f"\n[OK] {len(events)} events ({duration:.2f}s) | has_more={has_more}")
        for ev in events:
            print(f"  - {ev['title'][:60]} | {ev.get('city')} | type={ev.get('event_type')}")
        return {"status": "pass", "duration": duration, "count": len(events)}
    except Exception as e:
        duration = time.time() - start
        print(f"[FAIL] {e} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(e)}


def test_city_aliases() -> Dict[str, Any]:
    """Test: city name aliases resolve correctly (nyc, sf, la, bangalore)."""
    print("\n" + "=" * 60)
    print("TEST: city_aliases")
    print("=" * 60)
    aliases = {
        "nyc": "discplace-Izx1rQVSh8njYpP",
        "New York": "discplace-Izx1rQVSh8njYpP",
        "sf": "discplace-BDj7GNbGlsF7Cka",
        "San Francisco": "discplace-BDj7GNbGlsF7Cka",
        "la": "discplace-OgfEAh5KgfMzise",
        "Los Angeles": "discplace-OgfEAh5KgfMzise",
        "bangalore": "discplace-G0tGUVYwl7T17Sb",
        "Bengaluru": "discplace-G0tGUVYwl7T17Sb",
    }
    start = time.time()
    failures = []
    for alias, expected_id in aliases.items():
        try:
            place_id, slug, name = resolve_city(alias)
            if place_id != expected_id:
                failures.append(f"{alias!r}: got {place_id!r}, expected {expected_id!r}")
            else:
                print(f"  [OK] {alias!r} -> {name} ({place_id})")
        except ValueError as e:
            failures.append(f"{alias!r}: {e}")
    duration = time.time() - start
    if failures:
        for f in failures:
            print(f"  [FAIL] {f}")
        return {"status": "fail", "duration": duration, "failures": failures}
    print(f"\n[OK] All {len(aliases)} aliases resolved ({duration:.2f}s)")
    return {"status": "pass", "duration": duration}


def test_invalid_city() -> Dict[str, Any]:
    """Test: unsupported city raises a clear ValueError."""
    print("\n" + "=" * 60)
    print("TEST: invalid_city")
    print("=" * 60)
    start = time.time()
    try:
        resolve_city("InvalidCityXYZ")
        duration = time.time() - start
        print("[FAIL] Expected ValueError was not raised")
        return {"status": "fail", "duration": duration, "error": "No exception raised"}
    except ValueError as e:
        duration = time.time() - start
        print(f"[OK] Got expected ValueError: {str(e)[:100]}... ({duration:.2f}s)")
        return {"status": "pass", "duration": duration}


def test_pagination() -> Dict[str, Any]:
    """Test: request 50 events to trigger multi-page pagination."""
    print("\n" + "=" * 60)
    print("TEST: pagination")
    print("=" * 60)
    print("Fetching 50 NYC events to verify pagination cursor handling...")
    start = time.time()
    try:
        events, has_more = search_events(city="nyc", query=None, count=50)
        duration = time.time() - start
        print(f"\n[OK] {len(events)} events ({duration:.2f}s) | has_more={has_more}")
        print(f"     Pagination {'triggered' if len(events) > MAX_PAGE_SIZE else 'not needed (single page)'}")
        ids = [e["id"] for e in events]
        unique_count = len(set(ids))
        print(f"     Unique event IDs: {unique_count}/{len(events)}")
        if unique_count != len(events):
            print("     [WARN] Duplicate events across pages detected!")
        return {"status": "pass", "duration": duration, "count": len(events), "has_more": has_more}
    except Exception as e:
        duration = time.time() - start
        print(f"[FAIL] {e} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(e)}


def test_list_cities() -> Dict[str, Any]:
    """Test: list all 78 supported cities from the hardcoded mapping."""
    print("\n" + "=" * 60)
    print("TEST: list_cities")
    print("=" * 60)
    start = time.time()
    seen = set()
    unique = []
    for slug, pid in CITY_PLACE_IDS.items():
        if pid not in seen:
            seen.add(pid)
            unique.append((slug, CITY_NAMES.get(slug, slug)))
    unique.sort(key=lambda x: x[1])
    print(f"\nLuma featured cities ({len(unique)} unique):")
    for slug, name in unique:
        print(f"  {slug:<22} {name}")
    duration = time.time() - start
    print(f"\n[OK] Listed {len(unique)} cities ({duration:.2f}s)")
    return {"status": "pass", "duration": duration, "count": len(unique)}


# ---------------------------------------------------------------------------
# Test registry and CLI
# ---------------------------------------------------------------------------

TESTS = {
    "search_berlin_ai": test_search_berlin_ai,
    "search_london_startup": test_search_london_startup,
    "search_sf_all_events": test_search_sf_all_events,
    "city_aliases": test_city_aliases,
    "invalid_city": test_invalid_city,
    "pagination": test_pagination,
    "list_cities": test_list_cities,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Luma.com reverse-engineered event search API tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/api_tests/test_luma_api.py                         # run all tests\n"
            "  python scripts/api_tests/test_luma_api.py --test search_berlin_ai # single test\n"
            "  python scripts/api_tests/test_luma_api.py --list                  # list tests\n"
            "  python scripts/api_tests/test_luma_api.py --list-cities           # show all cities\n"
            "  python scripts/api_tests/test_luma_api.py --city berlin --query AI --limit 10\n"
        ),
    )
    parser.add_argument("--test", help="Run a specific test by name")
    parser.add_argument("--list", action="store_true", help="List available tests")
    parser.add_argument("--list-cities", action="store_true", help="List all supported cities")
    parser.add_argument("--city", help="City slug or name (e.g. 'berlin', 'nyc', 'san-francisco')")
    parser.add_argument("--query", help="Keyword search (e.g. 'AI', 'startup')")
    parser.add_argument("--limit", type=int, default=10, help="Number of results (default: 10)")
    parser.add_argument("--json", action="store_true", help="Output events as JSON")
    args = parser.parse_args()

    if args.list:
        print("Available tests:")
        for name, fn in TESTS.items():
            print(f"  {name:<30} {fn.__doc__ or ''}")
        return

    if args.list_cities:
        test_list_cities()
        return

    if args.city:
        print(f"\nLuma search: city={args.city!r} query={args.query!r} limit={args.limit}")
        t0 = time.time()
        try:
            events, has_more = search_events(city=args.city, query=args.query, count=args.limit)
            duration = time.time() - t0
            print(f"Got {len(events)} events ({duration:.2f}s) | has_more={has_more}\n")
            if args.json:
                print(json.dumps(events, indent=2, ensure_ascii=False))
            else:
                for ev in events:
                    print(f"  {ev['title']}")
                    print(f"    start:   {ev['date_start']}")
                    print(f"    city:    {ev.get('city', 'N/A')}")
                    venue = ev.get("venue") or {}
                    print(f"    address: {venue.get('full_address') or 'N/A'}")
                    print(f"    url:     {ev['url']}")
                    print(f"    guests:  {ev.get('rsvp_count', 'N/A')}")
                    print(f"    paid:    {ev.get('is_paid', False)}")
                    print()
        except (ValueError, RuntimeError) as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        return

    if args.test:
        if args.test not in TESTS:
            print(f"[ERROR] Unknown test: {args.test!r}")
            print(f"Available: {', '.join(TESTS.keys())}")
            sys.exit(1)
        tests_to_run = {args.test: TESTS[args.test]}
    else:
        tests_to_run = TESTS

    results = {}
    for name, fn in tests_to_run.items():
        results[name] = fn()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in results.values() if r["status"] == "pass")
    failed = sum(1 for r in results.values() if r["status"] == "fail")
    print(f"Passed: {passed}/{len(results)}  |  Failed: {failed}/{len(results)}")
    for name, result in results.items():
        status = "PASS" if result["status"] == "pass" else "FAIL"
        print(f"  [{status}] {name} ({result['duration']:.2f}s)")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
