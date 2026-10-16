"""Resolve verified, host-scoped temporary tariffs without mutating the catalog."""

import copy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlparse

from backend.shared.python_utils.model_availability import utc_today

TARIFF_FIELDS = ("pricing", "costs", "supplier_cost_profiles")
PROMOTION_FIELDS = (
    "id", "effective_from", "expires_on", "guaranteed_through", "source_url",
    "reviewed_on", "eligible_hosts", "regions", "processing_tier",
)


class ModelPricingError(ValueError):
    """A configured promotion cannot safely authorize priced provider work."""


def _date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        raise ModelPricingError(f"Temporary price {field} must be a UTC calendar date")
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ModelPricingError(f"Invalid temporary price {field}") from exc
    if str(value) != parsed.isoformat():
        raise ModelPricingError(f"Invalid temporary price {field}")
    return parsed


def _strings(value: Any, field: str) -> set[str]:
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(set(value)) != len(value)):
        raise ModelPricingError(f"Invalid temporary price {field}")
    return set(value)


def _number(value: Any, *, positive: bool) -> None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ModelPricingError("Invalid temporary token price") from exc
    if isinstance(value, bool) or not parsed.is_finite() or parsed < 0 or (positive and parsed == 0):
        raise ModelPricingError("Invalid temporary token price")


def _validate_rates(base: Mapping[str, Any], offer: Mapping[str, Any]) -> None:
    for field in ("pricing", "costs"):
        if not isinstance(base.get(field), dict) or not isinstance(offer.get(field), dict):
            raise ModelPricingError(f"Temporary price requires complete {field}")
    rates = offer["pricing"].get("tokens")
    base_rates = base["pricing"].get("tokens")
    if not isinstance(rates, dict) or not rates or not isinstance(base_rates, dict) or set(rates) != set(base_rates):
        raise ModelPricingError("Temporary price token categories must match the regular tariff")
    for row in rates.values():
        if not isinstance(row, dict) or set(row) != {"per_credit_unit"}:
            raise ModelPricingError("Invalid temporary price token category")
        _number(row["per_credit_unit"], positive=True)
    if set(offer["costs"]) != set(base["costs"]):
        raise ModelPricingError("Temporary supplier cost categories must match the regular tariff")
    for key, row in offer["costs"].items():
        regular = base["costs"][key]
        if (not isinstance(row, dict) or not isinstance(regular, dict)
                or {key: value for key, value in row.items() if key != "price"}
                != {key: value for key, value in regular.items() if key != "price"}):
            raise ModelPricingError("Temporary supplier currency must match the regular tariff")
        _number(row.get("price"), positive=False)
    bands = offer["pricing"].get("context_bands", {})
    if not isinstance(bands, dict) or set(bands) != set(base["pricing"].get("context_bands", {})):
        raise ModelPricingError("Temporary context bands must match the regular tariff")
    for name, band in bands.items():
        regular_band = base["pricing"]["context_bands"][name]
        if (not isinstance(band, dict) or band.get("min_input_tokens") != regular_band.get("min_input_tokens")
                or band.get("eligible_hosts") != regular_band.get("eligible_hosts")
                or not isinstance(band.get("tokens"), dict) or set(band["tokens"]) != set(rates)):
            raise ModelPricingError("Temporary context band boundary, hosts, or categories changed")
        for row in band["tokens"].values():
            if not isinstance(row, dict) or set(row) != {"per_credit_unit"}:
                raise ModelPricingError("Invalid temporary context band rate")
            _number(row["per_credit_unit"], positive=True)
    profiles = offer.get("supplier_cost_profiles")
    if profiles is not None:
        if not isinstance(profiles, dict) or set(profiles) != set(base.get("supplier_cost_profiles", {})):
            raise ModelPricingError("Temporary supplier profiles must preserve every regular host")
        for profile in profiles.values():
            if not isinstance(profile, dict):
                raise ModelPricingError("Invalid temporary supplier profile")
            _number(profile.get("multiplier", 1), positive=True)
            if "region" in profile and (not isinstance(profile["region"], str) or not profile["region"]):
                raise ModelPricingError("Invalid temporary supplier region")
            route_costs = profile.get("costs", {})
            if not isinstance(route_costs, dict):
                raise ModelPricingError("Invalid temporary supplier route costs")
            for key, row in route_costs.items():
                if (key not in base["costs"] or not isinstance(row, dict)
                        or row.get("currency") != base["costs"][key].get("currency")):
                    raise ModelPricingError("Invalid temporary supplier route cost")
                _number(row.get("price"), positive=False)
            for field in ("context_bands", "service_tiers", "modalities"):
                groups = profile.get(field, {})
                if not isinstance(groups, dict):
                    raise ModelPricingError(f"Invalid temporary supplier {field}")
                for group in groups.values():
                    if not isinstance(group, dict):
                        raise ModelPricingError(f"Invalid temporary supplier {field}")
                    for category, multiplier in group.items():
                        if category not in {"input", "output", "cache_read", "cache_write", "cache_write_1h"}:
                            raise ModelPricingError("Invalid temporary supplier token category")
                        _number(multiplier, positive=True)


