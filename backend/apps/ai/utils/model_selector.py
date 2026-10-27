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

from backend.apps.ai.processing.model_routing import (
    LOW_FALLBACK_MODEL, MERCURY_MODEL, automatic_model_candidates,
    normalize_request_tier,
)

logger = logging.getLogger(__name__)

# Provider YAML files containing model configs with allow_auto_select settings
PROVIDERS_DIR = Path("/app/backend/providers")
LLM_PROVIDER_FILES = [
    "inception.yml",
    "anthropic.yml",
    "openai.yml",
    "google.yml",
    "mistral.yml",
    "deepseek.yml",
    "moonshot.yml",
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


# Current, cost-bounded recovery models. Eligibility is checked for every route.
# These MUST include provider prefix for billing/routing to work.
DEFAULT_FALLBACK_MODEL = MERCURY_MODEL
DEFAULT_FALLBACK_MODEL_ALT = LOW_FALLBACK_MODEL

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
    "claude-haiku-5-5",           # Fast, affordable Claude
    "gemini-3.5-flash-lite",      # Fastest, cheapest Gemini
    "gemini-3-flash-preview",     # Fast Gemini
    "gemini-flash-latest",        # Fast Gemini
    "gpt-oss-120b",               # Cheaper GPT
    "gpt-6-luna",                 # Fast, affordable GPT
}

# Models considered premium (for complex tasks or when user is unhappy)
# These are model_id values from leaderboard (without provider prefix)
PREMIUM_MODELS = {
    "gpt-6-astra",                    # Most capable GPT
    "gpt-6.1-sol",                  # High-capability GPT
    "gpt-5.6-terra",                # Balanced reasoning GPT
    "claude-fable-5-1",               # Latest max-capability Claude
    "claude-opus-5-5",                # Latest Opus
    "claude-sonnet-5-5",              # Latest Sonnet
    "gemini-3.8-flash",              # Current Gemini Flash
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



def warm_auto_select_settings() -> None:
    """Parse deployment-static provider policy once in each AI worker child.

    Runtime provider YAML changes still require clear_auto_select_cache(). This
    warmup reads local policy only; model choice and provider calls stay per turn.
    """
    _load_auto_select_settings()



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
        complexity: str = "low",
        china_related: bool = False,
        user_unhappy: bool = False,
        required_input_type: Optional[str] = None,
        available_model_ids: Optional[List[str]] = None,
        excluded_provider_ids: Optional[set[str]] = None,
        log_prefix: str = ""
    ) -> ModelSelectionResult:
        """Select an eligible tier default followed by current, affordable recovery.

        Leaderboard changes must not silently introduce an older Gemini model
        or a premium paid model into an automatic failure path. Exact user
        selections bypass this selector. An explicit empty availability list
        means no permitted route, rather than unrestricted availability.
        """
        complexity = normalize_request_tier(complexity)
        available = set(available_model_ids) if available_model_ids is not None else None
        excluded = excluded_provider_ids or set()
        candidates = []
        for model_id in automatic_model_candidates(complexity):
            provider, short_id = model_id.split("/", 1)
            if provider in excluded:
                continue
            if available is not None and model_id not in available and short_id not in available:
                continue
            if model_id == MERCURY_MODEL and required_input_type not in {None, "text"}:
                continue
            candidates.append(model_id)
        if not candidates:
            raise ValueError(f"No permitted automatic {complexity} model is available")

        primary_full_id = candidates[0]
        secondary_full_id = candidates[1] if len(candidates) > 1 else None
        fallback_full_id = candidates[-1] if len(candidates) > 1 else None
        reasons = [f"Selected configured {complexity} default or permitted recovery: {primary_full_id}",
                   "Current cost-bounded automatic recovery; rankings cannot add providers"]
        if china_related:
            reasons.append("CN models excluded (China-sensitive content)")
        if excluded:
            reasons.append(f"Excluded providers: {', '.join(sorted(excluded))}")
        if user_unhappy:
            reasons.append("User unhappy; preserve the configured tier without paid escalation")

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
