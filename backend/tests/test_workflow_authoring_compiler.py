"""Focused contract tests for compact Workflow authoring compilation."""
# contract-test-file: infrastructure

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest
from jsonschema import Draft202012Validator

from backend.core.api.app.services.workflow_authoring_compiler import (
    FlatAuthoringAccumulator, authoring_validation_code, authoring_validation_path, build_authoring_schema,
    compile_authoring_plan, compile_authoring_preview,
)
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry,
)
from backend.core.api.app.services.workflow_yaml_compiler import compile_workflow_yaml


@pytest.fixture(autouse=True)
def filesystem_capabilities(monkeypatch):
    """Keep graph contract tests independent of runtime service imports."""
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda self: _FilesystemWorkflowMetadataRegistry())


def selection(*capabilities: str, mode: str = "none", operation: str = "create",
              schedule_timezone: str | None = None, workflow_count: int | None = None,
              preserve_schedule_timezone: bool = False) -> WorkflowPreselection:
    registry = WorkflowCapabilityRegistry()
    return WorkflowPreselection(
        capabilities=[registry.get_capability(identifier) for identifier in capabilities],
        operation=operation, check_mode=mode, chat_delivery=True, scores={}, metrics={},
        schedule_timezone=schedule_timezone, workflow_count=workflow_count,
        preserve_schedule_timezone=preserve_schedule_timezone,
    )


def plan(steps, *, schedule=None):
    return {"operation": "create", "title": "Weather watch", "description": "Send the requested updates",
            "icon": "cloud-rain", "schedule": schedule or {"type": "daily", "time": "08:00"},
            "steps": steps}


def ref(step: str, field: str):
    return {"ref": {"step": step, "field": field}}


def test_selected_schedule_timezone_overrides_authored_zone_and_browser_for_single_workflow():
    send = {"kind": "send", "id": "reply", "title": "Notice", "message": [{"text": "Hello"}]}
    chosen = selection(schedule_timezone="Europe/Lisbon", workflow_count=1)
    for authored in ({"type": "weekly", "time": "09:00", "weekdays": ["thursday"], "timezone": "UTC"},
                     {"type": "weekly", "time": "09:00", "weekdays": ["thursday"]}):
        result = compile_authoring_plan(plan([send], schedule=authored), chosen, "UTC")
        assert result["graph"]["nodes"][0]["config"]["schedule"]["timezone"] == "Europe/Lisbon"


def test_no_selected_zone_preserves_authored_or_browser_timezone():
    send = {"kind": "send", "id": "reply", "title": "Notice", "message": [{"text": "Hello"}]}
    for authored, expected in (({"type": "weekly", "timezone": "Europe/Madrid"}, "Europe/Madrid"),
                               ({"type": "weekly"}, "UTC")):
        result = compile_authoring_plan(plan([send], schedule=authored), selection(), "UTC")
        assert result["graph"]["nodes"][0]["config"]["schedule"]["timezone"] == expected


def test_unrelated_update_preserves_timezone_but_explicit_schedule_edit_uses_selected_zone():
    send = {"kind": "send", "id": "reply", "title": "Notice", "message": [{"text": "Hello"}]}
    original = compile_authoring_plan(
        plan([send], schedule={"type": "weekly", "time": "09:00", "timezone": "Europe/Berlin"}), selection(), "UTC")
    target = {"id": "workflow-1", "version": 1, "graph": original["graph"]}
    chosen = selection(operation="update", schedule_timezone="Europe/Lisbon", workflow_count=1)
    renamed = compile_authoring_plan(
        {"operation": "update", "workflow_id": "workflow-1", "title": "Renamed"}, chosen, "UTC", target)
    assert renamed["graph"]["nodes"][0]["config"]["schedule"]["timezone"] == "Europe/Berlin"
    rescheduled = compile_authoring_plan(
        {"operation": "update", "workflow_id": "workflow-1",
         "schedule": {"type": "weekly", "time": "10:00", "timezone": "UTC"}}, chosen, "UTC", target)
    assert rescheduled["graph"]["nodes"][0]["config"]["schedule"]["timezone"] == "Europe/Lisbon"


