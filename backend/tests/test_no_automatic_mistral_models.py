"""Mistral models are never chosen automatically for server-side processing.

Owner decision (21 Nov): Mistral Small and the other Mistral text models stay in the
catalog for users to select themselves, but no default, utility route, fallback or
automatic selection may pick them.
"""

from pathlib import Path

import yaml

from backend.apps.ai.utils.utility_model_fallbacks import (
    UTILITY_TRANSLATION_MODEL,
    utility_model_fallbacks,
)
from backend.core.api.app.services.workflow_identity_service import WORKFLOW_IDENTITY_MODEL_ID

BACKEND = Path(__file__).resolve().parents[1]
MISTRAL_TEXT_MODELS = {"mistral-large-4", "mistral-small-latest", "mistral-medium-latest"}


def _mistral_models() -> list[dict]:
    config = yaml.safe_load((BACKEND / "providers" / "mistral.yml").read_text())
    return config["models"]


# contract-test: tooling
def test_mistral_text_models_are_selectable_but_not_auto_selectable():
    models = {model["id"]: model for model in _mistral_models()}
    assert MISTRAL_TEXT_MODELS <= set(models)
    for model_id in MISTRAL_TEXT_MODELS:
        assert models[model_id]["allow_auto_select"] is False


# contract-test: tooling
def test_configured_default_llms_name_no_mistral_model():
    app = yaml.safe_load((BACKEND / "apps" / "ai" / "app.yml").read_text())
    skill_config = next(skill["skill_config"] for skill in app["skills"] if skill["id"] == "ask")
    for key, value in skill_config["default_llms"].items():
        assert "mistral" not in str(value).lower(), key
    assert "mistral" not in str(skill_config["decision_routing"]).lower()


# contract-test: tooling
def test_utility_routes_use_gemini_or_mercury():
    assert UTILITY_TRANSLATION_MODEL.startswith("google/")
    assert WORKFLOW_IDENTITY_MODEL_ID.startswith("google/")
    for model in ("google/gemini-3.5-flash-lite", "google/gemini-3.8-flash"):
        assert utility_model_fallbacks(model, [model])[0] == "inception/mercury-3"
