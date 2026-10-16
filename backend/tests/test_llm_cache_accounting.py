# contract-test-file: infrastructure
"""Cache usage and tariffs remain exact, partitioned, and inactive by default."""

import copy
from types import SimpleNamespace
from decimal import Decimal
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest
import yaml

from backend.apps.ai.processing.model_usage_tracker import (
    ModelUsageTracker,
    build_model_usage_breakdown,
    build_summary_usage_breakdown,
)
from backend.core.api.app.services.llm_usage_receipt import validate_public_llm_usage_receipt
from backend.shared.python_schemas.llm_usage import normalize_provider_usage
from backend.shared.python_utils.billing_utils import (
    BillingError,
    calculate_cache_aware_supplier_cost,
    is_cache_tariff_admissible,
    select_customer_context_band,
    snapshot_model_tariff,
)


def _pricing(enabled: bool = False) -> dict:
    return {
        "pricing": {"tokens": {
            "input": {"per_credit_unit": 10},
            "output": {"per_credit_unit": 5},
            "cache_read": {"per_credit_unit": 100},
            "cache_write": {"per_credit_unit": 8},
            "cache_write_1h": {"per_credit_unit": 5},
        }},
        "cache_pricing": {
            "enabled": enabled, "write_billing": "separate", "status": "verified_for_activation",
            "source_url": "https://example.test/pricing", "reviewed_on": "2026-10-01",
            "expires_on": "2099-01-01", "eligible_hosts": ["anthropic", "aws_bedrock", "openai", "google", "mistral"],
        },
        "costs": {
            "input_per_million_token": {"price": 1},
            "output_per_million_token": {"price": 5},
            "cache_read_per_million_token": {"price": 0.1},
            "cache_write_per_million_token": {"price": 1.25},
            "cache_write_1h_per_million_token": {"price": 2},
        },
        "supplier_cost_profiles": {"aws_bedrock": {"region": "EU", "multiplier": 1.10}},
    }


def _lookup(pricing: dict):
    return lambda _provider, _model: pricing


def _provider_model(provider: str, model_id: str) -> dict:
    path = Path(__file__).parents[1] / "providers" / f"{provider}.yml"
    return next(model for model in yaml.safe_load(path.read_text())["models"] if model["id"] == model_id)


def _active_openai_model(model_id: str) -> dict:
    model = _provider_model("openai", model_id)
    model["cache_pricing"].update(
        enabled=True, status="verified_for_activation", reviewed_on="2026-10-01",
        expires_on="2099-01-01",
    )
    return model


def test_compression_fallback_cost_uses_actual_cerebras_route_without_changing_customer_rates() -> None:
    model = _provider_model("openai", "gpt-oss-120b")
    snapshot = snapshot_model_tariff(model)
    usage = {
        "input_tokens": 1000, "uncached_input_tokens": 1000,
        "output_tokens": 1000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0, "usage_source": "provider_reported",
    }
    cerebras = calculate_cache_aware_supplier_cost(
        usage=usage, model_pricing_details=snapshot, inference_host="cerebras",
    )
    bedrock = calculate_cache_aware_supplier_cost(
        usage=usage, model_pricing_details=snapshot, inference_host="aws_bedrock",
    )
    assert Decimal(cerebras["cost_usd"]) == Decimal("0.0011")
    assert Decimal(bedrock["cost_usd"]) == Decimal("0.00075")
    assert snapshot["pricing"]["tokens"]["input"]["per_credit_unit"] == 2200
    assert snapshot["pricing"]["tokens"]["output"]["per_credit_unit"] == 550


def test_anthropic_exclusive_cache_input_is_inclusive_only_after_normalization() -> None:
    native = SimpleNamespace(
        input_tokens=100, output_tokens=20, cache_read_input_tokens=50,
        cache_creation_input_tokens=10, cache_creation_5m_input_tokens=10,
        cache_creation_1h_input_tokens=0,
    )
    usage = normalize_provider_usage(native, model_id="anthropic/claude-test", provider_kind="anthropic", inference_host="anthropic", region="US")
    assert usage.input_total == 160
    assert usage.input_uncached == usage.legacy_billable_input_tokens == 100
    assert usage.cache_read_input_tokens == 50
    assert usage.cache_creation_input_tokens == 10
    assert usage.to_bucket()["region"] == "US"

    # Proposed rates do not silently change the legacy debit.
    legacy = build_model_usage_breakdown([usage.to_bucket()], _lookup(_pricing()))
    assert legacy["credits_charged"] == 14
    assert legacy["entries"][0]["category_credits"]["cache_read"] == "0"
    assert legacy["entries"][0]["rates"]["cache_read"] is None
    assert "write_billing" not in legacy["entries"][0]

    active = build_model_usage_breakdown([usage.to_bucket()], _lookup(_pricing(True)))
    assert active["raw_credits"] == "15.75"
    assert active["credits_charged"] == 15
    assert active["entries"][0]["billing_mode"] == "cache_aware"
    assert active["entries"][0]["billed_input_tokens"] == 100
    assert active["entries"][0]["category_credits"]["cache_write"] == "1.25"