def test_multi_workflow_distinct_authored_zones_survive_global_preselection():
    send = {"kind": "send", "id": "reply", "title": "Notice", "message": [{"text": "Hello"}]}
    chosen = selection(schedule_timezone="UTC", workflow_count=2)
    for zone in ("Europe/Berlin", "America/New_York"):
        result = compile_authoring_plan(
            plan([send], schedule={"type": "weekly", "time": "09:00", "timezone": zone}), chosen, "UTC")
        assert result["graph"]["nodes"][0]["config"]["schedule"]["timezone"] == zone


def test_time_only_update_preserves_prior_zone_when_model_echoes_browser_zone():
    send = {"kind": "send", "id": "reply", "title": "Notice", "message": [{"text": "Hello"}]}
    original = compile_authoring_plan(
        plan([send], schedule={"type": "weekly", "time": "09:00", "timezone": "Europe/Berlin"}), selection(), "UTC")
    target = {"id": "workflow-1", "version": 1, "graph": original["graph"]}
    chosen = selection(operation="update", preserve_schedule_timezone=True, workflow_count=1)
    result = compile_authoring_plan(
        {"operation": "update", "workflow_id": "workflow-1",
         "schedule": {"type": "weekly", "time": "10:00", "timezone": "UTC"}}, chosen, "UTC", target)
    schedule = result["graph"]["nodes"][0]["config"]["schedule"]
    assert schedule["time"] == "10:00"
    assert schedule["timezone"] == "Europe/Berlin"


def test_multi_update_preserves_each_prior_zone_and_create_ignores_preserve_flag():
    send = {"kind": "send", "id": "reply", "title": "Notice", "message": [{"text": "Hello"}]}
    chosen = selection(operation="update", preserve_schedule_timezone=True, workflow_count=2)
    for index, zone in enumerate(("Europe/Berlin", "America/New_York")):
        original = compile_authoring_plan(
            plan([send], schedule={"type": "weekly", "time": "09:00", "timezone": zone}), selection(), "UTC")
        workflow_id = f"workflow-{index}"
        target = {"id": workflow_id, "version": 1, "graph": original["graph"]}
        result = compile_authoring_plan(
            {"operation": "update", "workflow_id": workflow_id,
             "schedule": {"type": "weekly", "time": "10:00", "timezone": "UTC"}}, chosen, "UTC", target)
        assert result["graph"]["nodes"][0]["config"]["schedule"]["timezone"] == zone
    create = compile_authoring_plan(
        plan([send], schedule={"type": "weekly", "time": "10:00"}),
        selection(preserve_schedule_timezone=True), "UTC")
    assert create["graph"]["nodes"][0]["config"]["schedule"]["timezone"] == "UTC"


def test_flat_accumulator_accepts_check_before_children_and_rejects_bad_node_without_mutation():
    author = FlatAuthoringAccumulator(selection("weather.forecast", mode="exact"), "UTC")
    with pytest.raises(ValueError, match="title and description"):
        author.accept_header({"operation": "create", "title": "Rain", "schedule": {"type": "daily"}})
    assert author.flat_snapshot() is None
    header = {"operation": "create", "title": "Rain", "description": "Report rain", "icon": "cloud-rain",
              "schedule": {"type": "daily"}}
    assert len(author.accept_header(header)["graph"]["nodes"]) == 1
    weather = {"kind": "app", "id": "forecast", "capability": "weather.forecast",
               "input_json": json.dumps({"location": "Berlin", "days": 1})}
    author.accept_node(weather)
    check = {"kind": "check", "id": "rain", "mode": "exact", "predicate_json": json.dumps({
        "op": "eq", "left": ref("forecast", "rain_expected"), "right": True})}
    assert any(node["id"] == "rain" for node in author.accept_node(check)["graph"]["nodes"])
    frozen = author.flat_snapshot()
    with pytest.raises(ValueError, match="malformed"):
        author.accept_node({"kind": "send", "id": "bad", "parent_check_id": "rain", "branch": "yes",
                            "title": "Rain", "message_json": '{"text":"a","text":"b"}'})
    assert author.flat_snapshot() == frozen
    author.accept_node({"kind": "send", "id": "umbrella", "parent_check_id": "rain", "branch": "yes",
                        "title": "Rain", "message_json": '[{"text":"Take an umbrella"}]'})
    author.accept_node({"kind": "send", "id": "dry", "parent_check_id": "rain", "branch": "no",
                        "title": "Rain", "message_json": '[{"text":"Dry today"}]'})
    assert author.snapshot()["steps"][1]["yes"][0]["id"] == "umbrella"
    assert author.compile_final()["action"] == "create_workflow"


