"""Focused graph and template contracts for option checks and bounded item loops."""

import json
import pytest
from pydantic import ValidationError

from backend.core.api.app.services.workflow_models import (
    WorkflowGraph, WorkflowLifecycle, WorkflowValidationError, validate_workflow_readiness,
)
from backend.core.api.app.services.workflow_template_expressions import resolve_workflow_template
from backend.core.api.app.services.workflow_yaml_compiler import compile_workflow_yaml
from backend.core.api.app.services.workflow_authoring_compiler import FlatAuthoringAccumulator, build_authoring_schema, compile_authoring_plan
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry


@pytest.fixture(autouse=True)
def filesystem_capabilities(monkeypatch):
    """Use repository metadata when isolated CI has no process skill registry."""
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda self: _FilesystemWorkflowMetadataRegistry())


def _option_graph():
    return {"version": 2, "nodes": [
        {"id": "source", "type": "app_skill_action", "config": {"app_id": "news", "skill_id": "search", "input": {"requests": [{"query": "AI", "count": 5}]}}},
        {"id": "check", "type": "check", "config": {"mode": "ai", "result_type": "options", "question": "Which stories?",
            "selected_inputs": ["$nodes.source.output.results"], "selection_mode": "multiple",
            "options": [{"id": "funding", "label": "Funding"}, {"id": "research", "label": "Research"}]}},
        {"id": "funding", "type": "send_chat_message", "config": {"title": "Funding", "message": "Funding update"}},
        {"id": "continue", "type": "send_chat_message", "config": {"title": "Daily", "message": "Daily update"}},
    ], "edges": [{"from": "source", "to": "check"}, {"from": "check", "to": "funding", "branch": "option:funding"},
                 {"from": "check", "to": "continue"}]}


# contract-test: supporting surface=rest_api assertions=workflows.control.choice-check
def test_option_check_uses_stable_branch_ids_and_typed_outputs():
    graph = WorkflowGraph.model_validate(_option_graph())
    validate_workflow_readiness(graph)
    invalid = _option_graph()
    invalid["edges"][1]["branch"] = "option:unknown"
    with pytest.raises((WorkflowValidationError, ValidationError), match="branch"):
        WorkflowGraph.model_validate(invalid)
    invalid = _option_graph()
    invalid["nodes"][1]["config"]["options"][1]["id"] = "funding"
    with pytest.raises((WorkflowValidationError, ValidationError), match="unique stable"):
        WorkflowGraph.model_validate(invalid)
    data = _option_graph()
    data["nodes"][1]["config"].pop("question")
    validate_workflow_readiness(WorkflowGraph.model_validate(data))
    data["nodes"][1]["config"]["selected_inputs"] = []
    with pytest.raises((WorkflowValidationError, ValidationError), match="selected inputs or a meaningful instruction"):
        WorkflowGraph.model_validate(data)
    data["nodes"][1]["config"]["question"] = "Classify the current situation"
    validate_workflow_readiness(WorkflowGraph.model_validate(data))


# contract-test: supporting surface=rest_api assertions=workflows.control.for-each
def test_for_each_body_is_scoped_and_bounded():
    data = {"version": 2, "nodes": [
        {"id": "source", "type": "app_skill_action", "config": {"app_id": "news", "skill_id": "search", "input": {"requests": [{"query": "AI", "count": 5}]}}},
        {"id": "loop", "type": "for_each", "config": {"items": "$nodes.source.output.results", "max_items": 3}},
        {"id": "body", "type": "send_chat_message", "config": {"title": "Item", "message": "{{items.loop.item.title}}"}},
        {"id": "after", "type": "send_chat_message", "config": {"title": "Done", "message": "Done"}},
    ], "edges": [{"from": "source", "to": "loop"}, {"from": "loop", "to": "body", "branch": "body"},
                 {"from": "loop", "to": "after"}]}
    graph = WorkflowGraph.model_validate(data)
    validate_workflow_readiness(graph)
    assert graph.nodes[1].config["max_duration_seconds"] == 300
    data["nodes"][3]["config"]["message"] = "{{items.loop.item.title}}"
    with pytest.raises((WorkflowValidationError, ValidationError), match="outside For each body"):
        WorkflowGraph.model_validate(data)
    data["nodes"][3]["config"]["message"] = "Done"
    data["nodes"][1]["config"]["max_items"] = 101
    with pytest.raises((WorkflowValidationError, ValidationError), match="max_items"):
        WorkflowGraph.model_validate(data)
    data["nodes"][1]["config"]["max_items"] = 3
    data["edges"] = [edge for edge in data["edges"] if edge.get("branch") != "body"]
    data["nodes"] = [node for node in data["nodes"] if node["id"] != "body"]
    validate_workflow_readiness(WorkflowGraph.model_validate(data))


