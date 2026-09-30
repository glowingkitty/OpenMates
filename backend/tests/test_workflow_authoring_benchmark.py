"""Cheap protocol and oracle checks for the opt-in live authoring comparison."""
# contract-test-file: infrastructure

import json

import pytest

from backend.scripts.benchmark_workflow_authoring import CASES, decode_transport, oracle, validate_graph
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


def test_transport_decodes_config_without_implicit_coercion():
    raw = _rain_graph()
    envelope = {"version": raw["version"], "trigger_node_id": raw["trigger_node_id"],
                "edges": [{**edge, "branch": edge.get("branch")} for edge in raw["edges"]],
                "nodes": [{"id": node["id"], "type": node["type"], "title": None,
                           "config_json": json.dumps(node["config"])} for node in raw["nodes"]]}
    assert decode_transport(envelope)["nodes"][1]["config"]["input"]["location"] == "Berlin"
    envelope["nodes"][1]["config_json"] = "[]"
    with pytest.raises(ValueError, match="JSON object"):
        decode_transport(envelope)


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