def validate_temporary_prices(model: Mapping[str, Any]) -> None:
    """Reject malformed or overlapping offers, including future inactive rows."""
    offers = model.get("temporary_prices", [])
    if not isinstance(offers, list):
        raise ModelPricingError("Temporary prices must be a list")
    identifiers: set[str] = set()
    windows: list[tuple[date, date, set[str], set[str] | None, str]] = []
    configured_hosts = {server["id"] for server in model.get("servers", []) if isinstance(server, dict) and server.get("id")}
    for offer in offers:
        if not isinstance(offer, dict) or set(offer) - set(PROMOTION_FIELDS) - set(TARIFF_FIELDS):
            raise ModelPricingError("Invalid temporary price fields")
        identifier = offer.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers:
            raise ModelPricingError("Temporary prices require unique identifiers")
        identifiers.add(identifier)
        start = _date(offer.get("effective_from"), "effective_from")
        end = _date(offer["expires_on"], "expires_on") if offer.get("expires_on") is not None else date.max
        _date(offer.get("reviewed_on"), "reviewed_on")
        if end < start:
            raise ModelPricingError("Temporary price expires before its start")
        if offer.get("guaranteed_through") is not None and not start <= _date(offer["guaranteed_through"], "guaranteed_through") <= end:
            raise ModelPricingError("Invalid temporary price minimum duration")
        source = urlparse(str(offer.get("source_url", "")))
        if source.scheme != "https" or not source.netloc:
            raise ModelPricingError("Temporary prices require an authoritative HTTPS source")
        hosts = _strings(offer.get("eligible_hosts"), "eligible_hosts")
        if configured_hosts and not hosts <= configured_hosts:
            raise ModelPricingError("Temporary price uses an unconfigured inference host")
        regions = _strings(offer["regions"], "regions") if "regions" in offer else None
        tier = offer.get("processing_tier")
        if not isinstance(tier, str) or not tier.strip():
            raise ModelPricingError("Temporary price requires a processing tier")
        _validate_rates(model, offer)
        for other_start, other_end, other_hosts, other_regions, other_tier in windows:
            if (tier == other_tier and hosts & other_hosts and max(start, other_start) <= min(end, other_end)
                    and (regions is None or other_regions is None or regions & other_regions)):
                raise ModelPricingError("Overlapping temporary prices for the same route")
        windows.append((start, end, hosts, regions, tier))


def resolve_model_tariff(
    model: Mapping[str, Any], *, inference_host: str | None = None,
    region: str | None = None, processing_tier: str = "standard", on_date: date | None = None,
) -> dict[str, Any]:
    """Resolve one tariff at dispatch/read time; regular rates remain untouched."""
    if "temporary_prices" in model:
        validate_temporary_prices(model)
    if not model.get("temporary_prices"):
        return model if isinstance(model, dict) else dict(model)
    today = on_date or utc_today()
    host = inference_host or model.get("default_server")
    if region is None:
        regions = {server.get("region") for server in model.get("servers", []) if server.get("id") == host}
        region = next(iter(regions)) if len(regions) == 1 else None
    resolved = copy.deepcopy(dict(model))
    resolved.pop("active_temporary_price", None)
    resolved.pop("pricing_version", None)
    for offer in model["temporary_prices"]:
        start = _date(offer["effective_from"], "effective_from")
        end = _date(offer["expires_on"], "expires_on") if offer.get("expires_on") else date.max
        if (start <= today <= end and host in offer["eligible_hosts"]
                and processing_tier == offer["processing_tier"]
                and ("regions" not in offer or region in offer["regions"])):
            if _date(offer["reviewed_on"], "reviewed_on") > today:
                raise ModelPricingError("Temporary price review is in the future")
            for field in TARIFF_FIELDS:
                if field in offer:
                    resolved[field] = copy.deepcopy(offer[field])
            resolved["active_temporary_price"] = {field: copy.deepcopy(offer[field]) for field in PROMOTION_FIELDS if field in offer}
            break
    # A verification deadline is independent of a promotion's expiry. Continue
    # valid ordinary billing after cache verification lapses; never extend it.
    cache = resolved.get("cache_pricing") or {}
    if cache.get("enabled") and cache.get("expires_on") and today > _date(cache["expires_on"], "cache expires_on"):
        cache["enabled"] = False
        cache["status"] = "expired_pending_review"
    return resolved
