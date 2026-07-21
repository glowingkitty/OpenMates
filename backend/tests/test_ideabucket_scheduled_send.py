"""IdeaBucket scheduled-send service contract tests.

These tests pin the privacy boundary for background processing: the scheduler
may consume the latest Redis payload, but Directus-facing persistence receives
only client-encrypted chat history and client-encrypted system-event content.
The server-processable payload remains confined to cache/AI dispatch paths.
"""

import base64

import pytest

from backend.core.api.app.services.ideabucket_scheduled_send_service import IdeaBucketScheduledSendService


def _client_cipher(label: str) -> str:
    return base64.b64encode((label.encode("utf-8") + b"x" * 64)[:40]).decode("utf-8")


class _FakeCache:
    def __init__(self, window: dict | None) -> None:
        self.window = dict(window) if window else None
        self.saved_ai_messages = []
        self.sent_marks = []
        self.failed_marks = []
        self.deleted_drafts = []
        self.deleted_draft_versions = []
        self.active_ai_tasks = []
        self.set_versions = []

    async def lock_due_ideabucket_processing_window_in_cache(self, user_id, processing_window_id, *, now, lock_token):
        if not self.window:
            return None
        if self.window.get("status") == "sent":
            return dict(self.window)
        if self.window.get("scheduled_send_at") > now:
            return None
        self.window["status"] = "processing"
        self.window["lock_token"] = lock_token
        return dict(self.window)

    async def save_chat_message_and_update_versions(self, *, user_id, chat_id, message_data):
        self.saved_ai_messages.append(message_data)
        return {"messages_v": 8, "last_edited_overall_timestamp": message_data.created_at}

    async def mark_ideabucket_processing_window_sent_in_cache(
        self,
        user_id,
        processing_window_id,
        *,
        lock_token,
        user_message_id,
        system_event_id,
        sent_at,
    ):
        self.sent_marks.append((user_message_id, system_event_id, sent_at))
        if not self.window or self.window.get("lock_token") != lock_token:
            return False
        self.window.update(
            {
                "status": "sent",
                "user_message_id": user_message_id,
                "system_event_id": system_event_id,
                "sent_at": sent_at,
            }
        )
        self.window.pop("lock_token", None)
        return True

    async def mark_ideabucket_processing_window_failed_in_cache(
        self,
        user_id,
        processing_window_id,
        *,
        lock_token,
        failed_at,
        error_code,
    ):
        self.failed_marks.append((failed_at, error_code))
        if self.window:
            self.window.update({"status": "failed", "failed_at": failed_at, "error_code": error_code})
            self.window.pop("lock_token", None)
        return True

    async def delete_user_draft_from_cache(self, *, user_id, chat_id):
        self.deleted_drafts.append((user_id, chat_id))
        return True

    async def delete_user_draft_version_from_chat_versions(self, *, user_id, chat_id):
        self.deleted_draft_versions.append((user_id, chat_id))
        return True

    async def set_active_ai_task(self, chat_id, task_id):
        self.active_ai_tasks.append((chat_id, task_id))
        return True

    async def set_chat_version_component(self, user_id, chat_id, component, value):
        self.set_versions.append((user_id, chat_id, component, value))
        return True