def test_create_header_requires_icon_before_acceptance_but_normalizes_unknown_string():
    author = FlatAuthoringAccumulator(selection(), "UTC")
    header = {"operation": "create", "title": "Notices", "description": "Send notices",
              "schedule": {"type": "daily"}}
    with pytest.raises(ValueError, match="icon string"):
        author.accept_header(header)
    assert author.flat_snapshot() is None
    with pytest.raises(ValueError, match="icon string"):
        author.accept_header({**header, "icon": None})
    assert author.flat_snapshot() is None
    author.accept_header({**header, "icon": "unsupported-but-string"})
    assert author.compile_partial()["icon"] == "help-circle"


def test_schedule_rejects_fields_from_other_kinds_before_streaming_header():
    for schedule in ({"type": "weekly", "weekdays": ["monday"], "at": "07:30"},
                     {"type": "hourly", "time": "07:30"},
                     {"type": "once", "time": "07:30"},
                     {"type": "manual", "timezone": "UTC"}):
        author = FlatAuthoringAccumulator(selection(), "UTC")
        with pytest.raises(ValueError, match=f"{schedule['type']} schedule supports") as error:
            author.accept_header({"operation": "create", "title": "Test", "description": "Test",
                                  "icon": "help-circle", "schedule": schedule})
        assert "unsupported fields: " in str(error.value)
        assert "07:30" not in str(error.value)
        if schedule["type"] == "weekly":
            assert str(error.value) == "weekly schedule supports time, timezone, weekdays; unsupported fields: at"
        assert author.flat_snapshot() is None
    author = FlatAuthoringAccumulator(selection(), "UTC")
    accepted = author.accept_header({"operation": "create", "title": "Test", "description": "Test",
                                     "icon": "help-circle", "schedule": {"type": "weekly", "time": "07:30",
                                                                          "weekdays": ["monday"]}})
    assert accepted["graph"]["nodes"][0]["config"]["schedule"]["time"] == "07:30"


def test_authoring_failure_codes_are_fixed_and_hide_model_values():
    assert authoring_validation_code(ValueError(
        "weekly schedule supports time, timezone, weekdays; unsupported fields: at"), "header") == "header_schedule_field_set"
    assert authoring_validation_code(ValueError("Schedule time must be HH:MM"), "header") == "header_schedule_time"
    assert authoring_validation_code(ValueError("Schedule timezone is invalid"), "header") == "header_schedule_timezone"
    assert authoring_validation_code(ValueError("Weekly schedule needs unique weekdays"), "header") == "header_schedule_weekdays"
    assert authoring_validation_code(ValueError("Schedule type is unsupported"), "header") == "header_schedule_schema"
    assert authoring_validation_code(ValueError(
        "Authoring plan violates the selected capability schema at $.schedule.time"), "header") == "header_schedule_time"
    assert authoring_validation_code(ValueError("Partial create needs a title and description"), "header") == "header_metadata"
    assert authoring_validation_code(ValueError("Authoring plan violates the selected capability schema at $.icon"),
                                     "header") == "header_icon"
    assert authoring_validation_code(ValueError("Authoring plan violates the selected capability schema at $.steps[0]"),
                                     "node") == "node_selected_schema"
    assert authoring_validation_code(ValueError("private arbitrary model string"), "header") == "header_validation"
    assert authoring_validation_path(ValueError("Schedule timezone is invalid"), "header") == "$.schedule.timezone"
    assert authoring_validation_path(ValueError(
        "Authoring plan violates the selected capability schema at $.schedule.weekdays"), "header") == "$.schedule.weekdays"
    assert authoring_validation_path(ValueError(
        "Authoring plan violates the selected capability schema at $.private_model_value"), "header") is None
    assert authoring_validation_path(ValueError("Schedule timezone is invalid"), "node") is None


