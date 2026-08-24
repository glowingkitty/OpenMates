"""
Contract tests for non-mutating official-cloud payment readiness.

The tests use aggregate fake Stripe inventory only. They require independent EU
and Managed Payments status, complete event coverage, catalog checks, freshness,
and a gateway surface that cannot create or mutate Stripe payment objects.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.core.api.app.services.payment_readiness import (
    EU_PRICE_CATALOG,
    GLOBAL_PRICE_CATALOG,
    REQUIRED_STRIPE_EVENTS,
    StripeSdkReadOnlyGateway,
    collect_stripe_readiness,
    evaluate_stripe_readiness,
)


NOW = datetime(2026, 8, 24, 13, 0, tzinfo=timezone.utc)


# contract-test: direct surface=cli assertions=operational-monitoring.billing.no-spend-readiness,billing.purchase.provider-routing
def test_eu_card_catalog_excludes_bank_transfer_only_tier():
    assert "110.000 credits" not in EU_PRICE_CATALOG


def _passing_inventory(**overrides):
    inventory = {
        "account_access": True,
        "active_catalog": {
            name: [price]
            for name, price in (EU_PRICE_CATALOG | GLOBAL_PRICE_CATALOG).items()
        },
        "destination_enabled": True,
        "enabled_events": set(REQUIRED_STRIPE_EVENTS),
        "routes_registered": True,
        "workers_healthy": True,
        "settlements_healthy": True,
        "checked_at": NOW,
        "now": NOW,
    }
    inventory.update(overrides)
    return inventory


# contract-test: direct surface=cli assertions=operational-monitoring.billing.no-spend-readiness,billing.purchase.provider-routing
def test_missing_managed_checkout_event_does_not_hide_healthy_eu_path():
    enabled_events = set(REQUIRED_STRIPE_EVENTS) - {"checkout.session.completed"}

    result = evaluate_stripe_readiness(**_passing_inventory(enabled_events=enabled_events))

    assert result["eu_card"] == "healthy"
    assert result["managed_payments"] == "unavailable"
    assert result["status"] == "degraded"
    assert result["missing_events"] == ["checkout.session.completed"]


# contract-test: direct surface=cli assertions=operational-monitoring.billing.no-spend-readiness,billing.purchase.provider-routing
def test_missing_catalog_or_stale_check_cannot_report_healthy():
    missing_catalog = _passing_inventory()["active_catalog"].copy()
    missing_catalog.pop("1.000 credits (global)")
    missing_global = _passing_inventory(active_catalog=missing_catalog)
    stale = _passing_inventory(checked_at=NOW - timedelta(minutes=31))

    assert evaluate_stripe_readiness(**missing_global)["managed_payments"] == "unavailable"
    assert evaluate_stripe_readiness(**stale)["status"] == "stale"


# contract-test: direct surface=cli assertions=operational-monitoring.billing.no-spend-readiness,billing.purchase.provider-routing
def test_wrong_active_price_cannot_report_healthy():
    wrong_catalog = _passing_inventory()["active_catalog"].copy()
    wrong_catalog["1.000 credits"] = [("eur", 999, None)]

    result = evaluate_stripe_readiness(**_passing_inventory(active_catalog=wrong_catalog))

    assert result["eu_card"] == "unavailable"
    assert result["status"] == "degraded"
    assert result["missing_products"] == ["1.000 credits"]


# contract-test: direct surface=cli assertions=operational-monitoring.billing.no-spend-readiness
def test_readiness_inventory_uses_read_only_gateway_surface():
    class ReadOnlyGateway:
        def __init__(self):
            self.calls = []

        def retrieve_account(self):
            self.calls.append("retrieve_account")
            return True

        def list_active_catalog(self):
            self.calls.append("list_active_catalog")
            return _passing_inventory()["active_catalog"]

        def list_event_destinations(self):
            self.calls.append("list_event_destinations")
            return [{"status": "enabled", "enabled_events": set(REQUIRED_STRIPE_EVENTS)}]

    gateway = ReadOnlyGateway()

    result = collect_stripe_readiness(
        gateway,
        routes_registered=True,
        workers_healthy=True,
        settlements_healthy=True,
        now=NOW,
    )

    assert result["status"] == "healthy"
    assert gateway.calls == [
        "retrieve_account",
        "list_active_catalog",
        "list_event_destinations",
    ]
    assert not any(token in " ".join(gateway.calls) for token in ("create", "update", "cancel", "expire", "refund", "delete"))


# contract-test: direct surface=cli assertions=operational-monitoring.billing.no-spend-readiness
def test_stripe_sdk_gateway_merges_classic_and_v2_destinations():
    class Page:
        def __init__(self, values):
            self.values = values

        def auto_paging_iter(self):
            return iter(self.values)

    stripe_module = SimpleNamespace(
        api_key="redacted",
        WebhookEndpoint=SimpleNamespace(list=lambda **_kwargs: Page([
            SimpleNamespace(status="enabled", enabled_events=["payment_intent.succeeded"]),
        ])),
        StripeClient=lambda _key: SimpleNamespace(v2=SimpleNamespace(core=SimpleNamespace(
            event_destinations=SimpleNamespace(list=lambda _params: Page([
                SimpleNamespace(status="enabled", enabled_events=["checkout.session.completed"]),
            ])),
        ))),
    )

    destinations = StripeSdkReadOnlyGateway(stripe_module).list_event_destinations()

    assert destinations == [
        {"status": "enabled", "enabled_events": {"payment_intent.succeeded"}},
        {"status": "enabled", "enabled_events": {"checkout.session.completed"}},
    ]
