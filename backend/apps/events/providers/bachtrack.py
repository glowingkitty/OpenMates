# backend/apps/events/providers/bachtrack.py
#
# Purpose: Fetch concert listings from Bachtrack city/category pages.
# Architecture: Reverse-engineered HTML adapter used by events.search provider routing.
# Architecture Doc: docs/architecture/README.md
# Tests: N/A (covered by manual API scripts in scripts/api_tests/)

import html
import re
from typing import Any, Dict, List, Tuple

import httpx


BASE_URL = "https://bachtrack.com"
DEFAULT_TIMEOUT_SECONDS = 25.0

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL + "/",
}

SUPPORTED_CATEGORY_TO_SECTION = {
    "all": "search-events",
    "concerts": "search-concerts",
    "opera": "search-opera",
    "dance": "search-dance",
    "kids": "search-kids-events",
    "master_classes": "search-master-classes",
}


def _strip_tags(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _location_to_city_slug(location: str) -> str:
    city = (location or "").strip().split(",", maxsplit=1)[0].strip().lower()
    city = re.sub(r"\s+", "-", city)
    return re.sub(r"[^a-z\-]", "", city)


def _get_section_slug(categories: List[str]) -> str:
    for category in categories:
        key = (category or "").strip().lower().replace(" ", "_")
        if key in SUPPORTED_CATEGORY_TO_SECTION:
            return SUPPORTED_CATEGORY_TO_SECTION[key]
    return SUPPORTED_CATEGORY_TO_SECTION["all"]


async def search_events_async(
    *,
    location: str,
    categories: List[str],
    count: int,
) -> Tuple[List[Dict[str, Any]], int]:
    city_slug = _location_to_city_slug(location)
    if not city_slug:
        raise ValueError("Bachtrack provider requires a city in 'location'.")

    section_slug = _get_section_slug(categories)
    search_url = f"{BASE_URL}/{section_slug}/city={city_slug}"

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(search_url, headers=REQUEST_HEADERS)
    response.raise_for_status()
    page = response.text

    booking_by_id: Dict[str, str] = {}
    for event_id, device in re.findall(r"/handler/listing/click/(\d+)/(SearchMobile|Search)", page):
        if event_id not in booking_by_id or device == "Search":
            booking_by_id[event_id] = f"{BASE_URL}/handler/listing/click/{event_id}/Search"

    event_pattern = re.compile(
        r"<div\s+data-id=\"(?P<id>\d+)\"[^>]*>"
        r"(?P<body>.*?)"
        r"<div class=\"li-shortform-title\">(?P<title>.*?)</div>"
        r".*?href=\"(?P<detail>/[^\"]+?/\d+)\"\s+class=\"listing-more-info\""
        r"(?P<tail>.*?)</div>\s*</div>\s*</div>",
        re.S,
    )

    seen_ids: set[str] = set()
    events: List[Dict[str, Any]] = []
    for match in event_pattern.finditer(page):
        source_event_id = match.group("id")
        if source_event_id in seen_ids:
            continue
        seen_ids.add(source_event_id)

        full_block = match.group(0)
        venue_match = re.search(r"<h2 class=\"li-shortform-venue\"[^>]*>(.*?)</h2>", full_block, re.S)
        dates_match = re.search(r"<div class=\"listing-shortform-dates\">(.*?)</div>", full_block, re.S)

        venue_text = _strip_tags(venue_match.group(1)) if venue_match else ""
        date_text = _strip_tags(dates_match.group(1)) if dates_match else ""

        events.append(
            {
                "id": source_event_id,
                "provider": "bachtrack",
                "title": _strip_tags(match.group("title")),
                "description": f"{venue_text} | {date_text}".strip(" |"),
                "url": BASE_URL + match.group("detail"),
                "date_start": None,
                "date_end": None,
                "timezone": None,
                "event_type": "PHYSICAL",
                "venue": {
                    "name": venue_text,
                    "address": None,
                    "city": city_slug.replace("-", " ").title(),
                    "state": None,
                    "country": None,
                    "lat": None,
                    "lon": None,
                },
                "organizer": None,
                "rsvp_count": 0,
                "is_paid": None,
                "fee": None,
                "image_url": None,
                "booking_url": booking_by_id.get(source_event_id),
                "date_text": date_text,
            }
        )
        if len(events) >= count:
            break

    return events, len(events)