def test_flat_update_header_preserves_original_and_new_node_splices_without_dropping_reply():
    original = compile_authoring_plan(plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast",
         "input": {"location": "Paris", "days": 1}},
        {"kind": "send", "id": "reply", "title": "Forecast", "message": [ref("forecast", "summary")]},
    ]), selection("weather.forecast"), "UTC")
    target = {"id": "workflow-1", "version": 3, "graph": original["graph"]}
    author = FlatAuthoringAccumulator(selection("weather.forecast", "ai.ask", operation="update"), "UTC", target)
    author.accept_header({"operation": "update", "workflow_id": "workflow-1",
                          "schedule": {"type": "daily", "time": "10:00"}})
    assert "steps" not in author.snapshot()
    assert author.compile_final()["graph"]["nodes"][0]["config"]["schedule"]["time"] == "10:00"
    author.accept_node({"kind": "app", "id": "forecast", "capability": "weather.forecast",
                        "input_json": '{"location":"Paris","days":1}'})
    preview = author.accept_node({"kind": "ask_ai", "id": "analysis", "prompt_json": json.dumps([
        {"text": "Explain "}, ref("forecast", "results")])})
    graph = author.compile_partial()["graph"]
    assert graph == preview["graph"]
    assert {node["id"] for node in graph["nodes"]} == {"trigger", "forecast", "analysis", "reply"}
    assert {(edge["from"], edge["to"]) for edge in graph["edges"]} == {
        ("trigger", "forecast"), ("forecast", "analysis"), ("analysis", "reply")}
    assert author.compile_partial()["expected_record_version"] == 3


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


def test_event_date_named_strings_accept_structured_runtime_markers():
    # events.search declares these fields as strings without JSON Schema
    # format, while its runtime accepts relative date markers from Workflow.
    raw = plan([
        {"kind": "app", "id": "events", "capability": "events.search", "input": {"requests": [{
            "query": "robotics", "providers": ["Luma", "Eventbrite"], "location": "Lisbon",
            "event_type": "PHYSICAL", "start_date": {"$date": "next_week_start"},
            "end_date": {"$date": "next_week_end"}, "count": 10,
        }]}},
        {"kind": "send", "id": "report", "title": "Events", "message": [
            {"text": "Events: "}, ref("events", "results")]},
    ])
    chosen = selection("events.search", "ai.ask")
    Draft202012Validator(build_authoring_schema(chosen)).validate(raw)
    graph = compile_authoring_plan(raw, chosen, "UTC")["graph"]
    request = graph["nodes"][1]["config"]["input"]["requests"][0]
    assert request["start_date"] == {"$date": "next_week_start"}
    assert request["end_date"] == {"$date": "next_week_end"}
    malformed = deepcopy(raw)
    malformed["steps"][0]["input"]["requests"][0]["query"] = {"$date": "today"}
    assert list(Draft202012Validator(build_authoring_schema(chosen)).iter_errors(malformed))


