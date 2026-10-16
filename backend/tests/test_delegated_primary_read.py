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
        preprocessing_overrides={"selected_app_ids": ["web"], "relevant_app_skills": ["web-search", "web-read"],
                                 **kwargs.pop("preprocessing_overrides", {})},
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



def batch_schema_fixture(monkeypatch):
    import sys
    import yaml
    app = yaml.safe_load((Path(__file__).parents[1] / "apps/web/app.yml").read_text())
    schemas = {skill["id"]: skill["tool_schema"] for skill in app["skills"] if skill["id"] in {"search", "read"}}
    offered = [tool("web-" + name) for name in ["search", "read"]]
    for definition in offered:
        definition["function"]["parameters"] = copy.deepcopy(schemas[definition["function"]["name"][4:]])
    monkeypatch.setattr(sys.modules[__name__], "TOOLS", offered)
    web = copy.copy(METADATA["web"])
    web.skills = [SimpleNamespace(id=name, parallel_safe=False, exclude_fields_for_llm=None,
                                 pricing=None, tool_schema=schema) for name, schema in schemas.items()]
    monkeypatch.setitem(METADATA, "web", web)


@pytest.mark.asyncio
@pytest.mark.parametrize("search_count,read_fails", [(4, False), (5, False), (5, True)])
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.assistant.bounded-private-failure,app-skills.execution.registered-validated
async def test_actual_four_or_five_search_batch_leaves_one_admitted_primary_read(monkeypatch, search_count, read_fails):
    batch_schema_fixture(monkeypatch)
    executed = []

    async def execute(**kwargs):
        requests = copy.deepcopy(kwargs["arguments"]["requests"])
        executed.append((kwargs["skill_id"], requests))
        if kwargs["skill_id"] == "read" and read_fails:
            raise RuntimeError("Source unavailable")
        return [{"results": [{"id": r["id"], "results": [{"url": r.get("url", "https://example.org/source"),
                            "title": "Source", "markdown": "Primary text"}]} for r in requests]}]

    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    searches = [{"id": i, "query": f"source {i}"} for i in range(search_count)]
    reads = [{"id": i, "url": f"https://example.org/source/{i}"} for i in range(4)]
    _, calls = await run(monkeypatch, [
        [{"fake_google_tool_call": "web-search", "arguments": {"requests": searches}, "tool_call_id": "search-batch"}],
        [{"fake_google_tool_call": "web-read", "arguments": {"requests": reads}, "tool_call_id": "read-batch"}],
        ["Qualified findings."],
    ], request_overrides=CHILD)
    assert executed == [("search", searches[:4]), ("read", reads[:1])]
    assert sum(len(requests) for _, requests in executed) == main_processor.HARD_LIMIT_SKILL_CALLS == 5
    assert [selection(call)[1] for call in calls] == ["required", "required", "none"]
    assert calls[0]["tools"][0]["function"]["parameters"]["properties"]["requests"]["maxItems"] == 4
    assert calls[1]["tools"][0]["function"]["parameters"]["properties"]["requests"]["maxItems"] == 1
    results = [m for m in calls[-1]["message_history"] if m.get("role") == "tool"]
    read_result = next(m["content"] for m in results if m.get("tool_call_id") == "read-batch")
    assert "omitted_requests" in read_result and reads[3]["url"] in read_result
    if search_count == 5:
        search_result = next(m["content"] for m in results if m.get("tool_call_id") == "search-batch")
        assert "omitted_requests" in search_result and searches[4]["query"] in search_result


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.execution.registered-validated
async def test_multiple_search_function_calls_share_one_read_reservation(monkeypatch):
    batch_schema_fixture(monkeypatch)
    executed = []

    async def execute(**kwargs):
        requests = copy.deepcopy(kwargs["arguments"]["requests"])
        executed.append((kwargs["skill_id"], requests))
        return [{"results": [{"id": r["id"], "results": [{"url": "https://example.org/primary", "title": "Source"}]} for r in requests]}]

    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    batches = [[{"id": i, "query": f"query {i}"} for i in range(start, stop)] for start, stop in [(0, 3), (3, 6), (6, 7)]]
    _, calls = await run(monkeypatch, [
        [{"fake_google_tool_call": "web-search", "arguments": {"requests": requests}, "tool_call_id": f"search-{i}"}
         for i, requests in enumerate(batches)],
        [{"fake_google_tool_call": "web-read", "arguments": {"requests": [{"id": 0, "url": "https://example.org/primary"}]}}],
        ["Qualified findings."],
    ], request_overrides=CHILD)
    assert executed == [("search", batches[0]), ("search", batches[1][:1]),
                        ("read", [{"id": 0, "url": "https://example.org/primary"}])]
    assert selection(calls[1]) == (["web-read"], "required")
    omitted = [m["content"] for m in calls[1]["message_history"] if m.get("tool_call_id") == "search-2" and m.get("role") == "tool"]
    assert len(omitted) == 1 and "omitted_requests" in omitted[0] and "query 6" in omitted[0]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_ordinary_five_search_requests_keep_existing_full_budget(monkeypatch):
    batch_schema_fixture(monkeypatch)
    execute = AsyncMock(return_value=[{"results": [{"id": 0, "results": [{"url": "https://example.org/primary"}]}]}])
    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    searches = [{"id": i, "query": f"source {i}"} for i in range(5)]
    _, calls = await run(monkeypatch, [
        [{"fake_google_tool_call": "web-search", "arguments": {"requests": searches}}],
        ["Final answer."],
    ])
    execute.assert_awaited_once()
    assert execute.await_args.kwargs["arguments"]["requests"] == searches
    assert [selection(call)[1] for call in calls] == ["auto", "none"]


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.assistant.idempotent-resume
def test_checkpointed_pending_read_keeps_remaining_slot_and_budget_rejection_is_not_attempt():
    import json
    # Same private booleans and total_skill_calls already stored by Main; no new
    # schema field, prompt, source content, or paid operation is needed on resume.
    checkpoint = json.loads(json.dumps({"has_source_urls": True, "search_attempted": True, "read_attempted": False}))
    restored = DelegatedPrimaryReadState(enabled=True, **checkpoint)
    bounded, omitted = restored.bound_requests({"requests": [{"url": "https://example.org/primary"}]}, "web-read", 0)
    assert bounded == {"requests": []} and len(omitted) == 1 and not restored.read_attempted
    assert restored.request_limit("web-search", 1) == 0 and restored.request_limit("web-read", 1) == 1
    restored.observe_attempt("web-read")
    assert restored.read_attempted and restored.request_limit("web-search", 4) == 4


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.assistant.bounded-private-failure
async def test_invalid_read_arguments_finish_gate_once_without_forced_retry(monkeypatch):
    for malformed_json in [True, False]:
        with monkeypatch.context() as scoped:
            execute = AsyncMock(side_effect=AssertionError("Invalid read reached execution"))
            scoped.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
            original_normalize = main_processor._normalize_skill_arguments

            def normalize(**kwargs):
                if not malformed_json and kwargs["app_id"] == "web" and kwargs["skill_id"] == "read":
                    raise ValueError("Read schema validation failed")
                return original_normalize(**kwargs)

            scoped.setattr(main_processor, "_normalize_skill_arguments", normalize)
            streams = [[], ["Primary source could not be read; findings remain limited."]]
            provider_calls = []

            def capture(call):
                provider_calls.append(call)
                if len(provider_calls) == 1:
                    chunk = main_processor.ParsedGoogleToolCall()
                    chunk.function_name = "web-read"
                    chunk.function_arguments_raw = "{invalid" if malformed_json else '{"url":"https://example.org/primary"}'
                    chunk.tool_call_id = "invalid-read"
                    streams[0] = [chunk]

            _, calls = await run(scoped, streams, on_provider_call=capture, request_overrides={
                **CHILD, "current_user_content": "Audit https://example.org/primary",
            })
            assert [selection(call)[1] for call in calls] == ["required", "auto"]
            assert len([m for m in calls[1]["message_history"]
                        if m.get("role") == "tool" and m.get("tool_call_id") == "invalid-read"]) == 1
            execute.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.execution.registered-validated
