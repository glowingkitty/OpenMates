# backend/apps/events/providers/siegessaeule.py
#
# Siegessäule (siegessaeule.de) event search provider.
#
# Scrapes Berlin's primary LGBTQ+ community event calendar. Covers clubs,
# bars, culture (theater/exhibitions), mixed events, and nightlife.
#
# Key design decisions:
# - No API available — HTML scraping via Webshare residential proxy
# - Siegessaeule blocks datacenter IPs (403) but allows residential proxies
# - Same proxy pattern as Meetup: direct attempt first, proxy fallback
# - Berlin-only (Siegessäule is a Berlin-specific publication)
# - No server-side keyword search — client-side filtering after fetch
# - Categories from URL structure: clubs, bars, kultur, mix, sex
#
# Coverage: LGBTQ+ events in Berlin — unique data source not covered by
# Meetup, Luma, or RA. Includes drag shows, queer parties, pride events,
# bar nights, cultural exhibitions, and community gatherings.

import html as html_module
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.shared.testing.caching_http_transport import create_http_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.siegessaeule.de"
_TERMINE_URL = f"{_BASE_URL}/termine/"

# HTTP timeout (seconds).
_HTTP_TIMEOUT = 25.0

# Browser-like headers.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# Siegessäule event categories (from URL structure).
CATEGORIES = {"clubs", "bars", "kultur", "mix", "sex"}

# HTTP status codes indicating the site is rejecting direct requests.
_REJECTION_STATUS_CODES = {403, 429, 500, 502, 503, 504}

