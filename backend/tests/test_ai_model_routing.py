# backend/tests/test_ai_model_routing.py
#
# Contract tests for the approved four-tier AI model-routing boundary.
# They define conservative request-tier normalization, fixed Google defaults,
# and chat-exact precedence while retaining non-model preprocessing.
# Product implementation belongs to backend/apps/ai/processing/preprocessor.py.

import importlib
from typing import Any

import pytest


def _routing_module() -> Any:
    """Load the dependency-free routing boundary planned for the preprocessor."""

    try:
        return importlib.import_module("backend.apps.ai.processing.model_routing")
    except ModuleNotFoundError as error:
        if error.name != "backend.apps.ai.processing.model_routing":
            raise
        pytest.fail(
            "the approved dependency-free four-tier routing boundary is unimplemented"
        )


# contract-test: direct surface=rest_api assertions=ai-model-routing.tiers.conservative-three-way
@pytest.mark.parametrize(
    ("classified_tier", "expected_tier"),
    [
        ("low", "low"), ("medium", "medium"), ("high", "high"), ("max", "max"),
        ("simple", "low"), ("complex", "medium"), ("most_demanding", "max"),
        ("uncertain", "medium"), ("invalid-tier", "medium"), (None, "medium"),
    ],
)
# contract-test: direct surface=rest_api assertions=ai-model-routing.tiers.conservative-three-way
def test_routing_normalizes_only_approved_tiers_conservatively(
    classified_tier: str | None,
    expected_tier: str,
) -> None:
    """Invalid classification uses medium; old callers keep compatible routing."""

    decision = _routing_module().resolve_model_routing(
        classified_tier=classified_tier,
        chat_model_preference="auto",
        tier_preferences={},
        automatic_model="anthropic/claude-sonnet-5",
    )

    assert decision.tier == expected_tier


# contract-test: direct surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_routing_uses_approved_google_profiles_for_all_four_auto_tiers() -> None:
    """Auto routing keeps Gemini variant IDs and thinking configuration together."""

    profiles = _routing_module().DEFAULT_TIER_MODEL_PROFILES

    assert profiles == {
        "low": {
            "model": "inception/mercury-3",
            "thinking_level": "MEDIUM",
        },
        "medium": {
            "model": "google/gemini-3.8-flash",
            "thinking_level": "MEDIUM",
        },
        "high": {
            "model": "google/gemini-3.8-flash",
            "thinking_level": "HIGH",
        },
        "max": {"model": "google/gemini-4-argon", "thinking_level": "HIGH"},
    }


# contract-test: direct surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles,ai-model-routing.precedence.chat-over-tier-over-auto
@pytest.mark.parametrize("tier,level", [
    ("low", "MEDIUM"), ("medium", "MEDIUM"), ("high", "HIGH"), ("max", "HIGH"),
])
def test_automatic_profile_applies_only_when_selected_model_matches(tier: str, level: str) -> None:
    routing = _routing_module()
    model = routing.default_profile_for_tier(tier)["model"]
    automatic = routing.resolve_model_routing(
        classified_tier=tier, chat_model_preference="auto", tier_preferences={},
        automatic_model=model,
    )
    assert automatic.thinking_level == level
    assert routing.resolve_model_routing(
        classified_tier=tier, chat_model_preference="auto", tier_preferences={},
        automatic_model="google/gemini-3.5-flash-lite",
    ).thinking_level is None
    assert routing.resolve_model_routing(
        classified_tier=tier, chat_model_preference=model,
        tier_preferences={}, automatic_model=model,
    ).thinking_level is None
    assert routing.resolve_model_routing(
        classified_tier=tier, chat_model_preference="auto",
        tier_preferences={tier: model},
        automatic_model=model,
    ).thinking_level is None


# contract-test: direct surface=rest_api assertions=ai-model-routing.preferences.exclusive-tier-defaults,ai-model-routing.precedence.chat-over-tier-over-auto
@pytest.mark.parametrize("tier,bucket", [
    ("low", "simple"), ("medium", "complex"), ("high", "complex"), ("max", "most_demanding"),
])
def test_four_tiers_honor_existing_saved_preferences(tier: str, bucket: str) -> None:
    routing = _routing_module()
    field = f"default_ai_model_{bucket}"
    assert routing.tier_preference_key(tier) == field
    for key in (field, bucket):
        decision = routing.resolve_model_routing(
            classified_tier=tier, chat_model_preference="auto",
            tier_preferences={key: "mistral/mistral-small-latest"},
            automatic_model=routing.default_profile_for_tier(tier)["model"],
        )
        assert decision.model_id == "mistral/mistral-small-latest"
        assert decision.source == "tier_user_preference"
        assert decision.thinking_level is None


