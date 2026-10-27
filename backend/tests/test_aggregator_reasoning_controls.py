# contract-test-file: infrastructure
"""Verified model/server effort mappings and aggregator HTTP wire contracts."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml

from backend.apps.ai.utils.model_reasoning import resolve_reasoning_parameters


def model(provider, identity):
    catalog = yaml.safe_load((Path(__file__).parents[1] / f"providers/{provider}.yml").read_text())
    return next(entry for entry in catalog["models"] if entry["id"] == identity)


@pytest.mark.parametrize("provider,identity,host,level,native", [
    ("deepseek", "deepseek-v4-pro", "together", "MEDIUM", "high"),
    ("deepseek", "deepseek-v4-pro", "together", "EXTRA_HIGH", "max"),
    ("deepseek", "deepseek-v4-pro", "openrouter", "LOW", "high"),
    ("deepseek", "deepseek-v4-flash", "openrouter", "EXTRA_HIGH", "xhigh"),
    ("zai", "zai-glm-5.2", "openrouter", "MEDIUM", "high"),
    ("mistral", "mistral-small-latest", "openrouter", "EXTRA_HIGH", "high"),
    ("mistral", "mistral-medium-latest", "openrouter", "LOW", "high"),
    ("moonshot", "kimi-k3", "together", "LOW", "low"),
    ("moonshot", "kimi-k3", "together", "MEDIUM", "high"),
    ("moonshot", "kimi-k3", "together", "EXTRA_HIGH", "max"),
    ("openai", "gpt-oss-120b", "openrouter", "EXTRA_HIGH", "high"),
])
def test_model_specific_aggregator_controls(provider, identity, host, level, native):
    assert resolve_reasoning_parameters(model(provider, identity), host, level) == {"reasoning_effort": native}


@pytest.mark.parametrize("provider,identity,host", [
    ("moonshot", "kimi-k2.6", "together"),
    ("moonshot", "kimi-k2.6", "openrouter"),
    ("moonshot", "kimi-k2.7-code", "openrouter"),
    ("zai", "zai-glm-4.7", "openrouter"),
])
def test_no_effort_selection_is_invented_for_fixed_reasoning(provider, identity, host):
    assert resolve_reasoning_parameters(model(provider, identity), host, "EXTRA_HIGH") == {}


@pytest.mark.parametrize("host,effort", [("openrouter", None), ("openrouter", "xhigh"), ("together", None), ("together", "max")])
def test_native_aggregator_http_payload(monkeypatch, host, effort):
    from backend.apps.ai.llm_providers import openrouter_client, together_client
    client = openrouter_client if host == "openrouter" else together_client
    invoke = client.invoke_openrouter_api if host == "openrouter" else client.invoke_together_api
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1, "model": "test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    original = httpx.AsyncClient
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    asyncio.run(invoke(task_id="test", model_id="test", messages=[{"role": "user", "content": "hello"}],
                       api_key="placeholder", reasoning_effort=effort))
    payload = captured[0]
    assert payload.get("reasoning") == ({"effort": effort} if host == "openrouter" and effort else None)
    assert payload.get("reasoning_effort") == (effort if host == "together" else None)


@pytest.mark.parametrize("host", ["openrouter", "together"])
def test_wrapper_preserves_optional_effort(monkeypatch, host):
    from backend.apps.ai.llm_providers import openai_openrouter, together_wrapper
    wrapper = openai_openrouter if host == "openrouter" else together_wrapper
    invoke = wrapper.invoke_openrouter_chat_completions if host == "openrouter" else wrapper.invoke_together_chat_completions
    monkeypatch.setattr(wrapper, f"_get_{host}_api_key", AsyncMock(return_value="placeholder"))
    native = AsyncMock(return_value="answer")
    monkeypatch.setattr(wrapper, f"invoke_{host}_api", native)
    asyncio.run(invoke(task_id="test", model_id="test", messages=[], secrets_manager=object(), reasoning_effort="high"))
    assert native.await_args.kwargs["reasoning_effort"] == "high"
