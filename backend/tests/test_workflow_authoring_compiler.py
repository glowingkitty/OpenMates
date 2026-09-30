"""Focused contract tests for compact Workflow authoring compilation."""
# contract-test-file: infrastructure

from __future__ import annotations

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from backend.core.api.app.services.workflow_authoring_compiler import (
    build_authoring_schema, compile_authoring_plan, compile_authoring_preview,
)
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry,
)


@pytest.fixture(autouse=True)
def filesystem_capabilities(monkeypatch):
    """Keep graph contract tests independent of runtime service imports."""
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda self: _FilesystemWorkflowMetadataRegistry())


def selection(*capabilities: str, mode: str = "none", operation: str = "create") -> WorkflowPreselection:
    registry = WorkflowCapabilityRegistry()
    return WorkflowPreselection(
        capabilities=[registry.get_capability(identifier) for identifier in capabilities],
        operation=operation, check_mode=mode, chat_delivery=True, scores={}, metrics={},
    )


def plan(steps, *, schedule=None):
    return {"operation": "create", "title": "Weather watch", "description": "Send the requested updates",
            "icon": "cloud-rain", "schedule": schedule or {"type": "daily", "time": "08:00"},
            "steps": steps}


def ref(step: str, field: str):
    return {"ref": {"step": step, "field": field}}


def test_schema_is_selected_capability_scoped_and_supports_structured_steps():
    schema = build_authoring_schema(selection("weather.forecast", mode="exact"))
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["operation"]["enum"] == ["create", "update", "draft", "clarify"]
    serialized = str(schema)
    assert "weather.forecast" in serialized
    assert "shopping.search_products" not in serialized
    assert "selected_inputs" in serialized
    assert "yes" in serialized and "no" in serialized
    assert "output.path" not in serialized


def test_compiles_rain_branches_and_runtime_date_with_stable_edges():
    raw = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast",
         "input": {"location": "Graz", "start_date": {"$date": "today", "format": "date"},
                   "end_date": {"$date": "today", "format": "date"}}},
        {"kind": "check", "id": "rain", "mode": "exact",
         "predicate": {"op": "eq", "left": ref("forecast", "rain_expected"), "right": True},
         "yes": [{"kind": "send", "id": "umbrella", "title": "Rain update",
                  "message": [{"text": "Take an umbrella. "}, ref("forecast", "rain_summary")]}],
         "no": [{"kind": "send", "id": "dry", "title": "Weather update",
                 "message": [{"text": "It should be dry. "}, ref("forecast", "rain_summary")]}]},
    ])
    result = compile_authoring_plan(raw, selection("weather.forecast", mode="exact"), "Europe/Berlin")
    graph = result["graph"]
    assert result["action"] == "create_workflow"
    assert graph["version"] == 2
    assert graph["nodes"][0]["config"]["schedule"] == {"type": "daily", "time": "08:00", "timezone": "Europe/Berlin"}
    edges = {(edge["from"], edge["branch"], edge["to"]) for edge in graph["edges"]}
    assert {("trigger", None, "forecast"), ("forecast", None, "rain"),
            ("rain", "yes", "umbrella"), ("rain", "no", "dry")} <= edges
    assert graph["nodes"][2]["config"]["predicate"]["left"] == "$nodes.forecast.output.rain_expected"
    assert graph["nodes"][1]["config"]["input"]["start_date"] == {"$date": "today", "format": "date"}


def test_compiles_ask_ai_and_output_binding():
    raw = plan([
        {"kind": "app", "id": "events", "capability": "events.search",
         "input": {"requests": [{"query": "AI", "location": "Berlin"}]}},
        {"kind": "ask_ai", "id": "summary",
         "prompt": [{"text": "Summarize these upcoming events: "}, ref("events", "results")]},
        {"kind": "send", "id": "message", "title": "AI events",
         "message": [{"text": "Events: "}, ref("summary", "answer")]},
    ], schedule={"type": "weekly", "time": "16:00", "weekdays": ["friday"]})
    result = compile_authoring_plan(raw, selection("events.search", "ai.ask"), "Europe/Berlin")
    graph = result["graph"]
    assert graph["nodes"][2]["config"]["input"]["prompt"] == "Summarize these upcoming events: {{ $nodes.events.output.results }}"
    assert graph["nodes"][3]["config"]["message"] == "Events: {{ $nodes.summary.output.answer }}"
    assert graph["nodes"][0]["config"]["schedule"]["weekdays"] == ["friday"]