# contract-test: direct surface=rest_api assertions=ai-model-routing.precedence.chat-over-tier-over-auto
def test_exact_chat_model_bypasses_only_model_tier_selection() -> None:
    """An exact chat choice skips tier-model routing, not unrelated preprocessing."""

    preprocessed: list[str] = []

    def run_non_model_preprocessing() -> None:
        preprocessed.append("ran")

    decision = _routing_module().resolve_model_routing(
        classified_tier="simple",
        chat_model_preference="anthropic/claude-sonnet-5",
        tier_preferences={"simple": "google/gemini-3.5-flash-lite"},
        automatic_model="google/gemini-3.5-flash-lite",
        run_non_model_preprocessing=run_non_model_preprocessing,
    )

    assert preprocessed == ["ran"]
    assert decision.model_id == "anthropic/claude-sonnet-5"
    assert decision.complexity_classifier_used_for_model is False


# contract-test: direct surface=rest_api assertions=ai-model-routing.precedence.chat-over-tier-over-auto
def test_explicit_api_model_parameter_becomes_preprocessor_override() -> None:
    resolved = _routing_module().explicit_api_model_override(
        {"model": "mistral/mistral-small-latest"},
        None,
    )
    assert resolved == ("mistral/mistral-small-latest", None)
    assert _routing_module().explicit_api_model_override(
        {"model": "mistral/mistral-small-latest"},
        "anthropic/claude-opus",
    ) is None


# contract-test: direct surface=rest_api assertions=ai-model-routing.precedence.chat-over-tier-over-auto,ai-model-routing.unavailable.notify-reset-auto
def test_unavailable_exact_chat_model_resets_to_auto_and_resumes_tier_routing() -> None:
    """Backend-owned routing must not retain or substitute an unavailable exact ID."""

    decision = _routing_module().resolve_model_routing(
        classified_tier="most_demanding",
        chat_model_preference="anthropic/claude-sonnet-5",
        tier_preferences={"most_demanding": "google/gemini-3.7-flash-high"},
        automatic_model="google/gemini-3.7-flash-high",
        is_model_available=lambda model_id: model_id != "anthropic/claude-sonnet-5",
    )

    assert decision.chat_model_preference == "auto"
    assert decision.model_id == "google/gemini-3.7-flash-high"
    assert decision.complexity_classifier_used_for_model is True


# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_automatic_low_fallback_has_low_profile_without_affecting_explicit_choices():
    routing = _routing_module()
    assert routing.automatic_profile_thinking_level("low", routing.LOW_FALLBACK_MODEL) == "LOW"
    assert routing.automatic_attempt_thinking_level("low", routing.LOW_FALLBACK_MODEL, "LOW") == "LOW"
    assert routing.automatic_attempt_thinking_level("medium", routing.LOW_FALLBACK_MODEL, "MEDIUM") == "MEDIUM"
    assert routing.automatic_attempt_thinking_level("low", routing.MERCURY_MODEL, None) is None


