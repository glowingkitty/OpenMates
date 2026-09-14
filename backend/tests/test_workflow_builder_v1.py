"""Focused builder validation: manual readiness, deterministic nodes, unsafe graphs."""
import pytest
from pydantic import ValidationError
from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowValidationError, validate_manual_run_input, validate_workflow_readiness


def graph_data():
    return {"version": 2, "nodes": [
        {"id": "search", "type": "app_skill_action", "config": {"app_id": "news", "skill_id": "search", "input": {"requests": [{"query": "AI", "count": 10}]}}},
        {"id": "check", "type": "check", "config": {"predicate": {"left": "$nodes.search.output.result_count", "op": "gt", "right": 0}}},
        {"id": "send", "type": "send_chat_message", "config": {"title": "News", "blocks": [{"id": "news", "source": "$nodes.search.output.results", "only_new_results": True, "include_if": "$nodes.check.output.matched"}]}},
    ], "edges": [{"from": "search", "to": "check"}, {"from": "check", "to": "send"}]}


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.schedule.edge-cases
def test_complete_unscheduled_graph_can_run_but_not_enable():
    graph = WorkflowGraph.model_validate(graph_data())
    validate_manual_run_input(graph, {})
    with pytest.raises(WorkflowValidationError, match="time/date trigger"):
        validate_workflow_readiness(graph, require_schedule=True)


@pytest.mark.parametrize("change", ["cycle", "forward_reference", "invalid_block", "duplicate_branch"])
# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.control.typed-data
def test_builder_rejects_unsafe_graphs(change):
    data = graph_data()
    if change == "cycle":
        data["edges"].append({"from": "send", "to": "search"})
    elif change == "forward_reference":
        data["nodes"][0]["config"]["input"] = {"query": "$nodes.send.output.message"}
    elif change == "invalid_block":
        data["nodes"][2]["config"]["blocks"][0]["only_new_results"] = "yes"
    else:
        data["edges"].append({"from": "search", "to": "send"})
    with pytest.raises((ValidationError, WorkflowValidationError)):
        WorkflowGraph.model_validate(data)


@pytest.mark.parametrize("change,reason", [
    ("missing_input", "required app input"), ("empty_requests", "request items"),
    ("nested_required", "required app input"), ("wrong_input_type", "expected integer"),
    ("out_of_range", "allowed range"), ("unavailable_skill", "unavailable"),
    ("unknown_output", "not declared"), ("numeric_condition", "expected boolean"),
    ("scalar_dedup", "declared result list"), ("missing_title", "title"),
    ("numeric_title", "expected string"), ("incompatible_check", "compatible scalar"),
])
# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.actions.skill-contract,workflows.control.typed-data
def test_modern_preflight_rejects_unrunnable_inputs_before_dispatch(change, reason):
    data = graph_data()
    search, check, send = data["nodes"]
    if change == "missing_input":
        search["config"]["input"] = {}
    elif change == "empty_requests":
        search["config"]["input"]["requests"] = []
    elif change == "nested_required":
        search["config"]["input"]["requests"] = [{"count": 3}]
    elif change == "wrong_input_type":
        search["config"]["input"]["requests"][0]["count"] = "three"
    elif change == "out_of_range":
        search["config"]["input"]["requests"][0]["count"] = 1000
    elif change == "unavailable_skill":
        search["config"]["skill_id"] = "not-real"
    elif change == "unknown_output":
        send["config"]["blocks"][0]["source"] = "$nodes.search.output.raw.private"
    elif change == "numeric_condition":
        send["config"]["blocks"][0]["include_if"] = "$nodes.search.output.result_count"
    elif change == "scalar_dedup":
        send["config"]["blocks"][0]["source"] = "$nodes.search.output.result_count"
    elif change == "missing_title":
        send["config"].pop("title")
    elif change == "numeric_title":
        send["config"]["title"] = "$nodes.search.output.result_count"
    else:
        check["config"]["predicate"]["right"] = "some text"
    graph = WorkflowGraph.model_validate(data)  # Draft remains inspectable/saveable.
    with pytest.raises(WorkflowValidationError, match=reason):
        validate_workflow_readiness(graph)


# contract-test: supporting surface=rest_api assertions=workflows.control.check,workflows.control.typed-data
def test_template_step_references_cannot_escape_check_branch_scope():
    data = graph_data()
    data["nodes"].append({"id": "branch", "type": "app_skill_action", "config": {"app_id": "news", "skill_id": "search", "input": {"requests": [{"query": "AI"}]}}})
    data["edges"].append({"from": "check", "to": "branch", "branch": "yes"})
    data["nodes"][2]["config"]["title"] = "{{steps.branch.summary}}"
    with pytest.raises((WorkflowValidationError, ValidationError), match="branch-local"):
        WorkflowGraph.model_validate(data)


# contract-test: supporting surface=rest_api assertions=workflows.mvp.steps
def test_legacy_placeholder_can_be_inspected_but_requires_migration_to_run():
    data = {"version": 1, "nodes": [
        {"id": "pause", "type": "wait", "config": {"seconds": 1}},
        {"id": "send", "type": "start_new_chat", "config": {"title": "Old", "message": "Old"}},
    ], "edges": [{"from": "pause", "to": "send"}]}
    graph = WorkflowGraph.model_validate(data)
    with pytest.raises(WorkflowValidationError, match="Edit this workflow"):
        validate_workflow_readiness(graph)


# contract-test: supporting surface=rest_api assertions=workflows.control.typed-data,workflows.actions.skill-contract
def test_result_list_cannot_be_used_as_requests_without_required_query_fields():
    data = graph_data()
    data["nodes"].append({"id": "second", "type": "app_skill_action", "config": {"app_id": "news", "skill_id": "search", "input": {"requests": "$nodes.search.output.results"}}})
    data["edges"][0] = {"from": "search", "to": "second"}
    data["edges"].append({"from": "second", "to": "check"})
    with pytest.raises(WorkflowValidationError, match="required typed app input"):
        validate_workflow_readiness(WorkflowGraph.model_validate(data))


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
@pytest.mark.parametrize("reference", ["$nodes.limit.output.value", "{{steps.limit.value}}"])
def test_check_resolves_both_reference_operands_and_missing_numeric_values(reference):
    from backend.core.api.app.services.workflow_runner import _evaluate_predicate
    context = {"nodes": {"search": {"output": {"result_count": 3}}, "limit": {"output": {"value": 2}}}}
    predicate = {"op": "gt", "left": "{{steps.search.result_count}}", "right": reference}
    assert _evaluate_predicate(predicate, context) is True
    context["nodes"]["limit"]["output"]["value"] = None
    assert _evaluate_predicate(predicate, context) is False
    context["nodes"]["limit"]["output"]["value"] = 2
    context["nodes"]["search"]["output"]["result_count"] = None
    assert _evaluate_predicate(predicate, context) is False