def test_selected_app_schema_failure_reports_only_registry_path_and_keyword():
    raw = plan([{"kind": "app", "id": "events", "capability": "events.search", "input": {
        "requests": [{"query": "robotics", "location": "Lisbon", "providers": ["private-bad-provider"]}],
    }}])
    with pytest.raises(ValueError, match="selected capability schema") as caught:
        compile_authoring_preview(raw, selection("events.search"), "UTC")
    assert caught.value.validation_path == "$.steps[0].input.requests[0].providers[0]"
    assert caught.value.validation_keyword == "enum"
    assert "private-bad-provider" not in str(caught.value)
    raw["steps"][0]["input"]["requests"][0].pop("providers")
    raw["steps"][0]["input"]["requests"][0]["private-unknown-key"] = "sensitive"
    with pytest.raises(ValueError) as caught:
        compile_authoring_preview(raw, selection("events.search"), "UTC")
    assert caught.value.validation_path == "$.steps[0].input.requests[0]"
    assert caught.value.validation_keyword == "additionalProperties"
    assert "private-unknown-key" not in caught.value.validation_path


def test_node_schema_diagnostic_selects_the_authored_kind_without_exposing_values():
    chosen = selection("weather.forecast", "ai.ask")
    cases = [
        ({"kind": "app", "id": "weather", "capability": "weather.forecast"},
         "$.steps[0].input", "required"),
        ({"kind": "app", "id": "weather", "capability": "private-capability", "input": {}},
         "$.steps[0].capability", "enum"),
        ({"kind": "app", "id": "weather", "capability": "weather.forecast",
          "input": {"location": "Berlin", "days": "private-value"}},
         "$.steps[0].input.days", "type"),
        ({"kind": "send", "id": "reply", "message": [{"text": "private text"}]},
         "$.steps[0].title", "required"),
        ({"kind": "ask_ai", "id": "analysis", "prompt": "private prompt"},
         "$.steps[0].prompt", "type"),
    ]
    for step, path, keyword in cases:
        with pytest.raises(ValueError, match="selected capability schema") as caught:
            compile_authoring_preview(plan([step]), chosen, "UTC")
        assert caught.value.validation_path == path
        assert caught.value.validation_keyword == keyword
        assert "private" not in str(caught.value)
        assert "private" not in caught.value.validation_path

    # The Check branch schema has no single safe leaf under this compact
    # diagnostic; omit a path instead of reporting an unrelated variant.
    with pytest.raises(ValueError) as caught:
        compile_authoring_preview(plan([{"kind": "check", "id": "check", "mode": "exact",
                                         "predicate": "private", "yes": [], "no": []}]), chosen, "UTC")
    assert not hasattr(caught.value, "validation_path")


def test_imported_event_workflow_full_replay_preserves_every_unedited_field():
    source = """title: Synthetic undo guard
start_when:
  schedule: {type: weekly, weekdays: [monday], time: '08:00', timezone: Europe/Berlin}
steps:
  - id: events
    use_app_skill: events.search
    input:
      requests:
        - query: AI
          providers: [Luma, Eventbrite]
          location: Berlin
          event_type: PHYSICAL
          start_date: {$date: next_week_start}
          end_date: {$date: next_week_end}
          count: 10
  - id: report
    send_chat_message:
      title: Synthetic message
      message: "Synthetic events: {{steps.events.results}}"
      blocks:
        - {id: events, label: Synthetic event results, source: '$nodes.events.output.results'}
"""
    registry = WorkflowCapabilityRegistry()
    before = compile_workflow_yaml(source, registry).graph.model_dump(mode="json", by_alias=True)
    before["nodes"][2]["ui"] = {"position": {"x": 40, "y": 25}}
    target = {"id": "workflow-1", "version": 3, "graph": before}
    changed_input = deepcopy(before["nodes"][1]["config"]["input"])
    changed_input["requests"][0]["query"] = "robotics"
    changed_input["requests"][0]["location"] = "Lisbon"
    raw = {"operation": "update", "workflow_id": "workflow-1", "steps": [
        {"kind": "app", "id": "events", "capability": "events.search", "input": changed_input},
        {"kind": "send", "id": "report"},
    ]}
    chosen = selection("events.search", "ai.ask", operation="update")
    expected = deepcopy(before)
    expected["nodes"][1]["config"]["input"] = changed_input
    assert compile_authoring_plan(raw, chosen, "UTC", target)["graph"] == expected
    author = FlatAuthoringAccumulator(chosen, "UTC", target)
    author.accept_header({"operation": "update", "workflow_id": "workflow-1"})
    author.accept_node({"kind": "app", "id": "events", "capability": "events.search",
                        "input_json": json.dumps(changed_input)})
    author.accept_node({"kind": "send", "id": "report"})
    assert author.compile_final()["graph"] == expected

    # Reauthoring a Send is allowed; its omitted block label keeps the prior
    # presentation label for the same stable block ID.
    reauthored = deepcopy(raw)
    reauthored["steps"][1] = {"kind": "send", "id": "report", "title": "New message",
                             "message": [{"text": "Updated events"}],
                             "blocks": [{"id": "events", "source": {"step": "events", "field": "results"}}]}
    changed = compile_authoring_plan(reauthored, chosen, "UTC", target)["graph"]
    assert changed["nodes"][2]["config"]["blocks"][0]["label"] == "Synthetic event results"
    reauthored["steps"][1]["blocks"][0]["label"] = "New label"
    changed = compile_authoring_plan(reauthored, chosen, "UTC", target)["graph"]
    assert changed["nodes"][2]["config"]["blocks"][0]["label"] == "New label"