@pytest.mark.parametrize("content,expected", [
    ("hello", False), ([{"type": "text", "text": "hello"}], False),
    ([{"type": "image_url", "image_url": {"url": "private"}}], True),
    ({"result": [{"type": "image", "data": "private"}]}, True),
    ([{"type": "document", "source": {"data": "private"}}], True),
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_mercury_automatic_route_inspects_actual_content_blocks(content, expected):
    assert _routing_module().history_requires_non_text([{"role": "tool", "content": content}]) is expected


@pytest.mark.parametrize("preferences", [
    {"disabled_ai_models": ["mercury-3"]},
    {"disabled_ai_servers": {"mercury-3": ["inception"]}},
    {"excluded_provider_ids": ["inception"]},
    {"disabled_ai_providers": ["inception"]},
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_mercury_automatic_route_honors_user_restrictions(preferences):
    assert not _routing_module().mercury_allowed_by_preferences(preferences)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_low_selector_has_deterministic_gemini_fallback(monkeypatch):
    from backend.apps.ai.utils.model_selector import ModelSelector
    selector = ModelSelector(leaderboard_data={})
    monkeypatch.setattr(selector, "_get_ranked_models", lambda **_: [
        {"provider_id": "anthropic", "model_id": "claude-sonnet-5-5"},
    ])
    result = selector.select_models(complexity="low")
    assert result.primary_model_id == "inception/mercury-3"
    assert result.secondary_model_id == result.fallback_model_id == "google/gemini-3.8-flash"
    for restrictions in ({"required_input_type": "image"}, {"excluded_provider_ids": {"inception"}}, {"available_model_ids": ["gemini-3.8-flash"]}):
        fallback = selector.select_models(complexity="low", **restrictions)
        assert fallback.primary_model_id == "google/gemini-3.8-flash"
        assert fallback.secondary_model_id is None
    medium = selector.select_models(complexity="medium")
    assert medium.primary_model_id == "google/gemini-3.8-flash"
    assert medium.secondary_model_id == medium.fallback_model_id == "inception/mercury-3"


def _low_routing_provider_config(provider):
    return {"models": [{"id": "mercury-3", "servers": [{"id": "inception"}]}]} if provider == "inception" else {
        "models": [{"id": "gemini-3.8-flash", "servers": [{"id": "google_ai_studio"}, {"id": "google"}]}]}


@pytest.mark.parametrize("restriction", ["none", "image", "disabled_model", "disabled_server", "excluded_provider", "unhealthy", "unavailable"])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_preprocessor_automatic_low_eligibility_and_disabled_selector(monkeypatch, restriction):
    import asyncio
    from types import SimpleNamespace
    from backend.apps.ai.processing import preprocessor
    preferences = {
        "disabled_model": {"disabled_ai_models": ["mercury-3"]},
        "disabled_server": {"disabled_ai_servers": {"mercury-3": ["inception"]}},
        "excluded_provider": {"excluded_provider_ids": ["inception"]},
    }.get(restriction, {})
    request = SimpleNamespace(message_history=[{"role": "user", "content": "hello"}],
        has_image_upload_embed=restriction == "image", user_preferences=preferences)
    skill = SimpleNamespace(enable_auto_model_selection=False, default_llms=SimpleNamespace(
        main_processing_complex="google/gemini-3.8-flash", main_processing_complex_name="Gemini 3.8 Flash"))
    monkeypatch.setattr(preprocessor, "config_manager", SimpleNamespace(get_model_display_name=lambda model, _: model, get_provider_config=_low_routing_provider_config))
    monkeypatch.setattr(preprocessor, "_usable_chat_model_reference", lambda model, _: None if restriction == "unavailable" and model == "inception/mercury-3" else (model, model))
    async def healthy(*_):
        return restriction != "unhealthy"
    monkeypatch.setattr(preprocessor, "is_provider_healthy", healthy)
    result = asyncio.run(preprocessor._select_main_model(
        {"complexity": "low", "china_model_sensitive": False}, request, skill, None, "test"))
    expected = "inception/mercury-3" if restriction == "none" else "google/gemini-3.8-flash"
    assert result["selected_llm_for_main_id"] == expected
    assert result["selected_llm_thinking_level"] == ("MEDIUM" if restriction == "none" else "LOW")
    assert result["selected_fallback_model_id"] == ("google/gemini-3.8-flash" if restriction == "none" else None)


@pytest.mark.parametrize("choice", ["exact", "saved", "medium"])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles,ai-model-routing.precedence.chat-over-tier-over-auto
def test_preprocessor_keeps_explicit_choices_and_medium_unchanged(monkeypatch, choice):
    import asyncio
    from types import SimpleNamespace
    from backend.apps.ai.processing import preprocessor
    from backend.core.api.app.utils.override_parser import UserOverrides
    request = SimpleNamespace(message_history=[], has_image_upload_embed=False,
        user_preferences={"default_ai_model_simple": "inception/mercury-3"} if choice == "saved" else {})
    skill = SimpleNamespace(enable_auto_model_selection=False, default_llms=SimpleNamespace(
        main_processing_complex="google/gemini-3.8-flash", main_processing_complex_name="Gemini 3.8 Flash"))
    monkeypatch.setattr(preprocessor, "config_manager", SimpleNamespace(get_model_display_name=lambda model, _: model, get_provider_config=_low_routing_provider_config))
    monkeypatch.setattr(preprocessor, "_usable_chat_model_reference", lambda model, _: (model, model))
    async def forbidden(*_):
        raise AssertionError("Explicit/medium routing must not run automatic Mercury health selection")
    monkeypatch.setattr(preprocessor, "is_provider_healthy", forbidden)
    result = asyncio.run(preprocessor._select_main_model(
        {"complexity": "medium" if choice == "medium" else "low", "china_model_sensitive": False},
        request, skill, UserOverrides(model_id="inception/mercury-3") if choice == "exact" else None, "test"))
    assert result["selected_llm_thinking_level"] == ("MEDIUM" if choice == "medium" else None)
    assert result["selected_llm_for_main_id"] == ("google/gemini-3.8-flash" if choice == "medium" else "inception/mercury-3")


# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_dependency_free_low_resolution_bypasses_unavailable_mercury():
    routing = _routing_module()
    decision = routing.resolve_model_routing(classified_tier="low", chat_model_preference="auto",
        tier_preferences={}, automatic_model=routing.MERCURY_MODEL,
        is_model_available=lambda model: model != routing.MERCURY_MODEL)
    assert decision.model_id == routing.LOW_FALLBACK_MODEL
    assert decision.thinking_level == "LOW"


@pytest.mark.parametrize("gemini_restriction", [
    {"disabled_ai_models": ["gemini-3.8-flash"]},
    {"disabled_ai_providers": ["google"]},
    {"excluded_provider_ids": ["google"]},
    {"disabled_ai_servers": {"gemini-3.8-flash": ["google_ai_studio", "google"]}},
])
@pytest.mark.parametrize("mercury_ineligible", [True, False])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_automatic_low_never_substitutes_forbidden_gemini(monkeypatch, gemini_restriction, mercury_ineligible):
    import asyncio
    from types import SimpleNamespace
    from backend.apps.ai.processing import preprocessor
    request = SimpleNamespace(message_history=[{"role": "user", "content": "hello"}],
        has_image_upload_embed=mercury_ineligible, user_preferences=gemini_restriction)
    skill = SimpleNamespace(enable_auto_model_selection=False)
    monkeypatch.setattr(preprocessor, "config_manager", SimpleNamespace(
        get_model_display_name=lambda model, _: model, get_provider_config=_low_routing_provider_config))
    monkeypatch.setattr(preprocessor, "_usable_chat_model_reference", lambda model, _: (model, model))
    from unittest.mock import AsyncMock
    monkeypatch.setattr(preprocessor, "is_provider_healthy", AsyncMock(return_value=True))
    result = asyncio.run(preprocessor._select_main_model(
        {"complexity": "low", "china_model_sensitive": False}, request, skill, None, "test"))
    assert result["selected_llm_for_main_id"] == (None if mercury_ineligible else "inception/mercury-3")
    assert result["model_selection_unavailable"] is mercury_ineligible
    assert result["selected_secondary_model_id"] is None
    assert result["selected_fallback_model_id"] is None


# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_low_selector_fails_closed_when_both_providers_excluded():
    from backend.apps.ai.utils.model_selector import ModelSelector
    with pytest.raises(ValueError, match="No permitted"):
        ModelSelector(leaderboard_data={}).select_models(complexity="low", excluded_provider_ids={"inception", "google"})


# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
def test_low_routes_filter_disabled_google_host_without_losing_enabled_vertex():
    routing = _routing_module()
    preferences = {"disabled_ai_servers": {"gemini-3.8-flash": ["google_ai_studio"]}}
    assert routing.automatic_low_allowed_servers(routing.LOW_FALLBACK_MODEL, preferences, _low_routing_provider_config("google")) == {"google"}
    assert routing.automatic_low_allowed_servers(routing.LOW_FALLBACK_MODEL, {"disabled_ai_models": ["gemini-3.8-flash"]}, _low_routing_provider_config("google")) == set()
    with pytest.raises(ValueError, match="No permitted"):
        routing.resolve_model_routing(classified_tier="low", chat_model_preference="auto",
            tier_preferences={}, automatic_model=routing.MERCURY_MODEL, is_model_available=lambda _: False)


@pytest.mark.parametrize('restriction', ['image', 'disabled', 'all_disabled'])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.recovery.affordable-current-models
def test_invalid_explicit_selection_uses_permitted_automatic_recovery(monkeypatch, restriction):
    import asyncio
    from types import SimpleNamespace
    from backend.apps.ai.processing import preprocessor
    from backend.core.api.app.utils.override_parser import UserOverrides
    preferences = {'disabled_ai_models': ['mercury-3']} if restriction != 'image' else {}
    if restriction == 'all_disabled':
        preferences['disabled_ai_models'].append('gemini-3.8-flash')
    request = SimpleNamespace(message_history=[], has_image_upload_embed=restriction == 'image', user_preferences=preferences)
    skill = SimpleNamespace(enable_auto_model_selection=False, default_llms=SimpleNamespace(
        main_processing_complex='google/gemini-3.8-flash', main_processing_complex_name='Gemini 3.8 Flash'))
    monkeypatch.setattr(preprocessor, 'config_manager', SimpleNamespace(
        get_model_display_name=lambda model, _: model, get_provider_config=_low_routing_provider_config))
    monkeypatch.setattr(preprocessor, '_usable_chat_model_reference',
        lambda model, _: None if model == 'google/retired-model' else (model, model))
    result = asyncio.run(preprocessor._select_main_model(
        {'complexity': 'medium', 'china_model_sensitive': False}, request, skill,
        UserOverrides(model_id='google/retired-model'), 'test'))
    assert result['model_override_applied'] is False
    assert result['selected_llm_for_main_id'] == (None if restriction == 'all_disabled' else 'google/gemini-3.8-flash')
    assert result['selected_secondary_model_id'] is None
    assert result['selected_fallback_model_id'] is None


# contract-test: supporting surface=rest_api assertions=ai-model-routing.recovery.affordable-current-models
def test_disabled_automatic_selection_preserves_configured_primary(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from backend.apps.ai.processing import preprocessor
    request = SimpleNamespace(message_history=[], has_image_upload_embed=False, user_preferences={})
    skill = SimpleNamespace(enable_auto_model_selection=False, default_llms=SimpleNamespace(
        main_processing_complex='mistral/configured-model', main_processing_complex_name='Configured model'))
    def catalog(provider):
        return {'models': [{'id': 'configured-model', 'servers': [{'id': 'mistral'}]}]} if provider == 'mistral' else _low_routing_provider_config(provider)
    monkeypatch.setattr(preprocessor, 'config_manager', SimpleNamespace(
        get_model_display_name=lambda model, _: model, get_provider_config=catalog))
    monkeypatch.setattr(preprocessor, '_usable_chat_model_reference', lambda model, _: (model, model))
    result = asyncio.run(preprocessor._select_main_model(
        {'complexity': 'medium', 'china_model_sensitive': False}, request, skill, None, 'test'))
    assert result['selected_llm_for_main_id'] == 'mistral/configured-model'
    assert result['selected_secondary_model_id'] == 'google/gemini-3.8-flash'
    assert result['selected_fallback_model_id'] == 'inception/mercury-3'


# contract-test: supporting surface=rest_api assertions=ai-model-routing.reasoning.preprocessor-recommendation
@pytest.mark.parametrize("level,deadline,cap", [
    (None, 15., 16384), ("invalid", 15., 16384), ("LOW", 5., 8192),
    ("MEDIUM", 15., 16384), ("HIGH", 60., 32768), ("EXTRA_HIGH", 60., 32768),
])
def test_mercury_reasoning_budget_is_effort_specific(level, deadline, cap):
    routing = _routing_module()
    assert routing.mercury_reasoning_budget(level) == (deadline, cap)
    # The default Mercury effort must not leak into its low-tier Gemini fallback.
    assert routing.automatic_attempt_thinking_level("low", routing.LOW_FALLBACK_MODEL, "MEDIUM") == "LOW"
    assert routing.automatic_attempt_thinking_level("medium", routing.MERCURY_MODEL, "HIGH") == "MEDIUM"
