# backend/tests/test_workflows_models.py
#
# Contract tests for Workflows V1 graph validation, feature gating, ownership,
# and capability metadata.
#
# Spec: docs/specs/workflows-v1/spec.yml

import json

import pytest
from pydantic import ValidationError

from backend.core.api.app.services.feature_availability_service import FeatureAvailabilityService, FeatureDefinition
from backend.core.api.app.services.workflow_models import WorkflowGraph
from backend.core.api.app.services.workflow_service import (
    InMemoryWorkflowRepository,
    WORKFLOW_PLATFORM_FEATURE,
    WorkflowFeatureDisabledError,
    WorkflowService,
)


def rain_graph() -> dict:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {
                "id": "trigger",
                "type": "schedule_trigger",
                "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "Europe/Berlin"}},
            },
            {
                "id": "weather",
                "type": "app_skill_action",
                "config": {"app_id": "weather", "skill_id": "forecast", "input": {"location": "Berlin", "days": 1}},
            },
            {
                "id": "decision",
                "type": "decision",
                "config": {"predicate": {"left": "$nodes.weather.output.rain_probability", "op": "gte", "right": 60}},
            },
            {"id": "notify", "type": "send_notification", "config": {"title": "Rain today", "body": "Take an umbrella."}},
            {"id": "email", "type": "send_email_notification", "config": {"title": "Rain today", "body": "Take an umbrella."}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"from": "trigger", "to": "weather"},
            {"from": "weather", "to": "decision"},
            {"from": "decision", "to": "notify", "branch": "yes"},
            {"from": "notify", "to": "email"},
            {"from": "email", "to": "end"},
        ],
    }


def disabled_workflow_service() -> WorkflowService:
    return WorkflowService(
        feature_availability=FeatureAvailabilityService(
            definitions=[FeatureDefinition(id=WORKFLOW_PLATFORM_FEATURE, kind="platform", default_enabled=False)],
            config={},
        )
    )


def test_workflow_graph_requires_exactly_one_trigger() -> None:
    graph = rain_graph()
    graph["nodes"].append({"id": "manual", "type": "manual_trigger", "config": {}})

    with pytest.raises(ValidationError, match="exactly one trigger"):
        WorkflowGraph.model_validate(graph)


def test_decision_predicates_reject_arbitrary_code_operator() -> None:
    graph = rain_graph()
    graph["nodes"][2]["config"]["predicate"] = {"op": "eval", "left": "__import__('os')", "right": True}

    with pytest.raises(ValidationError, match="Unsupported decision operator"):
        WorkflowGraph.model_validate(graph)


def test_app_skill_actions_are_limited_to_v1_allowlist() -> None:
    graph = rain_graph()
    graph["nodes"][1]["config"] = {"app_id": "calendar", "skill_id": "list_events", "input": {}}

    with pytest.raises(ValidationError, match="not enabled"):
        WorkflowGraph.model_validate(graph)


def test_repeat_nodes_require_safety_bounds() -> None:
    graph = rain_graph()
    graph["nodes"].append({"id": "repeat", "type": "repeat", "config": {"max_iterations": 10}})
    graph["edges"].append({"from": "end", "to": "repeat"})

    with pytest.raises(ValidationError, match="max_duration_seconds"):
        WorkflowGraph.model_validate(graph)


def test_future_custom_code_node_is_not_executable_in_v1() -> None:
    graph = rain_graph()
    graph["nodes"].append({"id": "code", "type": "custom_code", "config": {"runtime": "python"}})

    with pytest.raises(ValidationError, match="future UI only"):
        WorkflowGraph.model_validate(graph)


def test_workflow_service_blocks_when_platform_feature_disabled() -> None:
    service = disabled_workflow_service()

    with pytest.raises(WorkflowFeatureDisabledError):
        service.create_workflow("alice", "Rain", rain_graph())


def test_workflow_service_enforces_owner_isolation() -> None:
    service = WorkflowService()
    workflow = service.create_workflow("alice", "Rain", rain_graph())

    assert service.get_workflow(workflow.id, "alice").id == workflow.id
    with pytest.raises(KeyError):
        service.get_workflow(workflow.id, "bob")


def test_workflow_definition_rows_store_sensitive_content_as_encrypted_blob_refs() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository=repository)

    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph())
    raw_workflow_rows = json.dumps(repository.workflows, sort_keys=True)
    raw_blob_rows = json.dumps(repository.encrypted_blobs, sort_keys=True)

    assert service.get_workflow(workflow.id, "alice").title == "Daily rain alert"
    assert "Daily rain alert" not in raw_workflow_rows
    assert "Berlin" not in raw_workflow_rows
    assert "weather" not in raw_workflow_rows
    assert "alice" not in raw_workflow_rows
    assert "encrypted_graph_ref" in raw_workflow_rows
    assert "Daily rain alert" not in raw_blob_rows
    assert "Berlin" not in raw_blob_rows
    assert "weather" not in raw_blob_rows
    assert "alice" not in raw_blob_rows


def test_workflow_run_content_retention_defaults_updates_and_rejects_unknown_values() -> None:
    service = WorkflowService()
    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph())

    assert workflow.run_content_retention == "last_5"
    assert service.update_workflow(workflow.id, "alice", run_content_retention="none").run_content_retention == "none"
    with pytest.raises(ValueError, match="not_a_mode"):
        service.update_workflow(workflow.id, "alice", run_content_retention="not_a_mode")


def test_capabilities_include_safe_v1_app_skills_and_disabled_custom_code() -> None:
    service = WorkflowService()
    capabilities = {item.id: item for item in service.capabilities()}

    assert capabilities["weather:forecast"].enabled is True
    assert capabilities["news:search"].enabled is True
    assert capabilities["custom_code"].enabled is False
