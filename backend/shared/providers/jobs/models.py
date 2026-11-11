"""Provider-independent job listing fields."""

from typing import NotRequired, TypedDict


class JobListing(TypedDict):
    id: str
    title: str
    company: str | None
    url: str
    apply_url: str | None
    location: str | None
    country: str
    remote: bool | None
    employment_type: str | None
    published_at: str | None
    description: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None
    provider: str
    sector: NotRequired[str | None]
    role: NotRequired[str | None]
    seniority: NotRequired[str | None]
    organization_type: NotRequired[str | None]
    work_arrangement: NotRequired[str | None]
    salary_text: NotRequired[str | None]
    valid_through: NotRequired[str | None]
    impact: NotRequired[str | None]
    detail_status: NotRequired[str | None]
    # Normalized listing facts used by request filters; None when the source does not state them.
    start_date: NotRequired[str | None]
    contract_duration_months: NotRequired[int | None]
    visa_sponsorship: NotRequired[bool | None]
    education_level: NotRequired[str | None]
    experience_level: NotRequired[str | None]
    experience_years_min: NotRequired[int | None]
    impact_area: NotRequired[str | None]
    languages: NotRequired[list[str] | None]
