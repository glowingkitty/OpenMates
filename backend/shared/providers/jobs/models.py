"""Provider-independent job listing fields."""

from typing import TypedDict


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
