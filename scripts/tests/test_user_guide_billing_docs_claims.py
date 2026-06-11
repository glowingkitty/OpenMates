#!/usr/bin/env python3
"""
Regression tests for user-guide billing documentation claims.

These checks keep user-facing billing pages grounded in the current settings UI,
payment routes, usage export endpoints, and billing utilities without exercising
live payment providers.

Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def read_repo(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def doc_assert(claim_id: str) -> None:
    assert claim_id


def test_billing_index_links_to_implemented_billing_surfaces() -> None:
    doc_assert("user-guide-billing-index-source")
    doc = read_repo("docs/user-guide/billing/README.md")
    settings_billing = read_repo("frontend/packages/ui/src/components/settings/SettingsBilling.svelte")

    for guide in ["pricing.md", "usage.md", "gift-cards.md", "invoices-and-refunds.md"]:
        assert guide in doc
    for route_part in ["buy-credits", "auto-topup", "invoices", "billing/gift-cards"]:
        assert route_part in settings_billing
    assert "settingsPath: `billing/${path}`" in settings_billing
    assert "SettingsUsage" in settings_billing


def test_pricing_guide_is_grounded_in_credit_billing_sources() -> None:
    doc_assert("user-guide-billing-pricing-source")
    doc = read_repo("docs/user-guide/billing/pricing.md")
    billing_utils = read_repo("backend/shared/python_utils/billing_utils.py")
    billing_service = read_repo("backend/core/api/app/services/billing_service.py")
    payments = read_repo("backend/core/api/app/routes/payments.py")

    assert "Minimum charge" in doc
    assert "1 credit" in doc
    assert "MINIMUM_CREDITS_CHARGED = 1" in billing_utils
    assert "OVERDRAFT_LIMIT = -500" in billing_service
    assert "Insufficient credits" in billing_service
    assert "get_price_for_credits" in payments
    assert "create-bank-transfer-order" in payments


def test_gift_card_guide_is_grounded_in_redemption_sources() -> None:
    doc_assert("user-guide-billing-gift-cards-source")
    doc = read_repo("docs/user-guide/billing/gift-cards.md")
    redeem_component = read_repo("frontend/packages/ui/src/components/settings/billing/GiftCardRedeem.svelte")
    payments = read_repo("backend/core/api/app/routes/payments.py")
    gift_card_methods = read_repo("backend/core/api/app/services/directus/gift_card_methods.py")

    assert "Standard cards are single-use" in doc
    assert "giftCardCode.trim().toUpperCase()" in redeem_component
    assert "/redeem-gift-card" in payments
    assert "Invalid gift card code or code has already been redeemed" in payments
    assert "Invalid gift card: credits value is invalid" in payments
    assert "user_credits_updated" in payments
    assert "is_reusable=true" in gift_card_methods


def test_invoices_and_refunds_guide_is_grounded_in_billing_sources() -> None:
    doc_assert("user-guide-billing-invoices-refunds-source")
    doc = read_repo("docs/user-guide/billing/invoices-and-refunds.md")
    settings = read_repo("backend/core/api/app/routes/settings.py")
    payments = read_repo("backend/core/api/app/routes/payments.py")

    assert "Gift cards cannot be refunded after redemption" in doc
    assert "encrypted_amount" in settings
    assert "encrypted_credits_purchased" in settings
    assert "download_url" in settings
    assert "refund_status" in settings
    assert "credits_from_gift_cards" in settings
    assert "is_gift_card" in payments


def test_usage_guide_is_grounded_in_usage_sources() -> None:
    doc_assert("user-guide-billing-usage-source")
    doc = read_repo("docs/user-guide/billing/usage.md")
    usage_component = read_repo("frontend/packages/ui/src/components/settings/SettingsUsage.svelte")
    settings = read_repo("backend/core/api/app/routes/settings.py")
    usage_service = read_repo("backend/core/api/app/services/directus/usage.py")

    assert "Usage data downloads as a CSV file" in doc
    for endpoint in ["getSummaries", "getDetails", "getDailyOverview", "export"]:
        assert endpoint in usage_component
    assert "loadedMonths += 3" in usage_component
    assert "usage-export-" in settings
    assert "text/csv" in settings
    assert "Encrypt credit and token fields" in usage_service
    assert "Stores app_id, skill_id, chat_id, message_id in cleartext" in usage_service
