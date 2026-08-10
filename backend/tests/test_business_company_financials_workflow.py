"""Workflow contract tests for Business company financials.

The skill is read-only, no-key, and workflow-safe. These tests make sure the
metadata registry exposes it and the generic workflow app-skill adapter can
consume the normalized output without a custom workflow runner path.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry


def test_business_company_financials_is_workflow_capability() -> None:
    capability = WorkflowCapabilityRegistry().get_capability("business.company_financials")

    assert capability.enabled is True
    assert capability.metadata["workflow"] == {
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


class FakeRegistry:
    def __init__(self, response: dict[str, Any]) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.response = response

    async def dispatch_skill(self, app_id: str, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((app_id, skill_id, request))
        return self.response


@pytest.mark.anyio
async def test_workflow_adapter_exposes_company_financials_output_summary() -> None:
    registry = FakeRegistry(
        {
            "success": True,
            "summary": "SEC EDGAR latest annual financials for CALM",
            "provider": "SEC EDGAR",
            "result_count": 1,
            "results": [
                {
                    "type": "company_financial_result",
                    "ticker": "CALM",
                    "revenue": 4_261_885_000,
                    "net_income": 1_220_048_000,
                }
            ],
        }
    )
    adapter = WorkflowAppSkillAdapter(registry=registry)

    output = await adapter.execute(
        "business",
        "company_financials",
        {"companies": [{"query": "CALM"}], "period": "latest_annual", "metric_group": "summary"},
    )

    assert registry.calls == [
        (
            "business",
            "company_financials",
            {"companies": [{"query": "CALM"}], "period": "latest_annual", "metric_group": "summary"},
        )
    ]
    assert output["summary"] == "SEC EDGAR latest annual financials for CALM"
    assert output["provider"] == "SEC EDGAR"
    assert output["result_count"] == 1
    assert output["raw"]["results"][0]["ticker"] == "CALM"