def test_google_output_adds_thoughts_once_and_missing_cache_is_not_zero() -> None:
    usage = normalize_provider_usage(
        SimpleNamespace(prompt_token_count=1000, candidates_token_count=30, thoughts_token_count=10),
        model_id="google/gemini-test", provider_kind="google", inference_host="google",
    )
    assert (usage.input_total, usage.input_uncached, usage.output_billable) == (1000, 1000, 40)
    assert usage.legacy_billable_output_tokens == 30
    assert usage.cache_read_input_tokens is None
    receipt = build_model_usage_breakdown([usage.to_bucket()], _lookup(_pricing(True)))
    assert receipt["cache_read_input_tokens"] is None
    assert receipt["entries"][0]["category_credits"]["cache_read"] == "0"
    # An enabled tariff charges paid thinking even when cache metrics are
    # missing, but must not show an inapplicable cache rate on the receipt.
    assert receipt["output_tokens"] == 40
    assert receipt["entries"][0]["category_credits"]["output"] == "8"
    assert receipt["entries"][0]["rates"]["cache_read"] is None
    assert "write_billing" not in receipt["entries"][0]

    inactive = build_model_usage_breakdown([usage.to_bucket()], _lookup(_pricing(False)))
    assert inactive["output_tokens"] == 30
    assert inactive["entries"][0]["category_credits"]["output"] == "6"
    assert inactive["credits_charged"] == 106  # 1000 ordinary input + 30 native output.
    assert usage.to_bucket()["output_tokens"] == 40  # Full shadow usage survives.
    assert validate_public_llm_usage_receipt(inactive) == inactive

    reported_zero = normalize_provider_usage(
        {"prompt_token_count": 1000, "candidates_token_count": 30, "cached_content_token_count": 0},
        model_id="google/gemini-test", provider_kind="google", inference_host="google",
    )
    assert reported_zero.cache_read_input_tokens == 0


def test_google_missing_candidates_only_proves_zero_from_exact_reported_total() -> None:
    proven = normalize_provider_usage(
        {"prompt_token_count": 100, "candidates_token_count": None,
         "thoughts_token_count": 20, "total_token_count": 120},
        model_id="google/gemini-test", provider_kind="google", inference_host="google",
    )
    assert proven.output_billable == 20
    assert proven.legacy_billable_output_tokens == 0
    assert proven.usage_source == "provider_reported"
    inactive = build_model_usage_breakdown([proven.to_bucket()], _lookup(_pricing(False)))
    assert inactive["credits_charged"] == 10  # Legacy Google candidates omitted.

    uncertain = normalize_provider_usage(
        {"prompt_token_count": 100, "candidates_token_count": None,
         "thoughts_token_count": 20, "total_token_count": 125,
         "cache_read_input_tokens": 50},
        model_id="google/gemini-test", provider_kind="google", inference_host="google",
    )
    assert uncertain.output_billable == 20  # Do not invent five candidates.
    assert uncertain.usage_source == "estimated"
    enabled = build_model_usage_breakdown([uncertain.to_bucket()], _lookup(_pricing(True)))
    assert enabled["entries"][0]["category_credits"]["cache_read"] == "0"
    assert enabled["entries"][0]["category_credits"]["output"] == "4"


def test_google_missing_prompt_preserves_legacy_zero_without_fake_cache_zero() -> None:
    missing = normalize_provider_usage(
        {"prompt_token_count": None, "candidates_token_count": 10,
         "thoughts_token_count": 5, "total_token_count": 40,
         "cache_read_input_tokens": 5},
        model_id="google/gemini-test", provider_kind="google",
    )
    assert missing.input_total == 0
    assert missing.output_billable == 15
    assert missing.legacy_billable_output_tokens == 10
    assert missing.cache_read_input_tokens is None
    assert missing.usage_source == "estimated"
    inactive = build_model_usage_breakdown([missing.to_bucket()], _lookup(_pricing(False)))
    assert inactive["credits_charged"] == 2
    assert inactive["cache_read_input_tokens"] is None

    both_missing = normalize_provider_usage(
        {"prompt_token_count": None, "candidates_token_count": None},
        model_id="google/gemini-test", provider_kind="google",
    )
    assert both_missing.input_total == both_missing.output_billable == 0
    assert both_missing.usage_source == "estimated"
    with pytest.raises(ValueError, match="missing input_tokens"):
        normalize_provider_usage(
            {"input_tokens": None, "output_tokens": 1},
            model_id="openai/gpt-test", provider_kind="openai",
        )


def test_paid_writes_require_reported_write_and_retention_metrics() -> None:
    p = _pricing(True)
    # OpenAI currently reports cached reads but has no distinct paid-write count.
    openai = normalize_provider_usage(
        {"input_tokens": 100, "output_tokens": 0, "cache_read_input_tokens": 50},
        model_id="openai/gpt-test", provider_kind="openai", inference_host="openai",
    )
    receipt = build_model_usage_breakdown([openai.to_bucket()], _lookup(p))
    assert receipt["credits_charged"] == 10  # All inclusive input at ordinary legacy rate.
    assert receipt["entries"][0]["category_credits"]["cache_read"] == "0"

    p["cache_pricing"]["requires_cache_retention_metric"] = True
    anthropic = normalize_provider_usage(
        {"input_tokens": 100, "output_tokens": 0, "cache_read_input_tokens": 0,
         "cache_creation_input_tokens": 20},
        model_id="anthropic/claude-test", provider_kind="anthropic", inference_host="anthropic",
    )
    receipt = build_model_usage_breakdown([anthropic.to_bucket()], _lookup(p))
    assert receipt["credits_charged"] == 12  # Known native + write tokens at ordinary rate.
    assert receipt["entries"][0]["category_credits"]["cache_write"] == "0"


