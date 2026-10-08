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
    "gpt-6.1-sol": "high",
    "gpt-6-luna": "low",
    "gpt-5.6-terra": "medium",
    "gpt-oss-120b": "low",
    "claude-haiku-5-5": "low",
    "claude-sonnet-5-5": "medium",
    "claude-opus-5-5": "high",
    "claude-fable-5-1": "max",
    "mistral-large-4": "high",
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

    assert len(models) == 28
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

    sol = models_by_id["gpt-6.1-sol"]
    assert sol["release_date"] == "2026-09-29"
    assert sol["reasoning_effort"] == "medium"
    assert sol["servers"][0]["model_id"] == "gpt-6.1-sol"
    assert sol["costs"]["cached_input_per_million_token"]["price"] == 0.10


# contract-test: supporting surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
def test_gpt6_astra_uses_max_reasoning_on_openai() -> None:
    models_by_id = {model["id"]: model for model in _ai_ask_models()}
    astra = models_by_id["gpt-6-astra"]

    assert astra["capability_level"] == "max"
    # The live OpenAI endpoint rejects max for Astra; xhigh is its highest
    # supported effort. Product capability remains independently rated max.
    assert astra["reasoning_effort"] == "xhigh"
    assert astra["default_server"] == "openai"
    assert astra["servers"] == [
        {
            "id": "openai",
            "name": "OpenAI API",
            "model_id": "gpt-6-astra",
            "region": "US",
        }
    ]


# contract-test: supporting surface=rest_api assertions=ai-model-routing.catalog.public-read-only
def test_claude_and_openai_chat_catalogs_contain_only_the_curated_lineup() -> None:
    expected = {
        "anthropic": {"claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"},
        "openai": {"gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "gpt-5.6-terra", "gpt-oss-120b"},
    }
    for provider, ids in expected.items():
        catalog = yaml.safe_load((PROVIDERS_DIR / f"{provider}.yml").read_text())
        chat_models = [m for m in catalog["models"] if m.get("for_app_skill") == "ai.ask"]
        assert {m["id"] for m in chat_models} == ids
        assert all(m.get("allow_auto_select") is True for m in chat_models)
        assert all(m.get("show_in_mentions", True) for m in chat_models)
        assert all(m["default_server"] in {r["id"] for r in m["servers"]} for m in chat_models)

    openai = yaml.safe_load((PROVIDERS_DIR / "openai.yml").read_text())
    assert {m["id"] for m in openai["models"] if m.get("for_app_skill") != "ai.ask"} == {
        "gpt-image-2", "gpt-oss-safeguard-20b", "gpt-oss-safeguard-20b-openrouter",
    }


def test_new_claude_models_expose_vision_tools_and_documented_limits() -> None:
    models = {m["id"]: m for m in _ai_ask_models()}
    for model_id, release_date in [("claude-sonnet-5-5", "2026-09-28"), ("claude-haiku-5-5", "2026-10-07")]:
        model = models[model_id]
        assert model["release_date"] == release_date
        assert model["input_types"] == ["text", "image"]
        assert model["reasoning"]
        assert model["features"]["tool_use"] and model["features"]["streaming"]
        assert model["features"]["max_output_tokens"] == 128000
        assert model["costs"]["input_per_million_token"]["max_context"] == 1000000
        assert model["servers"] == [{"id": "anthropic", "name": "Anthropic API", "model_id": model_id, "region": "US"}]