def test_fixed_branch_messages_use_upstream_check_without_fake_variables():
    raw = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast",
         "input": {"location": "Lisbon", "start_date": {"$date": "tomorrow", "format": "date"},
                   "end_date": {"$date": "tomorrow", "format": "date"}}},
        {"kind": "check", "id": "rain", "mode": "exact",
         "predicate": {"op": "eq", "left": ref("forecast", "rain_expected"), "right": True},
         "yes": [{"kind": "send", "id": "umbrella", "title": "Weather update",
                  "message": [{"text": "Take an umbrella."}]}], "no": []},
    ])
    result = compile_authoring_plan(raw, selection("weather.forecast", mode="exact"), "Europe/Lisbon")
    graph = result["graph"]
    assert next(node for node in graph["nodes"] if node["id"] == "umbrella")["config"]["message"] == "Take an umbrella."
    assert any(edge["from"] == "rain" and edge["branch"] == "no" and edge["to"] == "rain_no_end"
               for edge in graph["edges"])


def test_rejects_date_marker_encoded_as_app_input_string():
    raw = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast",
         "input": {"location": "Berlin", "start_date": "{$date:'today',format:'date'}",
                   "end_date": {"$date": "today", "format": "date"}}},
        {"kind": "send", "id": "reply", "title": "Weather", "message": [ref("forecast", "summary")]},
    ])
    with pytest.raises(ValueError, match="runtime date markers must be structured objects"):
        compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")


def test_rejects_end_inside_branch_with_queued_continuation():
    raw = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast",
         "input": {"location": "Berlin", "days": 1}},
        {"kind": "check", "id": "rain", "mode": "exact",
         "predicate": {"op": "eq", "left": ref("forecast", "rain_expected"), "right": True},
         "yes": [{"kind": "end", "id": "stop"}],
         "no": [{"kind": "send", "id": "dry", "title": "Weather",
                 "message": [{"text": "It should be dry."}]}]},
        {"kind": "send", "id": "followup", "title": "Weather",
         "message": [{"text": "Check complete."}]},
    ])
    with pytest.raises(ValueError, match="queued continuation"):
        compile_authoring_plan(raw, selection("weather.forecast", mode="exact"), "Europe/Berlin")
    raw["steps"].pop()
    graph = compile_authoring_plan(raw, selection("weather.forecast", mode="exact"), "Europe/Berlin")["graph"]
    assert any(node["id"] == "stop" for node in graph["nodes"])


def test_check_mode_hint_does_not_remove_needed_fallback_check():
    raw = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast", "input": {"location": "Paris", "days": 1}},
        {"kind": "check", "id": "available", "mode": "exact",
         "predicate": {"op": "exists", "left": ref("forecast", "summary")},
         "yes": [{"kind": "send", "id": "results", "title": "Forecast",
                  "message": [ref("forecast", "summary")]}],
         "no": [{"kind": "send", "id": "missing", "title": "Forecast",
                 "message": [{"text": "No forecast is available."}]}]},
    ])
    result = compile_authoring_plan(raw, selection("weather.forecast", mode="none"), "Europe/Berlin")
    assert any(node["id"] == "available" for node in result["graph"]["nodes"])


def test_ai_check_selected_inputs_and_branch_continuation():
    raw = plan([
        {"kind": "app", "id": "news", "capability": "news.search",
         "input": {"requests": [{"query": "AI policy"}]}},
        {"kind": "check", "id": "important", "mode": "ai",
         "question": [{"text": "Is any item important for a small European startup?"}],
         "selected_inputs": [{"step": "news", "field": "results"}],
         "yes": [{"kind": "send", "id": "relevant", "title": "Relevant news",
                  "message": [{"text": "Relevant policy news"}],
                  "blocks": [{"id": "items", "source": {"step": "news", "field": "results"}}]}],
         "no": [{"kind": "send", "id": "none", "title": "News update",
                 "message": [{"text": "No important update."}]}]},
        {"kind": "send", "id": "followup", "title": "Followup", "message": [{"text": "Review complete."}]},
    ])
    result = compile_authoring_plan(raw, selection("news.search", mode="ai"), "Europe/Berlin")
    edges = result["graph"]["edges"]
    assert any(edge["from"] == "important" and edge["branch"] == "default" and edge["to"] == "followup"
               for edge in edges)
    check = next(node for node in result["graph"]["nodes"] if node["id"] == "important")
    assert check["config"]["selected_inputs"] == ["$nodes.news.output.results"]


