# backend/tests/test_workflow_yaml_validation.py
#
# Focused contracts for the first authoritative Workflow YAML compiler slice.
# These tests keep unsafe parsing, draft structural validation, and graph
# translation independent of routes, persistence, and runtime execution.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

import pytest

from backend.core.api.app.services.workflow_yaml_compiler import (
    WorkflowYamlParseError,
    compile_workflow_yaml,
    parse_workflow_yaml,
    validate_workflow_yaml,
)


VALID_WORKFLOW_YAML = """
title: Daily rain alert
description: Send a notification when rain is likely.
start_when:
  schedule:
    type: daily
    time: "07:00"
    timezone: Europe/Berlin
steps:
  - id: forecast
    use_app_skill: weather.forecast
    input:
      location: Berlin
      days: 1
  - id: notify
    send_notification:
      title: Rain today
      body: Take an umbrella.
"""


def test_safe_yaml_parser_accepts_plain_workflow_mappings() -> None:
    document = parse_workflow_yaml(VALID_WORKFLOW_YAML)

    assert document["title"] == "Daily rain alert"
    assert document["steps"][0]["use_app_skill"] == "weather.forecast"


def test_safe_yaml_parser_rejects_duplicate_keys_and_aliases() -> None:
    duplicate_title = VALID_WORKFLOW_YAML.replace("title: Daily rain alert", "title: First\ntitle: Second")

    with pytest.raises(WorkflowYamlParseError, match="YAML_DUPLICATE_KEY"):
        parse_workflow_yaml(duplicate_title)

    with pytest.raises(WorkflowYamlParseError, match="YAML_ANCHORS_DISABLED"):
        parse_workflow_yaml(VALID_WORKFLOW_YAML.replace("location: Berlin", "location: &berlin Berlin\n      city: *berlin"))


def test_structurally_valid_draft_reports_missing_runtime_input_without_rejecting_draft() -> None:
    result = validate_workflow_yaml(VALID_WORKFLOW_YAML.replace("location: Berlin", "location: \"\""))

    assert result.draft_valid is True
    assert result.enable_ready is False
    assert result.graph is not None
    assert [(diagnostic.code, diagnostic.path) for diagnostic in result.diagnostics] == [
        ("REQUIRED_RUNTIME_INPUT", "steps[0].input.location")
    ]


def test_unknown_fields_make_a_workflow_structurally_invalid() -> None:
    result = validate_workflow_yaml(VALID_WORKFLOW_YAML + "unexpected: value\n")

    assert result.draft_valid is False
    assert result.graph is None
    assert [(diagnostic.code, diagnostic.path) for diagnostic in result.diagnostics] == [
        ("UNKNOWN_FIELD", "unexpected")
    ]


def test_empty_if_branches_are_structurally_valid_do_nothing_paths() -> None:
    workflow = VALID_WORKFLOW_YAML.replace(
        "  - id: notify\n    send_notification:\n      title: Rain today\n      body: Take an umbrella.\n",
        """  - id: rain_check
    if:
      left: "{{ steps.forecast.rain_probability }}"
      op: gte
      right: 60
    if_true: []
    if_false: []
""",
    )

    result = validate_workflow_yaml(workflow)

    assert result.draft_valid is True
    assert result.graph is not None


def test_compiler_translates_minimal_yaml_to_existing_workflow_graph() -> None:
    compilation = compile_workflow_yaml(VALID_WORKFLOW_YAML)

    assert compilation.title == "Daily rain alert"
    assert compilation.graph.trigger_node_id == "trigger"
    assert [(node.id, node.type.value) for node in compilation.graph.nodes] == [
        ("trigger", "schedule_trigger"),
        ("forecast", "app_skill_action"),
        ("notify", "send_notification"),
    ]
    assert compilation.graph.nodes[1].config == {
        "app_id": "weather",
        "skill_id": "forecast",
        "input": {"location": "Berlin", "days": 1},
    }
    assert [(edge.from_node, edge.to_node, edge.branch) for edge in compilation.graph.edges] == [
        ("trigger", "forecast", None),
        ("forecast", "notify", None),
    ]
