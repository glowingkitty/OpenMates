"""Stable, JSON-safe models for anonymous Gandi shop domain search."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def checked_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DomainPriceTier:
    duration_unit: str | None = None
    min_duration: int | None = None
    max_duration: int | None = None
    price_before_taxes: float | None = None
    price_after_taxes: float | None = None
    price: float | None = None
    discount: bool | None = None
    normal_price_before_taxes: float | None = None
    normal_price_after_taxes: float | None = None
    normal_price: float | None = None
    type: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    features: list[Any] = field(default_factory=list)


@dataclass
class DomainPriceProduct:
    process: str
    name: str | None = None
    status: str | None = None
    tiers: list[DomainPriceTier] = field(default_factory=list)
    taxes: list[dict[str, Any]] = field(default_factory=list)
    phases: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DomainResult:
    domain_ascii: str
    domain_unicode: str
    availability: str = "unknown"
    provider: str = "Gandi"
    premium: bool | None = None
    reserved: bool | None = None
    corporate: bool | None = None
    restriction: str | None = None
    tld: str | None = None
    allow_lang: bool | None = None
    phase: str | None = None
    categories: list[str] = field(default_factory=list)
    registration: list[DomainPriceProduct] = field(default_factory=list)
    renewal: list[DomainPriceProduct] = field(default_factory=list)
    currency: str = "EUR"
    country: str = "DE"
    taxes: list[dict[str, Any]] = field(default_factory=list)
    grid: str | None = None
    checked_at: str = field(default_factory=checked_now)
    url: str = ""
    error: str | None = None
    retry_after: str | None = None
    pricing_status: str = "unknown"
    pricing_error: str | None = None
    provider_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class DomainSearchResult:
    query: str
    results: list[DomainResult] = field(default_factory=list)
    provider: str = "Gandi"
    currency: str = "EUR"
    country: str = "DE"
    checked_at: str = field(default_factory=checked_now)
    partial: bool = False
    error: str | None = None
    retry_after: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> dict[str, Any]:
        return self.to_dict()
