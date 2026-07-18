"""Teams V1 workspace context and move authorization tests.

Moving personal records into a team is irreversible in V1 and must fail closed:
only the current personal owner may move a record, and only owner/admin/member
roles can write into a team workspace.
"""

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError, hash_id
from backend.core.api.app.services.team_workspace_service import (
    TeamWorkspaceMoveError,
    authorize_personal_to_team_move,
    move_workspace_record_to_team,
    workspace_context_filters,
)
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload


async def _seed_team_with_member(role: str) -> tuple[FakeDirectus, TeamMethods]:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    directus.team = methods
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": f"invite-{role}", "role": role, "created_at": 110})
    request = await methods.accept_invite(f"invite-{role}", "bob", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=125)
    return directus, methods


def test_workspace_context_filters_separate_personal_and_team_records() -> None:
    assert workspace_context_filters(user_id="alice") == {
        "filter[hashed_user_id][_eq]": hash_id("alice"),
        "filter[hashed_team_id][_null]": "true",
    }
    assert workspace_context_filters(user_id="alice", team_id="team-1") == {"filter[hashed_team_id][_eq]": hash_id("team-1")}


@pytest.mark.anyio
async def test_member_can_move_owned_personal_record_into_team() -> None:
    directus, _methods = await _seed_team_with_member("member")

    patch = await authorize_personal_to_team_move(
        directus_service=directus,
        actor_user_id="bob",
        team_id="team-1",
        record={"id": "record-1", "hashed_user_id": hash_id("bob"), "hashed_team_id": None},
        moved_at=200,
    )

    assert patch == {"hashed_team_id": hash_id("team-1"), "updated_at": 200}


@pytest.mark.anyio
async def test_viewer_cannot_move_personal_record_into_team() -> None:
    directus, _methods = await _seed_team_with_member("viewer")

    with pytest.raises(TeamPermissionError):
        await authorize_personal_to_team_move(
            directus_service=directus,
            actor_user_id="bob",
            team_id="team-1",
            record={"id": "record-1", "hashed_user_id": hash_id("bob"), "hashed_team_id": None},
            moved_at=200,
        )


@pytest.mark.anyio
async def test_non_owner_cannot_move_someone_else_personal_record() -> None:
    directus, _methods = await _seed_team_with_member("member")

    with pytest.raises(TeamWorkspaceMoveError):
        await authorize_personal_to_team_move(
            directus_service=directus,
            actor_user_id="bob",
            team_id="team-1",
            record={"id": "record-1", "hashed_user_id": hash_id("alice"), "hashed_team_id": None},
            moved_at=200,
        )


@pytest.mark.anyio
async def test_cannot_move_already_team_scoped_record_again() -> None:
    directus, _methods = await _seed_team_with_member("member")

    with pytest.raises(TeamWorkspaceMoveError):
        await authorize_personal_to_team_move(
            directus_service=directus,
            actor_user_id="bob",
            team_id="team-1",
            record={"id": "record-1", "hashed_user_id": hash_id("bob"), "hashed_team_id": hash_id("team-1")},
            moved_at=200,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("workspace_type", "collection", "id_field", "object_id"),
    [
        ("chat", "chats", "id", "chat-1"),
        ("project", "projects", "project_id", "project-1"),
        ("task", "user_tasks", "task_id", "task-1"),
        ("plan", "user_plans", "plan_id", "plan-1"),
        ("workflow", "workflows", "workflow_id", "workflow-1"),
    ],
)
async def test_move_workspace_record_updates_supported_collection(workspace_type: str, collection: str, id_field: str, object_id: str) -> None:
    directus, _methods = await _seed_team_with_member("member")
    directus.rows[collection].append({"id": "row-1", id_field: object_id, "hashed_user_id": hash_id("bob"), "hashed_team_id": None})

    updated = await move_workspace_record_to_team(
        directus_service=directus,
        actor_user_id="bob",
        team_id="team-1",
        workspace_type=workspace_type,
        object_id=object_id,
        confirmed=True,
        moved_at=210,
    )

    assert updated["hashed_team_id"] == hash_id("team-1")
    assert updated["updated_at"] == 210


@pytest.mark.anyio
async def test_move_workspace_record_requires_confirmation() -> None:
    directus, _methods = await _seed_team_with_member("member")

    with pytest.raises(TeamWorkspaceMoveError):
        await move_workspace_record_to_team(
            directus_service=directus,
            actor_user_id="bob",
            team_id="team-1",
            workspace_type="project",
            object_id="project-1",
            confirmed=False,
        )
