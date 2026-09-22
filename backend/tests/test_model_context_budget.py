"""Selected-model context and compression budget contracts."""

# contract-test-file: infrastructure

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
    ) > 900_000


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
