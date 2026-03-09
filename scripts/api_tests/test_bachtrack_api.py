#!/usr/bin/env python3
"""
Purpose: Search Berlin classical events from Bachtrack by reverse-engineering listing HTML.
Architecture: Standalone API-feasibility script for source comparison experiments.
Architecture Doc: docs/architecture/README.md
Tests: N/A (manual CLI verification script)

This script does not use an official Bachtrack API. It parses the public listing page.
"""

import argparse
import html
import json
import re
import time
from typing import Any
from urllib.parse import urljoin

import requests


BACHTRACK_BASE_URL = "https://bachtrack.com"
DEFAULT_CITY = "berlin"
DEFAULT_TIMEOUT_SECONDS = 25
DEFAULT_SECTION = "search-events"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BACHTRACK_BASE_URL + "/",
}

SUPPORTED_SECTIONS = {
    "all": "search-events",
    "concerts": "search-concerts",
    "opera": "search-opera",
    "dance": "search-dance",
    "kids": "search-kids-events",
    "master_classes": "search-master-classes",
}


def _strip_tags(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    unescaped = html.unescape(without_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def fetch_events(city: str, section_slug: str) -> list[dict[str, Any]]:
    search_url = f"{BACHTRACK_BASE_URL}/{section_slug}/city={city}"
    response = requests.get(
        search_url,
        headers=REQUEST_HEADERS,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    page = response.text

    booking_by_id: dict[str, str] = {}
    for event_id, device in re.findall(r"/handler/listing/click/(\d+)/(SearchMobile|Search)", page):
        if event_id not in booking_by_id or device == "Search":
            booking_by_id[event_id] = urljoin(
                BACHTRACK_BASE_URL,
                f"/handler/listing/click/{event_id}/Search",
            )

    event_pattern = re.compile(
        r"<div\s+data-id=\"(?P<id>\d+)\"[^>]*>"
        r"(?P<body>.*?)"
        r"<div class=\"li-shortform-title\">(?P<title>.*?)</div>"
        r".*?href=\"(?P<detail>/[^\"]+?/\d+)\"\s+class=\"listing-more-info\""
        r"(?P<tail>.*?)</div>\s*</div>\s*</div>",
        re.S,
    )

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for match in event_pattern.finditer(page):
        event_id = match.group("id")
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)

        full_block = match.group(0)
        venue_match = re.search(r"<h2 class=\"li-shortform-venue\"[^>]*>(.*?)</h2>", full_block, re.S)
        dates_match = re.search(r"<div class=\"listing-shortform-dates\">(.*?)</div>", full_block, re.S)

        venue_text = _strip_tags(venue_match.group(1)) if venue_match else ""
        city_name = ""
        if "," in venue_text:
            city_name = venue_text.split(",", maxsplit=1)[1].strip()

        events.append(
            {
                "source": "bachtrack",
                "source_event_id": event_id,
                "title": _strip_tags(match.group("title")),
                "date_text": _strip_tags(dates_match.group(1)) if dates_match else "",
                "venue": venue_text,
                "city": city_name,
                "detail_url": urljoin(BACHTRACK_BASE_URL, match.group("detail")),
                "booking_url": booking_by_id.get(event_id),
                "search_url": search_url,
                "section": section_slug,
            }
        )

    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverse-engineered Bachtrack Berlin event search")
    parser.add_argument("--city", default=DEFAULT_CITY, help="City slug used by Bachtrack URL (default: berlin)")
    parser.add_argument(
        "--category",
        default="all",
        choices=sorted(SUPPORTED_SECTIONS.keys()),
        help="Listing category route (default: all)",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List supported Bachtrack categories",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    if args.list_categories:
        print(json.dumps(SUPPORTED_SECTIONS, indent=2, ensure_ascii=True))
        return

    started_at = time.time()
    section_slug = SUPPORTED_SECTIONS[args.category]
    events = fetch_events(city=args.city, section_slug=section_slug)
    duration = time.time() - started_at

    payload = {
        "source": "bachtrack",
        "city": args.city,
        "category": args.category,
        "section": section_slug,
        "count": len(events),
        "duration_seconds": round(duration, 2),
        "events": events,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return

    print(
        f"[bachtrack] {len(events)} events for city={args.city!r}, "
        f"category={args.category!r} ({duration:.2f}s)"
    )
    for item in events[:15]:
        print(f"- {item['title']} | {item['date_text']} | {item['venue']}")
        print(f"  detail:  {item['detail_url']}")
        print(f"  booking: {item['booking_url'] or '-'}")


if __name__ == "__main__":
    main()
