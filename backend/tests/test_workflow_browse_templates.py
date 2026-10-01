"""Executable contracts for the templates offered by the web workflow browser."""

import json
from pathlib import Path

import pytest

from backend.core.api.app.services.workflow_models import WorkflowGraph
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.tests.test_workflow_runner import FakeActionAdapter, FakeAppSkillAdapter
from backend.tests.workflow_test_utils import workflow_service


CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend/packages/ui/src/components/workflows/workflowTemplates.json"
)


class RecordingMessageAdapter(FakeActionAdapter):
    async def send_chat_message(self, config, context, user_id):
        del context, user_id
        self.calls.append({"type": "send_chat_message", "config": config})
        return {"chat_id": "isolated-test-chat", "message": config["message"]}


# contract-test: supporting surface=rest_api assertions=workflows-ui.workspace.owned-library-and-templates,workflows.mvp.steps
@pytest.mark.asyncio
async def test_browse_templates_create_disabled_and_execute_with_real_graph_runner() -> None:
    catalog = json.loads(CATALOG_PATH.read_text())
    assert {item["id"] for item in catalog} == {
        "daily-planning-reminder",
        "weekly-review-reminder",
    }

    for template in catalog:
        graph = WorkflowGraph.model_validate(template["graph"])
        service = workflow_service()
        workflow = service.create_workflow("template-owner", template["title"], graph, enabled=False)
        actions = RecordingMessageAdapter()
        skills = FakeAppSkillAdapter()

        assert workflow.enabled is False
        assert actions.calls == []
        run = await WorkflowRunner(
            service, app_skill_adapter=skills, action_adapter=actions
        ).run_workflow(workflow, "template-owner", trigger_type="schedule")

        assert run.status == "completed"
        assert [node.node_id for node in run.node_runs] == ["trigger", "reminder"]
        assert actions.calls == [{
            "type": "send_chat_message",
            "config": template["graph"]["nodes"][1]["config"],
        }]
        assert skills.calls == []
