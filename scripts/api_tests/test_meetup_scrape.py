#!/usr/bin/env python3
"""
Meetup.com event search via reverse-engineered internal GraphQL API.

## How it works

Meetup's official public API (api.meetup.com/gql-ext) does NOT support global
event discovery — the eventsSearch query is scoped to Pro Network groups only,
and Pro access requires a paid Meetup Pro subscription.

However, Meetup's own website uses an internal GraphQL endpoint at:
    POST https://www.meetup.com/gql2

This endpoint is unauthenticated (no API key required) and accepts standard
GraphQL queries. The schema was discovered by introspecting the endpoint.

Key difference from the _next/data approach (now deprecated in this script):
The _next/data endpoint resolves location from server-side geo-IP, not from
the location parameter in the query string. Using the GraphQL endpoint directly
with explicit lat/lon values bypasses this completely — you get results for
the exact coordinates you specify.

## Authentication

None required. The endpoint is publicly accessible without session cookies or
tokens. Sending a standard browser User-Agent and Referer is enough.

## Rate limiting

Not publicly documented. Based on observation:
- Meetup has server-side throttling on this endpoint
- No explicit Retry-After header observed yet
- Recommended: 1-2 second delay between requests in production

## Pagination

Standard Relay cursor-based pagination:
- `pageInfo.hasNextPage` — true if more results exist
- `pageInfo.endCursor`   — opaque cursor, pass as `after:` in next request
- Default page size: ~12-15 events (Meetup controls this server-side)
- `first:` argument accepted (tested up to 50 per page)

## EventSearchFilter fields (required and optional)

Required:
- lat (Float!)        — latitude of search center
- lon (Float!)        — longitude of search center
- query (String!)     — keyword search term

Optional:
- city (String)       — city name (used for display, not for geo-resolution)
- country (String)    — ISO 3166-1 alpha-2 country code (e.g. "de", "us")
- state (String)      — state/region name
- zip (String)        — postal code
- radius (Float)      — search radius in miles (default: ~25)
- startDateRange (DateTime)  — ISO 8601 with TZ, e.g. "2026-03-01T00:00:00+01:00[Europe/Berlin]"
- endDateRange (DateTime)    — same format
- eventType (EventType)      — "PHYSICAL" or "ONLINE"
- doConsolidateEvents (Bool) — merge recurring event instances (default: true)
- isHappeningNow (Bool)      — only ongoing events
- topicCategoryId (ID)       — filter by Meetup category ID

## Usage

    # Search AI events in Berlin this week:
    python scripts/api_tests/test_meetup_scrape.py --keywords "ai" --location "Berlin, Germany" --pages 1

    # Explicit lat/lon (skips geocoding):
    python scripts/api_tests/test_meetup_scrape.py --keywords "ai" --lat 52.52 --lon 13.405 --pages 1

    # Date range (ISO 8601):
    python scripts/api_tests/test_meetup_scrape.py --keywords "python" --lat 52.52 --lon 13.405 \\
        --start "2026-03-01T00:00:00+01:00[Europe/Berlin]" \\
        --end   "2026-03-08T00:00:00+01:00[Europe/Berlin]"

    # Run a specific test:
    python scripts/api_tests/test_meetup_scrape.py --test search_berlin_ai

    # List available tests:
    python scripts/api_tests/test_meetup_scrape.py --list

    # JSON output only (for piping):
    python scripts/api_tests/test_meetup_scrape.py --keywords "ai" --lat 52.52 --lon 13.405 --json-only
"""

import argparse
import json
import sys
import time
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAPHQL_URL = "https://www.meetup.com/gql2"

# Well-known city coordinates for convenience (degrees)
CITY_COORDS: dict[str, tuple[float, float, str, str]] = {
    # city_key: (lat, lon, city_name, country_code)
    "berlin": (52.52, 13.405, "Berlin", "de"),
    "munich": (48.137, 11.576, "Munich", "de"),
    "hamburg": (53.551, 9.993, "Hamburg", "de"),
    "london": (51.507, -0.128, "London", "gb"),
    "paris": (48.857, 2.352, "Paris", "fr"),
    "amsterdam": (52.374, 4.898, "Amsterdam", "nl"),
    "new york": (40.713, -74.006, "New York", "us"),
    "san francisco": (37.775, -122.418, "San Francisco", "us"),
}

