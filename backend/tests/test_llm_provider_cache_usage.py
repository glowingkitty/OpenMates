"""Provider cache usage contracts observed with synthetic dev metadata probes."""

# contract-test-file: infrastructure

import asyncio
from types import SimpleNamespace

from backend.apps.ai.llm_providers.anthropic_direct_api import invoke_direct_api
from backend.apps.ai.llm_providers.anthropic_shared import (
    AnthropicUsageMetadata,
    _prepare_messages_for_anthropic,
)
from backend.apps.ai.llm_providers.bedrock_client import (
    _controlled_five_minute_cache_write,
    _process_converse_response,
)
from backend.apps.ai.llm_providers.google_client import _google_usage_metadata
from backend.apps.ai.llm_providers.openai_client import _invoke_openai_direct_api
from backend.apps.ai.llm_providers.openai_responses import _usage as responses_usage
from backend.apps.ai.llm_providers.openai_shared import openai_cache_read_tokens


def test_openai_read_present_and_write_unknown() -> None:
    usage = responses_usage({
        "id": "resp_synthetic",
        "usage": {"input_tokens": 5285, "output_tokens": 5, "total_tokens": 5290,
                  "input_tokens_details": {"cached_tokens": 5282}},
    })
    assert usage.cache_read_input_tokens == 5282
    assert usage.cache_creation_input_tokens is None
    assert usage.provider_request_id == "resp_synthetic"
    assert openai_cache_read_tokens({"prompt_tokens_details": {"cached_tokens": 0}}) == 0
    assert openai_cache_read_tokens({"prompt_tokens": 10}) is None


def test_anthropic_caps_breakpoints_and_preserves_static_boundary() -> None:
    prefix = "stable " * 700
    dynamic = "changed timestamp"
    messages = [{"role": "system", "content": prefix + dynamic}]
    messages.extend({"role": "user", "content": f"history {index} " * 500} for index in range(8))
    system, converted = _prepare_messages_for_anthropic(messages, prefix)
    assert system[0]["text"] == prefix
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[1]["text"] == dynamic
    assert "cache_control" not in system[1]
    marked = sum("cache_control" in block for block in system)
    marked += sum("cache_control" in block for item in converted for block in item["content"])
    assert marked == 4


def test_anthropic_stream_merges_start_input_cache_and_delta_output() -> None:
    start_usage = SimpleNamespace(input_tokens=10, output_tokens=0,
                                  cache_creation_input_tokens=5273,
                                  cache_read_input_tokens=0,
                                  cache_creation=SimpleNamespace(
                                      ephemeral_5m_input_tokens=5273,
                                      ephemeral_1h_input_tokens=0))
    delta_usage = SimpleNamespace(input_tokens=None, output_tokens=5,
                                  cache_creation_input_tokens=None,
                                  cache_read_input_tokens=None)
    events = [
        SimpleNamespace(type="message_start", message=SimpleNamespace(id="msg_synthetic", usage=start_usage)),
        SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="end_turn", usage=delta_usage)),
    ]
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: events))

    async def collect():
        stream = await invoke_direct_api("task", "claude-sonnet-4-6", [
            {"role": "system", "content": "Stable system"},
            {"role": "user", "content": "Reply with OK."},
        ], client, max_tokens=8, stream=True)
        return [item async for item in stream]

    usage = next(item for item in asyncio.run(collect()) if isinstance(item, AnthropicUsageMetadata))
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.cache_creation_input_tokens == 5273
    assert usage.cache_creation_5m_input_tokens == 5273
    assert usage.provider_request_id == "msg_synthetic"


def test_anthropic_nonstream_preserves_missing_cache_counters() -> None:
    response = SimpleNamespace(
        id="msg_synthetic", usage=SimpleNamespace(input_tokens=10, output_tokens=1),
        content=[SimpleNamespace(type="text", text="OK")],
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: response))
    result = asyncio.run(invoke_direct_api(
        "task", "claude-sonnet-4-6", [{"role": "user", "content": "Reply OK"}],
        client, max_tokens=8,
    ))
    assert result.success
    assert result.usage.cache_read_input_tokens is None
    assert result.usage.cache_creation_input_tokens is None
    assert result.usage.usage_source == "provider_reported"


def test_google_read_and_thoughts_are_provider_reported() -> None:
    usage = _google_usage_metadata(
        SimpleNamespace(prompt_token_count=5277, candidates_token_count=2,
                        total_token_count=5286, cached_content_token_count=5272,
                        thoughts_token_count=7),
        {"user_input_tokens": 5, "system_prompt_tokens": 5272}, "google_ai_studio",
    )
    assert usage.cache_read_input_tokens == 5272
    assert usage.cache_creation_input_tokens is None
    assert usage.thoughts_token_count == 7
    assert usage.inference_host == "google_ai_studio"


