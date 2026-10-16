"""Bounded reader for German jobs in Arbeitnow's multi-country public feed."""

import re
import time
from urllib.parse import quote

import httpx

from .common import (
    ProviderError, clean_text, country_matches, fetch_json, job_matches,
    normalize_employment_type, parse_date, safe_url,
)
from .models import JobListing

API_URL = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 3
MAX_LIMIT = 20
CACHE_TTL_SECONDS = 600
_TIMEOUT = httpx.Timeout(8.0, connect=3.0)
_PAGE_CACHE: dict[int, tuple[float, list[dict], bool]] = {}
_GERMANY_NAME = re.compile(r"(?<![A-Za-z])(?:Germany|Deutschland)(?![A-Za-z])", re.IGNORECASE)
_GERMANY_CODE = re.compile(r"(?:^|[,;|/(])\s*DE\s*(?:$|[,;|/)])", re.IGNORECASE)


def _has_german_location(location: str | None) -> bool:
    """The feed spans countries, so a city name or remote flag is insufficient."""
    return bool(location and (_GERMANY_NAME.search(location) or _GERMANY_CODE.search(location)))


def _normalize(raw: dict) -> JobListing | None:
    slug = raw.get("slug")
    title = clean_text(raw.get("title"), max_length=300)
    if not isinstance(slug, str) or not slug or not title:
        return None
    # Derive the board URL from its stable slug; do not pass through tracking links.
    url = safe_url(f"https://www.arbeitnow.com/view/{quote(slug, safe='')}", allowed_hosts={"www.arbeitnow.com"})
    if not url:
        return None
    location = clean_text(raw.get("location"), max_length=300) or None
    if not _has_german_location(location):
        return None
    date = parse_date(raw.get("created_at"))
    source_remote = raw.get("remote")
    return JobListing(
        id=f"arbeitnow:{slug}", title=title,
        company=clean_text(raw.get("company_name"), max_length=300) or None,
        url=url, apply_url=url, location=location, country="DE",
        remote=source_remote if isinstance(source_remote, bool) else None,
        employment_type=normalize_employment_type(raw.get("job_types")),
        published_at=date.isoformat() if date else None,
        description=clean_text(raw.get("description")) or None,
        salary_min=None, salary_max=None, salary_currency=None, salary_period=None,
        provider="arbeitnow",
    )


async def _page(client: httpx.AsyncClient, number: int) -> tuple[list[dict], bool]:
    cached = _PAGE_CACHE.get(number)
    if cached and cached[0] > time.monotonic():
        return cached[1], cached[2]
    payload = await fetch_json(client, API_URL, params={"page": number})
    rows = payload.get("data")
    links = payload.get("links")
    if not isinstance(rows, list) or not isinstance(links, dict):
        raise ProviderError("invalid_response", "Arbeitnow returned invalid job data.")
    valid_rows = [row for row in rows if isinstance(row, dict)]
    has_next = bool(links.get("next"))
    _PAGE_CACHE[number] = (time.monotonic() + CACHE_TTL_SECONDS, valid_rows, has_next)
    return valid_rows, has_next


async def search_jobs(
    *, query: str = "", location: str | None = None, country: str | None = "DE",
    remote: bool | None = None, employment_type: str | None = None,
    max_days_old: int | None = None, limit: int = 10, impact_area: str | None = None,
    radius_km: int | None = None,
) -> list[JobListing]:
    """Scan at most three newest pages; matching is partial beyond that window."""
    if not country_matches(country, "DE"):
        return []
    if radius_km is not None:
        raise ProviderError("unsupported_filter", "Arbeitnow does not support radius searches.")
    if limit <= 0:
        return []
    bounded_limit = min(limit, MAX_LIMIT)
    results: list[JobListing] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        for number in range(1, MAX_PAGES + 1):
            rows, has_next = await _page(client, number)
            for raw in rows:
                job = _normalize(raw)
                if not job or job["id"] in seen:
                    continue
                seen.add(job["id"])
                if job_matches(job, query=query, location=location, remote=remote,
                               employment_type=employment_type, max_days_old=max_days_old):
                    results.append(job)
                    if len(results) >= bounded_limit:
                        return results
            if not has_next:
                break
    return results
