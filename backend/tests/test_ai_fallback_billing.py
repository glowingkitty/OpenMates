# contract-test-file: infrastructure

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from backend.shared.python_schemas.llm_usage import normalize_provider_usage
from backend.shared.python_utils.billing_utils import snapshot_model_tariff

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
        user_preferences={},
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
    assert {key: result[key] for key in (
        "prompt_tokens", "completion_tokens", "user_input_tokens", "system_prompt_tokens", "total_credits",
    )} == {
        "prompt_tokens": 150,
        "completion_tokens": 15,
        "user_input_tokens": 45,
        "system_prompt_tokens": 105,
        "total_credits": 5,
    }
    assert "llm_usage_breakdown" not in result  # Disabled tariffs remain a private shadow ledger.


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


@pytest.mark.parametrize("state,actual", [("settled", 13), ("settled", 1), ("pending", 0)])
def test_verified_cache_receipt_reconciles_to_actual_debit(monkeypatch, state, actual) -> None:
    config_manager = FakeConfigManager()
    tariff = {
        "pricing": {"tokens": {
            "input": {"per_credit_unit": 100}, "output": {"per_credit_unit": 10},
            "cache_read": {"per_credit_unit": 1000}, "cache_write": {"per_credit_unit": 80},
        }},
        "cache_pricing": {
            "enabled": True, "write_billing": "separate", "eligible_hosts": ["anthropic"],
            "status": "verified_for_activation", "source_url": "https://example.com/pricing",
            "reviewed_on": "2026-10-01", "expires_on": "2099-12-31",
        },
        "costs": {},
    }
    native = AnthropicUsageMetadata(
        input_tokens=100, output_tokens=100, total_tokens=1100,
        cache_read_input_tokens=800, cache_creation_input_tokens=100,
        cache_creation_5m_input_tokens=100, cache_creation_1h_input_tokens=0,
        inference_host="anthropic", provider_request_id="private-provider-request",
    )
    normalized = normalize_provider_usage(
        native, model_id="anthropic/claude-fallback", attempt_id="private-attempt",
        tariff_snapshot=snapshot_model_tariff(tariff),
    )
    captured = {}

    async def fake_charge(_task_id, _request_data, credits, usage_details, _log_prefix):
        captured.update(credits=credits, usage_details=usage_details)
        return {"total_credits": actual, "settlement_state": state, "requested_credits": credits}

    monkeypatch.setattr(stream_consumer.celery_config, "config_manager", config_manager)
    monkeypatch.setattr(stream_consumer, "_charge_credits", fake_charge)
    result = asyncio.run(stream_consumer._handle_normal_billing(
        native, _preprocessing(), _request(), "task-cache", "[cache-test]",
        successful_model_id="anthropic/claude-fallback", usage_by_model=[normalized.to_bucket()],
        billing_reservation_required=True,
    ))
    assert captured["usage_details"]["reservation_required"] is True
    assert config_manager.model_requests == []  # Frozen attempt price survives a reload.
    assert captured["credits"] == 13  # 1 + .8 + 1.25 + 10, floored once.
    saved_intent = captured["usage_details"]["llm_usage_breakdown"]
    receipt = result["llm_usage_breakdown"]
    assert saved_intent["credits_charged"] == 13  # Pending copy cannot mutate durable retry intent.
    assert result["total_credits"] == receipt["credits_charged"] == actual
    assert receipt["settlement_state"] == state
    assert receipt["input_tokens"] == 1000
    assert receipt["uncached_input_tokens"] == 100
    assert receipt["cache_read_input_tokens"] == 800
    assert receipt["cache_creation_input_tokens"] == 100
    assert receipt["entries"][0]["category_credits"]["cache_write"] == "1.25"
    assert "private-provider-request" not in str(receipt)
    assert "private-attempt" not in str(receipt)
    from decimal import Decimal
    assert Decimal(receipt["raw_credits"]) + Decimal(receipt["rounding_adjustment"]) == actual


@pytest.mark.parametrize("state,actual", [("committed", 2), ("retry_scheduled", 0)])
def test_internal_charge_response_reports_committed_debit(monkeypatch, state, actual) -> None:
    import httpx
    from backend.apps.ai.skills.ask_skill import AskSkillRequest

    async_client = httpx.AsyncClient

    def respond(request):
        return httpx.Response(200, json={
            "state": state, "charged_credits": actual, "requested_credits": 20,
        })

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(stream_consumer.httpx, "AsyncClient", lambda: async_client(transport=transport))
    request = AskSkillRequest(
        chat_id="disposable-chat", message_id="disposable-message", user_id="disposable-user",
        user_id_hash="disposable-user-hash", message_history=[],
    )
    result = asyncio.run(stream_consumer._charge_credits(
        "disposable-task", request, 20, {"input_tokens": 10, "output_tokens": 5}, "[charge-test]",
    ))
    assert result["total_credits"] == actual
    assert result["requested_credits"] == 20
    assert result["settlement_state"] == ("settled" if state == "committed" else "pending")
