"""
Regression tests for encrypted chat metadata WebSocket storage guards.

These tests exercise the backend boundary that accepts client-encrypted chat
messages and metadata. A stale client can generate ciphertext with the wrong
chat key; the server must fail closed before anything is persisted.
"""

import pytest
import asyncio
from pathlib import Path
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
team_methods_module = types.ModuleType(
    "backend.core.api.app.services.directus.team_methods"
)
team_methods_module.hash_id = lambda value: f"hashed-{value}"
sys.modules.setdefault(
    "backend.core.api.app.services.directus.team_methods", team_methods_module
)

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
    tasks_module.__path__ = [str(Path(__file__).resolve().parents[1] / "core/api/app/tasks")]
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


class FakeNewChatCacheService:
    async def get_chat_list_item_data(self, user_id: str, chat_id: str):
        return None

    async def update_chat_list_item_field(
        self, user_id: str, chat_id: str, field: str, value: str
    ) -> bool:
        return True


# contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
def test_mismatched_chat_key_rejects_entire_encrypted_payload(monkeypatch):
    asyncio.run(_run_mismatched_chat_key_rejects_entire_encrypted_payload(monkeypatch))


# contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
def test_incomplete_initial_chat_metadata_rejects_entire_payload(monkeypatch):
    asyncio.run(_run_incomplete_initial_chat_metadata_rejects_entire_payload(monkeypatch))


# contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
def test_explicit_chat_key_rotation_is_broadcast_with_rotation_flag(monkeypatch):
    asyncio.run(_run_explicit_chat_key_rotation_is_broadcast_with_rotation_flag(monkeypatch))


# contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted
def test_key_only_new_chat_shell_stays_empty_for_deferred_audio_send(monkeypatch):
    asyncio.run(_run_key_only_new_chat_shell_stays_empty_for_deferred_audio_send(monkeypatch))


# contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted
def test_message_less_titled_chat_keeps_allocated_metadata_versions(monkeypatch):
    asyncio.run(_run_message_less_titled_chat_keeps_allocated_metadata_versions(monkeypatch))


async def _run_key_only_new_chat_shell_stays_empty_for_deferred_audio_send(monkeypatch):
    persisted_payloads: list[dict] = []

    async def fake_persist(
        chat_id: str,
        encrypted_metadata: dict,
        task_id: str,
        hashed_user_id: str,
        user_id: str,
        hashed_team_id: str | None = None,
    ) -> bool:
        persisted_payloads.append(dict(encrypted_metadata))
        return True

    monkeypatch.setattr(
        _handler_module(),
        "_async_persist_encrypted_chat_metadata",
        fake_persist,
    )

    await _handle_encrypted_chat_metadata(
        websocket=None,
        manager=FakeManager(),
        cache_service=FakeNewChatCacheService(),
        directus_service=FakeNewChatDirectusService(),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload={
            "chat_id": "new-audio-chat",
            "encrypted_chat_key": "encrypted-chat-key",
            "created_at": 1_778_686_000,
            "versions": {},
        },
    )

    assert len(persisted_payloads) == 1
    assert persisted_payloads[0]["messages_v"] == 0
    assert persisted_payloads[0]["title_v"] == 0
    assert persisted_payloads[0]["metadata_v"] == 0
    assert persisted_payloads[0]["last_message_timestamp"] is None
    assert "encrypted_title" not in persisted_payloads[0]


async def _run_message_less_titled_chat_keeps_allocated_metadata_versions(monkeypatch):
    persisted_payloads: list[dict] = []

    async def fake_persist(
        _chat_id: str,
        encrypted_metadata: dict,
        _task_id: str,
        _hashed_user_id: str,
        _user_id: str,
        _hashed_team_id: str | None = None,
    ) -> bool:
        persisted_payloads.append(dict(encrypted_metadata))
        return True

    async def fake_allocate(*_args, **_kwargs) -> dict:
        return {"messages_v": 0, "title_v": 1, "metadata_v": 1}

    monkeypatch.setattr(_handler_module(), "_async_persist_encrypted_chat_metadata", fake_persist)
    monkeypatch.setattr(_handler_module(), "allocate_chat_metadata_versions", fake_allocate)

    await _handle_encrypted_chat_metadata(
        websocket=None,
        manager=FakeManager(),
        cache_service=FakeNewChatCacheService(),
        directus_service=FakeNewChatDirectusService(),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload={
            "chat_id": "new-titled-chat",
            "encrypted_chat_key": "encrypted-chat-key",
            "encrypted_title": "encrypted-title",
            "encrypted_icon": "encrypted-icon",
            "encrypted_chat_category": "encrypted-category",
            "created_at": 1_778_686_000,
            "versions": {},
        },
    )

    assert persisted_payloads[0]["encrypted_title"] == "encrypted-title"
    assert persisted_payloads[0]["title_v"] == 1
    assert persisted_payloads[0]["metadata_v"] == 1
    assert persisted_payloads[0]["last_message_timestamp"] == 1_778_686_000


# contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted
def test_history_injection_preserves_encrypted_pii_mappings_without_positional_shift(monkeypatch):
    asyncio.run(_run_history_injection_preserves_encrypted_pii_mappings_without_positional_shift(monkeypatch))


async def _run_history_injection_preserves_encrypted_pii_mappings_without_positional_shift(monkeypatch):
    queued_tasks: list[tuple[str, list, dict, str | None]] = []

    def fake_send_task(
        name: str,
        args: list | None = None,
        kwargs: dict | None = None,
        queue: str | None = None,
    ):
        queued_tasks.append((name, args or [], kwargs or {}, queue))
        return SimpleNamespace(id="history-task")

    monkeypatch.setattr(
        _handler_module().celery_app,
        "send_task",
        fake_send_task,
    )

    manager = FakeManager()
    await _handle_encrypted_chat_metadata(
        websocket=None,
        manager=manager,
        cache_service=FakeNewChatCacheService(),
        directus_service=FakeNewChatDirectusService(),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload={
            "chat_id": "new-chat-123",
            "message_id": "message-123",
            "encrypted_content": "current-message-content",
            "encrypted_sender_name": "sender",
            "encrypted_category": "message-category",
            "encrypted_title": "encrypted-title",
            "encrypted_icon": "encrypted-icon",
            "encrypted_chat_category": "encrypted-chat-category",
            "encrypted_chat_key": "encrypted-chat-key",
            "created_at": 1_778_686_000,
            "versions": {
                "messages_v": 1,
                "title_v": 1,
                "last_edited_overall_timestamp": 1_778_686_000,
            },
            "message_history": [
                {
                    "message_id": "history-message-1",
                    "encrypted_content": "history-content",
                    "encrypted_sender_name": "history-sender",
                    "encrypted_category": "history-category",
                    "encrypted_model_name": "history-model",
                    "encrypted_pii_mappings": "history-pii-ciphertext",
                    "created_at": 1_778_685_999,
                    "task_id": "legacy-history-task-id",
                }
            ],
        },
    )

    history_task = next(task for task in queued_tasks if task[2].get("message_id") == "history-message-1")
    assert history_task[0] == "app.tasks.persistence_tasks.persist_new_chat_message"
    assert history_task[1] == []
    assert history_task[3] == "persistence"
    assert history_task[2] == {
        "message_id": "history-message-1",
        "chat_id": "new-chat-123",
        "hashed_user_id": "user-hash-123",
        "role": "user",
        "encrypted_sender_name": "history-sender",
        "encrypted_category": "history-category",
        "encrypted_model_name": "history-model",
        "encrypted_content": "history-content",
        "created_at": 1_778_685_999,
        "new_chat_messages_version": None,
        "new_last_edited_overall_timestamp": None,
        "encrypted_chat_key": "encrypted-chat-key",
        "user_id": "user-123",
        "encrypted_pii_mappings": "history-pii-ciphertext",
    }


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
        hashed_team_id: str | None = None,
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


