"""Direct Baseten transport, cache usage, tool streaming and safe failure contracts."""

# contract-test-file: infrastructure
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from backend.shared.providers.baseten import (
    BasetenClient,
    BasetenError,
    BasetenRequest,
    resolve_api_key,
)
from backend.apps.ai.llm_providers import baseten_client as adapter
from backend.apps.ai.llm_providers.openai_shared import (
    OpenAIUsageMetadata,
    ParsedOpenAIToolCall,
)
from backend.apps.ai.utils import llm_utils


def test_key_prefers_vault_and_rejects_import_sentinel(monkeypatch):
    monkeypatch.setenv("SECRET__BASETEN__API_KEY", "environment-test-key")

    class Secrets:
        async def get_secret(self, **kwargs):
            assert kwargs == {
                "secret_path": "kv/data/providers/baseten",
                "secret_key": "api_key",
            }
            return "vault-test-key"

    assert asyncio.run(resolve_api_key(Secrets())) == "vault-test-key"
    assert asyncio.run(resolve_api_key()) == "environment-test-key"
    monkeypatch.setenv("SECRET__BASETEN__API_KEY", "IMPORTED_TO_VAULT")
    with pytest.raises(BasetenError, match="not configured"):
        asyncio.run(resolve_api_key())


def test_direct_route_is_primary_and_fallback_preserves_exact_cache_tariff(monkeypatch):
    provider = yaml.safe_load(
        (Path(__file__).parents[1] / "providers/deepseek.yml").read_text()
    )
    model = next(m for m in provider["models"] if m["id"] == "deepseek-v4.1-flash")
    assert model["default_server"] == "baseten"
    assert [s["id"] for s in model["servers"]] == ["baseten", "openrouter"]
    assert model["servers"][0]["model_id"] == "deepseek-ai/DeepSeek-V4.1-Flash-1017"
    assert model["provider_overrides"]["only"] == ["baseten"]
    assert model["provider_overrides"]["allow_fallbacks"] is False
    assert set(model["cache_pricing"]["eligible_hosts"]) == {"baseten", "openrouter"}
    monkeypatch.setattr(
        llm_utils.config_manager, "get_provider_configs", lambda: {"deepseek": provider}
    )
    monkeypatch.setattr(
        llm_utils.config_manager, "_provider_configs", {"deepseek": provider}
    )
    assert (
        llm_utils._build_provider_registry()["baseten"]
        is adapter.invoke_baseten_chat_completions
    )


def _install_transport(monkeypatch, handler):
    client_type = BasetenClient
    monkeypatch.setattr(
        adapter,
        "BasetenClient",
        lambda key, **kw: client_type(
            key, transport=httpx.MockTransport(handler), **kw
        ),
    )
    monkeypatch.setenv("SECRET__BASETEN__API_KEY", "test-only")


def test_stream_tools_affinity_reasoning_and_usage_only_chunk(monkeypatch):
    captured = []

    def handler(request):
        captured.append(request)
        chunks = [
            {
                "id": "bt-request",
                "choices": [
                    {"delta": {"reasoning_content": "reasoning"}, "finish_reason": None}
                ],
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-a",
                                    "function": {
                                        "name": "read",
                                        "arguments": '{"path":',
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '"main.rs"}'}}
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 12,
                    "total_tokens": 112,
                    "prompt_tokens_details": {"cached_tokens": 80},
                    "completion_tokens_details": {"reasoning_tokens": 7},
                },
            },
        ]
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(x) + "\n\n" for x in chunks)
            + "data: [DONE]\n\n",
        )

    _install_transport(monkeypatch, handler)

    async def run():
        stream = await adapter.invoke_baseten_chat_completions(
            "task",
            "model",
            [{"role": "user", "content": "hello"}],
            stream=True,
            prompt_cache_key="opaque-root",
            reasoning_effort="medium",
        )
        return [x async for x in stream]

    values = asyncio.run(run())
    tool = next(x for x in values if isinstance(x, ParsedOpenAIToolCall))
    usage = next(x for x in values if isinstance(x, OpenAIUsageMetadata))
    assert tool.function_arguments_parsed == {"path": "main.rs"}
    assert tool.function_name == "read"
    assert values[0].content == "reasoning"
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_input_tokens) == (
        100,
        12,
        80,
    )
    assert usage.reasoning_tokens == 7 and usage.provider_request_id == "bt-request"
    assert usage.cache_creation_input_tokens is None
    payload = json.loads(captured[0].content)
    assert payload["reasoning_effort"] == "medium"
    assert payload["stream_options"] == {"include_usage": True}
    assert captured[0].headers["x-session-affinity"] == "opaque-root"
    assert captured[0].headers["authorization"] == "Bearer test-only"


def test_nonstream_usage_and_nonbillable_health(monkeypatch):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "model"}]})
        return httpx.Response(
            200,
            json={
                "id": "bt-answer",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 2,
                    "total_tokens": 102,
                    "prompt_tokens_details": {"cached_tokens": 80},
                },
            },
        )

    _install_transport(monkeypatch, handler)
    result = asyncio.run(
        adapter.invoke_baseten_chat_completions(
            "task", "model", [{"role": "user", "content": "hello"}]
        )
    )
    assert result.success and result.usage.cache_read_input_tokens == 80
    models = asyncio.run(adapter.BasetenClient("test").models())
    assert models == [{"id": "model"}]
    assert paths == ["/v1/chat/completions", "/v1/models"]


def test_http_error_never_exposes_private_provider_body():
    def handler(_):
        return httpx.Response(401, json={"error": "secret-api-key and private prompt"})

    client = BasetenClient("test", transport=httpx.MockTransport(handler))
    with pytest.raises(BasetenError, match="HTTP error 401") as error:
        asyncio.run(client.complete(BasetenRequest(model="model", messages=[])))
    assert "secret" not in str(error.value) and "private" not in str(error.value)


