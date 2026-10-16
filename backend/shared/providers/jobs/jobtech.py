"""Swedish Public Employment Service JobSearch vacancy adapter.

Official API: https://jobsearch.api.jobtechdev.se/
Dataset and licence: https://data.jobtechdev.se/dataservice/jobsearch/
"""

from __future__ import annotations

import unicodedata
from typing import Any

import httpx

from backend.shared.providers.jobs.common import (
    ProviderError,
    clean_text,
    country_matches,
    fetch_json,
    normalize_employment_type,
    safe_url,
    within_days,
)
from backend.shared.providers.jobs.models import JobListing

JOBTECH_SEARCH_URL = "https://jobsearch.api.jobtechdev.se/search"
SWEDEN_CONCEPT_ID = "i46j_HmG_v64"
SWEDEN_COUNTRY_CODE = "199"
MAX_RESULTS = 25
MAX_FETCH = 100
MAX_QUERY_CHARS = 160
REQUEST_TIMEOUT = httpx.Timeout(8.0, connect=3.0)


def _label(value: object) -> str:
    return clean_text(value.get("label")) if isinstance(value, dict) else ""


def _employment_type(ad: dict[str, Any]) -> str | None:
    """Use Swedish work time or duration only when the source states it."""
    hours = _label(ad.get("working_hours_type")).casefold()
    duration = _label(ad.get("duration")).casefold()
    if hours == "heltid":
        return "full_time"
    if hours == "deltid":
        return "part_time"
    if "praktik" in duration or "praktik" in _label(ad.get("employment_type")).casefold():
        return "internship"
    return None


def _remote_status(ad: dict[str, Any]) -> bool | None:
    """Only classify an unambiguous, structured workplace model."""
    model = _label(ad.get("workplace_model")).casefold().strip()
    if model in {"remote", "fully remote", "100% remote", "helt på distans"}:
        return True
    if model in {"arbete på plats", "på plats", "onsite", "on-site"}:
        return False
    return None


def _swedish_address(ad: dict[str, Any]) -> dict[str, Any] | None:
    address = ad.get("workplace_address")
    if not isinstance(address, dict):
        return None
    if address.get("country_concept_id") == SWEDEN_CONCEPT_ID or str(address.get("country_code")) == SWEDEN_COUNTRY_CODE:
        return address
    return None


def _location(address: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("city", "municipality", "region"):
        value = clean_text(address.get(key))
        if value and value.casefold() not in {part.casefold() for part in parts}:
            parts.append(value)
    return ", ".join(parts) or None


def _place_key(value: object) -> str:
    """Compare a requested place only with structured workplace place names."""
    return unicodedata.normalize("NFKC", clean_text(value)).casefold().strip()


def _matches_workplace(address: dict[str, Any], requested: str) -> bool | None:
    """Return None when the ad lacks enough workplace data to check a place."""
    name = requested.split(",", 1)[0].strip()
    wanted = _place_key(name)
    if not wanted:
        return None
    city = _place_key(address.get("city"))
    municipality = _place_key(address.get("municipality"))
    region = _place_key(address.get("region"))
    if wanted.endswith(" län"):
        return region == wanted if region else None
    # The stated city takes precedence: Solna city must not pass a Stockholm
    # request merely because the municipality happens to say Stockholm.
    if city:
        return city == wanted
    if municipality:
        return municipality == wanted
    return None


def _normalize(ad: dict[str, Any]) -> JobListing | None:
    address = _swedish_address(ad)
    if address is None:
        return None
    source_id = clean_text(ad.get("id"))
    title = clean_text(ad.get("headline"))
    url = safe_url(ad.get("webpage_url"))
    if not source_id or not title or not url:
        return None
    employer = ad.get("employer") if isinstance(ad.get("employer"), dict) else {}
    application = ad.get("application_details") if isinstance(ad.get("application_details"), dict) else {}
    description = ad.get("description") if isinstance(ad.get("description"), dict) else {}
    apply_url = safe_url(application.get("url")) or url
    published_at = clean_text(ad.get("publication_date")) or None
    return {
        "id": f"jobtech:{source_id}",
        "title": title,
        "company": clean_text(employer.get("name")) or None,
        "url": url,
        "apply_url": apply_url,
        "location": _location(address),
        "country": "SE",
        "remote": _remote_status(ad),
        "employment_type": _employment_type(ad),
        "published_at": published_at,
        "description": clean_text(description.get("text")) or None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "provider": "jobtech",
    }


def _type_matches(requested: str | None, normalized: str | None) -> bool:
    if not requested:
        return True
    wanted = normalize_employment_type(requested)
    return bool(wanted and normalized == wanted)


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
    """Search active Swedish jobs; unsupported countries never trigger a request.

    JobSearch accepts a free-text location but a precise radius requires a separate
    geocoding step. ``impact_area`` has no trustworthy native JobSearch filter.
    """
    if not country or not country_matches(country, "SE"):
        return []
    if radius_km is not None:
        raise ProviderError("unsupported_filter", "JobTech radius search requires coordinates.")
    if impact_area:
        raise ProviderError("unsupported_filter", "JobTech does not support impact-area filtering.")
    requested_limit = max(1, min(int(limit), MAX_RESULTS))
    terms = [clean_text(value) for value in (query, location) if value]
    params: dict[str, str | int | bool] = {
        "country": SWEDEN_CONCEPT_ID,
        "limit": min(MAX_FETCH, max(10, requested_limit * 3)),
        "sort": "pubdate-desc" if not query.strip() else "relevance",
    }
    if terms:
        params["q"] = " ".join(terms)[:MAX_QUERY_CHARS]
    if remote is not None:
        params["remote"] = remote
    if max_days_old is not None and 0 < max_days_old <= 365:
        params["published-after"] = max_days_old * 24 * 60

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers={"Accept": "application/json"}) as client:
        payload = await fetch_json(client, JOBTECH_SEARCH_URL, params=params)
    if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
        raise ProviderError("invalid_response", "JobTech returned an invalid search response")

    results: list[JobListing] = []
    unverifiable_workplace = False
    for ad in payload["hits"][:MAX_FETCH]:
        if not isinstance(ad, dict):
            continue
        if location:
            address = _swedish_address(ad)
            if address is None:
                continue
            workplace_match = _matches_workplace(address, location)
            if workplace_match is None:
                unverifiable_workplace = True
                continue
            if not workplace_match:
                continue
        normalized = _normalize(ad)
        if normalized is None:
            continue
        if not _type_matches(employment_type, normalized["employment_type"]):
            continue
        if not within_days(normalized["published_at"], max_days_old):
            continue
        results.append(normalized)
        if len(results) >= requested_limit:
            break
    if location and not results and unverifiable_workplace:
        raise ProviderError("unsupported_filter", "JobTech could not verify the requested workplace location.")
    return results