# contract-test: supporting surface=rest_api assertions=workflows.control.for-each,workflows.chat.embedded-lifecycle
def test_item_runtime_paths_and_chat_lifecycle():
    context = {"items": {"loop": {"item": {"title": "First"}, "index": 2}}}
    assert resolve_workflow_template("$items.loop.item.title", context) == "First"
    assert resolve_workflow_template("{{items.loop.index}}", context) == 2
    assert WorkflowLifecycle.CHAT_EMBED.value == "chat_embed"


# contract-test: supporting surface=rest_api assertions=workflows.control.for-each
def test_for_each_accepts_declared_trigger_list_and_rejects_untyped_input():
    data = {"version": 2, "trigger_node_id": "trigger", "nodes": [
        {"id": "trigger", "type": "manual_trigger", "config": {"required_start_input_schema": {
            "type": "object", "properties": {"results": {"type": "array", "items": {
                "type": "object", "properties": {"title": {"type": "string"}}}}}, "required": ["results"]}}},
        {"id": "loop", "type": "for_each", "config": {"items": "trigger.results"}},
        {"id": "body", "type": "send_chat_message", "config": {"title": "Item", "message": "{{items.loop.item.title}}"}},
        {"id": "after", "type": "send_chat_message", "config": {"title": "Done", "message": "Done"}},
    ], "edges": [{"from": "trigger", "to": "loop"}, {"from": "loop", "to": "body", "branch": "body"},
                 {"from": "loop", "to": "after"}]}
    validate_workflow_readiness(WorkflowGraph.model_validate(data))
    assert resolve_workflow_template("trigger.results", {"trigger": {"results": [{"title": "First"}]}}) == [{"title": "First"}]
    data["nodes"][0]["config"]["required_start_input_schema"]["properties"]["results"].pop("items")
    with pytest.raises(WorkflowValidationError, match="typed earlier list"):
        validate_workflow_readiness(WorkflowGraph.model_validate(data))


