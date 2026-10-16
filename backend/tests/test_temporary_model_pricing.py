"""Provider tariffs resolve at dispatch, with immutable historical receipts."""

import copy
from datetime import date
from pathlib import Path

import pytest
import yaml

from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown
from backend.core.api.app.utils import config_manager as config_module
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.shared.python_utils.billing_utils import (
    calculate_cache_aware_supplier_cost, calculate_token_category_credits,
    select_customer_context_band, snapshot_model_tariff,
)
from backend.shared.python_utils.model_pricing import (
    ModelPricingError, resolve_model_tariff, validate_temporary_prices,
)

PROVIDERS = Path(__file__).resolve().parents[1] / "providers"


def catalog_model(provider: str, model_id: str) -> dict:
    return next(model for model in yaml.safe_load((PROVIDERS / f"{provider}.yml").read_text())["models"] if model["id"] == model_id)


# contract-test: supporting surface=rest_api assertions=billing.models.scheduled-temporary-tariffs
@pytest.mark.parametrize("day,promo,input_cost,input_unit", [
    (date(2026, 10, 14), True, 2, 160),
    (date(2026, 11, 30), True, 2, 160),
    (date(2026, 12, 1), False, 4, 80),
])
def test_argon_dates_switch_complete_tariffs_without_mutation(day, promo, input_cost, input_unit):
    model = catalog_model("google", "gemini-4-argon")
    original = copy.deepcopy(model)
    result = resolve_model_tariff(model, on_date=day)
    assert bool(result.get("active_temporary_price")) is promo
    assert result["costs"]["input_per_million_token"]["price"] == input_cost
    assert result["pricing"]["tokens"]["input"]["per_credit_unit"] == input_unit
    assert result["costs"]["cached_input_per_million_token"]["price"] == input_cost / 20
    assert result["costs"]["output_per_million_token"]["price"] == input_cost * 5
    assert model == original


# contract-test: supporting surface=rest_api assertions=billing.models.scheduled-temporary-tariffs
def test_same_manager_recomputes_catalog_prices_at_utc_boundary(monkeypatch):
    model = catalog_model("google", "gemini-3.8-flash")
    manager = object.__new__(ConfigManager)
    manager._provider_configs = {"google": {"provider_id": "google", "models": [model]}}
    monkeypatch.setattr(config_module, "utc_today", lambda: date(2026, 12, 31))
    before = manager.get_provider_configs()["google"]["models"][0]
    monkeypatch.setattr(config_module, "utc_today", lambda: date(2027, 1, 1))
    after = manager.get_provider_config("google")["models"][0]
    assert before["pricing"]["tokens"]["input"]["per_credit_unit"] == 450
    assert after["pricing"]["tokens"]["input"]["per_credit_unit"] == 225
    assert "active_temporary_price" not in after
    assert after["costs"]["output_per_million_token"]["price"] == 7.5
    assert before["supplier_cost_profiles"]["google"]["multiplier"] == 2
    assert after["supplier_cost_profiles"]["google"]["multiplier"] == 1
    # Expired independent verification does not invent an extended cache TTL
    # or prevent ordinary input/output billing after the promotion ends.
    assert after["cache_pricing"]["enabled"] is False
    assert snapshot_model_tariff(after)["pricing"]["tokens"]["output"]["per_credit_unit"] == 45
    assert model["pricing"]["tokens"]["input"]["per_credit_unit"] == 225


# contract-test: supporting surface=rest_api assertions=billing.models.unknown-promotion-expiry
@pytest.mark.parametrize("provider,model_id,unit,guarantee", [
    ("mistral", "mistral-large-4", 490, None),
    ("openai", "gpt-5.6-sol", 80, "2026-11-21"),
])
def test_undated_sales_do_not_invent_end_dates(provider, model_id, unit, guarantee):
    model = catalog_model(provider, model_id)
    result = resolve_model_tariff(model, on_date=date(2026, 11, 22))
    assert result["pricing"]["tokens"]["input"]["per_credit_unit"] == unit
    assert "expires_on" not in result["active_temporary_price"]
    assert result["active_temporary_price"].get("guaranteed_through") == guarantee
    assert model["pricing"] != result["pricing"]


