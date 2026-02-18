# backend/apps/ai/utils/model_selector.py
#
# Model selector service for intelligent AI model selection.
# Uses leaderboard rankings, task area, complexity, and sensitivity filters
# to select the optimal model(s) for each request.
#
# Respects the `allow_auto_select` flag from provider YAML configs - models
# with allow_auto_select=false are excluded from automatic selection and can
# only be used via explicit @ai-model:xxx user overrides.

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

import yaml

logger = logging.getLogger(__name__)

# Provider YAML files containing model configs with allow_auto_select settings
PROVIDERS_DIR = Path("/app/backend/providers")
LLM_PROVIDER_FILES = [
    "anthropic.yml",
    "openai.yml",
    "google.yml",
    "mistral.yml",
    "alibaba.yml",
    "zai.yml",
]


@dataclass
class ModelSelectionResult:
    """
    Result of model selection containing primary, secondary, and fallback models.

    Attributes:
        primary_model_id: Best model for the task (highest ranked for task area)
        secondary_model_id: Fallback if primary fails (second best)
        fallback_model_id: Last resort fallback (reliable default)
        selection_reason: Human-readable explanation of why these models were chosen
        filtered_cn_models: True if CN models were excluded due to sensitivity
    """
    primary_model_id: str
    secondary_model_id: Optional[str] = None
    fallback_model_id: Optional[str] = None
    selection_reason: str = ""
    filtered_cn_models: bool = False


# Default fallback models (always available, reliable)
# These MUST include provider prefix for billing/routing to work
DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4-6"  # Reliable Claude Sonnet
DEFAULT_FALLBACK_MODEL_ALT = "anthropic/claude-haiku-4-5-20251001"  # Fast, affordable fallback

# Task area to leaderboard category mapping
TASK_AREA_CATEGORIES = {
    "code": "code",
    "math": "math",
    "creative": "creative",
    "instruction": "instruction",
    "general": "general",
}

# Models considered economical (for simple tasks)
# These are model_id values from leaderboard (without provider prefix)
ECONOMICAL_MODELS = {
    "claude-haiku-4-5-20251001",  # Fast, affordable Claude
    "gemini-3-flash-preview",     # Fast Gemini
    "gemini-flash-latest",        # Fast Gemini
    "gpt-oss-120b",               # Cheaper GPT
}

# Models considered premium (for complex tasks or when user is unhappy)
# These are model_id values from leaderboard (without provider prefix)
PREMIUM_MODELS = {
    "claude-opus-4-6",               # Top Claude
    "claude-sonnet-4-6",             # High-quality Claude
    "gemini-3-pro-preview",          # Top Gemini
    "gpt-5.2",                       # Top GPT
}

# Cache for allow_auto_select settings (loaded once per process)
_auto_select_cache: Optional[Dict[str, bool]] = None


def _load_auto_select_settings() -> Dict[str, bool]:
    """
    Load allow_auto_select settings from all provider YAML files.

    Returns:
        Dict mapping model_id -> allow_auto_select (True/False)
        Models without the setting default to False (safe default).
    """
    global _auto_select_cache

    if _auto_select_cache is not None:
        return _auto_select_cache

    settings: Dict[str, bool] = {}

    for provider_file in LLM_PROVIDER_FILES:
        provider_path = PROVIDERS_DIR / provider_file
        if not provider_path.exists():
            logger.debug(f"Provider file not found: {provider_path}")
            continue

        try:
            with open(provider_path, 'r') as f:
                provider_config = yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Failed to load provider YAML {provider_file}: {e}")
            continue

        for model in provider_config.get("models", []):
            model_id = model.get("id")
            if not model_id:
                continue

            # Default to False if not specified (safe: requires explicit opt-in)
            allow_auto = model.get("allow_auto_select", False)
            settings[model_id] = allow_auto

    _auto_select_cache = settings
    logger.info(
        f"Loaded allow_auto_select settings for {len(settings)} models. "
        f"Auto-select enabled: {sum(1 for v in settings.values() if v)}"
    )
    return settings


def clear_auto_select_cache() -> None:
    """
    Clear the cached auto_select settings.

    Call this if provider YAML files have been modified and you want
    to reload the settings without restarting the process.
    """
    global _auto_select_cache
    _auto_select_cache = None
    logger.info("Cleared allow_auto_select cache")


