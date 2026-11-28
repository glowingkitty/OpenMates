"""Team chat creators retain the validated Team scope through their write boundary."""

from types import SimpleNamespace

import pytest

from backend.apps.projects.skills.create_skill import CreateSkill as ProjectCreateSkill
from backend.apps.workflows.skills.create_or_modify_skill import CreateOrModifySkill


class TeamRole:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    async def require_team_role(self, team_id, user_id, roles):
        self.calls.append((team_id, user_id, roles))
        if not self.allowed:
            raise PermissionError("Team write denied")


def skill(cls, app_id, skill_id):
    return cls(app=None, app_id=app_id, skill_id=skill_id,
               skill_name=skill_id, skill_description=skill_id)


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
async def test_project_creator_carries_team_into_pending_client_action_and_checks_role():
    creator = skill(ProjectCreateSkill, "projects", "create")
    role = TeamRole()
    response = await creator.execute(name="Team project", user_id="member", team_id="team-1",
                                    directus_service=SimpleNamespace(team=role))
    assert response.success
    assert response.pending_client_action["team_id"] == "team-1"
    assert role.calls == [("team-1", "member", {"owner", "admin", "member"})]

    denied = await creator.execute(name="Denied project", user_id="viewer", team_id="team-1",
                                   directus_service=SimpleNamespace(team=TeamRole(allowed=False)))
    assert not denied.success
    assert denied.pending_client_action is None


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local,workflows.access.boundaries
async def test_workflow_creator_passes_team_to_authoring_and_rejects_unsupported_paths():
    calls = []

    def start(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="queued", message="Pending")

    creator = skill(CreateOrModifySkill, "workflows", "create-or-modify")
    service = SimpleNamespace(start=start)
    response = await creator.execute(instruction="Create reminder", user_id="member", team_id="team-1",
                                     workflow_input_service=service)
    assert response.success
    assert calls[0]["team_id"] == "team-1"

    run = await creator.execute(instruction="Run reminder", execution_mode="run_once",
                                user_id="member", team_id="team-1", workflow_input_service=service)
    graph = await creator.execute(title="Graph", graph={"nodes": []}, user_id="member",
                                  team_id="team-1", workflow_input_service=service)
    assert not run.success and "Team workflow execution" in run.error
    assert not graph.success and "Team workflow graph proposals" in graph.error
    assert len(calls) == 1
