# contract-test-file: infrastructure
"""SDK truncation is private metadata and failed delegated evidence, never a retry."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.llm_providers import google_client
from backend.apps.ai.utils.main_processing_failure import main_processing_failure_reason
from backend.tests.test_main_processor_invalid_tool_calls import (
    _run_mocked_protocol_guard_main_processor, main_processor,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["studio", "vertex"])
@pytest.mark.parametrize("with_usage", [True, False])
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
async def test_google_max_tokens_metadata_follows_usage_and_client_close(monkeypatch, provider, with_usage):
    closed, calls = [], []
    reported = SimpleNamespace(prompt_token_count=100, candidates_token_count=3,
        thoughts_token_count=1257, total_token_count=1360, cached_content_token_count=0)

    async def generate_content_stream(**kwargs):
        calls.append(kwargs)
        async def chunks():
            yield SimpleNamespace(candidates=[SimpleNamespace(finish_reason=google_client.types.FinishReason.MAX_TOKENS,
                content=SimpleNamespace(parts=[SimpleNamespace(text="Partial report", thought=False)]))],
                usage_metadata=reported if with_usage else None)
        return chunks()

    async def close():
        closed.append(True)

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream),
        aclose=close), close=lambda: None)
    monkeypatch.setattr(google_client, "_get_loop_google_client",
        AsyncMock(return_value=(client, SimpleNamespace(close=AsyncMock()))))
    monkeypatch.setattr(google_client, "_get_google_ai_studio_api_key", AsyncMock(return_value="test-key"))
    monkeypatch.setattr(google_client, "_google_client_initialized", True)
    monkeypatch.setattr(google_client, "calculate_token_breakdown", lambda *_a, **_k: {})
    # Local SDK versions may predate Argon's thinking enum; this fixture isolates
    # finish/usage transport while provider thinking profiles have their own tests.
    monkeypatch.setattr(google_client, "_google_thinking_config",
        lambda *_a: google_client.types.ThinkingConfig(include_thoughts=True))
    # Missing usage remains missing: finish metadata cannot pretend to be zero-cost usage.
    monkeypatch.setattr(google_client.tiktoken, "get_encoding", lambda *_a: (_ for _ in ()).throw(ValueError("no estimate")))
    invoke = (google_client.invoke_google_ai_studio_chat_completions if provider == "studio"
              else google_client.invoke_google_chat_completions)
    stream = await invoke(task_id="task", model_id="gemini-4-argon", stream=True,
        messages=[{"role": "user", "content": "Audit primary sources."}], max_tokens=1260, thinking_level="HIGH")
    chunks = []
    async for chunk in stream:
        if isinstance(chunk, google_client.GoogleStreamFinishMetadata):
            assert closed == [True]
        chunks.append(chunk)
    assert len(calls) == 1
    assert calls[0]["config"].max_output_tokens == 1260
    assert isinstance(chunks[-1], google_client.GoogleStreamFinishMetadata)
    assert chunks[-1].finish_reason == "MAX_TOKENS"
    from backend.apps.ai.testing.caching_llm_wrapper import _serialize_stream_chunk, _deserialize_stream_chunk
    restored = _deserialize_stream_chunk(_serialize_stream_chunk(chunks[-1]))
    assert isinstance(restored, google_client.GoogleStreamFinishMetadata)
    assert restored.finish_reason == "MAX_TOKENS"
    usage = [c for c in chunks if isinstance(c, google_client.GoogleUsageMetadata)]
    assert len(usage) == int(with_usage)
    if with_usage:
        assert usage[0].candidates_token_count == 3 and usage[0].thoughts_token_count == 1257
        assert chunks.index(usage[0]) < len(chunks) - 1
    # Ordinary collectors still see the original text and notice, never metadata repr.
    text = "".join(c for c in chunks if isinstance(c, str))
    assert text.startswith("Partial report") and "maximum output length" in text
    assert "finish_reason=" not in text


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.parametrize("checkpoint_failed", [False, True])
async def test_subchat_truncation_checkpoints_usage_before_failure_without_tools_or_retry(monkeypatch, checkpoint_failed):
    checkpoint = AsyncMock(return_value=12, side_effect=RuntimeError("lost checkpoint acknowledgement") if checkpoint_failed else None)
    monkeypatch.setattr(main_processor, "_reserve_ai_iteration", AsyncMock(return_value="operation-1"))
    monkeypatch.setattr(main_processor, "_fit_orchestrated_output_token_limit", AsyncMock(return_value=1260))
    monkeypatch.setattr(main_processor, "_checkpoint_orchestrated_ai_iteration", checkpoint)
    monkeypatch.setattr(main_processor, "calculate_model_usage_credits", lambda *_a: 12)
    execute = AsyncMock(side_effect=AssertionError("Tool after truncated report"))
    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    chunks = ["Provisional text.", {"fake_google_tool_call": "web-read", "arguments": {"url": "https://example.org/primary"}},
        {"fake_google_usage": (100, 1260)}, google_client.GoogleStreamFinishMetadata(finish_reason="MAX_TOKENS")]
    output, calls = await _run_mocked_protocol_guard_main_processor(monkeypatch, [chunks],
        generated_tools=[{"type": "function", "function": {"name": "web-read", "description": "Read", "parameters": {"type": "object"}}}],
        request_overrides={"is_sub_chat": True, "parent_id": "parent", "orchestration_id": "orchestration"})
    assert len(calls) == 1
    checkpoint.assert_awaited_once()
    assert checkpoint.await_args.kwargs["cumulative_credits"] == 12
    assert main_processing_failure_reason(output[-1]) == "orchestration_output_limit"
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("is_sub_chat,typed_finish", [(False, True), (True, False)])
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure
async def test_ordinary_turn_and_quoted_notice_do_not_become_truncation_failure(monkeypatch, is_sub_chat, typed_finish):
    chunks = ["Quoted notice: maximum output length.", {"fake_google_usage": (10, 3)}]
    if typed_finish:
        chunks.append(google_client.GoogleStreamFinishMetadata(finish_reason="MAX_TOKENS"))
    output, calls = await _run_mocked_protocol_guard_main_processor(monkeypatch, [chunks],
        request_overrides={"is_sub_chat": is_sub_chat})
    assert len(calls) == 1
    assert not any(main_processing_failure_reason(chunk) for chunk in output)
