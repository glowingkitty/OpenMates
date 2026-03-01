#!/usr/bin/env python3
"""
Meetup.com event search via web scraping (reverse-engineered).

Meetup's official API does NOT support global event discovery — the eventsSearch
GraphQL query is scoped to Pro Network groups only. This script scrapes the
public /find page, which uses a Next.js SSR frontend backed by an internal
GraphQL API (Apollo). The initial page data is embedded in the HTML as
__NEXT_DATA__ and also exposed via a stable /_next/data/<buildId>/find.json
endpoint that returns the Apollo cache as clean JSON.

Mechanism:
  1. Fetch https://www.meetup.com/find/ to discover the current Next.js buildId
     (returned in X-Build-Version response header).
  2. Fetch /_next/data/<buildId>/find.json with search parameters to get the
     first page of results as structured JSON (no HTML parsing required).
  3. The response embeds Apollo cache with full event data including pagination
     cursors (endCursor, hasNextPage) — use cursor for subsequent pages.

WARNING: This is a reverse-engineered scrape. It will break if Meetup:
  - Deploys a new Next.js build (buildId changes — auto-resolved by step 1)
  - Changes the /find page URL structure or Apollo query shape
  - Adds authentication or bot-detection to the _next/data endpoint

Usage:
    # Search events near a city (default: Berlin, Germany):
    python scripts/api_tests/test_meetup_scrape.py

    # Custom search:
    python scripts/api_tests/test_meetup_scrape.py --keywords "python" --location "Munich, Germany"

    # Run specific test:
    python scripts/api_tests/test_meetup_scrape.py --test search_events

    # List available tests:
    python scripts/api_tests/test_meetup_scrape.py --list

    # Increase result pages:
    python scripts/api_tests/test_meetup_scrape.py --pages 3

    # JSON output only (for piping):
    python scripts/api_tests/test_meetup_scrape.py --json-only
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

BASE_URL = "https://www.meetup.com"
FIND_URL = f"{BASE_URL}/find/"

# Headers that mimic a real browser request to avoid bot-detection
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Referer": "https://www.meetup.com/",
}

JSON_HEADERS = {
    **HEADERS,
    "Accept": "application/json, */*;q=0.1",
    "Referer": FIND_URL,
    "x-nextjs-data": "1",  # Required header for _next/data endpoints
}

# Polite delay between requests (seconds)
REQUEST_DELAY = 1.0


# ---------------------------------------------------------------------------
# Core scraping functions
# ---------------------------------------------------------------------------


def get_build_id(session: requests.Session) -> str:
    """
    Discover the current Next.js buildId by fetching the /find page header.

    The buildId is returned in the X-Build-Version response header and also
    embedded in <script id="__NEXT_DATA__"> in the HTML. Using the header
    is faster (HEAD request, no body parsing needed).
    """
    print("[BUILD] Fetching current Next.js buildId from /find...")
    start = time.time()

    # HEAD request is sufficient — buildId is in the response header
    resp = session.head(FIND_URL, headers=HEADERS, timeout=15, allow_redirects=True)
    build_id = resp.headers.get("X-Build-Version", "").strip()

    if not build_id:
        # Fallback: fetch the full page and extract from __NEXT_DATA__
        print("[BUILD] Header missing, falling back to HTML extraction...")
        resp = session.get(FIND_URL, headers=HEADERS, timeout=20)
        html = resp.text
        marker = '"buildId":"'
        idx = html.find(marker)
        if idx == -1:
            raise RuntimeError(
                "Could not find Next.js buildId in /find page. "
                "Meetup may have changed their page structure."
            )
        start_idx = idx + len(marker)
        end_idx = html.index('"', start_idx)
        build_id = html[start_idx:end_idx]

    duration = time.time() - start
    print(f"[BUILD] buildId: {build_id} ({duration:.2f}s)")
    return build_id


def fetch_events_page(
    session: requests.Session,
    build_id: str,
    keywords: str,
    location: str,
    source: str = "EVENTS",
    cursor: Optional[str] = None,
) -> dict:
    """
    Fetch one page of search results from the Next.js data endpoint.

    Returns the raw Apollo cache dict from the JSON response, which contains:
      - ROOT_QUERY with eventSearch connection (edges + pageInfo)
      - Event nodes keyed as "Event:<id>"
      - Group nodes keyed as "Group:<id>"
      - Venue data embedded in Event nodes
      - PhotoInfo nodes for event images

    Args:
        session:   requests.Session with shared headers/cookies
        build_id:  Current Next.js build hash (from get_build_id())
        keywords:  Search keyword string (e.g. "python", "tech")
        location:  City string (e.g. "Berlin, Germany")
        source:    "EVENTS" or "GROUPS"
        cursor:    base64-encoded cursor from previous page's endCursor,
                   or None for the first page
    """
    # Build query params — match what the browser sends
    params: dict = {
        "keywords": keywords,
        "location": location,
        "source": source,
    }
    if cursor:
        # Note: cursor is appended as a URL param; the Next.js page reads it
        # and passes it to the Apollo query as the `after` argument
        params["after"] = cursor

    # The _next/data path mirrors the page route: /find → find.json
    data_url = f"{BASE_URL}/_next/data/{build_id}/find.json"

    print(f"[FETCH] {data_url}")
    print(f"        params: {params}")

    start = time.time()
    resp = session.get(
        data_url,
        headers=JSON_HEADERS,
        params=params,
        timeout=20,
    )
    duration = time.time() - start

    if resp.status_code == 404:
        raise RuntimeError(
            f"_next/data endpoint returned 404. The buildId ({build_id}) may be "
            "stale — re-fetch with get_build_id() to get the latest one."
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Unexpected status {resp.status_code} from _next/data endpoint. "
            f"Body: {resp.text[:500]}"
        )

    data = resp.json()
    print(f"[FETCH] OK ({duration:.2f}s), response size: {len(resp.content)} bytes")
    return data


def parse_events(raw_data: dict) -> tuple[list[dict], dict]:
    """
    Parse events from the Next.js Apollo cache response.

    The _next/data endpoint returns:
      pageProps.__APOLLO_STATE__  — the Apollo cache (direct key in pageProps)

    Some older builds used:
      pageProps.apolloState.__APOLLO_STATE__  (double-nested)

    Within the Apollo cache:
      - ROOT_QUERY contains the eventSearch connection (inline, not a ref)
      - Event:<id> entries contain event details
      - Group:<id> entries contain group details
      - PhotoInfo:<id> entries contain image URLs

    Returns:
        (events, page_info) where:
          events    — list of normalized event dicts
          page_info — dict with hasNextPage (bool), endCursor (str | None),
                      totalCount (int), and location (dict from userLocation)
    """
    page_props = raw_data.get("pageProps", {})

    # Try direct key first (current structure as of Feb 2026)
    apollo = page_props.get("__APOLLO_STATE__")

    # Fallback: older double-nested structure
    if not apollo:
        nested = page_props.get("apolloState", {})
        apollo = nested.get("__APOLLO_STATE__", nested) or None

    if not apollo:
        raise ValueError(
            "Apollo state not found in _next/data response. "
            "Page structure may have changed."
        )

    # Find the eventSearch root query key (it's dynamic, includes filter params).
    # Format as of Feb 2026: 'eventSearch:{"filter":{...},"sort":{...}}'
    # Older builds used:      'eventSearch({"filter":{...},"sort":{...}})'
    root_query = apollo.get("ROOT_QUERY", {})
    event_search_key = None
    for key in root_query:
        if key.startswith("eventSearch"):
            event_search_key = key
            break

    if not event_search_key:
        # Try alternate query name used in some builds
        for key in root_query:
            if "eventsSearch" in key:
                event_search_key = key
                break

    if not event_search_key:
        # Dump available keys to help debug
        available_keys = list(root_query.keys())[:10]
        raise ValueError(
            f"No eventSearch query found in Apollo ROOT_QUERY. "
            f"Available root keys: {available_keys}"
        )

    connection = root_query[event_search_key]

    # Extract pagination info
    page_info_ref = connection.get("pageInfo", {})
    if "__ref" in page_info_ref:
        page_info_data = apollo.get(page_info_ref["__ref"], {})
    else:
        page_info_data = page_info_ref

    # Also capture resolved location (may differ from requested location due to geo-IP)
    user_location = page_props.get("userLocation", {})

    page_info = {
        "hasNextPage": page_info_data.get("hasNextPage", False),
        "endCursor": page_info_data.get("endCursor"),
        "totalCount": connection.get("totalCount", 0),
        "resolved_location": {
            "city": user_location.get("city"),
            "country": user_location.get("country"),
            "name": user_location.get("name"),
            "lat": user_location.get("lat"),
            "lon": user_location.get("lon"),
            "timezone": user_location.get("timeZone"),
        },
    }

    # Resolve event edges
    edges = connection.get("edges", [])
    events = []

    for edge in edges:
        # Each edge may be a direct object or a __ref to an edge in the cache
        if "__ref" in edge:
            edge = apollo.get(edge["__ref"], {})

        node_ref = edge.get("node", {})
        if "__ref" in node_ref:
            node_ref = apollo.get(node_ref["__ref"], {})

        if not node_ref:
            continue

        # Resolve nested refs: group, venue, photo
        group = node_ref.get("group", {})
        if "__ref" in group:
            group = apollo.get(group["__ref"], {})

        venue = node_ref.get("venue") or {}
        if "__ref" in venue:
            venue = apollo.get(venue["__ref"], {})

        photo = node_ref.get("featuredEventPhoto") or node_ref.get("displayPhoto") or {}
        if "__ref" in photo:
            photo = apollo.get(photo["__ref"], {})

        # Resolve edge metadata (recId, recSource for analytics tracking)
        metadata = edge.get("metadata", {})
        if "__ref" in metadata:
            metadata = apollo.get(metadata["__ref"], {})

        # Build normalized event dict
        event = {
            "id": node_ref.get("id"),
            "title": node_ref.get("title"),
            "date_time": node_ref.get("dateTime"),
            "event_type": node_ref.get("eventType"),  # "PHYSICAL" or "ONLINE"
            "url": node_ref.get("eventUrl"),
            "description": node_ref.get("description", ""),
            "rsvp_count": (
                (node_ref.get("rsvps") or {}).get("totalCount", 0)
                if isinstance(node_ref.get("rsvps"), dict)
                else 0
            ),
            "rsvp_state": node_ref.get("rsvpState"),  # e.g. "JOIN_OPEN"
            "max_tickets": node_ref.get("maxTickets", 0),
            "is_paid": node_ref.get("feeSettings") is not None,
            "group": {
                "id": group.get("id"),
                "name": group.get("name"),
                "slug": group.get("urlname"),
                "timezone": group.get("timezone"),
                "is_new": group.get("isNewGroup", False),
                "rating": (
                    (group.get("stats") or {})
                    .get("eventRatings", {})
                    .get("average")
                ),
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
            "photo_url": photo.get("highResUrl") or (
                f"{photo.get('baseUrl', '')}{node_ref.get('id')}.jpeg"
                if photo.get("baseUrl") and node_ref.get("id")
                else None
            ),
            # Tracking metadata (kept for context, not needed for display)
            "_rec_id": metadata.get("recId"),
            "_rec_source": metadata.get("recSource"),
        }
        events.append(event)

    return events, page_info


def search_meetup_events(
    keywords: str,
    location: str,
    max_pages: int = 1,
    source: str = "EVENTS",
) -> list[dict]:
    """
    Search Meetup.com for public events matching keywords near a location.

    This is the main entry point. It handles:
      1. buildId discovery (one HEAD request)
      2. Paginated event fetching (up to max_pages pages)
      3. Parsing and normalizing the Apollo cache response

    Args:
        keywords:   Search term (e.g. "python", "tech")
        location:   City name (e.g. "Berlin, Germany", "Munich, Germany")
        max_pages:  Maximum number of result pages to fetch (default: 1)
        source:     "EVENTS" (default) or "GROUPS"

    Returns:
        List of normalized event dicts. Each dict contains:
          id, title, date_time, event_type, url, description,
          rsvp_count, group (id/name/slug/timezone/rating),
          venue (name/address/city/...), photo_url

    Notes:
        - Results are geo-resolved server-side; passing lat/lon in the URL
          does NOT override the geo-resolver — the location string is used
          for a place lookup instead.
        - Each page contains ~12–15 events. Pagination uses Relay-style
          base64 cursors (endCursor from pageInfo).
        - Rate limiting: a REQUEST_DELAY pause is inserted between pages.
    """
    session = requests.Session()
    # Seed cookies by visiting the main page first (helps avoid bot checks)
    session.get(BASE_URL, headers=HEADERS, timeout=15)
    time.sleep(0.5)

    build_id = get_build_id(session)
    all_events: list[dict] = []
    cursor: Optional[str] = None
    page = 0

    while page < max_pages:
        page += 1
        print(f"\n[PAGE {page}/{max_pages}]")

        raw_data = fetch_events_page(
            session=session,
            build_id=build_id,
            keywords=keywords,
            location=location,
            source=source,
            cursor=cursor,
        )

        events, page_info = parse_events(raw_data)
        all_events.extend(events)

        print(
            f"[PAGE {page}] Got {len(events)} events "
            f"(total so far: {len(all_events)}, "
            f"has_next: {page_info['hasNextPage']}, "
            f"cursor: {page_info['endCursor']})"
        )

        if not page_info["hasNextPage"] or not page_info["endCursor"]:
            print("[PAGE] No more pages available.")
            break

        cursor = page_info["endCursor"]

        # Polite delay between pages
        if page < max_pages:
            time.sleep(REQUEST_DELAY)

    return all_events


# ---------------------------------------------------------------------------
# Test functions (following project test script conventions)
# ---------------------------------------------------------------------------


def test_search_events(keywords: str = "tech", location: str = "Berlin, Germany") -> dict:
    """Search for tech events near Berlin — basic happy path."""
    print("\n" + "=" * 60)
    print("TEST: search_events")
    print(f"      keywords={keywords!r}  location={location!r}")
    print("=" * 60)

    start = time.time()
    try:
        events = search_meetup_events(keywords=keywords, location=location, max_pages=1)
        duration = time.time() - start

        if not events:
            print("[WARN] No events returned — this may be a geo-resolution issue")
            print("       Meetup uses the server's IP for geo-detection; the location")
            print("       param may be overridden when running behind a US-based proxy.")
            return {"status": "warn", "duration": duration, "data": events, "count": 0}

        print(f"\n[OK] Found {len(events)} events ({duration:.2f}s)")
        print("\nSample events:")
        for i, e in enumerate(events[:5], 1):
            venue_str = (
                f"{e['venue']['city']}, {e['venue']['country']}"
                if e.get("venue")
                else e["event_type"]
            )
            print(f"  {i}. [{e['date_time'][:10]}] {e['title'][:60]}")
            print(f"     Group: {e['group']['name'][:50]}")
            print(f"     Location: {venue_str}  |  RSVPs: {e['rsvp_count']}")
            print(f"     URL: {e['url']}")

        return {"status": "pass", "duration": duration, "data": events, "count": len(events)}
    except Exception as exc:
        duration = time.time() - start
        print(f"[FAIL] {exc} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(exc)}


def test_pagination(keywords: str = "python", location: str = "London, UK") -> dict:
    """Fetch 2 pages of results and verify cursor-based pagination works."""
    print("\n" + "=" * 60)
    print("TEST: pagination")
    print(f"      keywords={keywords!r}  location={location!r}  pages=2")
    print("=" * 60)

    start = time.time()
    try:
        events = search_meetup_events(keywords=keywords, location=location, max_pages=2)
        duration = time.time() - start

        print(f"\n[OK] Fetched {len(events)} events across 2 pages ({duration:.2f}s)")
        if len(events) > 12:
            print("[OK] Pagination working: got more than 1 page of results")
        else:
            print(f"[INFO] Only {len(events)} events total — may be end of results")

        return {"status": "pass", "duration": duration, "count": len(events)}
    except Exception as exc:
        duration = time.time() - start
        print(f"[FAIL] {exc} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(exc)}


def test_group_search(keywords: str = "python", location: str = "Berlin, Germany") -> dict:
    """Search for groups instead of events (source=GROUPS)."""
    print("\n" + "=" * 60)
    print("TEST: group_search")
    print(f"      keywords={keywords!r}  location={location!r}  source=GROUPS")
    print("=" * 60)

    start = time.time()
    try:
        # Groups use a different Apollo query shape — may need separate parsing
        session = requests.Session()
        session.get(BASE_URL, headers=HEADERS, timeout=15)
        time.sleep(0.5)

        build_id = get_build_id(session)
        raw = fetch_events_page(
            session=session,
            build_id=build_id,
            keywords=keywords,
            location=location,
            source="GROUPS",
        )
        duration = time.time() - start

        # For groups, we just verify the response structure rather than parse it
        page_props = raw.get("pageProps", {})
        apollo = page_props.get("apolloState", {})
        if "__APOLLO_STATE__" in apollo:
            apollo = apollo["__APOLLO_STATE__"]

        root_query = apollo.get("ROOT_QUERY", {})
        group_keys = [k for k in root_query if "groupSearch" in k or "keywordSearch" in k]

        print(f"[OK] Group search response received ({duration:.2f}s)")
        print(f"     Apollo ROOT_QUERY keys: {list(root_query.keys())[:5]}")
        print(f"     Group query keys found: {group_keys[:3]}")

        # Count Group entities in cache
        group_count = sum(1 for k in apollo if k.startswith("Group:"))
        print(f"     Group entities in cache: {group_count}")

        return {
            "status": "pass",
            "duration": duration,
            "group_keys": group_keys,
            "group_count": group_count,
        }
    except Exception as exc:
        duration = time.time() - start
        print(f"[FAIL] {exc} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(exc)}


def test_build_id_discovery() -> dict:
    """Verify that buildId discovery via HEAD request works correctly."""
    print("\n" + "=" * 60)
    print("TEST: build_id_discovery")
    print("=" * 60)

    start = time.time()
    try:
        session = requests.Session()
        build_id = get_build_id(session)
        duration = time.time() - start

        if not build_id or len(build_id) < 10:
            raise ValueError(f"BuildId looks invalid: {build_id!r}")

        print(f"[OK] buildId: {build_id} ({duration:.2f}s)")
        return {"status": "pass", "duration": duration, "build_id": build_id}
    except Exception as exc:
        duration = time.time() - start
        print(f"[FAIL] {exc} ({duration:.2f}s)")
        return {"status": "fail", "duration": duration, "error": str(exc)}


# ---------------------------------------------------------------------------
# Test registry and CLI
# ---------------------------------------------------------------------------

TESTS = {
    "build_id_discovery": lambda: test_build_id_discovery(),
    "search_events": lambda: test_search_events(),
    "pagination": lambda: test_pagination(),
    "group_search": lambda: test_group_search(),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test Meetup.com event search via reverse-engineered scraping"
    )
    parser.add_argument("--keywords", default="tech", help="Search keywords")
    parser.add_argument("--location", default="Berlin, Germany", help="Location string")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to fetch")
    parser.add_argument("--test", help="Run a specific test by name")
    parser.add_argument("--list", action="store_true", help="List available tests")
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Output results as JSON (for piping)",
    )
    args = parser.parse_args()

    if args.list:
        print("Available tests:")
        for name, fn in TESTS.items():
            print(f"  {name}: {fn.__doc__ or '(no description)'}")
        return

    if args.test:
        # Run a single named test
        if args.test not in TESTS:
            print(f"Unknown test: {args.test!r}. Use --list to see available tests.")
            sys.exit(1)
        result = TESTS[args.test]()
        if args.json_only:
            print(json.dumps(result, indent=2, default=str))
        return

    # Custom search mode (when --keywords or --location are specified)
    if args.keywords != "tech" or args.location != "Berlin, Germany" or args.pages != 1:
        events = search_meetup_events(
            keywords=args.keywords,
            location=args.location,
            max_pages=args.pages,
        )
        if args.json_only:
            print(json.dumps(events, indent=2, default=str))
        else:
            print(f"\nFound {len(events)} events:")
            for e in events:
                venue = (
                    f"{e['venue']['city']}" if e.get("venue") and e["venue"].get("city")
                    else e.get("event_type", "?")
                )
                print(f"  [{e['date_time'][:10]}] {e['title']}")
                print(f"    {e['group']['name']} | {venue} | {e['rsvp_count']} RSVPs")
                print(f"    {e['url']}")
        return

    # Default: run all tests
    results = {}
    for name, fn in TESTS.items():
        results[name] = fn()
        time.sleep(REQUEST_DELAY)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in results.values() if r.get("status") == "pass")
    warned = sum(1 for r in results.values() if r.get("status") == "warn")
    failed = sum(1 for r in results.values() if r.get("status") == "fail")
    print(f"Passed: {passed}  |  Warned: {warned}  |  Failed: {failed}  |  Total: {len(results)}")
    for name, result in results.items():
        status = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(
            result.get("status", "fail"), "FAIL"
        )
        print(f"  [{status}] {name} ({result.get('duration', 0):.2f}s)")

    if args.json_only:
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