def test_openai_chat_stream_captures_usage_only_final_chunk(monkeypatch) -> None:
    from backend.apps.ai.llm_providers import openai_client

    async def chunks():
        yield SimpleNamespace(id="chat_synthetic", choices=[], usage=SimpleNamespace(
            prompt_tokens=5285, completion_tokens=5, total_tokens=5290,
            model_dump=lambda **kwargs: {"prompt_tokens_details": {"cached_tokens": 5282}},
        ))

    async def create(**kwargs):
        assert kwargs["stream_options"] == {"include_usage": True}
        return chunks()

    monkeypatch.setattr(openai_client, "_openai_direct_client", SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))

    async def collect():
        stream = await _invoke_openai_direct_api(
            "task", "gpt-6-luna", [{"role": "user", "content": "Reply OK"}], stream=True,
        )
        return [item async for item in stream]

    usage = next(item for item in asyncio.run(collect()) if item.__class__.__name__ == "OpenAIUsageMetadata")
    assert usage.cache_read_input_tokens == 5282
    assert usage.cache_creation_input_tokens is None
    assert usage.usage_source == "provider_reported"
    assert usage.provider_request_id == "chat_synthetic"


def test_bedrock_cache_tokens_are_separate_from_uncached_input(monkeypatch) -> None:
    from backend.apps.ai.llm_providers import bedrock_client

    response = {
        "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 5288,
                  "cacheReadInputTokens": 5273, "cacheWriteInputTokens": 0},
        "ResponseMetadata": {"RequestId": "aws_synthetic"},
        "output": {"message": {"content": [{"text": "OK"}]}},
        "stopReason": "end_turn",
    }
    monkeypatch.setattr(bedrock_client, "_bedrock_runtime_client",
                        SimpleNamespace(converse=lambda **kwargs: response))
    result = asyncio.run(_process_converse_response(
        "task", "eu.anthropic.claude-sonnet-4-6", {"modelId": "model"},
        [{"role": "user", "content": "Reply OK"}], "[test]",
    ))
    assert result.usage.input_tokens == 10
    assert result.usage.cache_read_input_tokens == 5273
    assert result.usage.cache_creation_input_tokens == 0
    assert result.usage.total_tokens == 5288
    assert result.usage.provider_request_id == "aws_synthetic"


def test_bedrock_claude_places_checkpoint_before_dynamic_system_text(monkeypatch) -> None:
    from backend.apps.ai.llm_providers import bedrock_client

    captured = {}

    def converse(**kwargs):
        captured.update(kwargs)
        return {
            "usage": {"inputTokens": 10, "outputTokens": 1, "totalTokens": 18,
                      "cacheWriteInputTokens": 7},
            "output": {"message": {"content": [{"text": "OK"}]}},
            "stopReason": "end_turn",
        }

    monkeypatch.setattr(bedrock_client, "_bedrock_runtime_client", SimpleNamespace(converse=converse))
    prefix = "stable " * 700
    result = asyncio.run(bedrock_client.invoke_aws_bedrock_chat_completions(
        "task", "eu.anthropic.claude-sonnet-4-6", [
            {"role": "system", "content": prefix + "dynamic timestamp"},
            {"role": "user", "content": "Reply OK"},
        ], cacheable_system_prefix=prefix,
    ))
    assert result.success
    assert result.usage.cache_creation_input_tokens == 7
    assert result.usage.cache_creation_5m_input_tokens == 7
    assert result.usage.cache_creation_1h_input_tokens == 0
    assert captured["system"] == [
        {"text": prefix}, {"cachePoint": {"type": "default"}},
        {"text": "dynamic timestamp"},
    ]


def test_bedrock_retention_is_known_only_for_controlled_claude_cache_point() -> None:
    reported = {"cacheWriteInputTokens": 5273}
    controlled = {"system": [{"text": "stable"}, {"cachePoint": {"type": "default"}}]}
    assert _controlled_five_minute_cache_write("eu.anthropic.claude-sonnet-4-6", controlled, reported) == (5273, 0)
    assert _controlled_five_minute_cache_write("eu.anthropic.claude-sonnet-4-6", {}, reported) == (None, None)
    assert _controlled_five_minute_cache_write("meta.llama", controlled, reported) == (None, None)
    assert _controlled_five_minute_cache_write(
        "eu.anthropic.claude-sonnet-4-6",
        {"system": [{"cachePoint": {"type": "default", "ttl": "1h"}}]},
        reported,
    ) == (None, None)
    assert _controlled_five_minute_cache_write("eu.anthropic.claude-sonnet-4-6", controlled, {}) == (None, None)


def test_mistral_scoped_cache_key_is_top_level_request_field(monkeypatch) -> None:
    from backend.apps.ai.llm_providers import mistral_client

    captured = {}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            captured.update(kwargs["json"])
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "id": "mistral_synthetic", "object": "chat.completion", "created": 1,
                    "model": "mistral-small-latest", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 1,
                              "total_tokens": 11, "prompt_tokens_details": {"cached_tokens": 8}},
                },
            )

    monkeypatch.setattr(mistral_client, "MISTRAL_API_KEY", "synthetic")
    monkeypatch.setattr(mistral_client, "_get_mistral_reasoning_effort", lambda model_id: None)
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient", Client)
    result = asyncio.run(mistral_client.invoke_mistral_chat_completions(
        "task", "mistral-small-latest", [{"role": "user", "content": "Reply OK"}],
        prompt_cache_key="scoped-hmac-synthetic",
    ))
    assert captured["prompt_cache_key"] == "scoped-hmac-synthetic"
    assert result.usage.cache_read_input_tokens == 8
    assert result.usage.cache_creation_input_tokens is None
