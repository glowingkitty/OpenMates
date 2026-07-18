"""Teams V1 membership contract tests.

These tests keep membership behavior focused outside the broader lifecycle test:
admin invites, invite acceptance, role changes, owner protection, and member
removal all use hashed identities and fail closed for unsupported transitions.
"""

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, hash_id
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload


@pytest.mark.anyio
async def test_admin_can_invite_member_and_change_role_without_owner_promotion() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "admin", "created_at": 110})
    ada_request = await methods.accept_invite("invite-1", "ada", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", ada_request["access_request_id"], "cipher-team-key-for-ada", approved_at=125)

    invite = await methods.create_invite("team-1", "ada", {"invite_id": "invite-2", "role": "member", "created_at": 130})
    bob_request = await methods.accept_invite("invite-2", "bob", accepted_at=140)
    accepted = await methods.approve_access_request("team-1", "ada", bob_request["access_request_id"], "cipher-team-key-for-bob", approved_at=145)
    updated = await methods.set_member_role("team-1", "ada", "bob", "viewer", updated_at=150)
    blocked_owner_promotion = await methods.set_member_role("team-1", "ada", "bob", "owner", updated_at=160)

    assert invite is not None
    assert accepted is not None
    assert updated is not None
    assert updated["role"] == "viewer"
    assert blocked_owner_promotion is None
    assert directus.rows["team_invites"][1]["created_by_hash"] == hash_id("ada")
    assert directus.rows["team_invites"][1]["hashed_team_id"] == hash_id("team-1")


@pytest.mark.anyio
async def test_remove_member_refuses_owner_and_revokes_non_owner_access() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "member", "created_at": 110})
    request = await methods.accept_invite("invite-1", "bob", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=125)

    owner_removed = await methods.remove_member("team-1", "alice", "alice", removed_at=130)
    bob_removed = await methods.remove_member("team-1", "alice", "bob", removed_at=140)

    assert owner_removed is False
    assert bob_removed is True
    alice_membership = [row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("alice")][0]
    bob_membership = [row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("bob")][0]
    bob_wrapper = [row for row in directus.rows["team_key_wrappers"] if row["hashed_user_id"] == hash_id("bob")][0]
    assert alice_membership["status"] == "active"
    assert bob_membership["status"] == "removed"
    assert bob_wrapper["status"] == "revoked"


@pytest.mark.anyio
async def test_accept_invite_returns_none_for_unknown_or_already_requested_invite() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "member", "created_at": 110})

    unknown = await methods.accept_invite("missing", "bob", accepted_at=120)
    first_accept = await methods.accept_invite("invite-1", "bob", accepted_at=130)
    second_accept = await methods.accept_invite("invite-1", "bob", accepted_at=140)

    assert unknown is None
    assert first_accept is not None
    assert second_accept is None


@pytest.mark.anyio
async def test_invalid_invite_or_role_update_role_is_rejected() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "member", "created_at": 110})
    request = await methods.accept_invite("invite-1", "bob", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=125)

    with pytest.raises(ValueError):
        await methods.create_invite("team-1", "alice", {"invite_id": "bad-invite", "role": "owner", "created_at": 130})

    with pytest.raises(ValueError):
        await methods.set_member_role("team-1", "alice", "bob", "superadmin", updated_at=140)