# contract-test: supporting surface=rest_api assertions=workflows.control.choice-check
def test_option_check_can_use_caller_variable_without_instruction():
    data = {"version": 2, "trigger_node_id": "trigger", "nodes": [
        {"id": "trigger", "type": "manual_trigger", "config": {"required_start_input_schema": {
            "type": "object", "properties": {"results": {"type": "array", "items": {"type": "string"}}}}}},
        {"id": "pick", "type": "check", "config": {"mode": "ai", "result_type": "options",
            "selection_mode": "single", "selected_inputs": ["trigger.results"],
            "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}},
        {"id": "after", "type": "send_chat_message", "config": {"title": "Done", "message": "Done"}},
    ], "edges": [{"from": "trigger", "to": "pick"}, {"from": "pick", "to": "after"}]}
    validate_workflow_readiness(WorkflowGraph.model_validate(data))
    data["nodes"][1]["config"]["result_type"] = "boolean"
    data["nodes"][1]["config"].pop("selection_mode")
    data["nodes"][1]["config"].pop("options")
    with pytest.raises((WorkflowValidationError, ValidationError), match="Boolean AI Check requires a question"):
        WorkflowGraph.model_validate(data)


# contract-test: supporting surface=rest_api assertions=workflows.control.for-each
def test_for_each_body_output_cannot_escape_to_shared_or_sibling_step():
    data = {"version": 2, "trigger_node_id": "trigger", "nodes": [
        {"id": "trigger", "type": "manual_trigger", "config": {"required_start_input_schema": {
            "type": "object", "properties": {"results": {"type": "array", "items": {"type": "string"}}}}}},
        {"id": "loop", "type": "for_each", "config": {"items": "trigger.results"}},
        {"id": "body", "type": "app_skill_action", "config": {"app_id": "news", "skill_id": "search",
            "input": {"requests": [{"query": "AI", "count": 5}]}}},
        {"id": "after", "type": "send_chat_message", "config": {"title": "Done", "message": "{{steps.body.result_count}}"}},
    ], "edges": [{"from": "trigger", "to": "loop"}, {"from": "loop", "to": "body", "branch": "body"},
                 {"from": "loop", "to": "after"}]}
    with pytest.raises((WorkflowValidationError, ValidationError), match="branch-local"):
        WorkflowGraph.model_validate(data)
    data["nodes"][3]["config"]["message"] = "Done"
    data["nodes"].extend([
        {"id": "sibling", "type": "for_each", "config": {"items": "trigger.results"}},
        {"id": "sibling_body", "type": "send_chat_message", "config": {"title": "Sibling", "message": "{{steps.body.result_count}}"}},
    ])
    data["edges"].extend([{"from": "after", "to": "sibling"}, {"from": "sibling", "to": "sibling_body", "branch": "body"}])
    with pytest.raises((WorkflowValidationError, ValidationError), match="branch-local"):
        WorkflowGraph.model_validate(data)


# contract-test: supporting surface=rest_api assertions=workflows.control.choice-check
def test_yaml_compiles_option_branches_and_loop_body():
    source = """\
title: News selection
start_when:
  manual: {}
steps:
  - id: source
    use_app_skill: news.search
    input:
      requests: [{query: AI, count: 5}]
  - id: check
    check:
      mode: ai
      result_type: options
      selection_mode: multiple
      selected_inputs: [$nodes.source.output.results]
      options:
        - {id: funding, label: Funding}
        - {id: research, label: Research}
    option_branches:
      funding:
        - id: funding_send
          send_chat_message: {title: Funding, message: '{{steps.source.result_count}}'}
  - id: loop
    for_each:
      items: $nodes.source.output.results
      max_items: 3
      do:
        - id: item_send
          send_chat_message: {title: Item, message: '{{items.loop.item.title}}'}
  - id: complete
    send_chat_message: {title: Done, message: '{{steps.source.result_count}}'}
"""
    graph = compile_workflow_yaml(source).graph
    assert graph.version == 2
    assert ("check", "funding_send", "option:funding") in {(edge.from_node, edge.to_node, edge.branch) for edge in graph.edges}
    assert ("loop", "item_send", "body") in {(edge.from_node, edge.to_node, edge.branch) for edge in graph.edges}


# contract-test: supporting surface=rest_api assertions=workflows.control.for-each
def test_yaml_compiles_typed_trigger_list_source():
    source = """\
title: Caller results
start_when:
  manual:
    input_schema:
      type: object
      properties:
        results:
          type: array
          items:
            type: object
            properties:
              title: {type: string}
      required: [results]
steps:
  - id: loop
    for_each:
      items: trigger.results
      do:
        - id: item_send
          send_chat_message: {title: Item, message: '{{items.loop.item.title}}'}
  - id: done
    send_chat_message: {title: Done, message: Done}
"""
    graph = compile_workflow_yaml(source).graph
    assert next(node for node in graph.nodes if node.id == "loop").config["items"] == "trigger.results"


# contract-test: supporting surface=rest_api assertions=workflows.control.for-each
def test_ai_authoring_compiles_typed_item_reference(monkeypatch):
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda self: _FilesystemWorkflowMetadataRegistry())
    capability = WorkflowCapabilityRegistry().get_capability("news.search")
    selection = WorkflowPreselection(capabilities=[capability], operation="create", check_mode="none", chat_delivery=True, scores={}, metrics={})
    schema = build_authoring_schema(selection)
    assert "for_each_3" in schema["$defs"]
    result = compile_authoring_plan({
        "operation": "create", "title": "News", "description": "Send news", "icon": "newspaper",
        "schedule": {"type": "manual"},
        "steps": [
            {"kind": "app", "id": "source", "capability": "news.search", "input": {"requests": [{"query": "AI", "count": 5}]}},
            {"kind": "for_each", "id": "loop", "items": {"step": "source", "field": "results"}, "max_items": 3,
             "body": [{"kind": "send", "id": "item_send", "title": "Item", "message": [{"ref": {"loop": "loop", "field": "item.title"}}]}]},
            {"kind": "send", "id": "complete", "title": "Done", "message": [{"ref": {"step": "source", "field": "result_count"}}]},
        ],
    }, selection, "UTC")
    graph = result["graph"]
    assert ("loop", "item_send", "body") in {(edge["from"], edge["to"], edge.get("branch")) for edge in graph["edges"]}


# contract-test: supporting surface=rest_api assertions=workflows.control.choice-check
def test_ai_authoring_compiles_option_branches(monkeypatch):
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda self: _FilesystemWorkflowMetadataRegistry())
    capability = WorkflowCapabilityRegistry().get_capability("news.search")
    selection = WorkflowPreselection(capabilities=[capability], operation="create", check_mode="ai", chat_delivery=True, scores={}, metrics={})
    result = compile_authoring_plan({
        "operation": "create", "title": "News", "description": "Select stories", "icon": "newspaper",
        "schedule": {"type": "manual"},
        "steps": [
            {"kind": "app", "id": "source", "capability": "news.search", "input": {"requests": [{"query": "AI", "count": 5}]}},
            {"kind": "check", "id": "pick", "mode": "ai", "result_type": "options", "selection_mode": "multiple",
             "selected_inputs": [{"step": "source", "field": "results"}],
             "options": [{"id": "funding", "label": "Funding"}, {"id": "research", "label": "Research"}],
             "yes": [], "no": [], "unsure": [], "no_match": [],
             "option_branches": [{"option_id": "funding", "steps": [
                 {"kind": "send", "id": "funding_send", "title": "Funding", "message": [{"text": "Funding found"}]}]}]},
            {"kind": "send", "id": "complete", "title": "Done", "message": [{"ref": {"step": "source", "field": "result_count"}}]},
        ],
    }, selection, "UTC")
    graph = result["graph"]
    assert ("pick", "funding_send", "option:funding") in {(edge["from"], edge["to"], edge.get("branch")) for edge in graph["edges"]}