def _window(**overrides) -> dict:
    payload = {
        "processing_window_id": "window-1",
        "chat_id": "chat-1",
        "version": 2,
        "scheduled_send_at": 100,
        "status": "active",
        "server_vault_encrypted_processing_payload": "server-cache-only-cipher",
        "client_encrypted_future_user_message": _client_cipher("future-user-message"),
        "client_encrypted_ideabucket_system_event": _client_cipher("system-event"),
        "payload_hash": "hash-v2",
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
async def test_scheduled_send_persists_only_client_encrypted_payloads_and_dispatches_ai() -> None:
    cache = _FakeCache(_window())
    persisted_user_messages = []
    persisted_system_events = []
    provenance_updates = []
    ai_dispatches = []
    deleted_directus_drafts = []
    persisted_chat_metadata = []

    async def persist_user(payload):
        persisted_user_messages.append(payload)

    async def persist_system(payload):
        persisted_system_events.append(payload)

    async def persist_chat(payload):
        persisted_chat_metadata.append(payload)
        return True

    async def mark_provenance(payload):
        provenance_updates.append(payload)

    async def dispatch_ai(payload):
        ai_dispatches.append(payload)
        return "ai-task-1"

    async def delete_processed_draft(payload):
        deleted_directus_drafts.append(payload)
        return True

    result = await IdeaBucketScheduledSendService(
        cache_service=cache,
        persist_user_message=persist_user,
        persist_system_event=persist_system,
        persist_chat_metadata=persist_chat,
        mark_chat_provenance=mark_provenance,
        dispatch_ai=dispatch_ai,
        delete_processed_draft=delete_processed_draft,
    ).process_due_window(user_id="user-1", processing_window_id="window-1", now=101)

    assert result["status"] == "sent"
    assert persisted_user_messages[0]["encrypted_content"] == _window()["client_encrypted_future_user_message"]
    assert persisted_system_events[0]["encrypted_content"] == _window()["client_encrypted_ideabucket_system_event"]
    assert persisted_system_events[0]["user_message_id"] == result["user_message_id"]
    assert persisted_chat_metadata == [{
        "id": "chat-1",
        "hashed_user_id": persisted_user_messages[0]["hashed_user_id"],
        "messages_v": 9,
        "title_v": 0,
        "metadata_v": 0,
        "last_edited_overall_timestamp": 101,
        "unread_count": 0,
        "created_at": 101,
        "updated_at": 101,
        "last_message_timestamp": 101,
    }]
    assert provenance_updates == [{
        "chat_id": "chat-1",
        "ideabucket": True,
        "ideabucket_processing_window_id": "window-1",
        "ideabucket_triggered_at": 101,
    }]
    assert ai_dispatches[0]["server_vault_encrypted_processing_payload"] == "server-cache-only-cipher"
    assert cache.saved_ai_messages[0].encrypted_content == "server-cache-only-cipher"
    assert "server-cache-only-cipher" not in str(persisted_user_messages + persisted_system_events + provenance_updates)
    assert cache.deleted_drafts == [("user-1", "chat-1")]
    assert cache.deleted_draft_versions == [("user-1", "chat-1")]
    assert cache.set_versions == [("user-1", "chat-1", "messages_v", 9)]
    assert deleted_directus_drafts == [{"user_id": "user-1", "chat_id": "chat-1"}]
    assert cache.active_ai_tasks == [("chat-1", "ai-task-1")]


@pytest.mark.anyio
async def test_scheduled_send_duplicate_trigger_is_idempotent() -> None:
    cache = _FakeCache(_window(status="sent", user_message_id="user-msg-1", system_event_id="system-msg-1"))
    persisted_user_messages = []

    result = await IdeaBucketScheduledSendService(
        cache_service=cache,
        persist_user_message=lambda payload: persisted_user_messages.append(payload),
    ).process_due_window(user_id="user-1", processing_window_id="window-1", now=101)

    assert result == {
        "status": "already_sent",
        "processing_window_id": "window-1",
        "chat_id": "chat-1",
        "user_message_id": "user-msg-1",
        "system_event_id": "system-msg-1",
    }
    assert persisted_user_messages == []
    assert cache.saved_ai_messages == []


@pytest.mark.anyio
async def test_scheduled_send_not_due_does_not_consume_payload() -> None:
    cache = _FakeCache(_window(scheduled_send_at=200))

    result = await IdeaBucketScheduledSendService(cache_service=cache).process_due_window(
        user_id="user-1",
        processing_window_id="window-1",
        now=199,
    )

    assert result == {"status": "not_due", "processing_window_id": "window-1"}
    assert cache.window["status"] == "active"
    assert cache.saved_ai_messages == []


@pytest.mark.anyio
async def test_scheduled_send_failure_keeps_window_retryable() -> None:
    cache = _FakeCache(_window())

    async def persist_user(_payload):
        raise RuntimeError("directus unavailable")

    result = await IdeaBucketScheduledSendService(
        cache_service=cache,
        persist_user_message=persist_user,
    ).process_due_window(user_id="user-1", processing_window_id="window-1", now=101)

    assert result == {"status": "failed", "processing_window_id": "window-1", "error_code": "processing_failed"}
    assert cache.window["status"] == "failed"
    assert cache.window["error_code"] == "processing_failed"
    assert cache.sent_marks == []
