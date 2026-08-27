# backend/apps/ai/processing/model_routing.py
#
# Dependency-free boundary for approved AI model-routing semantics.
# The preprocessor can import this module without pulling in provider clients,
# caches, FastAPI, or Directus. It owns three-tier normalization, default tier
# profiles, and precedence between exact chat selection, tier preferences, and
# automatic model selection. Durable preference storage remains outside here.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


RequestTier = str

SIMPLE_TIER: RequestTier = "simple"
COMPLEX_TIER: RequestTier = "complex"
MOST_DEMANDING_TIER: RequestTier = "most_demanding"
APPROVED_REQUEST_TIERS: tuple[RequestTier, ...] = (
    SIMPLE_TIER,
    COMPLEX_TIER,
    MOST_DEMANDING_TIER,
)
DEFAULT_SAFE_TIER: RequestTier = COMPLEX_TIER
AUTO_CHAT_MODEL_PREFERENCE = "auto"

DEFAULT_TIER_MODEL_PROFILES: dict[RequestTier, dict[str, str]] = {
    SIMPLE_TIER: {
        "model": "google/gemini-3.5-flash-lite",
        "thinking_level": "LOW",
    },
    COMPLEX_TIER: {
        "model": "google/gemini-3.7-flash",
        "thinking_level": "MEDIUM",
    },
    MOST_DEMANDING_TIER: {
        "model": "google/gemini-3.7-flash-high",
        "thinking_level": "HIGH",
    },
}


@dataclass(frozen=True)
class ModelRoutingDecision:
    tier: RequestTier
    model_id: str
    chat_model_preference: str
    complexity_classifier_used_for_model: bool
    source: str
    thinking_level: str | None = None


def normalize_request_tier(classified_tier: str | None) -> RequestTier:
    """Return an approved request tier, resolving uncertainty conservatively."""

    if classified_tier in APPROVED_REQUEST_TIERS:
        return classified_tier
    return DEFAULT_SAFE_TIER


def tier_preference_key(tier: RequestTier) -> str:
    """Map an approved request tier to its user preference field."""

    normalized_tier = normalize_request_tier(tier)
    return f"default_ai_model_{normalized_tier}"


def default_profile_for_tier(tier: RequestTier) -> dict[str, str]:
    """Return the approved default model profile for a normalized tier."""

    return DEFAULT_TIER_MODEL_PROFILES[normalize_request_tier(tier)]


def explicit_api_model_override(
    user_preferences: Mapping[str, Any] | None,
    existing_model_override: str | None,
) -> tuple[str, str | None] | None:
    """Resolve an explicit API model without replacing an in-message override."""

    if existing_model_override:
        return None
    explicit_model = (user_preferences or {}).get("model")
    if not isinstance(explicit_model, str) or not explicit_model.strip():
        return None
    provider = (user_preferences or {}).get("provider")
    normalized_provider = provider.strip() if isinstance(provider, str) and provider.strip() else None
    return explicit_model.strip(), normalized_provider


def _is_exact_model_preference(value: str | None) -> bool:
    return isinstance(value, str) and value != AUTO_CHAT_MODEL_PREFERENCE and "/" in value


def _available(model_id: str, is_model_available: Callable[[str], bool] | None) -> bool:
    return True if is_model_available is None else bool(is_model_available(model_id))


def resolve_model_routing(
    *,
    classified_tier: str | None,
    chat_model_preference: str | None,
    tier_preferences: Mapping[str, str | None] | None,
    automatic_model: str,
    is_model_available: Callable[[str], bool] | None = None,
    run_non_model_preprocessing: Callable[[], None] | None = None,
) -> ModelRoutingDecision:
    """Resolve one model ID while preserving non-model preprocessing behavior."""

    if run_non_model_preprocessing is not None:
        run_non_model_preprocessing()

    tier = normalize_request_tier(classified_tier)
    preference = chat_model_preference or AUTO_CHAT_MODEL_PREFERENCE
    if _is_exact_model_preference(preference) and _available(preference, is_model_available):
        return ModelRoutingDecision(
            tier=tier,
            model_id=preference,
            chat_model_preference=preference,
            complexity_classifier_used_for_model=False,
            source="chat_exact_model",
        )

    preferences = tier_preferences or {}
    user_tier_model = preferences.get(tier) or preferences.get(tier_preference_key(tier))
    if _is_exact_model_preference(user_tier_model) and _available(user_tier_model, is_model_available):
        return ModelRoutingDecision(
            tier=tier,
            model_id=user_tier_model,
            chat_model_preference=AUTO_CHAT_MODEL_PREFERENCE,
            complexity_classifier_used_for_model=True,
            source="tier_user_preference",
        )

    if automatic_model and _available(automatic_model, is_model_available):
        return ModelRoutingDecision(
            tier=tier,
            model_id=automatic_model,
            chat_model_preference=AUTO_CHAT_MODEL_PREFERENCE,
            complexity_classifier_used_for_model=True,
            source="automatic_selection",
        )

    profile = default_profile_for_tier(tier)
    return ModelRoutingDecision(
        tier=tier,
        model_id=profile["model"],
        chat_model_preference=AUTO_CHAT_MODEL_PREFERENCE,
        complexity_classifier_used_for_model=True,
        source="configured_fallback",
        thinking_level=profile["thinking_level"],
    )
