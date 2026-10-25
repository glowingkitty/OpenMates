"""Exercise real compatible HTTP adapters with provider-shaped usage events."""

# contract-test-file: infrastructure
import asyncio
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.apps.ai.llm_providers.openai_shared import (
    OpenAIUsageMetadata,
    merge_openai_usage,
    openai_usage_details,
)

PROVIDERS = ["openrouter", "together", "google_maas", "cerebras", "mistral"]


@pytest.mark.parametrize("host", PROVIDERS)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("cached", [None, 0, 80])
def test_adapters_preserve_reported_usage_and_usage_only_terminal_event(
    monkeypatch, host, stream, cached
):
    module = importlib.import_module(f"backend.apps.ai.llm_providers.{host}_client")
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 12,
        "total_tokens": 112,
        "completion_tokens_details": {"reasoning_tokens": 7},
    }
    if cached is not None:
        usage["prompt_tokens_details"] = {
            "cached_tokens": cached,
            "cache_write_tokens": 5,
        }
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        if not stream:
            return httpx.Response(
                200,
                json={
                    "id": "request-cache-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "OK"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": usage,
                },
            )
        chunks = [
            {
                "id": "request-cache-test",
                "choices": [{"delta": {"content": "OK"}, "finish_reason": None}],
                "usage": None,
            },
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": None},
            {"choices": [], "usage": usage},
            # Cumulative repeated metadata must replace, never add.
            {"choices": [], "usage": {"completion_tokens": 12}},
        ]
        body = (
            "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(
        module,
        "calculate_token_breakdown",
        lambda *a, **kw: {"user_input_tokens": 10, "system_prompt_tokens": 90},
    )
    kwargs = {
        "task_id": "task-cache",
        "model_id": "test-model",
        "payload": {
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
        "headers": {},
    }
    if host == "google_maas":
        kwargs["api_url"] = "https://example.test/v1/chat/completions"

    async def run():
        if host == "mistral":
            monkeypatch.setattr(module, "MISTRAL_API_KEY", "test-only")
            monkeypatch.setattr(
                module, "_get_mistral_reasoning_effort", lambda *a: None
            )
            result = await module.invoke_mistral_chat_completions(
                "task-cache", "test-model", kwargs["payload"]["messages"], stream=stream
            )
            if stream:
                values = [chunk async for chunk in result]
                assert "OK" in values
                usage_result = next(
                    chunk for chunk in values if isinstance(chunk, module.MistralUsage)
                )
            else:
                assert result.success
                usage_result = result.usage
            return SimpleNamespace(
                input_tokens=usage_result.prompt_tokens,
                output_tokens=usage_result.completion_tokens,
                **usage_result.model_dump(),
            )
        if stream:
            fn = getattr(module, f"_stream_{host}_response")
            values = [chunk async for chunk in fn(**kwargs)]
            assert "OK" in values
            return next(
                chunk for chunk in values if isinstance(chunk, OpenAIUsageMetadata)
            )
        return (await getattr(module, f"_send_{host}_request")(**kwargs)).usage

    result = asyncio.run(run())
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (
        100,
        12,
        112,
    )
    assert result.cache_read_input_tokens == cached
    assert result.cache_creation_input_tokens == (5 if cached is not None else None)
    assert result.reasoning_tokens == 7
    assert result.inference_host == host
    assert result.provider_request_id == "request-cache-test"
    assert result.usage_source == "provider_reported"
    if stream and host not in {"cerebras", "mistral"}:
        assert captured[0]["stream_options"] == {"include_usage": True}


def test_sdk_nested_objects_and_unknown_usage_remain_distinct():
    raw = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=12,
        total_tokens=112,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=7),
    )
    details = openai_usage_details(raw, inference_host="groq")
    assert details["cache_read_input_tokens"] == 0
    assert details["cache_creation_input_tokens"] is None
    assert details["reasoning_tokens"] == 7
    assert details["usage_source"] == "provider_reported"
    assert (
        openai_usage_details(None, inference_host="local")["usage_source"]
        == "estimated"
    )
    merged = {}
    merge_openai_usage(merged, raw)
    merge_openai_usage(merged, {"completion_tokens": 13})
    assert merged["prompt_tokens"] == 100
    assert merged["completion_tokens"] == 13
    assert (
        openai_usage_details(merged, inference_host="groq")["cache_read_input_tokens"]
        == 0
    )


