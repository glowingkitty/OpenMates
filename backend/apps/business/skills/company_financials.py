"""Business company financials skill.

This skill turns explicit public-company inputs into normalized SEC EDGAR
financial facts. It returns source-aware child embed payloads and is safe for
unattended workflow execution because it reads only public filing data.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.sec_edgar import CompanyFinancialResult, SECEdgarClient, SECProviderError

logger = logging.getLogger(__name__)

MAX_COMPANIES = 10
SUPPORTED_PERIODS = {"latest_annual", "latest_quarter", "annual_history", "quarterly_history"}
SUPPORTED_METRIC_GROUPS = {"summary", "income", "balance_sheet", "cash_flow", "all"}
SUPPORTED_IDENTIFIER_TYPES = {"auto", "ticker", "cik", "company_name"}
DISCOVERY_HINT_PATTERN = re.compile(
    r"\b(companies|producers|makers|manufacturers|sellers|suppliers|industry|sector|market)\b",
    re.IGNORECASE,
)
COMPANY_NAME_HINT_PATTERN = re.compile(
    r"\b(inc|inc\.|corp|corp\.|corporation|co\.|company|ltd|plc|se|ag|nv|sa|llc)\b",
    re.IGNORECASE,
)
TICKER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
CIK_PATTERN = re.compile(r"^\d{1,10}$")


class CompanyFinancialProvider(Protocol):
    provider_name: str

    async def get_company_financials(
        self,
        query: str,
        *,
        identifier_type: str = "auto",
        period: str = "latest_annual",
        metric_group: str = "summary",
        years: int = 3,
    ) -> CompanyFinancialResult: ...


class CompanyFinancialInput(BaseModel):
    query: str
    identifier_type: str = "auto"
    display_name: str | None = None


class CompanyFinancialsResponse(BaseModel):
    success: bool = False
    app_id: str = "business"
    skill_id: str = "company_financials"
    status: str = "finished"
    provider: str = "SEC EDGAR"
    query: str = ""
    period: str = "latest_annual"
    metric_group: str = "summary"
    result_count: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    summary: str | None = None
    error: str | None = None
    error_code: str | None = None
    ignore_fields_for_inference: list[str] = Field(
        default_factory=lambda: [
            "source_url",
            "accession_number",
            "history.source_url",
            "history.accession_number",
        ]
    )


class CompanyFinancialsSkill(BaseSkill):
    """Look up normalized public-company financial facts from SEC EDGAR."""

    async def execute(
        self,
        companies: list[dict[str, Any]] | None = None,
        period: str = "latest_annual",
        metric_group: str = "summary",
        years: int = 3,
        include_sources: bool = True,
        provider_client: CompanyFinancialProvider | None = None,
        **kwargs: Any,
    ) -> CompanyFinancialsResponse:
        del kwargs
        try:
            normalized_companies = _normalize_company_inputs(companies)
            period = _normalize_period(period)
            metric_group = _normalize_metric_group(metric_group)
            years = max(1, min(int(years or 3), 10))
        except ValueError as exc:
            return CompanyFinancialsResponse(
                success=False,
                error=str(exc),
                error_code="invalid_request",
                period=period or "latest_annual",
                metric_group=metric_group or "summary",
            )

        provider = provider_client or SECEdgarClient()
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for company in normalized_companies:
            try:
                result = await provider.get_company_financials(
                    company.query,
                    identifier_type=company.identifier_type,
                    period=period,
                    metric_group=metric_group,
                    years=years,
                )
                payload = result.to_embed_payload()
                if not include_sources:
                    payload.pop("source_url", None)
                    payload.pop("accession_number", None)
                results.append(payload)
            except SECProviderError as exc:
                errors.append({"query": company.query, "code": exc.code, "message": exc.message})
            except Exception as exc:
                logger.error("business.company_financials failed for %s: %s", company.query, exc, exc_info=True)
                errors.append({"query": company.query, "code": "provider_error", "message": "SEC EDGAR lookup failed"})

        if not results:
            error = errors[0]["message"] if errors else "No company financial results were found"
            return CompanyFinancialsResponse(
                success=False,
                query=_query_summary(normalized_companies),
                period=period,
                metric_group=metric_group,
                errors=errors,
                error=error,
                error_code=errors[0]["code"] if errors else "no_results",
            )

        period_label = period.replace("_", " ")
        summary = f"SEC EDGAR {period_label} financials for {_query_summary(normalized_companies)}"
        if errors:
            summary += f" ({len(errors)} unresolved)"
        return CompanyFinancialsResponse(
            success=True,
            query=_query_summary(normalized_companies),
            period=period,
            metric_group=metric_group,
            result_count=len(results),
            results=results,
            errors=errors,
            summary=summary,
        )

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        companies = request.get("companies") or []
        queries = [str(item.get("query") or "").strip() for item in companies if isinstance(item, dict)]
        return {
            "provider": "SEC EDGAR",
            "providers": ["SEC EDGAR"],
            "query": ", ".join(query for query in queries if query),
        }


def _normalize_company_inputs(companies: list[dict[str, Any]] | None) -> list[CompanyFinancialInput]:
    if not companies:
        raise ValueError("Get company financials requires at least one explicit company input")
    if len(companies) > MAX_COMPANIES:
        raise ValueError(f"Get company financials supports at most {MAX_COMPANIES} companies")

    normalized: list[CompanyFinancialInput] = []
    for raw_company in companies:
        company = CompanyFinancialInput.model_validate(raw_company)
        company.query = company.query.strip()
        company.identifier_type = company.identifier_type.strip().lower() if company.identifier_type else "auto"
        if company.identifier_type not in SUPPORTED_IDENTIFIER_TYPES:
            raise ValueError(f"Unsupported identifier type: {company.identifier_type}")
        if not company.query:
            raise ValueError("Each company financials input requires a non-empty query")
        if _looks_like_discovery_query(company.query, company.identifier_type):
            raise ValueError("Get company financials requires an explicit ticker, CIK, or company name; use Web Research for company discovery")
        normalized.append(company)
    return normalized


def _looks_like_discovery_query(query: str, identifier_type: str) -> bool:
    if identifier_type in {"ticker", "cik"}:
        return False
    stripped = query.strip()
    if CIK_PATTERN.fullmatch(stripped) or TICKER_PATTERN.fullmatch(stripped):
        return False
    if COMPANY_NAME_HINT_PATTERN.search(stripped):
        return False
    return bool(DISCOVERY_HINT_PATTERN.search(stripped))


def _normalize_period(period: str) -> str:
    normalized = (period or "latest_annual").strip().lower()
    if normalized not in SUPPORTED_PERIODS:
        raise ValueError(f"Unsupported financial period: {period}")
    return normalized


def _normalize_metric_group(metric_group: str) -> str:
    normalized = (metric_group or "summary").strip().lower()
    if normalized not in SUPPORTED_METRIC_GROUPS:
        raise ValueError(f"Unsupported financial metric group: {metric_group}")
    return normalized


def _query_summary(companies: list[CompanyFinancialInput]) -> str:
    return ", ".join(company.display_name or company.query for company in companies)
