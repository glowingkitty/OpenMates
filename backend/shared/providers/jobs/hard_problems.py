"""Bounded first-party RSS adapter for Hard Problems' impact design job board.

The board publishes a country-filterable RSS feed. Matching listings are enriched
from bounded first-party role pages, retaining source and employer attribution.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timezone
from email.utils import parsedate_to_datetime
import re
import xml.etree.ElementTree as ET

import httpx

from backend.shared.providers.jobs.common import (
    ProviderError,
    clean_text,
    country_matches,
    safe_url,
    within_days,
)
from backend.shared.providers.jobs.models import JobListing
from backend.shared.providers.jobs.hard_problems_details import fetch_role_details


FEED_URL = "https://www.hardproblems.com/jobs/feed.xml"
COUNTRIES = {"DE": "Germany", "SE": "Sweden"}
MAX_RESULTS = 15
MAX_FEED_BYTES = 256_000
MAX_ITEMS = 100
MAX_QUERY_CHARS = 400
REQUEST_TIMEOUT = httpx.Timeout(8.0, connect=3.0)
_PARAGRAPH = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p>", re.IGNORECASE | re.DOTALL)
logger = logging.getLogger(__name__)
DETAIL_CONCURRENCY = 3


def _country_code(requested: str) -> str | None:
    return next((code for code in COUNTRIES if country_matches(requested, code)), None) if requested else None


def _location_note(description: str) -> str:
    """The feed's final paragraph is its location/work-style note."""
    paragraphs = _PARAGRAPH.findall(description)
    return clean_text(paragraphs[-1], max_length=250) if paragraphs else ""


def _country_location(note: str, country_name: str) -> str | None:
    location = note.split(" · ", 1)[0].strip()
    if location == country_name:
        return location
    if location.endswith(f", {country_name}"):
        return location
    return None  # Global or ambiguous listings are not country-specific evidence.


def _published_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize(item: ET.Element, country_code: str) -> tuple[JobListing, list[str]] | None:
    title_line = clean_text(item.findtext("title"), max_length=300)
    source_url = safe_url(item.findtext("link"), allowed_hosts={"www.hardproblems.com", "hardproblems.com"})
    original_url = safe_url(item.findtext("guid"))
    if not title_line or not source_url:
        return None
    note = _location_note(item.findtext("description") or "")
    location = _country_location(note, COUNTRIES[country_code])
    if location is None:
        return None
    title, company = title_line.rsplit(" at ", 1) if " at " in title_line else (title_line, "")
    published_at = _published_at(item.findtext("pubDate"))
    work_style = [part.strip().casefold() for part in note.split(" · ")[1:]]
    # Hybrid, unspecified and descriptive "remote possible" text are not a
    # verified fully remote status. Nor does absence of Remote mean on-site.
    remote = True if "remote" in work_style else None
    categories = [clean_text(node.text, max_length=120) for node in item.findall("category")]
    paragraphs = [clean_text(value, max_length=5000) for value in _PARAGRAPH.findall(item.findtext("description") or "")]
    listing: JobListing = {
        "id": f"hard_problems:{source_url.rsplit('/', 1)[-1]}",
        "title": title,
        "company": company or None,
        "url": source_url,
        "apply_url": original_url if original_url != source_url else None,
        "location": location,
        "country": country_code,
        "remote": remote,
        "employment_type": None,
        "published_at": published_at,
        "description": "\n\n".join(paragraphs[:-1])[:5000] or None,
        "impact": paragraphs[2] if len(paragraphs) >= 4 else None,
        "detail_status": "summary",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "provider": "hard_problems",
    }
    return listing, categories


async def _enrich_listing(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, listing: JobListing) -> JobListing:
    async with semaphore:
        try:
            details = await fetch_role_details(client, listing["url"])
        except ProviderError as exc:
            # Keep the usable RSS listing, but expose its incomplete detail state.
            logger.warning("Hard Problems role details unavailable (%s): %s", exc.code, listing["url"])
            return listing
        return {**listing, **details}


async def _fetch_feed(client: httpx.AsyncClient, country_name: str) -> bytes:
    for attempt in range(3):
        try:
            response = await client.get(FEED_URL, params={"country": country_name})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 2:
                raise ProviderError("unavailable", "Impact job feed is temporarily unavailable.") from exc
            await asyncio.sleep(0.2 * (2 ** attempt))
            continue
        if response.status_code in {429, 500, 502, 503, 504}:
            if attempt == 2:
                code = "rate_limited" if response.status_code == 429 else "unavailable"
                raise ProviderError(code, "Impact job feed is temporarily unavailable.")
            await asyncio.sleep(0.2 * (2 ** attempt))
            continue
        if response.status_code >= 400:
            raise ProviderError("unavailable", "Impact job feed is temporarily unavailable.")
        if len(response.content) > MAX_FEED_BYTES:
            raise ProviderError("invalid_response", "Impact job feed exceeded its bounded size.")
        return response.content
    raise ProviderError("unavailable", "Impact job feed is temporarily unavailable.")


async def search_jobs(
    *,
    query: str = "",
    location: str | None = None,
    country: str = "DE",
    remote: bool | None = None,
    employment_type: str | None = None,
    max_days_old: int | None = None,
    limit: int = 10,
    impact_area: str | None = None,
    radius_km: int | None = None,
) -> list[JobListing]:
    """Search country-filtered RSS and enrich only the bounded matching roles."""
    country_code = _country_code(country)
    if country_code is None or limit <= 0:
        return []
    if radius_km is not None or employment_type or remote is False:
        raise ProviderError("unsupported_filter", "Hard Problems RSS cannot verify this filter.")
    requested_limit = max(1, min(int(limit), MAX_RESULTS))
    terms = clean_text(query, max_length=MAX_QUERY_CHARS).casefold().split()
    area = clean_text(impact_area, max_length=80).casefold() if impact_area else ""
    requested_place = clean_text(location, max_length=120).split(",", 1)[0].casefold() if location else ""

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers={"Accept": "application/rss+xml"}) as client:
        content = await _fetch_feed(client, COUNTRIES[country_code])
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ProviderError("invalid_response", "Impact job feed returned invalid XML.")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ProviderError("invalid_response", "Impact job feed returned invalid XML.") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise ProviderError("invalid_response", "Impact job feed returned invalid RSS.")

    results: list[JobListing] = []
    for item in root.findall("./channel/item")[:MAX_ITEMS]:
        parsed = _normalize(item, country_code)
        if parsed is None:
            continue
        listing, categories = parsed
        if remote is True and listing["remote"] is not True:
            continue
        if requested_place and requested_place != (listing["location"] or "").split(",", 1)[0].casefold():
            continue
        if not within_days(listing["published_at"], max_days_old):
            continue
        haystack = " ".join(filter(None, (listing["title"], listing["company"], *categories))).casefold()
        if not all(term in haystack for term in terms):
            continue
        if area and not any(area in category.casefold() for category in categories):
            continue
        results.append(listing)
        if len(results) >= requested_limit:
            break
    if not results:
        return results
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=2.0), follow_redirects=False) as client:
        return list(await asyncio.gather(*(_enrich_listing(client, semaphore, listing) for listing in results)))
