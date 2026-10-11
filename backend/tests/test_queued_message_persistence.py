"""Queued user revisions persist one client-encrypted Directus message ID."""

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin
from backend.core.api.app.services.directus.chat_methods import ChatMethods


def ciphertext(fill: int) -> str:
    return base64.b64encode(bytes([fill]) * 32).decode("ascii")


# contract-test: direct surface=rest_api assertions=chat-queued-followups.editing.stable-revision,chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_revision_sends_only_client_ciphertext_with_same_id(monkeypatch):
    execute = AsyncMock(return_value={
        "status": "staged", "queue_revision": 2, "stage_token": "a" * 32,
        "previous_encrypted_content": ciphertext(1),
        "previous_encrypted_pii_mappings": None,
    })
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    cache = SimpleNamespace(delete=AsyncMock())
    methods = ChatMethods(SimpleNamespace(cache=cache))

    result = await methods.revise_queued_message_ciphertext(
        "chat-1", "owner-1", "message-1", ciphertext(2), None, 1,
    )

    assert result["queue_revision"] == 2
    operation, body = execute.await_args.args
    assert operation == "revise_queued_message_ciphertext"
    assert body["message_id"] == "message-1"
    assert body["hashed_user_id"] == hashlib.sha256(b"owner-1").hexdigest()
    assert body["encrypted_content"] == ciphertext(2)
    assert body["encrypted_pii_mappings"] is None
    assert body["queue_mode"] == "follow_up"
    assert len(body["stage_token"]) == 32
    cache.delete.assert_not_awaited()  # Staged bytes are invisible to sync.

    await methods.revise_queued_message_ciphertext(
        "chat-1", "owner-1", "message-1", ciphertext(2), None, 1,
        stage_token="e" * 32,
    )
    assert execute.await_args.args[1]["stage_token"] == "e" * 32


# contract-test: direct surface=rest_api assertions=chat-queued-followups.editing.stable-revision
@pytest.mark.asyncio
async def test_commit_publishes_staged_ciphertext_and_invalidates_read_cache(monkeypatch):
    execute = AsyncMock(return_value={"status": "updated", "queue_revision": 2, "messages_v": 5})
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    cache = SimpleNamespace(delete=AsyncMock())
    methods = ChatMethods(SimpleNamespace(cache=cache))

    result = await methods.commit_queued_message_revision(
        "chat-1", "owner-1", "message-1", 1, "a" * 32,
    )

    assert result["status"] == "updated"
    operation, body = execute.await_args.args
    assert operation == "commit_queued_message_revision"
    assert body["stage_token"] == "a" * 32
    cache.delete.assert_awaited_once_with("chat:chat-1:messages")


