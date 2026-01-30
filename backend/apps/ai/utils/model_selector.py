# backend/apps/ai/utils/model_selector.py
#
# Model selector service for intelligent AI model selection.
# Uses leaderboard rankings, task area, complexity, and sensitivity filters
# to select the optimal model(s) for each request.

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
DEFAULT_FALLBACK_MODEL = "claude-sonnet-4-5-20250929"  # Reliable Claude Sonnet

# Task area to leaderboard category mapping
TASK_AREA_CATEGORIES = {
    "code": "code",
    "math": "math",
    "creative": "creative",
    "instruction": "instruction",
    "general": "general",
}

# Models considered economical (for simple tasks)
ECONOMICAL_MODELS = {
    "claude-haiku-4-5-20251001",  # Fast, affordable Claude
    "gemini-3-flash-20250602",    # Fast Gemini
    "gpt-oss-120b-20250601",      # Cheaper GPT
}

# Models considered premium (for complex tasks or when user is unhappy)
PREMIUM_MODELS = {
    "claude-opus-4-5-20251101",      # Top Claude
    "claude-sonnet-4-5-20250929",    # High-quality Claude
    "gemini-3-pro-20250602",         # Top Gemini
    "gpt-5.2-20250807",              # Top GPT
}


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
        exclude_cn: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get ranked models from leaderboard data, optionally excluding CN models.

        Args:
            exclude_cn: If True, exclude models with country_origin=CN

        Returns:
            List of ranked model entries sorted by composite score
        """
        if not self._leaderboard_data:
            return []

        rankings = self._leaderboard_data.get("rankings", [])

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

        # Step 1: Get ranked models
        ranked_models = self._get_ranked_models(exclude_cn=china_related)

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
        primary_model_id = None
        secondary_model_id = None

        if ranked_models:
            # Get model IDs from rankings
            ranked_model_ids = [m.get("model_id") for m in ranked_models if m.get("model_id")]

            if prefer_economical:
                # Find best economical model that's in our rankings
                for model_id in ranked_model_ids:
                    if model_id in ECONOMICAL_MODELS:
                        primary_model_id = model_id
                        reasons.append(f"Selected economical model: {model_id}")
                        break

                # If no economical model in rankings, just use the top ranked
                if not primary_model_id and ranked_model_ids:
                    primary_model_id = ranked_model_ids[0]
                    reasons.append(f"Selected top-ranked model (no economical match): {primary_model_id}")

            elif prefer_premium:
                # Find best premium model that's in our rankings
                for model_id in ranked_model_ids:
                    if model_id in PREMIUM_MODELS:
                        primary_model_id = model_id
                        reasons.append(f"Selected premium model: {model_id}")
                        break

                # If no premium model in rankings, just use the top ranked
                if not primary_model_id and ranked_model_ids:
                    primary_model_id = ranked_model_ids[0]
                    reasons.append(f"Selected top-ranked model (no premium match): {primary_model_id}")

            else:
                # Default: use top ranked model
                if ranked_model_ids:
                    primary_model_id = ranked_model_ids[0]
                    reasons.append(f"Selected top-ranked model: {primary_model_id}")

            # Select secondary model (different from primary)
            for model_id in ranked_model_ids:
                if model_id != primary_model_id:
                    secondary_model_id = model_id
                    break

        # Step 6: Ensure we have at least a primary model
        if not primary_model_id:
            primary_model_id = DEFAULT_FALLBACK_MODEL
            reasons.append(f"No ranked models available, using default: {primary_model_id}")

        # Step 7: Set fallback model
        fallback_model_id = DEFAULT_FALLBACK_MODEL
        if fallback_model_id == primary_model_id:
            # Use a different fallback if primary is already the default
            fallback_model_id = "claude-haiku-4-5-20251001"

        # Log the selection
        selection_reason = "; ".join(reasons)
        logger.info(
            f"{log_prefix} MODEL_SELECTION: primary={primary_model_id}, "
            f"secondary={secondary_model_id}, fallback={fallback_model_id}. "
            f"Reason: {selection_reason}"
        )

        return ModelSelectionResult(
            primary_model_id=primary_model_id,
            secondary_model_id=secondary_model_id,
            fallback_model_id=fallback_model_id,
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
) -> Tuple[str, Optional[str], str]:
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