async def test_server_assigned_history_urls_require_read_without_current_content(monkeypatch):
    from backend.core.api.app.schemas.chat import AIHistoryMessage

    prompt = "Independently audit this assigned source: https://example.org/primary"
    # dispatch_sub_chat_task sends the assigned prompt solely in message_history;
    # AskSkillRequest defaults current_user_content to None. Cover both its typed
    # server model and the equivalent JSON payload accepted by the Main fixture.
    scenarios = [
        ({**CHILD, "current_user_content": None, "message_history": [{"role": "user", "content": prompt}]},
         (["web-read"], "required")),
        ({**CHILD, "current_user_content": None, "message_history": [AIHistoryMessage(role="user", content=prompt, created_at=1)]},
         (["web-read"], "required")),
        ({**CHILD, "current_user_content": "Discover the primary evidence first.",
          "message_history": [{"role": "user", "content": prompt}]}, (["web-search"], "required")),
        ({**CHILD, "current_user_content": None, "message_history": [
            {"role": "user", "content": "Discover evidence."},
            {"role": "tool", "content": prompt}]}, (["web-search"], "required")),
        ({"current_user_content": None, "message_history": [{"role": "user", "content": prompt}]},
         ([t["function"]["name"] for t in TOOLS], "auto")),
    ]
    for request, expected in scenarios:
        with monkeypatch.context() as scoped:
            execute = AsyncMock(side_effect=AssertionError("This case checks first provider transport only"))
            scoped.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
            _, calls = await run(scoped, [["Limited findings."]], request_overrides=request)
            assert len(calls) == 1 and selection(calls[0]) == expected
            execute.assert_not_awaited()


