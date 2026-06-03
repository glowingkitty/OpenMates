# backend/apps/events/providers/eventbrite.py
#
# Eventbrite event search provider.
#
# Uses Eventbrite's web app destination search endpoint. Eventbrite shut down
# its official public Event Search API in 2019, so this provider follows the
# current browser request contract: anonymous POST with a matching CSRF cookie
# and X-CSRFToken header. Results are enriched with full event descriptions by
# parsing each returned event page's embedded structuredContent payload.
#
# Proxy policy: direct first, retry once via Webshare only on access/network
# failures. Zero results and unavailable event pages do not trigger proxy use.
#
# Tests: scripts/api_tests/test_eventbrite_api.py

import asyncio
import html
import json
import logging
import re
import secrets
import time
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.shared.testing.caching_http_transport import create_http_client

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.eventbrite.com"
_SEARCH_ENDPOINT = f"{_BASE_URL}/api/v3/destination/search/"
_MAX_RESULTS = 10
_HTTP_TIMEOUT = 20.0
_HTML_TIMEOUT = 12.0
_HTML_CONCURRENCY = 3
_MAX_DESCRIPTION_CHARS = 8000
_REJECTION_STATUS_CODES = {403, 429, 500, 502, 503, 504}

_JSON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": _BASE_URL,
    "Referer": f"{_BASE_URL}/d/local/events/",
}

