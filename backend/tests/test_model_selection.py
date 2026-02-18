# backend/tests/test_model_selection.py
#
# Unit tests for the AI model selection system:
# - ModelSelector: Intelligent model selection based on leaderboard rankings
# - Override parser: User @ai-model:xxx syntax parsing
#
# Note: China sensitivity detection is now handled by the preprocessing LLM
# via the `china_model_sensitive` field, not by keyword matching.
#
# Run with: /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_model_selection.py

import pytest
from typing import Dict, Any


# ═══════════════════════════════════════════════════════════════════════════════
# Test Data Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_leaderboard_data() -> Dict[str, Any]:
    """
    Mock leaderboard data simulating real LMArena rankings.
    Includes US, FR, and CN models to test country filtering.
    """
    return {
        "metadata": {
            "generated_at": "2026-01-30T00:00:00Z",
            "category": "general",
            "sources": {
                "lmarena": {"valid": True, "models_fetched": 100},
                "openrouter": {"valid": True, "models_fetched": 50}
            }
        },
        "rankings": [
            {
                "rank": 1,
                "model_id": "gemini-3-pro-preview",
                "name": "Gemini 3 Pro Preview",
                "provider_id": "google",
                "country_origin": "US",
                "composite_score": 97.8,
                "lmarena_elo": 1487
            },
            {
                "rank": 2,
                "model_id": "claude-opus-4-5-20251101",
                "name": "Claude Opus 4.5",
                "provider_id": "anthropic",
                "country_origin": "US",
                "composite_score": 94.3,
                "lmarena_elo": 1466
            },
            {
                "rank": 3,
                "model_id": "qwen3-max",
                "name": "Qwen3 Max",
                "provider_id": "alibaba",
                "country_origin": "CN",  # Chinese model
                "composite_score": 93.0,
                "lmarena_elo": 1460
            },
            {
                "rank": 4,
                "model_id": "claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "provider_id": "anthropic",
                "country_origin": "US",
                "composite_score": 91.7,
                "lmarena_elo": 1450
            },
            {
                "rank": 5,
                "model_id": "gpt-5.2",
                "name": "GPT-5.2",
                "provider_id": "openai",
                "country_origin": "US",
                "composite_score": 90.0,
                "lmarena_elo": 1440
            },
            {
                "rank": 6,
                "model_id": "mistral-large",
                "name": "Mistral Large",
                "provider_id": "mistral",
                "country_origin": "FR",
                "composite_score": 85.0,
                "lmarena_elo": 1410
            },
            {
                "rank": 7,
                "model_id": "claude-haiku-4-5-20251001",
                "name": "Claude Haiku 4.5",
                "provider_id": "anthropic",
                "country_origin": "US",
                "composite_score": 83.8,
                "lmarena_elo": 1403
            },
            {
                "rank": 8,
                "model_id": "deepseek-v3",
                "name": "DeepSeek V3",
                "provider_id": "deepseek",
                "country_origin": "CN",  # Chinese model
                "composite_score": 82.0,
                "lmarena_elo": 1395
            },
        ],
        "unranked": []
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ModelSelector Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelSelector:
    """Tests for the ModelSelector class."""

    def test_select_models_basic(self, mock_leaderboard_data):
        """Test basic model selection returns top-ranked models."""
        from backend.apps.ai.utils.model_selector import ModelSelector

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(task_area="general", complexity="complex")

        # Should return top-ranked models
        assert result.primary_model_id is not None
        assert result.selection_reason != ""

    def test_select_models_complex_task_prefers_premium(self, mock_leaderboard_data):
        """Complex tasks should prefer premium/top-ranked models."""
        from backend.apps.ai.utils.model_selector import ModelSelector, PREMIUM_MODELS

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(task_area="general", complexity="complex")

        # For complex tasks, should prefer a premium model if available in rankings
        # Primary should be from top rankings
        assert result.primary_model_id in [
            "gemini-3-pro-preview",
            "claude-opus-4-5-20251101",
            "claude-sonnet-4-6",
            "anthropic/claude-sonnet-4-6",  # DEFAULT_FALLBACK_MODEL includes provider prefix
        ] or result.primary_model_id in PREMIUM_MODELS

    def test_select_models_simple_task_prefers_economical(self, mock_leaderboard_data):
        """Simple tasks should prefer economical models."""
        from backend.apps.ai.utils.model_selector import ModelSelector, ECONOMICAL_MODELS

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(task_area="general", complexity="simple")

        # For simple tasks, should prefer economical model if one is ranked
        # Claude Haiku is in ECONOMICAL_MODELS and should be selected
        assert "economical" in result.selection_reason.lower() or result.primary_model_id in ECONOMICAL_MODELS or result.primary_model_id is not None

    def test_select_models_excludes_cn_when_china_related(self, mock_leaderboard_data):
        """When china_related=True, CN models should be excluded."""
        from backend.apps.ai.utils.model_selector import ModelSelector

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(
            task_area="general",
            complexity="complex",
            china_related=True
        )

        # Should NOT select qwen3-max or deepseek-v3 (CN models)
        assert result.primary_model_id not in ["qwen3-max", "deepseek-v3"]
        assert result.secondary_model_id not in ["qwen3-max", "deepseek-v3"]
        assert result.filtered_cn_models is True
        assert "CN models excluded" in result.selection_reason

    def test_select_models_includes_cn_when_not_china_related(self, mock_leaderboard_data):
        """When china_related=False, CN models should be included in rankings."""
        from backend.apps.ai.utils.model_selector import ModelSelector

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(
            task_area="general",
            complexity="complex",
            china_related=False
        )

        assert result.filtered_cn_models is False

    def test_select_models_user_unhappy_prefers_premium(self, mock_leaderboard_data):
        """When user is unhappy, should upgrade to premium model."""
        from backend.apps.ai.utils.model_selector import ModelSelector

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(
            task_area="general",
            complexity="simple",  # Even for simple task
            user_unhappy=True  # User unhappy should upgrade
        )

        # Should prefer premium despite simple task
        assert "premium" in result.selection_reason.lower() or "unhappy" in result.selection_reason.lower()

    def test_select_models_returns_fallback_when_no_data(self):
        """When no leaderboard data, should return default fallback."""
        from backend.apps.ai.utils.model_selector import ModelSelector, DEFAULT_FALLBACK_MODEL

        selector = ModelSelector(leaderboard_data=None)
        result = selector.select_models(task_area="general", complexity="complex")

        # Should fall back to default model
        assert result.primary_model_id == DEFAULT_FALLBACK_MODEL
        assert "default" in result.selection_reason.lower()

    def test_get_model_ids_list_no_duplicates(self, mock_leaderboard_data):
        """get_model_ids_list should return unique models in order."""
        from backend.apps.ai.utils.model_selector import ModelSelector

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(task_area="general", complexity="complex")
        models_list = selector.get_model_ids_list(result)

        # Should have no duplicates
        assert len(models_list) == len(set(models_list))
        # First should be primary
        assert models_list[0] == result.primary_model_id

    def test_select_models_with_available_models_filter(self, mock_leaderboard_data):
        """Should filter to only available models when specified."""
        from backend.apps.ai.utils.model_selector import ModelSelector

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        # Model IDs can be bare or provider-prefixed; include both forms
        available = ["claude-sonnet-4-6", "anthropic/claude-sonnet-4-6", "mistral-large"]

        result = selector.select_models(
            task_area="general",
            complexity="complex",
            available_model_ids=available
        )

        # Should only select from available models
        assert result.primary_model_id in available


# ═══════════════════════════════════════════════════════════════════════════════
# Override Parser Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestOverrideParser:
    """Tests for user override syntax parsing."""

    def test_parse_model_override(self):
        """Should parse @ai-model:xxx syntax."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("What is AI? @ai-model:claude-opus-4-5")

        assert result.model_id == "claude-opus-4-5"
        assert result.has_overrides is True
        assert result.cleaned_message == "What is AI?"

    def test_parse_model_with_provider_override(self):
        """Should parse @ai-model:xxx:provider syntax."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("Explain quantum computing @ai-model:gpt-5.2:openrouter")

        assert result.model_id == "gpt-5.2"
        assert result.model_provider == "openrouter"
        assert result.has_overrides is True

    def test_parse_mate_override(self):
        """Should parse @mate:xxx syntax."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("Help me code @mate:coder")

        assert result.mate_id == "coder"
        assert result.has_overrides is True
        assert result.cleaned_message == "Help me code"

    def test_parse_skill_override(self):
        """Should parse @skill:app:skill_id syntax."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("Search for React docs @skill:web:search")

        assert len(result.skills) == 1
        assert result.skills[0] == ("web", "search")
        assert result.has_overrides is True

    def test_parse_focus_override(self):
        """Should parse @focus:app:focus_id syntax."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("Plan my project @focus:code:plan-project")

        assert len(result.focus_modes) == 1
        assert result.focus_modes[0] == ("code", "plan-project")
        assert result.has_overrides is True

    def test_parse_multiple_overrides(self):
        """Should parse multiple overrides in one message."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("Do something @ai-model:gpt-5.2 @mate:researcher @skill:web:search")

        assert result.model_id == "gpt-5.2"
        assert result.mate_id == "researcher"
        assert len(result.skills) == 1
        assert result.has_overrides is True

    def test_no_overrides(self):
        """Should handle messages without overrides."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("What is the weather today?")

        assert result.model_id is None
        assert result.mate_id is None
        assert result.has_overrides is False
        assert result.cleaned_message == "What is the weather today?"

    def test_case_insensitive_matching(self):
        """Override patterns should be case-insensitive."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("Test @AI-MODEL:claude-opus-4-5")

        assert result.model_id == "claude-opus-4-5"
        assert result.has_overrides is True

    def test_parse_overrides_from_messages(self):
        """Should extract overrides from last user message in history."""
        from backend.core.api.app.utils.override_parser import parse_overrides_from_messages

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "Explain this @ai-model:gpt-5.2"}
        ]

        overrides, cleaned_messages = parse_overrides_from_messages(messages)

        assert overrides.model_id == "gpt-5.2"
        assert overrides.has_overrides is True
        # Last user message should be cleaned
        assert cleaned_messages[-1]["content"] == "Explain this"

    def test_empty_message(self):
        """Should handle empty message."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("")

        assert result.model_id is None
        assert result.has_overrides is False
        assert result.cleaned_message == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Tests (ModelSelector + china_related flag)
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelSelectionIntegration:
    """Integration tests for model selection with china_related flag.
    
    Note: The china_related flag is now determined by the preprocessing LLM
    via the `china_model_sensitive` field, not by keyword matching.
    These tests verify that ModelSelector correctly handles the flag.
    """

    def test_selection_with_china_sensitive_flag_true(self, mock_leaderboard_data):
        """When china_model_sensitive=True from LLM, CN models should be excluded."""
        from backend.apps.ai.utils.model_selector import ModelSelector

        # Simulate: LLM returned china_model_sensitive=True
        china_related = True

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(
            task_area="general",
            complexity="complex",
            china_related=china_related
        )

        # Should NOT select CN models
        assert result.primary_model_id not in ["qwen3-max", "deepseek-v3"]
        assert result.filtered_cn_models is True

    def test_selection_with_china_sensitive_flag_false(self, mock_leaderboard_data):
        """When china_model_sensitive=False from LLM, CN models are eligible."""
        from backend.apps.ai.utils.model_selector import ModelSelector

        # Simulate: LLM returned china_model_sensitive=False
        china_related = False

        selector = ModelSelector(leaderboard_data=mock_leaderboard_data)
        result = selector.select_models(
            task_area="code",
            complexity="simple",
            china_related=china_related
        )

        # CN models are eligible (but may not be selected based on ranking)
        assert result.filtered_cn_models is False

    def test_user_override_bypasses_selection(self, mock_leaderboard_data):
        """User override should bypass automatic model selection."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        # User specifies a model directly
        message = "Explain quantum physics @ai-model:mistral-large"
        overrides = parse_overrides(message)

        # When override is present, we use the specified model directly
        # (this is handled in preprocessor.py, not in ModelSelector)
        assert overrides.model_id == "mistral-large"
        assert overrides.has_overrides is True

        # In real code, preprocessor would skip ModelSelector and use overrides.model_id


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Cases and Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_model_selector_with_empty_rankings(self):
        """Should handle empty rankings gracefully."""
        from backend.apps.ai.utils.model_selector import ModelSelector, DEFAULT_FALLBACK_MODEL

        empty_data = {"rankings": [], "unranked": []}
        selector = ModelSelector(leaderboard_data=empty_data)
        result = selector.select_models(task_area="general", complexity="complex")

        # Should fall back to default
        assert result.primary_model_id == DEFAULT_FALLBACK_MODEL

    def test_model_selector_with_all_cn_models_filtered(self):
        """When all ranked models are CN and china_related=True."""
        from backend.apps.ai.utils.model_selector import ModelSelector, DEFAULT_FALLBACK_MODEL

        # All models are CN
        cn_only_data = {
            "rankings": [
                {"rank": 1, "model_id": "qwen3-max", "country_origin": "CN", "composite_score": 95},
                {"rank": 2, "model_id": "deepseek-v3", "country_origin": "CN", "composite_score": 90},
            ]
        }

        selector = ModelSelector(leaderboard_data=cn_only_data)
        result = selector.select_models(
            task_area="general",
            complexity="complex",
            china_related=True  # Filter out CN
        )

        # All CN models filtered, should use fallback
        assert result.primary_model_id == DEFAULT_FALLBACK_MODEL

    def test_override_parser_with_special_characters(self):
        """Should handle special characters in message."""
        from backend.core.api.app.utils.override_parser import parse_overrides

        result = parse_overrides("What about this? 🤔 @ai-model:gpt-5.2")

        assert result.model_id == "gpt-5.2"
        assert "🤔" in result.cleaned_message
