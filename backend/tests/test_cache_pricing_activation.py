"""Check the admitted customer cache tariffs against their configured supplier costs."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown
from backend.shared.python_utils.billing_utils import is_cache_tariff_admissible, snapshot_model_tariff


PROVIDERS = Path(__file__).resolve().parents[1] / "providers"
ACTIVE = {
    "google": {"gemini-3.7-flash", "gemini-3.8-flash"},
    "openai": {"gpt-6.1-sol", "gpt-6-luna"},
    "anthropic": {"claude-sonnet-5-5", "claude-haiku-5-5"},
    "mistral": {"mistral-small-latest"},
}
SUPPLIER_COST_KEYS = {
    "input": "input_per_million_token",
    "cache_read": "cached_input_per_million_token",
    "cache_write": "cache_write_per_million_token",
    "cache_write_1h": "cache_write_1h_per_million_token",
    "output": "output_per_million_token",
}
REVIEW_DATE = date(2026, 10, 8)


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("provider", ACTIVE)
def test_only_verified_models_have_active_cache_tariffs(provider: str) -> None:
    catalog = yaml.safe_load((PROVIDERS / f"{provider}.yml").read_text())
    models = {model["id"]: model for model in catalog["models"] if "cache_pricing" in model}
    assert {model_id for model_id, model in models.items() if model["cache_pricing"]["enabled"]} == ACTIVE[provider]

    for model_id in ACTIVE[provider]:
        model = models[model_id]
        policy = model["cache_pricing"]
        assert policy["status"] == "verified_for_activation"
        assert date.fromisoformat(policy["reviewed_on"]) == REVIEW_DATE
        assert date.fromisoformat(policy["expires_on"]) >= REVIEW_DATE
        assert policy["source_url"].startswith("https://")
        assert set(policy["eligible_hosts"]) <= {server["id"] for server in model["servers"]}
        for host in policy["eligible_hosts"]:
            assert is_cache_tariff_admissible(policy, host, on_date=REVIEW_DATE)


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("provider,model_id", [
    (provider, model_id) for provider, model_ids in ACTIVE.items() for model_id in model_ids
])
def test_active_category_prices_cover_configured_supplier_costs(provider: str, model_id: str) -> None:
    catalog = yaml.safe_load((PROVIDERS / f"{provider}.yml").read_text())
    model = next(model for model in catalog["models"] if model["id"] == model_id)
    snapshot = snapshot_model_tariff(model)
    assert snapshot["cache_pricing"]["enabled"]

    for host in model["cache_pricing"]["eligible_hosts"]:
        profile = model.get("supplier_cost_profiles", {}).get(host, {})
        host_multiplier = Decimal(str(profile.get("multiplier", 1)))
        # Direct routes target about 3x the supplier category cost. Regional
        # gross premiums narrow the configured contribution on fallback hosts.
        minimum_markup = (
            Decimal("1.45") if host == "google" else
            Decimal("2.5") if host == "aws_bedrock" else Decimal("2.7")
        )
        rates = model["pricing"]["tokens"]
        bands = [(None, rates)] + [
            (band_name, band["tokens"])
            for band_name, band in model["pricing"].get("context_bands", {}).items()
            if host in band.get("eligible_hosts", [])
        ]
        for band_name, category_rates in bands:
            for category, rate in category_rates.items():
                if category == "cache_write_1h" and host not in model["cache_pricing"].get(
                    "cache_write_1h_hosts", [host]
                ):
                    continue
                cost_key = SUPPLIER_COST_KEYS[category]
                if category == "cache_read" and cost_key not in model["costs"]:
                    cost_key = "cache_read_per_million_token"
                supplier = Decimal(str(model["costs"][cost_key]["price"])) * host_multiplier
                supplier *= Decimal(str(profile.get("context_bands", {}).get(band_name, {}).get(category, 1)))
                customer = Decimal(1000) / Decimal(str(rate["per_credit_unit"]))
                assert customer >= supplier * minimum_markup, (provider, model_id, host, band_name, category)

            # OpenAI writes are not separately reported; ordinary input must also
            # cover the supplier's higher cache-write price in each context band.
            if provider == "openai":
                write_cost = Decimal(str(model["costs"]["cache_write_per_million_token"]["price"]))
                write_cost *= Decimal(str(profile.get("context_bands", {}).get(band_name, {}).get("cache_write", 1)))
                assert Decimal(1000) / Decimal(str(category_rates["input"]["per_credit_unit"])) >= write_cost * Decimal("2.4")


@pytest.mark.parametrize("provider,model_id,host,raw,expected_read,expected_write", [
    ("openai", "gpt-6.1-sol", "openai",
     {"input_tokens": 1000, "uncached_input_tokens": 600,
      "cache_read_input_tokens": 400, "cache_creation_input_tokens": None, "output_tokens": 20},
     400, 0),
    ("anthropic", "claude-sonnet-5-5", "anthropic",
     {"input_tokens": 600, "uncached_input_tokens": 100, "cache_creation_input_tokens": 200,
      "cache_creation_5m_input_tokens": 200, "cache_creation_1h_input_tokens": 0,
      "cache_read_input_tokens": 300, "output_tokens": 20},
     300, 200),
    ("mistral", "mistral-small-latest", "mistral",
     {"input_tokens": 1000, "uncached_input_tokens": 600,
      "cache_read_input_tokens": 400, "cache_creation_input_tokens": None, "output_tokens": 20},
     400, 0),
])
# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
def test_active_catalog_tariffs_settle_reported_cache_categories(
    provider: str, model_id: str, host: str, raw: dict, expected_read: int, expected_write: int,
) -> None:
    catalog = yaml.safe_load((PROVIDERS / f"{provider}.yml").read_text())
    model = next(model for model in catalog["models"] if model["id"] == model_id)
    bucket = {"model_id": f"{provider}/{model_id}", "inference_host": host,
              "usage_source": "provider_reported", **raw}
    receipt = build_model_usage_breakdown([bucket], lambda _provider, _model: model)
    entry = receipt["entries"][0]
    assert entry["billing_mode"] == "cache_aware"
    assert entry["cache_read_input_tokens"] == expected_read
    assert entry["cache_creation_input_tokens"] == expected_write or (
        expected_write == 0 and entry["cache_creation_input_tokens"] is None
    )
    assert float(entry["category_credits"]["cache_read"]) > 0
    assert (float(entry["category_credits"]["cache_write"]) > 0) is (expected_write > 0)
