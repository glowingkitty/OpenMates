"""Actual Workflow output eligibility, exact authority and per-channel replay."""
from __future__ import annotations
import hashlib
import json
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from backend.core.api.app.services import workflow_chat_notification_service as service
from backend.core.api.app.services import chat_email_notification_service as email
from backend.core.api.app.services.email_template import EmailSendDeferred
from backend.core.api.app.tasks.workflow_tasks import reconcile_workflow_chat_notifications_now


class Directus:
    base_url = "http://cms:8055"
    def __init__(self, *, run_status="running", persisted=False):
        self.row = {"id": "ledger", "owner_user_id": "owner", "chat_id": "chat", "message_id": "message",
                    "delivery_id": "delivery", "workflow_id": "workflow", "run_id": "run",
                    "notification_id": service.message_notification_id("owner", "chat", "message"),
                    "event_state": "pending", "push_state": "pending", "email_state": "pending"}
        self.delivery = {**{key: self.row[key] for key in service.ROUTING_FIELDS}, "status": "delivery_pending",
                         "encrypted_payload": "vault-ciphertext", "client_persisted_at": 123 if persisted else None,
                         "expires_at": time.time() + 300, "hashed_user_id": hashlib.sha256(b"owner").hexdigest()}
        self.run_status = run_status
        self.chat = SimpleNamespace(get_chat_metadata=AsyncMock(return_value={"id": "chat", "hashed_user_id": self.delivery["hashed_user_id"], "hashed_team_id": None, "chat_visibility": None, "participant_user_hashes": None, "participant_key_envelopes": None} if persisted else None))
        self.user = {"id": "owner", "status": "active", "push_notification_enabled": True,
                     "push_notification_preferences": {"aiResponses": True, "workflowRuns": False},
                     "push_notification_subscription": json.dumps({"type": "multi", "targets": [
                         {"type": "apns", "token": "one", "platform": "ios"},
                         {"type": "apns", "token": "two", "platform": "ios"}]})}
        self.messages_exist = persisted

    async def get_items(self, collection, params, **kwargs):
        assert kwargs["no_cache"] and kwargs["raise_on_error"]
        if collection == service.COLLECTION:
            return [deepcopy(self.row)] if self.row else []
        if collection == "workflow_chat_deliveries":
            return [deepcopy(self.delivery)] if self.delivery else []
        if collection == "workflow_runs":
            return [{"status": self.run_status}]
        if collection == "chats":
            metadata = self.chat.get_chat_metadata.return_value
            return [metadata] if metadata else []
        if collection == "messages":
            return [{"id": "canonical"}] if self.messages_exist else []
        raise AssertionError(collection)

    async def _make_api_request(self, *args, **kwargs):
        return SimpleNamespace(status_code=200, json=lambda: {"data": deepcopy(self.user)})

    async def get_user_fields_direct(self, user_id, fields, **kwargs):
        return deepcopy(self.user)

    async def update_item(self, collection, row_id, changes, **kwargs):
        assert collection == service.COLLECTION and row_id == self.row["id"]
        self.row.update(deepcopy(changes))
        return True


async def authority(directus, **overrides):
    return await service.delivery_authority(directus, **{"user_id": "owner", "chat_id": "chat",
        "message_id": "message", "delivery_id": "delivery", **overrides})


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target
async def test_offline_output_waits_for_success_but_committed_message_can_alert_before_or_after_failure():
    d = Directus()
    assert (await authority(d))[0] == "pending"
    d.run_status = "completed"
    assert (await authority(d))[0] == "eligible"
    for status in ("failed", "cancelled", "deleted"):
        d.run_status = status
        assert (await authority(d))[0] == "skipped"
    for status in ("running", "failed", "cancelled", "completed"):
        d = Directus(run_status=status, persisted=True)
        assert (await authority(d))[0] == "eligible"
    d.messages_exist = False
    assert (await authority(d))[0] == "unauthorized"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.content.privacy-boundary
