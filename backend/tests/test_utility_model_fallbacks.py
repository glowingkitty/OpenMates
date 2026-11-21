# contract-test-file: infrastructure
"""Utility routing and metadata can recover independently of Google."""

import pytest

from backend.apps.ai.utils import llm_utils
from backend.apps.ai.utils.utility_model_fallbacks import utility_model_fallbacks
from backend.apps.ai.llm_providers.openai_shared import (
    ParsedOpenAIToolCall,
    UnifiedOpenAIResponse,
)


def test_google_recovery_keeps_vertex_without_adding_a_fourth_attempt():
    model = "google/gemini-3.5-flash-lite"
    assert utility_model_fallbacks(model, [model]) == [
        "inception/mercury-3", model,
    ]


def test_non_google_primary_retains_server_then_deepseek_recovery():
    assert utility_model_fallbacks(
        "groq/openai/gpt-oss-20b", ["openrouter/openai/gpt-oss-20b"]
    ) == [
        "openrouter/openai/gpt-oss-20b", "deepseek/deepseek-v4-flash",
    ]

def test_mistral_is_never_an_automatic_utility_recovery_route():
    for model in ("google/gemini-3.5-flash-lite", "groq/openai/gpt-oss-20b"):
        assert not any("mistral" in route for route in utility_model_fallbacks(model, [model]))


@pytest.mark.anyio
@pytest.mark.parametrize("purpose", ["preprocess", "postprocess", "translation"])
@pytest.mark.parametrize("independent_unavailable", [False, True])
async def test_utility_chain_recovers_through_mercury_or_vertex(monkeypatch, purpose, independent_unavailable):
    calls = []

    async def unavailable_google(**kwargs):
        calls.append("google")
        return UnifiedOpenAIResponse(
            task_id="utility-outage", model_id=kwargs["model_id"], success=False,
            error_message="503 Service Unavailable",
        )

    async def available_mercury(**kwargs):
        calls.append("mercury")
        if independent_unavailable:
            return UnifiedOpenAIResponse(
                task_id="utility-outage", model_id=kwargs["model_id"], success=False,
                error_message="503 Service Unavailable",
            )
        return successful_response(kwargs["model_id"])

    async def available_vertex(**kwargs):
        calls.append("vertex")
        return successful_response(kwargs["model_id"])

    def successful_response(model_id):
        return UnifiedOpenAIResponse(
            task_id="utility-outage", model_id=model_id, success=True,
            tool_calls_made=[ParsedOpenAIToolCall(
                tool_call_id="decision", function_name="expected_tool",
                function_arguments_raw='{"value":"ok"}',
                function_arguments_parsed={"value": "ok"},
            )],
        )

    class NoHealthCache:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "CacheService", NoHealthCache)
    monkeypatch.setattr(
        llm_utils, "resolve_default_server_from_provider_config",
        lambda _model: ("google_ai_studio", "google_ai_studio/gemini-3.5-flash-lite"),
    )
    monkeypatch.setitem(llm_utils.PROVIDER_CLIENT_REGISTRY, "inception", available_mercury)
    monkeypatch.setitem(llm_utils.PROVIDER_CLIENT_REGISTRY, "google", available_vertex)
    monkeypatch.setattr(
        llm_utils, "_get_provider_client",
        lambda prefix: {
            "inception": available_mercury,
            "google": available_vertex,
        }.get(prefix, unavailable_google),
    )
    model = "google/gemini-3.5-flash-lite"
    result = await llm_utils.call_preprocessing_llm(
        task_id="utility-outage", model_id=model,
        message_history=[{"role": "user", "content": "Classify this request."}],
        tool_definition={"type": "function", "function": {
            "name": "expected_tool", "description": "Return a decision.",
            "parameters": {"type": "object", "properties": {"value": {"type": "string"}}},
        }},
        fallback_models=utility_model_fallbacks(model, [model]),
        observability_purpose=purpose,
    )
    assert result.arguments == {"value": "ok"}
    assert result.error_message is None
    expected_calls = ["google", "mercury", "vertex"] if independent_unavailable else ["google", "mercury"]
    assert calls == expected_calls
