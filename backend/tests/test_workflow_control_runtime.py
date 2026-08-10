# backend/tests/test_workflow_control_runtime.py
#
# Contracts for YAML-authored Workflow controls and isolated real step-test runs.
# These tests cover the CLI runtime slice without requiring browser UI.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

import pytest

from backend.core.api.app.services.workflow_models import WorkflowRunStatus
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_yaml_compiler import compile_workflow_yaml
from backend.tests.test_workflow_runner import FakeActionAdapter, FakeAppSkillAdapter
from backend.tests.workflow_test_utils import workflow_service


CONTROL_WORKFLOW_YAML = """
title: Control workflow
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
      mock_rain_probability: 70
  - id: check
    if:
      left: "{{ steps.forecast.rain_probability }}"
      op: gte
      right: 60
    if_true:
      - id: wait
        wait:
          seconds: 1
    if_false: []
"""


def test_yaml_compiler_maps_plain_language_controls_to_runtime_nodes() -> None:
    compilation = compile_workflow_yaml(CONTROL_WORKFLOW_YAML)

    node_types = {node.id: node.type.value for node in compilation.graph.nodes}
    assert node_types["check"] == "decision"
    assert node_types["wait"] == "wait"
    assert next(node for node in compilation.graph.nodes if node.id == "check").config["predicate"]["left"] == "$nodes.forecast.output.rain_probability"
    assert ("check", "wait", "true") in [
        (edge.from_node, edge.to_node, edge.branch)
        for edge in compilation.graph.edges
    ]


@pytest.mark.asyncio
async def test_yaml_if_branch_and_wait_execute_with_inspectable_step_outputs() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Control workflow", compile_workflow_yaml(CONTROL_WORKFLOW_YAML).graph, enabled=True)

    run = await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=FakeActionAdapter()).run_workflow(workflow, "alice", trigger_type="schedule")

    assert run.status == WorkflowRunStatus.COMPLETED
    assert [node.node_id for node in run.node_runs] == ["trigger", "forecast", "check", "wait"]
    assert run.node_runs[2].output_summary == {"matched": True, "branch": "yes"}
    assert run.node_runs[3].output_summary == {"waited": True, "seconds": 1, "until": None}


@pytest.mark.asyncio
async def test_step_test_runs_real_selected_action_even_when_workflow_is_disabled() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Disabled test workflow", compile_workflow_yaml(CONTROL_WORKFLOW_YAML).graph, enabled=False)
    app_adapter = FakeAppSkillAdapter()

    run = await WorkflowRunner(service, app_skill_adapter=app_adapter, action_adapter=FakeActionAdapter()).run_step_test(
        workflow,
        "alice",
        "forecast",
        input_override={"location": "Paris", "mock_rain_probability": 5},
    )

    assert run.trigger_type == "step_test"
    assert run.status == WorkflowRunStatus.COMPLETED
    assert run.node_runs[0].node_id == "forecast"
    assert app_adapter.calls == [
        {
            "app_id": "weather",
            "skill_id": "forecast",
            "request": {"location": "Paris", "mock_rain_probability": 5},
        }
    ]
