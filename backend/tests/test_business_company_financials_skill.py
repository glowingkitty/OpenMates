"""Business company financials skill contract tests.

The Business skill wraps the SEC EDGAR provider in app-skill output suitable for
chat, embeds, CLI, SDKs, and workflows. These tests use fake providers so skill
behavior stays deterministic and does not depend on external network access.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.apps.business.skills.company_financials import CompanyFinancialsSkill
from backend.shared.providers.sec_edgar import CompanyFinancialResult, SECCompanyNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _skill() -> CompanyFinancialsSkill:
    return CompanyFinancialsSkill(
        app=None,
        app_id="business",
        skill_id="company_financials",
        skill_name="Get company financials",
        skill_description="Look up public-company financial facts.",
    )


def _result(ticker: str = "CALM", company: str = "Cal-Maine Foods, Inc.") -> CompanyFinancialResult:
    return CompanyFinancialResult(
        company=company,
        ticker=ticker,
        cik="0000016160",
        period_type="annual",
        fiscal_year=2025,
        period_start="2024-06-02",
        period_end="2025-05-31",
        filed="2025-07-22",
        form="10-K",
        currency="USD",
        revenue=4_261_885_000,
        net_income=1_220_048_000,
        source_url="https://www.sec.gov/Archives/edgar/data/16160/000156276225000170/",
        accession_number="0001562762-25-000170",
        confidence="high",
    )


class FakeProvider:
    provider_name = "SEC EDGAR"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get_company_financials(
        self,
        query: str,
        *,
        identifier_type: str = "auto",
        period: str = "latest_annual",
        metric_group: str = "summary",
        years: int = 3,
    ) -> CompanyFinancialResult:
        self.calls.append(
            {
                "query": query,
                "identifier_type": identifier_type,
                "period": period,
                "metric_group": metric_group,
                "years": years,
            }
        )
        if query == "BROKEN":
            raise SECCompanyNotFoundError(query)
        return _result(ticker=query.upper(), company=f"{query.upper()} Corp")


@pytest.mark.asyncio
async def test_company_financials_returns_parent_and_child_payloads() -> None:
    provider = FakeProvider()

    response = await _skill().execute(
        companies=[{"query": "CALM"}],
        period="latest_annual",
        metric_group="summary",
        years=1,
        provider_client=provider,
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["app_id"] == "business"
    assert payload["skill_id"] == "company_financials"
    assert payload["provider"] == "SEC EDGAR"
    assert payload["result_count"] == 1
    assert "latest annual" in payload["summary"].lower()
    assert provider.calls == [
        {
            "query": "CALM",
            "identifier_type": "auto",
            "period": "latest_annual",
            "metric_group": "summary",
            "years": 1,
        }
    ]
    child = payload["results"][0]
    assert child["type"] == "company_financial_result"
    assert child["parent_app_skill_type"] == "app_skill_use"
    assert child["ticker"] == "CALM"
    assert child["revenue"] == 4_261_885_000
    assert child["net_income"] == 1_220_048_000
    assert child["source_url"].startswith("https://www.sec.gov/")


@pytest.mark.asyncio
async def test_multi_company_requests_preserve_partial_success_and_errors() -> None:
    response = await _skill().execute(
        companies=[{"query": "CALM"}, {"query": "BROKEN"}, {"query": "MU", "identifier_type": "ticker"}],
        provider_client=FakeProvider(),
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["result_count"] == 2
    assert [result["ticker"] for result in payload["results"]] == ["CALM", "MU"]
    assert payload["errors"] == [
        {
            "query": "BROKEN",
            "code": "company_not_found",
            "message": "Could not resolve company in SEC EDGAR: BROKEN",
        }
    ]


@pytest.mark.asyncio
async def test_company_financials_requires_explicit_company_inputs() -> None:
    response = await _skill().execute(companies=[], provider_client=FakeProvider())

    payload = response.model_dump()
    assert payload["success"] is False
    assert payload["error_code"] == "invalid_request"
    assert "at least one explicit company" in payload["error"]


@pytest.mark.asyncio
async def test_company_financials_rejects_discovery_queries() -> None:
    response = await _skill().execute(
        companies=[{"query": "egg selling companies"}],
        provider_client=FakeProvider(),
    )

    payload = response.model_dump()
    assert payload["success"] is False
    assert payload["error_code"] == "invalid_request"
    assert "explicit ticker, CIK, or company name" in payload["error"]


@pytest.mark.asyncio
async def test_company_financials_caps_company_count() -> None:
    response = await _skill().execute(
        companies=[{"query": f"C{index}"} for index in range(11)],
        provider_client=FakeProvider(),
    )

    payload = response.model_dump()
    assert payload["success"] is False
    assert payload["error_code"] == "invalid_request"
    assert "at most 10 companies" in payload["error"]


def test_business_app_metadata_declares_parent_child_embeds_and_workflow() -> None:
    app_yml = yaml.safe_load((REPO_ROOT / "backend/apps/business/app.yml").read_text())

    parent = next(embed for embed in app_yml["embed_types"] if embed["id"] == "company_financials")
    child = next(embed for embed in app_yml["embed_types"] if embed["id"] == "company_financial_result")
    skill = next(skill for skill in app_yml["skills"] if skill["id"] == "company_financials")

    assert app_yml["name_translation_key"] == "business"
    assert parent["category"] == "app-skill-use"
    assert parent["has_children"] is True
    assert parent["child_type"] == "company_financial_result"
    assert child["category"] == "direct"
    assert child["frontend_type"] == "business-company-financial-result"
    assert skill["providers"] == [{"name": "SEC EDGAR", "no_api_key": True}]
    assert "investment" in skill["preprocessor_hint"].lower()
    assert skill["workflow"] == {
        "available": True,
        "execution_mode": "sync",
        "effect": "read",
        "unattended": True,
        "approval": "never",
        "binding_requirements": ["none"],
        "test_allowed": True,
        "test_example_input": {
            "companies": [{"query": "CALM"}],
            "period": "latest_annual",
            "metric_group": "summary",
            "years": 1,
            "include_sources": True,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "result_count": {"type": "integer"},
                "provider": {"type": "string"},
                "results": {"type": "array"},
            },
        },
    }