def test_id_only_send_reuse_rejects_create_unknown_and_wrong_prior_type():
    send = {"kind": "send", "id": "report", "title": "Message", "message": [{"text": "Hello"}]}
    with pytest.raises(ValueError, match="unchanged existing Send ID"):
        compile_authoring_preview(plan([{"kind": "send", "id": "report"}]), selection(), "UTC")
    before = compile_authoring_plan(plan([send]), selection(), "UTC")["graph"]
    target = {"id": "workflow-1", "graph": before}
    with pytest.raises(ValueError, match="unchanged existing Send ID"):
        compile_authoring_preview({"operation": "update", "workflow_id": "workflow-1",
                                   "steps": [{"kind": "send", "id": "missing"}]},
                                  selection(operation="update"), "UTC", target)
    app_send = {**send, "message": [{"text": "Events: "}, ref("events", "summary")]}
    app_before = compile_authoring_plan(plan([
        {"kind": "app", "id": "events", "capability": "events.search",
         "input": {"requests": [{"query": "AI", "location": "Berlin"}]}}, app_send,
    ]), selection("events.search"), "UTC")["graph"]
    app_target = {"id": "workflow-2", "graph": app_before}
    with pytest.raises(ValueError, match="unchanged existing Send ID"):
        compile_authoring_preview({"operation": "update", "workflow_id": "workflow-2",
                                   "steps": [{"kind": "send", "id": "events"}]},
                                  selection(operation="update"), "UTC", app_target)


def test_send_schema_accepts_only_complete_authoring_or_exact_id_reuse():
    chosen = selection()
    schema = Draft202012Validator(build_authoring_schema(chosen))
    complete = {"kind": "send", "id": "reply", "title": "Notice", "message": [{"text": "Hello"}]}
    for incomplete in ({"kind": "send", "id": "reply", "message": [{"text": "Changed"}]},
                       {"kind": "send", "id": "reply", "title": "Changed"},
                       {"kind": "send", "id": "reply", "blocks": []},
                       {"kind": "send", "id": "reply", "title": "Changed", "blocks": []}):
        assert list(schema.iter_errors(plan([incomplete])))
        with pytest.raises(ValueError, match="selected capability schema"):
            compile_authoring_preview(plan([incomplete]), chosen, "UTC")
    assert not list(schema.iter_errors(plan([complete])))
    before = compile_authoring_plan(plan([complete]), chosen, "UTC")["graph"]
    target = {"id": "workflow-1", "graph": before}
    author = FlatAuthoringAccumulator(selection(operation="update"), "UTC", target)
    author.accept_header({"operation": "update", "workflow_id": "workflow-1"})
    frozen = author.flat_snapshot()
    for partial in ({"kind": "send", "id": "reply", "message_json": '[{"text":"Changed"}]'},
                    {"kind": "send", "id": "reply", "title": "Changed"},
                    {"kind": "send", "id": "reply", "blocks_json": "[]"}):
        with pytest.raises(ValueError, match="selected capability schema"):
            author.accept_node(partial)
        assert author.flat_snapshot() == frozen
    author.accept_node({"kind": "send", "id": "reply"})
    assert author.compile_final()["graph"] == before


