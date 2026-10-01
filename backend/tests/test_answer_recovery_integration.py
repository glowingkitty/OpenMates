# contract-test-file: infrastructure
"""Integrated coverage for bounded final-answer recovery.

These tests keep the real main-processing loop, LLM routing wrapper, Google
stream types, and tool protocol guard. Only provider I/O and unrelated setup
collaborators are replaced.
"""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.llm_providers.google_client import (
    GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY,
    GoogleUsageMetadata,
    ParsedGoogleToolCall,
)
from backend.apps.ai.processing import main_processor
from backend.apps.ai.utils import llm_utils
from backend.apps.ai.utils.tool_protocol_guard import ToolProtocolGuard


pytestmark = pytest.mark.asyncio

PRIMARY_MODEL = "google/answer-primary"
ALTERNATE_MODEL = "google/answer-alternate"
CROSS_PROVIDER_MODEL = "anthropic/answer-alternate"
CURRENT_REQUEST = "Compare the completed search evidence and answer with citations."
ATTACHMENT_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
CITATION_URL = "https://evidence.test/source-1"
EMBED_REFERENCE = "search-result-source-1"
ANSWER = f"The completed evidence supports the first option [source]({CITATION_URL})."


def _forbidden_tool_call(call_number: int) -> ParsedGoogleToolCall:
    return ParsedGoogleToolCall(
        tool_call_id=f"forbidden-{call_number}",
        function_name="web-search",
        function_arguments_raw=json.dumps({"query": "repeat the search"}),
        function_arguments_parsed={"query": "repeat the search"},
        thought_signature=f"new-signature-{call_number}",
        provider_transport_state={
            GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY: "google"
        },
    )


def _usage(call_number: int) -> GoogleUsageMetadata:
    return GoogleUsageMetadata(
        prompt_token_count=10 + call_number,
        candidates_token_count=call_number,
        total_token_count=10 + (2 * call_number),
        user_input_tokens=4,
        system_prompt_tokens=3,
    )


def _seeded_history() -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Use this reference chart in the comparison."},
                {"type": "image_url", "image_url": {"url": ATTACHMENT_URL}},
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "search-hit",
                    "type": "function",
                    "function": {
                        "name": "web-search",
                        "arguments": json.dumps({"query": "option comparison"}),
                    },
                    "thought_signature": "history-signature-hit",
                    "provider_transport_state": {
                        GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY: "google"
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "search-hit",
            "name": "web-search",
            "content": json.dumps(
                {
                    "results": [
                        {
                            "title": "Primary source",
                            "url": CITATION_URL,
                            "embed_ref": EMBED_REFERENCE,
                        }
                    ]
                }
            ),
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "search-zero",
                    "type": "function",
                    "function": {
                        "name": "web-search",
                        "arguments": json.dumps({"query": "zero-hit-query"}),
                    },
                    "thought_signature": "history-signature-zero",
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "search-zero",
            "name": "web-search",
            "content": json.dumps(
                {"query": "zero-hit-query", "results": [], "error": None}
            ),
        },
        {"role": "user", "content": CURRENT_REQUEST},
    ]


def _request(history: list[dict]) -> SimpleNamespace:
    request = SimpleNamespace(
        chat_id="chat-answer-recovery",
        message_id="message-answer-recovery",
        user_id="user-answer-recovery",
        user_id_hash="user-hash-answer-recovery",
        user_preferences={},
        mentioned_settings_memories_cleartext=None,
        historical_artifact_context=None,
        current_user_content=CURRENT_REQUEST,
        active_focus_id=None,
        active_project_focus=None,
        current_project=None,
        current_chat_title=None,
        is_incognito=False,
        is_external=False,
        message_history=history,
        orchestration_id=None,
        is_sub_chat=False,
        is_sub_chat_continuation=False,
        awaiting_async_skill_continuation=False,
        mate_id="mate-1",
        chat_has_title=True,
        chat_key_version=1,
        parent_id=None,
        root_chat_id=None,
        root_turn_id=None,
        sub_chat_depth=0,
        orchestration_dispatch_token=None,
        orchestration_descendant_limit=None,
        orchestration_credit_limit=None,
        orchestration_approved=False,
        budget_limit=None,
        budget_spent=0,
        team_id=None,
        team_id_hash=None,
        team_workspace_type=None,
        team_object_id_hash=None,
        recovery_preflight_id=None,
        recovery_turn_id=None,
        recovery_public_key=None,
        learning_mode=None,
        client_capabilities=[],
        is_anonymous=False,
        anonymous_reservation_id=None,
        has_image_upload_embed=True,
        embed_file_path_index=None,
    )
    request.resolved_recovery_inference_task_id = lambda: None
    request.model_dump = lambda **_kwargs: request.__dict__.copy()
    return request


