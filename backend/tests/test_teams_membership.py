"""Teams V1 membership contract tests.

These tests keep membership behavior focused outside the broader lifecycle test:
admin invites, invite acceptance, role changes, owner protection, and member
removal all use hashed identities and fail closed for unsupported transitions.
"""

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError, hash_id
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
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


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
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


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
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


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
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


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
@pytest.mark.anyio
async def test_security_policy_restricts_join_and_lists_only_safe_management_fields() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    policy = await methods.update_security_policy("team-1", "alice", {
        "restrict_email_domains": True, "allowed_email_domains": [" Example.COM "],
        "require_strong_auth": True,
    })
    assert policy["allowed_email_domains"] == ["example.com"]
    assert policy["require_invite_link_approval"] is True
    assert (await methods.get_security_policy_by_hash(hash_id("team-1")))["restrict_email_domains"] is True
    invite = await methods.create_invite("team-1", "alice", {"invite_id": "link-1", "role": "member", "created_at": 110})
    assert invite["kind"] == "share_link"
    assert invite["expires_at"] > 110 + 86400
    assert (await methods.list_invites("team-1", "alice"))[0]["invite_id"] == "link-1"
    assert (await methods.list_members("team-1", "alice"))[0]["user_id"] == "alice"
    assert await methods.revoke_invite("team-1", "alice", "link-1")
    assert await methods.accept_invite("link-1", "bob", accepted_at=120) is None


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
@pytest.mark.anyio
async def test_direct_invite_never_accepts_a_different_email_hash() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {
        "invite_id": "email-1", "hashed_recipient_email": "intended-hash", "created_at": 110,
    })
    assert await methods.accept_invite("email-1", "bob", accepted_at=120, encrypted_team_key="cipher", recipient_email_hash="different-hash") is None
    assert directus.rows["team_memberships"][-1]["user_id"] == "alice"


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
@pytest.mark.anyio
async def test_share_link_accepts_verified_recipient_hash_without_target_email() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "link-1", "created_at": 110})

    request = await methods.accept_invite(
        "link-1", "bob", accepted_at=120, encrypted_team_key="cipher-key",
        recipient_email_hash="bob-verified-email-hash",
    )

    assert request is not None
    assert request["status"] == "pending_access_approval"


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
@pytest.mark.anyio
async def test_pending_link_join_rechecks_current_domain_policy_before_activation() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "link-1", "created_at": 110})
    request = await methods.accept_invite("link-1", "bob", accepted_at=120,
                                          encrypted_team_key="cipher", verified_email_domain="other.example")
    await methods.update_security_policy("team-1", "alice", {
        "restrict_email_domains": True, "allowed_email_domains": ["example.com"],
    })
    with pytest.raises(TeamPermissionError):
        await methods.approve_access_request("team-1", "alice", request["access_request_id"], approved_at=130)
    assert [row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("bob")] == []


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
@pytest.mark.anyio
async def test_member_profile_remains_client_encrypted_through_create_accept_and_update() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload(encrypted_member_profile="cipher-owner-profile"))
    assert (await methods.list_members("team-1", "alice"))[0]["encrypted_member_profile"] == "cipher-owner-profile"
    await methods.create_invite("team-1", "alice", {"invite_id": "link-1", "created_at": 110})
    request = await methods.accept_invite("link-1", "bob", accepted_at=120,
                                          encrypted_team_key="cipher-key", encrypted_member_profile="cipher-bob-profile")
    assert request["encrypted_member_profile"] == "cipher-bob-profile"
    approved = await methods.approve_access_request("team-1", "alice", request["access_request_id"], approved_at=130)
    assert approved["encrypted_member_profile"] == "cipher-bob-profile"
    updated = await methods.update_own_member_profile("team-1", "bob", "cipher-bob-updated")
    assert updated["encrypted_member_profile"] == "cipher-bob-updated"
    assert (await methods.list_members("team-1", "alice"))[1]["encrypted_member_profile"] == "cipher-bob-updated"


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.security.join-policy
@pytest.mark.anyio
async def test_active_viewer_can_read_team_member_profiles() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload(encrypted_member_profile="cipher-owner-profile"))
    await methods.create_invite("team-1", "alice", {"invite_id": "link-1", "role": "viewer", "created_at": 110})
    request = await methods.accept_invite("link-1", "bob", accepted_at=120,
                                          encrypted_team_key="cipher-key", encrypted_member_profile="cipher-viewer-profile")
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], approved_at=130)

    members = await methods.list_members("team-1", "bob")
    assert {member["encrypted_member_profile"] for member in members} == {
        "cipher-owner-profile", "cipher-viewer-profile",
    }
