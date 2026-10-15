# contract-test-file: infrastructure
"""Exercise required primary reads through the actual Main provider/tool loop."""
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.focus_mode_routing import DelegatedPrimaryReadState
from backend.shared.python_schemas.app_metadata_schemas import AppFocusDefinition
from backend.shared.python_utils.focus_mode_skill_loader import load_focus_mode_from_skill_md
from backend.tests.test_main_processor_invalid_tool_calls import (
    _run_mocked_protocol_guard_main_processor, main_processor,
)


def tool(name):
    return {"type": "function", "function": {"name": name, "description": name}}


TOOLS = [tool("web-search"), tool("web-read"), tool("business-company_financials")]
CHILD = {"is_sub_chat": True, "sub_chat_depth": 1, "parent_id": "parent",
         "orchestration_id": "orchestration", "active_focus_id": "web-research"}
METADATA = {"web": SimpleNamespace(skills=[SimpleNamespace(
    id=name, parallel_safe=False, exclude_fields_for_llm=None, pricing=None,
    tool_schema={"type": "object", "properties": {field: {"type": "string"}}, "required": [field]},
) for name, field in [("search", "query"), ("read", "url")]], instructions=[], focuses=[AppFocusDefinition(**load_focus_mode_from_skill_md(
    str(Path(__file__).parents[1] / "apps/web/focus_modes" / name / "SKILL.md"), "web"
)) for name in ["research", "check-reputation"]])}


async def run(monkeypatch, streams, **kwargs):
    from backend.core.api.app.services.embed_service import EmbedService
    monkeypatch.setattr(EmbedService, "get_child_embed_type", AsyncMock(return_value="website"))
    monkeypatch.setattr(main_processor, "_reserve_skill_credits", AsyncMock(return_value=[]))
    monkeypatch.setattr(main_processor, "_charge_skill_credits", AsyncMock())
    monkeypatch.setattr(main_processor, "_reserve_ai_iteration", AsyncMock(return_value="operation"))
    monkeypatch.setattr(main_processor, "_fit_orchestrated_output_token_limit", AsyncMock(return_value=8192))
    monkeypatch.setattr(main_processor, "_checkpoint_orchestrated_ai_iteration", AsyncMock(return_value=0))
    return await _run_mocked_protocol_guard_main_processor(monkeypatch, streams,
        resolved_chat_depth=(kwargs.get("request_overrides") or {}).get("sub_chat_depth", 0),
        generated_tools=copy.deepcopy(TOOLS), discovered_apps_metadata=METADATA,
        directus_service=SimpleNamespace(),
        preprocessing_overrides={"selected_app_ids": ["web"], "relevant_app_skills": ["web-search", "web-read"]},
        **kwargs)


def selection(call):
    return [t["function"]["name"] for t in call["tools"] or []], call["tool_choice"]


