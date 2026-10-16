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
            "model": "google/gemini-3.8-flash",
            "thinking_level": "LOW",
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
    ("low", "LOW"), ("medium", "MEDIUM"), ("high", "HIGH"), ("max", "HIGH"),
])
def test_automatic_profile_applies_only_when_selected_model_matches(tier: str, level: str) -> None:
    routing = _routing_module()
    model = "google/gemini-4-argon" if tier == "max" else "google/gemini-3.8-flash"
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