ROOT_SYNTHESIS = {"is_sub_chat": False, "sub_chat_depth": 0, "is_sub_chat_continuation": True,
    "orchestration_id": "orchestration", "root_chat_id": "chat-1", "root_turn_id": "message-1",
    "active_focus_id": "web-research", "current_user_content": "Original research question.",
    "message_history": [{"role": "user", "content": "Saved child source URLs: primary: https://example.org/primary"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("read_failed", [False, True])
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
async def test_root_synthesis_reads_seeded_child_source_once_then_restores_auto(monkeypatch, read_failed):
    monkeypatch.setattr(main_processor, "SubChatOrchestrationService", lambda _: SimpleNamespace(execute=AsyncMock(return_value={
        "root_chat_id": "chat-1", "root_turn_id": "message-1", "research_stage": "synthesis", "verifier_batch_id": None})))
    execute = AsyncMock(side_effect=RuntimeError("Primary source unavailable")) if read_failed else AsyncMock(
        return_value=[{"url": "https://example.org/primary", "markdown": "Actual primary source body"}])
    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    _, calls = await run(monkeypatch, [
        [{"fake_google_tool_call": "web-read", "arguments": {"url": "https://example.org/primary"}, "tool_call_id": "primary"}],
        ["Qualified synthesis; unavailable sources remain unverified."],
    ], request_overrides=ROOT_SYNTHESIS)
    assert selection(calls[0]) == (["web-read"], "required")
    assert selection(calls[1])[1] == "auto"
    assert len(calls) == 2
    execute.assert_awaited_once()
    assert execute.await_args.kwargs["skill_id"] == "read"
    assert execute.await_args.kwargs["arguments"]["url"] == "https://example.org/primary"
    assert main_processor.HARD_LIMIT_SKILL_CALLS == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,verifier_batch", [("failed", None), ("synthesis", "legacy-verifier"), (None, None)])
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
async def test_root_failed_and_legacy_continuations_keep_existing_auto_tools(monkeypatch, stage, verifier_batch):
    monkeypatch.setattr(main_processor, "SubChatOrchestrationService", lambda _: SimpleNamespace(execute=AsyncMock(return_value={
        "root_chat_id": "chat-1", "root_turn_id": "message-1", "research_stage": stage, "verifier_batch_id": verifier_batch})))
    _, calls = await run(monkeypatch, [["Qualified synthesis."]], request_overrides=ROOT_SYNTHESIS)
    assert len(calls) == 1 and selection(calls[0])[1] == "auto"
    assert selection(calls[0])[0][:3] == [t["function"]["name"] for t in TOOLS]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["eligible", "ordinary", "legacy", "apps-disabled", "mate-forbidden", "read-unavailable", "exact-request"])
# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.execution.registered-validated
async def test_observed_search_only_catalog_adds_real_read_only_for_authorized_synthesis(monkeypatch, case):
    import importlib.util
    from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition
    # Load the production generator directly: the shared protocol fixture stubs
    # its import and normally supplies a fixed catalogue, masking this regression.
    spec = importlib.util.spec_from_file_location("primary_read_real_tool_generator",
        Path(main_processor.__file__).with_name("tool_generator.py"))
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    web = copy.deepcopy(METADATA["web"])
    web.skills = [AppSkillDefinition(**vars(skill), name_translation_key=f"web.{skill.id}",
        description_translation_key=f"web.{skill.id}.description") for skill in web.skills
        if case != "read-unavailable" or skill.id != "read"]
    monkeypatch.setitem(METADATA, "web", web)
    monkeypatch.setitem(METADATA, "news", SimpleNamespace(skills=[AppSkillDefinition(id="search",
        name_translation_key="news.search", description_translation_key="news.search.description",
        tool_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
        instructions=[], focuses=[]))
    generated = []
    def real_generate(**kwargs):
        tools = generator.generate_tools_from_apps(**kwargs)
        generated.append(tools)
        return tools
    def install(target, name, value, *args, **kwargs):
        monkeypatch.setattr(target, name, real_generate if target is main_processor and name == "generate_tools_from_apps" else value, *args, **kwargs)
    fixture_patches = SimpleNamespace(setattr=install)
    request = dict(ROOT_SYNTHESIS)
    if case == "ordinary":
        request = {}
    if case == "apps-disabled":
        request["user_preferences"] = {"apps_enabled": False}
    monkeypatch.setattr(main_processor, "SubChatOrchestrationService", lambda _: SimpleNamespace(execute=AsyncMock(return_value={
        "root_chat_id": "chat-1", "root_turn_id": "message-1", "research_stage": "synthesis",
        "verifier_batch_id": "legacy-verifier" if case == "legacy" else None})))
    execute = AsyncMock(return_value=[{"url": "https://example.org/primary", "markdown": "Actual primary body"}])
    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    streams = [[{"fake_google_tool_call": "web-read", "arguments": {"url": "https://example.org/primary"}}],
               ["Synthesis based on the primary body."]] if case == "eligible" else [["Qualified answer."]]
    observed_selection = ["news-search", "web-search"]
    _, calls = await run(fixture_patches, streams, request_overrides=request,
        preprocessing_overrides={"selected_app_ids": ["news", "web"], "relevant_app_skills": observed_selection,
                                 "user_requested_skills_only": case == "exact-request"},
        all_mates_configs=[SimpleNamespace(id="mate-1", default_system_prompt="Research assistant.",
            tools=["news"] if case == "mate-forbidden" else None)])
    offered = [tool["function"]["name"] for tool in generated[0]]
    assert "web-read" not in observed_selection
    assert ("web-read" in offered) == (case == "eligible")
    if case == "eligible":
        assert set(offered) == {"news-search", "web-search", "web-read"}
        assert selection(calls[0]) == (["web-read"], "required")
        assert calls[0]["tools"][0]["function"]["parameters"]["required"] == ["url"]
        assert selection(calls[1])[1] == "auto"
        execute.assert_awaited_once()
        assert execute.await_args.kwargs["skill_id"] == "read"
    else:
        assert "web-read" not in selection(calls[0])[0]
        assert selection(calls[0])[1] == "auto"
        execute.assert_not_awaited()
    assert main_processor.HARD_LIMIT_SKILL_CALLS == 5
