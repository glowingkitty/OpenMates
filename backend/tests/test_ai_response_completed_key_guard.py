"""
Regression tests for assistant-response ciphertext key validation.

The assistant completion path persists client-encrypted ciphertext after the AI
stream finishes. It must enforce the same key consistency guarantees as user
message metadata storage, otherwise a stale secondary device can win the
first-writer race and make only the follow-up assistant message undecryptable.
"""

import asyncio
import base64
import hashlib
from types import SimpleNamespace

from backend.core.api.app.routes.handlers.websocket_handlers import (
    ai_response_completed_handler,
)
from backend.core.api.app.routes.handlers.websocket_handlers.ai_response_completed_handler import (
    handle_ai_response_completed,
)
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError


class FakeManager:
    def __init__(self) -> None:
        self.personal_messages: list[tuple[dict, str, str]] = []

    async def send_personal_message(
        self, message: dict, user_id: str, device_fingerprint_hash: str
    ) -> None:
        self.personal_messages.append((message, user_id, device_fingerprint_hash))


class FakeCacheService:
    async def get(self, key: str):
        return None


class FakeCutoverController:
    epoch = 0
    authoritative_calls: list[bool] = []
    authorization_result = {"authorized": False}
    authorization_error: Exception | None = None
    authorization_calls: list[str] = []
    authorized_identities: set[str] | None = None
    events: list[str] = []

    def __init__(self, *_args) -> None:
        pass

    async def get_epoch(self, *, authoritative: bool = False) -> int:
        self.authoritative_calls.append(authoritative)
        return self.epoch

    async def authorize_legacy_completion(self, task_identity: str) -> dict:
        self.authorization_calls.append(task_identity)
        self.events.append("authorize")
        if self.authorization_error:
            raise self.authorization_error
        if self.authorized_identities is not None:
            return {"authorized": task_identity in self.authorized_identities}
        return self.authorization_result


def reset_cutover_controller(*, epoch: int, authorized: bool = False) -> None:
    FakeCutoverController.epoch = epoch
    FakeCutoverController.authoritative_calls = []
    FakeCutoverController.authorization_result = {
        "authorized": authorized,
    }
    FakeCutoverController.authorization_error = None
    FakeCutoverController.authorization_calls = []
    FakeCutoverController.authorized_identities = None
    FakeCutoverController.events = []


class FakeChatService:
    def __init__(self, authoritative_fingerprint: str) -> None:
        self.authoritative_fingerprint = authoritative_fingerprint

    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return True

    async def get_chat_metadata(self, chat_id: str) -> dict:
        return {
            "id": chat_id,
            "hashed_user_id": "user-hash-123",
            "encrypted_title": make_ciphertext(self.authoritative_fingerprint),
            "messages_v": 3,
        }

    async def get_messages_for_chats(self, chat_ids: list[str]) -> dict[str, list[str]]:
        return {
            chat_ids[0]: [
                {
                    "message_id": "existing-message-1",
                    "encrypted_content": make_ciphertext(self.authoritative_fingerprint),
                }
            ]
        }


class FakeDirectusService:
    def __init__(self, authoritative_fingerprint: str) -> None:
        self.chat = FakeChatService(authoritative_fingerprint)


def make_ciphertext(fingerprint: str) -> str:
    raw = b"OM" + bytes.fromhex(fingerprint) + (b"0" * 12) + b"ciphertext"
    return base64.b64encode(raw).decode("ascii")


def make_payload(fingerprint: str, user_message_id: str | None = None) -> dict:
    message = {
        "message_id": "assistant-123",
        "chat_id": "chat-123",
        "role": "assistant",
        "encrypted_content": make_ciphertext(fingerprint),
        "encrypted_category": make_ciphertext(fingerprint),
        "encrypted_model_name": make_ciphertext(fingerprint),
        "created_at": 1_779_399_620,
    }
    if user_message_id:
        message["user_message_id"] = user_message_id
    return {
        "chat_id": "chat-123",
        "message": message,
        "versions": {"messages_v": 4},
    }