def _preprocessing(
    alternate_model: str | None, secondary_model: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        load_app_settings_and_memories=[],
        rejection_reason=None,
        relevant_app_skills=[],
        selected_main_llm_model_id=PRIMARY_MODEL,
        selected_main_llm_model_name="Answer primary",
        selected_secondary_model_id=secondary_model,
        selected_fallback_model_id=alternate_model,
        selected_mate_id="mate-1",
        category="general",
        output_language="en",
        relevant_embedded_previews=[],
        relevant_focus_modes=[],
        enable_subchats=False,
        llm_response_temp=0.1,
        user_requested_skills_only=False,
        user_requested_focus_only=False,
    )


@pytest.fixture
def answer_recovery_runner(monkeypatch):
    provider_calls: list[dict] = []
    skill_dispatch = AsyncMock(name="execute_skill_with_multiple_requests")

    async def no_task_queue_retry(*_args, **_kwargs):
        return None

    class NoHealthCache:
        def __init__(self) -> None:
            self.client = asyncio.sleep(0, result=None)

    monkeypatch.setattr(main_processor, "MAX_TOOL_CALL_ITERATIONS", 1)
    monkeypatch.setattr(main_processor, "MAX_ANSWER_ONLY_RECOVERY_ITERATIONS", 2)
    monkeypatch.setattr(main_processor, "resolve_sub_chat_depth", lambda _request: 0)
    monkeypatch.setattr(
        main_processor, "has_transcribed_web_audio_recording", lambda _history: False
    )
    monkeypatch.setattr(
        main_processor,
        "should_include_embeds_results_view_instruction",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        main_processor, "normalize_wikipedia_language", lambda _language: "en"
    )
    monkeypatch.setattr(
        main_processor,
        "TranslationService",
        lambda: SimpleNamespace(get_nested_translation=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        main_processor, "generate_tools_from_apps", lambda **_kwargs: []
    )
    monkeypatch.setattr(
        main_processor, "evaluate_task_queue_post_turn", no_task_queue_retry
    )
    monkeypatch.setattr(
        main_processor, "model_history_token_budget", lambda *_args, **_kwargs: 100_000
    )
    monkeypatch.setattr(
        main_processor, "execute_skill_with_multiple_requests", skill_dispatch
    )
    monkeypatch.setattr(llm_utils, "CacheService", NoHealthCache)

    assert main_processor.call_main_llm_stream is llm_utils.call_main_llm_stream
    assert main_processor.ToolProtocolGuard is ToolProtocolGuard

    async def run(
        response_chunks: list[list[object]],
        *,
        alternate_model: str | None,
        secondary_model: str | None = None,
        hidden_server_fallback: bool = False,
    ) -> tuple[list[object], list[dict], list[dict]]:
        calls_before = len(provider_calls)

        monkeypatch.setattr(
            llm_utils,
            "resolve_fallback_servers_from_provider_config",
            lambda model_id: (
                ["google/hidden-server"]
                if hidden_server_fallback and model_id == PRIMARY_MODEL
                else []
            ),
        )

        async def fake_provider(provider_id: str, **kwargs):
            call_number = len(provider_calls) - calls_before + 1
            provider_calls.append({**copy.deepcopy(kwargs), "provider_id": provider_id})
            chunks = response_chunks[call_number - 1]

            async def stream():
                for chunk in chunks:
                    if isinstance(chunk, BaseException):
                        raise chunk
                    yield chunk
                yield _usage(call_number)

            return stream()

        async def fake_google_provider(**kwargs):
            return await fake_provider("google", **kwargs)

        async def fake_anthropic_provider(**kwargs):
            return await fake_provider("anthropic", **kwargs)

        monkeypatch.setitem(
            llm_utils.PROVIDER_CLIENT_REGISTRY,
            "google",
            fake_google_provider,
        )
        monkeypatch.setitem(
            llm_utils.PROVIDER_CLIENT_REGISTRY,
            "anthropic",
            fake_anthropic_provider,
        )

        history = _seeded_history()
        original_history = copy.deepcopy(history)
        output = [
            chunk
            async for chunk in main_processor.handle_main_processing(
                "task-answer-recovery",
                _request(history),
                _preprocessing(alternate_model, secondary_model),
                {},
                None,
                None,
                None,
                [],
                discovered_apps_metadata={},
                user_overrides=SimpleNamespace(skills=None, wikipedia_references=[]),
            )
        ]
        assert history == original_history
        skill_dispatch.assert_not_awaited()
        return output, provider_calls[calls_before:], original_history

    return run


def _assert_clean_recovery_payload(call: dict) -> None:
    messages = call["messages"]
    serialized = json.dumps(messages)
    assert call["tool_choice"] == "none"
    assert call["tools"] is None
    assert not any(message.get("role") == "tool" for message in messages)
    assert not any("tool_calls" in message for message in messages)
    assert "thought_signature" not in serialized
    assert "provider_transport_state" not in serialized
    assert "history-signature" not in serialized
    assert CURRENT_REQUEST in serialized
    assert ATTACHMENT_URL in serialized
    assert CITATION_URL in serialized
    assert EMBED_REFERENCE in serialized
    assert "zero-hit-query" in serialized
    assert "UNTRUSTED TOOL EVIDENCE" in serialized


def _assert_usage(
    output: list[object], calls: int, successful_model: str | None
) -> None:
    sentinels = [
        chunk
        for chunk in output
        if isinstance(chunk, dict) and chunk.get("__cumulative_llm_usage__") is True
    ]
    assert len(sentinels) == 1
    sentinel = sentinels[0]
    assert sentinel["total_input_tokens"] == sum(
        10 + number for number in range(1, calls + 1)
    )
    assert sentinel["total_output_tokens"] == sum(range(1, calls + 1))
    assert sentinel["successful_model_id"] == successful_model


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
async def test_forbidden_final_tool_call_retries_same_model_with_clean_evidence(
    answer_recovery_runner,
) -> None:
    output, calls, _original_history = await answer_recovery_runner(
        [[_forbidden_tool_call(1)], [ANSWER]],
        alternate_model=ALTERNATE_MODEL,
    )

    assert [call["model_id"] for call in calls] == ["answer-primary", "answer-primary"]
    assert all(
        call["tool_choice"] == "none" and call["tools"] is None for call in calls
    )
    _assert_clean_recovery_payload(calls[1])
    assert "".join(chunk for chunk in output if isinstance(chunk, str)) == ANSWER
    assert not any(
        isinstance(chunk, dict) and chunk.get("__main_processing_failure__") is True
        for chunk in output
    )
    _assert_usage(output, calls=2, successful_model=PRIMARY_MODEL)


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
async def test_forbidden_clean_retry_uses_one_configured_alternate(
    answer_recovery_runner,
) -> None:
    forbidden_output, forbidden_calls, _original_history = await answer_recovery_runner(
        [[_forbidden_tool_call(1)], [_forbidden_tool_call(2)], [ANSWER]],
        alternate_model=ALTERNATE_MODEL,
    )

    assert [call["model_id"] for call in forbidden_calls] == [
        "answer-primary",
        "answer-primary",
        "answer-alternate",
    ]
    _assert_clean_recovery_payload(forbidden_calls[1])
    _assert_clean_recovery_payload(forbidden_calls[2])
    assert (
        "".join(chunk for chunk in forbidden_output if isinstance(chunk, str)) == ANSWER
    )
    assert not any(
        isinstance(chunk, dict) and chunk.get("__main_processing_failure__") is True
        for chunk in forbidden_output
    )
    _assert_usage(forbidden_output, calls=3, successful_model=ALTERNATE_MODEL)

    partial_prefix = "The completed evidence favors the first option.\n\n"
    alternate_suffix = (
        f"The supporting citation is [the primary source]({CITATION_URL})."
    )
    timeout_output, timeout_calls, _original_history = await answer_recovery_runner(
        [
            [_forbidden_tool_call(1)],
            [
                partial_prefix,
                _usage(2),
                TimeoutError("provider stalled after partial text"),
            ],
            [alternate_suffix],
        ],
        alternate_model=ALTERNATE_MODEL,
        hidden_server_fallback=True,
    )

    # The clean partial attempt must escape to main processing immediately. If
    # the wrapper silently tried its configured server fallback, "hidden-server"
    # would appear here before the independently configured alternate model.
    assert [call["model_id"] for call in timeout_calls] == [
        "answer-primary",
        "answer-primary",
        "answer-alternate",
    ]
    _assert_clean_recovery_payload(timeout_calls[1])
    _assert_clean_recovery_payload(timeout_calls[2])
    published_prefix_messages = [
        message
        for message in timeout_calls[2]["messages"]
        if isinstance(message.get("content"), str)
        and "ALREADY PUBLISHED TO THE USER" in message["content"]
    ]
    assert len(published_prefix_messages) == 1
    assert partial_prefix in published_prefix_messages[0]["content"]

    published = "".join(chunk for chunk in timeout_output if isinstance(chunk, str))
    assert published == partial_prefix + alternate_suffix
    assert published.count(partial_prefix) == 1
    assert llm_utils.STANDARDIZED_USER_ERROR_MESSAGE not in published
    assert not any(
        isinstance(chunk, dict) and chunk.get("__main_processing_failure__") is True
        for chunk in timeout_output
    )
    _assert_usage(timeout_output, calls=3, successful_model=ALTERNATE_MODEL)


async def test_repeated_forbidden_calls_prefer_a_different_provider_for_final_answer(
    answer_recovery_runner,
) -> None:
    output, calls, _original_history = await answer_recovery_runner(
        [[_forbidden_tool_call(1)], [_forbidden_tool_call(2)], [ANSWER]],
        secondary_model=ALTERNATE_MODEL,
        alternate_model=CROSS_PROVIDER_MODEL,
    )

    assert [call["provider_id"] for call in calls] == [
        "google",
        "google",
        "anthropic",
    ]
    assert [call["model_id"] for call in calls] == [
        "answer-primary",
        "answer-primary",
        "answer-alternate",
    ]
    _assert_clean_recovery_payload(calls[1])
    _assert_clean_recovery_payload(calls[2])
    assert "".join(chunk for chunk in output if isinstance(chunk, str)) == ANSWER
    assert not any(
        isinstance(chunk, dict) and chunk.get("__main_processing_failure__") is True
        for chunk in output
    )
    _assert_usage(output, calls=3, successful_model=CROSS_PROVIDER_MODEL)


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
async def test_repeated_forbidden_calls_without_alternate_fail_once_and_stop(
    answer_recovery_runner,
) -> None:
    output, calls, original_history = await answer_recovery_runner(
        [[_forbidden_tool_call(1)], [_forbidden_tool_call(2)]],
        alternate_model=None,
    )

    assert [call["model_id"] for call in calls] == ["answer-primary", "answer-primary"]
    _assert_clean_recovery_payload(calls[1])
    failures = [
        chunk
        for chunk in output
        if isinstance(chunk, dict) and chunk.get("__main_processing_failure__") is True
    ]
    assert failures == [
        {"__main_processing_failure__": True, "reason": "empty_post_tool_response"}
    ]
    assert CURRENT_REQUEST in json.dumps(original_history)
    assert CITATION_URL in json.dumps(original_history)
    assert EMBED_REFERENCE in json.dumps(original_history)
    assert not any(isinstance(chunk, str) and chunk for chunk in output)
    _assert_usage(output, calls=2, successful_model=None)