_HTML_HEADERS = {
    "User-Agent": _JSON_HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Verified Eventbrite locality ID for Berlin. Unknown cities fall back to a
# location-qualified global query so Eventbrite still searches worldwide.
CITY_PLACE_IDS: Dict[str, str] = {
    "berlin": "101748799",
    "berlin-germany": "101748799",
    "germany-berlin": "101748799",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


async def search_events_async(
    *,
    location: str,
    query: Optional[str] = None,
    count: int = _MAX_RESULTS,
    proxy_url: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Search Eventbrite events and enrich every returned event with description."""
    count = max(1, min(count, _MAX_RESULTS))
    location = location or ""
    place_id = _resolve_place_id(location)
    search_query = (query or "").strip()
    if not place_id and location:
        search_query = f"{search_query} {location}".strip()

    started = time.time()
    response = await _post_search(
        query=search_query,
        place_id=place_id,
        count=count,
        proxy_url=proxy_url,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Eventbrite search returned HTTP {response.status_code} "
            f"after {time.time() - started:.2f}s. Body: {response.text[:300]}"
        )

    data = response.json()
    events_payload = data.get("events") or {}
    raw_events = list((events_payload.get("results") or [])[:count])
    pagination = events_payload.get("pagination") or {}
    total_available = int(pagination.get("object_count") or len(raw_events))

    events = [_normalize_event(raw) for raw in raw_events]
    descriptions = await _fetch_descriptions_parallel(events, proxy_url=proxy_url)
    for event, description in zip(events, descriptions):
        if description:
            event["description"] = description

    logger.info(
        "Eventbrite search: location=%r place_id=%r query=%r -> %d events total=%d",
        location,
        place_id,
        query,
        len(events),
        total_available,
    )
    return events, total_available


def _resolve_place_id(location: str) -> Optional[str]:
    normalized = re.sub(r"[^a-z0-9]+", "-", location.lower()).strip("-")
    candidates = [normalized]
    if "-" in normalized:
        parts = [part for part in normalized.split("-") if part]
        candidates.extend(parts)
        if len(parts) >= 2:
            candidates.append(f"{parts[0]}-{parts[-1]}")
            candidates.append(f"{parts[-1]}-{parts[0]}")
    for candidate in candidates:
        if candidate in CITY_PLACE_IDS:
            return CITY_PLACE_IDS[candidate]
    return None


async def _post_search(
    *,
    query: str,
    place_id: Optional[str],
    count: int,
    proxy_url: Optional[str],
) -> httpx.Response:
    event_search: Dict[str, Any] = {
        "dates": "current_future",
        "dedup": True,
        "page_size": count,
        "q": query,
        "aggs": ["places_borough", "places_neighborhood"],
        "page": 1,
    }
    if place_id:
        event_search["places"] = [place_id]

    payload = {
        "event_search": event_search,
        "expand.destination_event": [
            "primary_venue",
            "image",
            "ticket_availability",
            "saves",
            "event_sales_status",
            "primary_organizer",
            "primary_organizer.image",
            "public_collections",
        ],
        "browse_surface": "search",
    }
    headers, cookies = _csrf_headers()
    return await _request_with_proxy_fallback(
        method="POST",
        url=_SEARCH_ENDPOINT,
        headers=headers,
        cookies=cookies,
        json_body=payload,
        proxy_url=proxy_url,
        timeout=_HTTP_TIMEOUT,
        label="Eventbrite search",
    )


def _csrf_headers() -> Tuple[Dict[str, str], Dict[str, str]]:
    token = secrets.token_hex(16)
    headers = dict(_JSON_HEADERS)
    headers["X-CSRFToken"] = token
    return headers, {"csrftoken": token}


def _normalize_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    venue_raw = raw.get("primary_venue") or {}
    address = venue_raw.get("address") or {}
    ticket_availability = raw.get("ticket_availability") or {}
    organizer_raw = raw.get("primary_organizer") or {}
    image = raw.get("image") or {}

    min_price = ticket_availability.get("minimum_ticket_price") or {}
    max_price = ticket_availability.get("maximum_ticket_price") or {}
    is_free = bool(ticket_availability.get("is_free"))
    fee = None
    if min_price.get("display") or max_price.get("display"):
        fee = {
            "min": min_price.get("major_value") or min_price.get("value"),
            "max": max_price.get("major_value") or max_price.get("value"),
            "currency": min_price.get("currency") or max_price.get("currency"),
            "display": _format_price_display(min_price, max_price),
        }

    description = raw.get("summary") or ""
    return {
        "id": raw.get("id") or raw.get("eventbrite_event_id"),
        "provider": "eventbrite",
        "title": raw.get("name") or "",
        "description": description,
        "url": raw.get("url") or raw.get("parent_url") or "",
        "date_start": _combine_date_time(raw.get("start_date"), raw.get("start_time")),
        "date_end": _combine_date_time(raw.get("end_date"), raw.get("end_time")),
        "timezone": raw.get("timezone"),
        "event_type": "ONLINE" if raw.get("is_online_event") else "PHYSICAL",
        "venue": {
            "name": venue_raw.get("name"),
            "address": address.get("localized_address_display") or address.get("address_1"),
            "city": address.get("city"),
            "state": address.get("region"),
            "country": address.get("country"),
            "lat": _to_float(address.get("latitude")),
            "lon": _to_float(address.get("longitude")),
        } if venue_raw or address else None,
        "organizer": {
            "name": organizer_raw.get("name"),
            "url": organizer_raw.get("url"),
            "summary": organizer_raw.get("summary"),
            "followers": organizer_raw.get("num_followers"),
        } if organizer_raw else None,
        "is_paid": not is_free,
        "fee": fee,
        "image_url": image.get("url") or (image.get("original") or {}).get("url"),
        "ticket_info": {
            "tickets_by": raw.get("tickets_by"),
            "tickets_url": raw.get("tickets_url"),
            "has_available_tickets": ticket_availability.get("has_available_tickets"),
            "is_sold_out": ticket_availability.get("is_sold_out"),
            "sales_status": (raw.get("event_sales_status") or {}).get("sales_status"),
        },
        "tags": [tag.get("display_name") for tag in raw.get("tags") or [] if tag.get("display_name")],
        "eventbrite_event_id": raw.get("eventbrite_event_id") or raw.get("id"),
    }


def _combine_date_time(date_value: Optional[str], time_value: Optional[str]) -> Optional[str]:
    if not date_value:
        return None
    if not time_value:
        return date_value
    return f"{date_value}T{time_value}:00"


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _format_price_display(min_price: Dict[str, Any], max_price: Dict[str, Any]) -> Optional[str]:
    min_display = min_price.get("display")
    max_display = max_price.get("display")
    if min_display and max_display and min_display != max_display:
        return f"{min_display} - {max_display}"
    return min_display or max_display


async def _fetch_descriptions_parallel(
    events: List[Dict[str, Any]],
    proxy_url: Optional[str],
) -> List[Optional[str]]:
    semaphore = asyncio.Semaphore(_HTML_CONCURRENCY)

    async def fetch(event: Dict[str, Any]) -> Optional[str]:
        async with semaphore:
            return await _fetch_description(event.get("url"), proxy_url=proxy_url)

    return list(await asyncio.gather(*[fetch(event) for event in events]))


async def _fetch_description(url: Optional[str], proxy_url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        response = await _request_with_proxy_fallback(
            method="GET",
            url=url,
            headers=_HTML_HEADERS,
            cookies=None,
            json_body=None,
            proxy_url=proxy_url,
            timeout=_HTML_TIMEOUT,
            label="Eventbrite event page",
        )
    except httpx.RequestError as exc:
        logger.debug("Eventbrite description fetch failed for %s: %s", url, exc)
        return None

    if response.status_code != 200:
        logger.debug("Eventbrite description page returned HTTP %d for %s", response.status_code, url)
        return None
    description = _extract_structured_description(response.text)
    if description and len(description) > _MAX_DESCRIPTION_CHARS:
        return description[:_MAX_DESCRIPTION_CHARS] + "..."
    return description


def _extract_structured_description(page_html: str) -> Optional[str]:
    match = re.search(
        r'"structuredContent"\s*:\s*\{\s*"modules"\s*:\s*\[(.*?)\]\s*\}',
        page_html,
        re.S,
    )
    if not match:
        return None

    text_fragments: List[str] = []
    for raw in re.findall(r'"text"\s*:\s*"((?:\\.|[^"\\])*)"', match.group(1), re.S):
        try:
            decoded = json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            decoded = raw
        text = _strip_tags(decoded)
        if text:
            text_fragments.append(text)
    description = "\n".join(text_fragments).strip()
    return description or None


def _strip_tags(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(html.unescape(value))
    return parser.get_text()


async def _request_with_proxy_fallback(
    *,
    method: str,
    url: str,
    headers: Dict[str, str],
    cookies: Optional[Dict[str, str]],
    json_body: Optional[Dict[str, Any]],
    proxy_url: Optional[str],
    timeout: float,
    label: str,
) -> httpx.Response:
    direct_error: Optional[Exception] = None
    direct_response: Optional[httpx.Response] = None
    try:
        async with create_http_client(
            "eventbrite",
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            direct_response = await client.request(
                method,
                url,
                headers=headers,
                cookies=cookies,
                json=json_body,
            )
    except httpx.RequestError as exc:
        direct_error = exc
        logger.debug("%s direct request failed: %s", label, exc)

    if direct_response is not None and direct_response.status_code not in _REJECTION_STATUS_CODES:
        return direct_response

    if not proxy_url:
        if direct_error:
            raise direct_error
        return direct_response  # type: ignore[return-value]

    try:
        async with create_http_client(
            "eventbrite",
            proxy=proxy_url,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            return await client.request(
                method,
                url,
                headers=headers,
                cookies=cookies,
                json=json_body,
            )
    except httpx.RequestError as exc:
        logger.warning("%s proxy retry failed: %s", label, exc)
        if direct_error:
            raise exc
        return direct_response  # type: ignore[return-value]