def test_ai_response_completed_rejects_mismatched_ciphertext_fingerprint(monkeypatch):
    asyncio.run(_run_rejects_mismatched_ciphertext_fingerprint(monkeypatch))


async def _run_rejects_mismatched_ciphertext_fingerprint(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="unexpected-task")

    monkeypatch.setattr(
        ai_response_completed_handler.celery_app,
        "send_task",
        fake_send_task,
    )
    monkeypatch.setattr(
        ai_response_completed_handler,
        "ChatRecoveryCutoverController",
        FakeCutoverController,
    )
    reset_cutover_controller(epoch=0)

    manager = FakeManager()
    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("0f0165e4"),
    )

    assert queued_tasks == []
    assert FakeCutoverController.authoritative_calls == []
    assert manager.personal_messages == [
        (
            {
                "type": "chat_key_mismatch",
                "payload": {
                    "chat_id": "chat-123",
                    "message_id": "assistant-123",
                    "code": "chat_key_mismatch",
                    "message": "Chat encryption key mismatch. Reload the chat key and retry.",
                },
            },
            "user-123",
            "device-123",
        )
    ]


def test_ai_response_completed_accepts_matching_ciphertext_fingerprint(monkeypatch):
    asyncio.run(_run_accepts_matching_ciphertext_fingerprint(monkeypatch))


async def _run_accepts_matching_ciphertext_fingerprint(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr(
        ai_response_completed_handler.celery_app,
        "send_task",
        fake_send_task,
    )
    monkeypatch.setattr(
        ai_response_completed_handler,
        "ChatRecoveryCutoverController",
        FakeCutoverController,
    )
    reset_cutover_controller(epoch=0)

    manager = FakeManager()
    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("1a5b3b7c"),
    )

    assert len(queued_tasks) == 1
    assert FakeCutoverController.authoritative_calls == [True]
    assert queued_tasks[0][0] == "app.tasks.persistence_tasks.persist_ai_response_to_directus"
    assert queued_tasks[0][2] == "persistence"
    assert manager.personal_messages == [
        (
            {
                "type": "ai_response_storage_confirmed",
                "payload": {
                    "message_id": "assistant-123",
                    "chat_id": "chat-123",
                    "task_id": "task-123",
                },
            },
            "user-123",
            "device-123",
        )
    ]


def test_epoch_one_authorized_legacy_completion_queues_persistence(monkeypatch):
    asyncio.run(_run_epoch_one_authorized_legacy_completion(monkeypatch))


async def _run_epoch_one_authorized_legacy_completion(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        FakeCutoverController.events.append("dispatch")
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr(ai_response_completed_handler.celery_app, "send_task", fake_send_task)
    monkeypatch.setattr(
        ai_response_completed_handler,
        "ChatRecoveryCutoverController",
        FakeCutoverController,
    )
    reset_cutover_controller(epoch=1, authorized=True)
    manager = FakeManager()

    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("1a5b3b7c"),
    )

    assert len(queued_tasks) == 1
    assert FakeCutoverController.authorization_calls == ["assistant-123"]
    assert FakeCutoverController.events == ["authorize", "dispatch"]
    assert FakeCutoverController.authoritative_calls == [True]


def test_epoch_one_legacy_completion_uses_user_message_identity(monkeypatch):
    asyncio.run(_run_epoch_one_legacy_completion_uses_user_message_identity(monkeypatch))


async def _run_epoch_one_legacy_completion_uses_user_message_identity(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []
    user_message_id = "user-message-123"
    legacy_task_identity = hashlib.sha256(
        f"user-123:chat-123:{user_message_id}".encode()
    ).hexdigest()

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        FakeCutoverController.events.append("dispatch")
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr(ai_response_completed_handler.celery_app, "send_task", fake_send_task)
    monkeypatch.setattr(
        ai_response_completed_handler,
        "ChatRecoveryCutoverController",
        FakeCutoverController,
    )
    reset_cutover_controller(epoch=1)
    FakeCutoverController.authorized_identities = {legacy_task_identity}
    manager = FakeManager()

    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("1a5b3b7c", user_message_id=user_message_id),
    )

    assert len(queued_tasks) == 1
    assert FakeCutoverController.authorization_calls == ["assistant-123", legacy_task_identity]
    assert FakeCutoverController.events == ["authorize", "authorize", "dispatch"]
    assert manager.personal_messages[0][0]["type"] == "ai_response_storage_confirmed"