# Regex to extract event blocks from HTML.
# Each event is an <a> tag linking to /termine/category/slug/YYYY-MM-DD/HH:MM/
_EVENT_LINK_PATTERN = re.compile(
    r'<a[^>]*href="(/termine/(clubs|bars|kultur|mix|sex)/([^/]+)/(\d{4}-\d{2}-\d{2})/(\d{2}:\d{2})/)"[^>]*>(.*?)</a>',
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_page(
    url: str,
    proxy_url: Optional[str] = None,
) -> str:
    """
    Fetch a Siegessäule page. Tries direct first, falls back to proxy.

    Siegessäule blocks datacenter IPs with 403 but allows residential proxies.
    """
    # Try direct first (works from residential IPs)
    try:
        async with create_http_client(
            "siegessaeule", timeout=_HTTP_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(url, headers=_HEADERS)
            if response.status_code not in _REJECTION_STATUS_CODES:
                response.raise_for_status()
                return response.text
            logger.debug(
                "[siegessaeule] Direct request rejected (%d) — retrying via proxy",
                response.status_code,
            )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.debug("[siegessaeule] Direct request failed (%s) — retrying via proxy", exc)

    # Retry via Webshare residential proxy
    if not proxy_url:
        raise ValueError(
            "Siegessäule blocked direct request and no proxy configured. "
            "Webshare residential proxy is required for datacenter servers."
        )

    async with httpx.AsyncClient(
        proxy=proxy_url,
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = await client.get(url, headers=_HEADERS)
        response.raise_for_status()
        return response.text


def _strip_tags(value: str) -> str:
    """Strip HTML tags and decode entities."""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html_module.unescape(without_tags)).strip()


def _parse_events(page_html: str) -> List[Dict[str, Any]]:
    """
    Parse event listings from Siegessäule's HTML.

    Each event is an <a> block containing:
    - URL with category, slug, date, and time
    - <h4> tag with event title
    - Description text
    - Venue name (last text segment before closing tag)
    - Optional <img> with CDN image URL
    """
    events: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for match in _EVENT_LINK_PATTERN.finditer(page_html):
        href = match.group(1)
        category = match.group(2)
        slug = match.group(3)
        date_str = match.group(4)
        time_str = match.group(5)
        inner_html = match.group(6)

        full_url = f"{_BASE_URL}{href}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Extract title from <h4>
        title_match = re.search(r"<h4[^>]*>(.*?)</h4>", inner_html, re.DOTALL)
        title = _strip_tags(title_match.group(1)) if title_match else ""
        if not title or len(title) < 2:
            continue

        # Extract all text segments (split by tags, filter empties)
        text_segments = [
            s.strip() for s in re.split(r"<[^>]+>", inner_html)
            if s.strip() and s.strip() != title
        ]

        # First segment is usually the date string (e.g., "28. März 2026, 16:00")
        # Last non-empty segment is usually the venue name
        description = ""
        venue_name = ""

        # Filter out the date string from segments
        non_date_segments = [
            s for s in text_segments
            if not re.match(r"\d{1,2}\.\s+\w+\s+\d{4}", s)
        ]

        if non_date_segments:
            venue_name = non_date_segments[-1]
            if len(non_date_segments) > 1:
                description = " ".join(non_date_segments[:-1])

        # Extract image URL
        img_match = re.search(
            r'src="(https://cdn\.siegessaeule\.de/[^"]+)"', inner_html,
        )
        image_url = img_match.group(1) if img_match else None

        date_start = f"{date_str}T{time_str}:00"

        events.append({
            "id": slug,
            "provider": "siegessaeule",
            "title": title,
            "description": description,
            "url": full_url,
            "date_start": date_start,
            "date_end": None,
            "timezone": "Europe/Berlin",
            "event_type": "PHYSICAL",
            "venue": {
                "name": venue_name,
                "address": "",
                "city": "Berlin",
                "state": None,
                "country": "DE",
                "lat": None,
                "lon": None,
            },
            "organizer": None,
            "rsvp_count": None,
            "is_paid": None,
            "fee": None,
            "image_url": image_url,
            "category": category,
        })

    return events


# ---------------------------------------------------------------------------
# Detail page enrichment (iCal parsing)
# ---------------------------------------------------------------------------

# Concurrency limit for detail page fetches.
_DETAIL_FETCH_CONCURRENCY = 4

# Polite delay between detail page fetches (seconds).
_DETAIL_FETCH_DELAY = 0.3


def _parse_ical_from_html(detail_html: str) -> Dict[str, Any]:
    """
    Extract structured data from the iCal data URL embedded in event detail pages.

    Siegessäule embeds an iCal link like:
        data:text/calendar;charset=utf-8,...LOCATION:SO36\\, Oranienstrasse 190\\, ...
        GEO:52.500392;13.422102
        DESCRIPTION:...

    Returns dict with: address, lat, lon, full_description.
    """
    result: Dict[str, Any] = {}

    # Find the iCal data URL (charset can be utf-8 or utf8)
    ical_match = re.search(
        r'data:text/calendar;charset=utf-?8[^"\'>\s]+',
        detail_html,
    )
    if not ical_match:
        return result

    from urllib.parse import unquote
    ical_text = unquote(ical_match.group(0))

    # Extract GEO (lat/lon)
    geo_match = re.search(r'GEO:([\d.]+);([\d.]+)', ical_text)
    if geo_match:
        try:
            result["lat"] = float(geo_match.group(1))
            result["lon"] = float(geo_match.group(2))
        except (ValueError, TypeError):
            pass

    # Extract LOCATION (full venue address)
    loc_match = re.search(r'LOCATION:(.+?)(?:\r?\n[A-Z]|\Z)', ical_text, re.DOTALL)
    if loc_match:
        location_str = loc_match.group(1).strip()
        # iCal escapes commas with backslash
        location_str = location_str.replace("\\,", ",").replace("\\n", " ").strip()
        result["address"] = location_str

    # Extract DESCRIPTION (full event description)
    desc_match = re.search(r'DESCRIPTION:(.+?)(?:\r?\n[A-Z]|\Z)', ical_text, re.DOTALL)
    if desc_match:
        desc = desc_match.group(1).strip()
        desc = desc.replace("\\,", ",").replace("\\n", "\n").replace("\\;", ";").strip()
        if len(desc) > _MAX_DESCRIPTION_CHARS:
            desc = desc[:_MAX_DESCRIPTION_CHARS] + "..."
        result["full_description"] = desc

    return result


# Maximum description length (characters) — also used for iCal parsing.
_MAX_DESCRIPTION_CHARS = 2000


async def _enrich_events_with_details(
    events: List[Dict[str, Any]],
    proxy_url: Optional[str],
) -> None:
    """
    Fetch detail pages for events and enrich with venue address, lat/lon, description.

    Modifies events in-place. Only fetches details for events that are missing
    venue address or lat/lon (avoids redundant requests).
    """
    import asyncio

    events_needing_details = [
        e for e in events
        if not (e.get("venue") or {}).get("lat")
    ]
    if not events_needing_details:
        return

    semaphore = asyncio.Semaphore(_DETAIL_FETCH_CONCURRENCY)

    async def fetch_detail(event: Dict[str, Any]) -> None:
        url = event.get("url", "")
        if not url:
            return

        async with semaphore:
            try:
                detail_html = await _fetch_page(url, proxy_url=proxy_url)
                ical_data = _parse_ical_from_html(detail_html)

                # Enrich venue with address and coordinates
                venue = event.get("venue") or {}
                if ical_data.get("address") and not venue.get("address"):
                    venue["address"] = ical_data["address"]
                if ical_data.get("lat"):
                    venue["lat"] = ical_data["lat"]
                if ical_data.get("lon"):
                    venue["lon"] = ical_data["lon"]
                event["venue"] = venue

                # Enrich description
                if ical_data.get("full_description") and len(event.get("description", "")) < 50:
                    event["description"] = ical_data["full_description"]

            except Exception as exc:
                logger.debug(
                    "[siegessaeule] Detail fetch failed for %s: %s", url, exc,
                )

            # Polite delay
            await asyncio.sleep(_DETAIL_FETCH_DELAY)

    await asyncio.gather(*[fetch_detail(e) for e in events_needing_details])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_events_async(
    *,
    city: str,
    query: str = "",
    count: int = 10,
    start_date: Optional[str] = None,
    proxy_url: Optional[str] = None,
    secrets_manager: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Search for LGBTQ+ events on Siegessäule.

    Berlin-only. Fetches the /termine/ listing page via Webshare proxy.
    Keyword filtering is applied client-side after fetching.

    Args:
        city:            City name (must contain "berlin" — only Berlin is supported).
        query:           Optional keyword filter (applied client-side).
        count:           Maximum number of events to return (default 10).
        start_date:      ISO 8601 date string — fetches events for this date.
                         Defaults to today if not provided.
        proxy_url:       Webshare rotating proxy URL (required for datacenter servers).
        secrets_manager: Not used directly, accepted for interface compatibility.

    Returns:
        Tuple of (events_list, total_available).

    Raises:
        ValueError: If the city is not Berlin or proxy is unavailable.
    """
    if "berlin" not in city.lower():
        raise ValueError(
            "Siegessäule is a Berlin-only publication. "
            "It does not cover events outside Berlin."
        )

    # Build URL with date parameter
    url = _TERMINE_URL
    if start_date:
        try:
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            url = f"{_TERMINE_URL}?date={dt.strftime('%Y-%m-%d')}"
        except (ValueError, TypeError):
            logger.debug("[siegessaeule] Could not parse start_date %r", start_date)

    logger.debug("[siegessaeule] Fetching events: url=%s query=%r", url, query)

    page_html = await _fetch_page(url, proxy_url=proxy_url)
    events = _parse_events(page_html)
    total_available = len(events)

    # Client-side keyword filtering
    if query:
        query_tokens = query.lower().split()
        events = [
            e for e in events
            if any(
                token in (
                    e.get("title", "") + " " +
                    e.get("description", "") + " " +
                    e.get("category", "")
                ).lower()
                for token in query_tokens
            )
        ]

    # Sort by date ascending; None dates to end.
    events.sort(key=lambda e: (e.get("date_start") or "9999"))

    events = events[:count]

    # Enrich top results with detail page data (venue address, lat/lon, description).
    # Only fetches details for the final result set to avoid unnecessary requests.
    if events and proxy_url:
        await _enrich_events_with_details(events, proxy_url=proxy_url)

    logger.info(
        "[siegessaeule] Search complete: %d events (total=%d) query=%r",
        len(events),
        total_available,
        query,
    )

    return events, total_available
