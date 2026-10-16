"""Bounded searches of the logged-out 80,000 Hours job-board index.

This is the board's browser search interface, not a documented partner API.
The public search credential is read from the board's current page at runtime.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from .common import ProviderError, clean_text, parse_date, safe_url, within_days
from .models import JobListing

BOARD_URL = "https://jobs.80000hours.org/"
MAX_RESULTS = 20
MAX_FETCH = 50
MAX_QUERY_CHARS = 400
CONFIG_TTL_SECONDS = 60
REQUEST_TIMEOUT = httpx.Timeout(8.0, connect=3.0)
COUNTRY_NAMES = {"DE": "Germany", "SE": "Sweden"}
COUNTRY_ALIASES = {
    "DE": {"DE", "GERMANY", "DEUTSCHLAND"},
    "SE": {"SE", "SWEDEN", "SVERIGE"},
}
ROLE_TYPES = {"Full-time": "full_time", "Part-time": "part_time", "Internship": "internship"}
_CONFIG_PATTERNS = {
    "application": re.compile(r'algoliaApplicationId:"([A-Z0-9]{6,20})"'),
    "key": re.compile(r'algoliaApiKey:"([a-zA-Z0-9]{16,64})"'),
    "index": re.compile(r'algoliaJobsIndex:"([a-zA-Z0-9_]{3,80})"'),
}
_CONFIG_CACHE: tuple[float, tuple[str, str, str]] | None = None


def _country_code(country: str | None) -> str | None:
    value = country.strip().upper() if isinstance(country, str) else ""
    return next((code for code, aliases in COUNTRY_ALIASES.items() if value in aliases), None)


def _strings(value: object) -> list[str]:
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def _matches_city(cities: list[str], location: str | None, country_name: str) -> bool:
    country_aliases = {"Germany": {"de", "germany", "deutschland"},
                       "Sweden": {"se", "sweden", "sverige"}}
    if not location or location.strip().casefold() in country_aliases[country_name]:
        return True
    wanted = location.split(",", 1)[0].strip().casefold()
    return bool(wanted and any(city.split(",", 1)[0].strip().casefold() == wanted for city in cities))


def _employment_type(tags: list[str]) -> str | None:
    matches = {ROLE_TYPES[tag] for tag in tags if tag in ROLE_TYPES}
    return next(iter(matches)) if len(matches) == 1 else None


def _normalize(hit: dict[str, Any], country: str, location: str | None) -> JobListing | None:
    country_name = COUNTRY_NAMES[country]
    if country_name not in _strings(hit.get("tags_country")):
        return None
    # Multi-country roles carry all locations in one record. Show only places
    # explicitly tied to the requested country rather than implying, for
    # example, that a US workplace is in Sweden.
    country_key = country_name.casefold()
    cities = [city for city in _strings(hit.get("tags_city"))
              if city.casefold() == country_key or city.casefold().endswith(f", {country_key}")]
    if not _matches_city(cities, location, country_name):
        return None
    source_id = clean_text(hit.get("objectID"), max_length=80)
    title = clean_text(hit.get("title"), max_length=300)
    url = safe_url(hit.get("url_external"))
    if not source_id or not title or not url:
        return None
    posted = parse_date(hit.get("posted_at"))
    return JobListing(
        id=f"eighty_thousand_hours:{source_id}", title=title,
        company=clean_text(hit.get("company_name"), max_length=300) or None,
        url=url, apply_url=url,
        location=", ".join(cities[:3]) or country_name,
        country=country,
        # The board's Remote tag can include country-restricted or hybrid roles.
        remote=None,
        employment_type=_employment_type(_strings(hit.get("tags_role_type"))),
        published_at=posted.isoformat() if posted else None,
        description=None,
        salary_min=None, salary_max=None, salary_currency=None, salary_period=None,
        provider="eighty_thousand_hours",
    )


async def _browser_config(client: httpx.AsyncClient) -> tuple[str, str, str]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE and _CONFIG_CACHE[0] > time.monotonic():
        return _CONFIG_CACHE[1]
    try:
        response = await client.get(BOARD_URL)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ProviderError("unavailable", "80,000 Hours search is temporarily unavailable.") from exc
    if response.status_code == 429:
        raise ProviderError("rate_limited", "80,000 Hours search is rate limited.")
    if response.status_code != 200 or len(response.content) > 256_000:
        raise ProviderError("unavailable", "80,000 Hours search is temporarily unavailable.")
    matches = {name: pattern.search(response.text) for name, pattern in _CONFIG_PATTERNS.items()}
    if not all(matches.values()):
        raise ProviderError("invalid_response", "80,000 Hours search configuration changed.")
    config = (matches["application"].group(1), matches["key"].group(1), matches["index"].group(1))
    _CONFIG_CACHE = (time.monotonic() + CONFIG_TTL_SECONDS, config)
    return config


async def _search_index(
    client: httpx.AsyncClient, application: str, key: str, index: str,
    *, query: str, country_name: str, limit: int,
) -> list[dict[str, Any]]:
    url = f"https://{application}-dsn.algolia.net/1/indexes/{index}/query"
    headers = {"x-algolia-application-id": application, "x-algolia-api-key": key}
    body = {
        "query": query[:MAX_QUERY_CHARS], "page": 0, "hitsPerPage": min(MAX_FETCH, max(10, limit * 3)),
        "facetFilters": [f"tags_country:{country_name}"],
        "attributesToRetrieve": [
            "objectID", "title", "company_name", "url_external", "tags_country",
            "tags_city", "tags_role_type", "posted_at",
        ],
        "analytics": False, "clickAnalytics": False,
    }
    try:
        response = await client.post(url, headers=headers, json=body)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ProviderError("unavailable", "80,000 Hours search is temporarily unavailable.") from exc
    if response.status_code == 429:
        raise ProviderError("rate_limited", "80,000 Hours search is rate limited.")
    if response.status_code != 200:
        raise ProviderError("unavailable", "80,000 Hours search is temporarily unavailable.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("invalid_response", "80,000 Hours search returned invalid data.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
        raise ProviderError("invalid_response", "80,000 Hours search returned invalid data.")
    return [hit for hit in payload["hits"][:MAX_FETCH] if isinstance(hit, dict)]


async def search_jobs(
    *, query: str = "", location: str | None = None, country: str = "DE",
    remote: bool | None = None, employment_type: str | None = None,
    max_days_old: int | None = None, limit: int = 10,
    impact_area: str | None = None, radius_km: int | None = None,
) -> list[JobListing]:
    """Search board listings with explicit DE/SE tags and verified city labels."""
    code = _country_code(country)
    if code is None or limit <= 0:
        return []
    if radius_km is not None:
        raise ProviderError("unsupported_filter", "80,000 Hours does not support radius search.")
    if impact_area:
        raise ProviderError("unsupported_filter", "80,000 Hours impact areas do not match this filter directly.")
    if employment_type and employment_type not in ROLE_TYPES.values():
        raise ProviderError("unsupported_filter", "80,000 Hours does not support this employment type.")
    if remote is not None:
        raise ProviderError("unsupported_filter", "80,000 Hours does not verify fully remote eligibility.")
    bounded_limit = min(limit, MAX_RESULTS)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
        application, key, index = await _browser_config(client)
        hits = await _search_index(client, application, key, index, query=clean_text(query),
                                   country_name=COUNTRY_NAMES[code], limit=bounded_limit)
    results: list[JobListing] = []
    for hit in hits:
        job = _normalize(hit, code, location)
        if not job or not within_days(job["published_at"], max_days_old):
            continue
        if employment_type and job["employment_type"] != employment_type:
            continue
        results.append(job)
        if len(results) >= bounded_limit:
            break
    return results