# contract-test: supporting surface=rest_api assertions=workflows.control.choice-check
def test_flat_authoring_preserves_loop_body_and_option_branch(monkeypatch):
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda self: _FilesystemWorkflowMetadataRegistry())
    capability = WorkflowCapabilityRegistry().get_capability("news.search")
    selection = WorkflowPreselection(capabilities=[capability], operation="create", check_mode="ai", chat_delivery=True, scores={}, metrics={})
    author = FlatAuthoringAccumulator(selection, "UTC")
    author.accept_header({"operation": "create", "title": "News", "description": "Select stories",
                          "icon": "newspaper", "schedule": {"type": "manual"}})
    author.accept_node({"kind": "app", "id": "source", "capability": "news.search",
                        "input_json": json.dumps({"requests": [{"query": "AI", "count": 5}]})})
    author.accept_node({"kind": "check", "id": "pick", "mode": "ai", "result_type": "options",
                        "selection_mode": "multiple",
                        "selected_inputs_json": json.dumps([{"step": "source", "field": "results"}]),
                        "options_json": json.dumps([{"id": "funding", "label": "Funding"}, {"id": "research", "label": "Research"}])})
    author.accept_node({"kind": "send", "id": "funding_send", "parent_check_id": "pick", "branch": "option:funding",
                        "title": "Funding", "message_json": json.dumps([{"text": "Funding found"}])})
    author.accept_node({"kind": "for_each", "id": "loop", "items_json": json.dumps({"step": "source", "field": "results"})})
    author.accept_node({"kind": "send", "id": "item_send", "parent_loop_id": "loop", "branch": "body",
                        "title": "Item", "message_json": json.dumps([{"ref": {"loop": "loop", "field": "item.title"}}])})
    author.accept_node({"kind": "send", "id": "complete", "title": "Done",
                        "message_json": json.dumps([{"ref": {"step": "source", "field": "result_count"}}])})
    graph = author.compile_final()["graph"]
    assert ("pick", "funding_send", "option:funding") in {(edge["from"], edge["to"], edge.get("branch")) for edge in graph["edges"]}
    assert ("loop", "item_send", "body") in {(edge["from"], edge["to"], edge.get("branch")) for edge in graph["edges"]}