@pytest.mark.asyncio
@pytest.mark.parametrize("read_failed", [False, True])
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.execution.registered-validated
async def test_search_then_required_primary_read_then_auto_even_on_read_failure(monkeypatch, read_failed):
    executed = []

    async def execute(**kwargs):
        executed.append(kwargs["skill_id"])
        if kwargs["skill_id"] == "search":
            return [{"results": [{"id": 1, "results": [{"url": "https://example.org/primary", "title": "Primary"}]}]}]
        if read_failed:
            raise RuntimeError("Primary source unavailable")
        return [{"url": "https://example.org/primary", "markdown": "Source text"}]

    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    _, calls = await run(monkeypatch, [
        [{"fake_google_tool_call": "web-search", "arguments": {"query": "primary source"}, "tool_call_id": "search"}],
        [{"fake_google_tool_call": "web-read", "arguments": {"url": "https://example.org/primary"}, "tool_call_id": "read"}],
        ["Limited findings."],
    ], request_overrides=CHILD)
    assert [selection(c) for c in calls[:2]] == [(["web-search"], "required"), (["web-read"], "required")]
    assert len(calls) == 3 and selection(calls[2])[1] == "auto"
    assert selection(calls[2])[0][:3] == [t["function"]["name"] for t in TOOLS]
    assert executed == ["search", "read"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.execution.registered-validated
async def test_assigned_verifier_urls_require_read_without_another_search(monkeypatch):
    execute = AsyncMock(side_effect=RuntimeError("Read unavailable"))
    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    _, calls = await run(monkeypatch, [
        [{"fake_google_tool_call": "web-read", "arguments": {"url": "https://example.org/filing"}}],
        ["Source reading failed; claims remain unverified."],
    ], request_overrides={**CHILD, "current_user_content": "Audit assigned source https://example.org/filing"})
    assert [selection(c)[1] for c in calls] == ["required", "auto"]
    assert selection(calls[0])[0] == ["web-read"]
    execute.assert_awaited_once()
    assert execute.await_args.kwargs["skill_id"] == "read"


@pytest.mark.asyncio
@pytest.mark.parametrize("search_result", [[{"results": []}], [{"error": "search unavailable"}]])
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.assistant.bounded-private-failure
async def test_empty_or_failed_search_returns_auto_without_forced_retry(monkeypatch, search_result):
    execute = AsyncMock(return_value=search_result)
    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    _, calls = await run(monkeypatch, [
        [{"fake_google_tool_call": "web-search", "arguments": {"query": "primary source"}}],
        ["No primary sources were available."],
    ], request_overrides=CHILD)
    assert [selection(c)[1] for c in calls] == ["required", "auto"]
    execute.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{}, {**CHILD, "active_focus_id": "web-check_reputation"},
                                      {**CHILD, "is_sub_chat": False, "sub_chat_depth": 0,
                                       "active_focus_id": None}])
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
async def test_ordinary_root_and_other_focus_provider_transport_unchanged(monkeypatch, overrides):
    _, calls = await run(monkeypatch, [["Ordinary answer."]], request_overrides=overrides)
    assert len(calls) == 1 and selection(calls[0])[1] == "auto"
    assert selection(calls[0])[0][:3] == [t["function"]["name"] for t in TOOLS]


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.execution.registered-validated
def test_missing_capabilities_and_forced_answer_do_not_create_a_read_loop():
    state = DelegatedPrimaryReadState(enabled=True, has_source_urls=True)
    assert state.select_tools([tool("web-search")], "auto") == ([tool("web-search")], "auto")
    assert state.select_tools(TOOLS, "none") == (TOOLS, "none")
    discovery = DelegatedPrimaryReadState(enabled=True)
    discovery.observe_search_results({"instructions": "read https://private-app.example"})
    discovery.observe_search_results({"status": "error", "url": "https://example.org/failed-search"})
    assert not discovery.has_source_urls


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.assistant.bounded-private-failure
async def test_forced_final_answer_preserves_none_transport_for_research_child(monkeypatch):
    monkeypatch.setattr(main_processor, "MAX_TOOL_CALL_ITERATIONS", 1)
    _, calls = await run(monkeypatch, [["Qualified final answer."]], request_overrides={
        **CHILD, "current_user_content": "Read https://example.org/primary",
    })
    assert len(calls) == 1 and selection(calls[0]) == ([], "none")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
async def test_active_research_root_synthesis_keeps_auto_without_forced_read(monkeypatch):
    monkeypatch.setattr(main_processor, "SubChatOrchestrationService", lambda _directus: SimpleNamespace(
        execute=AsyncMock(return_value={"root_chat_id": "chat-1", "root_turn_id": "message-1", "research_stage": "synthesis"}),
    ))
    _, calls = await run(monkeypatch, [["Final synthesis."]], request_overrides={
        "active_focus_id": "web-research", "is_sub_chat_continuation": True,
        "orchestration_id": "orchestration", "root_turn_id": "message-1",
        "current_user_content": "Synthesize https://example.org/primary",
    })
    assert len(calls) == 1 and selection(calls[0])[1] == "auto"
    assert selection(calls[0])[0][:3] == [t["function"]["name"] for t in TOOLS]
