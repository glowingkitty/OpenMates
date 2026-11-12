#!/usr/bin/env python3
"""Derive every stored customer price from supplier costs and the pricing settings.

Reads ``pricing`` from backend/config/backend_config.yml (margin, 5-credit
rounding step, zero-cost minimum), derives the customer ``pricing`` of every
provider model, temporary tariff, provider request price and app skill, and
prints a before/after table. ``--write`` stores the derived values in the YAML
files, changing only the affected numbers. ``--check`` exits 1 when a
stored price differs from its derivation.

Usage:
  python3 scripts/derive_customer_prices.py [--check] [--write] [--table <file.md>]
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.python_utils.cost_plus_pricing import (  # noqa: E402 - repository root is added above.
    CostPlusPricingError, PricingSettings, derive_declared_pricing, derive_model_pricing, load_pricing_settings,
)
from scripts.yaml_exact_edit import replace_scalars  # noqa: E402 - repository root is added above.

PROVIDERS = ROOT / "backend" / "providers"
APPS = ROOT / "backend" / "apps"


def _per_million(rate: Any) -> str:
    return "free" if not rate else f"{Decimal(1_000_000) / Decimal(str(rate)):.0f}"


def _credit_cells(pricing: dict[str, Any]) -> dict[str, str]:
    """Human-readable customer price per category (tokens shown per 1M tokens)."""
    cells: dict[str, str] = {}
    for key, value in pricing.items():
        if key == "tokens":
            for category, row in value.items():
                cells[f"{category} / 1M tokens"] = _per_million(row["per_credit_unit"])
        elif key == "context_bands":
            for band, row in value.items():
                for category, rate in row["tokens"].items():
                    cells[f"{band} {category} / 1M tokens"] = _per_million(rate["per_credit_unit"])
        elif key == "per_unit":
            cells[f"per {value.get('unit_name', 'unit')}"] = str(value["credits"])
        elif key == "per_request_credits":
            cells["per request"] = str(value)
        elif key.startswith("per_million_"):
            cells[f"per 1M {key.removeprefix('per_million_')}"] = str(value)
        elif key in ("fixed", "per_second", "per_minute"):
            cells[{"fixed": "per call", "per_second": "per second", "per_minute": "per minute"}[key]] = str(value)
    return cells


def _derive(errors: list[str], function: Any, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
    try:
        return function(*args, **kwargs)
    except CostPlusPricingError as exc:
        errors.append(str(exc))
        return None


def iter_items(settings: PricingSettings, errors: list[str]) -> Iterator[dict[str, Any]]:
    """Yield every priced item with its stored and derived pricing; collect gaps in ``errors``."""
    model_pricing: dict[str, dict[str, Any]] = {}
    for path in sorted(PROVIDERS.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        provider = data.get("provider_id", path.stem)
        if data.get("pricing"):
            derived = _derive(errors, derive_declared_pricing, data["pricing"], data.get("supplier_costs") or {},
                              settings=settings, model_pricing={}, item=f"providers/{path.name}")
            yield {"file": path, "item": f"{provider} (requests)", "path": ("pricing",),
                   "before": data["pricing"], "after": derived}
        for index, model in enumerate(data.get("models") or []):
            if not isinstance(model, dict) or not model.get("pricing"):
                continue
            derived = _derive(errors, derive_model_pricing, model, settings=settings)
            if derived is not None:
                model_pricing[f"{provider}/{model['id']}"] = derived
            yield {"file": path, "item": f"{provider}/{model['id']}", "path": ("models", index, "pricing"),
                   "before": model["pricing"], "after": derived}
            for offer_index, offer in enumerate(model.get("temporary_prices") or []):
                if offer.get("pricing"):
                    yield {"file": path, "item": f"{provider}/{model['id']} [{offer['id']} until {offer.get('expires_on', 'no end')}]",
                           "path": ("models", index, "temporary_prices", offer_index, "pricing"),
                           "before": offer["pricing"],
                           "after": _derive(errors, derive_model_pricing, model, offer, settings=settings,
                                            hosts=offer.get("eligible_hosts"))}
    for path in sorted(APPS.glob("*/app.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for index, skill in enumerate(data.get("skills") or []):
            if not isinstance(skill, dict) or not skill.get("pricing"):
                continue
            item = f"{path.parent.name}.{skill['id']}"
            yield {"file": path, "item": item, "path": ("skills", index, "pricing"), "before": skill["pricing"],
                   "after": _derive(errors, derive_declared_pricing, skill["pricing"], skill.get("supplier_costs") or {},
                                    settings=settings, model_pricing=model_pricing, item=item)}


def table(rows: list[dict[str, Any]], settings: PricingSettings) -> str:
    lines = [
        f"Customer prices in credits (1 credit = $0.001), margin {settings.margin_percent}% on supplier cost, "
        f"rounded up to {settings.rounding_step_credits}-credit steps.",
        "",
        "| Item | Unit | Before | After | Change |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        before, after = _credit_cells(row["before"]), _credit_cells(row["after"])
        for unit in after:
            old, new = before.get(unit, "-"), after[unit]
            try:
                change = f"{(Decimal(new) - Decimal(old)) / Decimal(old) * 100:+.0f}%"
            except (ArithmeticError, ValueError):
                change = "-"
            lines.append(f"| {row['item']} | {unit} | {old} | {new} | {change} |")
    return "\n".join(lines) + "\n"


def _leaf_updates(path: tuple[Any, ...], before: Any, after: Any) -> list[tuple[tuple[Any, ...], Any]]:
    if isinstance(after, dict):
        return [update for key, value in after.items() for update in _leaf_updates(path + (key,), before[key], value)]
    return [] if before == after else [(path, after)]


def write(rows: list[dict[str, Any]]) -> None:
    """Store derived numbers by replacing only the changed scalars in each file."""
    by_file: dict[Path, list[tuple[tuple[Any, ...], Any]]] = {}
    for row in rows:
        by_file.setdefault(row["file"], []).extend(_leaf_updates(row["path"], row["before"], row["after"]))
    for path, updates in by_file.items():
        if updates:
            path.write_text(replace_scalars(path.read_text(encoding="utf-8"), updates), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Exit 1 when a stored price differs from its derivation.")
    parser.add_argument("--write", action="store_true", help="Store the derived prices in the YAML files.")
    parser.add_argument("--table", type=Path, help="Write the before/after table to this Markdown file.")
    args = parser.parse_args()
    settings = load_pricing_settings()
    errors: list[str] = []
    rows = [row for row in iter_items(settings, errors) if row["after"] is not None]
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 2
    report = table(rows, settings)
    if args.table:
        args.table.write_text(report, encoding="utf-8")
    else:
        print(report)
    drift = [row["item"] for row in rows if row["before"] != row["after"]]
    if args.write:
        write(rows)
        print(f"Updated {len(drift)} priced item(s).", file=sys.stderr)
        return 0
    if args.check and drift:
        print(f"{len(drift)} stored price(s) differ from their derivation: {', '.join(drift[:10])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
