# backend/apps/events/providers/siegessaeule.py
#
# Siegessäule (siegessaeule.de) event search provider.
#
# Scrapes Berlin's primary LGBTQ+ community event calendar. Covers clubs,
# bars, culture (theater/exhibitions), mixed events, and nightlife.
#
# Key design decisions:
# - No API — simple server-rendered HTML, scraped via direct httpx
# - Berlin-only (Siegessäule is a Berlin-specific publication)
# - Date-based URL pattern: /termine/?date=YYYY-MM-DD
# - No keyword search on server side — client-side filtering after fetch
# - Categories in URLs: clubs, bars, kultur, mix, sex
#
# Coverage: LGBTQ+ events in Berlin — unique data source not covered by
# Meetup, Luma, or RA. Includes drag shows, queer parties, pride events,
# bar nights, cultural exhibitions, and community gatherings.

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

from backend.shared.testing.caching_http_transport import create_http_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.siegessaeule.de"
_TERMINE_URL = f"{_BASE_URL}/termine/"

# HTTP timeout (seconds).
_HTTP_TIMEOUT = 20.0

# Maximum description length (characters).
_MAX_DESCRIPTION_CHARS = 1000

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_page(
    url: str,
    proxy_url: Optional[str] = None,
) -> str:
    """Fetch a Siegessäule page. Direct request only (no anti-bot detected)."""
    try:
        async with create_http_client(
            "siegessaeule", timeout=_HTTP_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(url, headers=_HEADERS)
            response.raise_for_status()
            return response.text
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        if not proxy_url:
            raise
        logger.debug("[siegessaeule] Direct request failed (%s) — retrying via proxy", exc)

    # Fallback to proxy
    async with httpx.AsyncClient(
        proxy=proxy_url,
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = await client.get(url, headers=_HEADERS)
        response.raise_for_status()
        return response.text


def _parse_events(html: str) -> List[Dict[str, Any]]:
    """
    Parse event listings from Siegessäule's /termine/ HTML page.

    The page structure uses event blocks with links to individual event pages.
    Each block contains: event title, time, venue name, and category.
    """
    events: List[Dict[str, Any]] = []
    seen_urls: set = set()

    # Look for event links — Siegessäule uses /termine/{category}/{slug}/{date}/{time}/
    # pattern for event detail pages.
    event_link_pattern = re.compile(
        r'<a[^>]*href="(/termine/(?:clubs|bars|kultur|mix|sex)/[^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    for match in event_link_pattern.finditer(html):
        href = match.group(1)
        inner = match.group(2)

        full_url = urljoin(_BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Extract title (strip HTML tags)
        title = re.sub(r"<[^>]+>", "", inner).strip()
        if not title or len(title) < 2:
            continue

        # Extract category from URL
        category_match = re.search(r"/termine/(clubs|bars|kultur|mix|sex)/", href)
        category = category_match.group(1) if category_match else ""

        # Extract date and time from URL if present
        # Pattern: /termine/category/slug/YYYY-MM-DD/HH:MM/
        date_match = re.search(r"/(\d{4}-\d{2}-\d{2})/(\d{2}:\d{2})/", href)
        date_start = None
        time_str = ""
        if date_match:
            date_str = date_match.group(1)
            time_str = date_match.group(2)
            date_start = f"{date_str}T{time_str}:00"

        events.append({
            "id": href.strip("/").split("/")[-3] if "/" in href else "",
            "provider": "siegessaeule",
            "title": title,
            "description": f"Category: {category}" if category else "",
            "url": full_url,
            "date_start": date_start,
            "date_end": None,
            "timezone": "Europe/Berlin",
            "event_type": "PHYSICAL",
            "venue": {
                "name": "",
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
            "image_url": None,
            "category": category,
        })

    return events


def _try_extract_venue_from_context(html: str, event_url: str) -> Optional[str]:
    """
    Try to extract venue name from the HTML context near an event link.

    Siegessäule sometimes shows venue names near event links in the listing.
    """
    # Find the event URL in HTML and look at surrounding text
    escaped_url = re.escape(event_url.replace(_BASE_URL, ""))
    context_match = re.search(
        rf'(.{{0,200}}){escaped_url}(.{{0,200}})',
        html,
        re.DOTALL,
    )
    if not context_match:
        return None

    context = context_match.group(1) + context_match.group(2)
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", " ", context).strip()
    # Look for venue-like text (often after "@" or "im" or "at")
    venue_match = re.search(r"(?:@|im|at|in)\s+([A-Z][^,\n]{3,40})", clean)
    if venue_match:
        return venue_match.group(1).strip()
    return None


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
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Search for LGBTQ+ events on Siegessäule.

    Berlin-only. Fetches the /termine/ listing page, optionally filtered by
    date. Keyword filtering is applied client-side after fetching.

    Args:
        city:       City name (must contain "berlin" — only Berlin is supported).
        query:      Optional keyword filter (applied client-side).
        count:      Maximum number of events to return (default 10).
        start_date: ISO 8601 date string — fetches events for this date.
                    Defaults to today if not provided.
        proxy_url:  Optional Webshare proxy URL for fallback.

    Returns:
        Tuple of (events_list, total_available).

    Raises:
        ValueError: If the city is not Berlin.
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
            # Parse ISO 8601 date to YYYY-MM-DD
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            url = f"{_TERMINE_URL}?date={dt.strftime('%Y-%m-%d')}"
        except (ValueError, TypeError):
            logger.debug("[siegessaeule] Could not parse start_date %r", start_date)

    logger.debug("[siegessaeule] Fetching events: url=%s query=%r", url, query)

    html = await _fetch_page(url, proxy_url=proxy_url)
    events = _parse_events(html)

    # Try to enrich events with venue names from context
    for event in events:
        if not event.get("venue", {}).get("name"):
            venue_name = _try_extract_venue_from_context(html, event["url"])
            if venue_name:
                event["venue"]["name"] = venue_name

    total_available = len(events)

    # Client-side keyword filtering
    if query:
        query_lower = query.lower()
        query_tokens = query_lower.split()
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

    logger.info(
        "[siegessaeule] Search complete: %d events (total=%d) query=%r",
        len(events),
        total_available,
        query,
    )

    return events, total_available
