"""Choice Check and flat For-each runtime contracts.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

import pytest

from backend.core.api.app.services import workflow_runner as runner_module
from backend.core.api.app.services.workflow_ai_service import WorkflowAiService, WorkflowOptionsCheckResult
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_template_expressions import resolve_workflow_template
from backend.shared.providers.typesafe.models import DecisionResponse, NoulAnswer
from backend.tests.test_workflow_runner import FakeAppSkillAdapter
from backend.tests.workflow_test_utils import workflow_service


class RecordingActionAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def send_chat_message(self, config, context, _user_id):
        message = resolve_workflow_template(config["message"], context)
        self.calls.append(message)
        return {"type": "send_chat_message", "message": message, "chat_id": "test-chat"}


def isolated_runtime_service():
    """Keep these runner tests independent of registry readiness, covered separately."""
    service = workflow_service()
    service.validate_manual_run_input = lambda _workflow, _payload: None
    return service


# contract-test: direct surface=rest_api assertions=workflows.control.for-each
def test_returned_outputs_project_only_typed_requested_values() -> None:
    context = {
        "workflow": {"invocation": {"return_outputs": {
            "count": {"ref": "$nodes.source.output.count", "type": "integer"},
            "wrong_type": {"ref": "$nodes.source.output.count", "type": "string"},
        }}},
        "nodes": {"source": {"output": {"count": 2, "private": "never shared"}}},
    }
    projected = runner_module._project_returned_outputs(context)
    assert projected == {"status": "completed", "values": {
        "count": {"ref": "$nodes.source.output.count", "type": "integer", "value": 2},
        "wrong_type": {"ref": "$nodes.source.output.count", "type": "string",
                       "error": "unavailable_or_type_mismatch"},
    }}
    assert "private" not in str(projected)


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.control.choice-check
async def test_multiple_options_require_every_jev_answer_and_preserve_config_order() -> None:
    responses = [
        DecisionResponse(model="typesafe/jev-1.13", answers={
            "option_0": NoulAnswer(type="noul", noul=0.9),
            "option_1": NoulAnswer(type="noul", noul=0.1),
            "option_2": NoulAnswer(type="noul", noul=0.8),
        }),
        DecisionResponse(model="typesafe/jev-1.13", answers={
            "option_0": NoulAnswer(type="noul", noul=0.9),
            "option_2": NoulAnswer(type="noul", noul=0.8),
        }),
    ]
    calls = []

    async def jev(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    ai = WorkflowAiService(secrets_manager=None, jev_evaluator=jev)
    options = [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"},
               {"id": "c", "label": "Gamma"}]
    args = {"question": "Which apply?", "selected_inputs": [{"reference": "source", "value": "data"}],
            "options": options, "selection_mode": "multiple"}
    selected = await ai.evaluate_options_check(**args)
    incomplete = await ai.evaluate_options_check(**args)

    assert selected.outcome == "selected" and selected.selected_options == ("a", "c")
    assert incomplete.outcome == "unsure" and incomplete.selected_options == ()
    assert len(calls) == 2
    assert set(calls[0]["questions"]) == {"option_0", "option_1", "option_2"}
    assert calls[0]["state"]["selected_inputs"][0]["value"] == "data"


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.control.choice-check
async def test_multiple_option_branches_run_in_config_order_then_continue_once(monkeypatch) -> None:
    graph = {
        "version": 2, "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00"}}},
            {"id": "check", "type": "check", "config": {"mode": "ai", "result_type": "options",
                "selection_mode": "multiple", "question": "Which apply?", "selected_inputs": [],
                "options": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}]}},
            {"id": "a", "type": "send_chat_message", "config": {"title": "A", "message": "a"}},
            {"id": "b", "type": "send_chat_message", "config": {"title": "B", "message": "b"}},
            {"id": "done", "type": "send_chat_message", "config": {"title": "Done", "message": "done"}},
        ],
        "edges": [{"from": "trigger", "to": "check"},
                  {"from": "check", "to": "a", "branch": "option:a"},
                  {"from": "check", "to": "b", "branch": "option:b"},
                  {"from": "check", "to": "done"}],
    }

    class Ai:
        async def preflight_options_check_evaluation(self, *_args):
            return True

        async def evaluate_options_check(self, **_kwargs):
            return WorkflowOptionsCheckResult("selected", ("b", "a"), "jev_noul")

    async def no_op(*_args, **_kwargs):
        return None

    async def one_credit(**_kwargs):
        return 1

    monkeypatch.setattr(runner_module, "_precheck_workflow_ai_check", no_op)
    monkeypatch.setattr(runner_module, "_charge_workflow_ai_check", one_credit)
    service = isolated_runtime_service()
    workflow = service.create_workflow("alice", "Options branches", graph, enabled=False)
    actions = RecordingActionAdapter()
    run = await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=actions, ai_service=Ai()).run_workflow(
        workflow, "alice", trigger_type="schedule")

    assert run.status.value == "completed"
    assert [item.node_id for item in run.node_runs] == ["trigger", "check", "a", "b", "done"]
    assert actions.calls == ["a", "b", "done"]
    output = run.node_runs[1].output_summary
    assert output["selected_options"] == ["a", "b"]
    assert output["selected_labels"] == ["Alpha", "Beta"]
    assert output["matches"] == {"a": True, "b": True}
    assert run.cost_summary == {"credits": 1}


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.control.choice-check
async def test_nested_single_check_finishes_its_continuation_before_outer_next_option(monkeypatch) -> None:
    graph = {
        "version": 2, "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00"}}},
            {"id": "outer", "type": "check", "config": {"mode": "ai", "result_type": "options",
                "selection_mode": "multiple", "question": "Outer?", "selected_inputs": [], "options": [
                    {"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}},
            {"id": "inner", "type": "check", "config": {"mode": "ai", "result_type": "options",
                "selection_mode": "single", "question": "Inner?", "selected_inputs": [], "options": [
                    {"id": "x", "label": "X"}, {"id": "y", "label": "Y"}]}},
            *({"id": node_id, "type": "send_chat_message", "config": {"title": node_id, "message": node_id}}
              for node_id in ("x", "y", "inner_done", "b", "outer_done")),
        ],
        "edges": [
            {"from": "trigger", "to": "outer"},
            {"from": "outer", "to": "inner", "branch": "option:a"},
            {"from": "outer", "to": "b", "branch": "option:b"},
            {"from": "outer", "to": "outer_done"},
            {"from": "inner", "to": "x", "branch": "option:x"},
            {"from": "inner", "to": "y", "branch": "option:y"},
            {"from": "inner", "to": "inner_done"},
        ],
    }

    class Ai:
        async def preflight_options_check_evaluation(self, *_args):
            return True

        async def evaluate_options_check(self, **kwargs):
            if kwargs["selection_mode"] == "multiple":
                return WorkflowOptionsCheckResult("selected", ("a", "b"), "jev_noul")
            return WorkflowOptionsCheckResult("selected", ("x",), "jev_choice")

    async def no_op(*_args, **_kwargs):
        return None

    async def one_credit(**_kwargs):
        return 1

    monkeypatch.setattr(runner_module, "_precheck_workflow_ai_check", no_op)
    monkeypatch.setattr(runner_module, "_charge_workflow_ai_check", one_credit)
    service = isolated_runtime_service()
    workflow = service.create_workflow("alice", "Nested options", graph, enabled=False)
    actions = RecordingActionAdapter()
    run = await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=actions, ai_service=Ai()).run_workflow(
        workflow, "alice", trigger_type="schedule")

    assert run.status.value == "completed"
    assert actions.calls == ["x", "inner_done", "b", "outer_done"]


def _loop_graph(item_count: int, *, max_items: int = 100) -> dict:
    return {
        "version": 2, "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00"}}},
            {"id": "source", "type": "app_skill_action", "config": {"app_id": "news", "skill_id": "search",
                "input": {"requests": [{"query": f"item-{index}"} for index in range(item_count)]}}},
            {"id": "loop", "type": "for_each", "config": {"items": "$nodes.source.output.queries", "max_items": max_items}},
            {"id": "body", "type": "send_chat_message", "config": {"title": "Item", "message": "{{items.loop.item}}"}},
            {"id": "done", "type": "send_chat_message", "config": {"title": "Done", "message": "Finished {{steps.source.summary}}"}},
        ],
        "edges": [{"from": "trigger", "to": "source"}, {"from": "source", "to": "loop"},
                  {"from": "loop", "to": "body", "branch": "body"},
                  {"from": "loop", "to": "done"}],
    }


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.control.for-each
async def test_for_each_snapshots_items_and_replays_completed_occurrences() -> None:
    service = isolated_runtime_service()
    workflow = service.create_workflow("alice", "Loop items", _loop_graph(2), enabled=False)
    actions = RecordingActionAdapter()
    app_adapter = FakeAppSkillAdapter()
    runner = WorkflowRunner(service, app_skill_adapter=app_adapter, action_adapter=actions)

    first = await runner.run_workflow(workflow, "alice", trigger_type="schedule")
    second = await runner.run_workflow(workflow, "alice", trigger_type="schedule",
        run_id=first.id, version_id=first.version_id)

    assert first.status.value == "completed"
    assert actions.calls == ["item-0", "item-1", "Finished News search completed"]
    assert len(app_adapter.calls) == 1
    assert first.output_summary["workflow"]["loops"]["loop"]["source_snapshot"] == ["item-0", "item-1"]
    assert next(item for item in first.node_runs if item.node_id == "loop").output_summary == {
        "item_count": 2, "completed_count": 2,
        "results": [{"index": 0, "outputs": {"body": {"type": "send_chat_message",
            "message": "item-0", "chat_id": "test-chat"}}},
                    {"index": 1, "outputs": {"body": {"type": "send_chat_message",
            "message": "item-1", "chat_id": "test-chat"}}}],
    }
    assert [item.node_id for item in second.node_runs if item.loop_id == "loop"] == [
        "loop:0:body:body", "loop:1:body:body"]
    assert all(item.graph_node_id == "body" for item in second.node_runs if item.loop_id == "loop")


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.control.for-each
async def test_for_each_rejects_oversized_source_before_first_body_action() -> None:
    service = isolated_runtime_service()
    workflow = service.create_workflow("alice", "Loop limit", _loop_graph(3, max_items=2), enabled=False)
    actions = RecordingActionAdapter()
    run = await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=actions).run_workflow(
        workflow, "alice", trigger_type="schedule")

    assert run.status.value == "failed"
    assert next(item for item in run.node_runs if item.node_id == "loop").error_code == "WORKFLOW_FOR_EACH_LIMIT"
    assert actions.calls == []


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.control.for-each
async def test_for_each_credit_limit_stops_before_next_billed_item() -> None:
    graph = _loop_graph(2)
    body = next(node for node in graph["nodes"] if node["id"] == "body")
    body.update(type="app_skill_action", config={"app_id": "weather", "skill_id": "forecast",
        "input": {"location": "{{items.loop.item}}"}})
    next(node for node in graph["nodes"] if node["id"] == "loop")["config"]["max_credits"] = 5
    service = isolated_runtime_service()
    workflow = service.create_workflow("alice", "Loop credit limit", graph, enabled=False)
    adapter = FakeAppSkillAdapter()
    actions = RecordingActionAdapter()

    run = await WorkflowRunner(service, app_skill_adapter=adapter, action_adapter=actions).run_workflow(
        workflow, "alice", trigger_type="schedule")

    assert run.status.value == "failed"
    assert next(item for item in run.node_runs if item.node_id == "loop").error_code == "WORKFLOW_FOR_EACH_CREDITS"
    assert [call["request"].get("location") for call in adapter.calls if call["app_id"] == "weather"] == ["item-0"]
    assert actions.calls == []


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.control.for-each
async def test_for_each_empty_body_records_items_without_body_actions() -> None:
    graph = _loop_graph(2)
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] != "body"]
    graph["edges"] = [edge for edge in graph["edges"] if edge.get("branch") != "body"]
    service = isolated_runtime_service()
    workflow = service.create_workflow("alice", "Empty body", graph, enabled=False)
    actions = RecordingActionAdapter()

    run = await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=actions).run_workflow(
        workflow, "alice", trigger_type="schedule")

    assert run.status.value == "completed"
    assert next(item for item in run.node_runs if item.node_id == "loop").output_summary == {
        "item_count": 2, "completed_count": 2,
        "results": [{"index": 0, "outputs": {}}, {"index": 1, "outputs": {}}],
    }
    assert actions.calls == ["Finished News search completed"]


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.control.for-each,workflows.chat.invocation,workflows.chat.result-return
async def test_caller_only_list_uses_real_readiness_and_restores_projection_on_retry() -> None:
    from backend.core.api.app.services.workflow_models import (
        WorkflowMissingInputError, WorkflowRunDetail, WorkflowRunStatus, WorkflowValidationError,
    )

    input_schema = {
        "type": "object", "required": ["results"],
        "properties": {"results": {
            "type": "array", "items": {
                "type": "object", "properties": {"keep": {"type": "boolean"}}, "required": ["keep"],
            },
        }},
    }
    graph = {"version": 2, "trigger_node_id": "start", "nodes": [
        {"id": "start", "type": "manual_trigger", "config": {"required_start_input_schema": input_schema}},
        {"id": "loop", "type": "for_each", "config": {"items": "trigger.results", "max_items": 3}},
        {"id": "check", "type": "check", "config": {"mode": "exact", "predicate": {
            "left": "$items.loop.item.keep", "op": "eq", "right": True}}},
    ], "edges": [{"from": "start", "to": "loop"}, {"from": "loop", "to": "check", "branch": "body"}]}
    service = workflow_service()
    workflow = service.create_workflow("alice", "Caller list", graph, lifecycle="chat_embed",
        source_chat_id="owned-chat", allow_data_dependencies=True)
    actions = RecordingActionAdapter()
    runner = WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=actions)
    payload = {"results": [{"keep": True}, {"keep": False}, {"keep": True}]}
    invocation = {"source_chat_id": "owned-chat", "return_outputs": {
        "processed": {"ref": "$nodes.loop.output.completed_count", "type": "integer"}}}

    with pytest.raises(WorkflowValidationError, match="qualifying effect"):
        await runner.run_workflow(workflow, "alice", input_payload=payload,
            run_id="no-projection", version_id=workflow.current_version_id,
            invocation={"source_chat_id": "owned-chat"})
    with pytest.raises(WorkflowMissingInputError, match="results"):
        await runner.run_workflow(workflow, "alice", input_payload={},
            run_id="missing-input", version_id=workflow.current_version_id, invocation=invocation)

    service.save_run("alice", WorkflowRunDetail(
        id="accepted-caller", workflow_id=workflow.id, version_id=workflow.current_version_id,
        trigger_type="manual", status=WorkflowRunStatus.QUEUED,
    ))
    first = await runner.run_workflow(workflow, "alice", input_payload=payload,
        run_id="accepted-caller", version_id=workflow.current_version_id, invocation=invocation)
    replay = await runner.run_workflow(workflow, "alice", input_payload=payload,
        run_id=first.id, version_id=first.version_id)
    for run in (first, replay):
        assert run.status.value == "completed"
        assert run.output_summary["returned_outputs"]["values"]["processed"]["value"] == 3
        assert [node.iteration_index for node in run.node_runs if node.graph_node_id == "check"] == [0, 1, 2]
    assert actions.calls == []
