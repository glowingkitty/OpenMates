#!/usr/bin/env python3
"""
Purpose: Query Berliner Philharmoniker calendar events via observed Typesense endpoint.
Architecture: Standalone API-feasibility script for source comparison experiments.
Architecture Doc: docs/architecture/README.md
Tests: N/A (manual CLI verification script)

This script uses a public site endpoint with an exposed search API key from page config.
"""

import argparse
import json
import time
from typing import Any
from urllib.parse import urljoin

import requests


BASE_URL = "https://www.berliner-philharmoniker.de"
SEARCH_URL = f"{BASE_URL}/filter/search/collections/performance_1/documents/search"
SEARCH_API_KEY = "09zNJI6igIRLJHhNB2YGwgaX0JApQYOL"
DEFAULT_TIMEOUT_SECONDS = 25
DEFAULT_QUERY_BY = "title,place,works_raw,artists_raw,super_title,brand_title,brand_title_second"


def build_filter_expression(
    include_guest_events: bool,
    tag: str,
    include_past: bool,
) -> str:
    clauses: list[str] = []
    clauses.append(f"is_guest_event:{'true' if include_guest_events else 'false'}")
    if tag:
        clauses.append(f"tags:={tag}")
    else:
        clauses.append("tags:!=Guided tours")
        clauses.append("tags:!=On tour")
    if not include_past:
        clauses.append(f"time_start:>={int(time.time())}")
    return " && ".join(clauses)


def fetch_events(
    include_guest_events: bool,
    tag: str,
    per_page: int,
    page: int,
    include_past: bool,
) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "x-typesense-api-key": SEARCH_API_KEY,
    }
    params = {
        "q": "",
        "query_by": DEFAULT_QUERY_BY,
        "filter_by": build_filter_expression(
            include_guest_events=include_guest_events,
            tag=tag,
            include_past=include_past,
        ),
        "facet_by": "tags",
        "max_facet_values": "40",
        "sort_by": "time_start:asc",
        "drop_tokens_threshold": "0",
        "per_page": str(per_page),
        "page": str(page),
    }
    response = requests.get(
        SEARCH_URL,
        headers=headers,
        params=params,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def normalize_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for hit in payload.get("hits", []):
        doc = hit.get("document", {})
        detail_url_raw = doc.get("detail_url")
        tickets_url_raw = doc.get("tickets_url")
        booking_url: str | None = None
        if isinstance(tickets_url_raw, str) and tickets_url_raw.strip() and tickets_url_raw != "Discontinued":
            booking_url = urljoin(BASE_URL, tickets_url_raw)

        events.append(
            {
                "source": "berlin_philharmonic",
                "source_event_id": str(doc.get("id", "")),
                "title": doc.get("title", ""),
                "date_time": doc.get("date_time_string", ""),
                "date_text": doc.get("date_string", ""),
                "venue": doc.get("place", ""),
                "city": "Berlin",
                "detail_url": urljoin(BASE_URL, detail_url_raw) if detail_url_raw else None,
                "booking_url": booking_url,
                "tags": doc.get("tags", []),
                "primary_category": doc.get("primary_category"),
                "is_guest_event": bool(doc.get("is_guest_event", False)),
                "is_free": bool(doc.get("is_free", False)),
            }
        )
    return events


def summarize_facets(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    facets: dict[str, list[dict[str, Any]]] = {}
    for entry in payload.get("facet_counts", []):
        field_name = entry.get("field_name")
        if not field_name:
            continue
        counts = []
        for item in entry.get("counts", []):
            counts.append({"value": item.get("value"), "count": item.get("count")})
        facets[field_name] = counts
    return facets


def main() -> None:
    parser = argparse.ArgumentParser(description="Berlin Philharmonic calendar API probe")
    parser.add_argument("--tag", default="", help="Filter by exact tag value, e.g. 'Chamber Music'")
    parser.add_argument("--guest-events", action="store_true", help="Include guest events instead of BPhil events")
    parser.add_argument("--include-past", action="store_true", help="Do not restrict to future events")
    parser.add_argument("--per-page", type=int, default=30, help="Page size (default: 30)")
    parser.add_argument("--page", type=int, default=1, help="Page number (default: 1)")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    started_at = time.time()
    payload = fetch_events(
        include_guest_events=args.guest_events,
        tag=args.tag.strip(),
        per_page=max(1, args.per_page),
        page=max(1, args.page),
        include_past=args.include_past,
    )
    events = normalize_events(payload)
    facets = summarize_facets(payload)
    duration = time.time() - started_at

    report = {
        "source": "berlin_philharmonic",
        "count": len(events),
        "found": payload.get("found"),
        "page": payload.get("page"),
        "out_of": payload.get("out_of"),
        "tag_filter": args.tag.strip() or None,
        "guest_events": args.guest_events,
        "include_past": args.include_past,
        "duration_seconds": round(duration, 2),
        "facets": facets,
        "events": events,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return

    print(
        f"[berlin_philharmonic] page_hits={len(events)} found={payload.get('found')} "
        f"guest_events={args.guest_events} tag={args.tag!r} ({duration:.2f}s)"
    )
    for event in events[:15]:
        print(f"- {event['title']} | {event['date_text']} | {event['venue']}")
        print(f"  booking: {event['booking_url'] or '-'}")


if __name__ == "__main__":
    main()
