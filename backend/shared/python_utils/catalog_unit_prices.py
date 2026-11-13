"""Stored customer unit prices from the provider and app catalogs.

Skill code that bills per second, per started minute or per character reads its
rate here instead of keeping its own constant, so every charge uses the
cost-plus prices that ``scripts/derive_customer_prices.py`` stores in
``backend/providers/*.yml`` and ``backend/apps/*/app.yml``.
"""

from __future__ import annotations

import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parents[2]


class CatalogPriceError(LookupError):
    """A referenced catalog price does not exist."""


@lru_cache(maxsize=None)
def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _credits(value: Any) -> Decimal:
    # ``per_unit`` prices are stored as ``{credits, unit_name}``.
    return Decimal(str(value["credits"] if isinstance(value, dict) else value))


def model_price(model_ref: str, key: str) -> Decimal:
    """Stored ``pricing.<key>`` of ``provider/model`` (for example ``per_second``)."""
    provider, _, model_id = model_ref.partition("/")
    for model in _yaml(BACKEND / "providers" / f"{provider}.yml").get("models") or []:
        if isinstance(model, dict) and model.get("id") == model_id:
            value = (model.get("pricing") or {}).get(key)
            if value is None:
                break
            return _credits(value)
    raise CatalogPriceError(f"{model_ref} has no pricing.{key}")


def skill_price(app_id: str, skill_id: str, key: str) -> Decimal:
    """Stored ``pricing.<key>`` of an app skill (for example ``per_minute``)."""
    for skill in _yaml(BACKEND / "apps" / app_id / "app.yml").get("skills") or []:
        if isinstance(skill, dict) and skill.get("id") == skill_id:
            value = (skill.get("pricing") or {}).get(key)
            if value is None:
                break
            return _credits(value)
    raise CatalogPriceError(f"{app_id}.{skill_id} has no pricing.{key}")


def whole_credits(value: Decimal) -> int:
    """Whole credits for rates billed per started unit (never rounds down)."""
    return math.ceil(value)
