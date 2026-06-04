#!/usr/bin/env python3
"""
Purpose: Test Eventbrite event search through its reverse-engineered web API.
Architecture: Standalone API-feasibility script for event-provider research.
Architecture Doc: docs/apis/eventbrite.md
Tests: Manual CLI script, supports direct and Webshare proxy comparison.

Eventbrite's official public Event Search API was shut down in 2019. This
script exercises the web app's current destination search endpoint for research.
"""

import argparse
import json
import os
import secrets
import sys
import time
from typing import Any

import httpx


EVENTBRITE_BASE_URL = "https://www.eventbrite.com"
SEARCH_ENDPOINT = f"{EVENTBRITE_BASE_URL}/api/v3/destination/search/"
DEFAULT_REFERER = f"{EVENTBRITE_BASE_URL}/d/germany--berlin/events/?q=ai"
DEFAULT_PLACE_ID = "101748799"  # Berlin locality, from Eventbrite server data.
DEFAULT_QUERY = "ai"
DEFAULT_PAGE_SIZE = 5
DEFAULT_TIMEOUT_SECONDS = 25
DEFAULT_BATCH_DELAY_SECONDS = 0.4

DEFAULT_BATCH_TOPICS = [
    "ai",
    "startup",
    "techno",
    "jazz",
    "yoga",
    "art",
    "film",
    "networking",
    "workshop",
    "food",
    "comedy",
    "design",
    "climate",
    "blockchain",
    "photography",
    "dance",
    "meditation",
    "marketing",
    "conference",
    "concert",
]

WEBSHARE_HOST = "p.webshare.io"
WEBSHARE_PORT = 80

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": EVENTBRITE_BASE_URL,
    "Referer": DEFAULT_REFERER,
}


def build_search_payload(
    query: str,
    place_id: str | None,
    page_size: int,
    page: int,
) -> dict[str, Any]:
    event_search: dict[str, Any] = {
        "dates": "current_future",
        "dedup": True,
        "page_size": page_size,
        "q": query,
        "aggs": ["places_borough", "places_neighborhood"],
        "page": page,
    }
    if place_id:
        event_search["places"] = [place_id]

    return {
        "event_search": event_search,
        "expand.destination_event": [
            "primary_venue",
            "image",
            "ticket_availability",
            "saves",
            "event_sales_status",
            "primary_organizer",
            "public_collections",
        ],
        "browse_surface": "search",
    }


def build_proxy_url(args: argparse.Namespace) -> str | None:
    if args.proxy_url:
        return args.proxy_url
    if not args.webshare:
        return None

    username = args.proxy_username or os.environ.get("WEBSHARE_PROXY_USERNAME", "")
    password = args.proxy_password or os.environ.get("WEBSHARE_PROXY_PASSWORD", "")
    if not username or not password:
        raise ValueError(
            "Missing Webshare credentials. Provide --proxy-username/--proxy-password "
            "or set WEBSHARE_PROXY_USERNAME and WEBSHARE_PROXY_PASSWORD."
        )
    return f"http://{username}:{password}@{WEBSHARE_HOST}:{WEBSHARE_PORT}"


def create_client(proxy_url: str | None) -> httpx.Client:
    return httpx.Client(
        headers=REQUEST_HEADERS,
        proxy=proxy_url,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        follow_redirects=True,
    )


def summarize_event(event: dict[str, Any]) -> dict[str, Any]:
    venue = event.get("primary_venue") or {}
    address = venue.get("address") or {}
    image = event.get("image") or {}
    return {
        "id": event.get("id"),
        "title": event.get("name"),
        "url": event.get("url"),
        "start_date": event.get("start_date"),
        "start_time": event.get("start_time"),
        "timezone": event.get("timezone"),
        "venue": venue.get("name"),
        "city": address.get("city"),
        "country": address.get("country"),
        "image_url": image.get("url"),
        "is_free": event.get("is_free"),
        "sales_status": (event.get("event_sales_status") or {}).get("sales_status"),
    }


