# backend/apps/events/providers/siegessaeule.py
#
# Siegessäule (siegessaeule.de) event search provider.
#
# Uses Siegessäule's internal GraphQL API (Sapper/Apollo) for structured
# event data. The GraphQL endpoint requires a residential proxy — Siegessäule
# blocks datacenter IPs.
#
# Key design decisions:
# - GraphQL API at siegessaeule.de/graphql/ (trailing slash required)
# - No authentication needed — public API
# - Requires Webshare residential proxy (datacenter IPs get 403)
# - Single query returns all data: title, dates, venue with lat/lng, tags,
#   images, descriptions — no detail page fetching needed
# - Berlin-only (Siegessäule is a Berlin-specific publication)
# - Client-side keyword filtering (GraphQL supports section filter only)
#
# GraphQL structure:
#   homePage → eventIndexPage → eventsAndAdsForDate(date, days, section)
#   Returns union of [EventPage | EventSectionBannerAd] — filter on EventPage
#
# Coverage: LGBTQ+ events in Berlin — unique data source. Includes drag shows,
# queer parties, pride events, bar nights, culture, and community gatherings.
#
# Sections (categories): mix, kultur, bars, clubs, sex, festival, fetisch,
# open-air, livestreams

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.siegessaeule.de"
_GRAPHQL_URL = f"{_BASE_URL}/graphql/"  # Trailing slash required

# HTTP timeout (seconds).
_HTTP_TIMEOUT = 25.0

# Maximum description length (characters).
_MAX_DESCRIPTION_CHARS = 2000

# Headers for GraphQL requests.
_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.siegessaeule.de",
    "Referer": "https://www.siegessaeule.de/termine/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}

# GraphQL query for event listings.
_EVENTS_QUERY = """
{
  homePage {
    eventIndexPage {
      eventsAndAdsForDate(date: "%DATE%", days: %DAYS%%SECTION%) {
        date
        items {
          ... on EventPage {
            id
            title
            slug
            startDate
            startTime
            startsAt
            endsAt
            teaser
            info
            description
            tags
            siegessaeulePresents
            venue {
              title
              slug
              address
              location { lat lng }
              phone
              email
              categories { name slug }
            }
            section { title slug }
            image {
              title
              rendition(fill: {width: 480, height: 480}) { url }
            }
            categories { name slug }
          }
        }
      }
    }
  }
}
"""

# Map query keywords to Siegessäule section slugs for server-side filtering.
_KEYWORD_TO_SECTION: Dict[str, str] = {
    "club": "clubs",
    "clubs": "clubs",
    "techno": "clubs",
    "rave": "clubs",
    "bar": "bars",
    "bars": "bars",
    "kultur": "kultur",
    "culture": "kultur",
    "theater": "kultur",
    "theatre": "kultur",
    "exhibition": "kultur",
    "art": "kultur",
    "sex": "sex",
    "fetish": "fetisch",
    "fetisch": "fetisch",
    "festival": "festival",
    "open air": "open-air",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_query(date_str: str, days: int, section: Optional[str] = None) -> str:
    """Build the GraphQL query string with parameters interpolated."""
    query = _EVENTS_QUERY.replace("%DATE%", date_str)
    query = query.replace("%DAYS%", str(days))
    if section:
        query = query.replace("%SECTION%", f', section: "{section}"')
    else:
        query = query.replace("%SECTION%", "")
    return query


def _strip_html(text: str) -> str:
    """Strip HTML tags from a string."""
    clean = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean).strip()


