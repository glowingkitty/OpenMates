"""
Evaluate official-cloud Stripe payment readiness without payment mutations.

The gateway accepted by this module intentionally exposes only account,
catalog, and event-destination reads. Results contain aggregate status and
missing configuration names only; Stripe object identifiers are never emitted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


EU_PRICE_CATALOG = {
    "1.000 credits": ("eur", 200, None),
    "10.000 credits": ("eur", 1000, None),
    "21.000 credits": ("eur", 2000, None),
    "54.000 credits": ("eur", 5000, None),
    "10.500 credits (monthly auto top-up)": ("eur", 1000, "month"),
    "22.000 credits (monthly auto top-up)": ("eur", 2000, "month"),
    "57.000 credits (monthly auto top-up)": ("eur", 5000, "month"),
}
GLOBAL_PRICE_CATALOG = {
    "1.000 credits (global)": ("eur", 250, None),
    "10.000 credits (global)": ("eur", 1300, None),
    "21.000 credits (global)": ("eur", 2500, None),
    "54.000 credits (global)": ("eur", 6000, None),
    "10.500 credits (monthly auto top-up, global)": ("eur", 1300, "month"),
    "22.000 credits (monthly auto top-up, global)": ("eur", 2500, "month"),
    "57.000 credits (monthly auto top-up, global)": ("eur", 6000, "month"),
}
EU_STRIPE_EVENTS = {
    "payment_intent.payment_failed",
    "payment_intent.succeeded",
}
MANAGED_STRIPE_EVENTS = {
    "charge.dispute.created",
    "charge.dispute.updated",
    "charge.refunded",
    "checkout.session.async_payment_failed",
    "checkout.session.completed",
    "customer.subscription.deleted",
    "customer.subscription.updated",
    "invoice.payment_failed",
    "invoice.payment_succeeded",
    "refund.failed",
}
REQUIRED_STRIPE_EVENTS = EU_STRIPE_EVENTS | MANAGED_STRIPE_EVENTS
READINESS_MAX_AGE = timedelta(minutes=30)


class StripeSdkReadOnlyGateway:
    """Adapt the Stripe SDK to the deliberately read-only readiness surface."""

    def __init__(self, stripe_module: Any):
        self.stripe = stripe_module

    def retrieve_account(self) -> bool:
        self.stripe.Account.retrieve()
        return True

    def list_active_catalog(self) -> dict[str, list[tuple[str, int, str | None]]]:
        catalog: dict[str, list[tuple[str, int, str | None]]] = {}
        for product in self.stripe.Product.list(active=True, limit=100).auto_paging_iter():
            prices = []
            for price in self.stripe.Price.list(product=product.id, active=True, limit=100).auto_paging_iter():
                interval = price.recurring.interval if price.recurring else None
                if price.unit_amount is not None:
                    prices.append((price.currency, int(price.unit_amount), interval))
            if prices:
                catalog[product.name] = prices
        return catalog

    def list_event_destinations(self) -> list[dict[str, Any]]:
        destinations = [
            {"status": endpoint.status, "enabled_events": set(endpoint.enabled_events)}
            for endpoint in self.stripe.WebhookEndpoint.list(limit=100).auto_paging_iter()
        ]
        client = self.stripe.StripeClient(self.stripe.api_key)
        destinations.extend(
            {"status": destination.status, "enabled_events": set(destination.enabled_events)}
            for destination in client.v2.core.event_destinations.list({"limit": 100}).auto_paging_iter()
        )
        return destinations


def _is_stale(*, checked_at: datetime, now: datetime) -> bool:
    normalized_checked_at = checked_at if checked_at.tzinfo else checked_at.replace(tzinfo=timezone.utc)
    normalized_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age = normalized_now - normalized_checked_at
    return age < timedelta(0) or age > READINESS_MAX_AGE


def evaluate_stripe_readiness(
    *,
    account_access: bool,
    active_catalog: dict[str, Iterable[tuple[str, int, str | None]]],
    destination_enabled: bool,
    enabled_events: Iterable[str],
    routes_registered: bool,
    workers_healthy: bool,
    settlements_healthy: bool,
    checked_at: datetime,
    now: datetime,
) -> dict[str, Any]:
    """Return independent EU and Managed Payments readiness states."""
    normalized_catalog = {name: set(prices) for name, prices in active_catalog.items()}
    events = set(enabled_events)
    if "*" in events:
        events.update(REQUIRED_STRIPE_EVENTS)
    missing_products = sorted(
        name
        for name, expected in (EU_PRICE_CATALOG | GLOBAL_PRICE_CATALOG).items()
        if expected not in normalized_catalog.get(name, set())
    )
    missing_events = sorted(REQUIRED_STRIPE_EVENTS - events)
    stale = _is_stale(checked_at=checked_at, now=now)
    shared_ready = all((account_access, destination_enabled, routes_registered, workers_healthy, settlements_healthy))
    eu_catalog_ready = all(expected in normalized_catalog.get(name, set()) for name, expected in EU_PRICE_CATALOG.items())
    managed_catalog_ready = all(expected in normalized_catalog.get(name, set()) for name, expected in GLOBAL_PRICE_CATALOG.items())
    eu_ready = shared_ready and eu_catalog_ready and EU_STRIPE_EVENTS <= events and not stale
    managed_ready = shared_ready and managed_catalog_ready and MANAGED_STRIPE_EVENTS <= events and not stale

    eu_status = "healthy" if eu_ready else "unavailable"
    managed_status = "healthy" if managed_ready else "unavailable"
    if stale:
        status = "stale"
    elif eu_ready and managed_ready:
        status = "healthy"
    elif eu_ready or managed_ready:
        status = "degraded"
    else:
        status = "unavailable"

    return {
        "status": status,
        "eu_card": eu_status,
        "managed_payments": managed_status,
        "missing_products": missing_products,
        "missing_events": missing_events,
        "checked_at": checked_at.isoformat(),
        "checks": {
            "account_access": account_access,
            "destination_enabled": destination_enabled,
            "routes_registered": routes_registered,
            "workers_healthy": workers_healthy,
            "settlements_healthy": settlements_healthy,
        },
    }


def collect_stripe_readiness(
    gateway: Any,
    *,
    routes_registered: bool,
    workers_healthy: bool,
    settlements_healthy: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect only read-only Stripe inventory and evaluate it immediately."""
    checked_at = now or datetime.now(timezone.utc)
    account_access = bool(gateway.retrieve_account())
    active_catalog = gateway.list_active_catalog()
    destinations = list(gateway.list_event_destinations())
    enabled_destinations = [item for item in destinations if item.get("status") == "enabled"]
    enabled_events = {
        event
        for destination in enabled_destinations
        for event in destination.get("enabled_events", ())
    }
    return evaluate_stripe_readiness(
        account_access=account_access,
        active_catalog=active_catalog,
        destination_enabled=bool(enabled_destinations),
        enabled_events=enabled_events,
        routes_registered=routes_registered,
        workers_healthy=workers_healthy,
        settlements_healthy=settlements_healthy,
        checked_at=checked_at,
        now=checked_at,
    )