async def test_pending_fallback_is_exact_owner_message_nonexpired_and_never_cross_team():
    d = Directus(run_status="completed")
    for overrides in ({"user_id": "other"}, {"message_id": "other"}, {"chat_id": "other"}):
        assert (await authority(d, **overrides))[0] == "unauthorized"
    d.chat.get_chat_metadata.return_value = {"hashed_user_id": d.delivery["hashed_user_id"], "hashed_team_id": "team"}
    assert (await authority(d))[0] == "unauthorized"
    d.chat.get_chat_metadata.return_value = None
    d.delivery["expires_at"] = time.time() - 1
    assert (await authority(d))[0] == "expired"
    d.delivery["expires_at"] = time.time() + 300
    d.delivery["status"] = "cancelled"
    assert (await authority(d))[0] == "skipped"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.workflow-run.chat-target
async def test_channels_are_independent_and_replay_does_not_repeat_accepted_or_uncertain_push(monkeypatch):
    d = Directus(run_status="completed")
    task = SimpleNamespace(directus_service=d, cache_service=object(), secrets_manager=object())
    monkeypatch.setattr(service, "has_active_human", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "is_message_viewed", AsyncMock(return_value=False))
    events = AsyncMock(side_effect=[RuntimeError("SSE offline"), True])
    monkeypatch.setattr(service.NotificationEventService, "store_and_publish_once", events)
    mail = AsyncMock(return_value="sent")
    monkeypatch.setattr(service, "_email", mail)
    monkeypatch.setattr(service.push_notification_service, "initialize", AsyncMock())
    monkeypatch.setattr(service.push_notification_service, "is_apns_ready", lambda: True)
    attempts = []
    def send(**kwargs):
        attempts.append(kwargs)
        return len(attempts) == 1  # Second provider response is uncertain.
    monkeypatch.setattr(service.push_notification_service, "send_push_notification", send)
    first = await service.dispatch_chat_notification(task, "delivery")
    assert first == {"status": "eligible", "event": "pending", "push": "accepted", "email": "sent"}
    # Replay even if dispatch died before its aggregate channel state was saved.
    d.row["push_state"] = "pending"
    second = await service.dispatch_chat_notification(task, "delivery")
    assert second["event"] == "published" and len(attempts) == 2 and mail.await_count == 1
    assert sorted(d.row["push_target_states"].values()) == ["accepted", "attempting"]
    assert attempts[0]["category"] == "OPENMATES_CHAT_MESSAGE"
    assert attempts[0]["workflow_routing"]["message_id"] == "message"
    assert "workflow-completion" not in attempts[0]["url"]
    assert events.await_args.args[0].id == d.row["notification_id"]
    assert events.await_args.args[0].type == "chat.assistant_message_received"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target
async def test_ordinary_chat_preferences_and_foreground_apply_independently_of_workflow_status_preferences(monkeypatch):
    d = Directus(run_status="completed")
    task = SimpleNamespace(directus_service=d, cache_service=object(), secrets_manager=object())
    d.user["push_notification_preferences"] = {"aiResponses": False, "workflowRuns": True}
    assert await service._push(task, d.row) == "disabled"
    monkeypatch.setattr(service, "has_active_human", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "is_message_viewed", AsyncMock(return_value=False))
    result = await service.dispatch_chat_notification(task, "delivery")
    assert result == {"status": "eligible", "event": "suppressed", "push": "suppressed", "email": "suppressed"}


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary,notifications.workflow-run.chat-target
async def test_email_workflow_access_cannot_be_used_as_broad_chat_or_status_authority():
    d = Directus(run_status="completed")
    assert not await email.notification_chat_access(d, "owner", "chat")
    assert await email._email_access(d, "owner", "chat", "message", {"source": "workflow_delivery", "workflow_delivery_id": "delivery"})
    assert not await email._email_access(d, "other", "chat", "message", {"source": "workflow_delivery", "workflow_delivery_id": "delivery"})
    assert not await email._email_access(d, "owner", "chat", "message", {"source": "workflow_delivery"})
    d.run_status = "failed"
    assert not await email._email_access(d, "owner", "chat", "message", {"source": "workflow_delivery", "workflow_delivery_id": "delivery"})


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent
async def test_reconciler_recovers_multiple_nodes_and_rotates_past_unfinished_runs():
    class PendingDirectus:
        async def get_items(self, collection, params, **kwargs):
            assert collection == service.COLLECTION
            start = (params["page"] - 1) * params["limit"]
            return [{"delivery_id": f"delivery-{i}"} for i in range(start, min(start + params["limit"], 205))]
    class Cursor:
        value = 1
        async def get(self, key): return self.value
        async def set(self, key, value, **kwargs): self.value = value
    cursor, queued = Cursor(), []
    for _ in range(3):
        await reconcile_workflow_chat_notifications_now(PendingDirectus(), cursor, queued.append, limit=100)
    assert len(queued) == len(set(queued)) == 205 and cursor.value == 1


# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target
def test_committed_message_routes_without_workflow_recovery_dependency():
    row = {key: key + "-value" for key in service.ROUTING_FIELDS}
    pending = service.message_url(row)
    committed = service.message_url({**row, "workflow_delivery_pending": False})
    assert "delivery-id=" in pending and "workflow-tab=runs" in pending
    assert committed.endswith("/#chat-id=chat_id-value&message-id=message_id-value")
    assert service._routing(row, {"client_persisted_at": 123}) == {"chat_id": "chat_id-value", "message_id": "message_id-value"}


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.content.privacy-boundary
async def test_workflow_email_candidate_recovers_after_cache_write_without_a_broker_message(monkeypatch):
    from backend.tests.test_chat_email_notification_service import Cache, Directus as EmailDirectus, Encryption
    user = {"id": "owner", "status": "active", "email_notifications_enabled": True,
            "email_notification_preferences": {"aiResponses": True, "workflowRuns": False, "includeContent": False},
            "vault_key_id": "owner-vault", "language": "en"}
    cache, directus, encryption = Cache(), EmailDirectus(user), Encryption()
    directus.base_url = "http://cms:8055"
    profile_reads = 0
    async def profile(*args, **kwargs):
        nonlocal profile_reads
        profile_reads += 1
        return SimpleNamespace(status_code=503 if profile_reads == 4 else 200, json=lambda: {"data": deepcopy(user)})
    directus._make_api_request = profile
    row = Directus(run_status="completed").row
    delivery = {"created_at": 123, "encrypted_payload": "private-vault-ciphertext"}
    task = SimpleNamespace(cache_service=cache, directus_service=directus, encryption_service=encryption,
                           email_template_service=object())
    monkeypatch.setattr(service, "delivery_authority", AsyncMock(return_value=("eligible", delivery)))
    monkeypatch.setattr(service, "load_delivery_notification", AsyncMock(return_value=row))
    monkeypatch.setattr(email, "has_active_human", AsyncMock(return_value=False))
    monkeypatch.setattr(email, "is_message_viewed", AsyncMock(return_value=False))
    monkeypatch.setattr(email, "resolve_notification_email", AsyncMock(return_value="ci@example.com"))
    from backend.core.api.app.services import email_delivery_guard
    captured = []
    async def send_once(**kwargs):
        try:
            assert await kwargs["before_send"]()
        except EmailSendDeferred:
            # The shared guard records a pre-provider failure for retry.
            return False, "failed"
        captured.append(kwargs)
        return True, "sent"
    monkeypatch.setattr(email_delivery_guard, "send_email_once", send_once)
    assert await service._email(task, row, delivery) == "pending"
    key = email.candidate_key("owner", "chat", "message")
    candidate = json.loads(cache.redis.values[key])
    assert candidate["source"] == "workflow_delivery" and candidate["workflow_delivery_id"] == "delivery"
    assert "private-vault-ciphertext" not in cache.redis.values[key]
    candidate["not_before"] = time.time() - 1
    cache.redis.values[key] = json.dumps(candidate)
    assert await service._email(task, row, delivery) == "pending"
    assert not captured  # Final-boundary HTTP 503 did not cross the provider.
    assert await service._email(task, row, delivery) == "sent"
    assert len(captured) == 1 and "delivery-id=delivery" in captured[0]["context"]["chat_url"]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.workflow-run.chat-target