def test_id_only_app_and_ask_ai_replay_preserves_legacy_prompt_and_modified_node_ui():
    created = plan([
        {"kind": "app", "id": "events", "capability": "events.search",
         "input": {"requests": [{"query": "AI", "location": "Berlin", "count": 10}]}},
        {"kind": "ask_ai", "id": "summary", "prompt": [
            {"text": "Summarize "}, ref("events", "results")]},
        {"kind": "send", "id": "reply", "title": "Events", "message": [ref("summary", "answer")]},
    ])
    before = compile_authoring_plan(created, selection("events.search", "ai.ask"), "UTC")["graph"]
    before["nodes"][1]["ui"] = {"position": {"x": 10, "y": 20}}
    before["nodes"][2]["ui"] = {"position": {"x": 21, "y": 32}}
    before["nodes"][2]["config"]["input"]["prompt"] = "Summarize {{steps.events.results}}"
    target = {"id": "workflow-1", "version": 3, "graph": before}
    changed_input = deepcopy(before["nodes"][1]["config"]["input"])
    changed_input["requests"][0]["query"] = "robotics"
    changed_input["requests"][0]["location"] = "Lisbon"
    chosen = selection("events.search", "ai.ask", operation="update")
    raw = {"operation": "update", "workflow_id": "workflow-1", "steps": [
        {"kind": "app", "id": "events", "capability": "events.search", "input": changed_input},
        {"kind": "ask_ai", "id": "summary"}, {"kind": "send", "id": "reply"},
    ]}
    expected = deepcopy(before)
    expected["nodes"][1]["config"]["input"] = changed_input
    assert compile_authoring_plan(raw, chosen, "UTC", target)["graph"] == expected
    author = FlatAuthoringAccumulator(chosen, "UTC", target)
    author.accept_header({"operation": "update", "workflow_id": "workflow-1"})
    author.accept_node({"kind": "app", "id": "events", "capability": "events.search",
                        "input_json": json.dumps(changed_input)})
    author.accept_node({"kind": "ask_ai", "id": "summary"})
    author.accept_node({"kind": "send", "id": "reply"})
    assert author.compile_final()["graph"] == expected


def test_id_only_app_and_ask_ai_reuse_rejects_wrong_scope_before_preview():
    created = plan([
        {"kind": "app", "id": "events", "capability": "events.search",
         "input": {"requests": [{"query": "AI", "location": "Berlin"}]}},
        {"kind": "ask_ai", "id": "summary", "prompt": [
            {"text": "Summarize "}, ref("events", "results")]},
        {"kind": "send", "id": "reply", "title": "Events", "message": [ref("summary", "answer")]},
    ])
    base = selection("events.search", "ai.ask")
    target = {"id": "workflow-1", "graph": compile_authoring_plan(created, base, "UTC")["graph"]}
    cases = [
        (plan([{"kind": "app", "id": "events"}]), base, None, "App reuse requires"),
        (plan([{"kind": "ask_ai", "id": "summary"}]), base, None, "Ask AI reuse requires"),
        ({"operation": "update", "workflow_id": "workflow-1", "steps": [{"kind": "app", "id": "missing"}]},
         selection("events.search", operation="update"), target, "App reuse requires"),
        ({"operation": "update", "workflow_id": "workflow-1", "steps": [{"kind": "ask_ai", "id": "missing"}]},
         selection("ai.ask", operation="update"), target, "Ask AI reuse requires"),
        ({"operation": "update", "workflow_id": "workflow-1", "steps": [{"kind": "app", "id": "summary"}]},
         selection("events.search", operation="update"), target, "selected available capability"),
        ({"operation": "update", "workflow_id": "workflow-1", "steps": [{"kind": "ask_ai", "id": "events"}]},
         selection("ai.ask", operation="update"), target, "Ask AI reuse requires"),
        ({"operation": "update", "workflow_id": "workflow-1", "steps": [{"kind": "app", "id": "events"}]},
         selection("ai.ask", operation="update"), target, "selected available capability"),
        ({"operation": "update", "workflow_id": "workflow-1", "steps": [{"kind": "ask_ai", "id": "summary"}]},
         selection("events.search", operation="update"), target, "not selected or available"),
    ]
    disabled = selection("events.search", operation="update")
    disabled = replace(disabled, capabilities=[disabled.capabilities[0].model_copy(update={"enabled": False})])
    cases.append(({"operation": "update", "workflow_id": "workflow-1",
                   "steps": [{"kind": "app", "id": "events"}]}, disabled, target, "selected available capability"))
    disabled_ai = selection("ai.ask", operation="update")
    disabled_ai = replace(disabled_ai, capabilities=[disabled_ai.capabilities[0].model_copy(update={"enabled": False})])
    cases.append(({"operation": "update", "workflow_id": "workflow-1",
                   "steps": [{"kind": "ask_ai", "id": "summary"}]}, disabled_ai, target,
                  "not selected or available"))
    for raw, chosen, selected_workflow, reason in cases:
        with pytest.raises(ValueError, match=reason):
            compile_authoring_preview(raw, chosen, "UTC", selected_workflow)


