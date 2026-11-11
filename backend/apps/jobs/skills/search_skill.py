"""Search approved public job feeds with explicit source and filter semantics.

Operator-installed app package providers implementing ``jobs.search@1``
(docs/architecture/apps/instance-app-packages.md) answer next to the built-in
source; with app packages disabled none are listed and behaviour is unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from backend.apps.base_skill import BaseSkill
from backend.apps.jobs.listing_filters import matches_listing_filters
from backend.apps.jobs.provider_aliases import PROVIDER_ALIASES
from backend.shared.app_packages.contracts import jobs_search_input
from backend.shared.app_packages.loader import get_installed_providers
from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome, run_installed_providers
from backend.shared.providers.jobs import jobtech
from backend.shared.providers.jobs.common import ProviderError, normalize_employment_type, safe_url
from backend.shared.python_utils.country_codes import iso_country, iso_language
from backend.shared.python_utils.search_relevance import (
    MAX_RELEVANCE_CRITERIA_CHARS,
    MAX_SEARCH_RELEVANCE_CANDIDATES,
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
RANKING_FIELDS = (
    "title", "company", "location", "country", "remote", "employment_type",
    "description", "published_at", "salary_min", "salary_max", "salary_currency", "salary_period",
    "start_date", "contract_duration_months", "visa_sponsorship", "education_level", "experience_level",
    "experience_years_min", "valid_through", "organization_type", "impact_area", "languages",
)
PROVIDER_SEARCH = {"jobtech": jobtech.search_jobs}
PROVIDER_COUNTRIES = {"jobtech": frozenset({"SE"})}
APP_ID, SKILL_ID = "jobs", "search"
JOB_FIELDS = (
    "id", "title", "company", "url", "apply_url", "location", "country",
    "remote", "employment_type", "published_at", "description", "salary_min",
    "salary_max", "salary_currency", "salary_period", "provider",
    "sector", "role", "seniority", "organization_type", "work_arrangement",
    "salary_text", "valid_through", "impact", "detail_status",
    "start_date", "contract_duration_months", "visa_sponsorship", "education_level",
    "experience_level", "experience_years_min", "impact_area", "languages",
)
MAX_COUNTRIES = 10
COUNTRY_NAMES = {"GERMANY": "DE", "DEUTSCHLAND": "DE", "SWEDEN": "SE", "SVERIGE": "SE"}
EducationLevel = Literal["none", "vocational", "bachelor", "master", "doctorate"]
ExperienceLevel = Literal["internship", "entry", "mid", "senior", "lead"]
SalaryPeriod = Literal["hour", "day", "week", "month", "year"]


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
    # Listing filters; a listing that does not state the filtered value is excluded
    # (backend/apps/jobs/listing_filters.py).
    visa_sponsorship: bool | None = None
    experience_levels: list[ExperienceLevel] | None = Field(default=None, max_length=5)
    education_levels: list[EducationLevel] | None = Field(default=None, max_length=5)
    start_after: date | None = None
    start_before: date | None = None
    min_contract_duration_months: int | None = Field(default=None, ge=1, le=600)
    max_contract_duration_months: int | None = Field(default=None, ge=1, le=600)
    deadline_after: date | None = None
    min_salary: float | None = Field(default=None, gt=0)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    salary_period: SalaryPeriod | None = None
    languages: list[str] | None = Field(default=None, max_length=10)

    @field_validator("experience_levels", "education_levels", "languages")
    @classmethod
    def _empty_list_is_absent(cls, value: list[str] | None) -> list[str] | None:
        return list(dict.fromkeys(value)) if value else None

    @field_validator("languages")
    @classmethod
    def _iso_languages(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        codes = [iso_language(code) for code in value]
        if None in codes:
            raise ValueError("languages must be ISO 639-1 codes such as en or de.")
        return list(dict.fromkeys(code for code in codes if code))

    @field_validator("salary_currency")
    @classmethod
    def _upper_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def _consistent_ranges(self) -> "JobsSearchRequestItem":
        if self.start_after and self.start_before and self.start_after > self.start_before:
            raise ValueError("start_after must not be later than start_before.")
        low, high = self.min_contract_duration_months, self.max_contract_duration_months
        if low is not None and high is not None and low > high:
            raise ValueError("min_contract_duration_months must not exceed max_contract_duration_months.")
        if self.min_salary is not None and not (self.salary_currency and self.salary_period):
            raise ValueError("min_salary requires salary_currency and salary_period.")
        return self


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
    """Any ISO 3166-1 alpha-2 code; built-in source coverage is checked per provider."""
    country = iso_country(COUNTRY_NAMES.get(value.strip().upper(), value))
    if country is None:
        raise ValueError("Select countries using ISO 3166-1 alpha-2 codes such as DE, SE or US.")
    return country


def _countries(values: Any) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError("Select at least one country (ISO 3166-1 alpha-2 code).")
    selected: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Select countries using ISO 3166-1 alpha-2 codes such as DE, SE or US.")
        country = _country(value)
        if country not in selected:
            selected.append(country)
    if len(selected) > MAX_COUNTRIES:
        raise ValueError(f"Select at most {MAX_COUNTRIES} countries.")
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


def _installed_provider_labels() -> dict[str, str]:
    """Operator-installed providers for this skill from the server registry ({id: name})."""
    return {p.provider_id: p.name for p in get_installed_providers(APP_ID, SKILL_ID)}


def _installed_selector(raw: str, installed: dict[str, str]) -> str | None:
    key = raw.strip().casefold()
    return next((provider_id for provider_id, name in installed.items()
                 if key in (provider_id.casefold(), name.strip().casefold())), None)


@dataclass
class _Selection:
    """Built-in sources and installed provider ids selected for one request.

    ``gaps`` lists built-in limits (provider, code, message) that were skipped
    instead of failing the request because installed providers also answer it.
    """

    builtin: list[str]
    installed: list[str] = field(default_factory=list)
    gaps: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def providers(self) -> list[str]:
        return [*self.builtin, *self.installed]


def _provider_selection(item: JobsSearchRequestItem, countries: list[str]) -> _Selection:
    if item.provider and item.providers is not None:
        raise ValueError("Specify provider or providers, not both.")
    normalized_type = normalize_employment_type(item.employment_type) if item.employment_type else None
    if item.employment_type and normalized_type is None:
        raise ValueError("Unsupported employment type. Use full_time, part_time, internship, contract, or apprenticeship.")
    item.employment_type = normalized_type
    requested = item.providers if item.providers is not None else [item.provider or "auto"]
    if not requested:
        raise ValueError("Provider list cannot be empty.")
    labels = _installed_provider_labels()
    normalized: list[str] = []
    installed: list[str] = []
    for raw in requested:
        name = PROVIDER_ALIASES.get(raw.strip().lower())
        if name is None:
            installed_id = _installed_selector(raw, labels)
            if installed_id is None:
                raise ValueError(f"Unsupported jobs provider. Choose {', '.join(['JobTech', *labels.values()])}.")
            if installed_id not in installed:
                installed.append(installed_id)
        elif name not in normalized:
            normalized.append(name)
    gaps: list[tuple[str, str, str]] = []
    if "auto" in normalized:
        if len(normalized) > 1 or installed:
            raise ValueError("Do not combine auto with explicit providers.")
        normalized = []
        for country in countries:
            if country == "SE" and normalized_type in {None, "full_time", "part_time"}:
                normalized.append("jobtech")
        # Installed providers declare no country coverage: each one receives the
        # request and returns no listings when it is out of scope.
        installed = list(labels)
    else:
        irrelevant = [name for name in normalized if not PROVIDER_COUNTRIES[name].intersection(countries)]
        if irrelevant:
            message = (f"Requested jobs provider {', '.join(irrelevant)} does not cover selected countries "
                       f"{', '.join(countries)}.")
            if not installed:
                raise ValueError(message)
            gaps.extend((name, "coverage_gap", message) for name in irrelevant)
            normalized = [name for name in normalized if name not in irrelevant]
    normalized = list(dict.fromkeys(normalized))
    uncovered = [country for country in countries if not any(country in PROVIDER_COUNTRIES[name] for name in normalized)]
    if uncovered and not installed:
        raise ValueError(f"No requested jobs provider covers {', '.join(uncovered)}.")
    if item.radius_km is not None:
        if not installed:
            raise ValueError("Radius search is unavailable from the permitted jobs providers.")
        gaps.extend((name, "unsupported_filter", "Radius search is unavailable from this job source.")
                    for name in normalized)
        normalized = []
    if normalized_type and "jobtech" in normalized and normalized_type not in {"full_time", "part_time"}:
        message = "JobTech supports only full_time and part_time employment filters."
        if not installed:
            raise ValueError(message)
        gaps.append(("jobtech", "unsupported_filter", message))
        normalized.remove("jobtech")
    return _Selection(normalized, installed, gaps)


def _installed_job(result: dict[str, Any]) -> dict[str, Any]:
    """Shape a contract-validated, server-attributed installed result like a built-in listing."""
    job = {name: result.get(name) for name in JOB_FIELDS}
    job.update({
        "provider_id": result["provider_id"],
        "type": "job_result", "parent_app_skill_type": "app_skill_use",
    })
    return job


def _interleave(sources: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Round-robin merge: first listing of each source, then the second, and so on."""
    merged: list[dict[str, Any]] = []
    for position in range(max((len(source) for source in sources), default=0)):
        merged.extend(source[position] for source in sources if position < len(source))
    return merged


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
                selected = _provider_selection(item, selected_countries).providers
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
            selection = _provider_selection(item, selected_countries)
            providers = selection.builtin
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
        responses, outcomes = await asyncio.gather(
            asyncio.gather(*calls, return_exceptions=True),
            self._run_installed(selection.installed, item, selected_countries, candidate_limit, secrets_manager),
        )
        jobs: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = [
            _warning(request_id, provider, code, message) for provider, code, message in selection.gaps
        ]
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
                        if matches_listing_filters(job, item):
                            jobs.append(job)
            if response and valid_rows == 0:
                warnings.append(_warning(request_id, provider, "invalid_response", "Job source returned unusable listings.", country=country))
                continue
            succeeded += 1

        installed_sources: list[list[dict[str, Any]]] = []
        for outcome in outcomes:
            if outcome.error:
                warnings.append(_warning(request_id, outcome.provider_id, "unavailable", outcome.error))
                continue
            succeeded += 1
            installed_sources.append([
                job for job in map(_installed_job, outcome.results) if matches_listing_filters(job, item)
            ])
        jobs = stable_deduplicate_candidates(_interleave([jobs, *installed_sources]), key=_job_dedup_key)
        if installed_sources:
            # Installed listings may spell the country differently; one URL is one listing.
            jobs = stable_deduplicate_candidates(
                jobs, key=lambda job: normalize_url_for_deduplication(job["url"]))
        if item.relevance_criteria and jobs:
            # Several sources can each return the full candidate limit; the ranker
            # accepts a bounded list. The list is interleaved, so the cut keeps every source.
            jobs = jobs[:MAX_SEARCH_RELEVANCE_CANDIDATES]
            projections = [{key: job.get(key) for key in RANKING_FIELDS} for job in jobs]
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
            # Every source asked for this request; billing re-checks installed ids
            # against the server registry, so a group with a built-in source is charged.
            "providers": selection.providers, "results": jobs, "result_count": len(jobs), "warnings": warnings,
        }
        if succeeded == 0:
            group["error"] = "All requested job sources failed."
        return group

    @staticmethod
    async def _run_installed(
        provider_ids: list[str], item: JobsSearchRequestItem, countries: list[str], limit: int,
        secrets_manager: Any,
    ) -> list[InstalledProviderOutcome]:
        """Run the selected installed providers with one ``jobs.search@1`` input item."""
        if not provider_ids:
            return []
        payload = {**item.model_dump(mode="json", exclude_none=True), "countries": countries, "limit": limit}
        return await run_installed_providers(APP_ID, SKILL_ID, provider_ids, jobs_search_input(payload), secrets_manager)
