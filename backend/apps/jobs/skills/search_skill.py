"""Search approved public job feeds with explicit source and filter semantics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.jobs import arbeitnow, arbeitsagentur, jobtech
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
PROVIDER_SEARCH = {
    "arbeitnow": arbeitnow.search_jobs,
    "arbeitsagentur": arbeitsagentur.search_jobs,
    "jobtech": jobtech.search_jobs,
}
PROVIDER_COUNTRIES = {"arbeitnow": "DE", "arbeitsagentur": "DE", "jobtech": "SE"}
PROVIDER_ALIASES = {
    "arbeitnow": "arbeitnow", "arbeit now": "arbeitnow",
    "arbeitsagentur": "arbeitsagentur", "bundesagentur für arbeit": "arbeitsagentur",
    "bundesagentur fuer arbeit": "arbeitsagentur", "federal employment agency": "arbeitsagentur",
    "ba": "arbeitsagentur", "jobtech": "jobtech", "jobtechdev": "jobtech",
    "jobtech dev": "jobtech", "auto": "auto",
}
JOB_FIELDS = (
    "id", "title", "company", "url", "apply_url", "location", "country",
    "remote", "employment_type", "published_at", "description", "salary_min",
    "salary_max", "salary_currency", "salary_period", "provider",
)


class JobsSearchRequestItem(BaseModel):
    """One independent search; the optional ID correlates a batch result."""

    id: str | int | None = None
    query: str = Field(min_length=1, max_length=400)
    country: str = "DE"
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


def _provider_names(item: JobsSearchRequestItem) -> list[str]:
    if item.provider and item.providers is not None:
        raise ValueError("Specify provider or providers, not both.")
    requested = item.providers if item.providers is not None else [item.provider or "auto"]
    if not requested:
        raise ValueError("Provider list cannot be empty.")
    normalized: list[str] = []
    for raw in requested:
        name = PROVIDER_ALIASES.get(raw.strip().lower())
        if name is None:
            raise ValueError("Unsupported jobs provider. Choose Arbeitnow, Arbeitsagentur, or JobTech.")
        if name not in normalized:
            normalized.append(name)
    if "auto" in normalized:
        if len(normalized) > 1:
            raise ValueError("Do not combine auto with explicit providers.")
        normalized = ["arbeitsagentur", "arbeitnow"] if item.country == "DE" else ["jobtech"]
        if item.radius_km is not None:
            normalized = ["arbeitsagentur"] if item.country == "DE" else []
    if not normalized:
        raise ValueError("Radius search is not supported for Swedish job listings.")
    unsupported = [name for name in normalized if PROVIDER_COUNTRIES[name] != item.country]
    if unsupported:
        raise ValueError(f"Provider {', '.join(unsupported)} does not support country {item.country}.")
    if item.radius_km is not None:
        if not item.location:
            raise ValueError("radius_km requires a location.")
        unsupported_radius = [name for name in normalized if name != "arbeitsagentur"]
        if unsupported_radius:
            raise ValueError(f"Radius search is not supported by {', '.join(unsupported_radius)}.")
    if item.employment_type:
        normalized_type = normalize_employment_type(item.employment_type)
        if normalized_type is None:
            raise ValueError("Unsupported employment type. Use full_time, part_time, internship, contract, or apprenticeship.")
        if "jobtech" in normalized and normalized_type not in {"full_time", "part_time"}:
            raise ValueError("JobTech supports only full_time and part_time employment filters.")
        item.employment_type = normalized_type
    return normalized


def _warning(request_id: str | int, provider: str, code: str, message: str) -> dict[str, Any]:
    return {"request_id": str(request_id), "provider": provider, "code": code, "message": message}


def _normalized_job(raw: dict[str, Any], provider: str) -> dict[str, Any] | None:
    url, title = safe_url(raw.get("url")), raw.get("title")
    if url is None:
        return None
    if not isinstance(title, str) or not title.strip():
        return None
    if raw.get("country") != PROVIDER_COUNTRIES[provider]:
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


class SearchSkill(BaseSkill):
    """Search public jobs without requiring a provider key from the user."""

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        """Describe pending sources from validated input without provider calls or child data."""
        raw_requests = request.get("requests")
        items = raw_requests if isinstance(raw_requests, list) else [request]
        providers: list[str] = []
        countries: list[str] = []
        queries: list[str] = []
        for raw in items[:MAX_REQUESTS]:
            if not isinstance(raw, dict):
                continue
            try:
                item = JobsSearchRequestItem.model_validate(raw)
                item.country = _country(item.country)
                item.location = item.location.strip() if item.location else None
                selected = _provider_names(item)
            except (ValueError, ValidationError):
                continue
            providers.extend(name for name in selected if name not in providers)
            countries.append(item.country)
            queries.append(item.query.strip())
        if not providers:
            return {}
        result: dict[str, Any] = {"providers": providers, "provider": ", ".join(providers)}
        if len(queries) == 1:
            result["query"] = queries[0]
            result["country"] = countries[0]
        return result

    async def execute(
        self,
        requests: list[dict[str, Any]] | None = None,
        secrets_manager: Any = None,
        **kwargs: Any,
    ) -> JobsSearchResponse:
        if not isinstance(requests, list) or not requests or len(requests) > MAX_REQUESTS:
            return JobsSearchResponse(error=f"Provide 1 to {MAX_REQUESTS} job search requests.")
        groups = await asyncio.gather(
            *(self._search_one(index, raw, secrets_manager) for index, raw in enumerate(requests, start=1))
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

    async def _search_one(self, index: int, raw: Any, secrets_manager: Any) -> dict[str, Any]:
        candidate_id = raw.get("id", index) if isinstance(raw, dict) else index
        request_id = candidate_id if isinstance(candidate_id, (str, int)) else index
        try:
            if not isinstance(raw, dict):
                raise ValueError("Each job search request must be an object.")
            item = JobsSearchRequestItem.model_validate(raw)
            item.query = item.query.strip()
            if not item.query:
                raise ValueError("Job search requires a query.")
            item.country = _country(item.country)
            item.location = item.location.strip() if item.location else None
            item.relevance_criteria = normalize_relevance_criteria(item.relevance_criteria)
            providers = _provider_names(item)
        except ValidationError:
            return {"id": request_id, "results": [], "result_count": 0, "providers": [], "warnings": [], "error": "Invalid job search request."}
        except ValueError as exc:
            return {"id": request_id, "results": [], "result_count": 0, "providers": [], "warnings": [], "error": str(exc)}

        candidate_limit = min(MAX_LIMIT, max(item.limit, 40)) if item.relevance_criteria else item.limit
        calls = []
        for provider in providers:
            arguments: dict[str, Any] = {
                "query": item.query, "location": item.location, "country": item.country,
                "remote": item.remote, "employment_type": item.employment_type,
                "max_days_old": item.max_days_old, "limit": candidate_limit, "impact_area": None,
            }
            if provider == "arbeitsagentur" and item.radius_km is not None:
                arguments["radius_km"] = item.radius_km
            calls.append(PROVIDER_SEARCH[provider](**arguments))
        responses = await asyncio.gather(*calls, return_exceptions=True)
        jobs: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        succeeded = 0
        for provider, response in zip(providers, responses):
            if isinstance(response, asyncio.CancelledError):
                raise response
            if isinstance(response, BaseException):
                if isinstance(response, ProviderError):
                    warnings.append(_warning(request_id, provider, response.code, response.message))
                else:
                    logger.warning("jobs.search provider %s failed: %s", provider, type(response).__name__)
                    warnings.append(_warning(request_id, provider, "unavailable", "Job source temporarily unavailable."))
                continue
            if not isinstance(response, list):
                warnings.append(_warning(request_id, provider, "invalid_response", "Job source returned an invalid response."))
                continue
            valid_rows = 0
            for raw_job in response:
                if isinstance(raw_job, dict):
                    job = _normalized_job(raw_job, provider)
                    if job is not None:
                        valid_rows += 1
                        if _matches_strict_filters(job, item):
                            jobs.append(job)
            if response and valid_rows == 0:
                warnings.append(_warning(request_id, provider, "invalid_response", "Job source returned unusable listings."))
                continue
            succeeded += 1

        jobs = stable_deduplicate_candidates(
            jobs,
            key=lambda job: normalize_url_for_deduplication(job["url"]) or (
                str(job["title"]).casefold(), str(job.get("company") or "").casefold()
            ),
        )
        if item.relevance_criteria and jobs:
            projections = [{key: job.get(key) for key in (
                "title", "company", "location", "country", "remote", "employment_type",
                "description", "published_at", "salary_min", "salary_max", "salary_currency", "salary_period",
            )} for job in jobs]
            try:
                ranking = await rank_search_candidates(
                    candidates=jobs, candidate_projections=projections,
                    relevance_criteria=item.relevance_criteria,
                    search_parameters={"query": item.query, "country": item.country, "location": item.location},
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
            "id": request_id, "query": item.query, "country": item.country,
            "providers": providers, "results": jobs, "result_count": len(jobs), "warnings": warnings,
        }
        if succeeded == 0:
            group["error"] = "All requested job sources failed."
        return group
