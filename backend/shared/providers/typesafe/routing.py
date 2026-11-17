"""Which decision model answers a typed decision, per purpose.

The order lives in the existing model-routing config,
``backend/apps/ai/app.yml`` → ``skills[ask].skill_config.decision_routing``:

    decision_routing:
      default: [typesafe/jev-1.14]
      purposes:
        preprocess_decision: [google/gemini-decision-1, typesafe/jev-1.14]

The first model of a purpose is its default; Jev after it is the automatic
fallback on errors, timeouts or provider blocks. A purpose that is not listed
uses ``default``. Choices come from the Gemini-vs-Jev benchmark
(backend/scripts/benchmark_gemini_decision_jev.py, TASK-1809).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

GEMINI_DECISION_MODEL = "google/gemini-decision-1"
JEV_DECISION_MODEL = "typesafe/jev-1.14"
KNOWN_MODELS = frozenset({GEMINI_DECISION_MODEL, JEV_DECISION_MODEL})
_APP_YML = Path(__file__).resolve().parents[3] / "apps" / "ai" / "app.yml"


def _validated(route: object, where: str) -> tuple[str, ...]:
    if (not isinstance(route, list) or not route or len(set(route)) != len(route)
            or any(model not in KNOWN_MODELS for model in route)):
        raise ValueError(f"decision_routing.{where} must be a non-empty list of {sorted(KNOWN_MODELS)}")
    if route[-1] != JEV_DECISION_MODEL:
        # Jev is the reviewed decider and the only fallback for image and size limits.
        raise ValueError(f"decision_routing.{where} must end with {JEV_DECISION_MODEL}")
    return tuple(route)


@lru_cache(maxsize=1)
def decision_routes(path: Path = _APP_YML) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """(default route, routes by purpose) from app.yml; a missing block means Jev only."""
    app = yaml.safe_load(path.read_text(encoding="utf-8"))
    ask = next(skill for skill in app["skills"] if skill["id"] == "ask")
    config = (ask.get("skill_config") or {}).get("decision_routing")
    if config is None:
        return (JEV_DECISION_MODEL,), {}
    default = _validated(config.get("default", [JEV_DECISION_MODEL]), "default")
    purposes = {str(purpose): _validated(route, f"purposes.{purpose}")
                for purpose, route in (config.get("purposes") or {}).items()}
    return default, purposes


def decision_route(purpose: Optional[str]) -> tuple[str, ...]:
    default, purposes = decision_routes()
    return purposes.get(purpose or "", default)


def gemini_first(purpose: Optional[str]) -> bool:
    return decision_route(purpose)[0] == GEMINI_DECISION_MODEL
