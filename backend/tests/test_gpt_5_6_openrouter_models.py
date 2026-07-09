#!/usr/bin/env python3
# backend/tests/test_gpt_5_6_openrouter_models.py
#
# Catalog contract for GPT-5.6 models that are currently available only through
# the configured OpenRouter account. This test avoids paid provider calls while
# protecting model IDs, routing, and billing metadata.

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]

MODEL_COSTS = {
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-luna": (1.00, 6.00),
}


@pytest.mark.parametrize(("model_id", "input_cost", "output_cost"), [
    (model_id, *costs) for model_id, costs in MODEL_COSTS.items()
])
def test_gpt_5_6_models_route_through_openrouter(model_id, input_cost, output_cost):
    provider_config = yaml.safe_load((REPO_ROOT / "backend/providers/openai.yml").read_text())
    model = next(model for model in provider_config["models"] if model["id"] == model_id)

    assert model["default_server"] == "openrouter"
    assert model["external_ids"]["openrouter"] == f"openai/{model_id}"
    assert model["servers"] == [{
        "id": "openrouter",
        "name": "OpenRouter API",
        "model_id": f"openai/{model_id}",
        "region": "US",
    }]
    assert model["costs"]["input_per_million_token"]["price"] == input_cost
    assert model["costs"]["output_per_million_token"]["price"] == output_cost
    assert model["costs"]["input_per_million_token"]["max_context"] == 1050000
    assert model["features"]["max_output_tokens"] == 128000
