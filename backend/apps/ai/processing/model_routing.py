# backend/apps/ai/processing/model_routing.py
#
# Dependency-free boundary for approved AI model-routing semantics.
# The preprocessor can import this module without pulling in provider clients,
# caches, FastAPI, or Directus. It owns four-tier normalization, default tier
# profiles, and precedence between exact chat selection, tier preferences, and
# automatic model selection. Durable preference storage remains outside here.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


RequestTier = str

LOW_TIER: RequestTier = "low"
MEDIUM_TIER: RequestTier = "medium"
HIGH_TIER: RequestTier = "high"
MAX_TIER: RequestTier = "max"
APPROVED_REQUEST_TIERS: tuple[RequestTier, ...] = (
    LOW_TIER,
    MEDIUM_TIER,
    HIGH_TIER,
    MAX_TIER,
)
DEFAULT_SAFE_TIER: RequestTier = MEDIUM_TIER
AUTO_CHAT_MODEL_PREFERENCE = "auto"

# Existing settings and clients retain their three saved preference fields.
TIER_PREFERENCE_BUCKETS: dict[RequestTier, str] = {
    LOW_TIER: "simple",
    MEDIUM_TIER: "complex",
    HIGH_TIER: "complex",
    MAX_TIER: "most_demanding",
}
LEGACY_REQUEST_TIERS: dict[str, RequestTier] = {
    "simple": LOW_TIER,
    "complex": MEDIUM_TIER,
    "most_demanding": MAX_TIER,
}

DEFAULT_TIER_MODEL_PROFILES: dict[RequestTier, dict[str, str]] = {
    LOW_TIER: {
        "model": "inception/mercury-3",
        "thinking_level": "MEDIUM",
    },
    MEDIUM_TIER: {
        "model": "google/gemini-3.8-flash",
        "thinking_level": "MEDIUM",
    },
    HIGH_TIER: {
        "model": "google/gemini-3.8-flash",
        "thinking_level": "HIGH",
    },
    MAX_TIER: {
        "model": "google/gemini-4-argon",
        "thinking_level": "HIGH",
    },
}


LOW_FALLBACK_MODEL = "google/gemini-3.8-flash"
MERCURY_MODEL = "inception/mercury-3"
MERCURY_REASONING_BUDGETS = {
    "LOW": (5.0, 8192),
    "MEDIUM": (15.0, 16384),
    "HIGH": (60.0, 32768),
}


def mercury_reasoning_budget(requested_level: str | None) -> tuple[float, int]:
    """Bound reasoning plus visible output without increasing credit limits."""
    from backend.apps.ai.utils.model_reasoning import normalize_reasoning_level

    level = normalize_reasoning_level(requested_level) or "MEDIUM"
    return MERCURY_REASONING_BUDGETS["HIGH" if level == "EXTRA_HIGH" else level]


def automatic_model_candidates(tier: str) -> list[str]:
    """Return current approved routes, ending with inexpensive text recovery."""
    return list(dict.fromkeys([
        default_profile_for_tier(tier)["model"], LOW_FALLBACK_MODEL, MERCURY_MODEL,
    ]))


def automatic_attempt_thinking_level(tier: str, model_id: str, primary_level: str | None) -> str | None:
    """Retain automatic provenance separately from a Jev effort recommendation."""
    if primary_level is None or model_id not in automatic_model_candidates(tier):
        return None
    if model_id == MERCURY_MODEL:
        return "MEDIUM"
    if normalize_request_tier(tier) == LOW_TIER:
        return "LOW"
    return primary_level


def history_requires_non_text(history: Any) -> bool:
    """Inspect actual content blocks, including image/document tool results."""
    for message in history or []:
        content = message.get("content") if isinstance(message, Mapping) else getattr(message, "content", None)
        if isinstance(content, list):
            if any(not isinstance(block, Mapping) or block.get("type") != "text"
                   or not isinstance(block.get("text"), str) for block in content):
                return True
        elif isinstance(content, Mapping):
            # Rich tool payloads may wrap provider-ready image blocks.
            if content.get("type") in {"image", "image_url", "input_image", "document", "file", "input_file"}:
                return True
            if history_requires_non_text([{"content": value} for value in content.values() if isinstance(value, (list, Mapping))]):
                return True
    return False


