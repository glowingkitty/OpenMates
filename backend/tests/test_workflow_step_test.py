# backend/tests/test_workflow_step_test.py
#
# Dedicated Workflow action-test contracts. Step tests execute the real selected
# action path, persist an inspectable step_test run, and do not require the
# workflow itself to be enabled.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

import pytest

from backend.core.api.app.services.workflow_models import WorkflowRunStatus
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.tests.test_workflow_runner import FakeActionAdapter, FakeAppSkillAdapter, rain_graph
from backend.tests.workflow_test_utils import workflow_service


@pytest.mark.asyncio
async def test_step_test_records_real_output_without_enabling_workflow() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Draft rain", rain_graph(), enabled=False)
    app_adapter = FakeAppSkillAdapter()

    run = await WorkflowRunner(service, app_skill_adapter=app_adapter, action_adapter=FakeActionAdapter()).run_step_test(
        workflow,
        "alice",
        "weather",
        input_override={"location": "Paris", "mock_rain_probability": 42},
    )

    assert run.trigger_type == "step_test"
    assert run.status == WorkflowRunStatus.COMPLETED
    assert run.node_runs[0].output_summary["summary"] == "Weather forecast for Paris"
    assert service.get_workflow(workflow.id, "alice").enabled is False
    assert service.get_run(workflow.id, run.id, "alice").id == run.id


@pytest.mark.asyncio
async def test_step_test_missing_step_fails_visibly() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Draft rain", rain_graph(), enabled=False)

    with pytest.raises(ValueError, match="Workflow step not found"):
        await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=FakeActionAdapter()).run_step_test(
            workflow,
            "alice",
            "missing",
        )
