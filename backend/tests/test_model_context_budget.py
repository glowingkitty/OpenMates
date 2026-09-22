"""Selected-model context and compression budget contracts."""

# contract-test-file: infrastructure

import pytest

from backend.apps.ai.processing.chat_compressor import (
    model_compression_threshold,
    model_context_window,
    model_history_token_budget,
)


class FakeConfigManager:
    def __init__(self, context: int, max_output: int = 64_000) -> None:
        self.context = context
        self.max_output = max_output

    def get_model_pricing(self, provider_id: str, model_id: str):
        assert (provider_id, model_id) == ("provider", "model")
        return {
            "costs": {"input_per_million_token": {"max_context": self.context}},
            "features": {"max_output_tokens": self.max_output},
        }


def test_model_aware_budgets_scale_without_using_jev_context() -> None:
    config_128k = FakeConfigManager(128_000)
    config_1m = FakeConfigManager(1_000_000)

    assert model_context_window("provider/model", config_128k) == 128_000
    assert model_compression_threshold("provider/model", config_1m) > model_compression_threshold(
        "provider/model", config_128k
    )
    assert model_history_token_budget(
        "provider/model",
        config_1m,
        system_prompt="system" * 100,
        tools=[{"function": {"name": "search", "description": "x" * 400}}],
    ) < 176_000
    # Provider metadata stays truthful; only the inference policy is capped.
    assert model_context_window("provider/model", config_1m) == 1_000_000


@pytest.mark.parametrize("context,threshold", [(1_048_576, 176_000), (200_000, 176_000), (128_000, 104_000)])
def test_context_ceiling_and_admin_overrides(context: int, threshold: int) -> None:
    config = FakeConfigManager(context)
    assert model_compression_threshold("provider/model", config) == threshold
    assert model_compression_threshold(
        "provider/model", config, threshold_override=900_000
    ) == threshold
    assert model_compression_threshold(
        "provider/model", config, threshold_override=3_000
    ) == 3_000


def test_fallback_and_growing_tool_results_stay_within_policy() -> None:
    for context, input_budget in [(1_048_576, 176_000), (128_000, 104_000)]:
        config = FakeConfigManager(context)
        # The same helper is called again for fallback models and tool iterations.
        budget = model_history_token_budget(
            "provider/model", config, system_prompt="x" * 60_000, tools=[]
        )
        assert budget == input_budget - 15_000
        larger_tools_budget = model_history_token_budget(
            "provider/model", config, system_prompt="x" * 60_000,
            tools=[{"description": "y" * 40_000}],
        )
        assert larger_tools_budget < budget - 10_000


def test_actual_prompt_and_tools_reduce_history_budget() -> None:
    config = FakeConfigManager(128_000, max_output=8_000)
    small = model_history_token_budget(
        "provider/model", config, system_prompt="short", tools=[]
    )
    large = model_history_token_budget(
        "provider/model",
        config,
        system_prompt="x" * 20_000,
        tools=[{"description": "y" * 20_000}],
    )
    assert large < small