def test_partial_anthropic_cache_metrics_bill_known_inclusive_input_only_when_eligible() -> None:
    p = _pricing(True)
    p["cache_pricing"]["eligible_hosts"] = ["anthropic"]
    usage = normalize_provider_usage(
        {"input_tokens": 100, "output_tokens": 20,
         "cache_read_input_tokens": 50, "cache_creation_input_tokens": None},
        model_id="anthropic/claude-test", provider_kind="anthropic", inference_host="anthropic",
    )
    assert usage.input_total == 150
    eligible = build_model_usage_breakdown([usage.to_bucket()], _lookup(p))
    assert eligible["credits_charged"] == 19  # 150 known input ordinary + 20 output.
    assert eligible["entries"][0]["billing_mode"] == "ordinary_input"
    assert eligible["entries"][0]["billed_input_tokens"] == 150
    assert eligible["entries"][0]["uncached_input_tokens"] == 100
    assert eligible["entries"][0]["cache_read_input_tokens"] == 50
    assert "attempt_id" not in eligible["entries"][0]
    assert "provider_request_id" not in eligible["entries"][0]
    assert validate_public_llm_usage_receipt(eligible) == eligible
    assert eligible["entries"][0]["category_credits"]["cache_read"] == "0"
    assert eligible["entries"][0]["rates"]["cache_read"] is None

    p["cache_pricing"]["enabled"] = False
    disabled = build_model_usage_breakdown([usage.to_bucket()], _lookup(p))
    assert disabled["credits_charged"] == 14  # Preserve native exclusive input.
    assert disabled["entries"][0]["billed_input_tokens"] == 100

    p["cache_pricing"]["enabled"] = True
    ineligible_bucket = {**usage.to_bucket(), "inference_host": "aws_bedrock"}
    ineligible = build_model_usage_breakdown([ineligible_bucket], _lookup(p))
    assert ineligible["credits_charged"] == 14
    assert ineligible["entries"][0]["billed_input_tokens"] == 100


def test_ineligible_google_route_preserves_legacy_output_count() -> None:
    p = _pricing(True)
    p["cache_pricing"]["eligible_hosts"] = ["google"]
    usage = normalize_provider_usage(
        {"prompt_token_count": 100, "candidates_token_count": 30, "thoughts_token_count": 10},
        model_id="google/gemini-test", provider_kind="google", inference_host="openrouter",
    )
    ineligible = build_model_usage_breakdown([usage.to_bucket()], _lookup(p))
    assert ineligible["output_tokens"] == 30
    assert ineligible["credits_charged"] == 16
    eligible = build_model_usage_breakdown([{**usage.to_bucket(), "inference_host": "google"}], _lookup(p))
    assert eligible["output_tokens"] == 40
    assert eligible["credits_charged"] == 18


def test_implicit_write_is_included_in_billed_ordinary_input() -> None:
    p = _pricing(True)
    p["cache_pricing"]["write_billing"] = "included_in_input"
    usage = normalize_provider_usage(
        {"prompt_tokens": 100, "completion_tokens": 0,
         "cache_read_input_tokens": 20, "cache_creation_input_tokens": 10},
        model_id="mistral/test", provider_kind="mistral", inference_host="mistral",
    )
    entry = build_model_usage_breakdown([usage.to_bucket()], _lookup(p))["entries"][0]
    assert entry["billing_mode"] == "cache_aware"
    assert entry["uncached_input_tokens"] == 70
    assert entry["billed_input_tokens"] == 80
    assert entry["category_credits"]["input"] == "8"
    assert entry["category_credits"]["cache_write"] == "0"


def test_inclusive_partition_rejects_overlapping_cache_counters() -> None:
    with pytest.raises(ValueError, match="exceed"):
        normalize_provider_usage(
            {"input_tokens": 100, "output_tokens": 2, "cache_read_input_tokens": 70, "cache_creation_input_tokens": 40},
            model_id="openai/gpt-test", provider_kind="openai",
        )


