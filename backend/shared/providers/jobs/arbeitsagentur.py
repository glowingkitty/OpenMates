"""Bounded public Jobsuche reader for the German Federal Employment Agency."""

import base64
from urllib.parse import quote

import httpx

from .common import (
    ProviderError, clean_text, country_matches, fetch_json,
    normalize_employment_type, parse_date, safe_url, within_days,
)
from .models import JobListing

SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
DETAIL_ROOT = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails"
PUBLIC_HEADER = {"X-API-Key": "jobboerse-jobsuche"}
MAX_PAGES = 2
MAX_LIMIT = 10
PAGE_SIZE = 50
_TIMEOUT = httpx.Timeout(8.0, connect=3.0)


def _remote(raw: dict) -> bool | None:
    # BA's homeofficemoeglich only says that some work from home is possible.
    # This must never be advertised as a fully remote position.
    kind = str(raw.get("homeofficetyp") or "").upper()
    if kind in {"VOLLSTAENDIG", "VOLLSTÄNDIG", "VOLLSTAENDIG_REMOTE", "AUSSCHLIESSLICH"}:
        return True
    if raw.get("homeofficemoeglich") is False:
        return False
    return None


def _employment_type(raw: dict) -> str | None:
    kind = str(raw.get("stellenangebotsart") or "").upper()
    if kind == "PRAKTIKUM" or kind == "TRAINEE":
        return "internship"
    if kind == "AUSBILDUNG":
        return "apprenticeship"
    if kind == "SELBSTAENDIGKEIT":
        return "contract"
    full_time = raw.get("arbeitszeitVollzeit")
    if full_time is True:
        return "full_time"
    if full_time is False:
        return "part_time"
    return None


def _normalize(raw: dict) -> JobListing | None:
    ref = raw.get("referenznummer")
    title = clean_text(raw.get("stellenangebotsTitel"), max_length=300)
    if not isinstance(ref, str) or not ref or not title:
        return None
    url = safe_url(f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{quote(ref, safe='')}",
                   allowed_hosts={"www.arbeitsagentur.de"})
    if not url:
        return None
    places = raw.get("stellenlokationen")
    addresses = [place.get("adresse", {}) for place in places if isinstance(place, dict)] if isinstance(places, list) else []
    first = addresses[0] if addresses and isinstance(addresses[0], dict) else {}
    town = clean_text(first.get("ort"), max_length=120)
    region = clean_text(first.get("region"), max_length=120)
    location = ", ".join(part for part in (town, region) if part) or None
    period = raw.get("veroeffentlichungszeitraum")
    first_published = raw.get("datumErsteVeroeffentlichung")
    date = parse_date(first_published or (period.get("von") if isinstance(period, dict) else None))
    description = clean_text(raw.get("stellenangebotsBeschreibung")) or None
    return JobListing(
        id=f"arbeitsagentur:{ref}", title=title,
        company=clean_text(raw.get("firma"), max_length=300) or None,
        url=url, apply_url=url, location=location, country="DE",
        remote=_remote(raw), employment_type=_employment_type(raw),
        published_at=date.isoformat() if date else None,
        description=description, salary_min=None, salary_max=None,
        salary_currency=None, salary_period=None, provider="arbeitsagentur",
    )


def _offer_type(employment_type: str | None) -> int:
    normalized = normalize_employment_type(employment_type)
    return {"internship": 34, "apprenticeship": 4, "contract": 2}.get(normalized, 1)


async def search_jobs(
    *, query: str = "", location: str | None = None, country: str | None = "DE",
    remote: bool | None = None, employment_type: str | None = None,
    max_days_old: int | None = None, limit: int = 10, impact_area: str | None = None,
    radius_km: int | None = None,
) -> list[JobListing]:
    """Search v6, then fetch v4 details only for final, bounded results."""
    if not country_matches(country, "DE"):
        return []
    if radius_km is not None and (not location or radius_km < 0 or radius_km > 200):
        raise ProviderError("unsupported_filter", "BA radius requires a location and 0–200 km.")
    if employment_type and normalize_employment_type(employment_type) is None:
        raise ProviderError("unsupported_filter", "BA does not support this employment type.")
    if limit <= 0:
        return []
    bounded_limit = min(limit, MAX_LIMIT)
    params: dict[str, object] = {
        "page": 1, "size": PAGE_SIZE, "angebotsart": _offer_type(employment_type),
    }
    if query:
        params["was"] = query.strip()
    if location:
        params["wo"] = location.strip()
    if radius_km is not None:
        params["umkreis"] = radius_km
    if max_days_old is not None and max_days_old <= 100:
        params["veroeffentlichtseit"] = max(0, max_days_old)
    normalized_type = normalize_employment_type(employment_type)
    if normalized_type == "part_time":
        params["arbeitszeit"] = "tz"
    elif normalized_type == "full_time":
        params["arbeitszeit"] = "vz"
    results: list[JobListing] = []
    refs: list[str] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        for page in range(1, MAX_PAGES + 1):
            params["page"] = page
            payload = await fetch_json(client, SEARCH_URL, params=params, headers=PUBLIC_HEADER)
            rows = payload.get("ergebnisliste")
            if not isinstance(rows, list):
                raise ProviderError("invalid_response", "BA returned invalid job data.")
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                job = _normalize(raw)
                if not job or job["id"] in seen:
                    continue
                seen.add(job["id"])
                if remote is not None and job["remote"] is not remote:
                    continue
                if normalized_type and job["employment_type"] != normalized_type:
                    continue
                if not within_days(job["published_at"], max_days_old):
                    continue
                results.append(job)
                refs.append(raw["referenznummer"])
                if len(results) >= bounded_limit:
                    break
            if len(results) >= bounded_limit or len(rows) < PAGE_SIZE:
                break
        for job, ref in zip(results, refs):
            encoded = base64.b64encode(ref.encode("utf-8")).decode("ascii")
            try:
                detail = await fetch_json(client, f"{DETAIL_ROOT}/{quote(encoded, safe='')}", headers=PUBLIC_HEADER)
            except ProviderError:
                break  # Preserve results and avoid a detail-request storm on outage or 429.
            description = clean_text(detail.get("stellenangebotsBeschreibung"))
            if description:
                job["description"] = description
    return results
