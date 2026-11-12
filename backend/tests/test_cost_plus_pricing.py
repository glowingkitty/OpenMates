"""Cost-plus customer pricing: one configurable margin, 5-credit rounding, catalog drift guard."""

from decimal import Decimal
from pathlib import Path
import subprocess
import sys

import pytest

from backend.shared.python_utils.cost_plus_pricing import (
    CostPlusPricingError,
    PricingSettings,
    credits_for_cost,
    derive_declared_pricing,
    derive_model_pricing,
    load_pricing_settings,
    round_credits,
    tokens_per_credit,
)

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = PricingSettings()


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
@pytest.mark.parametrize("raw,expected", [(13, 15), (8, 10), (271, 275), (5, 5), (15, 15), (4.2, 5), (3, 3), (1, 1)])
# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_per_unit_prices_round_up_to_five_credit_steps_and_keep_small_prices(raw, expected):
    assert round_credits(Decimal(str(raw)), SETTINGS, per_call=True) == expected


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_supplier_cost_gets_the_margin_before_rounding():
    # $0.005 per request -> 7.5 credits -> 10; $0.211 per image -> 316.5 -> 320.
    assert credits_for_cost("0.005", SETTINGS, per_call=True) == 10
    assert credits_for_cost("0.211", SETTINGS, per_call=True) == 320
    # Under one step, a per-call price is a whole credit (billing floors call totals).
    assert credits_for_cost("0.002", SETTINGS, per_call=True) == 3
    # Items without an external supplier cost charge the flat minimum.
    assert credits_for_cost(0, SETTINGS, per_call=True) == 1


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_token_rates_never_sell_below_cost_plus_margin():
    # $4 / 1M input -> 6000 credits / 1M -> 166.6666 tokens per credit (rounded down).
    assert tokens_per_credit(4, SETTINGS) == 166.6666
    for usd in ("0.1", "0.68", "2.1", "3.75", "25"):
        customer_usd = Decimal(1_000_000) / Decimal(str(tokens_per_credit(usd, SETTINGS))) * Decimal("0.001")
        assert customer_usd >= Decimal(usd) * SETTINGS.multiplier


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_free_token_category_stays_free_while_free_billed_items_cost_the_minimum():
    settings = PricingSettings()
    assert tokens_per_credit(0, settings) == 0
    assert credits_for_cost(0, settings, per_call=True) == 1


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_margin_is_read_from_backend_config_and_overridable_by_environment(tmp_path):
    config = tmp_path / "backend_config.yml"
    config.write_text("pricing:\n  margin_percent: 50\n  rounding_step_credits: 5\n  zero_cost_minimum_credits: 1\n")
    assert load_pricing_settings(config, environ={}).multiplier == Decimal("1.5")
    overridden = load_pricing_settings(config, environ={"OPENMATES_PRICING_MARGIN_PERCENT": "20"})
    assert overridden.multiplier == Decimal("1.2")
    # $0.003: 4.5 -> 5 credits at 50%, 3.6 -> 4 credits at 20%.
    assert credits_for_cost("0.003", overridden, per_call=True) == 4
    with pytest.raises(CostPlusPricingError):
        load_pricing_settings(config, environ={"OPENMATES_PRICING_MARGIN_PERCENT": "-5"})


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_highest_eligible_route_sets_the_token_price():
    model = {
        "id": "example-model",
        "servers": [{"id": "direct"}, {"id": "regional"}],
        "costs": {"input_per_million_token": {"price": 1, "currency": "USD"},
                  "output_per_million_token": {"price": 2, "currency": "USD"}},
        "supplier_cost_profiles": {"regional": {"multiplier": 2}},
        "pricing": {"tokens": {"input": {"per_credit_unit": 1}, "output": {"per_credit_unit": 1}}},
    }
    tokens = derive_model_pricing(model, settings=SETTINGS)["tokens"]
    assert tokens == {"input": {"per_credit_unit": 333.3333}, "output": {"per_credit_unit": 166.6666}}
    direct_only = derive_model_pricing(model, settings=SETTINGS, hosts=["direct"])["tokens"]
    assert direct_only["input"] == {"per_credit_unit": 666.6666}


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_declared_skill_prices_need_a_supplier_cost():
    with pytest.raises(CostPlusPricingError, match="no supplier_costs.fixed"):
        derive_declared_pricing({"fixed": 10}, {}, settings=SETTINGS, model_pricing={}, item="example.skill")
    derived = derive_declared_pricing(
        {"fixed": 10, "per_unit": {"credits": 99, "unit_name": "track"}},
        {"fixed": {"none": True}, "per_unit": {"model": "example/song-model"}},
        settings=SETTINGS, model_pricing={"example/song-model": {"per_unit": {"credits": 60, "unit_name": "song"}}},
        item="example.skill",
    )
    assert derived == {"fixed": 1, "per_unit": {"credits": 60, "unit_name": "track"}}


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_every_stored_catalog_price_equals_its_cost_plus_derivation():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "derive_customer_prices.py"), "--check", "--table", "/dev/null"],
        capture_output=True, text=True, cwd=ROOT, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