def test_attempt_cumulative_snapshots_replace_earlier_usage_and_tariff_is_frozen() -> None:
    tracker = ModelUsageTracker()
    tariff = snapshot_model_tariff(_pricing(True))
    first = normalize_provider_usage(
        {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        model_id="openai/gpt-test", provider_kind="openai", inference_host="openai", attempt_id="attempt-1", tariff_snapshot=tariff,
    )
    second = normalize_provider_usage(
        {"input_tokens": 120, "output_tokens": 15, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 0},
        model_id="openai/gpt-test", provider_kind="openai", inference_host="openai", attempt_id="attempt-1", tariff_snapshot=tariff,
    )
    tracker.record_reported_usage(model_id=first.model_id, normalized_usage=first)
    tracker.record_reported_usage(model_id=second.model_id, normalized_usage=second)
    assert tracker.total_input_tokens == 120
    assert tracker.total_output_tokens == 15
    assert len(tracker.usage_by_model) == 1
    receipt = build_model_usage_breakdown(tracker.usage_by_model, _lookup(_pricing(False)))
    assert receipt["entries"][0]["category_credits"]["cache_read"] == "0.2"
    assert receipt["entries"][0]["pricing_version"] == tariff["pricing_version"]
    assert receipt["credits_charged"] == 13  # 100 ordinary + 20 reads + 15 output


def test_missing_cache_counter_stays_unknown_when_attempt_deltas_merge() -> None:
    tracker = ModelUsageTracker()
    first = normalize_provider_usage(
        {"input_tokens": 10, "output_tokens": 1},
        model_id="openai/gpt-test", provider_kind="openai", attempt_id="attempt-delta",
    )
    second = normalize_provider_usage(
        {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 5},
        model_id="openai/gpt-test", provider_kind="openai", attempt_id="attempt-delta",
    )
    tracker.record_reported_usage(model_id=first.model_id, normalized_usage=first, usage_event_kind="delta")
    tracker.record_reported_usage(model_id=second.model_id, normalized_usage=second, usage_event_kind="delta")
    receipt = build_model_usage_breakdown(tracker.usage_by_model, _lookup(_pricing(True)))
    assert receipt["input_tokens"] == 20
    assert receipt["uncached_input_tokens"] == 20
    assert receipt["cache_read_input_tokens"] is None
    assert receipt["entries"][0]["category_credits"]["cache_read"] == "0"


def test_single_floor_across_attempts_and_route_supplier_profile() -> None:
    p = _pricing()
    p["pricing"]["tokens"]["input"]["per_credit_unit"] = 2
    p["pricing"]["tokens"]["output"]["per_credit_unit"] = 2
    buckets = [
        {"model_id": "openai/a", "input_tokens": 1, "output_tokens": 0},
        {"model_id": "openai/b", "input_tokens": 1, "output_tokens": 0},
    ]
    receipt = build_model_usage_breakdown(buckets, _lookup(p))
    assert receipt["raw_credits"] == "1"
    assert receipt["credits_charged"] == 1

    p["pricing"]["tokens"]["input"]["per_credit_unit"] = 3
    repeating = build_model_usage_breakdown(buckets, _lookup(p))
    entry_sum = sum((Decimal(entry["raw_credits"]) for entry in repeating["entries"]), Decimal(0))
    assert entry_sum == Decimal(repeating["raw_credits"])
    assert Decimal(repeating["raw_credits"]) + Decimal(repeating["rounding_adjustment"]) == 1

    cost = calculate_cache_aware_supplier_cost(
        usage={"input_tokens": 160, "uncached_input_tokens": 100, "cache_read_input_tokens": 50,
               "cache_creation_input_tokens": 10, "cache_creation_1h_input_tokens": 0, "output_tokens": 20},
        model_pricing_details=_pricing(), inference_host="aws_bedrock", region="EU",
    )
    assert cost["complete"] is True
    assert cost["cost_usd"] == "0.00023925"


def test_supplier_cost_remains_incomplete_when_paid_write_metric_is_missing() -> None:
    p = _pricing()
    p["cache_pricing"]["write_billing"] = "included_in_input"
    incomplete = calculate_cache_aware_supplier_cost(
        usage={"input_tokens": 100, "uncached_input_tokens": 100,
               "cache_read_input_tokens": 0, "cache_creation_input_tokens": None,
               "output_tokens": 0, "usage_source": "provider_reported", "provider_kind": "openai"},
        model_pricing_details=p, inference_host="openai",
    )
    assert incomplete["complete"] is False
    assert "cache_creation_input_tokens" in incomplete["missing"]
    assert incomplete["cost_usd"] == "0.0001"
    assert incomplete["cost_upper_bound_usd"] == "0.000125"
    assert incomplete["upper_bound_complete"] is True

    p["supplier_cost_profiles"]["google"] = {"region": "global", "multiplier": 2}
    p["costs"].pop("cache_write_per_million_token")
    p["cache_pricing"]["write_billing"] = "included_in_input"
    vertex = calculate_cache_aware_supplier_cost(
        usage={"input_tokens": 100, "uncached_input_tokens": 100,
               "cache_read_input_tokens": 0, "cache_creation_input_tokens": None,
               "output_tokens": 0},
        model_pricing_details=p, inference_host="google", region="global",
    )
    assert vertex["cost_usd"] == vertex["cost_upper_bound_usd"] == "0.0002"
    assert vertex["complete"] is vertex["upper_bound_complete"] is True


def test_openai_reported_reads_discount_without_inventing_paid_writes() -> None:
    p = _pricing(True)
    p["cache_pricing"].update(write_billing="included_in_input", eligible_hosts=["openai"])
    p["pricing"]["tokens"].pop("cache_write")
    usage = normalize_provider_usage(
        {"input_tokens": 1000, "output_tokens": 20, "cache_read_input_tokens": 400},
        model_id="openai/gpt-6.1-sol", provider_kind="openai", inference_host="openai",
    )
    receipt = build_model_usage_breakdown([usage.to_bucket()], _lookup(p))
    entry = receipt["entries"][0]
    assert entry["billing_mode"] == "cache_aware"
    assert entry["billed_input_tokens"] == 600
    assert entry["cache_creation_input_tokens"] is None
    assert entry["category_credits"] == {
        "input": "60", "cache_read": "4", "cache_write": "0", "cache_write_1h": "0", "output": "4",
    }
    assert entry["write_billing"] == "included_in_input"
    assert receipt["credits_charged"] == 68


def test_unverified_or_expired_enabled_catalog_tariff_cannot_be_snapshotted() -> None:
    p = _pricing(True)
    p["cache_pricing"].update(status="verified_provider_usage_pending_financial_check", expires_on="2026-11-06")
    with pytest.raises(BillingError, match="verified activation status"):
        snapshot_model_tariff(p)
    p["cache_pricing"]["status"] = "verified_for_activation"
    p["cache_pricing"]["expires_on"] = "2020-01-01"
    p["cache_pricing"].update(source_url="https://example.test/pricing", reviewed_on="2019-12-01", eligible_hosts=["openai"])
    with pytest.raises(BillingError, match="expired"):
        snapshot_model_tariff(p)
    assert is_cache_tariff_admissible(p["cache_pricing"], "openai", on_date=date(2019, 12, 31))
    assert not is_cache_tariff_admissible(p["cache_pricing"], "openai", on_date=date(2020, 1, 2))

    # A previously admitted attempt keeps its frozen price during replay.
    frozen = _pricing(True)
    frozen["cache_pricing"].update(status="verified_for_activation", expires_on="2020-01-01")
    frozen["admitted_on"] = "2019-12-31"
    cost = calculate_cache_aware_supplier_cost(
        usage={"provider_kind": "openai", "input_tokens": 10, "uncached_input_tokens": 10,
               "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1},
        model_pricing_details=frozen, inference_host="openai",
    )
    assert "tariff_expired" not in cost["missing"]


@pytest.mark.parametrize("field,value", [
    ("status", None), ("source_url", None), ("reviewed_on", "2026-99-01"),
    ("expires_on", "not-a-date"), ("eligible_hosts", []),
    ("effective_from", "2099-01-02"),
])
def test_activation_predicate_rejects_missing_or_invalid_catalog_metadata(field: str, value: object) -> None:
    policy = _pricing(True)["cache_pricing"]
    policy[field] = value
    assert not is_cache_tariff_admissible(policy, "openai", on_date=date(2026, 10, 7))
    with pytest.raises(BillingError):
        snapshot_model_tariff({"pricing": _pricing(True)["pricing"], "cache_pricing": policy})


def test_exclusive_provider_missing_writes_has_no_supplier_upper_bound() -> None:
    p = _pricing(True)
    cost = calculate_cache_aware_supplier_cost(
        usage={"provider_kind": "anthropic", "input_tokens": 150, "uncached_input_tokens": 100,
               "cache_read_input_tokens": 50, "cache_creation_input_tokens": None, "output_tokens": 10},
        model_pricing_details=p, inference_host="anthropic",
    )
    assert cost["complete"] is False
    assert cost["upper_bound_complete"] is False
    assert cost["cost_upper_bound_usd"] is None


def test_reported_write_without_retention_split_uses_private_one_hour_bound() -> None:
    cost = calculate_cache_aware_supplier_cost(
        usage={"provider_kind": "anthropic", "input_tokens": 100, "uncached_input_tokens": 90,
               "cache_read_input_tokens": 0, "cache_creation_input_tokens": 10,
               "cache_creation_1h_input_tokens": None, "output_tokens": 0},
        model_pricing_details=_pricing(True), inference_host="anthropic",
    )
    assert cost["complete"] is False
    assert "cache_creation_1h_input_tokens" in cost["missing"]
    assert cost["cost_usd"] == "0.0001025"
    assert cost["cost_upper_bound_usd"] == "0.00011"
    assert cost["upper_bound_complete"] is True


def test_five_minute_only_host_prices_reported_writes_without_one_hour_row() -> None:
    p = _pricing(True)
    p["cache_pricing"].update(
        eligible_hosts=["aws_bedrock"], cache_write_1h_hosts=[], requires_cache_retention_metric=False,
    )
    usage = normalize_provider_usage(
        {"input_tokens": 100, "output_tokens": 0, "cache_read_input_tokens": 0,
         "cache_creation_input_tokens": 10, "cache_creation_5m_input_tokens": 10},
        model_id="anthropic/claude-sonnet-4-6", provider_kind="bedrock", inference_host="aws_bedrock",
    )
    entry = build_model_usage_breakdown([usage.to_bucket()], _lookup(p))["entries"][0]
    assert entry["billing_mode"] == "cache_aware"
    assert entry["category_credits"]["cache_write"] == "1.25"
    assert entry["rates"]["cache_write_1h"] is None

    unexpected_one_hour = {**usage.to_bucket(), "cache_creation_5m_input_tokens": 0,
                           "cache_creation_1h_input_tokens": 10}
    entry = build_model_usage_breakdown([unexpected_one_hour], _lookup(p))["entries"][0]
    assert entry["billing_mode"] == "ordinary_input"
    assert entry["rates"]["cache_write_1h"] is None


def test_implicit_google_unknown_reads_have_a_private_gross_supplier_bound() -> None:
    model = _provider_model("google", "gemini-3.5-flash-lite")
    usage = normalize_provider_usage(
        {"prompt_token_count": 1000, "candidates_token_count": 20},
        model_id="google/gemini-3.5-flash-lite", provider_kind="google",
        inference_host="google_ai_studio",
    ).to_bucket()
    assert usage["cache_read_input_tokens"] is None
    studio = calculate_cache_aware_supplier_cost(
        usage=usage, model_pricing_details=model, inference_host="google_ai_studio", region="US",
    )
    assert studio["complete"] is False
    assert studio["missing"] == ["cache_read_input_tokens"]
    assert studio["upper_bound_complete"] is True
    assert studio["cost_upper_bound_usd"] == "0.00035"

    vertex = calculate_cache_aware_supplier_cost(
        usage={**usage, "inference_host": "google"}, model_pricing_details=model,
        inference_host="google", region="global",
    )
    assert vertex["complete"] is False
    assert vertex["upper_bound_complete"] is True
    assert vertex["cost_upper_bound_usd"] == "0.00035"
    wrong_region = calculate_cache_aware_supplier_cost(
        usage=usage, model_pricing_details=model, inference_host="google", region="US",
    )
    assert wrong_region["cost_usd"] == "0.00035"  # Retain known rate, mark route region unresolved.
    assert wrong_region["cost_upper_bound_usd"] is None


def test_implicit_read_bound_requires_known_host_rates_output_and_reported_usage() -> None:
    model = _provider_model("mistral", "mistral-small-latest")
    base = {"provider_kind": "mistral", "input_tokens": 1000, "uncached_input_tokens": 1000,
            "cache_read_input_tokens": None, "cache_creation_input_tokens": None,
            "output_tokens": 20, "usage_source": "provider_reported"}
    safe = calculate_cache_aware_supplier_cost(
        usage=base, model_pricing_details=model, inference_host="mistral",
    )
    assert safe["complete"] is False and safe["upper_bound_complete"] is True
    assert safe["cost_upper_bound_usd"] == "0.000162"

    for changed_usage, host, changed_model in (
        ({**base, "output_tokens": None}, "mistral", model),
        ({**base, "usage_source": "estimated"}, "mistral", model),
        ({**base, "usage_source": None}, "mistral", model),
        (base, "openrouter", model),
        (base, "mistral", {**model, "costs": {k: v for k, v in model["costs"].items()
                                            if k != "output_per_million_token"}}),
    ):
        unsafe = calculate_cache_aware_supplier_cost(
            usage=changed_usage, model_pricing_details=changed_model, inference_host=host,
        )
        assert unsafe["upper_bound_complete"] is False
        assert unsafe["cost_upper_bound_usd"] is None


@pytest.mark.parametrize("model_id", [
    "gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-5.6-terra",
])
def test_openai_long_context_catalog_units_match_approved_multipliers(model_id: str) -> None:
    frozen = snapshot_model_tariff(_active_openai_model(model_id))
    base = frozen["pricing"]["tokens"]
    standard_band, standard = select_customer_context_band(
        model_pricing_details=frozen, inference_host="openai", input_total=272_000,
    )
    long_band, long_rates = select_customer_context_band(
        model_pricing_details=frozen, inference_host="openai", input_total=272_001,
    )
    assert standard_band == "standard" and standard == base
    assert long_band == "over_272k" and set(long_rates) == set(base)
    for category, row in base.items():
        base_unit = Fraction(Decimal(str(row["per_credit_unit"])))
        expected = base_unit * Fraction(2, 3) // 1 if category == "output" else base_unit / 2
        assert Fraction(Decimal(str(long_rates[category]["per_credit_unit"]))) == expected


def test_openai_long_context_uses_actual_attempt_total_and_frozen_rates() -> None:
    model = _active_openai_model("gpt-6.1-sol")
    frozen = snapshot_model_tariff(model)
    tracker = ModelUsageTracker()
    first = normalize_provider_usage(
        {"input_tokens": 272_000, "output_tokens": 30,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        model_id="openai/gpt-6.1-sol", provider_kind="openai", inference_host="openai",
        attempt_id="one-attempt", tariff_snapshot=frozen,
    )
    second = normalize_provider_usage(
        {"input_tokens": 272_001, "output_tokens": 30,
         "cache_read_input_tokens": 100_000, "cache_creation_input_tokens": 0},
        model_id="openai/gpt-6.1-sol", provider_kind="openai", inference_host="openai",
        attempt_id="one-attempt", tariff_snapshot=frozen,
    )
    tracker.record_reported_usage(model_id=first.model_id, normalized_usage=first)
    tracker.record_reported_usage(model_id=second.model_id, normalized_usage=second)
    assert tracker.total_input_tokens == 272_001
    model["pricing"]["tokens"]["input"]["per_credit_unit"] = 1
    model["pricing"]["context_bands"]["over_272k"]["tokens"]["input"]["per_credit_unit"] = 1
    receipt = build_model_usage_breakdown(tracker.usage_by_model, _lookup(model))
    assert len(receipt["entries"]) == 1
    entry = receipt["entries"][0]
    assert entry["context_band"] == "over_272k"
    assert entry["rates"]["input"] == "82.5"
    assert entry["rates"]["cache_read"] == "1650"
    assert entry["rates"]["output"] == "20"
    assert entry["pricing_version"] == frozen["pricing_version"]
    assert tracker.usage_by_model[0]["tariff_snapshot"] == frozen


def test_openai_fallback_attempts_choose_independent_context_bands_and_floor_once() -> None:
    frozen = snapshot_model_tariff(_active_openai_model("gpt-6-luna"))
    tracker = ModelUsageTracker()
    for attempt_id, input_tokens in (("first-host", 272_000), ("second-host", 272_001)):
        usage = normalize_provider_usage(
            {"input_tokens": input_tokens, "output_tokens": 1, "cache_read_input_tokens": 0},
            model_id="openai/gpt-6-luna", provider_kind="openai", inference_host="openai",
            attempt_id=attempt_id, tariff_snapshot=frozen,
        )
        tracker.record_reported_usage(model_id=usage.model_id, normalized_usage=usage)
    receipt = build_model_usage_breakdown(tracker.usage_by_model, _lookup({}))
    assert [entry["context_band"] for entry in receipt["entries"]] == ["standard", "over_272k"]
    assert [entry["rates"]["output"] for entry in receipt["entries"]] == ["650", "433"]
    assert receipt["credits_charged"] == int(Decimal(receipt["raw_credits"]))
    assert receipt["credits_charged"] > 0


def test_openai_long_context_missing_cache_counter_uses_long_ordinary_input() -> None:
    model = _active_openai_model("gpt-6.1-sol")
    usage = normalize_provider_usage(
        {"input_tokens": 272_001, "output_tokens": 30},
        model_id="openai/gpt-6.1-sol", provider_kind="openai", inference_host="openai",
    ).to_bucket()
    long_entry = build_model_usage_breakdown([usage], _lookup(model))["entries"][0]
    assert long_entry["context_band"] == "over_272k"
    assert long_entry["billing_mode"] == "ordinary_input"
    assert long_entry["billed_input_tokens"] == 272_001
    assert long_entry["rates"]["input"] == "82.5"
    assert long_entry["rates"]["cache_read"] is None
    assert long_entry["category_credits"]["cache_read"] == "0"

    disabled = copy.deepcopy(model)
    disabled["cache_pricing"]["enabled"] = False
    old_entry = build_model_usage_breakdown([usage], _lookup(disabled))["entries"][0]
    assert "context_band" not in old_entry
    assert old_entry["rates"]["input"] == "165"
    ineligible = build_model_usage_breakdown([{**usage, "inference_host": "openrouter"}], _lookup(model))["entries"][0]
    assert "context_band" not in ineligible
    assert ineligible["rates"]["input"] == "165"


def test_openai_long_context_activation_rejects_malformed_or_missing_band() -> None:
    model = _active_openai_model("gpt-6.1-sol")
    model["pricing"]["context_bands"]["over_272k"]["min_input_tokens"] = 272_000
    with pytest.raises(BillingError, match="boundary"):
        snapshot_model_tariff(model)
    model["pricing"]["context_bands"]["over_272k"]["min_input_tokens"] = 272_001
    model["pricing"]["context_bands"]["over_272k"]["tokens"]["output"]["per_credit_unit"] = 21
    with pytest.raises(BillingError, match="multiplier"):
        snapshot_model_tariff(model)
    model["pricing"].pop("context_bands")
    with pytest.raises(BillingError, match="lacks a customer band"):
        snapshot_model_tariff(model)


def test_anthropic_haiku_long_context_uses_inclusive_cached_and_tool_input() -> None:
    tariff = snapshot_model_tariff(_provider_model("anthropic", "claude-haiku-5-5"))
    base = tariff["pricing"]["tokens"]
    for category, row in base.items():
        band_unit = tariff["pricing"]["context_bands"]["over_100k"]["tokens"][category]["per_credit_unit"]
        assert Fraction(Decimal(str(band_unit))) == Fraction(Decimal(str(row["per_credit_unit"]))) / 5

    # Anthropic's native input includes ordinary prompt and tool-result input;
    # cache reads and writes are added to get the inclusive threshold total.
    for native_input, expected_total, expected_band in (
        (99_800, 100_000, "standard"),
        (99_801, 100_001, "over_100k"),
    ):
        usage = normalize_provider_usage(
            {"input_tokens": native_input, "output_tokens": 20,
             "cache_read_input_tokens": 100, "cache_creation_input_tokens": 100,
             "cache_creation_5m_input_tokens": 100, "cache_creation_1h_input_tokens": 0},
            model_id="anthropic/claude-haiku-5-5", provider_kind="anthropic",
            inference_host="anthropic",
        )
        assert usage.input_total == expected_total
        band, rates = select_customer_context_band(
            model_pricing_details=tariff, inference_host="anthropic", input_total=usage.input_total,
        )
        assert band == expected_band
        assert rates["input"]["per_credit_unit"] == (3300 if expected_band == "standard" else 660)


def test_anthropic_haiku_attempts_freeze_receipt_rates_and_supplier_costs() -> None:
    model = _provider_model("anthropic", "claude-haiku-5-5")
    frozen = snapshot_model_tariff(model)
    tracker = ModelUsageTracker()
    usages = []
    for attempt_id, native_input in (("at-100k", 99_800), ("over-100k", 99_801)):
        usage = normalize_provider_usage(
            {"input_tokens": native_input, "output_tokens": 20,
             "cache_read_input_tokens": 100, "cache_creation_input_tokens": 100,
             "cache_creation_5m_input_tokens": 100, "cache_creation_1h_input_tokens": 0},
            model_id="anthropic/claude-haiku-5-5", provider_kind="anthropic",
            inference_host="anthropic", attempt_id=attempt_id, tariff_snapshot=frozen,
        )
        tracker.record_reported_usage(model_id=usage.model_id, normalized_usage=usage)
        usages.append(usage)

    model["pricing"]["tokens"]["input"]["per_credit_unit"] = 1
    model["pricing"]["context_bands"]["over_100k"]["tokens"]["input"]["per_credit_unit"] = 1
    receipt = build_model_usage_breakdown(tracker.usage_by_model, _lookup(model))
    assert [entry["context_band"] for entry in receipt["entries"]] == ["standard", "over_100k"]
    assert [entry["billing_mode"] for entry in receipt["entries"]] == ["cache_aware", "cache_aware"]
    assert [entry["rates"]["input"] for entry in receipt["entries"]] == ["3300", "660"]
    assert [entry["rates"]["cache_read"] for entry in receipt["entries"]] == ["33000", "6600"]
    assert [entry["rates"]["cache_write"] for entry in receipt["entries"]] == ["2640", "528"]
    assert [entry["rates"]["output"] for entry in receipt["entries"]] == ["660", "132"]
    assert all(entry["rates"]["cache_write_1h"] is None for entry in receipt["entries"])
    assert all(entry["pricing_version"] == frozen["pricing_version"] for entry in receipt["entries"])
    assert all(bucket["tariff_snapshot"] == frozen for bucket in tracker.usage_by_model)
    assert receipt["credits_charged"] == 181
    validate_public_llm_usage_receipt(receipt)

    for usage, expected in (
        (usages[0], "0.0100035"),
        (usages[1], "0.050018"),
    ):
        supplier = calculate_cache_aware_supplier_cost(
            usage=usage.to_bucket(), model_pricing_details=frozen,
            inference_host="anthropic",
        )
        assert supplier["complete"] is True
        assert Decimal(supplier["cost_usd"]) == Decimal(expected)


@pytest.mark.parametrize("change,match", [
    (lambda model: model["pricing"]["context_bands"]["over_100k"].update(min_input_tokens=100_000), "boundary"),
    (lambda model: model["pricing"]["context_bands"]["over_100k"].update(eligible_hosts=["aws_bedrock"]), "host"),
    (lambda model: model["pricing"]["context_bands"]["over_100k"]["tokens"]["output"].update(per_credit_unit=133), "multiplier"),
    (lambda model: model["pricing"]["context_bands"]["over_100k"]["tokens"]["cache_write_1h"].update(per_credit_unit=331), "multiplier"),
    (lambda model: model["pricing"].pop("context_bands"), "lacks a customer band"),
])
def test_anthropic_haiku_rejects_malformed_or_missing_customer_band(change, match: str) -> None:
    model = _provider_model("anthropic", "claude-haiku-5-5")
    change(model)
    with pytest.raises(BillingError, match=match):
        snapshot_model_tariff(model)


def test_summary_receipt_uses_full_reported_anthropic_input_while_main_stays_legacy() -> None:
    tariff = snapshot_model_tariff(_pricing(False))
    usage = normalize_provider_usage(
        {"input_tokens": 100, "output_tokens": 5, "cache_read_input_tokens": 40,
         "cache_creation_input_tokens": 10},
        model_id="anthropic/summary", provider_kind="anthropic", inference_host="anthropic",
        attempt_id="summary-1", tariff_snapshot=tariff,
    ).to_bucket()
    assert usage["input_tokens"] == 150 and usage["legacy_billable_input_tokens"] == 100
    main = build_model_usage_breakdown([usage], _lookup({}))
    summary = build_summary_usage_breakdown([usage], _lookup({}))
    assert main["credits_charged"] == 11
    assert "purpose" not in main["entries"][0]
    assert summary["credits_charged"] == 16
    assert summary["entries"][0]["purpose"] == "summary"
    assert summary["entries"][0]["billed_input_tokens"] == 150
    assert summary["entries"][0]["billing_mode"] == "ordinary_input"
    assert summary["entries"][0]["rates"]["cache_read"] is None
    assert summary["entries"][0]["category_credits"]["cache_read"] == "0"


def test_summary_receipt_bills_google_thoughts_once_with_frozen_ordinary_rates() -> None:
    tariff = snapshot_model_tariff(_pricing(False))
    usage = normalize_provider_usage(
        {"prompt_token_count": 100, "candidates_token_count": 20, "thoughts_token_count": 10},
        model_id="google/summary", provider_kind="google", inference_host="google",
        attempt_id="summary-1", tariff_snapshot=tariff,
    ).to_bucket()
    assert usage["output_tokens"] == 30 and usage["legacy_billable_output_tokens"] == 20
    main = build_model_usage_breakdown([usage], _lookup({}))
    summary = build_summary_usage_breakdown([usage], _lookup({}))
    assert main["credits_charged"] == 14
    assert summary["credits_charged"] == 16
    assert summary["output_tokens"] == 30
    assert summary["entries"][0]["category_credits"]["output"] == "6"


def test_summary_receipt_selects_long_context_band_from_reported_inclusive_input() -> None:
    tariff = snapshot_model_tariff(_active_openai_model("gpt-6.1-sol"))
    buckets = [
        normalize_provider_usage(
            {"input_tokens": tokens, "output_tokens": 30, "cache_read_input_tokens": 100_000},
            model_id="openai/gpt-6.1-sol", provider_kind="openai", inference_host="openai",
            attempt_id=f"summary-{tokens}", tariff_snapshot=tariff,
        ).to_bucket()
        for tokens in (272_000, 272_001)
    ]
    receipt = build_summary_usage_breakdown(buckets, _lookup({}))
    assert [entry["context_band"] for entry in receipt["entries"]] == ["standard", "over_272k"]
    assert [entry["rates"]["input"] for entry in receipt["entries"]] == ["165", "82.5"]
    assert [entry["rates"]["output"] for entry in receipt["entries"]] == ["30", "20"]
    assert receipt["input_tokens"] == 544_001
    assert receipt["output_tokens"] == 60


def test_summary_receipt_respects_verified_cache_rates_without_inventing_missing_counters() -> None:
    tariff = snapshot_model_tariff(_pricing(True))
    known = normalize_provider_usage(
        {"input_tokens": 100, "output_tokens": 5, "cache_read_input_tokens": 40,
         "cache_creation_input_tokens": 10},
        model_id="openai/summary", provider_kind="openai", inference_host="openai",
        attempt_id="known", tariff_snapshot=tariff,
    ).to_bucket()
    unknown = normalize_provider_usage(
        {"input_tokens": 100, "output_tokens": 5, "cache_read_input_tokens": 40},
        model_id="openai/summary", provider_kind="openai", inference_host="openai",
        attempt_id="unknown", tariff_snapshot=tariff,
    ).to_bucket()
    known_entry = build_summary_usage_breakdown([known], _lookup({}))["entries"][0]
    unknown_entry = build_summary_usage_breakdown([unknown], _lookup({}))["entries"][0]
    assert known_entry["billing_mode"] == "cache_aware"
    assert known_entry["category_credits"]["cache_read"] == "0.4"
    assert known_entry["category_credits"]["cache_write"] == "1.25"
    assert unknown_entry["billing_mode"] == "ordinary_input"
    assert unknown_entry["billed_input_tokens"] == 100
    assert unknown_entry["rates"]["cache_read"] is None
    assert unknown_entry["category_credits"]["cache_read"] == "0"


@pytest.mark.parametrize("invalid", [
    {"input_tokens": None}, {"output_tokens": None}, {"output_tokens": -1},
    {"usage_source": "estimated"}, {"attempt_id": None}, {"tariff_snapshot": None},
])
def test_summary_receipt_rejects_unknown_totals_or_unfrozen_attempt(invalid: dict) -> None:
    tariff = snapshot_model_tariff(_pricing(False))
    bucket = normalize_provider_usage(
        {"input_tokens": 10, "output_tokens": 2},
        model_id="openai/summary", provider_kind="openai", inference_host="openai",
        attempt_id="summary-1", tariff_snapshot=tariff,
    ).to_bucket()
    with pytest.raises(ValueError, match="Summary billing requires"):
        build_summary_usage_breakdown([{**bucket, **invalid}], _lookup({}))


def test_summary_receipt_replaces_replayed_attempt_and_floors_fallbacks_once() -> None:
    model = _pricing(False)
    tariff = snapshot_model_tariff(model)
    buckets = [
        normalize_provider_usage(
            {"input_tokens": tokens, "output_tokens": 0},
            model_id="openai/summary", provider_kind="openai", inference_host="openai",
            attempt_id=attempt_id, tariff_snapshot=tariff,
        ).to_bucket()
        for attempt_id, tokens in (("first", 2), ("first", 4), ("fallback", 4))
    ]
    model["pricing"]["tokens"]["input"]["per_credit_unit"] = 1
    receipt = build_summary_usage_breakdown(buckets, _lookup(model))
    assert receipt["input_tokens"] == 8
    assert len(receipt["entries"]) == 2
    assert receipt["raw_credits"] == "0.8"
    assert receipt["credits_charged"] == 1
    assert all(entry["rates"]["input"] == "10" for entry in receipt["entries"])
    assert all(entry["purpose"] == "summary" for entry in receipt["entries"])
