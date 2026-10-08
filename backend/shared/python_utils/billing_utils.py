# backend/shared/python_utils/billing_utils.py
# This module contains utility functions for calculating costs and credits
# based on usage metrics and pricing configurations.

import logging
import math
import os
import copy
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_EVEN
from decimal import localcontext
from fractions import Fraction
from typing import Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Define a type alias for pricing configuration for clarity
PricingConfig = Dict[str, Any]
ModelPricingDetails = PricingConfig

MINIMUM_CREDITS_CHARGED = 1
OVERDRAFT_LIMIT_CREDITS = -500
OPENAI_LONG_CONTEXT_MIN_INPUT_TOKENS = 272_001
ANTHROPIC_LONG_CONTEXT_MIN_INPUT_TOKENS = 100_001
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")

class BillingError(Exception):
    """Custom exception for billing related errors."""
    pass


def has_credit_headroom(current_credits: int, estimated_credits: int) -> bool:
    """Return whether a planned charge stays within the allowed overdraft."""
    return current_credits - estimated_credits >= OVERDRAFT_LIMIT_CREDITS


async def ensure_credit_headroom(
    *,
    user_id: str,
    estimated_credits: int,
    log_prefix: str,
    operation_name: str,
) -> None:
    """Reject paid provider calls that would exceed the allowed overdraft.

    The balance endpoint is cache-backed and intentionally non-critical. On a
    cache miss or infrastructure failure we log and proceed, matching the
    existing billing contract while blocking known insufficient balances.
    """
    if estimated_credits <= 0:
        return

    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{INTERNAL_API_BASE_URL}/internal/billing/balance",
                params={"user_id": user_id},
                headers=headers,
            )
            response.raise_for_status()
        balance = response.json()
    except Exception as exc:
        logger.warning("%s Could not precheck %s credits; proceeding: %s", log_prefix, operation_name, exc)
        return

    if not balance.get("cached"):
        logger.warning("%s Credit balance not cached; proceeding with %s precheck skipped", log_prefix, operation_name)
        return

    current_credits = balance.get("credits", 0)
    if not isinstance(current_credits, int):
        current_credits = 0

    if not has_credit_headroom(current_credits, estimated_credits):
        logger.warning(
            "%s Insufficient credits for %s precheck: current=%s estimated=%s overdraft_limit=%s",
            log_prefix,
            operation_name,
            current_credits,
            estimated_credits,
            OVERDRAFT_LIMIT_CREDITS,
        )
        raise BillingError(f"Insufficient credits for {operation_name}")

# A constant representing the value of one credit in USD.
# This is based on the standard pricing tier of 110,000 credits for $110.
USD_PER_CREDIT = 0.001

def get_usd_per_credit() -> float:
    """
    Returns the fixed USD value per credit.
    """
    return USD_PER_CREDIT


def decimal_string(value: Decimal | Fraction) -> str:
    """Emit a stable display decimal; exact Fraction math decides the debit."""
    if isinstance(value, Fraction):
        with localcontext() as context:
            context.prec = max(80, len(str(abs(value.numerator))) + len(str(value.denominator)) + 30)
            value = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
                Decimal("0.000000000000000000000001"), rounding=ROUND_HALF_EVEN,
            )
    if value == 0:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def floor_raw_credits(raw_credits: Decimal | Fraction) -> int:
    """Apply the existing one-charge floor and minimum after all categories."""
    if raw_credits < 0:
        raise BillingError("Raw credits cannot be negative")
    rounded = (
        raw_credits.numerator // raw_credits.denominator
        if isinstance(raw_credits, Fraction)
        else int(raw_credits.to_integral_value(rounding=ROUND_FLOOR))
    )
    return max(MINIMUM_CREDITS_CHARGED, rounded) if raw_credits > 0 else 0


