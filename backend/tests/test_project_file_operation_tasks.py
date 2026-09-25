"""Callback tests for Project file-operation wait notifications."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.tasks import project_file_operation_tasks as task_module


class FakeOperationService:
    mark_calls: list[dict[str, Any]] = []

    def __init__(self, _cache_service: object) -> None:
        pass

    async def get_job(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "chat_id": "chat-1",
            "episode_id": "episode-1",
            "email_due_at": 100,
            "pause_at": 300,
        }

    async def mark_email_sent(self, **kwargs: Any) -> bool:
        self.mark_calls.append(kwargs)
        return True


class FakeEncryptionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def decrypt_with_user_key(self, encrypted_email: str, vault_key_id: str) -> str:
        self.calls.append((encrypted_email, vault_key_id))
        return "recipient@example.test"


class FakeCache:
    def __init__(self, chat_metadata: Any = None) -> None:
        self.chat_metadata = chat_metadata
        self.calls: list[str] = []

    async def get(self, key: str) -> Any:
        self.calls.append(key)
        return self.chat_metadata


class FakeTask:
    def __init__(self, directus_service: object, *, chat_metadata: Any = None) -> None:
        self.cache_service = FakeCache(chat_metadata)
        self.directus_service = directus_service
        self.encryption_service = FakeEncryptionService()
        self.email_template_service = object()
        self.initialized = False

    async def initialize_services(self) -> None:
        self.initialized = True


class FakeDirectus:
    def __init__(self, chats: list[dict[str, Any]], *, chat_lookup_error: Exception | None = None) -> None:
        self.chats = chats
        self.chat_lookup_error = chat_lookup_error
        self.calls: list[tuple[str, dict[str, Any], bool, bool]] = []

    async def get_items(
        self,
        collection: str,
        *,
        params: dict[str, Any],
        no_cache: bool = False,
        admin_required: bool = False,
    ) -> list[dict[str, Any]]:
        self.calls.append((collection, params, no_cache, admin_required))
        if collection == "chats":
            if self.chat_lookup_error:
                raise self.chat_lookup_error
            return self.chats
        assert collection == "directus_users"
        return [{
            "id": "user-1",
            "language": "en",
            "darkmode": False,
            "vault_key_id": "vault-1",
            "encrypted_notification_email": "encrypted-email",
            "email_notifications_enabled": True,
            "email_notification_preferences": {"aiResponses": True},
        }]


@pytest.fixture(autouse=True)
def patch_operation_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeOperationService.mark_calls = []
    monkeypatch.setattr(task_module, "ProjectFileOperationService", FakeOperationService)
    monkeypatch.setattr(task_module.time, "time", lambda: 200)


# contract-test: supporting surface=cli assertions=projects.files.wait-email,projects.files.wait-deadlines
@pytest.mark.asyncio
async def test_wait_notification_skips_deleted_chat_before_email_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directus = FakeDirectus(chats=[])
    task = FakeTask(directus)

    async def unexpected_send(**_kwargs: Any) -> tuple[bool, str]:
        raise AssertionError("deleted chat must not send a wait notification")

    monkeypatch.setattr(task_module, "send_email_once", unexpected_send)

    sent = await task_module._project_file_operation_wait_notification(
        task,
        user_id="user-1",
        operation_id="operation-1",
        episode_id="episode-1",
    )

    assert sent is False
    assert directus.calls == [(
        "chats",
        {"fields": "id", "filter": {"id": {"_eq": "chat-1"}}, "limit": 1},
        True,
        True,
    )]
    assert task.encryption_service.calls == []
    assert FakeOperationService.mark_calls == []


# contract-test: supporting surface=cli assertions=projects.files.wait-email,projects.files.wait-deadlines
@pytest.mark.asyncio
async def test_wait_notification_skips_chat_with_deletion_tombstone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directus = FakeDirectus(chats=[{"id": "chat-1"}])
    task = FakeTask(directus, chat_metadata={"id": "chat-1", "deleted": True})

    async def unexpected_send(**_kwargs: Any) -> tuple[bool, str]:
        raise AssertionError("deleted chat must not send a wait notification")

    monkeypatch.setattr(task_module, "send_email_once", unexpected_send)

    sent = await task_module._project_file_operation_wait_notification(
        task,
        user_id="user-1",
        operation_id="operation-1",
        episode_id="episode-1",
    )

    assert sent is False
    assert task.cache_service.calls == ["chat:chat-1:metadata"]
    assert directus.calls == []
    assert task.encryption_service.calls == []
    assert FakeOperationService.mark_calls == []


# contract-test: supporting surface=cli assertions=projects.files.wait-email,projects.files.wait-deadlines
@pytest.mark.asyncio
async def test_wait_notification_fails_closed_on_chat_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directus = FakeDirectus(chats=[], chat_lookup_error=RuntimeError("lookup failed"))
    task = FakeTask(directus)

    async def unexpected_send(**_kwargs: Any) -> tuple[bool, str]:
        raise AssertionError("unverified chat must not send a wait notification")

    monkeypatch.setattr(task_module, "send_email_once", unexpected_send)

    sent = await task_module._project_file_operation_wait_notification(
        task,
        user_id="user-1",
        operation_id="operation-1",
        episode_id="episode-1",
    )

    assert sent is False
    assert len(directus.calls) == 1
    assert task.encryption_service.calls == []
    assert FakeOperationService.mark_calls == []


# contract-test: supporting surface=cli assertions=projects.files.wait-email,projects.files.wait-deadlines
@pytest.mark.asyncio
async def test_wait_notification_existing_chat_keeps_email_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directus = FakeDirectus(chats=[{"id": "chat-1"}])
    task = FakeTask(directus)
    send_calls: list[dict[str, Any]] = []

    async def record_send(**kwargs: Any) -> tuple[bool, str]:
        send_calls.append(kwargs)
        return True, "sent"

    monkeypatch.setattr(task_module, "send_email_once", record_send)

    sent = await task_module._project_file_operation_wait_notification(
        task,
        user_id="user-1",
        operation_id="operation-1",
        episode_id="episode-1",
    )

    assert sent is True
    assert directus.calls[0] == (
        "chats",
        {"fields": "id", "filter": {"id": {"_eq": "chat-1"}}, "limit": 1},
        True,
        True,
    )
    assert directus.calls[1][0] == "directus_users"
    assert task.encryption_service.calls == [("encrypted-email", "vault-1")]
    assert FakeOperationService.mark_calls == [{
        "user_id": "user-1",
        "operation_id": "operation-1",
        "episode_id": "episode-1",
        "now": 200,
    }]
    assert len(send_calls) == 1
