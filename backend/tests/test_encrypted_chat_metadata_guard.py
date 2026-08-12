"""
Regression tests for encrypted chat metadata WebSocket storage guards.

These tests exercise the backend boundary that accepts client-encrypted chat
messages and metadata. A stale client can generate ciphertext with the wrong
chat key; the server must fail closed before anything is persisted.
"""

import asyncio
import sys
import types
from types import SimpleNamespace

cache_module = types.ModuleType("backend.core.api.app.services.cache")
cache_module.CacheService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_module)

directus_package = types.ModuleType("backend.core.api.app.services.directus")
directus_package.__path__ = []
directus_module = types.ModuleType("backend.core.api.app.services.directus.directus")
directus_module.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus", directus_package)
sys.modules.setdefault("backend.core.api.app.services.directus.directus", directus_module)

encryption_module = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_module.EncryptionService = object
sys.modules.setdefault("backend.core.api.app.utils.encryption", encryption_module)

connection_manager_module = types.ModuleType(
    "backend.core.api.app.routes.connection_manager"
)
connection_manager_module.ConnectionManager = object
sys.modules.setdefault(
    "backend.core.api.app.routes.connection_manager", connection_manager_module
)

if "backend.core.api.app.tasks.celery_config" not in sys.modules:
    tasks_module = types.ModuleType("backend.core.api.app.tasks")
    tasks_module.__path__ = []
    celery_config_module = types.ModuleType("backend.core.api.app.tasks.celery_config")
    celery_config_module.app = SimpleNamespace(send_task=lambda *args, **kwargs: None)
    sys.modules["backend.core.api.app.tasks"] = tasks_module
    sys.modules["backend.core.api.app.tasks.celery_config"] = celery_config_module

persistence_tasks_module = types.ModuleType(
    "backend.core.api.app.tasks.persistence_tasks"
)


async def _default_persist_encrypted_chat_metadata(*_args, **_kwargs) -> bool:
    return True


persistence_tasks_module._async_persist_encrypted_chat_metadata = (
    _default_persist_encrypted_chat_metadata
)
sys.modules.setdefault(
    "backend.core.api.app.tasks.persistence_tasks", persistence_tasks_module
)

if "redis" not in sys.modules:
    redis_stub = types.ModuleType("redis")
    redis_asyncio_stub = types.ModuleType("redis.asyncio")
    redis_asyncio_stub.Redis = object
    redis_stub.asyncio = redis_asyncio_stub
    redis_stub.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception)
    sys.modules["redis"] = redis_stub
    sys.modules["redis.asyncio"] = redis_asyncio_stub


def _handler_module():
    from backend.core.api.app.routes.handlers.websocket_handlers import (  # noqa: PLC0415
        encrypted_chat_metadata_handler,
    )

    return encrypted_chat_metadata_handler


async def _handle_encrypted_chat_metadata(**kwargs):
    from backend.core.api.app.routes.handlers.websocket_handlers.encrypted_chat_metadata_handler import (  # noqa: PLC0415
        handle_encrypted_chat_metadata,
    )

    await handle_encrypted_chat_metadata(**kwargs)


class FakeManager:
    def __init__(self) -> None:
        self.personal_messages: list[tuple[dict, str, str]] = []
        self.broadcasts: list[tuple[dict, str, str | None]] = []

    async def send_personal_message(
        self, message: dict, user_id: str, device_fingerprint_hash: str
    ) -> None:
        self.personal_messages.append((message, user_id, device_fingerprint_hash))

    async def broadcast_to_user(
        self, message: dict, user_id: str, exclude_device_hash: str | None = None
    ) -> None:
        self.broadcasts.append((message, user_id, exclude_device_hash))


class FakeCacheService:
    async def get_chat_list_item_data(self, user_id: str, chat_id: str):
        return None

    async def update_chat_list_item_field(
        self, user_id: str, chat_id: str, field: str, value: str
    ) -> bool:
        raise AssertionError("mismatched key payload must not update cache")


class FakeRotationCacheService:
    async def get_chat_list_item_data(self, user_id: str, chat_id: str):
        return SimpleNamespace(encrypted_chat_key="existing-key-a")

    async def update_chat_list_item_field(
        self, user_id: str, chat_id: str, field: str, value: str
    ) -> bool:
        return True


class FakeChatService:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return True

    async def get_chat_metadata(self, chat_id: str) -> dict:
        return {
            "encrypted_chat_key": "existing-key-a",
            "messages_v": 5,
        }


class FakeDirectusService:
    def __init__(self) -> None:
        self.chat = FakeChatService()


class FakeNewChatService:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return False

    async def get_chat_metadata(self, chat_id: str) -> dict | None:
        return None


class FakeNewChatDirectusService:
    def __init__(self) -> None:
        self.chat = FakeNewChatService()


# contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
def test_mismatched_chat_key_rejects_entire_encrypted_payload(monkeypatch):
    asyncio.run(_run_mismatched_chat_key_rejects_entire_encrypted_payload(monkeypatch))


# contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
def test_incomplete_initial_chat_metadata_rejects_entire_payload(monkeypatch):
    asyncio.run(_run_incomplete_initial_chat_metadata_rejects_entire_payload(monkeypatch))


# contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
def test_explicit_chat_key_rotation_is_broadcast_with_rotation_flag(monkeypatch):
    asyncio.run(_run_explicit_chat_key_rotation_is_broadcast_with_rotation_flag(monkeypatch))


async def _run_incomplete_initial_chat_metadata_rejects_entire_payload(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="unexpected-task")

    monkeypatch.setattr(
        _handler_module().celery_app,
        "send_task",
        fake_send_task,
    )

    manager = FakeManager()
    payload = {
        "chat_id": "new-chat-123",
        "message_id": "message-123",
        "encrypted_content": "encrypted-user-message",
        "encrypted_sender_name": "sender",
        "encrypted_category": "message-category",
        "encrypted_title": "encrypted-title",
        "encrypted_chat_key": "encrypted-chat-key",
        "created_at": 1_778_686_000,
        "versions": {
            "messages_v": 1,
            "title_v": 1,
            "last_edited_overall_timestamp": 1_778_686_000,
        },
    }

    await _handle_encrypted_chat_metadata(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeNewChatDirectusService(),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=payload,
    )

    assert queued_tasks == []
    assert manager.broadcasts == []
    assert len(manager.personal_messages) == 1

    message, user_id, device_hash = manager.personal_messages[0]
    assert user_id == "user-123"
    assert device_hash == "device-123"
    assert message == {
        "type": "incomplete_chat_metadata",
        "payload": {
            "chat_id": "new-chat-123",
            "message_id": "message-123",
            "code": "incomplete_chat_metadata",
            "message": "Initial encrypted chat metadata must include title, icon, and category.",
        },
    }


async def _run_mismatched_chat_key_rejects_entire_encrypted_payload(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="unexpected-task")

    monkeypatch.setattr(
        _handler_module().celery_app,
        "send_task",
        fake_send_task,
    )

    manager = FakeManager()
    payload = {
        "chat_id": "chat-123",
        "message_id": "message-123",
        "encrypted_content": "encrypted-with-key-b",
        "encrypted_sender_name": "sender",
        "encrypted_category": "message-category",
        "encrypted_title": "title-with-key-b",
        "encrypted_icon": "icon-with-key-b",
        "encrypted_chat_category": "category-with-key-b",
        "encrypted_chat_key": "incoming-key-b",
        "created_at": 1_778_686_000,
        "versions": {
            "messages_v": 6,
            "title_v": 6,
            "last_edited_overall_timestamp": 1_778_686_000,
        },
        "message_history": [
            {
                "message_id": "history-message-1",
                "encrypted_content": "history-content-with-key-b",
            }
        ],
    }

    await _handle_encrypted_chat_metadata(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService(),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=payload,
    )

    assert queued_tasks == []
    assert manager.broadcasts == []
    assert len(manager.personal_messages) == 1

    message, user_id, device_hash = manager.personal_messages[0]
    assert user_id == "user-123"
    assert device_hash == "device-123"
    assert message == {
        "type": "chat_key_mismatch",
        "payload": {
            "chat_id": "chat-123",
            "message_id": "message-123",
            "code": "chat_key_mismatch",
            "message": "Chat encryption key mismatch. Reload the chat key and retry.",
        },
    }


async def _run_explicit_chat_key_rotation_is_broadcast_with_rotation_flag(monkeypatch):
    persisted_payloads: list[dict] = []

    async def fake_persist(
        chat_id: str,
        encrypted_metadata: dict,
        task_id: str,
        hashed_user_id: str,
        user_id: str,
    ) -> bool:
        persisted_payloads.append(dict(encrypted_metadata))
        return True

    monkeypatch.setattr(
        _handler_module(),
        "_async_persist_encrypted_chat_metadata",
        fake_persist,
    )

    manager = FakeManager()
    await _handle_encrypted_chat_metadata(
        websocket=None,
        manager=manager,
        cache_service=FakeRotationCacheService(),
        directus_service=FakeDirectusService(),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload={
            "chat_id": "chat-rotation",
            "encrypted_chat_key": "rotated-key-b",
            "allow_chat_key_rotation": True,
            "chat_key_rotation_reason": "hidden_chat",
            "versions": {
                "messages_v": 6,
                "title_v": 6,
                "last_edited_overall_timestamp": 1_778_686_000,
            },
        },
    )

    assert persisted_payloads
    assert persisted_payloads[0]["encrypted_chat_key"] == "rotated-key-b"
    assert persisted_payloads[0]["allow_chat_key_rotation"] is True
    assert len(manager.broadcasts) == 1
    message, user_id, excluded_device = manager.broadcasts[0]
    assert user_id == "user-123"
    assert excluded_device == "device-123"
    assert message == {
        "type": "encrypted_chat_metadata",
        "payload": {
            "chat_id": "chat-rotation",
            "versions": {"messages_v": 6, "title_v": 6, "last_edited_overall_timestamp": 1_778_686_000},
            "encrypted_chat_key": "rotated-key-b",
            "allow_chat_key_rotation": True,
            "chat_key_rotation_reason": "hidden_chat",
        },
    }
