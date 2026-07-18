"""Teams V1 billing and credit attribution tests.

Team credits are isolated from personal credits: owners/admins fund team accounts,
members can consume team credits, viewers cannot inspect or spend billing state,
and every deduction records the acting member for reporting.
"""

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError, hash_id
from backend.core.api.app.services.team_billing_service import TeamBillingService, TeamInsufficientCreditsError
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload


async def _seed_team() -> tuple[FakeDirectus, TeamMethods, TeamBillingService]:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    directus.team = methods
    billing = TeamBillingService(directus)
    await methods.create_team("alice", team_payload())
    return directus, methods, billing


async def _approve_invited_member(methods: TeamMethods, invite_id: str, user_id: str, encrypted_team_key: str) -> None:
    request = await methods.accept_invite(invite_id, user_id, accepted_at=120)
    assert request is not None
    approved = await methods.approve_access_request("team-1", "alice", request["access_request_id"], encrypted_team_key, approved_at=125)
    assert approved is not None


@pytest.mark.anyio
async def test_team_creation_starts_with_zero_server_balance_and_encrypted_snapshot() -> None:
    directus, _methods, billing = await _seed_team()

    account = await billing.get_billing_summary("team-1", "alice")

    assert account["encrypted_balance"] == "cipher-zero-balance"
    assert account["balance_credits"] == 0
    assert directus.rows["team_credit_accounts"][0]["hashed_team_id"] == hash_id("team-1")


@pytest.mark.anyio
async def test_owner_can_add_team_credits_without_touching_personal_credit_rows() -> None:
    directus, _methods, billing = await _seed_team()

    result = await billing.add_credits(
        team_id="team-1",
        actor_user_id="alice",
        event_id="purchase-1",
        credits=500,
        encrypted_balance="cipher-balance-500",
        event_type="purchase",
        encrypted_metadata="cipher-payment-metadata",
        occurred_at=130,
    )

    assert result["account"]["balance_credits"] == 500
    assert result["account"]["encrypted_balance"] == "cipher-balance-500"
    assert result["credit_event"]["amount"] == 500
    assert result["credit_event"]["event_type"] == "purchase"
    assert result["credit_event"]["actor_user_hash"] == hash_id("alice")
    assert "users" not in directus.rows


@pytest.mark.anyio
async def test_member_charge_deducts_team_balance_and_records_usage_attribution() -> None:
    directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-member", "role": "member", "created_at": 110})
    await _approve_invited_member(methods, "invite-member", "bob", "cipher-team-key-for-bob")
    await billing.add_credits(
        team_id="team-1",
        actor_user_id="alice",
        event_id="transfer-1",
        credits=200,
        encrypted_balance="cipher-balance-200",
        event_type="personal_transfer_in",
        occurred_at=130,
    )

    result = await billing.charge_team_credits(
        team_id="team-1",
        actor_user_id="bob",
        event_id="usage-1",
        credits=30,
        encrypted_balance="cipher-balance-170",
        workspace_type="chat",
        object_id_hash="hash-chat-1",
        occurred_at=140,
    )

    assert result["account"]["balance_credits"] == 170
    assert result["credit_event"]["amount"] == -30
    assert result["credit_event"]["event_type"] == "deduction"
    assert result["usage_event"]["actor_user_hash"] == hash_id("bob")
    assert result["usage_event"]["credit_amount"] == 30
    assert directus.rows["team_credit_accounts"][0]["balance_credits"] == 170


@pytest.mark.anyio
async def test_internal_team_charge_can_preserve_existing_encrypted_balance_snapshot() -> None:
    directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-member", "role": "member", "created_at": 110})
    await _approve_invited_member(methods, "invite-member", "bob", "cipher-team-key-for-bob")
    await billing.add_credits(
        team_id="team-1",
        actor_user_id="alice",
        event_id="purchase-1",
        credits=100,
        encrypted_balance="cipher-balance-100",
        occurred_at=130,
    )

    result = await billing.charge_team_credits(
        team_id="team-1",
        actor_user_id="bob",
        event_id="usage-1",
        credits=20,
        workspace_type="chat",
        occurred_at=140,
    )

    assert result["account"]["balance_credits"] == 80
    assert result["account"]["encrypted_balance"] == "cipher-balance-100"


@pytest.mark.anyio
async def test_insufficient_team_balance_rejects_charge_without_usage_event() -> None:
    directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-member", "role": "member", "created_at": 110})
    await _approve_invited_member(methods, "invite-member", "bob", "cipher-team-key-for-bob")

    with pytest.raises(TeamInsufficientCreditsError):
        await billing.charge_team_credits(
            team_id="team-1",
            actor_user_id="bob",
            event_id="usage-1",
            credits=1,
            encrypted_balance="cipher-balance-negative",
            workspace_type="chat",
            occurred_at=130,
        )

    assert directus.rows["team_usage_events"] == []
    assert directus.rows["team_credit_accounts"][0]["balance_credits"] == 0


@pytest.mark.anyio
async def test_viewer_cannot_view_or_use_team_billing() -> None:
    _directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-viewer", "role": "viewer", "created_at": 110})
    await _approve_invited_member(methods, "invite-viewer", "viv", "cipher-team-key-for-viewer")

    with pytest.raises(TeamPermissionError):
        await billing.get_billing_summary("team-1", "viv")
    with pytest.raises(TeamPermissionError):
        await billing.add_credits(
            team_id="team-1",
            actor_user_id="viv",
            event_id="purchase-1",
            credits=100,
            encrypted_balance="cipher-balance-100",
        )
    with pytest.raises(TeamPermissionError):
        await billing.charge_team_credits(
            team_id="team-1",
            actor_user_id="viv",
            event_id="usage-1",
            credits=1,
            encrypted_balance="cipher-balance-minus-1",
            workspace_type="chat",
        )


@pytest.mark.anyio
async def test_member_usage_report_is_self_scoped_owner_can_filter_any_member() -> None:
    _directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-member", "role": "member", "created_at": 110})
    await _approve_invited_member(methods, "invite-member", "bob", "cipher-team-key-for-bob")
    await billing.add_credits(
        team_id="team-1",
        actor_user_id="alice",
        event_id="purchase-1",
        credits=100,
        encrypted_balance="cipher-balance-100",
        occurred_at=130,
    )
    await billing.charge_team_credits(
        team_id="team-1",
        actor_user_id="bob",
        event_id="usage-bob",
        credits=10,
        encrypted_balance="cipher-balance-90",
        workspace_type="chat",
        occurred_at=140,
    )
    await billing.charge_team_credits(
        team_id="team-1",
        actor_user_id="alice",
        event_id="usage-alice",
        credits=5,
        encrypted_balance="cipher-balance-85",
        workspace_type="chat",
        occurred_at=150,
    )

    bob_usage = await billing.list_usage("team-1", "bob")
    owner_filtered_usage = await billing.list_usage("team-1", "alice", member_user_id="bob")

    assert [event["event_id"] for event in bob_usage] == ["usage-bob"]
    assert [event["event_id"] for event in owner_filtered_usage] == ["usage-bob"]
    with pytest.raises(TeamPermissionError):
        await billing.list_usage("team-1", "bob", member_user_id="alice")
