"""The weekly invoice settles exactly, while payment failures alone advance warnings."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.api.app.tasks import storage_billing_tasks as tasks


# contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote
def test_sunday_utc_period_and_integer_charge_boundaries():
    assert tasks._period_start_at(datetime(2026, 10, 4, 3, tzinfo=timezone.utc)) == 1791082800
    assert tasks._period_start_at(datetime(2026, 10, 4, 2, 59, tzinfo=timezone.utc)) == 1790478000
    assert tasks._compute_billable_credits(tasks.FREE_BYTES) == 0
    assert tasks._compute_billable_credits(tasks.FREE_BYTES + 1) == 3
    assert tasks._compute_billable_credits(2 * tasks.FREE_BYTES + 1) == 6


class FakeOrchestration:
    def __init__(self, periods):
        self.periods = list(periods)
        self.calls = []
        self.warning_due = False

    async def execute(self, operation, data):
        self.calls.append((operation, data))
        if operation == "freeze_storage_period":
            return {"period": data, "idempotent": False}
        if operation == "list_storage_debt":
            return {"periods": list(self.periods), "has_more": False}
        if operation == "mark_storage_period_paid":
            assert data["period_id"] == self.periods[0]["id"]
            self.periods.pop(0)
            return {"state": "paid", "all_debt_settled": not self.periods}
        if operation == "claim_storage_warning":
            return {"due": self.warning_due, "episode_id": "33333333-3333-4333-8333-333333333333"}
        if operation == "freeze_storage_warning_units":
            return {"frozen": True, "held": False}
        if operation == "inspect_storage_expiry":
            return {"due": self.warning_due, "episode_id": "33333333-3333-4333-8333-333333333333"}
        raise AssertionError(operation)


def period(name, due):
    return {
        "id": name, "charge_id": f"storage:owner:{name}",
        "measured_bytes": tasks.FREE_BYTES + 1,
        "period_start_at": 1000, "credits_due": due,
    }


def quote(total_bytes=0):
    return SimpleNamespace(
        total_bytes=total_bytes, complete=True,
        policy_version="storage-v2", source_version="directus-v1",
        categories={"legacy_upload_bytes": total_bytes},
    )


def empty_legacy_ledger():
    return SimpleNamespace(get_items=AsyncMock(return_value=[]))


def legacy_directus(*, identities=(), outbox=(), error=None):
    async def get_items(collection, *, params, **options):
        assert options == {"admin_required": True, "no_cache": True, "raise_on_error": True}
        assert params["limit"] == 2
        if error:
            raise error
        return list(identities if collection == "billing_charge_identities" else outbox)
    return SimpleNamespace(get_items=AsyncMock(side_effect=get_items))


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", [
    ("identity", {"state": "committed", "committed_at": "2026-10-04T03:01:00Z"}),
    ("outbox", {"state": "pending", "created_at": "2026-10-04T03:01:00Z"}),
    ("outbox", {"state": "mystery", "created_at": "2026-10-04T03:01:00Z"}),
])
# contract-test: supporting surface=rest_api assertions=billing.storage.legacy-cutover-safe
async def test_legacy_attempt_ignores_initial_period_without_paid_claim_or_debt(evidence):
    start = tasks._period_start_at(datetime(2026, 10, 4, 3, tzinfo=timezone.utc))
    owner = "22222222-2222-4222-8222-222222222222"
    owner_hash = tasks.hashlib.sha256(owner.encode()).hexdigest()
    row = {"charge_id": f"storage:{owner_hash}:{start // 604800}", **evidence[1]}
    directus = legacy_directus(**{"identities" if evidence[0] == "identity" else "outbox": [row]})
    orchestration = FakeOrchestration([])
    billing = SimpleNamespace(charge_user_credits=AsyncMock())
    for _ in range(2):  # A retry in the same Sunday window remains ignored.
        outcome = await tasks._settle_owner(
            owner, quote(tasks.FREE_BYTES + 1), period_start_at=start,
            directus=directus, billing=billing, orchestration=orchestration,
            encryption=None, email_service=None, cache=None,
        )
        assert outcome["legacy_period_ignored"] == 1
        assert outcome["billed"] == outcome["credits"] == outcome["insufficient"] == 0
    assert orchestration.calls == []
    billing.charge_user_credits.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.legacy-cutover-safe
async def test_legacy_ledger_outage_fails_closed_without_freezing_invoice():
    orchestration = FakeOrchestration([])
    billing = SimpleNamespace(charge_user_credits=AsyncMock())
    outcome = await tasks._settle_owner(
        "22222222-2222-4222-8222-222222222222", quote(tasks.FREE_BYTES + 1),
        period_start_at=tasks._period_start_at(datetime(2026, 10, 4, 3, tzinfo=timezone.utc)),
        directus=legacy_directus(error=RuntimeError("ledger unavailable")),
        billing=billing, orchestration=orchestration,
        encryption=None, email_service=None, cache=None,
    )
    assert outcome["operational_error"] == 1
    assert outcome["legacy_period_ignored"] == 0
    assert orchestration.calls == []
    billing.charge_user_credits.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.legacy-cutover-safe
async def test_legacy_lookup_covers_thursday_rollover_and_releases_prior_period():
    start = tasks._period_start_at(datetime(2026, 10, 4, 3, tzinfo=timezone.utc))
    owner_hash = tasks.hashlib.sha256(b"owner").hexdigest()
    later_week_key = f"storage:{owner_hash}:{(start + 604799) // 604800}"
    assert later_week_key != f"storage:{owner_hash}:{start // 604800}"
    row = {"charge_id": later_week_key, "state": "committed",
           "committed_at": "2026-10-08T00:01:00Z"}
    directus = legacy_directus(identities=[row])
    assert await tasks._legacy_charge_in_period(directus, owner_hash, start)
    assert not await tasks._legacy_charge_in_period(directus, owner_hash, start + 604800)
    first_query = directus.get_items.await_args_list[0].kwargs["params"]
    assert later_week_key in first_query["filter"]["charge_id"]["_in"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.legacy-cutover-safe,billing.storage.weekly-quote
async def test_no_legacy_attempt_allows_sunday_invoice():
    start = tasks._period_start_at(datetime(2026, 10, 4, 3, tzinfo=timezone.utc))
    owner = "22222222-2222-4222-8222-222222222222"
    orchestration = FakeOrchestration([])
    result = await tasks._settle_owner(
        owner, quote(tasks.FREE_BYTES + 1), period_start_at=start,
        directus=empty_legacy_ledger(),
        billing=SimpleNamespace(charge_user_credits=AsyncMock()),
        orchestration=orchestration, encryption=None, email_service=None, cache=None,
    )
    assert result["legacy_period_ignored"] == 0
    assert orchestration.calls[0][0] == "freeze_storage_period"
    assert orchestration.calls[0][1]["charge_id"].endswith(f":{start}")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement,billing.storage.weekly-quote
async def test_oldest_invoice_settles_before_newer_week_and_full_amount_only():
    orchestration = FakeOrchestration([period("old", 3), period("new", 6)])
    billing = SimpleNamespace(charge_user_credits=AsyncMock(side_effect=[
        {"state": "committed", "charged_credits": 3},
        {"state": "committed", "charged_credits": 6},
    ]))
    outcome = await tasks._settle_owner(
        "22222222-2222-4222-8222-222222222222", quote(), period_start_at=2000,
        directus=empty_legacy_ledger(), billing=billing, orchestration=orchestration,
        encryption=None, email_service=None, cache=None,
    )
    assert outcome["billed"] == 2
    assert outcome["credits"] == 9
    assert [call.kwargs["idempotency_key"] for call in billing.charge_user_credits.await_args_list] == [
        period("old", 3)["charge_id"], period("new", 6)["charge_id"],
    ]
    assert all(call.kwargs["require_full_charge"] for call in billing.charge_user_credits.await_args_list)
    assert not orchestration.periods


@pytest.mark.asyncio
@pytest.mark.parametrize("charge_result", [
    {"state": "retry_scheduled", "charged_credits": 3},
    {"state": "committed", "charged_credits": 2},
])
# contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement,billing.storage.four-warning-expiry
async def test_pending_or_partial_charge_cannot_mark_invoice_paid_or_warn(charge_result):
    orchestration = FakeOrchestration([period("old", 3)])
    billing = SimpleNamespace(charge_user_credits=AsyncMock(return_value=charge_result))
    outcome = await tasks._settle_owner(
        "22222222-2222-4222-8222-222222222222", quote(), period_start_at=2000,
        directus=empty_legacy_ledger(), billing=billing, orchestration=orchestration,
        encryption=None, email_service=None, cache=None,
    )
    assert outcome["operational_error"] == 1
    assert [name for name, _ in orchestration.calls] == ["list_storage_debt"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement,billing.storage.four-warning-expiry
async def test_credit_shortage_warns_but_operational_error_does_not(monkeypatch):
    delivery = AsyncMock(return_value=True)
    monkeypatch.setattr(tasks, "_deliver_warning", delivery)
    orchestration = FakeOrchestration([period("old", 3)])
    orchestration.warning_due = True
    billing = SimpleNamespace(charge_user_credits=AsyncMock(
        side_effect=HTTPException(status_code=402, detail="Insufficient credits")
    ))
    outcome = await tasks._settle_owner(
        "22222222-2222-4222-8222-222222222222", quote(), period_start_at=2000,
        directus=empty_legacy_ledger(), billing=billing, orchestration=orchestration,
        encryption=None, email_service=None, cache=None,
    )
    assert outcome["insufficient"] == 1
    assert outcome["warnings_delivered"] == 1
    assert outcome["expiry_due"] == 1
    delivery.assert_awaited_once()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement
async def test_full_charge_refuses_floor_crossing_without_partial_ledger(monkeypatch):
    from backend.core.api.app.services.billing_service import BillingService
    from backend.core.api.app.utils import server_mode

    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
    cache = SimpleNamespace(
        get_user_by_id=AsyncMock(return_value={"id": "u", "vault_key_id": "v"}),
        get_billing_projection=AsyncMock(return_value={
            "user": {"id": "u", "vault_key_id": "v"},
            "vault_key_id": "v", "encrypted_balance": "sealed",
            "credits": -499,
        }),
    )
    directus = SimpleNamespace(usage=SimpleNamespace(create_usage_entry=AsyncMock()))
    billing = BillingService(cache, directus, SimpleNamespace())
    with pytest.raises(HTTPException) as error:
        await billing.charge_user_credits(
            user_id="u", credits_to_deduct=3, user_id_hash="h",
            app_id="system", skill_id="storage", idempotency_key="storage:h:week",
            require_full_charge=True, _settlement_locked=True,
        )
    assert error.value.status_code == 402
    directus.usage.create_usage_entry.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [1, 2, 3, 4])
# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry,billing.storage.disclosures
async def test_new_storage_warning_uses_real_web_settings_routes(monkeypatch, stage):
    monkeypatch.setenv("WEBAPP_URL", "https://app.example.invalid/")
    sender = AsyncMock(return_value=(False, "failed"))
    monkeypatch.setattr(tasks, "send_email_once", sender)

    async def get_items(collection, **_kwargs):
        if collection == "email_deliveries":
            return []
        assert collection == "directus_users"
        return [{"encrypted_email_address": "sealed", "vault_key_id": "key", "language": "en"}]

    result = await tasks._deliver_warning(
        "22222222-2222-4222-8222-222222222222",
        {"warning_stage": stage, "episode_id": "33333333-3333-4333-8333-333333333333",
         "oldest_period_id": "period", "measured_bytes": tasks.FREE_BYTES + 192,
         "credits_due": 3, "outstanding_credits": 3, "unit_selection_hash": "a" * 64,
         "units": [{"unit_id": "b" * 64, "kind": "upload", "resource_id": "file",
                    "oldest_at": 1_000_000_000, "bytes": tasks.FREE_BYTES + 96}]},
        directus=SimpleNamespace(get_items=AsyncMock(side_effect=get_items)),
        encryption=SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value="owner@example.invalid")),
        email_service=object(), orchestration=SimpleNamespace(execute=AsyncMock()), cache=object(),
    )
    assert result is False  # Submission failures never advance the delivered-warning clock.
    context = sender.await_args.kwargs["context"]
    assert context["credits_url"] == "https://app.example.invalid/#settings/billing"
    assert context["export_url"] == "https://app.example.invalid/#settings/account/export"
    assert context["storage_url"] == "https://app.example.invalid/#settings/account/storage"
    assert sender.await_args.kwargs["template"] == f"storage-billing-failed-{stage}"
    from backend.tests.test_storage_billing_notice_email import _render_notice
    rendered = _render_notice(stage, "en", context)
    for link in ("credits_url", "export_url", "storage_url"):
        assert f'href="{context[link]}"' in rendered


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote,billing.storage.four-warning-expiry
async def test_warning_retry_reuses_frozen_context_and_delivery_identity(monkeypatch):
    episode = "33333333-3333-4333-8333-333333333333"
    owner = "22222222-2222-4222-8222-222222222222"
    frozen = {
        "storage_gb": 1.25, "credits_needed": 3,
        "outstanding_credits": 9, "deadline_date": "2026-11-01",
        "credits_url": "https://openmates.org/settings/billing",
        "export_url": "https://openmates.org/settings/export",
        "darkmode": False,
        "unit_selection_hash": "a" * 64,
    }
    class FakeDirectus:
        reads = 0
        async def get_items(self, collection, **_kwargs):
            if collection == "email_deliveries":
                self.reads += 1
                if self.reads > 1:
                    return [{
                        "id": "44444444-4444-4444-8444-444444444444",
                        "status": "sent", "recipient_hash": tasks.hashlib.sha256(
                            b"person@example.invalid").hexdigest(),
                        "provider_message_id": "provider-exact-1",
                    }]
                return [{
                    "status": "failed", "lang": "en",
                    "metadata": {"template": "storage-billing-failed-1", "context": frozen},
                }]
            return [{
                "encrypted_email_address": "sealed", "vault_key_id": "key",
                "language": "de",
            }]

    sender = AsyncMock(return_value=(True, "sent"))
    monkeypatch.setattr(tasks, "send_email_once", sender)
    async def operation(name, _payload):
        if name == "record_storage_delivery_receipt":
            return {"state": "delivered", "held": False}
        return {"warning_count": 1}
    orchestration = SimpleNamespace(execute=AsyncMock(side_effect=operation))
    email_service = SimpleNamespace(get_delivery_events_for_message=AsyncMock(
        return_value={"events": [{
            "messageId": "provider-exact-1", "email": "person@example.invalid",
            "event": "delivered", "date": "2025-10-04T03:00:00Z",
        }]}))
    result = await tasks._deliver_warning(
        owner,
        {
            "warning_stage": 1, "episode_id": episode, "oldest_period_id": "period",
            "measured_bytes": 5 * tasks.FREE_BYTES, "credits_due": 15,
            "outstanding_credits": 40,
            "unit_selection_hash": "a" * 64,
            "units": [{"unit_id": "b" * 64}],
        },
        directus=FakeDirectus(),
        encryption=SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value="person@example.invalid")),
        email_service=email_service, orchestration=orchestration, cache=object(),
    )
    assert result is True
    assert sender.await_args.kwargs["context"] == frozen
    assert sender.await_args.kwargs["lang"] == "en"
    assert sender.await_args.kwargs["retry_cache"] is not None
    assert orchestration.execute.await_args.args[0] == "acknowledge_storage_warning"


# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
def test_provider_delivery_event_requires_exact_message_recipient_and_untruncated_report():
    recipient_hash = tasks.hashlib.sha256(b"owner@example.invalid").hexdigest()
    exact = {"messageId": "<exact@provider>", "email": "owner@example.invalid",
             "event": "delivered", "date": "2025-10-04T03:00:00Z"}
    def decide(events):
        return tasks._provider_delivery_decision(
            {"events": events}, message_id="<exact@provider>", recipient_hash=recipient_hash)
    assert decide([exact])[0] == "delivered"
    assert decide([{**exact, "event": "requests"}]) == ("unknown", None)
    assert decide([{**exact, "messageId": "<other@provider>"}]) == ("unknown", None)
    assert decide([{**exact, "email": "other@example.invalid"}]) == ("unknown", None)
    assert decide([exact] * 101) == ("unknown", None)
    assert decide([exact, {**exact, "event": "hardBounces"}])[0] == "failed"
    assert decide([exact, {**exact, "event": "unknownNegativeEvent"}]) == ("unknown", None)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
async def test_storage_submission_persists_private_id_but_never_counts_without_delivery():
    from backend.core.api.app.services.email_delivery_guard import send_email_once

    class Directus:
        base_url = "https://cms.example.invalid"
        row = None

        async def login_admin(self):
            return "test"

        async def _make_api_request(self, _method, _url, **kwargs):
            self.row = dict(kwargs["json"])
            return SimpleNamespace(status_code=200, text="")

        async def update_item(self, _collection, _id, fields, **_kwargs):
            self.row.update(fields)
            return dict(self.row)

        async def get_items(self, _collection, **_kwargs):
            return [dict(self.row)]

    directus = Directus()

    async def accepted(**kwargs):
        await kwargs["accepted_message_id"]("<exact@provider>")
        return True

    template = SimpleNamespace(send_email=AsyncMock(side_effect=accepted))
    sent, state = await send_email_once(
        directus=directus, email_template_service=template,
        email_type="storage-billing-warning", campaign_key="episode",
        recipient_kind="directus_user", recipient_id="owner",
        recipient_email="owner@example.invalid", template="storage-billing-failed-1",
        context={}, stage="week-1",
    )
    assert (sent, state) == (True, "sent")
    assert directus.row["provider_message_id"] == "<exact@provider>"
    assert directus.row["provider_delivery_state"] == "accepted"
    assert directus.row.get("provider_delivered_at") is None
    orchestration = SimpleNamespace(execute=AsyncMock())
    assert not await tasks._reconcile_provider_receipt(
        "owner", "episode", 1,
        {"id": directus.row["id"], "status": "sent",
         "provider_message_id": "<exact@provider>",
         "recipient_hash": tasks.hashlib.sha256(b"owner@example.invalid").hexdigest()},
        email_service=SimpleNamespace(get_delivery_events_for_message=AsyncMock(
            return_value={"events": []})),
        orchestration=orchestration,
    )
    orchestration.execute.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
async def test_old_accepted_notice_is_reconciled_after_send_retry_window(monkeypatch):
    from datetime import timedelta
    from backend.core.api.app.services import storage_usage_metering

    user_id = "22222222-2222-4222-8222-222222222222"
    episode = "33333333-3333-4333-8333-333333333333"
    delivery_id = "44444444-4444-4444-8444-444444444444"
    address = "owner@example.invalid"
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    row = {
        "id": delivery_id, "recipient_id": user_id, "recipient_kind": "directus_user",
        "recipient_hash": tasks.hashlib.sha256(address.encode()).hexdigest(),
        "campaign_key": episode, "stage": "week-1", "status": "sent",
        "provider_message_id": "<exact@provider>", "processing_started_at": old,
    }

    class Directus:
        def __init__(self):
            self.reads = 0
            self.updated = []

        async def ensure_auth_token(self):
            return "test"

        async def get_items(self, collection, *, params, **_kwargs):
            if collection == "email_deliveries" and params["filter"].get(
                "provider_delivery_state") == {"_eq": "accepted"}:
                self.reads += 1
                return [row] if self.reads == 1 else []
            return []

        async def update_item(self, collection, item_id, data, **_kwargs):
            self.updated.append((collection, item_id, data))
            return {"id": item_id, **data}

    directus = Directus()
    operations = []

    class Orchestration:
        async def execute(self, name, data):
            operations.append(name)
            return {"state": "delivered", "held": False} if name == "record_storage_delivery_receipt" else {
                "warning_count": 1}

    class Email:
        async def get_delivery_events_for_message(self, message_id):
            assert message_id == "<exact@provider>"
            return {"events": [{
                "messageId": message_id, "email": address,
                "event": "delivered", "date": "2025-10-04T03:00:00Z",
            }]}

    class Secrets:
        async def initialize(self):
            pass

        async def aclose(self):
            pass

    class Cache:
        async def close(self):
            pass

    monkeypatch.setattr(tasks, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(tasks, "SecretsManager", Secrets)
    monkeypatch.setattr(tasks, "DirectusService", lambda: directus)
    monkeypatch.setattr(tasks, "CacheService", Cache)
    monkeypatch.setattr(tasks, "EncryptionService", lambda: object())
    monkeypatch.setattr(tasks, "BillingService", lambda **_kwargs: object())
    monkeypatch.setattr(tasks, "ServerStatsService", lambda *_args: object())
    monkeypatch.setattr(tasks, "SubChatOrchestrationService", lambda _directus: Orchestration())
    monkeypatch.setattr(tasks, "EmailTemplateService", lambda **_kwargs: Email())
    monkeypatch.setattr(storage_usage_metering, "StorageUsageMeteringService",
                        lambda _directus: object())

    result = await tasks._async_retry_storage_warning_deliveries()
    assert result["warnings_delivered"] == 1
    assert operations == ["record_storage_delivery_receipt", "acknowledge_storage_warning"]
    assert directus.updated[0][2].get("provider_receipt_checked_at")

    # A delayed or hung provider must not keep a two-minute sweep alive, and
    # the unchecked row remains eligible for the next sweep.
    directus.reads = 0
    directus.updated.clear()
    operations.clear()
    clock = iter((0, tasks.PROVIDER_RECEIPT_SWEEP_SECONDS + 1))
    monkeypatch.setattr(tasks.time, "monotonic",
                        lambda: next(clock, tasks.PROVIDER_RECEIPT_SWEEP_SECONDS + 1))
    result = await tasks._async_retry_storage_warning_deliveries()
    assert result["warnings_delivered"] == 0
    assert directus.reads == 0
    assert not directus.updated
    assert not operations


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
async def test_exact_brevo_receipt_query_has_ten_second_timeout(monkeypatch):
    from backend.core.api.app.services.email import brevo_provider

    captured = {}

    class Session:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def get(self, _url, **kwargs):
            captured["params"] = kwargs["params"]
            raise TimeoutError("provider stalled")

    monkeypatch.setattr(brevo_provider.aiohttp, "ClientSession", Session)
    provider = brevo_provider.BrevoProvider(api_key="placeholder")
    result = await provider.get_email_events(message_id="<private@provider>", days=90)
    assert result["error"] == "delivery_event_report_failed"
    assert captured["timeout"].total == 10
    assert captured["params"]["messageId"] == "<private@provider>"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["recent_retry", "due_warning"])
# contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement,billing.storage.four-warning-expiry
async def test_warning_sweep_bounds_slow_settlement_across_scans(monkeypatch, phase):
    import asyncio
    from backend.core.api.app.services import storage_usage_metering

    user_ids = ["owner-1", "owner-2"]
    attempted = []

    class Directus:
        def __init__(self):
            self.recent_reads = 0
            self.due_reads = 0

        async def ensure_auth_token(self):
            return "test"

        async def get_items(self, collection, *, params, **_kwargs):
            if collection == "email_deliveries" and params["filter"].get(
                "processing_started_at", {}).get("_gte"):
                self.recent_reads += 1
                if phase == "recent_retry" and self.recent_reads == 1:
                    return [{"id": str(i), "recipient_id": user_id,
                             "recipient_kind": "directus_user"}
                            for i, user_id in enumerate(user_ids)]
            if collection == "storage_billing_owner_state":
                self.due_reads += 1
                if phase == "due_warning" and self.due_reads == 1:
                    return [{"id": str(i), "user_id": user_id}
                            for i, user_id in enumerate(user_ids)]
            return []

    class Secrets:
        async def initialize(self):
            pass

        async def aclose(self):
            pass

    class Cache:
        async def close(self):
            pass

    class Metering:
        async def quote_personal(self, ids):
            return {user_id: quote() for user_id in ids}

    async def slow_settlement(user_id, *_args, **_kwargs):
        attempted.append(user_id)
        await asyncio.sleep(0.5)
        return {"warnings_delivered": 1}

    directus = Directus()
    monkeypatch.setattr(tasks, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(tasks, "PROVIDER_RECEIPT_SWEEP_SECONDS", 0.05)
    monkeypatch.setattr(tasks, "SecretsManager", Secrets)
    monkeypatch.setattr(tasks, "DirectusService", lambda: directus)
    monkeypatch.setattr(tasks, "CacheService", Cache)
    monkeypatch.setattr(tasks, "EncryptionService", lambda: object())
    monkeypatch.setattr(tasks, "BillingService", lambda **_kwargs: object())
    monkeypatch.setattr(tasks, "ServerStatsService", lambda *_args: object())
    monkeypatch.setattr(tasks, "SubChatOrchestrationService", lambda _directus: object())
    monkeypatch.setattr(tasks, "EmailTemplateService", lambda **_kwargs: object())
    monkeypatch.setattr(tasks, "_settle_owner", slow_settlement)
    monkeypatch.setattr(storage_usage_metering, "StorageUsageMeteringService",
                        lambda _directus: Metering())

    started = tasks.time.monotonic()
    result = await tasks._async_retry_storage_warning_deliveries()
    assert tasks.time.monotonic() - started < 0.2
    assert attempted == ["owner-1"]
    assert result["warnings_delivered"] == 0
    assert result["errors"] == 1


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.logical-usage,billing.storage.weekly-quote
async def test_incomplete_owner_quote_does_not_suppress_healthy_peers():
    from backend.core.api.app.services.storage_usage_metering import StorageUsageIncompleteError

    class FakeMetering:
        async def quote_personal(self, ids):
            if "bad" in ids:
                raise StorageUsageIncompleteError("storage_usage_invalid_bytes")
            return {user_id: quote() for user_id in ids}

    quotes, failed = await tasks._quote_owners_isolating_incomplete(
        FakeMetering(), ["good-1", "bad", "good-2"]
    )
    assert set(quotes) == {"good-1", "good-2"}
    assert failed == ["bad"]
