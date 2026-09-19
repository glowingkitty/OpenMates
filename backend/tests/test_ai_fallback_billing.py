# contract-test-file: infrastructure

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

try:
    from backend.apps.ai.llm_providers.anthropic_shared import AnthropicUsageMetadata
    from backend.apps.ai.tasks import stream_consumer
except ImportError:
    pytestmark = pytest.mark.skip(reason="Backend AI dependencies not installed")
    AnthropicUsageMetadata = None  # type: ignore[assignment, misc]
    stream_consumer = None  # type: ignore[assignment]


class FakeConfigManager:
    def __init__(self) -> None:
        self.provider_requests: list[str] = []
        self.model_requests: list[tuple[str, str]] = []

    def get_provider_config(self, provider_name: str) -> dict[str, Any]:
        self.provider_requests.append(provider_name)
        return {"id": provider_name}

    def get_model_pricing(self, provider_name: str, model_id: str) -> dict[str, Any]:
        self.model_requests.append((provider_name, model_id))
        per_input_credit = 100 if provider_name == "google" else 25
        per_output_credit = 10 if provider_name == "google" else 5
        return {
            "pricing": {
                "tokens": {
                    "input": {"per_credit_unit": per_input_credit},
                    "output": {"per_credit_unit": per_output_credit},
                }
            },
            "costs": {
                "input_per_million_token": {"price": 1.0},
                "output_per_million_token": {"price": 2.0},
            },
        }


def _usage() -> Any:
    return AnthropicUsageMetadata(
        input_tokens=50,
        output_tokens=5,
        total_tokens=55,
        user_input_tokens=15,
        system_prompt_tokens=35,
    )


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        chat_id="chat-1",
        message_id="message-1",
        api_key_name=None,
        is_external=False,
        is_anonymous=False,
    )


def _preprocessing() -> SimpleNamespace:
    return SimpleNamespace(
        selected_main_llm_model_id="google/gemini-primary",
        server_provider_name="Google",
        server_region="EU",
    )


def test_billing_uses_successful_fallback_model_instead_of_preprocessor_selection(monkeypatch) -> None:
    config_manager = FakeConfigManager()
    captured: dict[str, Any] = {}

    async def fake_charge(_task_id, _request_data, credits, usage_details, _log_prefix):
        captured.update({"credits": credits, "usage_details": usage_details})
        return {}

    monkeypatch.setattr(stream_consumer.celery_config, "config_manager", config_manager)
    monkeypatch.setattr(stream_consumer, "_charge_credits", fake_charge)

    result = asyncio.run(stream_consumer._handle_normal_billing(
        _usage(),
        _preprocessing(),
        _request(),
        "task-1",
        "[billing-test]",
        successful_model_id="anthropic/claude-fallback",
    ))

    assert config_manager.provider_requests == ["anthropic"]
    assert config_manager.model_requests == [("anthropic", "claude-fallback")]
    assert captured["usage_details"]["model_used"] == "anthropic/claude-fallback"
    assert captured["usage_details"]["server_provider"] is None
    assert captured["usage_details"]["server_region"] is None
    assert captured["usage_details"]["input_tokens"] == 50
    assert captured["usage_details"]["output_tokens"] == 5
    assert result["total_credits"] == captured["credits"] == 3


def test_billing_prices_each_successful_model_bucket_after_cross_provider_fallback(monkeypatch) -> None:
    config_manager = FakeConfigManager()
    captured: dict[str, Any] = {}

    async def fake_charge(_task_id, _request_data, credits, usage_details, _log_prefix):
        captured.update({"credits": credits, "usage_details": usage_details})
        return {}

    monkeypatch.setattr(stream_consumer.celery_config, "config_manager", config_manager)
    monkeypatch.setattr(stream_consumer, "_charge_credits", fake_charge)

    result = asyncio.run(stream_consumer._handle_normal_billing(
        _usage(),
        _preprocessing(),
        _request(),
        "task-2",
        "[billing-test]",
        cumulative_input_tokens=150,
        cumulative_output_tokens=15,
        tool_inference_iterations=1,
        successful_model_id="anthropic/claude-fallback",
        usage_by_model=[
            {
                "model_id": "google/gemini-primary",
                "input_tokens": 100,
                "output_tokens": 10,
                "user_input_tokens": 30,
                "system_prompt_tokens": 70,
            },
            {
                "model_id": "anthropic/claude-fallback",
                "input_tokens": 50,
                "output_tokens": 5,
                "user_input_tokens": 15,
                "system_prompt_tokens": 35,
            },
        ],
    ))

    assert config_manager.provider_requests == ["google", "anthropic"]
    assert config_manager.model_requests == [
        ("google", "gemini-primary"),
        ("anthropic", "claude-fallback"),
    ]
    assert captured["credits"] == 5
    assert captured["usage_details"]["model_used"] == "anthropic/claude-fallback"
    assert captured["usage_details"]["server_provider"] is None
    assert captured["usage_details"]["server_region"] is None
    assert captured["usage_details"]["input_tokens"] == 150
    assert captured["usage_details"]["output_tokens"] == 15
    assert captured["usage_details"]["user_input_tokens"] == 45
    assert captured["usage_details"]["system_prompt_tokens"] == 105
    assert captured["usage_details"]["tool_inference_iterations"] == 1
    assert result == {
        "prompt_tokens": 150,
        "completion_tokens": 15,
        "user_input_tokens": 45,
        "system_prompt_tokens": 105,
        "total_credits": 5,
    }


def test_cross_provider_billing_rounds_fractional_credits_once(monkeypatch) -> None:
    config_manager = FakeConfigManager()
    captured: dict[str, Any] = {}

    async def fake_charge(_task_id, _request_data, credits, usage_details, _log_prefix):
        captured.update({"credits": credits, "usage_details": usage_details})
        return {}

    monkeypatch.setattr(stream_consumer.celery_config, "config_manager", config_manager)
    monkeypatch.setattr(stream_consumer, "_charge_credits", fake_charge)

    asyncio.run(stream_consumer._handle_normal_billing(
        _usage(),
        _preprocessing(),
        _request(),
        "task-fractional",
        "[billing-test]",
        successful_model_id="anthropic/claude-fallback",
        usage_by_model=[
            {"model_id": "google/gemini-primary", "input_tokens": 1, "output_tokens": 0},
            {"model_id": "anthropic/claude-fallback", "input_tokens": 1, "output_tokens": 0},
        ],
    ))

    assert captured["credits"] == 1
    assert captured["usage_details"]["charged_cost_usd"] == pytest.approx(0.001)
