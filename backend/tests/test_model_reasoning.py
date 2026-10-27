# contract-test-file: infrastructure
"""Declared model/server reasoning controls and native request propagation."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml

from backend.apps.ai.utils.model_reasoning import normalize_reasoning_level, resolve_reasoning_parameters


def _model(provider, model_id):
    catalog = yaml.safe_load((Path(__file__).parents[1] / f"providers/{provider}.yml").read_text())
    return next(model for model in catalog["models"] if model["id"] == model_id)


@pytest.mark.parametrize("value,expected", [(" low ", "LOW"), ("extra_high", "EXTRA_HIGH"),
    ("medium", "MEDIUM"), ("HIGH", "HIGH"), ("xhigh", None), (None, None), (1, None), ("MAX", None)])
def test_normalize(value, expected):
    assert normalize_reasoning_level(value) == expected


@pytest.mark.parametrize("provider,model,server,requested,expected", [
    ("google", "gemini-4-argon", "google_ai_studio", "EXTRA_HIGH", {"thinking_level": "HIGH"}),
    ("google", "gemini-3.8-flash", "google", "MEDIUM", {"thinking_level": "MEDIUM"}),
    ("google", "gemini-4-argon", "google", "HIGH", {}),
    ("inception", "mercury-3", "inception", "EXTRA_HIGH", {"reasoning_effort": "high"}),
    ("inception", "mercury-3", "inception", "MEDIUM", {"reasoning_effort": "medium"}),
    ("openai", "gpt-6.1-sol", "openai", "EXTRA_HIGH", {"reasoning_effort": "xhigh"}),
    ("openai", "gpt-6.1-sol", "openrouter", "EXTRA_HIGH", {}),
    ("mistral", "mistral-large-4", "mistral", "LOW", {"reasoning_effort": "high"}),
    ("zai", "zai-glm-5.3", "mistral", "MEDIUM", {"reasoning_effort": "high"}),
    ("zai", "zai-glm-5.3", "mistral", "LOW", {"reasoning_effort": "low"}),
])
def test_explicit_catalog_controls_and_ceiling(provider, model, server, requested, expected):
    assert resolve_reasoning_parameters(_model(provider, model), server, requested) == expected


@pytest.mark.parametrize("recommendation", [None, "", "invalid", "max", {}, 4])
def test_absent_or_invalid_recommendation_preserves_defaults(recommendation):
    assert resolve_reasoning_parameters(_model("inception", "mercury-3"), "inception", recommendation) == {}


@pytest.mark.parametrize("model", [None, {}, {"reasoning": True},
    {"reasoning": True, "servers": [{"id": "openai"}]},
    {"servers": [{"id": "openai", "reasoning_control": {"parameter": "anything", "levels": {"HIGH": "high"}}}]},
    {"servers": [{"id": "openai", "reasoning_control": {"parameter": "reasoning_effort", "levels": {"MAX": "max"}}}]},
])
def test_unknown_or_malformed_controls_do_not_enable_reasoning(model):
    assert resolve_reasoning_parameters(model, "openai", "HIGH") == {}


@pytest.mark.parametrize("fixed_scope", ["model", "server"])
def test_fixed_effort_variant_keeps_native_max(fixed_scope):
    model = {"reasoning_effort": "max", "servers": [{"id": "openai", "reasoning_control": {
        "parameter": "reasoning_effort", "levels": {"LOW": "low", "EXTRA_HIGH": "xhigh"}}}]}
    control = model if fixed_scope == "model" else model["servers"][0]
    control["reasoning_control"] = {**control.get("reasoning_control", {}), "fixed": True}
    assert resolve_reasoning_parameters(model, "openai", "LOW") == {}
    assert model["reasoning_effort"] == "max"


def test_mistral_wire_override_preserves_no_recommendation_default(monkeypatch):
    from backend.apps.ai.llm_providers import mistral_client
    model = _model("zai", "zai-glm-5.3")
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1, "model": "zai-glm-5-3",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    original = httpx.AsyncClient
    monkeypatch.setattr(mistral_client, "MISTRAL_API_KEY", "placeholder")
    monkeypatch.setattr(mistral_client.config_manager, "get_model_pricing", lambda *_: model)
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    for level in [None, "LOW", "MEDIUM", "HIGH", "EXTRA_HIGH"]:
        response = asyncio.run(mistral_client.invoke_mistral_chat_completions(
            "test", "zai-glm-5-3", [{"role": "user", "content": "hi"}],
            catalog_model_id="zai/" + model["id"], **resolve_reasoning_parameters(model, "mistral", level)))
        assert response.success
    assert [item["reasoning_effort"] for item in captured] == ["high", "low", "high", "high", "max"]


@pytest.mark.parametrize("native_context", [None, {}])
def test_openai_responses_override_reaches_wire(monkeypatch, native_context):
    from backend.apps.ai.llm_providers import openai_client, openai_responses
    model = _model("openai", "gpt-6.1-sol")
    invoke = AsyncMock(return_value=SimpleNamespace(success=True))
    monkeypatch.setattr(openai_client, "_openai_direct_client", object())
    monkeypatch.setattr(openai_client, "_get_openai_model_config", lambda *_: model)
    monkeypatch.setattr(openai_responses, "invoke_responses", invoke)
    for level in [None, "LOW", "EXTRA_HIGH"]:
        asyncio.run(openai_client._invoke_openai_direct_api(
            "test", model["id"], [{"role": "user", "content": "hi"}],
            native_cache_context=native_context,
            **resolve_reasoning_parameters(model, "openai", level)))
    assert [call.kwargs["reasoning_effort"] for call in invoke.await_args_list] == ["medium", "low", "xhigh"]


def test_openai_tool_protocol_guard_preserved():
    from backend.apps.ai.llm_providers import openai_client
    assert openai_client._get_openai_request_reasoning_effort(
        "gpt-6-luna", has_tools=True, requested_effort="xhigh") == "none"
