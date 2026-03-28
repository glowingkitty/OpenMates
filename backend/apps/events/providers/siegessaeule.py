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

import httpx

from backend.shared.providers.firecrawl.firecrawl_scrape import scrape_url
from backend.shared.testing.caching_http_transport import create_http_client

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

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
    secrets_manager: Optional["SecretsManager"] = None,
) -> str:
    """
    Fetch a Siegessäule page. Tries direct httpx first, falls back to Firecrawl.

    Args:
        url:             The URL to fetch.
        secrets_manager: Required for Firecrawl fallback.

    Returns:
        HTML content of the page.
    """
    # Try direct first (cheapest)
    try:
        async with create_http_client(
            "siegessaeule", timeout=_HTTP_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(url, headers=_HEADERS)
            if response.status_code < 400:
                return response.text
            logger.debug(
                "[siegessaeule] Direct request rejected (%d) — trying Firecrawl",
                response.status_code,
            )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.debug("[siegessaeule] Direct request failed (%s) — trying Firecrawl", exc)

    # Fallback to Firecrawl
    if not secrets_manager:
        raise ValueError(
            "Siegessäule blocked direct request and no secrets_manager for Firecrawl fallback"
        )

    result = await scrape_url(
        url=url,
        secrets_manager=secrets_manager,
        formats=["html", "markdown"],
        only_main_content=False,
        sanitize_output=False,
    )

    if result.get("error"):
        raise ValueError(f"Firecrawl scrape failed for {url}: {result['error']}")

    data = result.get("data", {})
    html = data.get("html") or data.get("markdown") or ""
    if not html:
        raise ValueError(f"Firecrawl returned empty content for {url}")

    return html


def _parse_events(content: str) -> List[Dict[str, Any]]:
    """
    Parse event listings from Siegessäule's markdown (via Firecrawl).

    Markdown event blocks follow this pattern:
        [28\\. März 2026, 22:00\\
        \\
        **Event Title**\\
        \\
        Optional description\\
        \\
        Venue Name](https://www.siegessaeule.de/termine/category/slug/YYYY-MM-DD/HH:MM/)

    The URL contains the category, date, and time in a structured format.
    """
    events: List[Dict[str, Any]] = []
    seen_urls: set = set()

    # Match event links: [...](https://www.siegessaeule.de/termine/category/slug/date/time/)
    # The link text contains date, title (in **bold**), optional description, and venue.
    event_pattern = re.compile(
        r'\[([^\]]*?\*\*[^\]]+?\*\*[^\]]*?)\]'  # Link text containing **bold title**
        r'\((https://www\.siegessaeule\.de/termine/'
        r'(clubs|bars|kultur|mix|sex)/'  # Category
        r'[^/]+/'                         # Slug
        r'(\d{4}-\d{2}-\d{2})/'          # Date
        r'(\d{2}:\d{2})/)\)',            # Time
        re.DOTALL,
    )

    for match in event_pattern.finditer(content):
        link_text = match.group(1)
        full_url = match.group(2)
        category = match.group(3)
        date_str = match.group(4)
        time_str = match.group(5)

        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Extract title from **bold** text
        title_match = re.search(r'\*\*(.+?)\*\*', link_text, re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""
        if not title:
            continue

        # Clean escaped characters from title
        title = title.replace("\\", "").strip()

        # Extract description — text between title and venue (after the bold title)
        description = ""
        after_title = link_text.split("**")[-1] if "**" in link_text else ""
        # Clean up markdown escape sequences
        after_parts = re.sub(r'\\+\n?', ' ', after_title).strip()
        after_parts = re.sub(r'\s+', ' ', after_parts).strip()
        if after_parts:
            # Last part is usually venue name, rest is description
            parts = [p.strip() for p in after_parts.split(',') if p.strip()]
            if len(parts) > 1:
                description = ', '.join(parts[:-1])
                venue_name = parts[-1]
            elif parts:
                venue_name = parts[0]
            else:
                venue_name = ""
        else:
            venue_name = ""

        # Extract image URL if present
        image_match = re.search(r'!\[\]\((https://cdn\.siegessaeule\.de/[^)]+)\)', link_text)
        image_url = image_match.group(1) if image_match else None

        date_start = f"{date_str}T{time_str}:00"

        events.append({
            "id": full_url.rstrip("/").split("/")[-3],
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
# Public API
# ---------------------------------------------------------------------------

async def search_events_async(
    *,
    city: str,
    query: str = "",
    count: int = 10,
    start_date: Optional[str] = None,
    proxy_url: Optional[str] = None,
    secrets_manager: Optional["SecretsManager"] = None,
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

    content = await _fetch_page(url, secrets_manager=secrets_manager)
    events = _parse_events(content)
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
