# backend/tests/test_finance_check_accounts_skill.py
#
# Contract tests for the Finance Check accounts skill.
# The skill combines connected-account provider data and canonical CSV statement
# inputs into one privacy-safe app-skill-use payload for chat, CLI, and SDK use.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

"""Finance Check accounts skill contract tests.

The skill combines connected-account provider rows and canonical CSV statements
into one filterable, privacy-safe app-skill-use payload. Provider calls are faked
here; sandbox/live Revolut validation is covered by the separate API script.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.apps.finance.skills.check_accounts import CheckAccountsSkill
from backend.shared.providers.revolut_business import RevolutAccount, RevolutTransaction

REPO_ROOT = Path(__file__).resolve().parents[2]


CSV_STATEMENT = """transaction_id,account_id,account_label,posted_at,description,amount,currency,direction,balance_after,category_hint,counterparty_type,source_name
csv-1,cash,Cash account,2026-01-03,Grocery Mart,-50.00,EUR,expense,450.00,groceries,merchant,csv import
csv-2,cash,Cash account,2026-01-04,Acme Payroll,1000.00,EUR,income,1450.00,payroll,payer,csv import
"""


class FakeRevolutClient:
    def __init__(self, *, access_token: str, base_url: str | None = None) -> None:
        self.access_token = access_token
        self.base_url = base_url

    async def list_accounts(self) -> list[RevolutAccount]:
        return [
            RevolutAccount(
                id="rev-acct",
                name="Revolut EUR",
                balance=2000.0,
                currency="EUR",
                state="active",
                updated_at="2026-01-31T00:00:00Z",
            )
        ]

    async def list_transactions(self, **_: Any) -> list[RevolutTransaction]:
        return [
            RevolutTransaction(
                id="rev-txn-1",
                account_id="rev-acct",
                created_at="2026-01-08T10:00:00Z",
                completed_at="2026-01-08T10:00:00Z",
                amount=-12.99,
                currency="EUR",
                description="Spotify Premium",
                state="completed",
                category_hint="streaming",
            )
        ]


def _skill() -> CheckAccountsSkill:
    return CheckAccountsSkill(
        app=None,
        app_id="finance",
        skill_id="check_accounts",
        skill_name="Check accounts",
        skill_description="Analyze read-only account data.",
    )


@pytest.mark.asyncio
async def test_check_accounts_combines_revolut_and_csv_into_filterable_embed() -> None:
    response = await _skill().execute(
        period="monthly",
        projection_horizon="quarterly",
        csv_statements=[{"filename": "cash.csv", "content": CSV_STATEMENT}],
        connected_account_requests=[{"access_token_handle": "ath_1", "source_ref": "revolut:sandbox"}],
        connected_account_access_tokens={"ath_1": "access-secret"},
        revolut_client_factory=FakeRevolutClient,
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["app_id"] == "finance"
    assert payload["skill_id"] == "check_accounts"
    assert payload["account_count"] == 2
    assert payload["transaction_count"] == 3
    assert payload["overview"]["summaries"]["income_total"] == 1000.0
    assert payload["overview"]["summaries"]["expense_total"] == 62.99
    assert payload["overview"]["summaries"]["time_series"] == [
        {"bucket": "2026-01", "income": 1000.0, "expense": 62.99, "net": 937.01, "transaction_count": 3}
    ]
    assert payload["overview"]["summaries"]["projection"]["horizon"] == "quarterly"
    assert payload["overview"]["filter_options"]["sources"] == ["csv:cash.csv", "revolut:sandbox"]
    assert payload["overview"]["privacy"]["raw_names_persisted"] is False

    serialized = json.dumps(payload)
    for raw_name in ["Spotify", "Grocery Mart", "Acme Payroll"]:
        assert raw_name not in serialized
    assert "[MERCHANT_STREAMING_001]" in serialized
    assert "[MERCHANT_GROCERIES_001]" in serialized


@pytest.mark.asyncio
async def test_check_accounts_uses_sandbox_revolut_resource_host() -> None:
    created_clients: list[FakeRevolutClient] = []

    def client_factory(**kwargs: Any) -> FakeRevolutClient:
        client = FakeRevolutClient(**kwargs)
        created_clients.append(client)
        return client

    response = await _skill().execute(
        period="monthly",
        connected_account_requests=[{"access_token_handle": "ath_1", "environment": "sandbox"}],
        connected_account_access_tokens={"ath_1": "access-secret"},
        revolut_client_factory=client_factory,
    )

    assert response.success is True
    assert created_clients[0].base_url == "https://sandbox-b2b.revolut.com/api/1.0/"


@pytest.mark.asyncio
async def test_check_accounts_applies_filters_before_totals_and_list_output() -> None:
    response = await _skill().execute(
        period="monthly",
        projection_horizon="monthly",
        csv_statements=[{"filename": "cash.csv", "content": CSV_STATEMENT}],
        connected_account_requests=[{"access_token_handle": "ath_1", "source_ref": "revolut:sandbox"}],
        connected_account_access_tokens={"ath_1": "access-secret"},
        revolut_client_factory=FakeRevolutClient,
        start_date="2026-01-01",
        end_date="2026-01-31",
        direction_filter="expense",
        category_filters=["groceries"],
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["account_count"] == 1
    assert payload["transaction_count"] == 1
    assert payload["overview"]["summaries"]["income_total"] == 0.0
    assert payload["overview"]["summaries"]["expense_total"] == 50.0
    assert payload["overview"]["summaries"]["filters_applied"]["direction_filter"] == "expense"
    assert payload["overview"]["summaries"]["filters_applied"]["category_filters"] == ["groceries"]
    assert payload["overview"]["summaries"]["time_series"] == [
        {"bucket": "2026-01", "income": 0.0, "expense": 50.0, "net": -50.0, "transaction_count": 1}
    ]
    assert [item["category"] for item in payload["overview"]["transactions"]] == ["groceries"]


@pytest.mark.asyncio
async def test_check_accounts_requires_at_least_one_source() -> None:
    response = await _skill().execute(period="monthly")

    assert response.success is False
    assert response.error_code == "missing_sources"


def test_finance_app_metadata_declares_read_only_connected_account_skill() -> None:
    app_yml = yaml.safe_load((REPO_ROOT / "backend/apps/finance/app.yml").read_text())

    embed = next(item for item in app_yml["embed_types"] if item["id"] == "check_accounts")
    skill = next(item for item in app_yml["skills"] if item["id"] == "check_accounts")

    assert app_yml["id"] == "finance"
    assert embed["category"] == "app-skill-use"
    assert embed["frontend_type"] == "app-skill-use"
    assert skill["providers"] == [{"id": "revolut_business", "name": "Revolut Business", "no_api_key": True}]
    assert skill["pricing"] == {"fixed": 1}
    assert skill["workflow"]["effect"] == "read"
    assert skill["workflow"]["approval"] == "never"
    assert skill["workflow"]["binding_requirements"] == ["connected_account_or_csv"]
    assert skill["api_config"]["expose_post"] is False
