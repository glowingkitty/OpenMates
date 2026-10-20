# contract-test-file: infrastructure
"""Inception transport and application contract without paid inference."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.shared.providers.inception import InceptionClient, InceptionError, InceptionRequest, resolve_api_key
from backend.apps.ai.llm_providers.inception_client import _stream, _usage, invoke_inception_chat_completions


def run(coro):
    return asyncio.run(coro)


def test_vault_precedes_stale_environment(monkeypatch):
    monkeypatch.setenv("SECRET__INCEPTION_LABS__API_KEY", "stale")
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="live"))
    assert run(resolve_api_key(manager)) == "live"
    manager.get_secret.assert_awaited_once_with(secret_path="kv/data/providers/inception_labs", secret_key="api_key")


def test_request_constraints_and_complete_usage():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["temperature"] == 0.5
        assert payload["max_completion_tokens"] == 8192
        assert payload["reasoning_effort"] == "instant"
        return httpx.Response(200, json={"id": "req1", "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
    result = run(InceptionClient("key", transport=httpx.MockTransport(handler)).complete(InceptionRequest(messages=[{"role": "user", "content": "hello"}], temperature=0, max_completion_tokens=8192, reasoning_effort="instant")))
    usage = _usage(result)
    assert usage.input_tokens == 10 and usage.output_tokens == 2
    assert usage.cache_read_input_tokens is None
    with pytest.raises(ValueError):
        InceptionRequest(messages=[{"role": "user", "content": [{"type": "image_url"}]}])


def test_auth_errors_never_expose_body_or_key():
    client = InceptionClient("secret-key", transport=httpx.MockTransport(lambda request: httpx.Response(401, text="private response secret-key")))
    with pytest.raises(InceptionError, match="HTTP 401") as error:
        run(client.complete(InceptionRequest(messages=[])))
    assert "secret-key" not in str(error.value) and "private" not in str(error.value)


def test_bounded_rate_limit_retry(monkeypatch):
    calls = []
    async def no_sleep(delay):
        pass
    monkeypatch.setattr("backend.shared.providers.inception.client.asyncio.sleep", no_sleep)
    def handler(request):
        calls.append(request)
        return httpx.Response(429, text="private")
    with pytest.raises(InceptionError, match="429"):
        run(InceptionClient("key", transport=httpx.MockTransport(handler)).complete(InceptionRequest(messages=[])))
    assert len(calls) == 3
    calls.clear()
    with pytest.raises(InceptionError):
        run(InceptionClient("key", transport=httpx.MockTransport(handler), max_retries=0).complete(InceptionRequest(messages=[])))
    assert len(calls) == 1


@pytest.mark.parametrize("header,delay", [("7", 7), ("3600", 10), ("-1", .5), ("nan", .5), ("invalid", .5)])
def test_retry_after_is_respected_and_bounded(header, delay):
    from backend.shared.providers.inception.client import retry_delay
    assert retry_delay(httpx.Response(429, headers={"retry-after": header}), 0) == delay


class Body(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content, self.closed = content, False
    async def __aiter__(self):
        yield self.content
    async def aclose(self):
        self.closed = True


def test_stream_tool_fragments_usage_and_cleanup():
    events = [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call1", "function": {"name": "finalize", "arguments": '{"text":'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"hello"}'}}]}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}},
    ]
    body = Body((''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n').encode())
    def handler(request):
        assert json.loads(request.content)["stream_options"] == {"include_usage": True}
        return httpx.Response(200, stream=body)
    async def collect():
        return [chunk async for chunk in _stream(InceptionClient("key", transport=httpx.MockTransport(handler)), InceptionRequest(messages=[]))]
    chunks = run(collect())
    assert chunks[0].function_arguments_parsed == {"text": "hello"}
    assert chunks[1].input_tokens == 5
    assert body.closed


@pytest.mark.parametrize("content", [b'data: {private-invalid}\n\n', b'data: {"choices":[]}\n\n', b'data: {"choices":[{"delta":"private"}]}\n\n'])
def test_malformed_or_truncated_stream_fails_closed(content):
    body = Body(content)
    async def collect():
        return [e async for e in InceptionClient("key", transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=body))).stream(InceptionRequest(messages=[]))]
    with pytest.raises(InceptionError) as error:
        run(collect())
    assert "private" not in str(error.value)
    assert body.closed


def test_cancel_stream_closes_response():
    body = Body(b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n')
    async def cancel():
        stream = _stream(InceptionClient("key", transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=body))), InceptionRequest(messages=[]))
        assert await anext(stream) == "hello"
        await stream.aclose()
    run(cancel())
    assert body.closed


def test_missing_key_adapter_failure_is_sanitized(monkeypatch):
    monkeypatch.delenv("SECRET__INCEPTION_LABS__API_KEY", raising=False)
    result = run(invoke_inception_chat_completions("test", "mercury-3", [], SimpleNamespace(get_secret=AsyncMock(return_value=None))))
    assert result.success is False
    assert result.error_message == "Inception request could not be completed"


def test_adapter_maps_forced_tool_and_nonstream_usage(monkeypatch):
    from backend.shared.providers.inception import InceptionResult
    captured = {}
    async def complete(self, request):
        captured.update(request.model_dump())
        return InceptionResult.model_validate({
            "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "finalize", "arguments": '{"text":"ok"}'}}]}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6, "prompt_tokens_details": {"cached_tokens": 1}, "completion_tokens_details": {"reasoning_tokens": 1}},
        })
    monkeypatch.setattr(InceptionClient, "complete", complete)
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="key"))
    choice = {"type": "function", "function": {"name": "finalize"}}
    result = run(invoke_inception_chat_completions("test", "mercury-3", [{"role": "user", "content": "hello"}], manager,
        tools=[{"type": "function", "function": {"name": "finalize", "description": "Finalize text", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}}], tool_choice=choice))
    assert result.success and result.tool_calls_made[0].function_arguments_parsed == {"text": "ok"}
    assert result.usage.reasoning_tokens == 1
    assert result.usage.output_tokens == 2
    assert result.usage.cache_read_input_tokens == 1
    assert captured["tool_choice"] == choice
    assert captured["tools"][0]["function"]["name"] == "finalize"


def test_text_blocks_normalized_and_images_rejected():
    from backend.apps.ai.llm_providers.inception_client import _text_messages
    original = [{"role": "user", "content": [{"type": "text", "text": "Hello "}, {"type": "text", "text": "world"}]}]
    assert _text_messages(original) == [{"role": "user", "content": "Hello world"}]
    assert isinstance(original[0]["content"], list)
    with pytest.raises(InceptionError):
        _text_messages([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "private"}}]}])


def test_done_without_finish_reason_is_rejected():
    async def check():
        events = b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n'
        client = InceptionClient("key", transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Body(events))))
        with pytest.raises(InceptionError, match="without a finish reason"):
            _ = [chunk async for chunk in _stream(client, InceptionRequest(messages=[]))]
    run(check())


@pytest.mark.parametrize("reason,success", [("stop", True), ("length", True), ("content_filter", False), ("unknown", False), (None, False)])
def test_adapter_finish_reason_handling(monkeypatch, reason, success):
    from backend.shared.providers.inception import InceptionResult
    async def complete(self, request):
        return InceptionResult.model_validate({"choices": [{"finish_reason": reason, "message": {"content": "hello"}}]})
    monkeypatch.setattr(InceptionClient, "complete", complete)
    result = run(invoke_inception_chat_completions("test", "mercury-3", [], SimpleNamespace(get_secret=AsyncMock(return_value="key"))))
    assert result.success is success
    if reason == "length":
        assert "cut short" in result.direct_message_content


def test_launch_tariff_discounts_customer_and_supplier_and_freezes_attempt():
    import copy
    from datetime import date
    from pathlib import Path
    import yaml
    from backend.shared.python_utils.billing_utils import snapshot_model_tariff
    from backend.shared.python_utils.model_pricing import resolve_model_tariff, validate_temporary_prices
    model = yaml.safe_load((Path(__file__).resolve().parents[1] / "providers/inception.yml").read_text())["models"][0]
    original = copy.deepcopy(model)
    validate_temporary_prices(model)
    before = resolve_model_tariff(model, on_date=date(2026, 10, 18), inference_host="inception")
    launch = resolve_model_tariff(model, on_date=date(2026, 10, 20), inference_host="inception")
    assert before["pricing"]["tokens"] == {"input": {"per_credit_unit": 1650}, "output": {"per_credit_unit": 475}}
    assert launch["pricing"]["tokens"] == {"input": {"per_credit_unit": 3300}, "output": {"per_credit_unit": 950}}
    assert model == original
    assert before["costs"]["input_per_million_token"]["price"] == .2
    assert launch["costs"]["input_per_million_token"]["price"] == .1

    frozen = snapshot_model_tariff(launch)
    launch["pricing"]["tokens"]["input"]["per_credit_unit"] = 1
    launch["costs"]["input_per_million_token"]["price"] = 999
    assert frozen["pricing"]["tokens"]["input"]["per_credit_unit"] == 3300
    assert frozen["costs"]["input_per_million_token"]["price"] == .1
    assert frozen["active_temporary_price"]["id"] == "mercury-3-launch-2026"
    assert model == original
