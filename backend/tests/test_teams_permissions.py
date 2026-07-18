"""Teams V1 permission tests.

Server-side team authorization must be enforced independently of future CLI or UI
role checks. Viewers and members can read active team metadata through membership
but cannot mutate team state, membership, invites, or deletion state.
"""

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload


async def _seed_team_with_role(role: str) -> tuple[FakeDirectus, TeamMethods]:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": f"invite-{role}", "role": role, "created_at": 110})
    request = await methods.accept_invite(f"invite-{role}", "bob", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=125)
    return directus, methods


@pytest.mark.anyio
async def test_viewer_can_read_team_but_cannot_mutate_any_team_state() -> None:
    _directus, methods = await _seed_team_with_role("viewer")

    assert (await methods.get_team("team-1", "bob"))["role"] == "viewer"
    with pytest.raises(TeamPermissionError):
        await methods.update_team("team-1", "bob", {"encrypted_name": "cipher-updated", "updated_at": 130})
    with pytest.raises(TeamPermissionError):
        await methods.create_invite("team-1", "bob", {"invite_id": "invite-2", "role": "member", "created_at": 130})
    with pytest.raises(TeamPermissionError):
        await methods.set_member_role("team-1", "bob", "bob", "member", updated_at=130)
    with pytest.raises(TeamPermissionError):
        await methods.remove_member("team-1", "bob", "bob", removed_at=130)
    with pytest.raises(TeamPermissionError):
        await methods.delete_team("team-1", "bob", deleted_at=130)


@pytest.mark.anyio
async def test_member_can_read_but_cannot_manage_team_or_membership() -> None:
    _directus, methods = await _seed_team_with_role("member")

    assert (await methods.get_team("team-1", "bob"))["role"] == "member"
    with pytest.raises(TeamPermissionError):
        await methods.update_team("team-1", "bob", {"encrypted_name": "cipher-updated", "updated_at": 130})
    with pytest.raises(TeamPermissionError):
        await methods.create_invite("team-1", "bob", {"invite_id": "invite-2", "role": "viewer", "created_at": 130})
    with pytest.raises(TeamPermissionError):
        await methods.remove_member("team-1", "bob", "bob", removed_at=130)


@pytest.mark.anyio
async def test_admin_can_manage_members_but_cannot_delete_team() -> None:
    _directus, methods = await _seed_team_with_role("admin")

    invite = await methods.create_invite("team-1", "bob", {"invite_id": "invite-2", "role": "viewer", "created_at": 130})
    assert invite is not None

    with pytest.raises(TeamPermissionError):
        await methods.delete_team("team-1", "bob", deleted_at=140)


@pytest.mark.anyio
async def test_non_member_cannot_read_team_or_satisfy_any_role() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())

    assert await methods.get_team("team-1", "eve") is None
    with pytest.raises(TeamPermissionError):
        await methods.require_team_role("team-1", "eve", {"viewer", "member", "admin", "owner"})
