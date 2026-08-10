# backend/tests/test_finance_privacy_redaction.py
#
# Contract tests for Finance privacy redaction and placeholder mapping payloads.
# Raw merchant, counterparty, payer, and payee values may appear in fixtures, but
# saved embed-shaped overview data must expose only category-aware placeholders.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

"""Finance privacy redaction contract tests.

Finance analysis may inspect raw bank descriptions transiently, but saved skill
outputs and LLM-facing payloads must contain category-aware placeholders instead
of merchant, counterparty, payer, or payee names.
"""

from __future__ import annotations

import json

from backend.shared.python_utils.finance_accounts import (
    FinancePrivacyRedactor,
    NormalizedAccount,
    NormalizedTransaction,
    build_finance_overview,
)
from backend.core.api.app.services.embed_service import EmbedService


def test_finance_overview_excludes_raw_counterparty_names() -> None:
    redactor = FinancePrivacyRedactor()
    spotify = redactor.placeholder_for("Spotify Premium", category="streaming", counterparty_type="merchant")
    payroll = redactor.placeholder_for("Acme Payroll", category="payroll", counterparty_type="payer")
    clinic = redactor.placeholder_for("Private Health Clinic", category="health", counterparty_type="payee")

    overview = build_finance_overview(
        accounts=[
            NormalizedAccount(
                account_ref="checking",
                source_ref="csv:test",
                display_label="Main checking",
                currency="EUR",
                balance=1000.0,
                balance_as_of="2026-01-31",
            )
        ],
        transactions=[
            NormalizedTransaction(
                transaction_ref="txn-1",
                account_ref="checking",
                source_ref="csv:test",
                posted_at="2026-01-03",
                amount=-12.99,
                currency="EUR",
                direction="expense",
                category="streaming",
                counterparty_placeholder=spotify,
                state="completed",
            ),
            NormalizedTransaction(
                transaction_ref="txn-2",
                account_ref="checking",
                source_ref="csv:test",
                posted_at="2026-01-05",
                amount=2500.0,
                currency="EUR",
                direction="income",
                category="payroll",
                counterparty_placeholder=payroll,
                state="completed",
            ),
            NormalizedTransaction(
                transaction_ref="txn-3",
                account_ref="checking",
                source_ref="csv:test",
                posted_at="2026-01-10",
                amount=-80.0,
                currency="EUR",
                direction="expense",
                category="health",
                counterparty_placeholder=clinic,
                state="completed",
            ),
        ],
        period="monthly",
        projection_horizon="monthly",
        redactor=redactor,
    )

    payload = json.dumps(overview.model_dump())
    for raw_name in ["Spotify", "Acme", "Private Health Clinic"]:
        assert raw_name not in payload
    assert "[MERCHANT_STREAMING_001]" in payload
    assert "[PAYER_PAYROLL_001]" in payload
    assert "[PAYEE_HEALTH_001]" in payload
    assert overview.privacy.raw_names_persisted is False
    assert overview.privacy.placeholder_mappings_ref == "owner_encrypted_embed_pii_mappings"


def test_placeholder_mapping_export_keeps_originals_out_of_embed_payload() -> None:
    redactor = FinancePrivacyRedactor()
    redactor.placeholder_for("Grocery Mart", category="groceries", counterparty_type="merchant")

    public_payload = redactor.public_mapping_summary()
    encrypted_mapping = redactor.owner_mapping_payload()

    assert public_payload == [
        {
            "placeholder": "[MERCHANT_GROCERIES_001]",
            "category": "groceries",
            "counterparty_type": "merchant",
        }
    ]
    assert encrypted_mapping[0]["original"] == "Grocery Mart"


def test_finance_embed_sanitizer_strips_owner_only_mapping_fields() -> None:
    content = {
        "app_id": "finance",
        "skill_id": "check_accounts",
        "overview": {
            "transactions": [
                {"counterparty_placeholder": "[MERCHANT_GROCERIES_001]"},
            ],
        },
        "owner_pii_mappings": [
            {"placeholder": "[MERCHANT_GROCERIES_001]", "original": "Grocery Mart", "type": "merchant"},
        ],
        "_owner_pii_mappings": [
            {"placeholder": "[MERCHANT_GROCERIES_001]", "original": "Grocery Mart", "type": "merchant"},
        ],
    }

    sanitized = EmbedService._sanitize_final_app_skill_content("finance", "check_accounts", content)
    payload = json.dumps(sanitized)

    assert "owner_pii_mappings" not in payload
    assert "Grocery Mart" not in payload
    assert "[MERCHANT_GROCERIES_001]" in payload


def test_finance_embed_sidecar_extracts_owner_mappings_before_sanitizing() -> None:
    content = {
        "app_id": "finance",
        "skill_id": "check_accounts",
        "results": [
            {
                "overview": {
                    "transactions": [
                        {"counterparty_placeholder": "[MERCHANT_SOFTWARE_001]"},
                    ],
                },
                "owner_pii_mappings": [
                    {
                        "placeholder": "[MERCHANT_SOFTWARE_001]",
                        "original": "SaaS Vendor Ltd",
                        "type": "COUNTERPARTY",
                    },
                ],
            }
        ],
    }

    sidecar = EmbedService._extract_finance_owner_pii_mappings(
        "finance",
        "check_accounts",
        content,
    )
    sanitized = EmbedService._sanitize_final_app_skill_content("finance", "check_accounts", content)
    sanitized_payload = json.dumps(sanitized)

    assert sidecar == [
        {
            "placeholder": "[MERCHANT_SOFTWARE_001]",
            "original": "SaaS Vendor Ltd",
            "type": "COUNTERPARTY",
        }
    ]
    assert "SaaS Vendor Ltd" not in sanitized_payload
    assert "owner_pii_mappings" not in sanitized_payload
    assert "[MERCHANT_SOFTWARE_001]" in sanitized_payload
