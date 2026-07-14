"""Tests for the EU Stripe revenue-threshold guard.

The guard protects production credit purchases from crossing legacy EU OSS
revenue limits. Dev and test environments use Stripe test-mode transactions,
so they must not block E2E signup and billing coverage when test revenue grows.
These tests keep that environment boundary explicit without touching Stripe.
"""

from backend.core.api.app.utils.payment_environment import should_enforce_eu_revenue_threshold


def test_eu_revenue_threshold_guard_is_production_only(monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    assert should_enforce_eu_revenue_threshold(is_eu=True) is False

    monkeypatch.setenv("SERVER_ENVIRONMENT", "test")
    assert should_enforce_eu_revenue_threshold(is_eu=True) is False

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert should_enforce_eu_revenue_threshold(is_eu=True) is True
    assert should_enforce_eu_revenue_threshold(is_eu=False) is False
