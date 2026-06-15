#!/usr/bin/env python3
# backend/tests/test_deepseek_v4_models_script.py
#
# Deterministic coverage for the DeepSeek V4 live verification helper.
# The live script makes provider calls, so regular unit tests only assert the
# local provider catalog contract that routes V4 Pro through Together first and
# keeps OpenRouter as fallback.

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_deepseek_v4_pro_config_uses_together_primary_with_openrouter_fallback():
    provider_config = yaml.safe_load((REPO_ROOT / "backend/providers/deepseek.yml").read_text())
    model = next(model for model in provider_config["models"] if model["id"] == "deepseek-v4-pro")

    assert model["default_server"] == "together"
    assert model["external_ids"]["together"] == "deepseek-ai/DeepSeek-V4-Pro"
    assert model["external_ids"]["openrouter"] == "deepseek/deepseek-v4-pro"
    assert [server["id"] for server in model["servers"]] == ["together", "openrouter"]
    assert model["servers"][0]["model_id"] == "deepseek-ai/DeepSeek-V4-Pro"
    assert model["servers"][1]["model_id"] == "deepseek/deepseek-v4-pro"
