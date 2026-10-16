"""Private daily scheduled Workflow digest boundaries and send semantics."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.core.api.app.services.workflow_digest_service import (
    collect_workflow_digest,
    digest_window,
    load_workflow_message_previews,
    load_workflow_title_previews,
)
from backend.core.api.app.tasks.email_tasks import workflow_digest_email_task as sender
from backend.core.api.app.tasks.email_tasks import daily_notification_dispatcher as dispatcher


CUTOFF = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
START, END = digest_window(CUTOFF)
OWNER = "user_sha256:" + hashlib.sha256(b"alice").hexdigest()
DELIVERY_OWNER = OWNER.removeprefix("user_sha256:")


def run(run_id: str, *, at: int = START, trigger: str = "schedule", status: str = "completed", owner: str = OWNER) -> dict:
    return {"run_id": run_id, "workflow_id": "workflow-1", "hashed_user_id": owner,
            "trigger_type": trigger, "accepted_at": at, "status": status,
            "started_at": at + 1, "finished_at": at + 4,
            "encrypted_output_summary": "secret-output"}


class FakeDirectus:
    def __init__(self, *, runs: list[dict] | None = None, deliveries: list[dict] | None = None,
                 workflows: list[dict] | None = None, blobs: list[dict] | None = None,
                 user: dict | None = None) -> None:
        self.collections = {"workflow_runs": runs or [], "workflow_chat_deliveries": deliveries or [],
                            "workflows": workflows or [], "workflow_encrypted_blobs": blobs or []}
        self.user = user
        self.calls: list[tuple[str, dict]] = []

    async def get_items(self, collection: str, *, params: dict, admin_required: bool, raise_on_error: bool = False):
        assert admin_required
        self.calls.append((collection, params))
        start = (params.get("page", 1) - 1) * params.get("limit", 200)
        return self.collections.get(collection, [])[start:start + params.get("limit", 200)]

    async def get_user_fields_direct(self, user_id: str, fields: list[str], *, no_cache=False):
        assert user_id == "alice"
        return self.user


def fake_email_service():
    return SimpleNamespace(translation_service=SimpleNamespace(
        get_nested_translation=lambda key, language, context: "Your daily Workflow runs",
    ))


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_digest_uses_owner_schedule_and_half_open_utc_window(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.test")
    now = int(datetime.now(timezone.utc).timestamp())
    directus = FakeDirectus(runs=[
        run("first", at=START), run("second", at=END - 1, status="failed"),
        run("at-end", at=END), run("before", at=START - 1),
        run("manual", trigger="manual"), run("test", trigger="test"),
        run("event", trigger="event"), run("other-owner", owner="user_sha256:other"),
        run("deleted", status="deleted"),
    ], deliveries=[
        {"delivery_id": "pending", "run_id": "first", "hashed_user_id": DELIVERY_OWNER, "status": "delivery_pending"},
        {"delivery_id": "claimed", "run_id": "first", "hashed_user_id": DELIVERY_OWNER, "status": "claimed"},
        {"delivery_id": "ack", "run_id": "first", "hashed_user_id": DELIVERY_OWNER, "status": "acknowledged"},
        {"delivery_id": "cancelled", "run_id": "first", "hashed_user_id": DELIVERY_OWNER, "status": "cancelled"},
        {"delivery_id": "expired", "run_id": "first", "hashed_user_id": DELIVERY_OWNER, "status": "expired"},
        {"delivery_id": "failed", "run_id": "first", "hashed_user_id": DELIVERY_OWNER, "status": "failed"},
        {"delivery_id": "stale-pending", "run_id": "first", "hashed_user_id": DELIVERY_OWNER,
         "status": "delivery_pending", "expires_at": now - 1},
        {"delivery_id": "persisted-claimed", "run_id": "first", "hashed_user_id": DELIVERY_OWNER,
         "status": "claimed", "expires_at": now - 1, "client_persisted_at": now - 2},
        {"delivery_id": "not-ours", "run_id": "first", "hashed_user_id": "different", "status": "acknowledged"},
        {"delivery_id": "not-window", "run_id": "at-end", "hashed_user_id": DELIVERY_OWNER, "status": "acknowledged"},
    ])
    digest = await collect_workflow_digest(directus, "alice", CUTOFF)
    assert digest is not None
    assert digest["run_count"] == 2
    assert digest["status_counts"] == {"completed": 1, "failed": 1}
    assert digest["delivery_pending_count"] == 3
    assert digest["delivery_acknowledged_count"] == 1
    assert digest["delivery_cancelled_count"] == 1
    assert digest["delivery_expired_count"] == 2
    assert digest["delivery_failed_count"] == 1
    assert digest["rows"][0]["delivery_expired_count"] == 2
    assert [row["run_id"] for row in digest["rows"]] == ["first", "second"]
    assert digest["rows"][0]["url"] == "https://app.example.test/#workflow-id=workflow-1&workflow-tab=runs&run-id=first"
    assert "secret-output" not in json.dumps(digest)
    query = directus.calls[0][1]["filter"]["_and"]
    assert {"trigger_type": {"_in": ["schedule"]}} in query
    assert {"accepted_at": {"_gte": START, "_lt": END}} in query
    assert "expires_at,client_persisted_at" in directus.calls[1][1]["fields"]


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_empty_digest_has_no_delivery_query_or_email(monkeypatch):
    directus = FakeDirectus(runs=[run("manual", trigger="manual")])
    assert await collect_workflow_digest(directus, "alice", CUTOFF) is None
    assert [collection for collection, _ in directus.calls] == ["workflow_runs"]

    send_once = AsyncMock()
    monkeypatch.setattr(sender, "send_email_once", send_once)
    task = SimpleNamespace(directus_service=directus, encryption_service=object(), email_template_service=fake_email_service())
    assert await sender.send_user_workflow_digest(task, "alice", CUTOFF) == "empty"
    send_once.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_sender_rechecks_consent_and_uses_user_day_key_without_private_content(monkeypatch):
    directus = FakeDirectus(runs=[run("first")], user={
        "id": "alice", "status": "active", "email_notifications_enabled": True,
        "email_notification_preferences": {"workflowRuns": True, "includeContent": False},
        "language": "en", "vault_key_id": "vault-key", "darkmode": False,
    })
    monkeypatch.setattr(sender, "resolve_notification_email", AsyncMock(return_value="verified@example.test"))
    send_once = AsyncMock(side_effect=[(True, "sent"), (False, "already_reserved")])
    monkeypatch.setattr(sender, "send_email_once", send_once)
    task = SimpleNamespace(directus_service=directus, encryption_service=object(), email_template_service=fake_email_service())
    assert await sender.send_user_workflow_digest(task, "alice", CUTOFF) == "sent"
    assert await sender.send_user_workflow_digest(task, "alice", CUTOFF) == "already_reserved"
    kwargs = send_once.await_args.kwargs
    assert kwargs["campaign_key"] == "workflowRuns"
    assert kwargs["stage"] == "2026-10-01"
    assert kwargs["recipient_email"] == "verified@example.test"
    assert kwargs["context"]["rows"][0]["accepted_time"].endswith("UTC")
    assert "title" not in kwargs["context"]["rows"][0]
    assert "secret-output" not in json.dumps(kwargs["context"])

    directus.user["email_notification_preferences"] = {"workflowRuns": False}
    assert await sender.send_user_workflow_digest(task, "alice", CUTOFF) == "disabled"
    assert send_once.await_count == 2


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_sender_drops_preview_when_content_consent_changes_before_send(monkeypatch):
    user = {"id": "alice", "status": "active", "email_notifications_enabled": True,
            "email_notification_preferences": {"workflowRuns": True, "includeContent": True},
            "email_notification_preference_choices": {"includeContent": {"source": "user", "value": True}},
            "vault_key_id": "key-1"}
    directus = FakeDirectus(runs=[run("first")], user=user)
    load_user = AsyncMock(side_effect=[user, {**user, "email_notification_preferences": {"workflowRuns": True, "includeContent": False}}])
    monkeypatch.setattr(sender, "load_notification_user", load_user)
    monkeypatch.setattr(sender, "resolve_notification_email", AsyncMock(return_value="verified@example.test"))
    monkeypatch.setattr(sender, "load_workflow_title_previews", AsyncMock(return_value={"workflow-1": "Private title"}))
    monkeypatch.setattr(sender, "load_workflow_message_previews", AsyncMock(return_value={"first": "Private message"}))
    send_once = AsyncMock(return_value=(True, "sent"))
    monkeypatch.setattr(sender, "send_email_once", send_once)
    task = SimpleNamespace(directus_service=directus, encryption_service=object(), email_template_service=fake_email_service())
    assert await sender.send_user_workflow_digest(task, "alice", CUTOFF) == "sent"
    assert "Private title" not in json.dumps(send_once.await_args.kwargs["context"])
    assert "Private message" not in json.dumps(send_once.await_args.kwargs["context"])
    assert load_user.await_count == 2


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_reserved_send_rechecks_unsubscribe_and_redacts_preview(monkeypatch):
    user = {"id": "alice", "status": "active", "email_notifications_enabled": True,
            "email_notification_preferences": {"workflowRuns": True, "includeContent": True},
            "email_notification_preference_choices": {"includeContent": {"source": "user", "value": True}},
            "vault_key_id": "key-1"}
    without_preview = {**user, "email_notification_preferences": {"workflowRuns": True, "includeContent": False}}
    unsubscribed = {**user, "email_notification_preferences": {"workflowRuns": False, "includeContent": False}}
    directus = FakeDirectus(runs=[run("first")], user=user)
    load_user = AsyncMock(side_effect=[user, user, without_preview])
    monkeypatch.setattr(sender, "load_notification_user", load_user)
    monkeypatch.setattr(sender, "resolve_notification_email", AsyncMock(return_value="verified@example.test"))
    monkeypatch.setattr(sender, "load_workflow_title_previews", AsyncMock(return_value={"workflow-1": "Secret title"}))
    monkeypatch.setattr(sender, "load_workflow_message_previews", AsyncMock(return_value={"first": "Secret message"}))
    seen: list[dict] = []

    async def guarded_send(**kwargs):
        assert await kwargs["before_send"]()
        seen.append(kwargs["context"])
        return True, "sent"

    monkeypatch.setattr(sender, "send_email_once", guarded_send)
    task = SimpleNamespace(directus_service=directus, encryption_service=object(), email_template_service=fake_email_service())
    assert await sender.send_user_workflow_digest(task, "alice", CUTOFF) == "sent"
    assert "Secret title" not in json.dumps(seen[0])
    assert "Secret message" not in json.dumps(seen[0])
    assert seen[0]["settings_url"].endswith("/#settings/notifications/chat")

    load_user.side_effect = [user, user, unsubscribed]
    async def skipped_send(**kwargs):
        assert not await kwargs["before_send"]()
        return False, "ineligible_at_dispatch"
    monkeypatch.setattr(sender, "send_email_once", skipped_send)
    assert await sender.send_user_workflow_digest(task, "alice", CUTOFF) == "ineligible_at_dispatch"


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_dispatcher_does_not_apply_reminder_inactivity_gate_to_workflow_digest(monkeypatch):
    user = {"id": "alice", "status": "active", "email_notifications_enabled": True,
            "email_notification_preferences": {"workflowRuns": True}, "last_access": "2020-01-01T00:00:00Z"}
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[user]))
    task = SimpleNamespace(
        directus_service=directus, initialize_core_services=AsyncMock(),
        _email_template_service=object(), _secrets_manager=object(), cleanup_services=AsyncMock(),
    )
    send_digest = AsyncMock(return_value="sent")
    monkeypatch.setattr(dispatcher, "send_user_workflow_digest", send_digest)
    monkeypatch.setattr(dispatcher, "HANDLERS", [])
    stats = await dispatcher._async_run_daily_notifications(task)
    assert stats["sent_workflowRuns"] == 1
    assert stats["skipped_inactive"] == 1
    assert directus.get_items.await_args.kwargs["no_cache"] is True
    cutoff = send_digest.await_args.args[2]
    assert (cutoff.hour, cutoff.minute, cutoff.second, cutoff.tzinfo) == (9, 0, 0, timezone.utc)


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_explicit_title_preview_decrypts_only_owner_verified_blob():
    plaintext = json.dumps("My private workflow")
    ref = "vault://workflows/workflow_title/one"
    directus = FakeDirectus(workflows=[
        {"workflow_id": "workflow-1", "hashed_user_id": OWNER, "record_json": {"encrypted_title_ref": ref}},
    ], blobs=[
        {"ref": ref, "hashed_user_id": OWNER, "kind": "workflow_title", "ciphertext": "cipher",
         "checksum": "sha256:" + hashlib.sha256(plaintext.encode()).hexdigest(), "vault_key_ref": "key-1"},
    ])
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value=plaintext))
    titles = await load_workflow_title_previews(
        directus, encryption, user_id="alice", vault_key_id="key-1",
        rows=[{"workflow_id": "workflow-1"}],
    )
    assert titles == {"workflow-1": "My private workflow"}
    encryption.decrypt_with_user_key.assert_awaited_once_with("cipher", "key-1")


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
@pytest.mark.asyncio
async def test_message_preview_reads_only_live_owner_matched_send_message_payload():
    payload = json.dumps({"title": "ignored", "message": "<script>private</script>\n" + "x" * 2500 + "\nlast line", "embeds": [{"content": {"secret": "embed"}}]})
    envelope = json.dumps({"ciphertext": "cipher", "vault_key_id": "key-1"})
    now = int(datetime.now(timezone.utc).timestamp())
    base = {"delivery_id": "delivery-1", "run_id": "first", "workflow_id": "workflow-1",
            "hashed_user_id": DELIVERY_OWNER, "status": "delivery_pending", "expires_at": now + 100,
            "encrypted_payload": envelope}
    directus = FakeDirectus(deliveries=[
        {**base, "delivery_id": "foreign", "hashed_user_id": "other"},
        {**base, "delivery_id": "wrong-workflow", "workflow_id": "other"},
        {**base, "delivery_id": "expired", "expires_at": now - 1},
        {**base, "delivery_id": "cancelled", "status": "cancelled"},
        {**base, "delivery_id": "failed", "status": "failed"},
        {**base, "delivery_id": "terminal-expired", "status": "expired"},
        {**base, "delivery_id": "wrong-key", "encrypted_payload": json.dumps({"ciphertext": "cipher", "vault_key_id": "other"})},
        {**base, "delivery_id": "cleared", "encrypted_payload": ""},
        base,
        {**base, "delivery_id": "second-valid"},
    ])
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value=payload))
    result = await load_workflow_message_previews(
        directus, encryption, user_id="alice", vault_key_id="key-1",
        rows=[{"run_id": "first", "workflow_id": "workflow-1"}],
    )
    assert result["first"].startswith("<script>private</script>\n")
    assert len(result["first"]) == 2000
    assert "last line" not in result["first"] and "embed" not in result["first"]
    encryption.decrypt_with_user_key.assert_awaited_once_with("cipher", "key-1")
    query = directus.calls[0][1]["filter"]["_and"]
    assert {"hashed_user_id": {"_eq": DELIVERY_OWNER}} in query
    assert {"expires_at": {"_gt": now}} in query


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
@pytest.mark.asyncio
async def test_message_preview_stops_after_ten_lines():
    now = int(datetime.now(timezone.utc).timestamp())
    directus = FakeDirectus(deliveries=[{
        "delivery_id": "delivery-1", "run_id": "first", "workflow_id": "workflow-1",
        "hashed_user_id": DELIVERY_OWNER, "status": "claimed", "expires_at": now + 100,
        "encrypted_payload": json.dumps({"ciphertext": "cipher", "vault_key_id": "key-1"}),
    }])
    message = "\n".join(f"line-{index}" for index in range(1, 13))
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value=json.dumps({"message": message})))
    result = await load_workflow_message_previews(
        directus, encryption, user_id="alice", vault_key_id="key-1",
        rows=[{"run_id": "first", "workflow_id": "workflow-1"}],
    )
    assert result["first"].splitlines() == [f"line-{index}" for index in range(1, 11)]


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
def test_digest_cutoff_requires_fixed_utc_0900():
    with pytest.raises(ValueError):
        digest_window(datetime(2026, 10, 1, 9))
    with pytest.raises(ValueError):
        digest_window(datetime(2026, 10, 1, 10, tzinfo=timezone.utc))


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_digest_retry_cannot_cross_the_next_daily_boundary(monkeypatch):
    from backend.core.api.app.tasks.email_tasks import workflow_digest_email_task as worker
    cutoff = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)

    class Clock(datetime):
        current = cutoff + timedelta(days=1, seconds=-1)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(worker, "datetime", Clock)
    # apply_async publishes synchronously; retain the actual broker arguments.
    publish = Mock()
    monkeypatch.setattr(worker.retry_workflow_digest, "apply_async", publish)
    assert worker.queue_workflow_digest_retry("alice", int(cutoff.timestamp()), 1)
    assert publish.call_args.kwargs["expires"] == 600
    assert publish.call_args.kwargs["args"] == ["alice", int(cutoff.timestamp()), 1]

    Clock.current += timedelta(seconds=1)
    publish.reset_mock()
    assert not worker.queue_workflow_digest_retry("alice", int(cutoff.timestamp()), 1)
    publish.assert_not_called()
    initialize = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(worker, "initialize_notification_email_services", initialize)
    monkeypatch.setattr(worker, "send_user_workflow_digest", send)
    assert await worker._async_retry_workflow_digest(SimpleNamespace(), "alice", int(cutoff.timestamp()), 1) == "expired_retry"
    initialize.assert_not_awaited()
    send.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_digest_retry_expires_when_initialization_crosses_next_0900(monkeypatch):
    cutoff = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)

    class Clock(datetime):
        current = cutoff + timedelta(days=1, seconds=-1)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(sender, "datetime", Clock)

    async def initialize(task):
        Clock.current += timedelta(seconds=1)

    send = AsyncMock()
    cleanup = AsyncMock()
    monkeypatch.setattr(sender, "initialize_notification_email_services", initialize)
    monkeypatch.setattr(sender, "send_user_workflow_digest", send)
    assert await sender._async_retry_workflow_digest(
        SimpleNamespace(cleanup_services=cleanup), "alice", int(cutoff.timestamp()), 1,
    ) == "expired_retry"
    send.assert_not_awaited()
    cleanup.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_daily_sweep_skips_old_cutoff_after_initialization_crosses_0900(monkeypatch):
    cutoff = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)

    class Clock(datetime):
        current = cutoff + timedelta(days=1, seconds=-1)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(dispatcher, "datetime", Clock)
    monkeypatch.setattr(sender, "datetime", Clock)

    async def initialize(task):
        Clock.current += timedelta(seconds=1)

    directus = SimpleNamespace(get_items=AsyncMock(side_effect=[[
        {"id": "alice", "status": "active", "email_notifications_enabled": True,
         "email_notification_preferences": {"workflowRuns": True}},
    ], []]))
    task = SimpleNamespace(directus_service=directus, cleanup_services=AsyncMock())
    send = AsyncMock(return_value="sent")
    monkeypatch.setattr(dispatcher, "initialize_notification_email_services", initialize)
    monkeypatch.setattr(dispatcher, "send_user_workflow_digest", send)
    monkeypatch.setattr(dispatcher, "HANDLERS", [])
    stats = await dispatcher._async_run_daily_notifications(task)
    assert stats["sent_workflowRuns"] == 0
    send.assert_not_awaited()
    assert directus.get_items.await_args.kwargs["no_cache"] is True


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_production_digest_late_gate_rejects_cutoff_crossed_during_credentials(monkeypatch):
    cutoff = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)

    class Clock(datetime):
        current = cutoff + timedelta(days=1, seconds=-1)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(sender, "datetime", Clock)
    user = {"id": "alice", "status": "active", "email_notifications_enabled": True,
            "email_notification_preferences": {"workflowRuns": True, "includeContent": False}}
    directus = FakeDirectus(runs=[run("first")], user=user)
    monkeypatch.setattr(sender, "resolve_notification_email", AsyncMock(return_value="verified@example.test"))
    gates = []

    async def guarded_send(**kwargs):
        gates.append(await kwargs["before_send"]())
        # Mirrors the credential await inside EmailTemplateService; the guard
        # invokes this same callback again immediately before transport.
        Clock.current += timedelta(seconds=1)
        gates.append(await kwargs["before_send"]())
        return False, "ineligible_at_dispatch"

    monkeypatch.setattr(sender, "send_email_once", guarded_send)
    task = SimpleNamespace(directus_service=directus, encryption_service=object(),
                           email_template_service=fake_email_service())
    assert await sender.send_user_workflow_digest(
        task, "alice", cutoff, require_current_cutoff=True,
    ) == "ineligible_at_dispatch"
    assert gates == [True, False]
