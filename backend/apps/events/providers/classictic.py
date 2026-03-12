# backend/apps/events/providers/classictic.py
#
# Purpose: Fetch concert listings from Classictic category and reload endpoints.
# Architecture: Reverse-engineered HTML-fragment adapter used by events.search routing.
# Architecture Doc: docs/architecture/README.md
# Tests: N/A (covered by manual API scripts in scripts/api_tests/)

import html
import re
from typing import Any, Dict, List, Tuple

import httpx


BASE_URL = "https://www.classictic.com"
DEFAULT_TIMEOUT_SECONDS = 25.0

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

BERLIN_CATEGORY_URLS = {
    "all_events": f"{BASE_URL}/en/city/berlin-t10/berlin-events-ec1",
    "concerts": f"{BASE_URL}/en/city/berlin-t10/berlin-events-ec1/berlin-concerts-el234",
    "opera": f"{BASE_URL}/en/city/berlin-t10/berlin-events-ec1/berlin-opera-el3271",
    "church_concerts": f"{BASE_URL}/en/city/berlin-t10/berlin-events-ec1/berlin-church-concerts-el2897",
    "philharmonie_concerts": f"{BASE_URL}/en/city/berlin-t10/berlin-events-ec1/berlin-philharmonie-concerts-el105",
    "cathedral_concerts": f"{BASE_URL}/en/city/berlin-t10/berlin-events-ec1/concerts-cathedral-berlin-el455",
    "vivaldi": f"{BASE_URL}/en/city/berlin-t10/berlin-events-ec1/vivaldi-concerts-berlin-el9186",
}


def _strip_tags(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _resolve_category(categories: List[str]) -> str:
    for category in categories:
        key = (category or "").strip().lower().replace(" ", "_")
        if key == "all":
            key = "all_events"
        if key in BERLIN_CATEGORY_URLS:
            return key
    return "concerts"


async def _fetch_category_html(category_url: str) -> str:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(category_url, headers=REQUEST_HEADERS)
    response.raise_for_status()
    return response.text


def _parse_events(page: str, count: int, query: str) -> List[Dict[str, Any]]:
    block_pattern = re.compile(r"<li class=\"preview\">([\s\S]*?)</li>", re.S)
    events: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    query_tokens = [token for token in re.split(r"\s+", (query or "").strip().lower()) if token]

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
        source_event_id_match = re.search(r"\?e=(\d+)", detail_url)

        parsed_event = {
            "id": source_event_id_match.group(1) if source_event_id_match else None,
            "provider": "classictic",
            "title": _strip_tags(title_match.group(1)),
            "description": venue_line,
            "url": detail_url,
            "date_start": datetime_match.group(1).strip() if datetime_match else None,
            "date_end": None,
            "timezone": None,
            "event_type": "PHYSICAL",
            "venue": {
                "name": venue_line,
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
            "booking_url": detail_url,
            "date_text": _strip_tags(datetime_match.group(2)) if datetime_match else "",
        }

        if query_tokens:
            searchable = f"{parsed_event['title']} {parsed_event['description']}".lower()
            if not all(token in searchable for token in query_tokens):
                continue

        events.append(parsed_event)
        if len(events) >= count:
            break

    return events


async def search_events_async(
    *,
    query: str,
    location: str,
    categories: List[str],
    count: int,
) -> Tuple[List[Dict[str, Any]], int]:
    if "berlin" not in (location or "").lower():
        raise ValueError("Classictic provider currently supports Berlin location only.")

    category_key = _resolve_category(categories)
    page = await _fetch_category_html(BERLIN_CATEGORY_URLS[category_key])
    events = _parse_events(page=page, count=count, query=query)
    return events, len(events)