def test_update_preserves_supplied_ids_and_rejects_different_target():
    base = plan([
        {"kind": "app", "id": "search", "capability": "weather.forecast", "input": {"location": "Lisbon", "days": 1}},
        {"kind": "send", "id": "reply", "title": "Forecast", "message": [ref("search", "summary")]},
    ])
    original = compile_authoring_plan(base, selection("weather.forecast"), "Europe/Lisbon")
    selected = {"id": "workflow-1", "graph": original["graph"], "enabled": False}
    selected["graph"]["trigger_node_id"] = "existing_start"
    selected["graph"]["nodes"][0]["id"] = "existing_start"
    selected["graph"]["edges"][0]["from"] = "existing_start"
    edit = deepcopy(base)
    edit.update({"operation": "update", "workflow_id": "workflow-1"})
    edit["schedule"] = {"type": "daily", "time": "10:30"}
    result = compile_authoring_plan(edit, selection("weather.forecast", operation="update"), "Europe/Lisbon", selected)
    assert result["workflow_id"] == "workflow-1"
    assert [node["id"] for node in result["graph"]["nodes"]] == ["existing_start", "search", "reply"]
    assert result["graph"]["nodes"][0]["config"]["schedule"]["time"] == "10:30"
    edit["workflow_id"] = "workflow-2"
    with pytest.raises(ValueError, match="selected workflow"):
        compile_authoring_plan(edit, selection("weather.forecast", operation="update"), "Europe/Lisbon", selected)


def test_rejects_unselected_app_and_model_authored_variable():
    raw = plan([
        {"kind": "app", "id": "search", "capability": "web.search", "input": {"query": "example"}},
        {"kind": "send", "id": "reply", "title": "Update", "message": [{"text": "done"}]},
    ])
    with pytest.raises(ValueError, match="selected capability"):
        compile_authoring_plan(raw, selection("weather.forecast"), "UTC")
    raw["steps"][0] = {"kind": "app", "id": "search", "capability": "weather.forecast", "input": {"location": "{{ $nodes.foo.output.location }}"}}
    with pytest.raises(ValueError, match="typed reference"):
        compile_authoring_plan(raw, selection("weather.forecast"), "UTC")


def test_rejects_unknown_app_input_field_without_echoing_raw_content():
    raw = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast",
         "input": {"location": "Paris", "credential": "private-marker"}},
        {"kind": "send", "id": "reply", "title": "Forecast", "message": [ref("forecast", "summary")]},
    ])
    with pytest.raises(ValueError, match="selected capability schema") as error:
        compile_authoring_plan(raw, selection("weather.forecast"), "UTC")
    assert "private-marker" not in str(error.value)
    assert "credential" not in str(error.value)


def test_clarification_is_an_explicit_outcome():
    result = compile_authoring_plan({"operation": "clarify", "message": "Email delivery is unavailable."},
                                    selection("weather.forecast"), "UTC")
    assert result == {"action": "needs_clarification", "message": "Email delivery is unavailable."}


def test_preview_accepts_header_and_completed_app_without_delivery():
    raw = {"operation": "create", "title": "Weather watch", "description": "Forecast", "icon": "cloud-rain"}
    header = compile_authoring_preview(raw, selection("weather.forecast"), "Europe/Berlin")
    assert header["complete"] is False
    assert header["graph"]["version"] == 2
    assert [node["id"] for node in header["graph"]["nodes"]] == ["trigger"]
    assert "action" not in header and "enabled" not in header
    assert header["assumptions"] == [
        "No time was specified, so this workflow is scheduled for 09:00.",
        "No weekly day was specified, so this workflow is scheduled for Monday.",
    ]
    raw["steps"] = [{"kind": "app", "id": "forecast", "capability": "weather.forecast",
                     "input": {"location": "Berlin", "days": 1}}]
    partial = compile_authoring_preview(raw, selection("weather.forecast"), "Europe/Berlin")
    assert [node["id"] for node in partial["graph"]["nodes"]] == ["trigger", "forecast"]
    with pytest.raises(ValueError, match="chat delivery"):
        compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")


def test_preview_rejects_invalid_completed_step_reference():
    raw = {"operation": "create", "steps": [{"kind": "app", "id": "forecast",
           "capability": "weather.forecast", "input": {"location": ref("later", "summary")}}]}
    with pytest.raises(ValueError, match="earlier step"):
        compile_authoring_preview(raw, selection("weather.forecast"), "UTC")