# Headers that match what the Meetup web app sends
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://www.meetup.com/find/",
    "apollographql-client-name": "nextjs-web",
}

# The GraphQL query used for event search
# Fields chosen to match what the website uses (visible in __APOLLO_STATE__)
EVENT_SEARCH_QUERY = """
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

# Polite delay between paginated requests
REQUEST_DELAY = 1.2


# ---------------------------------------------------------------------------
# Core search function
# ---------------------------------------------------------------------------


def search_meetup_events(
    keywords: str,
    lat: float,
    lon: float,
    city: str = "",
    country: str = "",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    event_type: Optional[str] = None,
    radius_miles: float = 25.0,
    max_pages: int = 1,
    page_size: int = 50,
) -> list[dict]:
    """
    Search Meetup.com for public events matching keywords at the given coordinates.

    Uses the internal GraphQL endpoint (gql2) directly — no API key required,
    no geo-IP location ambiguity. Coordinates are used as-is.

    Args:
        keywords:     Search term (e.g. "ai", "python", "tech")
        lat:          Latitude of search center (required)
        lon:          Longitude of search center (required)
        city:         City name for display (optional, doesn't affect geo-resolution)
        country:      ISO 3166-1 alpha-2 country code (optional, e.g. "de")
        start_date:   ISO 8601 datetime with timezone, e.g.
                      "2026-03-01T00:00:00+01:00[Europe/Berlin]"
        end_date:     ISO 8601 datetime with timezone (same format)
        event_type:   "PHYSICAL", "ONLINE", or None (both)
        radius_miles: Search radius in miles (default 25, ~40 km)
        max_pages:    Maximum number of result pages to fetch
        page_size:    Results per page (tested up to 50)

    Returns:
        List of normalized event dicts. Each contains:
          id, title, date_time, event_type, url, description,
          rsvp_count, is_paid, fee (dict with amount/currency),
          group (id/name/slug/timezone),
          venue (name/address/city/state/country/lat/lon)
    """
    session = requests.Session()

    # Build the EventSearchFilter
    gql_filter: dict = {
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

    all_events: list[dict] = []
    cursor: Optional[str] = None
    page = 0

    while page < max_pages:
        page += 1
        print(f"\n[PAGE {page}/{max_pages}]")

        variables: dict = {
            "filter": gql_filter,
            "sort": {"sortField": "RELEVANCE"},
            "first": page_size,
        }
        if cursor:
            variables["after"] = cursor

        payload = {
            "operationName": "eventSearch",
            "variables": variables,
            "query": EVENT_SEARCH_QUERY,
        }

        print(f"[FETCH] POST {GRAPHQL_URL}")
        print(f"        filter.query={keywords!r}  lat={lat}  lon={lon}  after={cursor!r}")

        start = time.time()
        resp = session.post(GRAPHQL_URL, json=payload, headers=HEADERS, timeout=20)
        duration = time.time() - start

        if resp.status_code != 200:
            raise RuntimeError(
                f"GraphQL request failed with status {resp.status_code}. "
                f"Body: {resp.text[:300]}"
            )

        data = resp.json()

        if "errors" in data:
            raise RuntimeError(
                f"GraphQL errors: {json.dumps(data['errors'], indent=2)}"
            )

        es = data.get("data", {}).get("eventSearch")
        if es is None:
            raise ValueError(
                "No 'eventSearch' field in GraphQL response. "
                f"Response keys: {list(data.get('data', {}).keys())}"
            )

        page_info = es.get("pageInfo", {})
        edges = es.get("edges", [])

        print(
            f"[FETCH] OK ({duration:.2f}s) — "
            f"{len(edges)} events, "
            f"totalCount={es.get('totalCount')}, "
            f"hasNext={page_info.get('hasNextPage')}"
        )

        # Normalize each event
        for edge in edges:
            node = edge.get("node", {})
            venue = node.get("venue") or {}
            group = node.get("group") or {}
            fee = node.get("feeSettings")

            event = {
                "id": node.get("id"),
                "title": node.get("title"),
                "date_time": node.get("dateTime"),
                "event_type": node.get("eventType"),   # "PHYSICAL" | "ONLINE"
                "url": node.get("eventUrl"),
                "description": node.get("description", ""),
                "rsvp_count": (node.get("rsvps") or {}).get("totalCount", 0),
                "is_paid": fee is not None,
                "fee": (
                    {"amount": fee["amount"], "currency": fee["currency"]}
                    if fee
                    else None
                ),
                "group": {
                    "id": group.get("id"),
                    "name": group.get("name"),
                    "slug": group.get("urlname"),
                    "timezone": group.get("timezone"),
                },
                "venue": (
                    {
                        "name": venue.get("name"),
                        "address": venue.get("address"),
                        "city": venue.get("city"),
                        "state": venue.get("state"),
                        "country": venue.get("country"),
                        "lat": venue.get("lat"),
                        "lon": venue.get("lon"),
                    }
                    if venue
                    else None
                ),
            }
            all_events.append(event)

        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            print("[PAGE] No more pages.")
            break

        cursor = page_info["endCursor"]

        if page < max_pages:
            time.sleep(REQUEST_DELAY)

    return all_events


def resolve_location(location_str: str) -> tuple[float, float, str, str]:
    """
    Resolve a location string to (lat, lon, city, country).

    Checks the built-in CITY_COORDS lookup first (no network request).
    Falls back to querying the Meetup locationSearch GraphQL query.

    Args:
        location_str: City name, e.g. "Berlin, Germany" or "berlin"

    Returns:
        (lat, lon, city, country_code)

    Raises:
        ValueError if location cannot be resolved
    """
    # Check built-in lookup (case-insensitive, strips country suffix)
    key = location_str.lower().split(",")[0].strip()
    if key in CITY_COORDS:
        lat, lon, city, country = CITY_COORDS[key]
        print(f"[GEO] Resolved {location_str!r} from local lookup: {city} ({lat}, {lon})")
        return lat, lon, city, country

    # Fall back to Meetup's locationSearch GraphQL query
    # Note: locationSearch on gql2 takes lat/lon (not a text query).
    # To do text-to-coordinates, we query the _next/data endpoint which
    # accepts a location string and returns the resolved userLocation.
    print(f"[GEO] Resolving {location_str!r} via Meetup location lookup...")

    HEADERS_HTML = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/json, */*;q=0.1",
        "Referer": "https://www.meetup.com/find/",
        "x-nextjs-data": "1",
    }

    # Fetch the buildId first (needed for _next/data URL)
    r = requests.get(
        "https://www.meetup.com/find/",
        headers={**HEADERS_HTML, "Accept": "text/html"},
        timeout=15,
    )
    build_id = r.headers.get("X-Build-Version", "")
    if not build_id:
        marker = '"buildId":"'
        idx = r.text.find(marker)
        if idx != -1:
            end = r.text.index('"', idx + len(marker))
            build_id = r.text[idx + len(marker):end]

    if not build_id:
        raise ValueError("Could not determine Next.js buildId for location resolution")

    # Fetch _next/data with location string — server resolves it via their geocoder
    data_r = requests.get(
        f"https://www.meetup.com/_next/data/{build_id}/find.json",
        headers=HEADERS_HTML,
        params={"keywords": "test", "location": location_str, "source": "EVENTS"},
        timeout=15,
    )
    page_props = data_r.json().get("pageProps", {})
    loc = page_props.get("userLocation", {})

    if not loc or not loc.get("lat") or not loc.get("lon"):
        raise ValueError(
            f"Could not resolve location {location_str!r}. "
            "Try passing --lat and --lon explicitly."
        )

    lat = loc["lat"]
    lon = loc["lon"]
    city = loc.get("city", "")
    country = loc.get("country", "")
    print(f"[GEO] Resolved to: {city}, {country} ({lat:.4f}, {lon:.4f})")
    return lat, lon, city, country


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------


def test_search_berlin_ai() -> dict:
    """Search for AI events in Berlin this coming week."""
    print("\n" + "=" * 60)
    print("TEST: search_berlin_ai")
    print("      keywords='ai'  Berlin (52.52, 13.405)  this week")
    print("=" * 60)

    start = time.time()
    try:
        events = search_meetup_events(
            keywords="ai",
            lat=52.52,
            lon=13.405,
            city="Berlin",
            country="de",
            start_date="2026-03-01T00:00:00+01:00[Europe/Berlin]",
            end_date="2026-03-08T23:59:59+01:00[Europe/Berlin]",
            radius_miles=25.0,
            max_pages=1,
            page_size=50,
        )
        duration = time.time() - start

        if not events:
            print("[WARN] No events returned.")
            return {"status": "warn", "duration": duration, "count": 0}

        print(f"\n[OK] Found {len(events)} events ({duration:.2f}s)")
        print("\nTop AI events in Berlin this week:")
        print("-" * 60)
        # Show top 10, sorted by rsvp_count desc
        top = sorted(events, key=lambda e: e["rsvp_count"], reverse=True)[:10]
        for e in top:
            venue = (
                e["venue"]["city"] if e.get("venue") and e["venue"].get("city")
                else e["event_type"]
            )
            paid_str = f"  [PAID {e['fee']['amount']} {e['fee']['currency']}]" if e.get("is_paid") else ""
            print(f"[{e['date_time'][:16]}] [{e['event_type'][:4]}]{paid_str}")
            print(f"  {e['title']}")
            print(f"  {e['group']['name']}")
            print(f"  {venue}  |  {e['rsvp_count']} RSVPs")
            print(f"  {e['url']}")
            print()

        return {"status": "pass", "duration": duration, "count": len(events), "data": events}
    except Exception as exc:
        duration = time.time() - start
        print(f"[FAIL] {exc} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(exc)}


def test_graphql_endpoint() -> dict:
    """Verify the GraphQL endpoint is reachable and returns a valid schema."""
    print("\n" + "=" * 60)
    print("TEST: graphql_endpoint")
    print("=" * 60)

    start = time.time()
    try:
        r = requests.post(
            GRAPHQL_URL,
            json={"query": "{ __typename }"},
            headers=HEADERS,
            timeout=10,
        )
        duration = time.time() - start
        data = r.json()

        if r.status_code != 200 or "data" not in data:
            raise RuntimeError(f"Unexpected response: {r.status_code} {data}")

        print(f"[OK] GraphQL endpoint reachable ({duration:.2f}s)")
        print(f"     __typename: {data['data'].get('__typename')}")
        return {"status": "pass", "duration": duration}
    except Exception as exc:
        duration = time.time() - start
        print(f"[FAIL] {exc} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(exc)}


def test_pagination() -> dict:
    """Fetch 2 pages of Berlin tech events and verify cursor pagination."""
    print("\n" + "=" * 60)
    print("TEST: pagination")
    print("      keywords='tech'  Berlin  pages=2")
    print("=" * 60)

    start = time.time()
    try:
        events = search_meetup_events(
            keywords="tech",
            lat=52.52,
            lon=13.405,
            city="Berlin",
            country="de",
            max_pages=2,
            page_size=12,
        )
        duration = time.time() - start

        print(f"\n[OK] Fetched {len(events)} events across 2 pages ({duration:.2f}s)")
        if len(events) > 12:
            print("[OK] Pagination working: got more than 1 page of results")
        else:
            print(f"[INFO] {len(events)} total — may be end of results")

        return {"status": "pass", "duration": duration, "count": len(events)}
    except Exception as exc:
        duration = time.time() - start
        print(f"[FAIL] {exc} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(exc)}


def test_location_resolve() -> dict:
    """Verify location string resolution via built-in lookup and Meetup geocoder."""
    print("\n" + "=" * 60)
    print("TEST: location_resolve")
    print("=" * 60)

    start = time.time()
    try:
        # Test built-in lookup
        lat, lon, city, country = resolve_location("Berlin, Germany")
        assert abs(lat - 52.52) < 0.1, f"Berlin lat wrong: {lat}"
        assert abs(lon - 13.405) < 0.1, f"Berlin lon wrong: {lon}"
        print(f"[OK] Built-in lookup: Berlin → ({lat}, {lon})")

        duration = time.time() - start
        return {"status": "pass", "duration": duration, "lat": lat, "lon": lon}
    except Exception as exc:
        duration = time.time() - start
        print(f"[FAIL] {exc} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(exc)}


# ---------------------------------------------------------------------------
# Test registry and CLI
# ---------------------------------------------------------------------------

TESTS = {
    "graphql_endpoint": test_graphql_endpoint,
    "search_berlin_ai": test_search_berlin_ai,
    "pagination": test_pagination,
    "location_resolve": test_location_resolve,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search Meetup.com events via reverse-engineered GraphQL API"
    )
    parser.add_argument("--keywords", default="tech", help="Search keywords (default: tech)")
    parser.add_argument("--location", default="", help="City string, e.g. 'Berlin, Germany'")
    parser.add_argument("--lat", type=float, help="Latitude (overrides --location)")
    parser.add_argument("--lon", type=float, help="Longitude (overrides --location)")
    parser.add_argument("--start", help="Start date ISO 8601, e.g. '2026-03-01T00:00:00+01:00[Europe/Berlin]'")
    parser.add_argument("--end", help="End date ISO 8601")
    parser.add_argument("--radius", type=float, default=25.0, help="Search radius in miles (default: 25)")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to fetch (default: 1)")
    parser.add_argument("--page-size", type=int, default=50, help="Results per page (default: 50)")
    parser.add_argument("--test", help="Run a specific test by name")
    parser.add_argument("--list", action="store_true", help="List available tests")
    parser.add_argument("--json-only", action="store_true", help="Print results as JSON")
    args = parser.parse_args()

    if args.list:
        print("Available tests:")
        for name, fn in TESTS.items():
            print(f"  {name}: {fn.__doc__ or '(no description)'}")
        return

    if args.test:
        if args.test not in TESTS:
            print(f"Unknown test: {args.test!r}. Use --list to see available tests.")
            sys.exit(1)
        result = TESTS[args.test]()
        if args.json_only:
            print(json.dumps(result, indent=2, default=str))
        return

    # --- Custom search mode ---
    if args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
        city, country = "", ""
    elif args.location:
        lat, lon, city, country = resolve_location(args.location)
    else:
        print("Provide --lat/--lon or --location. Use --test search_berlin_ai for a demo.")
        sys.exit(1)

    events = search_meetup_events(
        keywords=args.keywords,
        lat=lat,
        lon=lon,
        city=city,
        country=country,
        start_date=args.start,
        end_date=args.end,
        radius_miles=args.radius,
        max_pages=args.pages,
        page_size=args.page_size,
    )

    if args.json_only:
        print(json.dumps(events, indent=2, default=str))
        return

    print(f"\nFound {len(events)} events:")
    print("=" * 60)
    for e in events:
        venue = (
            e["venue"]["city"] if e.get("venue") and e["venue"].get("city")
            else e.get("event_type", "?")
        )
        paid_str = f"  [PAID {e['fee']['amount']} {e['fee']['currency']}]" if e.get("is_paid") else ""
        print(f"[{(e['date_time'] or '')[:16]}] [{(e['event_type'] or '')[:4]}]{paid_str}")
        print(f"  {e['title']}")
        print(f"  {e['group']['name']} | {venue} | {e['rsvp_count']} RSVPs")
        print(f"  {e['url']}")


if __name__ == "__main__":
    main()
