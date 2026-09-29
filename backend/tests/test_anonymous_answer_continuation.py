# contract-test-file: infrastructure
"""Integrated anonymous metering coverage across tool-assisted answer continuation."""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.apps.ai.llm_providers.google_client import (
    GoogleUsageMetadata,
    ParsedGoogleToolCall,
)
from backend.apps.ai.processing import main_processor
from backend.apps.ai.processing.model_usage_tracker import calculate_model_usage_credits
from backend.apps.ai.utils import llm_utils
from backend.apps.ai.utils.tool_protocol_guard import ToolProtocolGuard
from backend.shared.python_schemas.app_metadata_schemas import (
    AppPricing,
    AppSkillDefinition,
    AppYAML,
)


pytestmark = pytest.mark.asyncio

PRIMARY_MODEL = "google/anonymous-primary"
ALTERNATE_MODEL = "google/anonymous-alternate"
PARENT_REQUEST_ID = "anonymous-parent-request"
EVIDENCE_URL = "https://evidence.test/anonymous-budget"
FINAL_ANSWER = "The retained evidence supports continuing the answer within the budget."

MODEL_PRICING = {
    "features": {"max_output_tokens": 3_800},
    "pricing": {
        "tokens": {
            "input": {"per_credit_unit": 1_000_000_000},
            "output": {"per_credit_unit": 10},
        }
    },
}


def _usage() -> GoogleUsageMetadata:
    # Each attempt costs a fractional 0.6 output credit. The first checkpoint
    # rounds to one; the cumulative 1.2 credits still rounds to one, so the
    # second checkpoint must carry the fraction and submit a zero delta.
    return GoogleUsageMetadata(
        prompt_token_count=10,
        candidates_token_count=6,
        total_token_count=16,
        user_input_tokens=4,
        system_prompt_tokens=6,
    )


def _tool_call() -> ParsedGoogleToolCall:
    arguments = {"requests": [{"id": "search-1", "query": "budget evidence"}]}
    return ParsedGoogleToolCall(
        tool_call_id="tool-search-1",
        function_name="web-search",
        function_arguments_raw=json.dumps(arguments),
        function_arguments_parsed=arguments,
    )


def _skill_definition() -> AppSkillDefinition:
    return AppSkillDefinition(
        id="search",
        name_translation_key="apps.web.skills.search.name",
        description_translation_key="apps.web.skills.search.description",
        class_path="unused.in.integration.test",
        anonymous_access="inline",
        pricing=AppPricing(per_unit={"credits": 20}),
        providers=[],
        tool_schema={
            "type": "object",
            "properties": {
                "requests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "query": {"type": "string"},
                        },
                        "required": ["id", "query"],
                    },
                }
            },
            "required": ["requests"],
        },
    )


def _request() -> SimpleNamespace:
    request = SimpleNamespace(
        chat_id="anonymous-chat",
        message_id="anonymous-message",
        user_id="",
        user_id_hash="",
        user_preferences={},
        mentioned_settings_memories_cleartext=None,
        historical_artifact_context=None,
        current_user_content="Find the budget evidence and answer from it.",
        active_focus_id=None,
        active_project_focus=None,
        current_project=None,
        current_chat_title=None,
        is_incognito=True,
        is_external=False,
        message_history=[
            {"role": "user", "content": "Find the budget evidence and answer from it."}
        ],
        orchestration_id=None,
        is_sub_chat=False,
        is_sub_chat_continuation=False,
        awaiting_async_skill_continuation=False,
        mate_id="mate-anonymous",
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
        is_anonymous=True,
        anonymous_reservation_id=PARENT_REQUEST_ID,
        has_image_upload_embed=False,
        embed_file_path_index=None,
    )
    request.resolved_recovery_inference_task_id = lambda: None
    request.model_dump = lambda **_kwargs: request.__dict__.copy()
    return request


def _preprocessing() -> SimpleNamespace:
    return SimpleNamespace(
        load_app_settings_and_memories=[],
        rejection_reason=None,
        relevant_app_skills=["web-search"],
        selected_main_llm_model_id=PRIMARY_MODEL,
        selected_main_llm_model_name="Anonymous primary",
        selected_secondary_model_id=None,
        selected_fallback_model_id=ALTERNATE_MODEL,
        selected_mate_id="mate-anonymous",
        category="general",
        output_language="en",
        relevant_embedded_previews=[],
        relevant_focus_modes=[],
        enable_subchats=False,
        llm_response_temp=0.1,
        user_requested_skills_only=False,
        user_requested_focus_only=False,
    )