def route_fixture() -> dict:
    rates = {"tokens": {"input": {"per_credit_unit": 100}, "output": {"per_credit_unit": 10}}}
    costs = {"input_per_million_token": {"price": 1, "currency": "USD"}, "output_per_million_token": {"price": 10, "currency": "USD"}}
    return {
        "id": "model", "default_server": "direct", "pricing": rates, "costs": costs,
        "servers": [{"id": "direct", "region": "EU"}, {"id": "fallback", "region": "US"}],
        "temporary_prices": [{
            "id": "sale", "effective_from": "2026-10-01", "expires_on": "2026-10-31",
            "source_url": "https://provider.example/pricing", "reviewed_on": "2026-10-01",
            "eligible_hosts": ["direct"], "regions": ["EU"], "processing_tier": "standard",
            "pricing": {"tokens": {"input": {"per_credit_unit": 200}, "output": {"per_credit_unit": 20}}},
            "costs": {"input_per_million_token": {"price": 0.5, "currency": "USD"}, "output_per_million_token": {"price": 5, "currency": "USD"}},
        }],
    }


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.parametrize("host,region,tier,discount", [
    ("direct", "EU", "standard", True),
    ("fallback", "US", "standard", False),
    ("direct", "US", "standard", False),
    ("direct", "EU", "batch", False),
])
def test_actual_host_region_and_processing_tier_bound_discounts(host, region, tier, discount):
    result = resolve_model_tariff(route_fixture(), inference_host=host, region=region, processing_tier=tier, on_date=date(2026, 10, 14))
    assert bool(result.get("active_temporary_price")) is discount
    assert result["pricing"]["tokens"]["input"]["per_credit_unit"] == (200 if discount else 100)


# contract-test: supporting surface=rest_api assertions=billing.models.scheduled-temporary-tariffs
def test_future_offer_is_not_applied_before_start():
    result = resolve_model_tariff(route_fixture(), on_date=date(2026, 9, 30))
    assert "active_temporary_price" not in result
    assert result["costs"]["input_per_million_token"]["price"] == 1


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.parametrize("defect", ["missing_cost", "missing_category", "currency", "negative", "zero", "nan", "boolean", "reversed", "source", "unknown_host", "duplicate", "overlap", "missing_tier"])
def test_invalid_and_incomplete_offers_fail_closed(defect):
    model = route_fixture()
    offer = model["temporary_prices"][0]
    if defect == "missing_cost":
        offer["costs"].pop("output_per_million_token")
    elif defect == "missing_category":
        offer["pricing"]["tokens"].pop("output")
    elif defect == "currency":
        offer["costs"]["input_per_million_token"]["currency"] = "EUR"
    elif defect in {"negative", "zero", "nan", "boolean"}:
        offer["pricing"]["tokens"]["input"]["per_credit_unit"] = {"negative": -1, "zero": 0, "nan": "NaN", "boolean": True}[defect]
    elif defect == "reversed":
        offer["expires_on"] = "2026-09-30"
    elif defect == "source":
        offer.pop("source_url")
    elif defect == "unknown_host":
        offer["eligible_hosts"] = ["unconfigured"]
    elif defect in {"duplicate", "overlap"}:
        second = copy.deepcopy(offer)
        if defect == "overlap":
            second["id"] = "second-sale"
            second["effective_from"] = "2026-10-31"
        model["temporary_prices"].append(second)
    elif defect == "missing_tier":
        offer.pop("processing_tier")
    with pytest.raises(ModelPricingError):
        resolve_model_tariff(model, on_date=date(2026, 10, 14))


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
def test_adjacent_nonoverlapping_periods_are_valid_and_unknown_list_shape_is_rejected():
    model = route_fixture()
    second = copy.deepcopy(model["temporary_prices"][0])
    second.update(id="second-sale", effective_from="2026-11-01", expires_on="2026-11-30")
    model["temporary_prices"].append(second)
    validate_temporary_prices(model)
    model["temporary_prices"] = {}
    with pytest.raises(ModelPricingError):
        resolve_model_tariff(model)


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.parametrize("defect", ["cost", "context", "tier", "modality"])
def test_invalid_nested_supplier_profiles_are_rejected_before_dispatch(defect):
    model = route_fixture()
    model["supplier_cost_profiles"] = {"direct": {"region": "EU", "multiplier": 1}}
    profile = {"region": "EU", "multiplier": 1}
    if defect == "cost":
        profile["costs"] = {"input_per_million_token": {"price": -1, "currency": "USD"}}
    else:
        field = {"context": "context_bands", "tier": "service_tiers", "modality": "modalities"}[defect]
        profile[field] = {"over_272k" if defect == "context" else "standard": {"input": "NaN"}}
    model["temporary_prices"][0]["supplier_cost_profiles"] = {"direct": profile}
    with pytest.raises(ModelPricingError):
        resolve_model_tariff(model, on_date=date(2026, 10, 14))


