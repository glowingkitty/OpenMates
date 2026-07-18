"""Teams V1 invite email and access approval tests.

Email invites must be simple for users but strict about privacy: invite creation
does not reveal whether an email has an account, email content never carries team
secrets, and accepting an invite waits for owner/admin access approval before
membership or team sync can become active.
"""

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, hash_id
from backend.core.api.app.services.team_invite_email_service import TeamInviteEmailService, hash_invite_email
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload


class FakeInviteEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_team_invite_email(self, *, to_email: str, accept_url: str, role: str, domain: str) -> bool:
        self.sent.append({"to_email": to_email, "accept_url": accept_url, "role": role, "domain": domain})
        return True


@pytest.mark.anyio
async def test_email_invite_stores_hashes_sends_safe_link_and_does_not_disclose_account_existence() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    sender = FakeInviteEmailSender()
    await methods.create_team("alice", team_payload())

    result = await TeamInviteEmailService(methods, sender).create_email_invite(
        team_id="team-1",
        inviter_user_id="alice",
        recipient_email="Bob@Example.COM",
        invite_id="invite-1",
        role="member",
        domain="https://app.selfhost.example",
        encrypted_recipient_hint="cipher-recipient-hint",
        created_at=110,
    )

    assert result == {
        "invite_id": "invite-1",
        "role": "member",
        "status": "pending",
        "delivery_status": "sent",
        "domain": "https://app.selfhost.example",
        "domain_reminder": "Recipient must accept with an OpenMates account on https://app.selfhost.example.",
    }
    invite = directus.rows["team_invites"][0]
    assert invite["hashed_recipient_email"] == hash_invite_email("bob@example.com")
    assert invite["one_time_token_hash"]
    assert "Bob@Example.COM" not in repr(invite)
    assert sender.sent[0]["to_email"] == "Bob@Example.COM"
    assert "invite_token=" in sender.sent[0]["accept_url"]
    assert "cipher-team-key" not in repr(sender.sent[0])


@pytest.mark.anyio
async def test_accept_invite_waits_for_team_access_approval_before_membership_wrapper() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "viewer", "created_at": 110})

    request = await methods.accept_invite("invite-1", "bob", accepted_at=120)

    assert request is not None
    assert request["status"] == "pending_access_approval"
    assert request["hashed_user_id"] == hash_id("bob")
    assert [row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("bob")] == []
    assert [row for row in directus.rows["team_key_wrappers"] if row["hashed_user_id"] == hash_id("bob")] == []

    approved = await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=130)

    assert approved is not None
    membership = [row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("bob")][0]
    wrapper = [row for row in directus.rows["team_key_wrappers"] if row["hashed_user_id"] == hash_id("bob")][0]
    assert membership["role"] == "viewer"
    assert wrapper["encrypted_team_key"] == "cipher-team-key-for-bob"
    assert directus.rows["team_access_requests"][0]["status"] == "approved"
    assert directus.rows["team_invites"][0]["status"] == "accepted"


@pytest.mark.anyio
async def test_accept_invite_stores_recipient_wrapper_for_owner_approval() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite(
        "team-1",
        "alice",
        {
            "invite_id": "invite-1",
            "role": "member",
            "hashed_recipient_email": hash_invite_email("bob@example.com"),
            "encrypted_invite_team_key": "cipher-invite-team-key",
            "invite_key_kdf_context": {"v": 1},
            "created_at": 110,
        },
    )

    request = await methods.accept_invite(
        "invite-1",
        "bob",
        accepted_at=120,
        encrypted_team_key="cipher-team-key-for-bob",
        recipient_email_hash=hash_invite_email("bob@example.com"),
    )

    assert request is not None
    assert request["status"] == "pending_access_approval"
    assert request["encrypted_team_key"] == "cipher-team-key-for-bob"
    assert [row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("bob")] == []

    approved = await methods.approve_access_request("team-1", "alice", request["access_request_id"], approved_at=130)

    assert approved is not None
    wrapper = [row for row in directus.rows["team_key_wrappers"] if row["hashed_user_id"] == hash_id("bob")][0]
    assert wrapper["encrypted_team_key"] == "cipher-team-key-for-bob"
