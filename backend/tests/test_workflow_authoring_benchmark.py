"""Cheap protocol and oracle checks for the opt-in live authoring comparison."""
# contract-test-file: infrastructure

import json
from types import SimpleNamespace

import pytest

from backend.scripts.benchmark_workflow_authoring import (
    CASES, _provider_cost, _transport_schema, decode_transport, oracle, validate_graph,
)
from backend.core.api.app.services.workflow_models import WorkflowGraph


def _rain_graph() -> dict:
    return {"version": 2, "trigger_node_id": "start", "nodes": [
        {"id": "start", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "08:00", "timezone": "Europe/Berlin"}}},
        {"id": "weather", "type": "app_skill_action", "config": {"app_id": "weather", "skill_id": "forecast", "input": {"location": "Berlin", "days": 1}}},
        {"id": "check", "type": "check", "config": {"mode": "exact", "predicate": {"left": "$nodes.weather.output.rain_expected", "op": "eq", "right": True}}},
        {"id": "yes", "type": "send_chat_message", "config": {"title": "Rain", "message": "{{steps.weather.rain_summary}} Take an umbrella."}},
        {"id": "no", "type": "send_chat_message", "config": {"title": "Dry", "message": "{{steps.weather.rain_summary}} It should be dry."}},
    ], "edges": [{"from": "start", "to": "weather"}, {"from": "weather", "to": "check"},
                 {"from": "check", "to": "yes", "branch": "yes"},
                 {"from": "check", "to": "no", "branch": "no"}]}


def _selection():
    return SimpleNamespace(capabilities=[SimpleNamespace(
        id="weather.forecast", metadata={"input_schema": {"type": "object", "properties": {
            "location": {"type": "string"}, "days": {"type": "integer"},
            "start_date": {"type": "string", "format": "date"}},
            "required": ["location"]}})])


def _envelope(raw: dict) -> dict:
    nodes = []
    for node in raw["nodes"]:
        config = node["config"]
        if node["type"] == "app_skill_action":
            config = {"capability_id": f"{config['app_id']}.{config['skill_id']}",
                      "input": config["input"]}
        nodes.append({"id": node["id"], "type": node["type"],
                      "title": None, "config": config})
    return {"version": raw["version"], "trigger_node_id": raw["trigger_node_id"],
            "edges": [{**edge, "branch": edge.get("branch")} for edge in raw["edges"]],
            "nodes": nodes}


def test_typed_transport_decodes_only_optional_nulls():
    raw = _rain_graph()
    envelope = _envelope(raw)
    envelope["nodes"][1]["config"]["input"].update({"days": None, "start_date": None})
    envelope["nodes"][3]["config"].update({"blocks": [], "message": "Umbrella"})
    decoded = decode_transport(envelope, _selection())
    assert decoded["nodes"][1]["config"] == {"app_id": "weather", "skill_id": "forecast", "input": {"location": "Berlin"}}
    envelope["nodes"][1]["config"] = []
    with pytest.raises(ValueError, match="object"):
        decode_transport(envelope, _selection())


def test_transport_preserves_dangling_edge_for_graph_validator():
    raw = _rain_graph()
    raw["edges"][-1]["to"] = "missing_end"
    envelope = _envelope(raw)
    decoded = decode_transport(envelope, _selection())
    assert decoded["edges"][-1]["to"] == "missing_end"
    with pytest.raises(Exception, match="edges must reference existing nodes"):
        validate_graph(decoded, {"weather.forecast"})


def test_dynamic_schema_closes_node_configs_over_selected_skills():
    selection = _selection()
    selection.capabilities.append(SimpleNamespace(
        id="web.search", metadata={"input_schema": {"type": "object", "properties": {
            "requests": {"type": "array", "items": {"type": "object", "properties": {
                "query": {"type": "string"}}, "required": ["query"]}}},
            "required": ["requests"]}}))
    schema = _transport_schema(selection)
    variants = schema["properties"]["nodes"]["items"]["anyOf"]
    app = next(item for item in variants if item["properties"]["type"].get("const") == "app_skill_action")
    assert sum(item["properties"]["type"].get("const") == "app_skill_action" for item in variants) == 1
    app_configs = app["properties"]["config"]["anyOf"]
    assert {item["properties"]["capability_id"]["const"] for item in app_configs} == {
        "weather.forecast", "web.search"}
    config = app_configs[0]
    assert config["additionalProperties"] is False
    assert config["properties"]["capability_id"]["const"] == "weather.forecast"
    assert "app_id" not in config["properties"]
    assert "skill_id" not in config["properties"]
    inputs = config["properties"]["input"]
    assert inputs["properties"]["days"]["anyOf"][-1] == {"type": "null"}
    assert inputs["properties"]["start_date"]["anyOf"][1]["properties"]["$date"]["enum"][0] == "today"
    assert "config_json" not in json.dumps(schema)
    for variant in variants:
        config_schema = variant["properties"]["config"]
        if config_schema.get("properties") == {}:
            assert "required" not in config_schema
            assert config_schema["additionalProperties"] is False


def test_transport_rejects_unselected_capability_identity():
    envelope = _envelope(_rain_graph())
    envelope["nodes"][1]["config"]["capability_id"] = "web.search"
    with pytest.raises(ValueError, match="not selected"):
        decode_transport(envelope, _selection())


def test_provider_cost_uses_cached_and_billed_output_tokens():
    usage = {"prompt_tokens": 1000, "completion_tokens": 500,
             "prompt_tokens_details": {"cached_tokens": 200}}
    assert _provider_cost("groq", usage) == round((800 * .15 + 200 * .075 + 500 * .60) / 1_000_000, 8)


def test_oracle_catches_schedule_action_and_branch_drift():
    case = CASES[0]
    graph = WorkflowGraph.model_validate(_rain_graph())
    assert oracle(graph, case) == []
    drift = _rain_graph()
    drift["nodes"][0]["config"]["schedule"]["time"] = "09:00"
    drift["nodes"][1]["config"]["input"]["location"] = "Paris"
    drift["nodes"][3]["config"]["message"] = "Rain is coming."
    issues = oracle(WorkflowGraph.model_validate(drift), case)
    assert "schedule time mismatch" in issues
    assert "missing action input Berlin" in issues
    assert "yes branch is missing umbrella" in issues


def test_oracle_rejects_implicit_seven_day_weather_default():
    graph = _rain_graph()
    del graph["nodes"][1]["config"]["input"]["days"]
    issues = oracle(WorkflowGraph.model_validate(graph), CASES[0])
    assert "weather action weather lacks exact today range" in issues


def test_validator_rejects_unselected_action():
    assert len(validate_graph(_rain_graph(), {"weather.forecast"}).nodes) == 5
    with pytest.raises(ValueError, match="not selected"):
        validate_graph(_rain_graph(), {"news.search"})