async def _handle_voice_call_chat_prepare(**kwargs):
    allowed = {"manager", "directus_service", "user_id", "user_id_hash", "device_fingerprint_hash", "payload"}
    await _handler_module().handle_voice_call_chat_prepare(**{
        key: value for key, value in kwargs.items() if key in allowed
    })


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
def test_voice_bootstrap_acks_only_after_atomic_commit_and_never_uses_generic_persistence(monkeypatch):
    async def run():
        from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
        manager = FakeManager()
        calls = []

        async def register(_self, **kwargs):
            assert manager.personal_messages == []
            calls.append(kwargs)
            return {"chat_id": "draft-123", "created": False}

        async def forbidden(*args, **kwargs):
            raise AssertionError("bootstrap must not use generic persistence")

        monkeypatch.setattr(ChatRecoveryService, "register_personal_chat_draft", register)
        monkeypatch.setattr(_handler_module(), "_async_persist_encrypted_chat_metadata", forbidden)
        await _handle_voice_call_chat_prepare(
            websocket=None, manager=manager, cache_service=object(), directus_service=object(),
            encryption_service=object(), user_id="user-123", user_id_hash="trusted-owner",
            device_fingerprint_hash="device-123", payload={"chat_id": "draft-123",
            "encrypted_chat_key": "wrapped-key", "created_at": 100, "voice_call_bootstrap": True},
        )
        assert calls == [{"hashed_user_id": "trusted-owner", "chat_id": "draft-123",
                          "encrypted_chat_key": "wrapped-key", "created_at": 100}]
        assert manager.personal_messages == [({"type": "encrypted_metadata_stored", "payload": {
            "chat_id": "draft-123", "message_id": None, "status": "stored", "voice_call_bootstrap": True,
        }}, "user-123", "device-123")]
        assert manager.broadcasts == []
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
def test_voice_bootstrap_rejects_extra_or_missing_fields_and_never_falls_back(monkeypatch):
    async def run():
        from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
        calls = []

        async def forbidden(*args, **kwargs):
            calls.append(True)
            raise AssertionError("malformed bootstrap must not reach storage")

        monkeypatch.setattr(ChatRecoveryService, "register_personal_chat_draft", forbidden)
        monkeypatch.setattr(_handler_module(), "_async_persist_encrypted_chat_metadata", forbidden)
        base = {"chat_id": "draft-123", "encrypted_chat_key": "wrapped-key", "created_at": 100,
                "voice_call_bootstrap": True}
        variants = [dict(base, **fields) for fields in [
            {"versions": {}}, {"encrypted_title": "title"}, {"team_id": "team"},
            {"user_id": "other"}, {"voice_call_bootstrap": False}, {"voice_call_bootstrap": 1},
        ]]
        variants.extend({key: value for key, value in base.items() if key != missing}
                        for missing in ["encrypted_chat_key", "voice_call_bootstrap"])
        for payload in variants:
            manager = FakeManager()
            await _handle_voice_call_chat_prepare(
                websocket=None, manager=manager, cache_service=object(), directus_service=object(),
                encryption_service=object(), user_id="user-123", user_id_hash="trusted-owner",
                device_fingerprint_hash="device-123", payload=payload,
            )
            assert [message[0]["type"] for message in manager.personal_messages] == ["error"]
        assert calls == []
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
def test_voice_bootstrap_storage_failure_never_acknowledges_or_falls_back(monkeypatch):
    async def run():
        from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError, ChatRecoveryService

        async def fenced(*args, **kwargs):
            raise ChatRecoveryProtocolError(404, "chat_not_found")

        async def forbidden(*args, **kwargs):
            raise AssertionError("failed bootstrap must not use generic persistence")

        monkeypatch.setattr(ChatRecoveryService, "register_personal_chat_draft", fenced)
        monkeypatch.setattr(_handler_module(), "_async_persist_encrypted_chat_metadata", forbidden)
        manager = FakeManager()
        await _handle_voice_call_chat_prepare(
            websocket=None, manager=manager, cache_service=object(), directus_service=object(),
            encryption_service=object(), user_id="user-123", user_id_hash="trusted-owner",
            device_fingerprint_hash="device-123", payload={"chat_id": "draft-123",
            "encrypted_chat_key": "wrapped-key", "created_at": 100, "voice_call_bootstrap": True},
        )
        assert [message[0]["type"] for message in manager.personal_messages] == ["error"]
        error = manager.personal_messages[0][0]["payload"]
        assert error["chat_id"] == "draft-123"
        assert error["voice_call_bootstrap"] is True
        assert error["code"] == "voice_call_bootstrap_failed"
        assert "chat_not_found" not in str(error)
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
def test_generic_metadata_rejects_reserved_voice_bootstrap_without_storage(monkeypatch):
    async def run():
        from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
        calls = []

        async def forbidden(*args, **kwargs):
            calls.append(True)
            raise AssertionError("reserved flag must not reach any persistence")

        monkeypatch.setattr(ChatRecoveryService, "register_personal_chat_draft", forbidden)
        monkeypatch.setattr(_handler_module(), "_async_persist_encrypted_chat_metadata", forbidden)
        manager = FakeManager()
        await _handle_encrypted_chat_metadata(
            websocket=None, manager=manager, cache_service=object(), directus_service=object(),
            encryption_service=object(), user_id="user-123", user_id_hash="trusted-owner",
            device_fingerprint_hash="device-123", payload={"chat_id": "draft-123",
            "encrypted_chat_key": "wrapped-key", "created_at": 100, "voice_call_bootstrap": True},
        )
        assert [message[0]["type"] for message in manager.personal_messages] == ["error"]
        assert calls == []
    asyncio.run(run())


@pytest.fixture(autouse=True)
def _cleanup_authority_for_existing_flow_fixtures(monkeypatch):
    """Existing fixtures model a successful separate cleanup exclusion RPC.

    Atomic eligibility/failure behavior is exercised by cleanup admission and
    Directus transaction tests; these cases retain their original boundaries.
    """
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    execute = ChatRecoveryService.execute

    async def with_cleanup_authority(self, operation, data):
        if operation == "update_call_cleanup_candidate":
            assert data["mode"] in {"disqualify", "start", "finish"}
            return {"eligible": False, "disqualified": True}
        return await execute(self, operation, data)

    monkeypatch.setattr(ChatRecoveryService, "execute", with_cleanup_authority)
