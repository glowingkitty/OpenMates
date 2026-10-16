"""Teams V1 billing and credit attribution tests.

Team credits are isolated from personal credits: owners/admins fund team accounts,
members can consume team credits, viewers cannot inspect or spend billing state,
and every deduction records the acting member for reporting.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError, hash_id
from backend.core.api.app.services.team_billing_service import TeamBillingService, TeamInsufficientCreditsError
from backend.core.api.app.services import team_billing_service
from backend.shared.python_utils.team_skill_billing import ensure_team_skill_credit_headroom
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload
from backend.tests.test_usage_entries import _llm_receipt, RoundTripEncryption


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,billing.purchase.provider-routing
async def test_team_bank_transfer_retries_invoice_without_granting_credits_twice(monkeypatch) -> None:
    from backend.tests.test_bank_transfer import _fake_confirmed_payment_service, _make_transaction_created_event
    from backend.core.api.app.routes import payments
    from backend.core.api.app.services.billing_profile_service import BillingProfileService

    team_id = "team-1"
    order_id = "bt_team_invoice_retry"
    reference = "OMT-team01-retry"
    event = _make_transaction_created_event(amount=100.0, reference=reference, transaction_id="txn-team-retry")
    order = {
        "id": "pending-row", "order_id": order_id, "reference": reference,
        "status": "pending", "amount_expected_cents": 10000,
        "user_id": "payer-1", "team_id": team_id, "credits_amount": 110000,
        "order_type": "team_credit_purchase",
    }

    class Cache:
        async def get_bank_transfer_by_reference(self, requested_reference):
            return order if requested_reference == reference else None

        async def update_bank_transfer_status(self, **kwargs):
            order.update({"status": kwargs["status"], **kwargs.get("extra_fields", {})})

        async def increment_stat(self, *_args):
            pass

        async def record_credit_purchase(self, *_args):
            pass

        async def update_liability(self, *_args):
            pass

        async def increment_json_stat(self, *_args):
            pass

    class Directus:
        async def get_items(self, collection, **_kwargs):
            assert collection == "pending_bank_transfers"
            return [order]

        async def update_item(self, collection, item_id, changes, **_kwargs):
            assert (collection, item_id) == ("pending_bank_transfers", order["id"])
            order.update(changes)
            return order

    credited = []
    dispatched = []

    async def add_credits(_service, **kwargs):
        credited.append(kwargs["event_id"])

    async def dispatch(**kwargs):
        dispatched.append(kwargs["order_id"])
        if len(dispatched) == 1:
            raise RuntimeError("invoice queue temporarily unavailable")

    async def begin_settlement(*_args, **_kwargs):
        return {"_created": True}

    async def no_op(*_args, **_kwargs):
        return None

    async def get_context(_service, requested_order_id):
        assert requested_order_id == order_id
        return {"owner_kind": "team", "owner_hash": hash_id(team_id)}

    monkeypatch.setattr(TeamBillingService, "add_credits", add_credits)
    monkeypatch.setattr(BillingProfileService, "get_order_context", get_context)
    monkeypatch.setattr(payments, "begin_purchase_settlement", begin_settlement)
    monkeypatch.setattr(payments, "complete_purchase_settlement", no_op)
    monkeypatch.setattr(payments, "_notify_admin_bank_transfer_processing_error", no_op)
    monkeypatch.setattr(payments, "_dispatch_purchase_invoice_from_context", dispatch)
    monkeypatch.setattr(payments.ComplianceService, "log_financial_transaction", lambda **_kwargs: None)

    kwargs = {
        "event_payload": event, "event_type": "TransactionCreated",
        "payment_service": _fake_confirmed_payment_service(event),
        "cache_service": Cache(), "directus_service": Directus(),
        "encryption_service": object(), "secrets_manager": object(), "tier_service": object(),
    }
    with pytest.raises(HTTPException) as failure:
        await payments._handle_revolut_business_webhook(**kwargs)
    assert failure.value.status_code == 503
    assert order["status"] == "completed"
    assert credited == [f"bank-transfer:{order_id}"]

    replay = await payments._handle_revolut_business_webhook(**kwargs)
    assert replay == {"status": "duplicate_transaction_ignored"}
    assert credited == [f"bank-transfer:{order_id}"]
    assert dispatched == [order_id, order_id]


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


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
@pytest.mark.anyio
async def test_team_creation_starts_with_zero_server_balance_and_encrypted_snapshot() -> None:
    directus, _methods, billing = await _seed_team()

    account = await billing.get_billing_summary("team-1", "alice")

    assert account["encrypted_balance"] == "cipher-zero-balance"
    assert account["balance_credits"] == 0
    assert directus.rows["team_credit_accounts"][0]["hashed_team_id"] == hash_id("team-1")


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
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


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
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


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary,teams.membership.role-gated
@pytest.mark.anyio
async def test_member_skill_headroom_uses_available_team_credits_without_billing_summary() -> None:
    directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-member", "role": "member", "created_at": 110})
    await _approve_invited_member(methods, "invite-member", "bob", "cipher-team-key-for-bob")
    await billing.add_credits(
        team_id="team-1", actor_user_id="alice", event_id="purchase-1", credits=100,
        encrypted_balance="cipher-balance-100",
    )
    directus.rows["billing_reservations"].append({
        "subject_kind": "team", "subject_hash": hash_id("team-1"),
        "state": "reserved", "quoted_credits": 60,
    })

    with pytest.raises(TeamPermissionError):
        await billing.get_billing_summary("team-1", "bob")
    await ensure_team_skill_credit_headroom(directus, "team-1", "bob", 40)
    with pytest.raises(ValueError, match="^INSUFFICIENT_TEAM_CREDITS$"):
        await ensure_team_skill_credit_headroom(directus, "team-1", "bob", 41)


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary,teams.membership.role-gated
@pytest.mark.anyio
async def test_viewer_and_outsider_cannot_check_skill_headroom() -> None:
    directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-viewer", "role": "viewer", "created_at": 110})
    await _approve_invited_member(methods, "invite-viewer", "viv", "cipher-team-key-for-viewer")
    await billing.add_credits(
        team_id="team-1", actor_user_id="alice", event_id="purchase-1", credits=100,
        encrypted_balance="cipher-balance-100",
    )

    for user_id in ("viv", "outsider"):
        with pytest.raises(TeamPermissionError):
            await ensure_team_skill_credit_headroom(directus, "team-1", user_id, 1)


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary,teams.membership.role-gated
@pytest.mark.anyio
async def test_member_cannot_fund_team_credits_directly() -> None:
    _directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-member", "role": "member", "created_at": 110})
    await _approve_invited_member(methods, "invite-member", "bob", "cipher-team-key-for-bob")

    with pytest.raises(TeamPermissionError):
        await billing.add_credits(
            team_id="team-1",
            actor_user_id="bob",
            event_id="purchase-1",
            credits=100,
            encrypted_balance="cipher-balance-100",
        )


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
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


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
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


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary,teams.membership.role-gated
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


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary,teams.membership.role-gated
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


# contract-test: direct surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.anyio
async def test_team_llm_receipt_uses_actor_key_and_existing_member_visibility() -> None:
    directus, methods, billing = await _seed_team()
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-member", "role": "member", "created_at": 110})
    await _approve_invited_member(methods, "invite-member", "bob", "cipher-team-key-for-bob")
    await billing.add_credits(team_id="team-1", actor_user_id="alice", event_id="fund", credits=100,
                              encrypted_balance="cipher-100", occurred_at=130)
    async def projected_actor_fields(user_id, fields, *, no_cache=False):
        assert user_id == "bob"
        assert no_cache is True
        actor = {"id": "bob", "vault_key_id": "bob-key"}
        return {field: actor[field] for field in fields}

    directus.get_user_fields_direct = AsyncMock(side_effect=projected_actor_fields)
    directus.usage = SimpleNamespace(encryption_service=RoundTripEncryption())
    receipt = _llm_receipt()
    receipt["settlement_state"] = "pending"
    receipt["credits_charged"] = 0

    charged = await billing.charge_team_credits(
        team_id="team-1", actor_user_id="bob", event_id="usage-bob", credits=1,
        workspace_type="chat", usage_details={"llm_usage_breakdown": receipt}, occurred_at=140,
    )
    assert charged["usage_event"]["encrypted_llm_usage_breakdown"].startswith("enc:bob-key:")
    directus.get_user_fields_direct.assert_awaited_once_with("bob", ["id", "vault_key_id"], no_cache=True)
    assert directus.rows["team_credit_accounts"][0]["balance_credits"] == 99
    member_rows = await billing.list_usage("team-1", "bob")
    admin_rows = await billing.list_usage("team-1", "alice", member_user_id="bob")
    assert member_rows[0]["llm_usage_breakdown"]["settlement_state"] == "settled"
    assert admin_rows[0]["llm_usage_breakdown"]["credits_charged"] == 1
    assert "llm_usage_vault_key_id" not in member_rows[0]
    assert "encrypted_llm_usage_breakdown" not in member_rows[0]
    assert receipt["settlement_state"] == "pending"
    with pytest.raises(TeamPermissionError):
        await billing.list_usage("team-1", "bob", member_user_id="alice")


# contract-test: direct surface=rest_api assertions=billing.access.authenticated-first-party,billing.credits.idempotent-charge
@pytest.mark.anyio
async def test_team_quote_reservation_requires_member_and_uses_team_wallet_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _directus, methods, billing = await _seed_team()
    operations = []

    async def execute(_self, operation, payload):
        operations.append((operation, payload))
        return {"state": "reserved", "quoted_credits": payload["quoted_credits"]}

    monkeypatch.setattr(team_billing_service.SubChatOrchestrationService, "execute", execute)
    with pytest.raises(TeamPermissionError):
        await billing.reserve_team_credits(
            team_id="team-1", actor_user_id="stranger", charge_id="ai-ask:one:main",
            quoted_credits=7, app_id="ai", skill_id="ask",
        )
    assert operations == []
    await methods.create_invite("team-1", "alice", {"invite_id": "reserve-member", "role": "member", "created_at": 110})
    await _approve_invited_member(methods, "reserve-member", "bob", "cipher-team-key-for-bob")
    result = await billing.reserve_team_credits(
        team_id="team-1", actor_user_id="bob", charge_id="ai-ask:one:main",
        quoted_credits=7, app_id="ai", skill_id="ask",
    )
    assert result["quoted_credits"] == 7
    assert operations == [("reserve_team_credits", {
        "protocol_version": 1, "charge_id": "ai-ask:one:main",
        "hashed_team_id": hash_id("team-1"), "actor_user_hash": hash_id("bob"),
        "app_id": "ai", "skill_id": "ask", "quoted_credits": 7,
    })]


# contract-test: direct surface=rest_api assertions=billing.access.authenticated-first-party,billing.credits.idempotent-charge
@pytest.mark.anyio
async def test_team_billing_summary_reports_only_authorized_aggregate_holds() -> None:
    directus, _methods, billing = await _seed_team()
    directus.rows["billing_reservations"] = [
        {"subject_kind": "team", "subject_hash": hash_id("team-1"), "state": "reserved",
         "quoted_credits": 7, "review_requested_at": None, "charge_id": "private-charge-1"},
        {"subject_kind": "team", "subject_hash": hash_id("team-1"), "state": "reserved",
         "quoted_credits": 3, "review_requested_at": "2026-10-07", "charge_id": "private-charge-2"},
        {"subject_kind": "personal", "subject_hash": hash_id("team-1"), "state": "reserved",
         "quoted_credits": 900, "review_requested_at": None},
    ]
    with pytest.raises(TeamPermissionError):
        await billing.get_billing_summary("team-1", "stranger")
    summary = await billing.get_billing_summary("team-1", "alice")
    assert summary["held_credits"] == 10
    assert summary["review_required_credits"] == 3
    assert "charge_id" not in summary
