"""Verify supported payment configuration and override routing.

@privacy-promise: payment-data-minimization

Integration cases require an authenticated isolated test account and service.
"""

import os

import httpx
import pytest


@pytest.fixture
def direct_client():
    """Create an authenticated client only when a test requests it."""
    api_key = os.getenv("OPENMATES_TEST_ACCOUNT_API_KEY")
    if not api_key or api_key == "IMPORTED_TO_VAULT":
        pytest.skip("OPENMATES_TEST_ACCOUNT_API_KEY is required for payment routing integration checks")
    with httpx.Client(
        base_url="https://api.dev.openmates.org",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30.0,
        trust_env=False,
    ) as client:
        yield client


@pytest.mark.integration
# contract-test: direct surface=rest_api assertions=billing.purchase.provider-routing
def test_config_returns_valid_provider(direct_client):
    """
    /v1/payments/config must return a valid provider name without any override.
    Valid providers are 'stripe' and 'stripe_managed'.
    This also verifies the endpoint is reachable and authenticated.
    """
    response = direct_client.get("/v1/payments/config")
    assert response.status_code == 200, f"Config endpoint failed: {response.text}"
    data = response.json()

    assert "provider" in data, f"Response missing 'provider': {data}"
    assert data["provider"] in ("stripe", "stripe_managed"), (
        f"Unexpected provider '{data['provider']}' — expected 'stripe' or 'stripe_managed'"
    )
    print(f"\n[CONFIG] Default provider (dev machine IP): {data['provider']}")


@pytest.mark.integration
# contract-test: direct surface=rest_api assertions=billing.purchase.provider-routing
def test_config_stripe_override(direct_client):
    """
    ?provider_override=stripe must always return Stripe regardless of caller IP.
    This validates the switch button logic (non-EU user switching to EU/Stripe).
    """
    response = direct_client.get("/v1/payments/config?provider_override=stripe")
    assert response.status_code == 200, f"Config with stripe override failed: {response.text}"
    data = response.json()

    assert data["provider"] == "stripe", (
        f"Expected 'stripe' with override, got '{data['provider']}'"
    )
    # Stripe must return a non-empty public key
    assert data.get("public_key"), (
        "Stripe config must include a non-empty 'public_key' (Stripe publishable key)"
    )
    assert data["public_key"].startswith("pk_"), (
        f"Stripe public key should start with 'pk_', got: {data['public_key']}"
    )
    print(f"\n[CONFIG] Stripe override: provider={data['provider']}, key={data['public_key'][:12]}...")


@pytest.mark.integration
# contract-test: direct surface=rest_api assertions=billing.purchase.provider-routing
def test_config_invalid_override_falls_back(direct_client):
    """
    An invalid ?provider_override value should be ignored and fall back to
    IP-based detection (return 200 with a valid provider, not 422 or 500).
    """
    response = direct_client.get("/v1/payments/config?provider_override=invalid_provider")
    assert response.status_code == 200, (
        f"Config with invalid override should still return 200: {response.text}"
    )
    data = response.json()
    assert data["provider"] in ("stripe", "stripe_managed"), (
        f"Invalid override should fall back to a valid provider, got: {data['provider']}"
    )
    print(f"\n[CONFIG] Invalid override fell back to: {data['provider']}")