async def test_profile_outage_at_final_push_gate_stays_pending_and_recovers_without_losing_other_channels(monkeypatch):
    d = Directus(run_status="completed")
    task = SimpleNamespace(directus_service=d, cache_service=object(), secrets_manager=object())
    reads = 0
    async def profile(*args, **kwargs):
        nonlocal reads
        reads += 1
        return SimpleNamespace(status_code=503 if reads == 2 else 200, json=lambda: {"data": deepcopy(d.user)})
    d._make_api_request = profile
    monkeypatch.setattr(service, "has_active_human", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "is_message_viewed", AsyncMock(return_value=False))
    events = AsyncMock(return_value=True)
    monkeypatch.setattr(service.NotificationEventService, "store_and_publish_once", events)
    mail = AsyncMock(return_value="sent")
    monkeypatch.setattr(service, "_email", mail)
    monkeypatch.setattr(service.push_notification_service, "initialize", AsyncMock())
    monkeypatch.setattr(service.push_notification_service, "is_apns_ready", lambda: True)
    attempts = []
    monkeypatch.setattr(service.push_notification_service, "send_push_notification", lambda **kwargs: attempts.append(kwargs) or True)
    first = await service.dispatch_chat_notification(task, "delivery")
    assert first["push"] == "pending" and first["email"] == "sent" and first["event"] == "published"
    assert not attempts and d.row["push_state"] == "pending"
    second = await service.dispatch_chat_notification(task, "delivery")
    assert second["push"] == "accepted" and len(attempts) == 2
    assert events.await_count == mail.await_count == 1


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent
async def test_strict_workflow_email_profile_404_is_terminal_but_outages_and_identity_mismatch_retry():
    d = Directus()
    d._make_api_request = AsyncMock(return_value=SimpleNamespace(status_code=503))
    with pytest.raises(RuntimeError, match="HTTP 503"):
        await email._email_user(d, "owner", {"source": "workflow_delivery"})
    d._make_api_request.return_value = SimpleNamespace(status_code=404)
    assert await email._email_user(d, "owner", {"source": "workflow_delivery"}) is None
    d._make_api_request.return_value = SimpleNamespace(status_code=200, json=lambda: {"data": {"id": "another"}})
    with pytest.raises(RuntimeError, match="identity mismatch"):
        await email._email_user(d, "owner", {"source": "workflow_delivery"})


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent
async def test_mixed_push_targets_progress_when_one_provider_is_unavailable(monkeypatch):
    d = Directus(run_status="completed")
    d.user["push_notification_subscription"] = json.dumps({"type": "multi", "targets": [
        {"type": "web", "endpoint": "https://example.com/web-push", "keys": {}},
        {"type": "apns", "token": "one", "platform": "ios"}]})
    task = SimpleNamespace(directus_service=d, cache_service=object(), secrets_manager=object())
    monkeypatch.setattr(service, "has_active_human", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "is_message_viewed", AsyncMock(return_value=False))
    monkeypatch.setattr(service.push_notification_service, "initialize", AsyncMock())
    monkeypatch.setattr(service.push_notification_service, "is_apns_ready", lambda: True)
    monkeypatch.setattr(service.push_notification_service, "is_ready", lambda: False)
    attempts = []
    monkeypatch.setattr(service.push_notification_service, "send_push_notification", lambda **kwargs: attempts.append(kwargs) or True)
    assert await service._push(task, d.row) == "pending"
    assert len(attempts) == 1 and json.loads(attempts[0]["subscription_json"])["type"] == "apns"
    monkeypatch.setattr(service.push_notification_service, "is_ready", lambda: True)
    assert await service._push(task, d.row) == "accepted"
    assert len(attempts) == 2 and json.loads(attempts[1]["subscription_json"])["type"] == "web"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.content.privacy-boundary
@pytest.mark.parametrize("persisted", [False, True])
async def test_inline_reply_workspace_requires_committed_canonical_personal_chat(monkeypatch, persisted):
    d = Directus(run_status="completed", persisted=persisted)
    task = SimpleNamespace(directus_service=d, cache_service=object(), secrets_manager=object())
    monkeypatch.setattr(service, "has_active_human", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "is_message_viewed", AsyncMock(return_value=False))
    monkeypatch.setattr(service.push_notification_service, "initialize", AsyncMock())
    monkeypatch.setattr(service.push_notification_service, "is_apns_ready", lambda: True)
    attempts = []
    monkeypatch.setattr(service.push_notification_service, "send_push_notification", lambda **kwargs: attempts.append(kwargs) or True)
    assert await service._push(task, d.row) == "accepted"
    assert len(attempts) == 2
    assert all(call["workspace"] == ({"kind": "personal"} if persisted else None) for call in attempts)
    assert all(("delivery_id" in call["workflow_routing"]) is not persisted for call in attempts)
    if persisted:
        d.chat.get_chat_metadata.return_value["chat_visibility"] = "direct"
        assert (await authority(d))[0] == "unauthorized"
