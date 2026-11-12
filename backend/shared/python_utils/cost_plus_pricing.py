"""Derive customer credit prices from supplier costs with one configurable margin.

Every priced provider model, provider request and app skill states what the
supplier charges us (USD per billed unit). The customer price is

    credits = supplier_usd * (1 + margin) / USD_PER_CREDIT

rounded up to the next ``rounding_step_credits`` (5). Prices below one step are
not stepped: per-call units and minutes (billed per started minute) are rounded
up to a whole credit, continuous units (tokens, seconds, characters) to 0.01 credit.
Token categories are stored as tokens per credit, the number customers see.
That number is rounded up to the next ``rounding_step_credits`` tokens (444.4 →
445), or to 0.01 token when it is below one step, so displayed token rates are
round numbers. Items with no external supplier cost charge
``zero_cost_minimum_credits`` per billed unit.

Settings live in ``backend/config/backend_config.yml`` under ``pricing``.
``OPENMATES_PRICING_MARGIN_PERCENT`` overrides the margin for the derivation
tool. Stored catalog prices are regenerated with
``scripts/derive_customer_prices.py`` and checked for drift by tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Mapping

import yaml

USD_PER_CREDIT = Decimal("0.001")
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)
BACKEND_CONFIG = Path(__file__).resolve().parents[2] / "config" / "backend_config.yml"
MARGIN_ENV = "OPENMATES_PRICING_MARGIN_PERCENT"

# Customer token category -> supplier cost keys, first match wins.
TOKEN_COST_KEYS: dict[str, tuple[str, ...]] = {
    "input": ("input_per_million_token", "text_input_per_million_token"),
    "output": ("output_per_million_token", "text_output_per_million_token"),
    "cache_read": (
        "cache_read_per_million_token", "cached_input_per_million_token",
        "cached_text_input_per_million_token",
    ),
    "cache_write": ("cache_write_per_million_token",),
    "cache_write_1h": ("cache_write_1h_per_million_token",),
}
PER_CALL_UNITS = frozenset({"fixed", "per_unit", "per_request_credits", "per_minute"})


class CostPlusPricingError(ValueError):
    """A priced item lacks a usable supplier cost or the settings are invalid."""


@dataclass(frozen=True)
class PricingSettings:
    """Margin and rounding policy shared by every derived customer price."""

    margin_percent: Decimal = Decimal(50)
    rounding_step_credits: Decimal = Decimal(5)
    zero_cost_minimum_credits: Decimal = Decimal(1)

    @property
    def multiplier(self) -> Decimal:
        return 1 + self.margin_percent / 100


def load_pricing_settings(config_path: Path = BACKEND_CONFIG, *, environ: Mapping[str, str] | None = None) -> PricingSettings:
    """Read ``pricing`` from backend_config.yml; the environment may override the margin."""
    environ = os.environ if environ is None else environ
    section = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}).get("pricing") or {}
    values = {
        "margin_percent": environ.get(MARGIN_ENV, section.get("margin_percent", 50)),
        "rounding_step_credits": section.get("rounding_step_credits", 5),
        "zero_cost_minimum_credits": section.get("zero_cost_minimum_credits", 1),
    }
    parsed = {}
    for name, value in values.items():
        try:
            number = Decimal(str(value))
        except ArithmeticError as exc:
            raise CostPlusPricingError(f"pricing.{name} must be a number") from exc
        if not number.is_finite() or number < 0 or (name != "margin_percent" and number == 0):
            raise CostPlusPricingError(f"pricing.{name} is out of range")
        parsed[name] = number
    return PricingSettings(**parsed)


def _ceil(value: Decimal, quantum: Decimal) -> Decimal:
    return (value / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum



def round_credits(raw: Decimal, settings: PricingSettings, *, per_call: bool) -> Decimal:
    """Round a raw credit amount up to the policy step, or keep small prices."""
    step = settings.rounding_step_credits
    if raw >= step:
        return _ceil(raw, step)
    return _ceil(raw, Decimal(1) if per_call else Decimal("0.01"))


def credits_for_cost(usd: Any, settings: PricingSettings, *, per_call: bool) -> Decimal:
    """Customer credits for one billed unit whose supplier cost is ``usd``."""
    cost = Decimal(str(usd))
    if not cost.is_finite() or cost < 0:
        raise CostPlusPricingError(f"Invalid supplier cost {usd!r}")
    if cost == 0:
        return settings.zero_cost_minimum_credits
    return round_credits(cost * settings.multiplier / USD_PER_CREDIT, settings, per_call=per_call)


def tokens_per_credit(usd_per_million: Any, settings: PricingSettings) -> int | float:
    """Stored token rate (tokens per credit) for a supplier cost per 1M tokens.

    The rate is ``1M tokens / (cost * (1 + margin) / USD_PER_CREDIT)`` rounded up
    to the next step of ``rounding_step_credits`` tokens, or up to 0.01 token
    below one step. A token category the supplier does not charge for stays
    free (rate 0): the flat minimum applies to billed items, not to free token
    categories of a priced model.
    """
    cost = Decimal(str(usd_per_million))
    if not cost.is_finite() or cost < 0:
        raise CostPlusPricingError(f"Invalid supplier cost {usd_per_million!r}")
    if cost == 0:
        return 0
    raw = TOKENS_PER_PRICE_UNIT * USD_PER_CREDIT / (cost * settings.multiplier)
    step = settings.rounding_step_credits
    return as_number(_ceil(raw, step) if raw >= step else _ceil(raw, Decimal("0.01")))

def as_number(value: Decimal) -> int | float:
    """YAML-friendly number: integers stay integers."""
    return int(value) if value == value.to_integral_value() else float(value.normalize())


# --- Provider model costs -------------------------------------------------------------


def _cost_price(costs: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[str, Decimal] | None:
    for key in keys:
        row = costs.get(key)
        if isinstance(row, Mapping) and row.get("price") is not None:
            if row.get("currency", "USD") != "USD":
                raise CostPlusPricingError(f"Supplier cost {key} must be in USD")
            return key, Decimal(str(row["price"]))
    return None


def _host_costs(model: Mapping[str, Any], tariff: Mapping[str, Any], hosts: list[str] | None) -> list[tuple[str, Mapping[str, Any], Decimal, Mapping[str, Any]]]:
    """(host, route costs, route multiplier, profile) for every eligible route."""
    profiles = tariff.get("supplier_cost_profiles") or model.get("supplier_cost_profiles") or {}
    servers = [server["id"] for server in model.get("servers", []) if isinstance(server, Mapping) and server.get("id")]
    route_ids = hosts or servers or [None]
    routes = []
    for host in route_ids:
        profile = profiles.get(host, {}) if host else {}
        costs = dict(tariff.get("costs") or {})
        costs.update(profile.get("costs") or {})
        routes.append((host, costs, Decimal(str(profile.get("multiplier", 1))), profile))
    return routes


def route_token_cost(model: Mapping[str, Any], tariff: Mapping[str, Any], category: str, *,
                     hosts: list[str] | None = None, band: str | None = None) -> Decimal:
    """Highest supplier cost per 1M tokens for a category across eligible routes."""
    best: Decimal | None = None
    for host, costs, multiplier, profile in _host_costs(model, tariff, hosts):
        found = _cost_price(costs, TOKEN_COST_KEYS[category])
        if found is None:
            continue
        price = found[1] * multiplier
        if band is not None:
            price *= Decimal(str(((profile.get("context_bands") or {}).get(band) or {}).get(category, 1)))
        best = price if best is None else max(best, price)
    if best is None:
        raise CostPlusPricingError(f"{model.get('id')}: no supplier cost for token category {category}")
    return best


def _unit_cost(costs: Mapping[str, Any], unit: str, model_id: Any) -> Decimal:
    """Supplier cost of one billed non-token unit (image, song, second, minute)."""
    explicit = _cost_price(costs, (f"per_{unit}",))
    if explicit is not None:
        return explicit[1]
    parts = [Decimal(str(row["price"])) for key, row in costs.items()
             if isinstance(row, Mapping) and key.endswith(f"_per_{unit}") and row.get("price") is not None]
    if not parts:
        raise CostPlusPricingError(f"{model_id}: no supplier cost per {unit}")
    # Inputs and outputs priced per unit are both incurred for one billed unit.
    return sum(parts, Decimal(0))


def derive_model_pricing(model: Mapping[str, Any], tariff: Mapping[str, Any] | None = None, *,
                         settings: PricingSettings, hosts: list[str] | None = None) -> dict[str, Any]:
    """Customer ``pricing`` for a provider model (or one of its temporary tariffs)."""
    tariff = tariff or model
    current = tariff.get("pricing") or {}
    costs = tariff.get("costs") or {}
    derived: dict[str, Any] = {}
    for key, value in current.items():
        if key == "tokens":
            derived["tokens"] = {
                category: {"per_credit_unit": tokens_per_credit(route_token_cost(model, tariff, category, hosts=hosts), settings)}
                for category in value
            }
        elif key == "context_bands":
            derived["context_bands"] = {}
            for band_name, band in value.items():
                band_hosts = band.get("eligible_hosts") or hosts
                derived_band = {k: v for k, v in band.items() if k != "tokens"}
                derived_band["tokens"] = {
                    category: {"per_credit_unit": tokens_per_credit(
                        route_token_cost(model, tariff, category, hosts=band_hosts, band=band_name), settings)}
                    for category in band["tokens"]
                }
                derived["context_bands"][band_name] = derived_band
        elif key == "per_unit":
            unit = value.get("unit_name", "unit")
            derived["per_unit"] = {**value, "credits": as_number(credits_for_cost(_unit_cost(costs, unit, model.get("id")), settings, per_call=True))}
        elif key in ("per_second", "per_minute"):
            unit = key.removeprefix("per_")
            derived[key] = as_number(credits_for_cost(_unit_cost(costs, unit, model.get("id")), settings,
                                                      per_call=key in PER_CALL_UNITS))
        elif key.startswith("per_million_"):
            cost = _cost_price(costs, (key,))
            if cost is None:
                raise CostPlusPricingError(f"{model.get('id')}: no supplier cost {key}")
            derived[key] = as_number(credits_for_cost(cost[1], settings, per_call=False))
        else:
            derived[key] = value
    return derived


# --- Skill and provider request costs -------------------------------------------------


def derive_declared_pricing(pricing: Mapping[str, Any], supplier_costs: Mapping[str, Any], *,
                            settings: PricingSettings, model_pricing: Mapping[str, Mapping[str, Any]],
                            item: str) -> dict[str, Any]:
    """Customer pricing for a skill or provider from its ``supplier_costs`` block.

    Each pricing key needs a matching supplier cost: ``{price, currency}``,
    ``{none: true}`` for work without an external supplier cost,
    ``{model: provider/model}`` to reuse that model's derived price for the
    same unit, or ``{policy_credits: n, note}`` for a revenue-share price that
    is not cost-based (for example a creator payout funded by the charge).
    """
    derived: dict[str, Any] = {}
    for key, value in pricing.items():
        if key == "cache_pricing":
            derived[key] = value
            continue
        cost = supplier_costs.get(key)
        if not isinstance(cost, Mapping):
            raise CostPlusPricingError(f"{item}: pricing.{key} has no supplier_costs.{key}")
        if cost.get("model"):
            reference = model_pricing.get(cost["model"])
            if reference is None or key not in reference:
                raise CostPlusPricingError(f"{item}: supplier_costs.{key} references {cost['model']} without {key} pricing")
            derived[key] = reference[key]
            if key == "per_unit":
                # The skill keeps its own unit name; only the credits come from the model.
                derived[key] = {**value, "credits": reference[key]["credits"]}
            if key == "tokens":
                # A skill bills only the token categories it declares.
                missing = set(value) - set(reference[key])
                if missing:
                    raise CostPlusPricingError(f"{item}: {cost['model']} has no {sorted(missing)} token pricing")
                derived[key] = {category: reference[key][category] for category in value}
            continue
        if cost.get("policy_credits") is not None:
            if not cost.get("note"):
                raise CostPlusPricingError(f"{item}: supplier_costs.{key}.policy_credits needs a note")
            credits = as_number(Decimal(str(cost["policy_credits"])))
            derived[key] = {**value, "credits": credits} if key == "per_unit" else credits
            continue
        if cost.get("none") is True:
            usd: Any = 0
        elif cost.get("price") is not None:
            if cost.get("currency", "USD") != "USD":
                raise CostPlusPricingError(f"{item}: supplier_costs.{key} must be in USD")
            usd = cost["price"]
        else:
            raise CostPlusPricingError(f"{item}: supplier_costs.{key} needs price, none or model")
        credits = as_number(credits_for_cost(usd, settings, per_call=key in PER_CALL_UNITS))
        derived[key] = {**value, "credits": credits} if key == "per_unit" else credits
    return derived