def mercury_allowed_by_preferences(preferences: Mapping[str, Any] | None) -> bool:
    preferences = preferences or {}
    disabled_models = preferences.get("disabled_ai_models") or []
    disabled_servers = preferences.get("disabled_ai_servers") or {}
    excluded_providers = set(preferences.get("excluded_provider_ids") or []) | set(preferences.get("disabled_ai_providers") or [])
    return ("mercury-3" not in disabled_models and MERCURY_MODEL not in disabled_models
            and "inception" not in (disabled_servers.get("mercury-3") or [])
            and "inception" not in excluded_providers)


def automatic_model_allowed_servers(
    model_id: str, preferences: Mapping[str, Any] | None,
    provider_config: Mapping[str, Any] | None,
) -> set[str]:
    """Enforce model, provider and server restrictions on every automatic route."""
    if not provider_config or "/" not in model_id:
        return set()
    preferences = preferences or {}
    provider, model = model_id.split("/", 1)
    disabled_models = preferences.get("disabled_ai_models") or []
    disabled_servers = preferences.get("disabled_ai_servers") or {}
    if not isinstance(disabled_servers, Mapping):
        return set()
    excluded = set(preferences.get("excluded_provider_ids") or []) | set(preferences.get("disabled_ai_providers") or [])
    if provider in excluded or model in disabled_models or model_id in disabled_models:
        return set()
    model_config = next((entry for entry in provider_config.get("models", [])
                         if isinstance(entry, Mapping) and entry.get("id") == model), None)
    if model_config is None:
        return set()
    blocked = set(disabled_servers.get(model) or []) | set(disabled_servers.get(model_id) or [])
    return {server["id"] for server in model_config.get("servers", [])
            if isinstance(server, Mapping) and isinstance(server.get("id"), str)
            and server["id"] not in blocked and server["id"] not in excluded}


def automatic_low_allowed_servers(
    model_id: str, preferences: Mapping[str, Any] | None,
    provider_config: Mapping[str, Any] | None,
) -> set[str]:
    """Retain the existing low-pair boundary for callers restricted to that pair."""
    if model_id not in {MERCURY_MODEL, LOW_FALLBACK_MODEL}:
        return set()
    return automatic_model_allowed_servers(model_id, preferences, provider_config)


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
    if isinstance(classified_tier, str):
        return LEGACY_REQUEST_TIERS.get(classified_tier, DEFAULT_SAFE_TIER)
    return DEFAULT_SAFE_TIER


def tier_preference_key(tier: RequestTier) -> str:
    """Map an approved request tier to its user preference field."""

    normalized_tier = normalize_request_tier(tier)
    return f"default_ai_model_{TIER_PREFERENCE_BUCKETS[normalized_tier]}"


def default_profile_for_tier(tier: RequestTier) -> dict[str, str]:
    """Return the approved default model profile for a normalized tier."""

    return DEFAULT_TIER_MODEL_PROFILES[normalize_request_tier(tier)]


def automatic_profile_thinking_level(tier: RequestTier, model_id: str | None) -> str | None:
    """Apply a tier's reasoning profile only to its automatically chosen model."""

    profile = default_profile_for_tier(tier)
    if model_id not in automatic_model_candidates(tier):
        return None
    if model_id == MERCURY_MODEL:
        return "MEDIUM"
    return "LOW" if normalize_request_tier(tier) == LOW_TIER else profile["thinking_level"]


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
    user_tier_model = (
        preferences.get(tier)
        or preferences.get(tier_preference_key(tier))
        or preferences.get(TIER_PREFERENCE_BUCKETS[tier])
    )
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
            thinking_level=automatic_profile_thinking_level(tier, automatic_model),
        )

    profile = default_profile_for_tier(tier)
    fallback_model = profile["model"]
    if tier == LOW_TIER and fallback_model == MERCURY_MODEL and not _available(fallback_model, is_model_available):
        fallback_model = LOW_FALLBACK_MODEL
        if not _available(fallback_model, is_model_available):
            raise ValueError("No permitted automatic low model is available")
    return ModelRoutingDecision(
        tier=tier,
        model_id=fallback_model,
        chat_model_preference=AUTO_CHAT_MODEL_PREFERENCE,
        complexity_classifier_used_for_model=True,
        source="configured_fallback",
        thinking_level=automatic_profile_thinking_level(tier, fallback_model),
    )
