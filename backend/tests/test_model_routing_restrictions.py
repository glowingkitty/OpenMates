# contract-test-file: infrastructure
"""Authenticated per-turn model metadata cannot become account preferences or overrides."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.schemas.ai_skill_schemas import ModelRoutingRestrictions


@pytest.mark.parametrize("payload", [
    {"disabled_ai_models": ["private value"]},
    {"disabled_ai_models": ["mercury-3"] * 257},
    {"disabled_ai_servers": {"mercury-3": ["inception"] * 17}},
    {"disabled_ai_models": [123]},
    {"default_ai_model_simple": "inception/mercury-3"},
    {"learning_mode": {"enabled": False}},
])
def test_transient_routing_schema_rejects_invalid_and_unrelated_preferences(payload):
    with pytest.raises(ValueError):
        ModelRoutingRestrictions.model_validate(payload)


@pytest.mark.parametrize("disabled_models,expected", [
    (["mercury-3"], "google/gemini-3.8-flash"),
    (["mercury-3", "gemini-3.8-flash"], None),
])
def test_web_restrictions_reach_actual_automatic_model_selection(monkeypatch, disabled_models, expected):
    from backend.apps.ai.processing import preprocessor
    restrictions = ModelRoutingRestrictions.model_validate({
        "disabled_ai_models": disabled_models,
        "disabled_ai_servers": {"gemini-3.8-flash": ["google_ai_studio"]},
    }).model_dump()
    catalog = {
        "inception": {"models": [{"id": "mercury-3", "servers": [{"id": "inception"}]}]},
        "google": {"models": [{"id": "gemini-3.8-flash", "servers": [{"id": "google_ai_studio"}, {"id": "google"}]}]},
    }
    monkeypatch.setattr(preprocessor, "config_manager", SimpleNamespace(
        get_provider_config=lambda provider: catalog.get(provider), get_model_display_name=lambda model, _: model))
    monkeypatch.setattr(preprocessor, "_usable_chat_model_reference", lambda model, _: (model, model))
    health = AsyncMock(return_value=True)
    monkeypatch.setattr(preprocessor, "is_provider_healthy", health)
    request = SimpleNamespace(message_history=[{"role": "user", "content": "Hello"}],
                              user_preferences=restrictions, has_image_upload_embed=False)
    result = asyncio.run(preprocessor._select_main_model(
        {"complexity": "low", "china_model_sensitive": False}, request,
        SimpleNamespace(enable_auto_model_selection=False), None, "test"))
    assert result["selected_llm_for_main_id"] == expected
    assert result["selected_llm_thinking_level"] == ("LOW" if expected else None)
    health.assert_not_awaited()  # Disabled Mercury never reaches provider availability/inference.