@pytest.mark.parametrize("host", ["groq", "local"])
@pytest.mark.parametrize("stream", [False, True])
def test_sdk_adapters_keep_cache_usage_on_empty_choices(monkeypatch, host, stream):
    module = importlib.import_module(
        "backend.apps.ai.llm_providers."
        + ("groq_client" if host == "groq" else "local_openai_compatible")
    )
    raw = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=12,
        total_tokens=112,
        prompt_tokens_details=SimpleNamespace(cached_tokens=80),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=7),
    )
    final = SimpleNamespace(id="sdk-final", choices=[], usage=raw)
    choice = SimpleNamespace(
        delta=SimpleNamespace(content="OK", tool_calls=None), finish_reason="stop"
    )

    async def events():
        yield SimpleNamespace(id="sdk-final", choices=[choice], usage=None)
        yield final

    async def create(**kwargs):
        if host == "local" and kwargs.get("stream"):
            assert kwargs["stream_options"] == {"include_usage": True}
        if kwargs.get("stream"):
            return events()
        return SimpleNamespace(
            id="sdk-final",
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="OK", tool_calls=None))
            ],
            usage=raw,
        )

    async def close():
        pass

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close
    )
    monkeypatch.setattr(
        module,
        "calculate_token_breakdown",
        lambda *a, **kw: {"user_input_tokens": 10, "system_prompt_tokens": 90},
    )
    if host == "groq":
        monkeypatch.setattr(module, "_groq_api_key", "test-only")
        monkeypatch.setattr(module, "AsyncGroq", lambda **kw: client)
        fn = module._invoke_groq_direct_api
        extra = {}
    else:
        monkeypatch.setattr(module, "AsyncOpenAI", lambda **kw: client)
        monkeypatch.setattr(
            module,
            "_resolve_server_settings",
            lambda *a: {
                "api_key": "test",
                "base_url": "https://local.test",
                "supports_tools": True,
            },
        )
        fn = module._invoke_local_openai_compatible_chat_completions
        extra = {"server_id": "local"}

    async def run():
        result = await fn(
            task_id="task",
            model_id="model",
            messages=[{"role": "user", "content": "hello"}],
            stream=stream,
            **extra,
        )
        if stream:
            values = [x async for x in result]
            assert "OK" in values
            return next(x for x in values if isinstance(x, OpenAIUsageMetadata))
        return result.usage

    result = asyncio.run(run())
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (
        100,
        12,
        112,
    )
    assert result.cache_read_input_tokens == 80
    assert result.cache_creation_input_tokens is None
    assert result.reasoning_tokens == 7
    assert result.inference_host == host
    assert result.provider_request_id == "sdk-final"


def test_together_top_level_cache_usage_alias():
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 12,
        "total_tokens": 112,
        "cached_tokens": 80,
    }
    assert (
        openai_usage_details(usage, inference_host="together")[
            "cache_read_input_tokens"
        ]
        == 80
    )
    merge_openai_usage(usage, {"prompt_tokens_details": {"cached_tokens": 0}})
    assert (
        openai_usage_details(usage, inference_host="together")[
            "cache_read_input_tokens"
        ]
        == 0
    )


@pytest.mark.parametrize("host", ["together", "cerebras"])
def test_documented_routing_hint_reaches_transport(monkeypatch, host):
    module = importlib.import_module(f"backend.apps.ai.llm_providers.{host}_client")
    captured = {}

    async def send(task_id, model_id, payload, headers):
        captured.update(payload)
        return "sent"

    monkeypatch.setattr(module, f"_send_{host}_request", send)
    result = asyncio.run(
        getattr(module, f"invoke_{host}_api")(
            "task",
            "model",
            [{"role": "user", "content": "hello"}],
            api_key="test",
            prompt_cache_key="opaque-root",
        )
    )
    assert result == "sent" and captured["prompt_cache_key"] == "opaque-root"