def test_weather_results_are_declared_for_ai_forecast_formatting():
    raw = plan([
        {"kind": "app", "id": "berlin", "capability": "weather.forecast",
         "input": {"location": "Berlin", "days": 1}},
        {"kind": "ask_ai", "id": "format", "prompt": [
            {"text": "Report the actual Berlin forecast, or say no forecast is available: "},
            ref("berlin", "results")]},
        {"kind": "send", "id": "reply", "title": "Forecast", "message": [ref("format", "answer")]},
    ])
    graph = compile_authoring_plan(raw, selection("weather.forecast", "ai.ask"), "Europe/Berlin")["graph"]
    assert "{{ $nodes.berlin.output.results }}" in graph["nodes"][2]["config"]["input"]["prompt"]


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


def test_cosmetic_icon_fallback_keeps_graph_validation_strict():
    raw = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast",
         "input": {"location": "Berlin", "days": 1}},
        {"kind": "send", "id": "reply", "title": "Forecast", "message": [ref("forecast", "summary")]},
    ])
    original = compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")
    raw["icon"] = "shopping-bag"
    normalized = compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")
    assert normalized["icon"] == "help-circle"
    assert normalized["graph"] == original["graph"]
    preview = compile_authoring_preview(raw, selection("weather.forecast"), "Europe/Berlin")
    assert preview["icon"] == "help-circle"
    raw["steps"][0]["capability"] = "web.search"
    with pytest.raises(ValueError, match="selected capability schema"):
        compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")
    raw["icon"] = 42
    with pytest.raises(ValueError, match="selected capability schema"):
        compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")


def test_update_unknown_icon_preserves_selected_icon():
    raw = plan([
        {"kind": "app", "id": "forecast", "capability": "weather.forecast", "input": {"location": "Berlin", "days": 1}},
        {"kind": "send", "id": "reply", "title": "Forecast", "message": [ref("forecast", "summary")]},
    ])
    prior = compile_authoring_plan(raw, selection("weather.forecast"), "Europe/Berlin")
    selected = {"id": "workflow-1", "version": 2, "icon": "cloud-rain", "graph": prior["graph"]}
    update = {"operation": "update", "workflow_id": "workflow-1", "icon": "shopping-bag", "title": "Updated forecast"}
    result = compile_authoring_plan(update, selection("weather.forecast", operation="update"),
                                    "Europe/Berlin", selected)
    assert "icon" not in result
    preview = compile_authoring_preview(update, selection("weather.forecast", operation="update"),
                                        "Europe/Berlin", selected)
    assert preview["icon"] == "cloud-rain"


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
