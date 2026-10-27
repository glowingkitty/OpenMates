"""Search approved public job feeds with explicit source and filter semantics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.jobs import jobtech
from backend.shared.providers.jobs.common import ProviderError, normalize_employment_type, safe_url
from backend.shared.python_utils.search_relevance import (
    MAX_RELEVANCE_CRITERIA_CHARS,
    normalize_relevance_criteria,
    normalize_url_for_deduplication,
    rank_search_candidates,
    stable_deduplicate_candidates,
)

logger = logging.getLogger(__name__)

MAX_REQUESTS = 5
MAX_LIMIT = 50
DEFAULT_LIMIT = 10
RANKING_UNAVAILABLE_MESSAGE = "Relevance criteria could not be applied; results remain in provider order."
PROVIDER_SEARCH = {"jobtech": jobtech.search_jobs}
PROVIDER_COUNTRIES = {"jobtech": frozenset({"SE"})}
PROVIDER_ALIASES = {
    "jobtech": "jobtech", "jobtechdev": "jobtech", "jobtech dev": "jobtech", "auto": "auto",
}
JOB_FIELDS = (
    "id", "title", "company", "url", "apply_url", "location", "country",
    "remote", "employment_type", "published_at", "description", "salary_min",
    "salary_max", "salary_currency", "salary_period", "provider",
    "sector", "role", "seniority", "organization_type", "work_arrangement",
    "salary_text", "valid_through", "impact", "detail_status",
)


class JobsSearchRequestItem(BaseModel):
    """One independent search; the optional ID correlates a batch result."""

    id: str | int | None = None
    query: str = Field(min_length=1, max_length=400)
    country: str | None = None
    countries: list[str] | None = None
    location: str | None = None
    radius_km: int | None = Field(default=None, ge=1, le=200)
    remote: bool | None = None
    employment_type: str | None = None
    max_days_old: int | None = Field(default=None, ge=1, le=3650)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    provider: str | None = None
    providers: list[str] | None = None
    relevance_criteria: str | None = Field(default=None, max_length=MAX_RELEVANCE_CRITERIA_CHARS)


class JobsSearchResponse(BaseModel):
    """Canonical grouped result shape consumed by chat embeds and SDK calls."""

    success: bool = False
    partial: bool = False
    app_id: str = "jobs"
    skill_id: str = "search"
    status: str = "finished"
    provider: str = ""
    providers: list[str] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


def _country(value: str) -> str:
    country = value.strip().upper()
    country = {"GERMANY": "DE", "DEUTSCHLAND": "DE", "SWEDEN": "SE", "SVERIGE": "SE"}.get(country, country)
    if country not in {"DE", "SE"}:
        raise ValueError("Job search currently supports Germany (DE) and Sweden (SE).")
    return country


def _countries(values: Any) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError("Select at least one supported country (DE or SE).")
    selected: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Select countries using DE or SE country codes.")
        country = _country(value)
        if country not in selected:
            selected.append(country)
    return selected


def _selected_countries(item: JobsSearchRequestItem, defaults: list[str]) -> list[str]:
    # REST's typed request serializer includes absent optional item fields as None.
    # Treat those as absent so the same logical request works over REST, CLI, SDK,
    # and direct skill calls; nonempty selections still conflict explicitly.
    if item.country is not None and item.countries is not None:
        raise ValueError("Specify country or countries for a request, not both.")
    if item.countries is not None:
        return _countries(item.countries)
    if item.country is not None:
        return [_country(item.country)]
    return defaults[:]


def _provider_names(item: JobsSearchRequestItem, countries: list[str]) -> list[str]:
    if item.provider and item.providers is not None:
        raise ValueError("Specify provider or providers, not both.")
    normalized_type = normalize_employment_type(item.employment_type) if item.employment_type else None
    if item.employment_type and normalized_type is None:
        raise ValueError("Unsupported employment type. Use full_time, part_time, internship, contract, or apprenticeship.")
    item.employment_type = normalized_type
    requested = item.providers if item.providers is not None else [item.provider or "auto"]
    if not requested:
        raise ValueError("Provider list cannot be empty.")
    normalized: list[str] = []
    for raw in requested:
        name = PROVIDER_ALIASES.get(raw.strip().lower())
        if name is None:
            raise ValueError("Unsupported jobs provider. Choose JobTech.")
        if name not in normalized:
            normalized.append(name)
    if "auto" in normalized:
        if len(normalized) > 1:
            raise ValueError("Do not combine auto with explicit providers.")
        normalized = []
        for country in countries:
            if country == "SE" and normalized_type in {None, "full_time", "part_time"}:
                normalized.append("jobtech")
    else:
        irrelevant = [name for name in normalized if not PROVIDER_COUNTRIES[name].intersection(countries)]
        if irrelevant:
            raise ValueError(
                f"Requested jobs provider {', '.join(irrelevant)} does not cover selected countries {', '.join(countries)}."
            )
    normalized = list(dict.fromkeys(normalized))
    uncovered = [country for country in countries if not any(country in PROVIDER_COUNTRIES[name] for name in normalized)]
    if uncovered:
        raise ValueError(f"No requested jobs provider covers {', '.join(uncovered)}.")
    if item.radius_km is not None:
        raise ValueError("Radius search is unavailable from the permitted jobs providers.")
    if normalized_type and "jobtech" in normalized and normalized_type not in {"full_time", "part_time"}:
        raise ValueError("JobTech supports only full_time and part_time employment filters.")
    return normalized


def _warning(
    request_id: str | int, provider: str, code: str, message: str, *, country: str | None = None,
) -> dict[str, Any]:
    warning = {"request_id": str(request_id), "provider": provider, "code": code, "message": message}
    if country is not None:
        warning["country"] = country
    return warning


def _normalized_job(raw: dict[str, Any], provider: str, requested_country: str) -> dict[str, Any] | None:
    url, title = safe_url(raw.get("url")), raw.get("title")
    if url is None:
        return None
    if not isinstance(title, str) or not title.strip():
        return None
    if raw.get("country") != requested_country or requested_country not in PROVIDER_COUNTRIES[provider]:
        return None
    job = {name: raw.get(name) for name in JOB_FIELDS}
    job.update({
        "id": str(raw.get("id") or normalize_url_for_deduplication(url)),
        "title": title.strip(), "url": url, "provider": provider,
        "type": "job_result", "parent_app_skill_type": "app_skill_use",
    })
    job["apply_url"] = safe_url(raw.get("apply_url"))
    return job


def _matches_strict_filters(job: dict[str, Any], item: JobsSearchRequestItem) -> bool:
    if item.remote is not None and job.get("remote") is not item.remote:
        return False
    if item.employment_type:
        if normalize_employment_type(job.get("employment_type")) != item.employment_type:
            return False
    if item.max_days_old is not None:
        published = job.get("published_at")
        if not isinstance(published, str) or not published:
            return False
        try:
            parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        if parsed < datetime.now(timezone.utc) - timedelta(days=item.max_days_old):
            return False
    return True


def _job_dedup_key(job: dict[str, Any]) -> tuple[str, ...]:
    country = str(job["country"])
    url = normalize_url_for_deduplication(job["url"])
    if url:
        return country, url
    return country, str(job["title"]).casefold(), str(job.get("company") or "").casefold()


class SearchSkill(BaseSkill):
    """Search public jobs without requiring a provider key from the user."""

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        """Describe pending sources from validated input without provider calls or child data."""
        raw_requests = request.get("requests")
        items = raw_requests if isinstance(raw_requests, list) else [request]
        try:
            defaults = _countries(request.get("countries", ["DE"]))
        except ValueError:
            return {}
        providers: list[str] = []
        countries: list[str] = []
        queries: list[str] = []
        for raw in items[:MAX_REQUESTS]:
            if not isinstance(raw, dict):
                continue
            try:
                item = JobsSearchRequestItem.model_validate(raw)
                selected_countries = _selected_countries(item, defaults)
                item.location = item.location.strip() if item.location else None
                selected = _provider_names(item, selected_countries)
            except (ValueError, ValidationError):
                continue
            providers.extend(name for name in selected if name not in providers)
            countries.extend(country for country in selected_countries if country not in countries)
            queries.append(item.query.strip())
        if not providers:
            return {}
        result: dict[str, Any] = {"providers": providers, "provider": ", ".join(providers), "countries": countries}
        if len(queries) == 1:
            result["query"] = queries[0]
            result["country"] = countries[0] if len(countries) == 1 else None
        return result

    async def execute(
        self,
        requests: list[dict[str, Any]] | None = None,
        countries: list[str] | None = None,
        secrets_manager: Any = None,
        **kwargs: Any,
    ) -> JobsSearchResponse:
        if not isinstance(requests, list) or not requests or len(requests) > MAX_REQUESTS:
            return JobsSearchResponse(error=f"Provide 1 to {MAX_REQUESTS} job search requests.")
        try:
            default_countries = _countries(["DE"] if countries is None else countries)
        except ValueError as exc:
            return JobsSearchResponse(error=str(exc))
        groups = await asyncio.gather(
            *(self._search_one(index, raw, default_countries, secrets_manager) for index, raw in enumerate(requests, start=1))
        )
        warnings = [warning for group in groups for warning in group.get("warnings", [])]
        providers = list(dict.fromkeys(provider for group in groups for provider in group.get("providers", [])))
        successes = sum("error" not in group for group in groups)
        return JobsSearchResponse(
            success=successes > 0,
            partial=successes > 0 and (successes < len(groups) or bool(warnings)),
            provider=", ".join(providers), providers=providers, results=groups,
            result_count=sum(group.get("result_count", 0) for group in groups),
            warnings=warnings,
            error="Job search failed for all requests." if successes == 0 else None,
        )

    async def _search_one(
        self, index: int, raw: Any, default_countries: list[str], secrets_manager: Any,
    ) -> dict[str, Any]:
        candidate_id = raw.get("id", index) if isinstance(raw, dict) else index
        request_id = candidate_id if isinstance(candidate_id, (str, int)) else index
        try:
            if not isinstance(raw, dict):
                raise ValueError("Each job search request must be an object.")
            item = JobsSearchRequestItem.model_validate(raw)
            item.query = item.query.strip()
            if not item.query:
                raise ValueError("Job search requires a query.")
            selected_countries = _selected_countries(item, default_countries)
            item.location = item.location.strip() if item.location else None
            item.relevance_criteria = normalize_relevance_criteria(item.relevance_criteria)
            providers = _provider_names(item, selected_countries)
        except ValidationError:
            return {"id": request_id, "results": [], "result_count": 0, "providers": [], "warnings": [], "error": "Invalid job search request."}
        except ValueError as exc:
            return {"id": request_id, "results": [], "result_count": 0, "providers": [], "warnings": [], "error": str(exc)}

        candidate_limit = min(MAX_LIMIT, max(item.limit, 40)) if item.relevance_criteria else item.limit
        pairs = [
            (provider, country)
            for country in selected_countries
            for provider in providers
            if country in PROVIDER_COUNTRIES[provider]
        ]
        calls = []
        for provider, country in pairs:
            arguments: dict[str, Any] = {
                "query": item.query, "location": item.location, "country": country,
                "remote": item.remote, "employment_type": item.employment_type,
                "max_days_old": item.max_days_old, "limit": candidate_limit, "impact_area": None,
            }
            calls.append(PROVIDER_SEARCH[provider](**arguments))
        responses = await asyncio.gather(*calls, return_exceptions=True)
        jobs: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        succeeded = 0
        for (provider, country), response in zip(pairs, responses):
            if isinstance(response, asyncio.CancelledError):
                raise response
            if isinstance(response, BaseException):
                if isinstance(response, ProviderError):
                    warnings.append(_warning(request_id, provider, response.code, response.message, country=country))
                else:
                    logger.warning("jobs.search provider %s failed: %s", provider, type(response).__name__)
                    warnings.append(_warning(request_id, provider, "unavailable", "Job source temporarily unavailable.", country=country))
                continue
            if not isinstance(response, list):
                warnings.append(_warning(request_id, provider, "invalid_response", "Job source returned an invalid response.", country=country))
                continue
            valid_rows = 0
            for raw_job in response:
                if isinstance(raw_job, dict):
                    job = _normalized_job(raw_job, provider, country)
                    if job is not None:
                        valid_rows += 1
                        if _matches_strict_filters(job, item):
                            jobs.append(job)
            if response and valid_rows == 0:
                warnings.append(_warning(request_id, provider, "invalid_response", "Job source returned unusable listings.", country=country))
                continue
            succeeded += 1

        jobs = stable_deduplicate_candidates(jobs, key=_job_dedup_key)
        if item.relevance_criteria and jobs:
            projections = [{key: job.get(key) for key in (
                "title", "company", "location", "country", "remote", "employment_type",
                "description", "published_at", "salary_min", "salary_max", "salary_currency", "salary_period",
            )} for job in jobs]
            try:
                ranking = await rank_search_candidates(
                    candidates=jobs, candidate_projections=projections,
                    relevance_criteria=item.relevance_criteria,
                    search_parameters={"query": item.query, "countries": selected_countries, "location": item.location},
                    profile="jobs", secrets_manager=secrets_manager,
                )
                if ranking.applied:
                    jobs = ranking.candidates
                else:
                    warnings.append(_warning(request_id, "ranking", "ranking_unavailable", RANKING_UNAVAILABLE_MESSAGE))
            except Exception:
                logger.warning("jobs.search relevance ranking unavailable; preserving provider order")
                warnings.append(_warning(request_id, "ranking", "ranking_unavailable", RANKING_UNAVAILABLE_MESSAGE))
        jobs = jobs[:item.limit]
        group: dict[str, Any] = {
            "id": request_id, "query": item.query,
            "country": selected_countries[0] if len(selected_countries) == 1 else None,
            "countries": selected_countries,
            "providers": providers, "results": jobs, "result_count": len(jobs), "warnings": warnings,
        }
        if succeeded == 0:
            group["error"] = "All requested job sources failed."
        return group