class AnonymousLedger:
    """Small HTTP-boundary model of one authoritative anonymous request ledger."""

    def __init__(
        self,
        *,
        cap: int = 400,
        deny_second_ai_reserve: bool = False,
        timeline: list[tuple[str, str]] | None = None,
    ) -> None:
        self.cap = cap
        self.deny_second_ai_reserve = deny_second_ai_reserve
        self.spent = 0
        self.operations: dict[str, dict[str, object]] = {}
        self.events: list[tuple[str, dict[str, object]]] = []
        self.ai_reservations = 0
        self.timeline = timeline

    @property
    def available(self) -> int:
        held = sum(int(operation["credits"]) for operation in self.operations.values())
        return max(self.cap - self.spent - held, 0)

    @staticmethod
    def _limit_error(endpoint: str) -> httpx.HTTPStatusError:
        request = httpx.Request("POST", f"http://api.test/{endpoint}")
        response = httpx.Response(429, request=request)
        return httpx.HTTPStatusError("anonymous budget exhausted", request=request, response=response)

    async def request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, object] | None = None,
        **_kwargs,
    ) -> dict[str, object]:
        assert method == "POST"
        body = copy.deepcopy(payload or {})
        self.events.append((endpoint, body))
        if self.timeline is not None:
            detail = str(body.get("operation_id") or body.get("parent_request_id") or "")
            self.timeline.append((endpoint, detail))

        if endpoint.endswith("request-budget"):
            assert body == {"parent_request_id": PARENT_REQUEST_ID}
            return {"available_credits": self.available}

        if endpoint.endswith("reserve-operation"):
            operation_id = str(body["operation_id"])
            quoted_credits = int(body["quoted_credits"])
            is_ai = operation_id.startswith("ai-ask:")
            if is_ai:
                self.ai_reservations += 1
                if self.deny_second_ai_reserve and self.ai_reservations == 2:
                    raise self._limit_error(endpoint)
            if quoted_credits > self.available:
                raise self._limit_error(endpoint)
            self.operations[operation_id] = {
                "charge_id": str(body["charge_id"]),
                "credits": quoted_credits,
            }
            return {"status": "reserved", "reserved_credits": quoted_credits}

        if endpoint.endswith("checkpoint-operation"):
            operation_id = str(body["operation_id"])
            checkpoint_credits = int(body["checkpoint_credits"])
            assert checkpoint_credits <= int(self.operations[operation_id]["credits"])
            self.operations[operation_id]["credits"] = checkpoint_credits
            return {"status": "checkpointed", "checkpoint_credits": checkpoint_credits}

        if endpoint.endswith("finalize-charge"):
            charge_id = str(body["charge_id"])
            actual_credits = int(body["actual_credits"])
            matching = [
                operation_id
                for operation_id, operation in self.operations.items()
                if operation["charge_id"] == charge_id
            ]
            assert matching
            for operation_id in matching:
                self.operations.pop(operation_id)
            self.spent += actual_credits
            return {"status": "finalized", "actual_credits": actual_credits}

        if endpoint.endswith("release-operation"):
            self.operations.pop(str(body["operation_id"]), None)
            return {"status": "released"}

        raise AssertionError(f"Unexpected internal request: {endpoint} {body}")


