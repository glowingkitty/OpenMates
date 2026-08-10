"""Pure SEC EDGAR API wrapper for public company filing data.

The SEC APIs do not need credentials, but they do require responsible automated
access. This client centralizes User-Agent handling, lightweight throttling,
provider errors, and normalization of US-GAAP/IFRS concepts into OpenMates'
Business app financial result shape.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Mapping
from datetime import date
from typing import Any

import httpx

from backend.shared.providers.sec_edgar.models import (
    CompanyFinancialPeriod,
    CompanyFinancialResult,
    ResolvedCompany,
    SECCompanyNotFoundError,
    SECHttpError,
    SECProviderError,
)

logger = logging.getLogger(__name__)

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_USER_AGENT = "OpenMates contact@example.com"
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_REQUESTS_PER_SECOND = 10
CIK_PATTERN = re.compile(r"^\d{1,10}$")
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
SUPPORTED_PERIODS = {"latest_annual", "latest_quarter", "annual_history", "quarterly_history"}
SUPPORTED_METRIC_GROUPS = {"summary", "income", "balance_sheet", "cash_flow", "all"}

METRIC_CONCEPTS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "revenue": (
        ("us-gaap", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")),
        ("ifrs-full", ("Revenue",)),
    ),
    "net_income": (
        ("us-gaap", ("NetIncomeLoss",)),
        ("ifrs-full", ("ProfitLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity")),
    ),
    "gross_profit": (
        ("us-gaap", ("GrossProfit",)),
        ("ifrs-full", ("GrossProfit",)),
    ),
    "operating_income": (
        ("us-gaap", ("OperatingIncomeLoss",)),
        ("ifrs-full", ("ProfitLossFromOperatingActivities",)),
    ),
    "assets": (
        ("us-gaap", ("Assets",)),
        ("ifrs-full", ("Assets",)),
    ),
    "liabilities": (
        ("us-gaap", ("Liabilities",)),
        ("ifrs-full", ("Liabilities",)),
    ),
    "equity": (
        ("us-gaap", ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")),
        ("ifrs-full", ("Equity", "EquityAttributableToOwnersOfParent")),
    ),
    "operating_cash_flow": (
        ("us-gaap", ("NetCashProvidedByUsedInOperatingActivities",)),
        ("ifrs-full", ("CashFlowsFromUsedInOperatingActivities",)),
    ),
}

METRIC_GROUPS: dict[str, tuple[str, ...]] = {
    "summary": ("revenue", "net_income"),
    "income": ("revenue", "gross_profit", "operating_income", "net_income"),
    "balance_sheet": ("assets", "liabilities", "equity"),
    "cash_flow": ("operating_cash_flow",),
    "all": tuple(METRIC_CONCEPTS),
}


class SECEdgarClient:
    """Small async client for SEC EDGAR public JSON endpoints."""

    provider_name = "SEC EDGAR"

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        ticker_mapping: Mapping[str, Any] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.user_agent = (user_agent or os.getenv("SEC_EDGAR_USER_AGENT") or DEFAULT_USER_AGENT).strip()
        if not self.user_agent:
            raise ValueError("SEC EDGAR User-Agent must not be empty")
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._ticker_mapping = dict(ticker_mapping) if ticker_mapping is not None else None
        self._company_cache: dict[str, ResolvedCompany] = {}
        self._json_cache: dict[str, Any] = {}
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def resolve_company(self, query: str, *, identifier_type: str = "auto") -> dict[str, str | None]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise SECCompanyNotFoundError(query)
        cache_key = f"{identifier_type}:{normalized_query.lower()}"
        cached = self._company_cache.get(cache_key)
        if cached:
            return cached.model_dump()

        mapping = await self._get_ticker_mapping()
        resolved = _resolve_company_from_mapping(mapping, normalized_query, identifier_type=identifier_type)
        self._company_cache[cache_key] = resolved
        return resolved.model_dump()

    async def get_company_facts(self, cik: str) -> dict[str, Any]:
        return await self._get_json(SEC_COMPANY_FACTS_URL.format(cik=_normalize_cik(cik)))

    async def get_submissions(self, cik: str) -> dict[str, Any]:
        return await self._get_json(SEC_SUBMISSIONS_URL.format(cik=_normalize_cik(cik)))

    async def get_company_financials(
        self,
        query: str,
        *,
        identifier_type: str = "auto",
        period: str = "latest_annual",
        metric_group: str = "summary",
        years: int = 3,
    ) -> CompanyFinancialResult:
        company = await self.resolve_company(query, identifier_type=identifier_type)
        facts = await self.get_company_facts(str(company["cik"]))
        return normalize_company_financials(
            facts,
            company=company,
            period=period,
            metric_group=metric_group,
            years=years,
        )

    async def _get_ticker_mapping(self) -> Mapping[str, Any]:
        if self._ticker_mapping is None:
            self._ticker_mapping = await self._get_json(SEC_TICKER_URL)
        return self._ticker_mapping

    async def _get_json(self, url: str) -> Any:
        cached = self._json_cache.get(url)
        if cached is not None:
            return cached
        await self._throttle()
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout_seconds)
        close_client = self._http_client is None
        try:
            response = await client.get(
                url,
                headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"},
            )
            response.raise_for_status()
            data = response.json()
            self._json_cache[url] = data
            return data
        except httpx.HTTPStatusError as exc:
            logger.warning("SEC EDGAR HTTP error for %s: %s", url, exc.response.status_code)
            raise SECHttpError("provider_http_error", f"SEC EDGAR returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            logger.warning("SEC EDGAR request failed for %s: %s", url, exc)
            raise SECHttpError("provider_unavailable", "SEC EDGAR request failed") from exc
        finally:
            if close_client:
                await client.aclose()

    async def _throttle(self) -> None:
        async with self._rate_lock:
            min_interval = 1.0 / MAX_REQUESTS_PER_SECOND
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            self._last_request_at = time.monotonic()


def normalize_company_financials(
    company_facts: Mapping[str, Any],
    *,
    company: Mapping[str, str | None],
    period: str,
    metric_group: str,
    years: int,
) -> CompanyFinancialResult:
    """Normalize SEC companyfacts into a stable app-skill result."""
    if period not in SUPPORTED_PERIODS:
        raise SECProviderError("invalid_request", f"Unsupported financial period: {period}")
    if metric_group not in SUPPORTED_METRIC_GROUPS:
        raise SECProviderError("invalid_request", f"Unsupported metric group: {metric_group}")

    cik = _normalize_cik(str(company.get("cik") or company_facts.get("cik") or ""))
    company_name = str(company.get("name") or company_facts.get("entityName") or "Unknown company")
    ticker = company.get("ticker") or company_facts.get("_openmates_ticker")
    selected_metrics = METRIC_GROUPS[metric_group]
    target_period_type = "quarter" if "quarter" in period else "annual"
    facts_by_metric = {
        metric: _extract_metric_facts(company_facts, metric, period_type=target_period_type)
        for metric in selected_metrics
    }
    periods = _merge_metric_facts(facts_by_metric, selected_metrics)
    capped_years = max(1, min(int(years or 3), 10))

    if period in {"annual_history", "quarterly_history"}:
        history = periods[-capped_years:]
        latest = history[-1] if history else CompanyFinancialPeriod(period_type=target_period_type)
        notes = list(latest.notes)
        for metric in selected_metrics:
            if all(getattr(item, metric) is None for item in history):
                notes.append(f"{metric} was not available in standardized SEC facts")
        return CompanyFinancialResult(
            **latest.model_dump(exclude={"notes"}),
            company=company_name,
            ticker=ticker,
            cik=cik,
            history=history,
            notes=notes,
        )

    latest = periods[-1] if periods else CompanyFinancialPeriod(period_type=target_period_type)
    notes = list(latest.notes)
    for metric in selected_metrics:
        if getattr(latest, metric) is None:
            notes.append(f"{metric} was not available in standardized SEC facts")
    return CompanyFinancialResult(
        **latest.model_dump(exclude={"notes"}),
        company=company_name,
        ticker=ticker,
        cik=cik,
        notes=notes,
    )


def _resolve_company_from_mapping(mapping: Mapping[str, Any], query: str, *, identifier_type: str) -> ResolvedCompany:
    query_stripped = query.strip()
    if identifier_type not in {"auto", "ticker", "cik", "company_name"}:
        raise SECProviderError("invalid_request", f"Unsupported identifier type: {identifier_type}", query=query)

    rows = [row for row in mapping.values() if isinstance(row, Mapping)]
    if identifier_type in {"auto", "cik"} and CIK_PATTERN.fullmatch(query_stripped):
        cik = _normalize_cik(query_stripped)
        for row in rows:
            if _normalize_cik(str(row.get("cik_str") or "")) == cik:
                return _resolved_from_row(row)
        return ResolvedCompany(cik=cik, ticker=None, name=f"CIK {cik}")

    upper_query = query_stripped.upper()
    if identifier_type in {"auto", "ticker"} and TICKER_PATTERN.fullmatch(upper_query):
        for row in rows:
            if str(row.get("ticker") or "").upper() == upper_query:
                return _resolved_from_row(row)

    if identifier_type in {"auto", "company_name"}:
        normalized_name = _normalize_name(query_stripped)
        for row in rows:
            if _normalize_name(str(row.get("title") or "")) == normalized_name:
                return _resolved_from_row(row)

    raise SECCompanyNotFoundError(query)


def _resolved_from_row(row: Mapping[str, Any]) -> ResolvedCompany:
    return ResolvedCompany(
        cik=_normalize_cik(str(row.get("cik_str") or "")),
        ticker=str(row.get("ticker") or "").upper() or None,
        name=str(row.get("title") or "").strip() or "Unknown company",
    )


def _extract_metric_facts(company_facts: Mapping[str, Any], metric: str, *, period_type: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    facts = company_facts.get("facts") if isinstance(company_facts.get("facts"), Mapping) else {}
    for taxonomy, concepts in METRIC_CONCEPTS.get(metric, ()):
        taxonomy_facts = facts.get(taxonomy) if isinstance(facts, Mapping) else None
        if not isinstance(taxonomy_facts, Mapping):
            continue
        for concept in concepts:
            concept_data = taxonomy_facts.get(concept)
            if not isinstance(concept_data, Mapping):
                continue
            units = concept_data.get("units")
            if not isinstance(units, Mapping):
                continue
            for unit, items in units.items():
                if unit not in {"USD", "EUR"} or not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, Mapping) or not _matches_period_type(item, period_type):
                        continue
                    normalized = _normalize_fact(item, unit=str(unit), metric=metric, taxonomy=taxonomy, concept=concept)
                    if normalized:
                        output.append(normalized)
            if output:
                return _dedupe_facts(output)
    return _dedupe_facts(output)


def _matches_period_type(item: Mapping[str, Any], period_type: str) -> bool:
    form = str(item.get("form") or "")
    if form not in {"10-K", "10-Q", "20-F", "40-F", "6-K"}:
        return False
    fp = str(item.get("fp") or "")
    if period_type == "annual" and fp != "FY":
        return False
    if period_type == "quarter" and fp not in {"Q1", "Q2", "Q3", "Q4"}:
        return False
    start = item.get("start")
    end = item.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return False
    days = _date_days(start, end)
    if days is None:
        return False
    return 300 <= days <= 430 if period_type == "annual" else 60 <= days <= 120


def _normalize_fact(
    item: Mapping[str, Any],
    *,
    unit: str,
    metric: str,
    taxonomy: str,
    concept: str,
) -> dict[str, Any] | None:
    if item.get("val") is None:
        return None
    period_start = str(item.get("start") or "") or None
    period_end = str(item.get("end") or "") or None
    filed = str(item.get("filed") or "") or None
    accession_number = str(item.get("accn") or "") or None
    return {
        "metric": metric,
        "value": item.get("val"),
        "period_start": period_start,
        "period_end": period_end,
        "fiscal_year": _safe_int(item.get("fy")),
        "fiscal_quarter": str(item.get("fp") or "") or None,
        "filed": filed,
        "form": str(item.get("form") or "") or None,
        "currency": unit,
        "accession_number": accession_number,
        "source_url": _source_url(item.get("accn"), item.get("cik") or None),
        "taxonomy": taxonomy,
        "concept": concept,
    }


def _dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_period: dict[tuple[Any, ...], dict[str, Any]] = {}
    for fact in facts:
        key = (fact.get("period_start"), fact.get("period_end"), fact.get("fiscal_year"), fact.get("fiscal_quarter"))
        current = latest_by_period.get(key)
        if current is None or str(fact.get("filed") or "") >= str(current.get("filed") or ""):
            latest_by_period[key] = fact
    return sorted(latest_by_period.values(), key=lambda item: (str(item.get("period_end") or ""), str(item.get("filed") or "")))


def _merge_metric_facts(
    facts_by_metric: Mapping[str, list[dict[str, Any]]],
    selected_metrics: tuple[str, ...],
) -> list[CompanyFinancialPeriod]:
    periods: dict[tuple[Any, ...], dict[str, Any]] = {}
    for metric, facts in facts_by_metric.items():
        for fact in facts:
            key = (fact.get("period_start"), fact.get("period_end"), fact.get("fiscal_year"), fact.get("fiscal_quarter"))
            row = periods.setdefault(
                key,
                {
                    "period_type": "quarter" if str(fact.get("fiscal_quarter") or "").startswith("Q") else "annual",
                    "fiscal_year": fact.get("fiscal_year"),
                    "fiscal_quarter": fact.get("fiscal_quarter"),
                    "period_start": fact.get("period_start"),
                    "period_end": fact.get("period_end"),
                    "filed": fact.get("filed"),
                    "form": fact.get("form"),
                    "currency": fact.get("currency"),
                    "accession_number": fact.get("accession_number"),
                    "source_url": None,
                    "confidence": "high",
                    "notes": [],
                },
            )
            row[metric] = fact.get("value")
            row["filed"] = max(str(row.get("filed") or ""), str(fact.get("filed") or "")) or None
            row["form"] = fact.get("form") or row.get("form")
            row["currency"] = fact.get("currency") or row.get("currency")
            row["accession_number"] = fact.get("accession_number") or row.get("accession_number")
            row["source_url"] = fact.get("source_url") or row.get("source_url")
    merged = []
    for row in periods.values():
        for metric in selected_metrics:
            row.setdefault(metric, None)
        if row.get("source_url") is None and row.get("accession_number"):
            row["source_url"] = _source_url(row.get("accession_number"), None)
        merged.append(CompanyFinancialPeriod.model_validate(row))
    return sorted(merged, key=lambda item: (item.period_end or "", item.filed or ""))


def _source_url(accession_number: Any, cik: Any) -> str | None:
    if not accession_number:
        return None
    accn = str(accession_number)
    accession_folder = accn.replace("-", "")
    cik_part = str(int(str(cik))) if cik and CIK_PATTERN.fullmatch(str(cik).strip()) else ""
    if not cik_part:
        return f"https://www.sec.gov/Archives/edgar/data/{accession_folder}/"
    return f"https://www.sec.gov/Archives/edgar/data/{cik_part}/{accession_folder}/"


def _normalize_cik(value: str) -> str:
    stripped = str(value or "").strip()
    if not CIK_PATTERN.fullmatch(stripped):
        raise SECProviderError("invalid_request", f"Invalid SEC CIK: {value}")
    return stripped.zfill(10)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _date_days(start: str, end: str) -> int | None:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
