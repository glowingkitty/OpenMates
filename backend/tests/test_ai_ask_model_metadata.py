# contract-test-file: infrastructure
# backend/tests/test_ai_ask_model_metadata.py
#
# Pins display metadata required by every user-selectable ai.ask model.
# Capability is explicit product metadata, not an inference from price or
# reasoning support, and release dates drive deterministic picker ordering.

from datetime import date
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDERS_DIR = REPO_ROOT / "backend" / "providers"
CAPABILITY_LEVELS = {"low", "medium", "high", "max"}
EXPECTED_CAPABILITIES = {
    "gpt-6-astra": "max",
    "gpt-5.6-luna": "low",
    "gpt-5.6-terra": "medium",
    "gpt-5.6-sol": "high",
    "gpt-5.6-sol-max": "max",
    "gpt-oss-120b": "low",
    "gpt-oss-20b": "low",
    "claude-haiku-4-5-20251001": "low",
    "claude-sonnet-5": "medium",
    "claude-opus-5": "high",
    "claude-fable-5-1": "max",
    "claude-fable-5": "max",
}


def _ai_ask_models() -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for path in sorted(PROVIDERS_DIR.glob("*.yml")):
        provider = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        models.extend(
            model
            for model in provider.get("models", [])
            if isinstance(model, dict) and model.get("for_app_skill") == "ai.ask"
        )
    return models


# contract-test: supporting surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
def test_every_ai_ask_model_has_explicit_capability_and_release_date() -> None:
    models = _ai_ask_models()

    assert len(models) == 39
    for model in models:
        assert model.get("capability_level") in CAPABILITY_LEVELS, model["id"]
        assert date.fromisoformat(model["release_date"]), model["id"]


# contract-test: supporting surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
def test_named_model_capabilities_match_the_approved_scale() -> None:
    models_by_id = {model["id"]: model for model in _ai_ask_models()}

    for model_id, capability in EXPECTED_CAPABILITIES.items():
        assert models_by_id[model_id]["capability_level"] == capability

    assert models_by_id["qwen-3.8-27b"]["capability_level"] == "low"
    assert models_by_id["qwen-3.8-27b"]["allow_auto_select"] is False


# contract-test: supporting surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
def test_gpt6_astra_uses_max_reasoning_on_openai() -> None:
    models_by_id = {model["id"]: model for model in _ai_ask_models()}
    astra = models_by_id["gpt-6-astra"]

    assert astra["capability_level"] == "max"
    assert astra["reasoning_effort"] == "max"
    assert astra["default_server"] == "openai"
    assert astra["servers"] == [
        {
            "id": "openai",
            "name": "OpenAI API",
            "model_id": "gpt-6-astra",
            "region": "US",
        }
    ]
