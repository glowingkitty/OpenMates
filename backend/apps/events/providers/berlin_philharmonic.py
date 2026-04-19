# backend/apps/events/providers/berlin_philharmonic.py
#
# Purpose: Query Berliner Philharmoniker calendar endpoint for concert listings.
# Architecture: JSON API adapter used by events.search provider routing.
# Architecture Doc: docs/architecture/README.md
# Tests: N/A (covered by manual API scripts in scripts/api_tests/)

import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from backend.shared.testing.caching_http_transport import create_http_client

BASE_URL = "https://www.berliner-philharmoniker.de"
SEARCH_URL = f"{BASE_URL}/filter/search/collections/performance_1/documents/search"
SEARCH_API_KEY = "09zNJI6igIRLJHhNB2YGwgaX0JApQYOL"
DEFAULT_TIMEOUT_SECONDS = 25.0
DEFAULT_QUERY_BY = "title,place,works_raw,artists_raw,super_title,brand_title,brand_title_second"


def _build_filter_expression(
    *,
    include_guest_events: bool,
    tags: List[str],
    include_past: bool,
) -> str:
    clauses: List[str] = []
    clauses.append(f"is_guest_event:{'true' if include_guest_events else 'false'}")

    if tags:
        for tag in tags:
            clauses.append(f"tags:={tag}")
    else:
        clauses.append("tags:!=Guided tours")
        clauses.append("tags:!=On tour")

    if not include_past:
        clauses.append(f"time_start:>={int(time.time())}")
    return " && ".join(clauses)


async def search_events_async(
    *,
    location: str,
    query: str = "",
    tags: List[str],
    count: int,
    include_guest_events: bool = False,
    include_past: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    if "berlin" not in (location or "").lower():
        raise ValueError("Berlin Philharmonic provider currently supports Berlin location only.")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "x-typesense-api-key": SEARCH_API_KEY,
    }
    params = {
        "q": query.strip() if query else "*",
        "query_by": DEFAULT_QUERY_BY,
        "filter_by": _build_filter_expression(
            include_guest_events=include_guest_events,
            tags=tags,
            include_past=include_past,
        ),
        "facet_by": "tags",
        "max_facet_values": "40",
        "sort_by": "time_start:asc",
        "drop_tokens_threshold": "0",
        "per_page": str(max(1, min(count, 50))),
        "page": "1",
    }

    async with create_http_client("berlin_philharmonic", timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(SEARCH_URL, headers=headers, params=params)
    response.raise_for_status()
    payload = response.json()

    events: List[Dict[str, Any]] = []
    for hit in payload.get("hits", []):
        doc = hit.get("document", {})

        detail_url_raw = doc.get("detail_url")
        tickets_url_raw = doc.get("tickets_url")
        booking_url: Optional[str] = None
        if isinstance(tickets_url_raw, str) and tickets_url_raw and tickets_url_raw != "Discontinued":
            booking_url = urljoin(BASE_URL, tickets_url_raw)

        events.append(
            {
                "id": str(doc.get("id", "")),
                "provider": "berlin_philharmonic",
                "title": doc.get("title", ""),
                "description": doc.get("super_title") or doc.get("brand_title") or "",
                "url": urljoin(BASE_URL, detail_url_raw) if detail_url_raw else None,
                "date_start": doc.get("date_time_string"),
                "date_end": None,
                "timezone": None,
                "event_type": "PHYSICAL",
                "venue": {
                    "name": doc.get("place"),
                    "address": None,
                    "city": "Berlin",
                    "state": None,
                    "country": "Germany",
                    "lat": None,
                    "lon": None,
                },
                "organizer": None,
                "rsvp_count": 0,
                "is_paid": None,
                "fee": None,
                "image_url": None,
                "booking_url": booking_url,
                "date_text": doc.get("date_string", ""),
                "tags": doc.get("tags", []),
                "is_guest_event": bool(doc.get("is_guest_event", False)),
            }
        )

    total_count = int(payload.get("found", len(events)) or len(events))
    return events, total_count