@pytest.fixture
def anonymous_continuation_runner(monkeypatch):
    provider_calls: list[dict] = []
    skill_dispatch = AsyncMock(
        name="execute_skill_with_multiple_requests",
        return_value=[
            {
                "results": [
                    {
                        "id": "search-1",
                        "results": [
                            {
                                "title": "Retained budget evidence",
                                "url": EVIDENCE_URL,
                                "description": "The completed tool result remains available.",
                            }
                        ],
                        "error": None,
                    }
                ],
                "provider": "test-provider",
                "error": None,
            }
        ],
    )

    class NoHealthCache:
        def __init__(self) -> None:
            self.client = asyncio.sleep(0, result=None)

    async def no_task_queue_retry(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main_processor, "MAX_TOOL_CALL_ITERATIONS", 2)
    monkeypatch.setattr(main_processor, "MAX_ANSWER_ONLY_RECOVERY_ITERATIONS", 2)
    monkeypatch.setattr(main_processor, "resolve_sub_chat_depth", lambda _request: 0)
    monkeypatch.setattr(main_processor, "has_transcribed_web_audio_recording", lambda _history: False)
    monkeypatch.setattr(
        main_processor,
        "should_include_embeds_results_view_instruction",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(main_processor, "normalize_wikipedia_language", lambda _language: "en")
    monkeypatch.setattr(
        main_processor,
        "TranslationService",
        lambda: SimpleNamespace(get_nested_translation=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        main_processor,
        "generate_tools_from_apps",
        lambda **_kwargs: [
            {
                "type": "function",
                "function": {
                    "name": "web-search",
                    "description": "Search the web",
                    "parameters": _skill_definition().tool_schema,
                },
            }
        ],
    )
    monkeypatch.setattr(main_processor, "evaluate_task_queue_post_turn", no_task_queue_retry)
    monkeypatch.setattr(main_processor, "model_history_token_budget", lambda *_args, **_kwargs: 100_000)
    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", skill_dispatch)
    monkeypatch.setattr(llm_utils, "CacheService", NoHealthCache)
    monkeypatch.setattr(
        llm_utils,
        "resolve_default_server_from_provider_config",
        lambda _model: (None, None),
    )
    assert main_processor.call_main_llm_stream is llm_utils.call_main_llm_stream
    assert main_processor.ToolProtocolGuard is ToolProtocolGuard

    async def run(
        *,
        deny_second_ai_reserve: bool,
        timeout_before_text: bool = False,
        hidden_server_fallback: bool = False,
        pricing: dict | None = None,
    ) -> tuple[list[object], list[dict], AnonymousLedger]:
        calls_before = len(provider_calls)
        timeline: list[tuple[str, str]] = []

        monkeypatch.setattr(
            main_processor.config_manager,
            "get_model_pricing",
            lambda *_args: pricing or MODEL_PRICING,
        )
        monkeypatch.setattr(
            llm_utils,
            "resolve_fallback_servers_from_provider_config",
            lambda model_id: (
                ["google/hidden-server"]
                if hidden_server_fallback and model_id == PRIMARY_MODEL
                else []
            ),
        )

        async def fake_google_provider(**kwargs):
            call_number = len(provider_calls) - calls_before + 1
            provider_calls.append(copy.deepcopy(kwargs))
            timeline.append(("provider", str(kwargs["model_id"])))

            async def stream():
                if timeout_before_text and call_number == 1:
                    yield _usage()
                    raise TimeoutError("server A timed out after reporting usage")
                if not timeout_before_text and call_number == 1:
                    yield _tool_call()
                else:
                    yield FINAL_ANSWER
                yield _usage()

            return stream()

        monkeypatch.setitem(llm_utils.PROVIDER_CLIENT_REGISTRY, "google", fake_google_provider)
        ledger = AnonymousLedger(
            deny_second_ai_reserve=deny_second_ai_reserve,
            timeline=timeline,
        )
        monkeypatch.setattr(main_processor, "_make_internal_api_request", ledger.request)

        skill = _skill_definition()
        output = [
            chunk
            async for chunk in main_processor.handle_main_processing(
                "task-anonymous-continuation",
                _request(),
                _preprocessing(),
                {},
                None,
                None,
                None,
                [],
                discovered_apps_metadata={
                    "web": AppYAML(
                        id="web",
                        name_translation_key="apps.web.name",
                        description_translation_key="apps.web.description",
                        skills=[skill],
                    )
                },
                user_overrides=SimpleNamespace(skills=None, wikipedia_references=[]),
            )
        ]
        ledger.timeline = timeline
        return output, provider_calls[calls_before:], ledger

    return SimpleNamespace(run=run, skill_dispatch=skill_dispatch)


def _failure_markers(output: list[object]) -> list[dict]:
    return [
        item
        for item in output
        if isinstance(item, dict) and item.get("__main_processing_failure__") is True
    ]


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_checkpoint_releases_first_ai_hold_before_skill_and_fits_final_answer(
    anonymous_continuation_runner,
) -> None:
    output, calls, ledger = await anonymous_continuation_runner.run(
        deny_second_ai_reserve=False
    )

    assert [call["model_id"] for call in calls] == ["anonymous-primary", "anonymous-primary"]
    assert calls[0]["max_tokens"] == 3_800
    assert calls[1]["max_tokens"] < calls[0]["max_tokens"]
    assert calls[1]["tool_choice"] == "none"
    assert calls[1]["tools"] is None
    assert EVIDENCE_URL in json.dumps(calls[1]["messages"])
    anonymous_continuation_runner.skill_dispatch.assert_awaited_once()

    event_names = [event[0] for event in ledger.events]
    first_checkpoint = event_names.index("internal/anonymous-usage/checkpoint-operation")
    skill_reserve = next(
        index
        for index, (endpoint, payload) in enumerate(ledger.events)
        if endpoint.endswith("reserve-operation")
        and not str(payload["operation_id"]).startswith("ai-ask:")
    )
    second_budget = [
        index
        for index, endpoint in enumerate(event_names)
        if endpoint.endswith("request-budget")
    ][1]
    assert first_checkpoint < skill_reserve < second_budget

    ai_reserves = [
        payload
        for endpoint, payload in ledger.events
        if endpoint.endswith("reserve-operation")
        and str(payload["operation_id"]).startswith("ai-ask:")
    ]
    assert int(ai_reserves[0]["quoted_credits"]) >= 380
    assert int(ai_reserves[1]["quoted_credits"]) <= 379
    assert ledger.spent == 20

    checkpoints = [
        int(payload["checkpoint_credits"])
        for endpoint, payload in ledger.events
        if endpoint.endswith("checkpoint-operation")
    ]
    assert checkpoints == [1, 0]

    sentinels = [
        item
        for item in output
        if isinstance(item, dict) and item.get("__cumulative_llm_usage__") is True
    ]
    assert len(sentinels) == 1
    terminal_credits = calculate_model_usage_credits(
        sentinels[0]["usage_by_model"],
        main_processor.config_manager.get_model_pricing,
    )
    assert terminal_credits == sum(checkpoints) == 1
    assert FINAL_ANSWER in "".join(item for item in output if isinstance(item, str))
    assert _failure_markers(output) == []

    tool_info = next(
        item["__tool_calls_info__"]
        for item in output
        if isinstance(item, dict) and "__tool_calls_info__" in item
    )
    assert tool_info[0]["anonymous_embeds"]
    assert EVIDENCE_URL in json.dumps(tool_info)


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_denied_continuation_stops_before_fallback_and_keeps_completed_tool_artifact(
    anonymous_continuation_runner,
) -> None:
    output, calls, ledger = await anonymous_continuation_runner.run(
        deny_second_ai_reserve=True
    )

    assert [call["model_id"] for call in calls] == ["anonymous-primary"]
    anonymous_continuation_runner.skill_dispatch.assert_awaited_once()
    assert _failure_markers(output) == [
        {"__main_processing_failure__": True, "reason": "anonymous_usage_limit"}
    ]
    assert FINAL_ANSWER not in "".join(item for item in output if isinstance(item, str))

    tool_info = next(
        item["__tool_calls_info__"]
        for item in output
        if isinstance(item, dict) and "__tool_calls_info__" in item
    )
    assert tool_info[0]["anonymous_embeds"]
    assert EVIDENCE_URL in json.dumps(tool_info)
    assert ledger.spent == 20
    assert ledger.ai_reservations == 2
    assert not any(call["model_id"] == "anonymous-alternate" for call in calls)


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_precontent_timeout_keeps_full_hold_and_retries_under_new_reservation(
    anonymous_continuation_runner,
) -> None:
    small_quote_pricing = copy.deepcopy(MODEL_PRICING)
    small_quote_pricing["features"]["max_output_tokens"] = 100
    output, calls, ledger = await anonymous_continuation_runner.run(
        deny_second_ai_reserve=False,
        timeout_before_text=True,
        hidden_server_fallback=True,
        pricing=small_quote_pricing,
    )

    # The wrapper must return control after server A fails. Its configured
    # hidden server shares the old reservation and therefore cannot be tried.
    assert [call["model_id"] for call in calls] == [
        "anonymous-primary",
        "anonymous-alternate",
    ]
    assert all(call["model_id"] != "hidden-server" for call in calls)
    anonymous_continuation_runner.skill_dispatch.assert_not_awaited()

    ai_reserve_events = [
        (index, payload)
        for index, (endpoint, payload) in enumerate(ledger.events)
        if endpoint.endswith("reserve-operation")
        and str(payload["operation_id"]).startswith("ai-ask:")
    ]
    assert len(ai_reserve_events) == 2
    failed_operation_id = str(ai_reserve_events[0][1]["operation_id"])
    successful_operation_id = str(ai_reserve_events[1][1]["operation_id"])
    assert failed_operation_id != successful_operation_id
    assert "model:google/anonymous-primary" in failed_operation_id
    assert "model:google/anonymous-alternate" in successful_operation_id

    checkpointed_operation_ids = [
        str(payload["operation_id"])
        for endpoint, payload in ledger.events
        if endpoint.endswith("checkpoint-operation")
    ]
    assert checkpointed_operation_ids == [successful_operation_id]
    assert int(ledger.operations[failed_operation_id]["credits"]) == int(
        ai_reserve_events[0][1]["quoted_credits"]
    )
    assert int(ledger.operations[successful_operation_id]["credits"]) == 1

    timeline = ledger.timeline or []
    first_reserve_position = timeline.index(
        ("internal/anonymous-usage/reserve-operation", failed_operation_id)
    )
    first_provider_position = timeline.index(("provider", "anonymous-primary"))
    second_reserve_position = timeline.index(
        ("internal/anonymous-usage/reserve-operation", successful_operation_id)
    )
    second_provider_position = timeline.index(("provider", "anonymous-alternate"))
    assert first_reserve_position < first_provider_position < second_reserve_position
    assert second_reserve_position < second_provider_position

    assert FINAL_ANSWER in "".join(item for item in output if isinstance(item, str))
    assert _failure_markers(output) == []