def test_schedule_defaults_and_hourly_once_runtime_shapes():
    steps = [{"kind": "app", "id": "forecast", "capability": "weather.forecast",
              "input": {"location": "Berlin", "days": 1}},
             {"kind": "send", "id": "reply", "title": "Forecast", "message": [ref("forecast", "summary")]}]
    raw = plan(steps)
    raw.pop("schedule")
    result = compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")
    assert result["graph"]["nodes"][0]["config"]["schedule"] == {
        "type": "weekly", "time": "09:00", "timezone": "Europe/Berlin", "weekdays": ["monday"]}
    assert len(result["assumptions"]) == 2
    raw["schedule"] = {"type": "hourly", "minute": 15}
    hourly = compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")
    assert hourly["graph"]["nodes"][0]["config"]["schedule"] == {
        "type": "hourly", "timezone": "Europe/Berlin", "minute": 15}
    raw["schedule"] = {"type": "once", "at": "2027-01-02T09:00:00"}
    once = compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")
    assert once["graph"]["nodes"][0]["config"]["schedule"] == {
        "type": "once", "timezone": "Europe/Berlin", "at": "2027-01-02T09:00:00"}


def test_update_without_steps_preserves_graph_and_full_replacement_requires_explicit_removal():
    base = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast",
         "input": {"location": "Berlin", "days": 1}},
        {"kind": "app", "id": "other", "capability": "weather.forecast",
         "input": {"location": "Paris", "days": 1}},
        {"kind": "send", "id": "reply", "title": "Forecast", "message": [ref("forecast", "summary")]},
    ])
    prior = compile_authoring_plan(base, selection("weather.forecast"), "Europe/Berlin")["graph"]
    selected = {"id": "workflow-1", "version": 4, "graph": prior}
    change = {"operation": "update", "workflow_id": "workflow-1",
              "schedule": {"type": "daily", "time": "11:00"}}
    updated = compile_authoring_plan(change, selection("weather.forecast", operation="update"),
                                     "Europe/Berlin", selected)
    assert updated["expected_record_version"] == 4
    assert [node["id"] for node in updated["graph"]["nodes"]] == ["trigger", "forecast", "other", "reply"]
    assert updated["graph"]["edges"] == prior["edges"]
    metadata_only = {"operation": "update", "workflow_id": "workflow-1", "title": "New title"}
    unchanged_graph = compile_authoring_plan(metadata_only, selection("weather.forecast", operation="update"),
                                             "Europe/Berlin", selected)
    assert unchanged_graph["graph"] == prior
    change["steps"] = [base["steps"][0], base["steps"][2]]
    first_step_preview = compile_authoring_preview({**change, "steps": [base["steps"][0]]},
                                                   selection("weather.forecast", operation="update"),
                                                   "Europe/Berlin", selected)
    assert [node["id"] for node in first_step_preview["graph"]["nodes"]] == ["trigger", "forecast"]
    assert first_step_preview["complete"] is False
    with pytest.raises(ValueError, match="preserve existing step IDs"):
        compile_authoring_plan(change, selection("weather.forecast", operation="update"),
                               "Europe/Berlin", selected)
    change["remove_step_ids"] = ["other"]
    removed = compile_authoring_plan(change, selection("weather.forecast", operation="update"),
                                    "Europe/Berlin", selected)
    assert [node["id"] for node in removed["graph"]["nodes"]] == ["trigger", "forecast", "reply"]
    change.pop("steps")
    change.pop("remove_step_ids")
    change["schedule"] = {"type": "weekly"}
    defaulted = compile_authoring_plan(change, selection("weather.forecast", operation="update"),
                                       "Europe/Berlin", selected)
    assert len(defaulted["assumptions"]) == 2


def test_explicit_short_title_draft_has_no_graph():
    result = compile_authoring_plan({"operation": "draft", "title": "Morning digest"},
                                    selection("weather.forecast"), "UTC")
    assert result == {"action": "create_empty_workflow", "title": "Morning digest"}


def test_preview_rejects_oversized_model_document_before_graph_work():
    raw = {"operation": "create", "title": "Weather", "description": "A" * 70_000}
    with pytest.raises(ValueError, match="size limit"):
        compile_authoring_preview(raw, selection("weather.forecast"), "UTC")
