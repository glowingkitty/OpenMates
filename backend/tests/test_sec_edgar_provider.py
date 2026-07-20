"""SEC EDGAR provider contract tests.

These tests protect the no-key public filing-data provider boundary for the
Business app. They use fixture payloads so normal test runs do not hit SEC
fair-access limits, while still asserting the normalized fields that live smoke
checks must later prove against data.sec.gov.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.shared.providers.sec_edgar import (
    SECCompanyNotFoundError,
    SECEdgarClient,
    normalize_company_financials,
)


CALM_CIK = "0000016160"
MU_CIK = "0000723125"
SAP_CIK = "0001000184"


def _fact(
    value: int,
    *,
    concept: str,
    unit: str = "USD",
    start: str = "2024-01-01",
    end: str = "2024-12-31",
    filed: str = "2025-02-20",
    fy: int = 2024,
    fp: str = "FY",
    form: str = "10-K",
    accn: str = "0000000000-25-000001",
) -> dict[str, Any]:
    return {
        "concept": concept,
        "units": {
            unit: [
                {
                    "val": value,
                    "start": start,
                    "end": end,
                    "fy": fy,
                    "fp": fp,
                    "form": form,
                    "filed": filed,
                    "accn": accn,
                }
            ]
        },
    }


def _company_facts(
    *,
    cik: str = CALM_CIK,
    entity_name: str = "Cal-Maine Foods, Inc.",
    ticker: str = "CALM",
    taxonomy: str = "us-gaap",
    revenue_concept: str = "RevenueFromContractWithCustomerExcludingAssessedTax",
    profit_concept: str = "NetIncomeLoss",
    revenue: int = 4_261_885_000,
    profit: int = 1_220_048_000,
    unit: str = "USD",
    form: str = "10-K",
    fy: int = 2025,
    start: str = "2024-06-02",
    end: str = "2025-05-31",
    filed: str = "2025-07-22",
) -> dict[str, Any]:
    return {
        "cik": int(cik),
        "entityName": entity_name,
        "facts": {
            taxonomy: {
                revenue_concept: _fact(
                    revenue,
                    concept=revenue_concept,
                    unit=unit,
                    start=start,
                    end=end,
                    filed=filed,
                    fy=fy,
                    form=form,
                    accn="0001562762-25-000170",
                ),
                profit_concept: _fact(
                    profit,
                    concept=profit_concept,
                    unit=unit,
                    start=start,
                    end=end,
                    filed=filed,
                    fy=fy,
                    form=form,
                    accn="0001562762-25-000170",
                ),
                "Assets": _fact(2_500_000_000, concept="Assets", unit=unit, start=start, end=end, filed=filed, fy=fy, form=form),
            }
        },
        "_openmates_ticker": ticker,
    }


@pytest.mark.anyio
async def test_ticker_to_cik_resolution_uses_cached_sec_mapping() -> None:
    client = SECEdgarClient(
        user_agent="OpenMates tests contact@example.com",
        ticker_mapping={
            "0": {"ticker": "CALM", "title": "Cal-Maine Foods, Inc.", "cik_str": 16160},
            "1": {"ticker": "MU", "title": "Micron Technology, Inc.", "cik_str": 723125},
        },
    )

    assert await client.resolve_company("calm") == {
        "cik": CALM_CIK,
        "ticker": "CALM",
        "name": "Cal-Maine Foods, Inc.",
    }
    assert await client.resolve_company("0000723125") == {
        "cik": MU_CIK,
        "ticker": "MU",
        "name": "Micron Technology, Inc.",
    }


@pytest.mark.anyio
async def test_unknown_ticker_returns_typed_error() -> None:
    client = SECEdgarClient(
        user_agent="OpenMates tests contact@example.com",
        ticker_mapping={"0": {"ticker": "CALM", "title": "Cal-Maine Foods, Inc.", "cik_str": 16160}},
    )

    with pytest.raises(SECCompanyNotFoundError) as exc_info:
        await client.resolve_company("NOTAREALTICKER")

    assert exc_info.value.code == "company_not_found"
    assert "NOTAREALTICKER" in exc_info.value.message


def test_companyfacts_normalization_returns_latest_annual_revenue_profit_and_source() -> None:
    result = normalize_company_financials(
        _company_facts(),
        company={"cik": CALM_CIK, "ticker": "CALM", "name": "Cal-Maine Foods, Inc."},
        period="latest_annual",
        metric_group="summary",
        years=1,
    )

    assert result.company == "Cal-Maine Foods, Inc."
    assert result.ticker == "CALM"
    assert result.cik == CALM_CIK
    assert result.period_type == "annual"
    assert result.fiscal_year == 2025
    assert result.period_start == "2024-06-02"
    assert result.period_end == "2025-05-31"
    assert result.filed == "2025-07-22"
    assert result.form == "10-K"
    assert result.currency == "USD"
    assert result.revenue == 4_261_885_000
    assert result.net_income == 1_220_048_000
    assert result.source_url.endswith("/000156276225000170/")
    assert result.confidence == "high"


def test_ifrs_normalization_supports_foreign_sec_filers_like_sap() -> None:
    result = normalize_company_financials(
        _company_facts(
            cik=SAP_CIK,
            entity_name="SAP SE",
            ticker="SAP",
            taxonomy="ifrs-full",
            revenue_concept="Revenue",
            profit_concept="ProfitLoss",
            revenue=36_800_000_000,
            profit=7_326_000_000,
            unit="EUR",
            form="20-F",
            fy=2025,
            start="2025-01-01",
            end="2025-12-31",
            filed="2026-02-26",
        ),
        company={"cik": SAP_CIK, "ticker": "SAP", "name": "SAP SE"},
        period="latest_annual",
        metric_group="summary",
        years=1,
    )

    assert result.company == "SAP SE"
    assert result.form == "20-F"
    assert result.currency == "EUR"
    assert result.revenue == 36_800_000_000
    assert result.net_income == 7_326_000_000


def test_annual_history_deduplicates_restatements_and_caps_year_count() -> None:
    facts = _company_facts(revenue=37_378_000_000, profit=8_539_000_000, ticker="MU", entity_name="Micron Technology, Inc.")
    revenue_units = facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    profit_units = facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]
    old_fact = {
        "val": 25_111_000_000,
        "start": "2023-08-31",
        "end": "2024-08-29",
        "fy": 2024,
        "fp": "FY",
        "form": "10-K",
        "filed": "2024-09-27",
        "accn": "0000723125-24-000034",
    }
    revenue_units.append(dict(old_fact))
    profit_units.append({**old_fact, "val": 778_000_000})
    revenue_units.append({**old_fact, "val": 25_111_000_000, "filed": "2025-10-03"})
    profit_units.append({**old_fact, "val": 778_000_000, "filed": "2025-10-03"})

    result = normalize_company_financials(
        facts,
        company={"cik": MU_CIK, "ticker": "MU", "name": "Micron Technology, Inc."},
        period="annual_history",
        metric_group="income",
        years=2,
    )

    assert result.history is not None
    assert [(item.fiscal_year, item.revenue, item.net_income) for item in result.history] == [
        (2024, 25_111_000_000, 778_000_000),
        (2025, 37_378_000_000, 8_539_000_000),
    ]


def test_missing_metric_stays_null_with_note() -> None:
    facts = _company_facts()
    del facts["facts"]["us-gaap"]["NetIncomeLoss"]

    result = normalize_company_financials(
        facts,
        company={"cik": CALM_CIK, "ticker": "CALM", "name": "Cal-Maine Foods, Inc."},
        period="latest_annual",
        metric_group="summary",
        years=1,
    )

    assert result.revenue == 4_261_885_000
    assert result.net_income is None
    assert any("net_income" in note for note in result.notes)
