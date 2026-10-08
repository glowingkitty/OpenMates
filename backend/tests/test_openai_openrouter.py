# backend/tests/test_openai_openrouter.py
#
# Unit coverage for OpenRouter routing contracts used by provider YAML models.
# These tests avoid live provider calls and secrets; live smoke tests remain
# manual/session evidence because they consume paid OpenRouter credits.
# They guard model-id transformation and OpenRouter-native namespace passthrough.

import asyncio
import json
import logging

import httpx
import pytest

from backend.apps.ai.llm_providers import openai_openrouter, openrouter_client
from backend.apps.ai.utils import llm_utils


class _DummyConfigManager:
    def __init__(self, provider_configs):
        self._provider_configs = provider_configs

    def get_provider_config(self, provider_id):
        return self._provider_configs.get(provider_id)


# contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
def test_zai_glm_52_resolves_to_openrouter_model(monkeypatch):
    monkeypatch.setattr(
        llm_utils,
        "config_manager",
        _DummyConfigManager(
            {
                "zai": {
                    "models": [
                        {
                            "id": "zai-glm-5.2",
                            "default_server": "openrouter",
                            "servers": [
                                {
                                    "id": "openrouter",
                                    "model_id": "z-ai/glm-5.2",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
    )

    server_id, transformed_model_id = llm_utils.resolve_default_server_from_provider_config(
        "zai/zai-glm-5.2"
    )

    assert server_id == "openrouter"
    assert transformed_model_id == "openrouter/z-ai/glm-5.2"


# contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
def test_openrouter_native_namespace_without_config_is_passthrough(monkeypatch, caplog):
    monkeypatch.setattr(openai_openrouter, "config_manager", _DummyConfigManager({}))
    caplog.set_level(logging.WARNING)

    provider_overrides = openai_openrouter._get_provider_overrides_for_model("z-ai/glm-5.2")

    assert provider_overrides is None
    assert not caplog.records


@pytest.mark.parametrize("fallbacks, expected_models", [
    (None, None),
    (["deepseek/deepseek-v4-flash", "mistralai/mistral-small-2603", "deepseek/deepseek-v4-flash"],
     ["mistralai/mistral-small-2603", "deepseek/deepseek-v4-flash"]),
])
# contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
def test_openrouter_fallback_payload_is_opt_in_and_one_request(monkeypatch, fallbacks, expected_models):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "3"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        })

    client_type = httpx.AsyncClient
    monkeypatch.setattr(openrouter_client.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    response = asyncio.run(openrouter_client.invoke_openrouter_api(
        task_id="health_check", model_id="mistralai/mistral-small-2603",
        messages=[{"role": "user", "content": "1+2?"}], api_key="test-only",
        fallback_models=fallbacks, stream=False,
    ))

    assert response.success is True
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    if expected_models is None:
        assert payload["model"] == "mistralai/mistral-small-2603"
        assert "models" not in payload
    else:
        assert payload["models"] == expected_models
        assert "model" not in payload


# contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
def test_openrouter_wrapper_resolves_fallback_model_ids(monkeypatch):
    received = {}

    async def key(_secrets_manager):
        return "test-only"

    async def invoke(**kwargs):
        received.update(kwargs)
        return object()

    monkeypatch.setattr(openai_openrouter, "_get_openrouter_api_key", key)
    monkeypatch.setattr(openai_openrouter, "invoke_openrouter_api", invoke)
    monkeypatch.setattr(openai_openrouter, "config_manager", _DummyConfigManager({
        "deepseek": {"models": [{"id": "deepseek-v4-flash", "servers": [
            {"id": "openrouter", "model_id": "deepseek/deepseek-v4-flash"},
        ]}]},
    }))
    asyncio.run(openai_openrouter.invoke_openrouter_chat_completions(
        task_id="health_check", model_id="mistralai/mistral-small-2603",
        messages=[{"role": "user", "content": "1+2?"}], secrets_manager=object(),
        fallback_models=["deepseek/deepseek-v4-flash"],
    ))
    assert received["fallback_models"] == ["deepseek/deepseek-v4-flash"]
