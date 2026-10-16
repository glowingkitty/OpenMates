"""Authenticated Team context must stay separate from Personal app-skill reads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.tasks.skills.search_skill import SearchSkill as TaskSearchSkill
from backend.apps.workflows.skills.run_skill import RunSkill
from backend.apps.workflows.skills.search_skill import SearchSkill as WorkflowSearchSkill
from backend.core.api.app.services.workflow_assistant_service import WorkflowAssistantService
from backend.core.api.app.services.workflow_models import WorkflowLifecycle


def _skill(skill_class, app_id: str, skill_id: str = "search"):
    return skill_class(
        app=None, app_id=app_id, skill_id=skill_id,
        skill_name="Test", skill_description="Test",
    )


def _directus(*, allowed: bool = True):
    async def require_role(team_id, user_id, roles):
        if not allowed:
            raise PermissionError("Team membership required")
        assert (team_id, user_id) == ("team-1", "alice")
        assert roles == {"owner", "admin", "member", "viewer"}

    return SimpleNamespace(team=SimpleNamespace(require_team_role=AsyncMock(side_effect=require_role)))


class ScopedWorkflows:
    def __init__(self):
        self.calls = []

    def list_workflows(self, user_id, vault_key_id=None, *, team_id=None):
        self.calls.append(("list", team_id))
        assert team_id == "team-1"
        return [SimpleNamespace(id="team-workflow", title="Team report")]

    def list_temporary_workflows(self, *args, **kwargs):
        raise AssertionError("Team search must not read Personal temporary workflows")

    def get_workflow(self, workflow_id, user_id, vault_key_id=None, *, team_id=None):
        self.calls.append(("get", team_id))
        assert team_id == "team-1"
        return SimpleNamespace(
            id=workflow_id, title="Team report", description="", status=SimpleNamespace(value="draft"),
            enabled=False, lifecycle=WorkflowLifecycle.PERSISTED,
            graph=SimpleNamespace(model_dump=lambda **kwargs: {"nodes": []}),
        )


# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
@pytest.mark.anyio
async def test_team_workflow_search_scopes_list_and_selected_detail_without_personal_temporary_read():
    service = ScopedWorkflows()
    assistant = WorkflowAssistantService(service)
    directus = _directus()
    skill = _skill(WorkflowSearchSkill, "workflows")

    listed = await skill.execute(
        query="Team", include_temporary=True, user_id="alice", team_id="team-1",
        workflow_assistant_service=assistant, directus_service=directus,
    )
    selected = await skill.execute(
        query="", workflow_id="team-workflow", user_id="alice", team_id="team-1",
        workflow_assistant_service=assistant, directus_service=directus,
    )

    assert listed.success and [item["workflow_id"] for item in listed.workflows] == ["team-workflow"]
    assert selected.success and selected.workflows[0]["workflow_id"] == "team-workflow"
    assert service.calls == [("list", "team-1"), ("get", "team-1"), ("get", "team-1")]
    assert directus.team.require_team_role.await_count == 2


# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
@pytest.mark.anyio
async def test_team_workflow_run_fails_before_personal_lookup_or_stage():
    workflow_service = SimpleNamespace(get_workflow=Mock())
    assistant = SimpleNamespace(workflow_service=workflow_service, create_pending_run=Mock())
    result = await _skill(RunSkill, "workflows", "run").execute(
        workflow_id="personal-workflow", user_id="alice", team_id="team-1",
        workflow_assistant_service=assistant,
    )
    assert not result.success
    assert result.error == "Team workflow execution is not supported"
    workflow_service.get_workflow.assert_not_called()
    assistant.create_pending_run.assert_not_called()


# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
@pytest.mark.anyio
async def test_team_task_search_verifies_membership_and_carries_context():
    directus = _directus()
    task = await _skill(TaskSearchSkill, "tasks").execute(
        query="Roadmap", user_id="alice", team_id="team-1", directus_service=directus,
    )
    assert task.success and task.pending_client_search["team_id"] == "team-1"
    assert directus.team.require_team_role.await_count == 1


# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
@pytest.mark.anyio
async def test_team_task_search_injects_context_into_client_request_and_results():
    class ClientSearch:
        async def search_or_request(self, **kwargs):
            assert kwargs["team_id"] == "team-1"
            return {"status": "finished", "results": [{"task_id": "task-1", "title": "Team task"}]}

    response = await _skill(TaskSearchSkill, "tasks").execute(
        query="Team", user_id="alice", team_id="team-1",
        task_search_service=ClientSearch(), directus_service=_directus(),
    )
    assert response.success and response.results[0]["team_id"] == "team-1"


# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
@pytest.mark.anyio
async def test_denied_team_membership_returns_no_pending_search_or_workflow_read():
    denied = _directus(allowed=False)
    workflows = ScopedWorkflows()
    assistant = WorkflowAssistantService(workflows)
    calls = [
        _skill(TaskSearchSkill, "tasks").execute(query="x", user_id="alice", team_id="team-1", directus_service=denied),
        _skill(WorkflowSearchSkill, "workflows").execute(
            query="x", user_id="alice", team_id="team-1", directus_service=denied,
            workflow_assistant_service=assistant,
        ),
    ]
    for call in calls:
        result = await call
        assert not result.success
        assert getattr(result, "pending_client_search", None) is None
    assert workflows.calls == []


# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
@pytest.mark.anyio
@pytest.mark.parametrize("skill_name, arguments, method_name", [
    ("schedule-once", {"title": "Once", "graph": {"nodes": []}}, "schedule_once"),
    ("schedule-recurring", {"title": "Recurring", "graph": {"nodes": []}}, "schedule_recurring"),
    ("cancel-pending", {"pending_id": "personal-pending"}, "cancel_pending"),
    ("keep-temporary", {"workflow_id": "personal-workflow"}, "keep_temporary"),
])
async def test_legacy_workflow_utilities_reject_team_before_personal_service_calls(skill_name, arguments, method_name):
    from backend.apps.workflows.skills.cancel_pending_skill import CancelPendingSkill
    from backend.apps.workflows.skills.keep_temporary_skill import KeepTemporarySkill
    from backend.apps.workflows.skills.schedule_once_skill import ScheduleOnceSkill
    from backend.apps.workflows.skills.schedule_recurring_skill import ScheduleRecurringSkill

    classes = {
        "schedule-once": ScheduleOnceSkill,
        "schedule-recurring": ScheduleRecurringSkill,
        "cancel-pending": CancelPendingSkill,
        "keep-temporary": KeepTemporarySkill,
    }
    assistant = SimpleNamespace(**{method_name: Mock()})
    result = await _skill(classes[skill_name], "workflows", skill_name).execute(
        **arguments, user_id="alice", team_id="team-1", workflow_assistant_service=assistant,
    )

    assert not result.success
    assert result.error and "Team chats" in result.error
    getattr(assistant, method_name).assert_not_called()
