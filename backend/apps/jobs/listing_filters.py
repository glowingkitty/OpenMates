"""Strict listing filters of a jobs search request, applied to every source's listings.

Rule for every filter: a listing passes only when it states the filtered value
and the value matches. A listing that does not state it (null) is excluded while
the filter is set. Sources that cannot provide a value therefore return no
listings for that filter; the request still runs them (billing is unchanged).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from backend.shared.providers.jobs.common import normalize_employment_type

# Month and year salaries convert into each other; other periods must match exactly.
_MONTHS_PER_PERIOD = {"month": 1, "year": 12}


class ListingFilters(Protocol):
    """The filter fields of ``JobsSearchRequestItem`` (structural, to avoid an import cycle)."""

    remote: bool | None
    employment_type: str | None
    max_days_old: int | None
    visa_sponsorship: bool | None
    experience_levels: list[str] | None
    education_levels: list[str] | None
    start_before: date | None
    start_after: date | None
    min_contract_duration_months: int | None
    max_contract_duration_months: int | None
    deadline_after: date | None
    min_salary: float | None
    salary_currency: str | None
    salary_period: str | None
    languages: list[str] | None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _date(value: Any) -> date | None:
    parsed = _datetime(value)
    return parsed.date() if parsed is not None else None


def _salary_ceiling(job: dict[str, Any], currency: str, period: str) -> float | None:
    """The listing's highest stated salary in ``currency`` per ``period``, or None when not comparable."""
    amount = job.get("salary_max") if job.get("salary_max") is not None else job.get("salary_min")
    job_currency, job_period = job.get("salary_currency"), job.get("salary_period")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        return None
    if not isinstance(job_currency, str) or job_currency.strip().upper() != currency:
        return None
    if job_period == period:
        return float(amount)
    if job_period in _MONTHS_PER_PERIOD and period in _MONTHS_PER_PERIOD:
        return float(amount) * _MONTHS_PER_PERIOD[period] / _MONTHS_PER_PERIOD[job_period]
    return None


def _within(value: Any, low: Any, high: Any) -> bool:
    if value is None:
        return False
    return (low is None or value >= low) and (high is None or value <= high)


def matches_listing_filters(job: dict[str, Any], item: ListingFilters) -> bool:
    """True when ``job`` states every filtered value of ``item`` and each one matches."""
    if item.remote is not None and job.get("remote") is not item.remote:
        return False
    if item.employment_type and normalize_employment_type(job.get("employment_type")) != item.employment_type:
        return False
    if item.max_days_old is not None:
        published = _datetime(job.get("published_at"))
        if published is None or published < datetime.now(timezone.utc) - timedelta(days=item.max_days_old):
            return False
    if item.visa_sponsorship is not None and job.get("visa_sponsorship") is not item.visa_sponsorship:
        return False
    if item.experience_levels and job.get("experience_level") not in item.experience_levels:
        return False
    if item.education_levels and job.get("education_level") not in item.education_levels:
        return False
    if (item.start_before or item.start_after) and not _within(
            _date(job.get("start_date")), item.start_after, item.start_before):
        return False
    if item.min_contract_duration_months is not None or item.max_contract_duration_months is not None:
        duration = job.get("contract_duration_months")
        if isinstance(duration, bool) or not isinstance(duration, int) or not _within(
                duration, item.min_contract_duration_months, item.max_contract_duration_months):
            return False
    if item.deadline_after and not _within(_date(job.get("valid_through")), item.deadline_after, None):
        return False
    if item.min_salary is not None and item.salary_currency and item.salary_period:
        ceiling = _salary_ceiling(job, item.salary_currency, item.salary_period)
        if ceiling is None or ceiling < item.min_salary:
            return False
    if item.languages:
        stated = job.get("languages")
        if not isinstance(stated, list) or not set(stated).intersection(item.languages):
            return False
    return True