def parse_search_response(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    data = response.json()
    events = data.get("events") or {}
    results = events.get("results") or []
    pagination = events.get("pagination") or {}
    return {
        "status_code": response.status_code,
        "search_id": data.get("search_id"),
        "count": len(results),
        "pagination": pagination,
        "events": [summarize_event(event) for event in results],
    }


def search_events(
    args: argparse.Namespace,
    proxy_url: str | None,
    include_csrf: bool = True,
) -> dict[str, Any]:
    payload = build_search_payload(
        query=args.query,
        place_id=args.place_id,
        page_size=args.page_size,
        page=args.page,
    )
    headers = dict(REQUEST_HEADERS)
    cookies: dict[str, str] = {}
    if include_csrf:
        csrf_token = secrets.token_hex(16)
        headers["X-CSRFToken"] = csrf_token
        cookies["csrftoken"] = csrf_token

    started_at = time.time()
    with create_client(proxy_url) as client:
        response = client.post(
            SEARCH_ENDPOINT,
            headers=headers,
            cookies=cookies,
            json=payload,
        )
    duration = time.time() - started_at

    if response.status_code >= 400:
        return {
            "status": "fail",
            "duration": round(duration, 2),
            "status_code": response.status_code,
            "error": response.text[:500],
        }

    result = parse_search_response(response)
    result.update(
        {
            "status": "pass" if result["count"] > 0 else "fail",
            "duration": round(duration, 2),
            "proxy": bool(proxy_url),
        }
    )
    if result["count"] == 0:
        result["error"] = "No events returned"
    return result


def test_direct_search(args: argparse.Namespace) -> dict[str, Any]:
    """Search Eventbrite directly without Webshare proxy."""
    return search_events(args=args, proxy_url=None, include_csrf=True)


def test_proxy_search(args: argparse.Namespace) -> dict[str, Any]:
    """Search Eventbrite through --proxy-url or Webshare credentials."""
    proxy_url = build_proxy_url(args)
    if not proxy_url:
        return {
            "status": "skip",
            "error": "No proxy configured. Use --webshare or --proxy-url.",
        }
    return search_events(args=args, proxy_url=proxy_url, include_csrf=True)


def test_csrf_required(args: argparse.Namespace) -> dict[str, Any]:
    """Verify the endpoint rejects a request without CSRF cookie/header."""
    result = search_events(args=args, proxy_url=None, include_csrf=False)
    if result.get("status_code") == 401 and "CSRF" in result.get("error", ""):
        return {
            "status": "pass",
            "duration": result["duration"],
            "status_code": result["status_code"],
            "evidence": result["error"],
        }
    return {
        "status": "fail",
        "error": "Expected a 401 CSRF failure without csrf cookie/header",
        "observed": result,
    }


def test_compare_proxy(args: argparse.Namespace) -> dict[str, Any]:
    """Run direct and proxy searches to compare whether Webshare is required."""
    direct = test_direct_search(args)
    proxy = test_proxy_search(args)
    proxy_status = proxy.get("status")
    direct_status = direct.get("status")

    if direct_status == "pass":
        conclusion = "direct_works"
    elif direct_status != "pass" and proxy_status == "pass":
        conclusion = "proxy_required_or_helpful"
    elif proxy_status == "skip":
        conclusion = "direct_failed_proxy_not_configured"
    else:
        conclusion = "both_failed"

    return {
        "status": "pass" if conclusion in {"direct_works", "proxy_required_or_helpful"} else "fail",
        "conclusion": conclusion,
        "direct": direct,
        "proxy": proxy,
    }


def _search_safely(
    args: argparse.Namespace,
    proxy_url: str | None,
) -> dict[str, Any]:
    try:
        return search_events(args=args, proxy_url=proxy_url, include_csrf=True)
    except Exception as exc:
        return {"status": "fail", "error": str(exc), "proxy": bool(proxy_url)}


def _get_optional_proxy_url(args: argparse.Namespace) -> tuple[str | None, str | None]:
    try:
        return build_proxy_url(args), None
    except ValueError as exc:
        return None, str(exc)


def test_batch_topics(args: argparse.Namespace) -> dict[str, Any]:
    """Run 20 varied direct searches, using proxy fallback only after direct failure."""
    topics = args.topics or DEFAULT_BATCH_TOPICS
    proxy_url, proxy_config_error = _get_optional_proxy_url(args)
    results = []
    direct_successes = 0
    direct_access_failures = 0
    proxy_fallback_attempts = 0
    proxy_fallback_successes = 0

    original_query = args.query
    try:
        for index, topic in enumerate(topics, start=1):
            args.query = topic
            direct = _search_safely(args=args, proxy_url=None)
            used_proxy = False
            final = direct

            # A 200 with zero results proves access works; do not burn proxy for relevance misses.
            direct_access_ok = direct.get("status_code") == 200
            if direct_access_ok:
                direct_successes += 1
            else:
                direct_access_failures += 1
                if proxy_url:
                    proxy_fallback_attempts += 1
                    used_proxy = True
                    final = _search_safely(args=args, proxy_url=proxy_url)
                    if final.get("status_code") == 200:
                        proxy_fallback_successes += 1

            results.append(
                {
                    "index": index,
                    "topic": topic,
                    "direct_status": direct.get("status"),
                    "direct_status_code": direct.get("status_code"),
                    "direct_count": direct.get("count", 0),
                    "direct_duration": direct.get("duration"),
                    "used_proxy_fallback": used_proxy,
                    "final_status": final.get("status"),
                    "final_status_code": final.get("status_code"),
                    "final_count": final.get("count", 0),
                    "error": None if final.get("status_code") == 200 else final.get("error"),
                }
            )

            if index < len(topics):
                time.sleep(args.delay)
    finally:
        args.query = original_query

    conclusion = "direct_works"
    if direct_access_failures and proxy_fallback_successes == direct_access_failures:
        conclusion = "proxy_fallback_covers_direct_failures"
    elif direct_access_failures and proxy_fallback_attempts == 0:
        conclusion = "direct_failures_proxy_not_configured"
    elif direct_access_failures:
        conclusion = "some_failures_not_fixed_by_proxy"

    return {
        "status": "pass" if direct_successes == len(topics) or proxy_fallback_successes else "fail",
        "conclusion": conclusion,
        "topics_tested": len(topics),
        "direct_successes": direct_successes,
        "direct_access_failures": direct_access_failures,
        "proxy_fallback_attempts": proxy_fallback_attempts,
        "proxy_fallback_successes": proxy_fallback_successes,
        "proxy_configured": bool(proxy_url),
        "proxy_config_error": proxy_config_error,
        "results": results,
    }


TESTS = {
    "batch_topics": test_batch_topics,
    "direct_search": test_direct_search,
    "proxy_search": test_proxy_search,
    "csrf_required": test_csrf_required,
    "compare_proxy": test_compare_proxy,
}


def print_human_summary(result: dict[str, Any]) -> None:
    if "events" not in result:
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return

    pagination = result.get("pagination") or {}
    print(
        f"[eventbrite] status={result['status']} count={result['count']} "
        f"duration={result['duration']}s object_count={pagination.get('object_count')} "
        f"page_count={pagination.get('page_count')}"
    )
    for event in result["events"]:
        print(f"- {event['title']} | {event.get('start_date')} {event.get('start_time') or ''}")
        print(f"  venue: {event.get('venue') or '-'} | {event.get('city') or '-'}")
        print(f"  url:   {event.get('url') or '-'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Eventbrite reverse-engineered event search API")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Search query (default: ai)")
    parser.add_argument(
        "--place-id",
        default=DEFAULT_PLACE_ID,
        help="Eventbrite place ID. Default is Berlin locality 101748799. Use empty string for global search.",
    )
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="Results per page")
    parser.add_argument("--page", type=int, default=1, help="Page number")
    parser.add_argument(
        "--topics",
        nargs="+",
        help="Topics for batch_topics test. Defaults to 20 varied topics.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_BATCH_DELAY_SECONDS,
        help="Delay between batch topic requests in seconds.",
    )
    parser.add_argument("--test", choices=sorted(TESTS.keys()), default="direct_search", help="Test to run")
    parser.add_argument("--list", action="store_true", help="List available tests")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument("--webshare", action="store_true", help="Use Webshare proxy credentials from flags/env")
    parser.add_argument("--proxy-url", help="Explicit proxy URL, e.g. http://user:pass@host:port")
    parser.add_argument("--proxy-username", help="Webshare proxy username (or WEBSHARE_PROXY_USERNAME)")
    parser.add_argument("--proxy-password", help="Webshare proxy password (or WEBSHARE_PROXY_PASSWORD)")
    args = parser.parse_args()

    if args.list:
        for name, fn in TESTS.items():
            print(f"  {name}: {fn.__doc__}")
        return

    if args.place_id == "":
        args.place_id = None

    try:
        result = TESTS[args.test](args)
    except Exception as exc:
        result = {"status": "fail", "error": str(exc)}

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True))
    else:
        print_human_summary(result)

    if result.get("status") == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
