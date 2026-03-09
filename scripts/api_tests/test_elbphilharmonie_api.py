#!/usr/bin/env python3
"""
Purpose: Search Elbphilharmonie events and filter for Berlin matches.
Architecture: Standalone API-feasibility script for source comparison experiments.
Architecture Doc: docs/architecture/README.md
Tests: N/A (manual CLI verification script)

This script does not use an official public events API. It parses the public event list.
"""

import argparse
import html
import json
import re
import time
from typing import Any
from urllib.parse import urljoin

import requests


ELB_BASE_URL = "https://www.elbphilharmonie.de"
ELB_WHATS_ON_URL = f"{ELB_BASE_URL}/en/whats-on/"
DEFAULT_CITY_FILTER = "berlin"
DEFAULT_TIMEOUT_SECONDS = 25
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _strip_tags(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    unescaped = html.unescape(without_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def fetch_events() -> list[dict[str, Any]]:
    response = requests.get(
        ELB_WHATS_ON_URL,
        headers=REQUEST_HEADERS,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    page = response.text

    item_pattern = re.compile(
        r"(<li id=\"event_id_[^\"]+\"[^>]*class=\"event-item\"[\s\S]*?</li>)",
        re.S,
    )

    events: list[dict[str, Any]] = []
    for block in item_pattern.findall(page):
        event_id_match = re.search(r'data-event-id=\"(\d+)\"', block)
        title_match = re.search(
            r'<p class=\"event-title h2 no-line\">\s*<a href=\"([^\"]+)\">\s*(.*?)\s*</a>',
            block,
            re.S,
        )
        datetime_match = re.search(r"<time datetime=\"([^\"]+)\">", block)
        place_match = re.search(r"<div class=\"cell small-6 medium-8 xlarge-12 place-cell\">(.*?)</div>", block, re.S)
        ticket_match = re.search(r"href=\"(/en/whats-on/ticket/[^\"]+)\"", block)

        if not event_id_match or not title_match:
            continue

        detail_rel = title_match.group(1).strip()
        title = _strip_tags(title_match.group(2))
        venue_text = _strip_tags(place_match.group(1)) if place_match else ""

        events.append(
            {
                "source": "elbphilharmonie",
                "source_event_id": event_id_match.group(1),
                "title": title,
                "date_time": datetime_match.group(1).strip() if datetime_match else "",
                "venue": venue_text,
                "city": "Hamburg",
                "detail_url": urljoin(ELB_BASE_URL, detail_rel),
                "booking_url": urljoin(ELB_BASE_URL, ticket_match.group(1)) if ticket_match else None,
                "search_url": ELB_WHATS_ON_URL,
            }
        )

    return events


def filter_for_city(events: list[dict[str, Any]], city_filter: str) -> list[dict[str, Any]]:
    lowered = city_filter.strip().lower()
    if not lowered:
        return events

    filtered: list[dict[str, Any]] = []
    for event in events:
        searchable = " ".join(
            [
                event.get("title", ""),
                event.get("venue", ""),
                event.get("city", ""),
            ]
        ).lower()
        if lowered in searchable:
            filtered.append(event)
    return filtered


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverse-engineered Elbphilharmonie event search")
    parser.add_argument(
        "--city-filter",
        default=DEFAULT_CITY_FILTER,
        help="Case-insensitive keyword filter over title/venue/city (default: berlin)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    started_at = time.time()
    all_events = fetch_events()
    filtered_events = filter_for_city(all_events, args.city_filter)
    duration = time.time() - started_at

    payload = {
        "source": "elbphilharmonie",
        "city_filter": args.city_filter,
        "count": len(filtered_events),
        "total_scraped": len(all_events),
        "duration_seconds": round(duration, 2),
        "events": filtered_events,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return

    print(
        f"[elbphilharmonie] {len(filtered_events)} filtered events "
        f"(from {len(all_events)} scraped, filter={args.city_filter!r}, {duration:.2f}s)"
    )
    for item in filtered_events[:15]:
        print(f"- {item['title']} | {item['date_time']} | {item['venue']}")
        print(f"  booking: {item['booking_url'] or '-'}")


if __name__ == "__main__":
    main()