def snapshot_model_tariff(model_pricing_details: ModelPricingDetails) -> Dict[str, Any]:
    """Copy a tariff for an already-admitted attempt so YAML reloads cannot reprice it."""
    snapshot = {
        "pricing": copy.deepcopy(model_pricing_details.get("pricing", model_pricing_details if "tokens" in model_pricing_details else {})),
        "costs": copy.deepcopy(model_pricing_details.get("costs", {})),
        "cache_pricing": copy.deepcopy(model_pricing_details.get("cache_pricing", {})),
        "supplier_cost_profiles": copy.deepcopy(model_pricing_details.get("supplier_cost_profiles", {})),
        "local": bool(model_pricing_details.get("local")),
        "self_hosted": bool(model_pricing_details.get("self_hosted")),
    }
    policy = snapshot["cache_pricing"]
    if policy.get("enabled"):
        today = date.today()
        if policy.get("status") != "verified_for_activation":
            raise BillingError("Cache tariff lacks verified activation status")
        if not all(
            policy.get(field) for field in ("source_url", "reviewed_on", "expires_on", "eligible_hosts")
        ):
            raise BillingError("Verified cache tariff lacks a source, expiry, or eligible route")
        if not isinstance(policy["eligible_hosts"], list) or not all(
            isinstance(host, str) and host for host in policy["eligible_hosts"]
        ):
            raise BillingError("Cache tariff eligible routes are invalid")
        try:
            reviewed = date.fromisoformat(str(policy["reviewed_on"]))
            expiry = date.fromisoformat(str(policy["expires_on"]))
            effective = date.fromisoformat(str(policy.get("effective_from", reviewed.isoformat())))
        except (TypeError, ValueError) as exc:
            raise BillingError("Cache tariff dates are invalid") from exc
        if reviewed > today:
            raise BillingError("Cache tariff review date is in the future")
        if today < effective:
            raise BillingError("Cache tariff is not yet effective")
        if today > expiry:
            raise BillingError("Cache tariff has expired")
        for host in policy["eligible_hosts"]:
            select_customer_context_band(
                model_pricing_details=snapshot, inference_host=host, input_total=0,
            )
        snapshot["admitted_on"] = today.isoformat()
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    snapshot["pricing_version"] = str(
        model_pricing_details.get("pricing_version") or hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    )
    return snapshot


def is_cache_tariff_eligible(cache_policy: Dict[str, Any], inference_host: str | None) -> bool:
    """One admission predicate for active output and partial-cache fallback."""
    return bool(
        cache_policy.get("enabled")
        and cache_policy.get("status") == "verified_for_activation"
        and (not cache_policy.get("eligible_hosts") or inference_host in cache_policy["eligible_hosts"])
    )


def is_cache_tariff_admissible(
    cache_policy: Dict[str, Any], inference_host: str | None, *, on_date: date | None = None,
) -> bool:
    """Fail closed when admitting new cache controls or a new public tariff.

    Settlement of an already admitted attempt uses its frozen snapshot instead
    of this clock-sensitive check, so expiry cannot reprice past work.
    """
    if (not inference_host or cache_policy.get("status") != "verified_for_activation"
            or not is_cache_tariff_eligible(cache_policy, inference_host)):
        return False
    if not all(cache_policy.get(field) for field in ("source_url", "reviewed_on", "expires_on", "eligible_hosts")):
        return False
    if not isinstance(cache_policy["eligible_hosts"], list) or not all(
        isinstance(host, str) and host for host in cache_policy["eligible_hosts"]
    ):
        return False
    try:
        today = on_date or date.today()
        reviewed = date.fromisoformat(str(cache_policy["reviewed_on"]))
        expiry = date.fromisoformat(str(cache_policy["expires_on"]))
        effective = date.fromisoformat(str(cache_policy.get("effective_from", reviewed.isoformat())))
    except (TypeError, ValueError):
        return False
    return reviewed <= today <= expiry and effective <= today