class ModelSelector:
    """
    Intelligent model selector that uses leaderboard rankings and context
    to choose the best model(s) for each request.
    """

    def __init__(self, leaderboard_data: Optional[Dict[str, Any]] = None):
        """
        Initialize the model selector.

        Args:
            leaderboard_data: Pre-loaded leaderboard data from cache/file.
                            If None, will use default rankings.
        """
        self._leaderboard_data = leaderboard_data
        self._rankings_cache: Dict[str, List[str]] = {}

    def set_leaderboard_data(self, leaderboard_data: Dict[str, Any]) -> None:
        """
        Update the leaderboard data.

        Args:
            leaderboard_data: New leaderboard data
        """
        self._leaderboard_data = leaderboard_data
        self._rankings_cache.clear()

    def _get_ranked_models(
        self,
        exclude_cn: bool = False,
        only_auto_select_enabled: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get ranked models from leaderboard data, with optional filtering.

        Args:
            exclude_cn: If True, exclude models with country_origin=CN
            only_auto_select_enabled: If True (default), exclude models with
                allow_auto_select=false in their provider YAML config.
                Set to False to include all ranked models regardless of auto-select setting.

        Returns:
            List of ranked model entries sorted by composite score
        """
        if not self._leaderboard_data:
            return []

        rankings = self._leaderboard_data.get("rankings", [])

        # Filter by allow_auto_select setting from provider YAMLs
        if only_auto_select_enabled:
            auto_select_settings = _load_auto_select_settings()
            original_count = len(rankings)
            rankings = [
                r for r in rankings
                if auto_select_settings.get(r.get("model_id"), False) is True
            ]
            filtered_count = original_count - len(rankings)
            if filtered_count > 0:
                logger.debug(
                    f"Filtered out {filtered_count} models with allow_auto_select=false"
                )

        # Filter by country origin (China-sensitive content)
        if exclude_cn:
            rankings = [r for r in rankings if r.get("country_origin") != "CN"]

        return rankings

    def _filter_by_capabilities(
        self,
        models: List[Dict[str, Any]],
        required_input_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Filter models by required capabilities (input types, etc.).

        Args:
            models: List of model entries
            required_input_type: Required input type (e.g., "image")

        Returns:
            Filtered list of models
        """
        # For now, we don't have input_types in leaderboard data
        # This can be extended later when we add capability filtering
        return models

    def select_models(
        self,
        task_area: str = "general",
        complexity: str = "simple",
        china_related: bool = False,
        user_unhappy: bool = False,
        required_input_type: Optional[str] = None,
        available_model_ids: Optional[List[str]] = None,
        log_prefix: str = ""
    ) -> ModelSelectionResult:
        """
        Select the best models for a request based on various factors.

        Selection logic:
        1. Get ranked models for the task area from leaderboard
        2. Filter out CN models if china_related is True
        3. If simple task and user not unhappy → prefer economical model
        4. If complex task or user unhappy → prefer premium/leading model
        5. Return top 2 models + hardcoded fallback

        Args:
            task_area: The type of task (code, math, creative, instruction, general)
            complexity: Task complexity (simple, complex)
            china_related: If True, exclude CN-origin models
            user_unhappy: If True, use premium models to improve response quality
            required_input_type: Required input type (e.g., "image" for vision)
            available_model_ids: If provided, only select from these models
            log_prefix: Prefix for log messages

        Returns:
            ModelSelectionResult with primary, secondary, and fallback model IDs
        """
        reasons = []

        # Step 1: Get ranked models (filtered by allow_auto_select=true by default)
        ranked_models = self._get_ranked_models(exclude_cn=china_related)

        if not ranked_models:
            # Check if leaderboard has models but all are filtered out by allow_auto_select
            all_ranked = self._get_ranked_models(
                exclude_cn=china_related, only_auto_select_enabled=False
            )
            if all_ranked:
                reasons.append(
                    f"No models with allow_auto_select=true ({len(all_ranked)} models filtered)"
                )
            else:
                reasons.append("No ranked models available in leaderboard")
        else:
            reasons.append(f"Filtered to {len(ranked_models)} models with allow_auto_select=true")

        if china_related:
            reasons.append("CN models excluded (China-sensitive content)")

        # Step 2: Filter by available models if specified
        if available_model_ids:
            available_set = set(available_model_ids)
            ranked_models = [m for m in ranked_models if m.get("model_id") in available_set]
            reasons.append(f"Filtered to {len(ranked_models)} available models")

        # Step 3: Filter by capabilities
        ranked_models = self._filter_by_capabilities(ranked_models, required_input_type)

        # Step 4: Determine selection strategy based on complexity and user satisfaction
        prefer_economical = complexity == "simple" and not user_unhappy
        prefer_premium = complexity == "complex" or user_unhappy

        if prefer_premium:
            reasons.append("Premium model preferred (complex task or user unhappy)")
        elif prefer_economical:
            reasons.append("Economical model preferred (simple task)")

        # Step 5: Select primary model
        # We need to track both the model_id (for matching against ECONOMICAL/PREMIUM sets) and
        # the full qualified ID (provider_id/model_id) for the result
        primary_model_id = None  # Short model_id for matching against sets
        primary_full_id = None   # Full provider/model_id for result
        secondary_full_id = None  # Full provider/model_id for result

        # Helper function to build fully qualified model ID
        def _build_full_model_id(model_entry: Dict[str, Any]) -> Optional[str]:
            """Build provider_id/model_id from a leaderboard entry."""
            provider_id = model_entry.get("provider_id")
            model_id = model_entry.get("model_id")
            if provider_id and model_id:
                return f"{provider_id}/{model_id}"
            return None

        if ranked_models:
            if prefer_economical:
                # Find best economical model that's in our rankings
                for model_entry in ranked_models:
                    model_id = model_entry.get("model_id")
                    if model_id and model_id in ECONOMICAL_MODELS:
                        primary_model_id = model_id
                        primary_full_id = _build_full_model_id(model_entry)
                        reasons.append(f"Selected economical model: {primary_full_id}")
                        break

                # If no economical model in rankings, just use the top ranked
                if not primary_model_id and ranked_models:
                    primary_model_id = ranked_models[0].get("model_id")
                    primary_full_id = _build_full_model_id(ranked_models[0])
                    reasons.append(f"Selected top-ranked model (no economical match): {primary_full_id}")

            elif prefer_premium:
                # Find best premium model that's in our rankings
                for model_entry in ranked_models:
                    model_id = model_entry.get("model_id")
                    if model_id and model_id in PREMIUM_MODELS:
                        primary_model_id = model_id
                        primary_full_id = _build_full_model_id(model_entry)
                        reasons.append(f"Selected premium model: {primary_full_id}")
                        break

                # If no premium model in rankings, just use the top ranked
                if not primary_model_id and ranked_models:
                    primary_model_id = ranked_models[0].get("model_id")
                    primary_full_id = _build_full_model_id(ranked_models[0])
                    reasons.append(f"Selected top-ranked model (no premium match): {primary_full_id}")

            else:
                # Default: use top ranked model
                if ranked_models:
                    primary_model_id = ranked_models[0].get("model_id")
                    primary_full_id = _build_full_model_id(ranked_models[0])
                    reasons.append(f"Selected top-ranked model: {primary_full_id}")

            # Select secondary model (different from primary)
            for model_entry in ranked_models:
                model_id = model_entry.get("model_id")
                if model_id and model_id != primary_model_id:
                    secondary_full_id = _build_full_model_id(model_entry)
                    break

        # Step 6: Ensure we have at least a primary model (with provider prefix)
        if not primary_full_id:
            primary_full_id = DEFAULT_FALLBACK_MODEL
            reasons.append(f"No ranked models available, using default: {primary_full_id}")

        # Step 7: Set fallback model (always with provider prefix)
        fallback_full_id = DEFAULT_FALLBACK_MODEL
        if fallback_full_id == primary_full_id:
            # Use a different fallback if primary is already the default
            fallback_full_id = DEFAULT_FALLBACK_MODEL_ALT

        # Log the selection
        selection_reason = "; ".join(reasons)
        logger.info(
            f"{log_prefix} MODEL_SELECTION: primary={primary_full_id}, "
            f"secondary={secondary_full_id}, fallback={fallback_full_id}. "
            f"Reason: {selection_reason}"
        )

        return ModelSelectionResult(
            primary_model_id=primary_full_id,
            secondary_model_id=secondary_full_id,
            fallback_model_id=fallback_full_id,
            selection_reason=selection_reason,
            filtered_cn_models=china_related,
        )

    def get_model_ids_list(self, result: ModelSelectionResult) -> List[str]:
        """
        Get a list of model IDs to try in order (primary, secondary, fallback).

        Args:
            result: ModelSelectionResult from select_models()

        Returns:
            List of model IDs to try in order, with no duplicates
        """
        models = []
        seen = set()

        for model_id in [result.primary_model_id, result.secondary_model_id, result.fallback_model_id]:
            if model_id and model_id not in seen:
                models.append(model_id)
                seen.add(model_id)

        return models


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Functions
# ═══════════════════════════════════════════════════════════════════════════════

async def get_model_selector() -> ModelSelector:
    """
    Get a ModelSelector instance with leaderboard data loaded from cache.

    Returns:
        ModelSelector instance ready to use
    """
    try:
        from backend.core.api.app.tasks.leaderboard_tasks import get_leaderboard_data
        leaderboard_data = await get_leaderboard_data()
        return ModelSelector(leaderboard_data=leaderboard_data)
    except Exception as e:
        logger.warning(f"Failed to load leaderboard data for model selector: {e}")
        return ModelSelector(leaderboard_data=None)


def select_models_simple(
    task_area: str = "general",
    china_related: bool = False,
    user_unhappy: bool = False,
    leaderboard_data: Optional[Dict[str, Any]] = None,
    log_prefix: str = ""
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Simple synchronous model selection returning a tuple of model IDs.

    Args:
        task_area: The type of task
        china_related: If True, exclude CN models
        user_unhappy: If True, use premium models
        leaderboard_data: Optional pre-loaded leaderboard data
        log_prefix: Prefix for log messages

    Returns:
        Tuple of (primary_model_id, secondary_model_id, fallback_model_id)
    """
    selector = ModelSelector(leaderboard_data=leaderboard_data)
    result = selector.select_models(
        task_area=task_area,
        china_related=china_related,
        user_unhappy=user_unhappy,
        log_prefix=log_prefix,
    )
    return (result.primary_model_id, result.secondary_model_id, result.fallback_model_id)