def test_epoch_one_server_trigger_completion_uses_prefixed_user_message_identity(monkeypatch):
    asyncio.run(_run_epoch_one_server_trigger_completion_uses_prefixed_user_message_identity(monkeypatch))


async def _run_epoch_one_server_trigger_completion_uses_prefixed_user_message_identity(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []
    user_message_id = "webhook-message-123"
    user_turn_identity = hashlib.sha256(
        f"user-123:chat-123:{user_message_id}".encode()
    ).hexdigest()
    server_trigger_identity = f"server-trigger:{user_turn_identity}"

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        FakeCutoverController.events.append("dispatch")
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr(ai_response_completed_handler.celery_app, "send_task", fake_send_task)
    monkeypatch.setattr(
        ai_response_completed_handler,
        "ChatRecoveryCutoverController",
        FakeCutoverController,
    )
    reset_cutover_controller(epoch=1)
    FakeCutoverController.authorized_identities = {server_trigger_identity}
    manager = FakeManager()

    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("1a5b3b7c", user_message_id=user_message_id),
    )

    assert len(queued_tasks) == 1
    assert FakeCutoverController.authorization_calls == [
        "assistant-123",
        user_turn_identity,
        server_trigger_identity,
    ]
    assert FakeCutoverController.events == ["authorize", "authorize", "authorize", "dispatch"]
    assert manager.personal_messages[0][0]["type"] == "ai_response_storage_confirmed"


def test_epoch_one_unauthorized_legacy_completion_is_rejected(monkeypatch):
    asyncio.run(_run_epoch_one_unauthorized_legacy_completion(monkeypatch))


async def _run_epoch_one_unauthorized_legacy_completion(monkeypatch):
    queued_tasks: list[object] = []
    monkeypatch.setattr(
        ai_response_completed_handler.celery_app,
        "send_task",
        lambda *args, **kwargs: queued_tasks.append((args, kwargs)),
    )
    monkeypatch.setattr(
        ai_response_completed_handler,
        "ChatRecoveryCutoverController",
        FakeCutoverController,
    )
    reset_cutover_controller(epoch=1)
    FakeCutoverController.authorization_error = ChatRecoveryProtocolError(
        410, "legacy_completion_expired"
    )
    manager = FakeManager()

    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("1a5b3b7c"),
    )

    assert queued_tasks == []
    assert FakeCutoverController.authorization_calls == ["assistant-123"]
    assert manager.personal_messages[0][0]["payload"]["code"] == "recovery_persistence_required"


def test_malformed_or_invalid_completion_never_authorizes(monkeypatch):
    asyncio.run(_run_malformed_or_invalid_completion_never_authorizes(monkeypatch))


async def _run_malformed_or_invalid_completion_never_authorizes(monkeypatch):
    monkeypatch.setattr(
        ai_response_completed_handler,
        "ChatRecoveryCutoverController",
        FakeCutoverController,
    )
    reset_cutover_controller(epoch=1, authorized=True)
    manager = FakeManager()
    malformed = make_payload("1a5b3b7c")
    del malformed["message"]["message_id"]
    invalid = make_payload("1a5b3b7c")
    invalid["message"]["role"] = "user"

    for payload in (None, malformed, invalid):
        await handle_ai_response_completed(
            websocket=None,
            manager=manager,
            cache_service=FakeCacheService(),
            directus_service=FakeDirectusService("1a5b3b7c"),
            encryption_service=None,
            user_id="user-123",
            user_id_hash="user-hash-123",
            device_fingerprint_hash="device-123",
            payload=payload,
        )

    assert FakeCutoverController.authorization_calls == []
    assert FakeCutoverController.authoritative_calls == []
