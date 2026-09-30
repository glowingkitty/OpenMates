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


def test_typed_transport_decodes_only_optional_nulls():
    raw = _rain_graph()
    envelope = {"version": raw["version"], "trigger_node_id": raw["trigger_node_id"],
                "edges": [{**edge, "branch": edge.get("branch")} for edge in raw["edges"]],
                "nodes": [{"id": node["id"], "type": node["type"], "title": None,
                           "config": node["config"]} for node in raw["nodes"]]}
    envelope["nodes"][1]["config"]["input"].update({"days": None, "start_date": None})
    envelope["nodes"][3]["config"].update({"blocks": [], "message": "Umbrella"})
    assert decode_transport(envelope, _selection())["nodes"][1]["config"]["input"] == {"location": "Berlin"}
    envelope["nodes"][1]["config"] = []
    with pytest.raises(ValueError, match="object"):
        decode_transport(envelope, _selection())


def test_dynamic_schema_closes_node_configs_over_selected_skills():
    schema = _transport_schema(_selection())
    variants = schema["properties"]["nodes"]["items"]["anyOf"]
    app = next(item for item in variants if item["properties"]["type"].get("const") == "app_skill_action")
    config = app["properties"]["config"]
    assert config["additionalProperties"] is False
    assert config["properties"]["app_id"]["const"] == "weather"
    assert config["properties"]["skill_id"]["const"] == "forecast"
    inputs = config["properties"]["input"]
    assert inputs["properties"]["days"]["anyOf"][-1] == {"type": "null"}
    assert inputs["properties"]["start_date"]["anyOf"][1]["properties"]["$date"]["enum"][0] == "today"
    assert "config_json" not in json.dumps(schema)


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


def test_validator_rejects_unselected_action():
    assert len(validate_graph(_rain_graph(), {"weather.forecast"}).nodes) == 5
    with pytest.raises(ValueError, match="not selected"):
        validate_graph(_rain_graph(), {"news.search"})
