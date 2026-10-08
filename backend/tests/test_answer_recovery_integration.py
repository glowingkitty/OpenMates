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

from backend.apps.ai.llm_providers.anthropic_shared import AnthropicUsageMetadata
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
CURRENT_TOOL_EVIDENCE = "A newly completed search favors option one."
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


def _completed_tool_call() -> ParsedGoogleToolCall:
    return ParsedGoogleToolCall(
        tool_call_id="current-search",
        function_name="web-search",
        function_arguments_raw=json.dumps({"query": "latest comparison"}),
        function_arguments_parsed={"query": "latest comparison"},
        thought_signature="current-signature",
        provider_transport_state={
            GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY: "google_ai_studio"
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


def _anthropic_usage(call_number: int) -> AnthropicUsageMetadata:
    return AnthropicUsageMetadata(
        input_tokens=10 + call_number,
        output_tokens=call_number,
        total_tokens=10 + (2 * call_number),
        user_input_tokens=4,
        system_prompt_tokens=3,
    )


def _seeded_history(*, signature_provider: str = "google") -> list[dict]:
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
                        GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY: signature_provider
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
    alternate_model: str | None,
    secondary_model: str | None = None,
    *,
    primary_model: str = PRIMARY_MODEL,
) -> SimpleNamespace:
    return SimpleNamespace(
        load_app_settings_and_memories=[],
        rejection_reason=None,
        relevant_app_skills=[],
        selected_main_llm_model_id=primary_model,
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

    async def reserve_test_turn(**kwargs):
        return kwargs.get("requested_output_token_limit") or 1024

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
    monkeypatch.setattr(main_processor, "_reserve_authenticated_ai_turn", reserve_test_turn)
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
        primary_model: str = PRIMARY_MODEL,
        signature_provider: str = "google",
        live_tool_call: bool = False,
    ) -> tuple[list[object], list[dict], list[dict]]:
        calls_before = len(provider_calls)
        skill_dispatch.reset_mock()
        if live_tool_call:
            monkeypatch.setattr(main_processor, "MAX_TOOL_CALL_ITERATIONS", 2)
            monkeypatch.setattr(
                main_processor,
                "generate_tools_from_apps",
                lambda **_kwargs: [
                    {
                        "type": "function",
                        "function": {
                            "name": "web-search",
                            "description": "Search the web",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            )
            skill_dispatch.return_value = [{
                "status": "success",
                "summary": CURRENT_TOOL_EVIDENCE,
            }]
        discovered_apps = (
            {"web": SimpleNamespace(
                skills=[SimpleNamespace(
                    id="search",
                    tool_schema={"type": "object", "properties": {}},
                    exclude_fields_for_llm=[],
                )],
                instructions=[],
            )}
            if live_tool_call else {}
        )

        monkeypatch.setattr(
            llm_utils,
            "resolve_fallback_servers_from_provider_config",
            lambda model_id: (
                ["google/hidden-server"]
                if hidden_server_fallback and model_id == primary_model
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
                yield (
                    _anthropic_usage(call_number)
                    if provider_id == "anthropic"
                    else _usage(call_number)
                )

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
            "google_ai_studio",
            fake_google_provider,
        )
        monkeypatch.setitem(
            llm_utils.PROVIDER_CLIENT_REGISTRY,
            "anthropic",
            fake_anthropic_provider,
        )

        history = _seeded_history(signature_provider=signature_provider)
        original_history = copy.deepcopy(history)
        output = [
            chunk
            async for chunk in main_processor.handle_main_processing(
                "task-answer-recovery",
                _request(history),
                _preprocessing(
                    alternate_model, secondary_model, primary_model=primary_model
                ),
                {},
                None,
                None,
                None,
                [],
                discovered_apps_metadata=discovered_apps,
                user_overrides=SimpleNamespace(skills=None, wikipedia_references=[]),
            )
        ]
        assert history == original_history
        if live_tool_call:
            skill_dispatch.assert_awaited_once()
        else:
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
@pytest.mark.parametrize("alternate_succeeds", [True, False])
async def test_fabricated_protocol_uses_clean_context_and_one_configured_alternate(
    answer_recovery_runner, alternate_succeeds: bool,
) -> None:
    safe_prefix = "A verified opening paragraph.\n\n"
    protocol = "```toon\napp_id: web\nskill_id: search\nstatus: finished\n```"
    output, calls, _original_history = await answer_recovery_runner(
        [[safe_prefix + protocol + "\nInvented evidence."], [protocol],
         [ANSWER if alternate_succeeds else protocol]],
        alternate_model=CROSS_PROVIDER_MODEL,
        secondary_model=ALTERNATE_MODEL,
    )

    assert [call["model_id"] for call in calls] == [
        "answer-primary", "answer-primary", "answer-alternate",
    ]
    assert [call["provider_id"] for call in calls] == ["google", "google", "anthropic"]
    for call in calls[1:]:
        _assert_clean_recovery_payload(call)
        system_messages = [
            message["content"]
            for message in call["messages"]
            if message["role"] == "system"
        ]
        assert len(system_messages) == 1
        assert main_processor.ANSWER_RECOVERY_INSTRUCTION in system_messages[0]
        assert "Invented evidence." not in json.dumps(call["messages"])
        assert "status: finished" not in json.dumps(call["messages"])
    assert "".join(chunk for chunk in output if isinstance(chunk, str)) == (
        safe_prefix + (ANSWER if alternate_succeeds else "")
    )
    failures = [chunk for chunk in output if isinstance(chunk, dict) and chunk.get("__main_processing_failure__")]
    assert failures == ([] if alternate_succeeds else [
        {"__main_processing_failure__": True, "reason": "protocol_guard"},
    ])
    _assert_usage(output, calls=3, successful_model=CROSS_PROVIDER_MODEL if alternate_succeeds else PRIMARY_MODEL)


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


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
async def test_first_answer_partial_503_recovers_without_replaying_signed_tool_history(
    answer_recovery_runner,
) -> None:
    primary_model = "google_ai_studio/answer-primary"
    prefix = "The completed searches favor option one.\n\n"
    suffix = f"See [the primary source]({CITATION_URL})."
    output, calls, _original_history = await answer_recovery_runner(
        [
            [_completed_tool_call()],
            [prefix, _usage(2), RuntimeError("503 high demand")],
            [suffix],
        ],
        alternate_model=CROSS_PROVIDER_MODEL,
        primary_model=primary_model,
        signature_provider="google_ai_studio",
        hidden_server_fallback=True,
        live_tool_call=True,
    )

    # The second call has completed signed tool evidence but recovery is not yet
    # active. The hidden Google server is incompatible with those signatures;
    # recovering from clean evidence keeps the prefix and avoids replaying it.
    assert [call["model_id"] for call in calls] == [
        "answer-primary",
        "answer-primary",
        "answer-primary",
    ]
    assert "current-signature" in json.dumps(calls[1]["messages"])
    assert CURRENT_TOOL_EVIDENCE in json.dumps(calls[1]["messages"])
    _assert_clean_recovery_payload(calls[2])
    assert CURRENT_TOOL_EVIDENCE in json.dumps(calls[2]["messages"])
    assert "ALREADY PUBLISHED TO THE USER" in json.dumps(calls[2]["messages"])
    published = "".join(chunk for chunk in output if isinstance(chunk, str))
    assert published == prefix + suffix
    assert published.count(prefix) == 1
    assert llm_utils.STANDARDIZED_USER_ERROR_MESSAGE not in published
    assert not any(
        isinstance(chunk, dict) and chunk.get("__main_processing_failure__") is True
        for chunk in output
    )
    _assert_usage(output, calls=3, successful_model=primary_model)


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
async def test_partial_503_clean_recovery_exhausts_compatible_models_once(
    answer_recovery_runner,
) -> None:
    primary_model = "google_ai_studio/answer-primary"
    prefix = "The completed searches favor option one.\n\n"
    output, calls, _original_history = await answer_recovery_runner(
        [
            [_completed_tool_call()],
            [prefix, _usage(2), RuntimeError("503 high demand")],
            [_usage(3), RuntimeError("503 high demand")],
            [_usage(4), RuntimeError("503 high demand")],
        ],
        alternate_model=CROSS_PROVIDER_MODEL,
        primary_model=primary_model,
        signature_provider="google_ai_studio",
        live_tool_call=True,
    )

    assert len(calls) == 4
    assert calls[-1]["provider_id"] == "anthropic"
    _assert_clean_recovery_payload(calls[2])
    _assert_clean_recovery_payload(calls[3])
    failures = [
        chunk
        for chunk in output
        if isinstance(chunk, dict) and chunk.get("__main_processing_failure__") is True
    ]
    assert failures == [
        {"__main_processing_failure__": True, "reason": "provider_exhausted"}
    ]
    assert "".join(chunk for chunk in output if isinstance(chunk, str)) == prefix
