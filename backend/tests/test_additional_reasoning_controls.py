"""Documented reasoning controls across the selectable Google/OpenAI catalog.

Native wire values are asserted independently of catalog declarations. These
checks run without any provider requests or model-selection overrides.
"""
# contract-test-file: infrastructure
from pathlib import Path

import pytest
import yaml

from backend.apps.ai.utils.model_reasoning import resolve_reasoning_parameters


CATALOGS = {
    provider: yaml.safe_load((Path(__file__).parents[1] / f"providers/{provider}.yml").read_text())
    for provider in ("google", "openai")
}


def model(provider, model_id):
    return next(item for item in CATALOGS[provider]["models"] if item["id"] == model_id)


@pytest.mark.parametrize("model_id", [
    "gemini-3-flash-preview", "gemini-3.7-flash", "gemini-3.8-flash",
    "gemini-3.1-pro-preview", "gemini-3.5-flash", "gemini-3.5-flash-lite",
])
@pytest.mark.parametrize("server", ["google_ai_studio", "google"])
def test_every_selectable_gemini_host_resolves_supported_levels(model_id, server):
    config = model("google", model_id)
    for requested, native in (("LOW", "LOW"), ("MEDIUM", "MEDIUM"),
                              ("HIGH", "HIGH"), ("EXTRA_HIGH", "HIGH")):
        assert resolve_reasoning_parameters(config, server, requested) == {"thinking_level": native}
    assert resolve_reasoning_parameters(config, server, None) == {}
    assert resolve_reasoning_parameters(config, "unregistered-host", "HIGH") == {}


@pytest.mark.parametrize("model_id", [
    "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna",
    "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4",
    "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.2",
])
def test_openai_adjustable_models_support_four_recommendation_levels(model_id):
    config = model("openai", model_id)
    for requested, native in (("LOW", "low"), ("MEDIUM", "medium"),
                              ("HIGH", "high"), ("EXTRA_HIGH", "xhigh")):
        assert resolve_reasoning_parameters(config, "openai", requested) == {"reasoning_effort": native}
    assert resolve_reasoning_parameters(config, "openai", None) == {}
    assert resolve_reasoning_parameters(config, "openrouter", "HIGH") == {}


@pytest.mark.parametrize("model_id,default", [
    ("gpt-5.5-pro", "high"), ("gpt-5.4-pro", "medium"), ("gpt-5.2-pro", "high"),
])
def test_true_openai_pro_models_adjust_effort_but_respect_documented_medium_floor(model_id, default):
    config = model("openai", model_id)
    for requested, native in (("LOW", "medium"), ("MEDIUM", "medium"),
                              ("HIGH", "high"), ("EXTRA_HIGH", "xhigh")):
        assert resolve_reasoning_parameters(config, "openai", requested) == {"reasoning_effort": native}
    assert resolve_reasoning_parameters(config, "openai", None) == {}
    assert config["reasoning_effort"] == default


def test_openai_51_clamps_extra_high_to_its_documented_high_ceiling():
    config = model("openai", "gpt-5.1")
    assert resolve_reasoning_parameters(config, "openai", "LOW") == {"reasoning_effort": "low"}
    assert resolve_reasoning_parameters(config, "openai", "EXTRA_HIGH") == {"reasoning_effort": "high"}
    assert resolve_reasoning_parameters(config, "openai", None) == {}
    assert config["reasoning_effort"] == "none"


@pytest.mark.parametrize("model_id", ["gemini-3.7-flash", "gemini-3.5-flash"])
def test_legacy_google_aliases_keep_selected_identity_and_host_order(model_id):
    config = model("google", model_id)
    assert config["default_server"] == "google_ai_studio"
    assert [server["id"] for server in config["servers"]] == ["google_ai_studio", "google"]
    assert all(server["model_id"] == model_id for server in config["servers"])


def test_undeclared_gemma_control_preserves_native_behavior():
    config = model("google", "gemma-4-31b")
    for requested in ("LOW", "MEDIUM", "HIGH", "EXTRA_HIGH"):
        assert resolve_reasoning_parameters(config, "cerebras", requested) == {}