def test_rate_retry_is_bounded_and_honors_retry_after(monkeypatch):
    calls, delays = [], []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("backend.shared.providers.baseten.client.asyncio.sleep", sleep)

    def handler(_):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1000000"})

    with pytest.raises(BasetenError, match="HTTP error 429"):
        asyncio.run(
            BasetenClient("test", transport=httpx.MockTransport(handler)).complete(
                BasetenRequest(model="model", messages=[])
            )
        )
    assert len(calls) == 3 and delays == [10, 10]


def test_cancel_closes_stream_without_yielding_during_generator_exit():
    closed = []

    async def events(_):
        try:
            yield SimpleNamespace(
                id="request",
                choices=[{"delta": {"content": "hello"}}],
                usage={"prompt_tokens": 3},
            )
        finally:
            closed.append(True)

    client = SimpleNamespace(stream=events)

    async def run():
        stream = adapter._stream(client, BasetenRequest(model="m", messages=[]))
        assert await anext(stream) == "hello"
        await stream.aclose()

    asyncio.run(run())
    assert closed == [True]


def test_incurred_usage_survives_truncated_transport():
    async def events(_):
        yield SimpleNamespace(
            id="request",
            choices=[],
            usage={"prompt_tokens": 100, "completion_tokens": 12, "total_tokens": 112},
        )
        raise BasetenError("transport interrupted")

    async def run():
        stream = adapter._stream(
            SimpleNamespace(stream=events), BasetenRequest(model="m", messages=[])
        )
        usage = await anext(stream)
        assert isinstance(usage, OpenAIUsageMetadata) and usage.input_tokens == 100
        with pytest.raises(BasetenError, match="interrupted"):
            await anext(stream)

    asyncio.run(run())


@pytest.mark.parametrize("unavailable", ["missing_key", 403, 429, "transport"])
def test_direct_unavailability_falls_back_with_pinned_host_and_reported_cache_usage(
    monkeypatch,
    unavailable,
):
    from backend.apps.ai.llm_providers import openai_openrouter, openrouter_client

    provider = yaml.safe_load(
        (Path(__file__).parents[1] / "providers/deepseek.yml").read_text()
    )
    model = next(m for m in provider["models"] if m["id"] == "deepseek-v4.1-flash")
    monkeypatch.delenv("SECRET__BASETEN__API_KEY", raising=False)
    if unavailable != "missing_key":
        monkeypatch.setenv("SECRET__BASETEN__API_KEY", "test-only")
    monkeypatch.setattr(
        adapter,
        "BasetenClient",
        lambda key, **kw: BasetenClient(key, max_retries=0, **kw),
    )
    monkeypatch.setattr(
        llm_utils.config_manager,
        "get_provider_config",
        lambda p: provider if p == "deepseek" else None,
    )
    monkeypatch.setattr(
        llm_utils.config_manager, "get_provider_configs", lambda: {"deepseek": provider}
    )
    monkeypatch.setattr(
        llm_utils.config_manager,
        "get_model_pricing",
        lambda p, m, **kw: model if (p, m) == ("deepseek", model["id"]) else None,
    )

    async def key(_):
        return "test-only"

    monkeypatch.setattr(openai_openrouter, "_get_openrouter_api_key", key)
    clients = {
        "baseten": adapter.invoke_baseten_chat_completions,
        "openrouter": openai_openrouter.invoke_openrouter_chat_completions,
    }
    monkeypatch.setattr(llm_utils, "_get_provider_client", clients.get)
    captured = []

    def handle(request):
        if request.url.host == "inference.baseten.co":
            if unavailable == "transport":
                raise httpx.ConnectError("private network detail", request=request)
            assert unavailable in {403, 429}
            return httpx.Response(unavailable)
        captured.append(json.loads(request.content))
        events = [
            {
                "id": "gateway-fallback",
                "choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}],
            },
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 2,
                    "total_tokens": 102,
                    "prompt_tokens_details": {"cached_tokens": 80},
                },
            },
        ]
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(event) + "\n\n" for event in events)
            + "data: [DONE]\n\n",
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        openrouter_client.httpx,
        "AsyncClient",
        lambda **kw: original(**{**kw, "transport": httpx.MockTransport(handle)}),
    )

    async def run():
        return [
            chunk
            async for chunk in llm_utils.call_main_llm_stream(
                task_id="fallback-test",
                model_id="deepseek/deepseek-v4.1-flash",
                system_prompt="Answer briefly.",
                message_history=[{"role": "user", "content": "hello"}],
                temperature=0.2,
                secrets_manager=object(),
                prompt_cache_key="opaque-root",
                customer_cache_pricing_enabled=True,
            )
        ]

    chunks = asyncio.run(run())
    assert "OK" in chunks and len(captured) == 1
    assert captured[0]["model"] == "deepseek/deepseek-v4.1-flash-20261017"
    assert captured[0]["provider"] == {
        "only": ["baseten"],
        "allow_fallbacks": False,
        "require_parameters": True,
    }
    assert captured[0]["session_id"] == "opaque-root"
    usage = next(chunk for chunk in chunks if isinstance(chunk, OpenAIUsageMetadata))
    bucket = usage._normalized_llm_usage.to_bucket()
    assert bucket["model_id"] == "deepseek/deepseek-v4.1-flash"
    assert (
        bucket["inference_host"] == "openrouter"
        and bucket["cache_read_input_tokens"] == 80
    )

    from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown

    assert (
        build_model_usage_breakdown([bucket], lambda *_: model)["entries"][0][
            "billing_mode"
        ]
        == "cache_aware"
    )