def _normalize_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a Siegessäule GraphQL EventPage into the standard EventResult format.
    """
    # Venue
    venue_raw = raw.get("venue") or {}
    location = venue_raw.get("location") or {}
    venue = {
        "name": venue_raw.get("title", ""),
        "address": venue_raw.get("address", ""),
        "city": "Berlin",
        "state": None,
        "country": "DE",
        "lat": location.get("lat"),
        "lon": location.get("lng"),
    }

    # Description — combine teaser + info + full description
    teaser = raw.get("teaser") or ""
    info = raw.get("info") or ""
    full_desc = raw.get("description") or ""
    if full_desc:
        full_desc = _strip_html(full_desc)

    description_parts = []
    if teaser:
        description_parts.append(teaser)
    if info:
        description_parts.append(info)
    if full_desc and full_desc != teaser:
        description_parts.append(full_desc)
    description = "\n".join(description_parts)
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[:_MAX_DESCRIPTION_CHARS] + "..."

    # Section / category
    section = raw.get("section") or {}
    category = section.get("slug") or ""

    # Tags
    tags = raw.get("tags") or []

    # Image
    image_data = raw.get("image") or {}
    rendition = image_data.get("rendition") or {}
    image_url = rendition.get("url")
    if image_url and not image_url.startswith("http"):
        image_url = f"https://cdn.siegessaeule.de{image_url}"

    # Date
    date_start = raw.get("startsAt")
    date_end = raw.get("endsAt")

    # Build URL from section + slug + date
    slug = raw.get("slug", "")
    start_date = raw.get("startDate", "")
    start_time = raw.get("startTime", "")
    url = f"{_BASE_URL}/termine/{category}/{slug}/{start_date}/{start_time[:5]}/" if slug and start_date and start_time else ""

    return {
        "id": raw.get("id", ""),
        "provider": "siegessaeule",
        "title": raw.get("title", ""),
        "description": description,
        "url": url,
        "date_start": date_start,
        "date_end": date_end,
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": venue,
        "organizer": None,
        "rsvp_count": None,
        "is_paid": None,
        "fee": None,
        "image_url": image_url,
        "category": category,
        "tags": tags if tags else None,
        "siegessaeule_presents": raw.get("siegessaeulePresents", False),
    }


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
    Search for LGBTQ+ events on Siegessäule via GraphQL.

    Berlin-only. Uses the internal GraphQL API with Webshare proxy.

    Args:
        city:            City name (must contain "berlin" — only Berlin is supported).
        query:           Optional keyword filter. Some keywords map to sections for
                         server-side filtering (e.g., "clubs", "kultur"). Others are
                         applied client-side.
        count:           Maximum number of events to return (default 10).
        start_date:      ISO 8601 date string. Defaults to today.
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

    if not proxy_url:
        raise ValueError(
            "Siegessäule GraphQL requires a proxy (datacenter IPs are blocked). "
            "Webshare rotating proxy URL is required."
        )

    # Parse start date or default to today
    now = datetime.now(timezone.utc)
    if start_date:
        try:
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            date_str = now.strftime("%Y-%m-%d")
    else:
        date_str = now.strftime("%Y-%m-%d")

    # Map query keywords to section for server-side filtering
    section = None
    if query:
        for keyword, sec in _KEYWORD_TO_SECTION.items():
            if keyword in query.lower():
                section = sec
                break

    # Request 7 days of events (Siegessäule shows daily listings)
    days = 7
    graphql_query = _build_query(date_str, days, section)

    logger.debug(
        "[siegessaeule] GraphQL query: date=%s days=%d section=%r query=%r",
        date_str, days, section, query,
    )

    async with httpx.AsyncClient(
        proxy=proxy_url,
        timeout=_HTTP_TIMEOUT,
    ) as client:
        response = await client.post(
            _GRAPHQL_URL,
            json={"query": graphql_query},
            headers=_HEADERS,
        )
        response.raise_for_status()
        data = response.json()

    # Extract events from the nested response structure
    errors = data.get("errors")
    if errors:
        error_msg = errors[0].get("message", "Unknown GraphQL error")
        raise ValueError(f"Siegessäule GraphQL error: {error_msg}")

    result = (
        data.get("data", {})
        .get("homePage", {})
        .get("eventIndexPage", {})
        .get("eventsAndAdsForDate")
    )

    events: List[Dict[str, Any]] = []

    # eventsAndAdsForDate returns a single {date, items} dict or a list of them
    if isinstance(result, dict):
        date_groups = [result]
    elif isinstance(result, list):
        date_groups = result
    else:
        date_groups = []

    for group in date_groups:
        if isinstance(group, str):
            # Skip string items (e.g., date strings in unexpected format)
            continue
        items = group.get("items") or []
        for item in items:
            # Filter out ads (union type — only EventPage has 'title')
            if not isinstance(item, dict) or not item.get("title"):
                continue
            events.append(_normalize_event(item))

    total_available = len(events)

    # Client-side keyword filtering (for queries that don't map to sections).
    # Uses word-boundary matching to avoid substring false positives (e.g.
    # "ai" matching "entertainment", "again", "paid").
    if query and not section:
        token_patterns = [
            re.compile(r"\b" + re.escape(token) + r"\b", re.IGNORECASE)
            for token in query.lower().split()
        ]
        events = [
            e for e in events
            if any(
                pattern.search(
                    e.get("title", "") + " " +
                    e.get("description", "") + " " +
                    " ".join(e.get("tags") or [])
                )
                for pattern in token_patterns
            )
        ]

    # Sort by date ascending; None dates to end.
    events.sort(key=lambda e: (e.get("date_start") or "9999"))

    events = events[:count]

    logger.info(
        "[siegessaeule] Search complete: %d events (total=%d) query=%r section=%r",
        len(events),
        total_available,
        query,
        section,
    )

    return events, total_available
