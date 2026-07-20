"""SEC EDGAR provider models.

These schemas define OpenMates' normalized public-company financial contract.
They intentionally hide raw SEC taxonomy details from app skills, workflows,
CLI, SDKs, and embeds while preserving filing source metadata for auditability.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SECProviderError(Exception):
    """Base typed error for SEC EDGAR provider failures."""

    def __init__(self, code: str, message: str, *, query: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.query = query

    def as_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.query:
            payload["query"] = self.query
        return payload


class SECCompanyNotFoundError(SECProviderError):
    """Raised when a ticker, CIK, or exact company name is unavailable."""

    def __init__(self, query: str) -> None:
        super().__init__(
            "company_not_found",
            f"Could not resolve company in SEC EDGAR: {query}",
            query=query,
        )


class SECHttpError(SECProviderError):
    """Raised when data.sec.gov or sec.gov returns an HTTP/provider error."""

    def __init__(self, code: str, message: str, *, query: str | None = None) -> None:
        super().__init__(code, message, query=query)


class ResolvedCompany(BaseModel):
    cik: str
    ticker: str | None = None
    name: str


class CompanyFinancialPeriod(BaseModel):
    period_type: str
    fiscal_year: int | None = None
    fiscal_quarter: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    filed: str | None = None
    form: str | None = None
    currency: str | None = None
    revenue: int | float | None = None
    gross_profit: int | float | None = None
    operating_income: int | float | None = None
    net_income: int | float | None = None
    operating_cash_flow: int | float | None = None
    assets: int | float | None = None
    liabilities: int | float | None = None
    equity: int | float | None = None
    source_url: str | None = None
    accession_number: str | None = None
    confidence: str = "medium"
    notes: list[str] = Field(default_factory=list)


class CompanyFinancialResult(CompanyFinancialPeriod):
    company: str
    ticker: str | None = None
    cik: str
    country: str | None = None
    exchange: str | None = None
    history: list[CompanyFinancialPeriod] | None = None

    def to_embed_payload(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        payload["type"] = "company_financial_result"
        payload["parent_app_skill_type"] = "app_skill_use"
        return payload
