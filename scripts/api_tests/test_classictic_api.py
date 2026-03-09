#!/usr/bin/env python3
"""
Purpose: Search Berlin classical events from Classictic via reverse-engineered listing pages.
Architecture: Standalone API-feasibility script for source comparison experiments.
Architecture Doc: docs/architecture/README.md
Tests: N/A (manual CLI verification script)

This script does not use an official Classictic API. It parses the public city page.
"""

import argparse
import html
import json
import re
import time
from typing import Any

import requests


CLASSICTIC_BERLIN_URL = "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1/berlin-concerts-el234"
DEFAULT_TIMEOUT_SECONDS = 25
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SUPPORTED_CATEGORY_URLS = {
    "all_events": "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1",
    "concerts": "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1/berlin-concerts-el234",
    "opera": "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1/berlin-opera-el3271",
    "church_concerts": "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1/berlin-church-concerts-el2897",
    "philharmonie_concerts": "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1/berlin-philharmonie-concerts-el105",
    "cathedral_concerts": "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1/concerts-cathedral-berlin-el455",
    "vivaldi": "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1/vivaldi-concerts-berlin-el9186",
    "christmas": "https://www.classictic.com/en/city/berlin-t10/berlin-events-ec1/berlin-christmas-concerts-el148",
}


def _strip_tags(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    unescaped = html.unescape(without_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def fetch_events(listing_url: str) -> list[dict[str, Any]]:
    response = requests.get(
        listing_url,
        headers=REQUEST_HEADERS,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    page = response.text

    events: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    block_pattern = re.compile(r"<li class=\"preview\">([\s\S]*?)</li>", re.S)
    for block_match in block_pattern.finditer(page):
        block = block_match.group(1)
        detail_match = re.search(r"<a href=\"(https://www\.classictic\.com/[^\"]+\?e=\d+)\"", block)
        title_match = re.search(r"<h3>(.*?)</h3>", block, re.S)
        datetime_match = re.search(r"<time datetime=\"([^\"]+)\">(.*?)</time>", block, re.S)
        venue_line_match = re.search(r"<p>\s*(.*?)\s*</p>", block, re.S)

        if not detail_match or not title_match:
            continue

        detail_url = detail_match.group(1)
        if detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)

        venue_line = _strip_tags(venue_line_match.group(1)) if venue_line_match else ""
        city_name = venue_line.split(",", maxsplit=1)[0].strip() if "," in venue_line else venue_line

        source_event_id_match = re.search(r"\?e=(\d+)", detail_url)
        events.append(
            {
                "source": "classictic",
                "source_event_id": source_event_id_match.group(1) if source_event_id_match else None,
                "title": _strip_tags(title_match.group(1)),
                "date_time": datetime_match.group(1).strip() if datetime_match else "",
                "date_text": _strip_tags(datetime_match.group(2)) if datetime_match else "",
                "venue": venue_line,
                "city": city_name,
                "detail_url": detail_url,
                "booking_url": detail_url,
                "search_url": listing_url,
            }
        )

    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverse-engineered Classictic Berlin event search")
    parser.add_argument(
        "--category",
        default="concerts",
        choices=sorted(SUPPORTED_CATEGORY_URLS.keys()),
        help="Category page to scrape (default: concerts)",
    )
    parser.add_argument(
        "--url",
        default="",
        help="Override URL to scrape directly",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List supported Classictic category pages",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    if args.list_categories:
        print(json.dumps(SUPPORTED_CATEGORY_URLS, indent=2, ensure_ascii=True))
        return

    listing_url = args.url.strip() or SUPPORTED_CATEGORY_URLS[args.category]

    started_at = time.time()
    events = fetch_events(listing_url=listing_url)
    duration = time.time() - started_at

    payload = {
        "source": "classictic",
        "city": "berlin",
        "category": args.category,
        "search_url": listing_url,
        "count": len(events),
        "duration_seconds": round(duration, 2),
        "events": events,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return

    print(
        f"[classictic] {len(events)} events for Berlin "
        f"category={args.category!r} ({duration:.2f}s)"
    )
    for item in events[:15]:
        print(f"- {item['title']} | {item['date_text']} | {item['venue']}")
        print(f"  booking: {item['booking_url']}")


if __name__ == "__main__":
    main()