def select_customer_context_band(
    *, model_pricing_details: ModelPricingDetails, inference_host: str | None, input_total: int,
) -> tuple[str | None, Dict[str, Any]]:
    """Select frozen customer token units from one provider attempt's inclusive input.

    Inactive routes retain their original token units and receipt shape. Customer
    bands are public tariff data, independent from private supplier cost profiles.
    """
    pricing = model_pricing_details.get("pricing", model_pricing_details)
    base_rates = pricing.get("tokens", {})
    policy = model_pricing_details.get("cache_pricing", {})
    if not is_cache_tariff_eligible(policy, inference_host):
        return None, base_rates
    if isinstance(input_total, bool) or not isinstance(input_total, int) or input_total < 0:
        raise BillingError("Inclusive input tokens must be a non-negative integer")

    bands = pricing.get("context_bands")
    supplier_bands = (
        (model_pricing_details.get("supplier_cost_profiles", {}).get("openai", {})
         .get("context_bands") or {})
    )
    if inference_host == "openai" and "over_272k" in supplier_bands and not bands:
        raise BillingError("OpenAI long-context supplier price lacks a customer band")
    anthropic_supplier_bands = (
        (model_pricing_details.get("supplier_cost_profiles", {}).get("anthropic", {})
         .get("context_bands") or {})
    )
    if inference_host == "anthropic" and "over_100k" in anthropic_supplier_bands and not bands:
        raise BillingError("Anthropic long-context supplier price lacks a customer band")
    if bands is None:
        return None, base_rates
    if not isinstance(bands, dict) or set(bands) not in ({"over_272k"}, {"over_100k"}):
        raise BillingError("Unsupported customer context bands")
    band_name = next(iter(bands))
    anthropic_band = band_name == "over_100k"
    band = bands[band_name]
    if not isinstance(band, dict) or set(band) != {"min_input_tokens", "eligible_hosts", "tokens"}:
        raise BillingError(
            "Invalid Anthropic customer context band" if anthropic_band
            else "Invalid OpenAI customer context band"
        )
    min_input_tokens = (
        ANTHROPIC_LONG_CONTEXT_MIN_INPUT_TOKENS if anthropic_band
        else OPENAI_LONG_CONTEXT_MIN_INPUT_TOKENS
    )
    eligible_hosts = ["anthropic"] if anthropic_band else ["openai"]
    if (type(band["min_input_tokens"]) is not int
            or band["min_input_tokens"] != min_input_tokens
            or band["eligible_hosts"] != eligible_hosts):
        raise BillingError(
            "Invalid Anthropic customer context boundary or host" if anthropic_band
            else "Invalid OpenAI customer context boundary or host"
        )
    band_rates = band["tokens"]
    if not isinstance(base_rates, dict) or not isinstance(band_rates, dict) or set(band_rates) != set(base_rates):
        raise BillingError("Customer context band categories do not match the base tariff")
    for category, base_row in base_rates.items():
        band_row = band_rates[category]
        if (category not in {"input", "output", "cache_read", "cache_write", "cache_write_1h"}
                or not isinstance(base_row, dict) or not isinstance(band_row, dict)
                or set(band_row) != {"per_credit_unit"}):
            raise BillingError("Invalid customer context band token category")
        try:
            base_unit = Decimal(str(base_row["per_credit_unit"]))
            band_unit = Decimal(str(band_row["per_credit_unit"]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise BillingError("Invalid customer context band token unit") from exc
        if not base_unit.is_finite() or base_unit <= 0 or not band_unit.is_finite() or band_unit <= 0:
            raise BillingError("Invalid customer context band token unit")
        if anthropic_band:
            expected = Fraction(base_unit) / 5
        elif category == "output":
            expected = Fraction(base_unit) * Fraction(2, 3) // 1
        else:
            expected = Fraction(base_unit) / 2
        if Fraction(band_unit) != expected:
            raise BillingError("Customer context band does not match the approved multiplier")
    if inference_host not in band["eligible_hosts"]:
        return None, base_rates
    return (
        (band_name, band_rates)
        if input_total >= band["min_input_tokens"] else ("standard", base_rates)
    )


def calculate_token_category_credits(
    *,
    input_total: int,
    uncached_input: int,
    cache_read: int | None,
    cache_write: int | None,
    cache_write_1h: int | None,
    output_tokens: int,
    legacy_billable_input: int | None,
    model_pricing_details: ModelPricingDetails,
    usage_source: str = "provider_reported",
    inference_host: str | None = None,
    legacy_billable_output: int | None = None,
) -> tuple[Dict[str, Fraction], bool]:
    """Calculate fractional category credits; never round an individual category.

    Proposed cache rates are inert until the model's flag, host and provider
    counters qualify. An eligible route with partial counters charges its known
    inclusive input at the ordinary rate, without a fabricated hit or write.
    Disabled/ineligible routes retain the old native input/output charge.
    """
    if min(input_total, uncached_input, output_tokens) < 0:
        raise BillingError("Token counts cannot be negative")
    if legacy_billable_output is not None and (legacy_billable_output < 0 or legacy_billable_output > output_tokens):
        raise BillingError("Legacy output count must be within normalized billable output")
    _context_band, rates = select_customer_context_band(
        model_pricing_details=model_pricing_details,
        inference_host=inference_host,
        input_total=input_total,
    )
    cache_policy = model_pricing_details.get("cache_pricing", {})
    eligible_policy = is_cache_tariff_eligible(cache_policy, inference_host)
    charged_output = (
        output_tokens if eligible_policy
        else output_tokens if legacy_billable_output is None else legacy_billable_output
    )
    separate_writes = cache_policy.get("write_billing") == "separate"
    one_hour_hosts = cache_policy.get("cache_write_1h_hosts")
    one_hour_allowed = one_hour_hosts is None or inference_host in one_hour_hosts
    active = bool(
        eligible_policy
        and usage_source == "provider_reported"
        and cache_read is not None
        and rates.get("cache_read", {}).get("per_credit_unit") is not None
        and (not separate_writes or cache_write is not None)
        and (not separate_writes or rates.get("cache_write", {}).get("per_credit_unit") is not None)
        and (not cache_policy.get("requires_cache_retention_metric") or cache_write_1h is not None)
        and (not cache_policy.get("requires_cache_retention_metric") or rates.get("cache_write_1h", {}).get("per_credit_unit") is not None)
        and (one_hour_allowed or not cache_write_1h)
    )
    if active and (
        uncached_input + cache_read + (cache_write or 0) != input_total
        or (cache_write_1h or 0) > (cache_write or 0)
    ):
        raise BillingError("Cache usage categories do not reconcile to total input")

    def credits(tokens: int, category: str) -> Fraction:
        if tokens == 0:
            return Fraction(0)
        unit = rates.get(category, {}).get("per_credit_unit")
        if unit is None:
            raise BillingError(f"Missing {category} token tariff for reported usage")
        unit_decimal = Decimal(str(unit))
        if not unit_decimal.is_finite() or unit_decimal <= 0:
            raise BillingError(f"Invalid {category} token tariff")
        return Fraction(tokens) / Fraction(unit_decimal)

    if not active:
        # An enabled/eligible route with partial counters has already incurred
        # every *known* reported input category. Bill that inclusive total at
        # the ordinary rate. Only disabled/ineligible routes retain the old
        # native-input charge (exclusive of cache tokens on Anthropic/Bedrock).
        legacy_input = (
            input_total if eligible_policy or legacy_billable_input is None
            else legacy_billable_input
        )
        return {
            "input": credits(legacy_input, "input"),
            "cache_read": Fraction(0),
            "cache_write": Fraction(0),
            "cache_write_1h": Fraction(0),
            "output": credits(charged_output, "output"),
        }, False

    write_1h = cache_write_1h or 0
    regular_write = (cache_write or 0) - write_1h
    if not separate_writes:
        # Implicit fills are already covered by ordinary input. No invented
        # write fee is added when a provider cannot expose a distinct write.
        ordinary_input = uncached_input + (cache_write or 0)
        regular_write = write_1h = 0
    else:
        ordinary_input = uncached_input
    return {
        "input": credits(ordinary_input, "input"),
        "cache_read": credits(cache_read, "cache_read"),
        "cache_write": credits(regular_write, "cache_write"),
        "cache_write_1h": credits(write_1h, "cache_write_1h"),
        "output": credits(charged_output, "output"),
    }, True


def calculate_cache_aware_supplier_cost(
    *,
    usage: Dict[str, Any],
    model_pricing_details: ModelPricingDetails,
    inference_host: str | None = None,
    region: str | None = None,
    context_band: str | None = None,
    service_tier: str | None = None,
    modality: str | None = None,
) -> Dict[str, Any]:
    """Estimate supplier cost from reported categories and actual host.

    ``complete=False`` means this must not be represented as realized margin.
    Missing supplier rates remain unknown rather than silently becoming zero.
    """
    costs = model_pricing_details.get("costs", {})
    profiles = model_pricing_details.get("supplier_cost_profiles", {})
    missing: list[str] = []
    if not inference_host:
        missing.append("inference_host")
    if usage.get("input_tokens") is None:
        missing.append("input_tokens")
    if usage.get("output_tokens") is None:
        missing.append("output_tokens")
    if usage.get("usage_source") == "estimated":
        missing.append("provider_reported_usage")
    expires_on = model_pricing_details.get("cache_pricing", {}).get("expires_on")
    # Replayed settlements retain the tariff admitted before expiry. Only a
    # newly resolved, unsnapshotted price is checked against today's date.
    tariff_admitted_on = model_pricing_details.get("admitted_on") or date.today().isoformat()
    if expires_on and str(tariff_admitted_on) > str(expires_on):
        missing.append("tariff_expired")
    profile = profiles.get(inference_host or "", {})
    route_costs = profile.get("costs", {})
    if not isinstance(route_costs, dict):
        raise BillingError("Invalid supplier route costs")
    costs = {**costs, **route_costs}
    if profile.get("region") and region != profile["region"]:
        missing.append("region")
        # Retain the declared route's conservative multiplier even when its
        # region is absent or differs. The bound remains incomplete until the
        # actual supplier region is proven.
    multiplier = Decimal(str(profile.get("multiplier", 1)))
    if not multiplier.is_finite() or multiplier <= 0:
        raise BillingError("Invalid supplier cost profile multiplier")
    read = usage.get("cache_read_input_tokens")
    write = usage.get("cache_creation_input_tokens")
    write_1h_reported = usage.get("cache_creation_1h_input_tokens")
    write_5m_reported = usage.get("cache_creation_5m_input_tokens")
    write_1h = write_1h_reported or 0
    allowed_one_hour_hosts = model_pricing_details.get("cache_pricing", {}).get("cache_write_1h_hosts")
    if allowed_one_hour_hosts is not None and inference_host not in allowed_one_hour_hosts and write_1h:
        missing.append("unpermitted_cache_write_1h_host")
    total = int(usage.get("input_tokens") or 0)
    uncached = int(usage.get("uncached_input_tokens", total - (read or 0) - (write or 0)))
    output = int(usage.get("output_tokens") or 0)
    if context_band is None and inference_host == "openai" and total > 272_000:
        context_band = "over_272k"
    if (context_band is None and inference_host == "anthropic" and total > 100_000
            and "over_100k" in (profile.get("context_bands") or {})):
        context_band = "over_100k"
    context_rates = (profile.get("context_bands") or {}).get(context_band or "standard", {})
    tier_rates = (profile.get("service_tiers") or {}).get(service_tier or "standard", {})
    if context_band not in (None, "standard") and not context_rates:
        missing.append("context_band")
    if service_tier not in (None, "standard") and not tier_rates:
        missing.append("service_tier")
    if modality not in (None, "text") and not (profile.get("modalities") or {}).get(modality):
        missing.append("modality")

    def amount(tokens: int, category: str, *keys: str) -> Decimal:
        if tokens <= 0:
            return Decimal(0)
        cost = next((costs.get(key) for key in keys if costs.get(key) is not None), None)
        if not isinstance(cost, dict) or cost.get("price") is None:
            missing.append(keys[0])
            return Decimal(0)
        category_multiplier = Decimal(str(context_rates.get(category, 1))) * Decimal(str(tier_rates.get(category, 1)))
        return Decimal(tokens) * Decimal(str(cost["price"])) * category_multiplier / Decimal(1_000_000)

    value = amount(uncached, "input", "input_per_million_token")
    if read is None:
        missing.append("cache_read_input_tokens")
    else:
        value += amount(int(read), "cache_read", "cache_read_per_million_token", "cached_input_per_million_token")
    separate_writes = model_pricing_details.get("cache_pricing", {}).get("write_billing") == "separate"
    if write is None and (separate_writes or costs.get("cache_write_per_million_token") is not None):
        # Supplier-paid writes cannot be ruled out from an absent counter, even
        # when a public tariff labels fills as included in ordinary input.
        missing.append("cache_creation_input_tokens")
    elif write is not None:
        if write_1h > write:
            raise BillingError("One-hour cache writes exceed total writes")
        if (write > 0 and write_1h_reported is None
                and write_5m_reported != write
                and costs.get("cache_write_1h_per_million_token") is not None):
            missing.append("cache_creation_1h_input_tokens")
        value += amount(int(write) - write_1h, "cache_write", "cache_write_per_million_token", "input_per_million_token")
        value += amount(write_1h, "cache_write", "cache_write_1h_per_million_token")
    value += amount(output, "output", "output_per_million_token")
    # Inclusive providers report a total that bounds unreported paid writes:
    # every non-read input token could be a cache creation. This is a private
    # supplier exposure bound, never a fabricated customer write charge.
    upper_bound: Decimal | None = value
    bounded_unknowns: set[str] = set()
    bound_only_missing: list[str] = []
    if read is None and "cache_read_input_tokens" in missing:
        kind = usage.get("provider_kind")
        implicit_read_hosts = {
            "google": {"google_ai_studio", "google"},
            "mistral": {"mistral"},
        }
        read_cost = costs.get("cache_read_per_million_token") or costs.get("cached_input_per_million_token")
        input_cost = costs.get("input_per_million_token")
        route_has_profile = inference_host != "google" or bool(profile)
        # These providers' ordinary prompt count includes implicit reads and
        # fills. If a read is cheaper than ordinary input, treating every
        # reported prompt token as ordinary is a private upper bound. Never
        # convert the absent read counter to a reported zero.
        if (inference_host in implicit_read_hosts.get(kind, set())
                and route_has_profile and write is None
                and usage.get("usage_source") == "provider_reported"
                and type(usage.get("input_tokens")) is int
                and type(usage.get("output_tokens")) is int
                and total >= 0 and output >= 0
                and usage.get("cache_creation_5m_input_tokens") in (None, 0)
                and usage.get("cache_creation_1h_input_tokens") in (None, 0)
                and costs.get("cache_write_per_million_token") is None
                and model_pricing_details.get("cache_pricing", {}).get("write_billing") == "included_in_input"
                and isinstance(input_cost, dict) and input_cost.get("price") is not None
                and isinstance(read_cost, dict) and read_cost.get("price") is not None):
            ordinary_unit = amount(1_000_000, "input", "input_per_million_token")
            read_unit = amount(1_000_000, "cache_read", "cache_read_per_million_token", "cached_input_per_million_token")
            if (ordinary_unit.is_finite() and read_unit.is_finite()
                    and 0 <= read_unit <= ordinary_unit and uncached == total):
                bounded_unknowns.add("cache_read_input_tokens")
    if "cache_creation_1h_input_tokens" in missing:
        regular_write = amount(int(write or 0), "cache_write", "cache_write_per_million_token", "input_per_million_token")
        all_one_hour = amount(int(write or 0), "cache_write", "cache_write_1h_per_million_token")
        upper_bound += max(all_one_hour - regular_write, Decimal(0))
        bounded_unknowns.add("cache_creation_1h_input_tokens")
    if write is None and costs.get("cache_write_per_million_token") is not None:
        if usage.get("provider_kind") not in {"openai", "mistral", "google"}:
            # Their native input excludes writes. An absent write count leaves
            # an unbounded category outside the reported inclusive total.
            # Unknown counter semantics are also unsuitable for a bound.
            upper_bound = None
            bound_only_missing.append("unbounded_or_unknown_input_counter_semantics")
        else:
            non_read = total - (int(read) if read is not None else 0)
            ordinary_non_read = amount(non_read, "input", "input_per_million_token")
            all_written_non_read = amount(non_read, "cache_write", "cache_write_per_million_token")
            upper_bound = value + max(all_written_non_read - ordinary_non_read, Decimal(0))
            bounded_unknowns.add("cache_creation_input_tokens")
    upper_bound_missing = list(dict.fromkeys(
        [item for item in missing if item not in bounded_unknowns] + bound_only_missing
    ))
    if upper_bound_missing:
        # A partial estimate is useful as cost_usd, but it is not a finite
        # calibrated supplier upper bound when route, output or rate is unknown.
        upper_bound = None
    return {
        "cost_usd": decimal_string(value * multiplier),
        "complete": not missing,
        "missing": missing,
        "cost_upper_bound_usd": decimal_string(upper_bound * multiplier) if upper_bound is not None else None,
        "upper_bound_complete": upper_bound is not None and not upper_bound_missing,
        "upper_bound_missing": upper_bound_missing,
    }

def calculate_real_and_charged_costs(
    input_tokens: int,
    output_tokens: int,
    model_pricing_details: ModelPricingDetails,
    total_credits_charged: int,
    pricing_config: PricingConfig,
) -> Dict[str, float]:
    """
    Calculates the real cost of the LLM call and the cost charged to the user.
    """
    costs = model_pricing_details.get("costs", {})
    input_cost_config = costs.get("input_per_million_token", {})
    output_cost_config = costs.get("output_per_million_token", {})

    input_price_per_million = input_cost_config.get("price", 0)
    output_price_per_million = output_cost_config.get("price", 0)

    real_input_cost = (input_tokens / 1_000_000) * input_price_per_million
    real_output_cost = (output_tokens / 1_000_000) * output_price_per_million
    real_total_cost = real_input_cost + real_output_cost

    usd_per_credit = get_usd_per_credit()
    charged_cost_usd = total_credits_charged * usd_per_credit
    
    margin = charged_cost_usd - real_total_cost

    return {
        "real_cost_usd": real_total_cost,
        "charged_cost_usd": charged_cost_usd,
        "margin_usd": margin,
    }

def calculate_credits_from_tokens(
    input_tokens: int,
    output_tokens: int,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on input and output tokens and their respective pricing.
    Handles cases where output_tokens is 0 (e.g., for interruptions after input is processed).
    """
    credits = 0.0
    token_pricing = pricing_details.get("tokens")
    if not token_pricing:
        return 0.0

    input_pricing = token_pricing.get("input", {})
    output_pricing = token_pricing.get("output", {})

    input_per_credit_unit = input_pricing.get("per_credit_unit")
    output_per_credit_unit = output_pricing.get("per_credit_unit")

    if input_per_credit_unit and input_per_credit_unit > 0:
        credits += (input_tokens / input_per_credit_unit)
    
    if output_tokens > 0 and output_per_credit_unit and output_per_credit_unit > 0:
        credits += (output_tokens / output_per_credit_unit)
        
    return credits

def calculate_credits_from_units(
    units: int,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on units processed (e.g., images, API calls).
    """
    credits = 0.0
    unit_pricing = pricing_details.get("per_unit")
    if unit_pricing and unit_pricing.get("credits") is not None:
        credits_per_unit = unit_pricing.get("credits", 0)
        credits += units * credits_per_unit
    return credits

def calculate_credits_from_duration(
    duration_minutes: float,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on duration in minutes.
    """
    credits = 0.0
    duration_pricing = pricing_details.get("per_minute")
    if isinstance(duration_pricing, (int, float)) and not isinstance(duration_pricing, bool):
        credits_per_minute = duration_pricing
        credits += duration_minutes * credits_per_minute
    elif duration_pricing and duration_pricing.get("credits") is not None:
        credits_per_minute = duration_pricing.get("credits", 0)
        credits += duration_minutes * credits_per_minute
    return credits


def calculate_credits_from_seconds(
    duration_seconds: float,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on duration in seconds.
    """
    credits = 0.0
    second_pricing = pricing_details.get("per_second")
    if isinstance(second_pricing, (int, float)) and not isinstance(second_pricing, bool):
        credits_per_second = second_pricing
        credits += duration_seconds * credits_per_second
    elif second_pricing and second_pricing.get("credits") is not None:
        credits_per_second = second_pricing.get("credits", 0)
        credits += duration_seconds * credits_per_second
    return credits

def calculate_fixed_credits(
    pricing_details: ModelPricingDetails
) -> float:
    """
    Returns fixed credits if defined.
    """
    fixed_pricing = pricing_details.get("fixed")
    if isinstance(fixed_pricing, (int, float)) and not isinstance(fixed_pricing, bool):
        return float(fixed_pricing)
    if fixed_pricing and fixed_pricing.get("credits") is not None:
        return float(fixed_pricing.get("credits", 0))
    return 0.0


def calculate_total_credits(
    *,  # Force keyword arguments
    pricing_config: PricingConfig,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    units_processed: Optional[int] = None,
    duration_minutes: Optional[float] = None,
    duration_seconds: Optional[float] = None,
) -> int:
    """
    Calculates the total credits for a skill execution based on its pricing config and usage metrics.
    Rounds down to the nearest whole credit, but ensures a minimum of 1 credit is charged if any cost is incurred.
    """
    if not pricing_config:
        return 0

    # If the pricing_config contains a 'pricing' key, use that as the basis for calculation.
    # This handles cases where the full model pricing details are passed.
    pricing_rules = pricing_config.get("pricing", pricing_config)

    raw_credits = 0.0

    if "fixed" in pricing_rules:
        raw_credits += calculate_fixed_credits(pricing_rules)

    if "tokens" in pricing_rules and input_tokens is not None:
        # Ensure output_tokens is at least 0 if not provided
        output_tokens = output_tokens if output_tokens is not None else 0
        raw_credits += calculate_credits_from_tokens(input_tokens, output_tokens, pricing_rules)

    if "per_unit" in pricing_rules and units_processed is not None:
        raw_credits += calculate_credits_from_units(units_processed, pricing_rules)

    if "per_minute" in pricing_rules and duration_minutes is not None:
        raw_credits += calculate_credits_from_duration(duration_minutes, pricing_rules)

    if "per_second" in pricing_rules and duration_seconds is not None:
        raw_credits += calculate_credits_from_seconds(duration_seconds, pricing_rules)

    # Floor the raw credits to round down.
    final_credits = math.floor(raw_credits)

    # If the result is 0 after flooring, but there was some cost, charge the minimum.
    if raw_credits > 0 and final_credits == 0:
        final_credits = MINIMUM_CREDITS_CHARGED
    
    logger.info(f"Calculated credits (raw: {raw_credits}, final: {final_credits}) for pricing config: {pricing_config}")

    return int(final_credits)