# contract-test: direct surface=rest_api assertions=chat-queued-followups.editing.stable-revision
@pytest.mark.asyncio
async def test_vault_ciphertext_is_rejected_before_directus(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    methods = ChatMethods(SimpleNamespace(cache=SimpleNamespace(delete=AsyncMock())))

    with pytest.raises(ValueError, match="Vault ciphertext"):
        await methods.revise_queued_message_ciphertext(
            "chat-1", "owner-1", "message-1", "vault:v1:server", None, 1,
        )
    execute.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_processing_receipt_uses_same_message_id_and_revision(monkeypatch):
    execute = AsyncMock(return_value={"status": "started", "messages_v": 6})
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    methods = ChatMethods(SimpleNamespace(cache=SimpleNamespace(delete=AsyncMock())))

    result = await methods.mark_queued_message_started(
        "chat-1", "owner-1", "message-1", 2, "task-1", "steer",
    )

    assert result["status"] == "started"
    operation, body = execute.await_args.args
    assert operation == "mark_queued_message_started"
    assert body["message_id"] == "message-1"
    assert body["queue_revision"] == 2
    assert body["mode"] == "steer"

    await methods.mark_queued_message_started(
        "chat-1", "owner-1", "message-1", 2, "task-1", "follow_up",
        recovery_preflight_id="preflight-1", recovery_task_id="task-1",
        expected_inference_commitment="a" * 64,
    )
    assert execute.await_args.args[1]["expected_inference_commitment"] == "a" * 64


# contract-test: direct surface=rest_api assertions=chat-queued-followups.editing.stable-revision,chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_sync_snapshot_replaces_ciphertext_in_place_after_commit():
    redis = SimpleNamespace(eval=AsyncMock(return_value=1), delete=AsyncMock())

    class Cache(ChatCacheMixin):
        @property
        async def client(self):
            return redis

    cache = Cache()
    cache.set_chat_version_component = AsyncMock(return_value=True)

    assert await cache.replace_sync_message_revision(
        "owner-1", "chat-1", "message-1", 1,
        ciphertext(2), None, 2, messages_v=5,
    )
    args = redis.eval.await_args.args
    assert args[1:4] == (1, "user:owner-1:chat:chat-1:messages:sync", "message-1")
    assert args[4:] == (1, ciphertext(2), "", 2, "follow_up")
    redis.delete.assert_not_awaited()
    cache.set_chat_version_component.assert_awaited_once_with("owner-1", "chat-1", "messages_v", 5)


# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_initial_queued_marker_updates_sync_snapshot_without_new_message():
    redis = SimpleNamespace(eval=AsyncMock(return_value=1), delete=AsyncMock())

    class Cache(ChatCacheMixin):
        @property
        async def client(self):
            return redis

    cache = Cache()
    cache.set_chat_version_component = AsyncMock(return_value=True)

    assert await cache.mark_sync_message_queued(
        "owner-1", "chat-1", "message-1", 1, "steer", 5,
    )
    args = redis.eval.await_args.args
    assert args[1:] == (1, "user:owner-1:chat:chat-1:messages:sync", "message-1", 1, "steer")
    redis.delete.assert_not_awaited()
    cache.set_chat_version_component.assert_awaited_once_with("owner-1", "chat-1", "messages_v", 5)


# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_paused_receipt_is_same_id_and_refreshes_sync_cache(monkeypatch):
    execute = AsyncMock(return_value={
        "status": "paused", "queue_revision": 2, "queue_mode": "steer",
        "reason": "queue_lost", "messages_v": 7,
    })
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    cache = SimpleNamespace(delete=AsyncMock(), mark_sync_message_paused=AsyncMock(return_value=True))
    methods = ChatMethods(SimpleNamespace(cache=cache))

    receipt = await methods.mark_queued_message_paused(
        "chat-1", "owner-1", "message-1", 2, "queue_lost", queue_mode="steer",
    )
    assert receipt["status"] == "paused"
    operation, body = execute.await_args.args
    assert operation == "mark_queued_message_paused"
    assert body["message_id"] == "message-1"
    assert body["hashed_user_id"] == hashlib.sha256(b"owner-1").hexdigest()
    cache.mark_sync_message_paused.assert_awaited_once_with(
        "owner-1", "chat-1", "message-1", 2, "queue_lost", 7,
        queue_mode="steer",
    )


# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_consumed_steer_failure_pauses_exact_task_and_invalidates_sync(monkeypatch):
    execute = AsyncMock(return_value={
        "status": "paused", "messages_v": 8,
        "messages": [{"message_id": "message-1", "queue_revision": 2,
                      "queue_mode": "steer", "pause_reason": "dispatch_failed"}],
    })
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    cache = SimpleNamespace(delete=AsyncMock(), delete_sync_messages_history=AsyncMock())
    methods = ChatMethods(SimpleNamespace(cache=cache))

    receipt = await methods.pause_consumed_steers_for_task(
        "chat-1", "owner-1", "task-1", hashed_team_id="team-hash",
    )
    assert receipt["status"] == "paused"
    assert execute.await_args.args == (
        "pause_consumed_steers_for_task", {
            "protocol_version": 1, "chat_id": "chat-1",
            "hashed_user_id": hashlib.sha256(b"owner-1").hexdigest(),
            "hashed_team_id": "team-hash", "task_id": "task-1",
        },
    )
    cache.delete.assert_awaited_once_with("chat:chat-1:messages")
    cache.delete_sync_messages_history.assert_awaited_once_with("owner-1", "chat-1")


# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_pending_snapshot_requests_only_owner_scoped_metadata(monkeypatch):
    execute = AsyncMock(return_value={"status": "found", "messages": [], "truncated": False})
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    methods = ChatMethods(SimpleNamespace(cache=SimpleNamespace()))

    snapshot = await methods.list_pending_queued_messages("chat-1", "owner-1", limit=25)
    assert snapshot["status"] == "found"
    operation, body = execute.await_args.args
    assert operation == "list_pending_queued_messages"
    assert body == {
        "protocol_version": 1, "chat_id": "chat-1",
        "hashed_user_id": hashlib.sha256(b"owner-1").hexdigest(),
        "hashed_team_id": None, "limit": 25,
    }


# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_fresh_epoch_one_outbox_release_uses_exact_owner_and_ids(monkeypatch):
    execute = AsyncMock(return_value={"status": "released"})
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    methods = ChatMethods(SimpleNamespace(cache=SimpleNamespace()))

    receipt = await methods.release_inference_outbox("preflight-1", "task-1", "outbox-1", "owner-1")
    assert receipt["status"] == "released"
    assert execute.await_args.args == (
        "release_inference_outbox",
        {
            "protocol_version": 1,
            "preflight_id": "preflight-1",
            "inference_task_id": "task-1",
            "outbox_id": "outbox-1",
            "hashed_user_id": hashlib.sha256(b"owner-1").hexdigest(),
        },
    )