# contract-test: supporting surface=rest_api assertions=billing.models.immutable-attempt-tariffs
def test_receipt_uses_frozen_sale_after_catalog_changes_and_settlement_replays():
    model = catalog_model("mistral", "mistral-large-4")
    frozen = snapshot_model_tariff(resolve_model_tariff(model, on_date=date(2026, 10, 14)))
    bucket = {
        "model_id": "mistral/mistral-large-4", "attempt_id": "paid-attempt-1", "tariff_snapshot": frozen,
        "inference_host": "mistral", "region": "EU", "usage_source": "provider_reported",
        "input_tokens": 5740, "uncached_input_tokens": 980, "cache_read_input_tokens": 4760,
        "output_tokens": 158,
    }
    model["temporary_prices"] = []
    def changed_lookup(*_args):
        raise AssertionError("Historical settlement must not consult today's catalog")
    first = build_model_usage_breakdown([bucket], changed_lookup)
    replay = build_model_usage_breakdown([bucket], changed_lookup)
    assert first == replay
    assert first["credits_charged"] == 4
    assert frozen["active_temporary_price"]["id"] == "half-price-sale-2026"
    assert frozen["costs"]["input_per_million_token"]["price"] == 0.68
    regular = snapshot_model_tariff(model)
    assert regular["pricing_version"] != frozen["pricing_version"]


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.parametrize("host", ["google_ai_studio", "google"])
@pytest.mark.parametrize("input_total,band,unit,input_cost", [(200000, "standard", 170, 2), (200001, "over_200k", 85, 4)])
def test_google_pro_full_request_context_boundary_without_cache_activation(host, input_total, band, unit, input_cost):
    model = catalog_model("google", "gemini-3.1-pro-preview")
    selected_band, rates = select_customer_context_band(model_pricing_details=model, inference_host=host, input_total=input_total)
    assert selected_band == band
    assert rates["input"]["per_credit_unit"] == unit
    credits, cache_active = calculate_token_category_credits(
        input_total=input_total, uncached_input=input_total, output_tokens=30,
        cache_read=None, cache_write=None, cache_write_1h=None, legacy_billable_input=None,
        model_pricing_details=model, inference_host=host,
    )
    assert not cache_active
    assert float(credits["input"]) == pytest.approx(input_total / unit)
    supplier = calculate_cache_aware_supplier_cost(
        usage={"input_tokens": input_total, "output_tokens": 0, "uncached_input_tokens": input_total, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "usage_source": "provider_reported"},
        model_pricing_details=model, inference_host=host,
    )
    assert float(supplier["cost_usd"]) == pytest.approx(input_total * input_cost / 1_000_000)
