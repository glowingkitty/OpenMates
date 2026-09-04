"""Cross-client encrypted draft protocol regression tests.

These tests pin the existing WebSocket draft lifecycle and the explicit
authoritative-deletion contract used by non-web clients. Draft payloads are
opaque ciphertext; no server-side test or implementation decrypts them.
"""

import hashlib
import importlib
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.tests.s3_service_test_support import ensure_s3_dependencies


if "redis.asyncio" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedis:
        pass

    redis_asyncio_module.Redis = FakeRedis
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

if "aiohttp" not in sys.modules:
    aiohttp_module = types.ModuleType("aiohttp")
    aiohttp_module.ClientSession = object
    sys.modules["aiohttp"] = aiohttp_module

sys.modules.setdefault("regex", re)
ensure_s3_dependencies()

if "backend.core.api.app.tasks.celery_config" not in sys.modules:
    tasks_package = types.ModuleType("backend.core.api.app.tasks")
    tasks_package.__path__ = [str(Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "tasks")]

    class _CeleryAppStub:
        def send_task(self, *_args, **_kwargs):
            return None

        def task(self, *_args, **_kwargs):
            return lambda func: func

    async def _missing_worker_cache_service():
        raise AssertionError("worker cache service is not used by these unit tests")

    celery_config_module = types.ModuleType("backend.core.api.app.tasks.celery_config")
    celery_config_module.app = _CeleryAppStub()
    celery_config_module.get_worker_cache_service = _missing_worker_cache_service
    sys.modules.setdefault("backend.core.api.app.tasks", tasks_package)
    sys.modules["backend.core.api.app.tasks.celery_config"] = celery_config_module
    setattr(tasks_package, "celery_config", celery_config_module)
    setattr(importlib.import_module("backend.core.api.app"), "tasks", tasks_package)

from backend.core.api.app.routes.handlers.websocket_handlers.draft_update_handler import (  # noqa: E402
    handle_update_draft,
)
from backend.core.api.app.routes.handlers.websocket_handlers.delete_draft_handler import (  # noqa: E402
    handle_delete_draft,
)
from backend.core.api.app.routes.handlers.websocket_handlers.get_draft_versions_handler import (  # noqa: E402
    get_authoritative_user_draft,
    handle_get_draft_versions,
)
from backend.core.api.app.routes.handlers.websocket_handlers.offline_sync_handler import (  # noqa: E402
    handle_sync_offline_changes,
)
from backend.core.api.app.routes.handlers.websocket_handlers.phased_sync_handler import (  # noqa: E402
    _apply_authoritative_draft_metadata,
    _authoritative_chat_reconciliation,
    _build_draft_only_phase2_wrapper,
    _handle_phase2_sync,
    _phase2_metadata_is_current,
)
from backend.core.api.app.routes.chats import get_draft  # noqa: E402
from backend.core.api.app.schemas.chat import CachedChatVersions  # noqa: E402
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin  # noqa: E402
from backend.core.api.app.tasks.persistence_tasks import _async_persist_user_draft_task  # noqa: E402


class _Manager:
    def __init__(self) -> None:
        self.sent = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.sent.append(message)

    async def broadcast_to_user(self, message=None, user_id=None, exclude_device_hash=None, message_content=None):
        self.broadcasts.append(message if message is not None else message_content)


class _WebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_json(self, message) -> None:
        self.sent.append(message)


class _DraftWriteRedis:
    async def eval(self, _script, _key_count, draft_key, versions_key, field, draft_version, encrypted_md, encrypted_preview, _draft_ttl, _versions_ttl):
        draft = self.data.setdefault(draft_key, {})
        dedicated_version = int(draft.get("draft_v", 0))
        general_version = int(self.data.get(versions_key, {}).get(field, 0))
        incoming_version = int(draft_version)
        if dedicated_version > incoming_version or general_version > incoming_version:
            return 0
        if draft.get("deleted") == "true" and dedicated_version >= incoming_version:
            return 0
        draft.update({
            "draft_v": str(incoming_version),
            "encrypted_draft_md": encrypted_md,
            "encrypted_draft_preview": encrypted_preview,
        })
        if encrypted_md != "null":
            draft["deleted"] = "false"
        self.data.setdefault(versions_key, {})[field] = str(incoming_version)
        return 1


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_update_draft_acknowledges_sender_and_broadcasts_only_ciphertext(monkeypatch) -> None:
    manager = _Manager()
    websocket = _WebSocket()
    sent_tasks = []

    class CeleryApp:
        def send_task(self, **kwargs):
            sent_tasks.append(kwargs)

    monkeypatch.setattr(
        "backend.core.api.app.routes.handlers.websocket_handlers.draft_update_handler.celery_app_instance",
        CeleryApp(),
    )

    class Cache:
        async def increment_user_draft_version(self, user_id, chat_id):
            return 4

        async def update_user_draft_in_cache(self, user_id, chat_id, encrypted_md, draft_v, *, encrypted_draft_preview):
            assert encrypted_md == "cipher-md"
            assert encrypted_draft_preview == "cipher-preview"
            return True

        async def update_user_draft_metadata_in_cache(self, *args, **kwargs):
            return True

        async def check_chat_exists_for_user(self, user_id, chat_id):
            return False

        async def add_chat_to_ids_versions(self, user_id, chat_id, timestamp):
            return True

        async def get_chat_last_edited_overall_timestamp(self, user_id, chat_id):
            return 1234

    directus = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=lambda chat_id, user_id: _async(False),
            get_chat_metadata=lambda chat_id: _async(None),
        )
    )

    await handle_update_draft(
        websocket=websocket,
        manager=manager,
        cache_service=Cache(),
        directus_service=directus,
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "encrypted_draft_md": "cipher-md",
            "encrypted_draft_preview": "cipher-preview",
        },
    )

    assert websocket.sent == [{
        "type": "draft_update_receipt",
        "payload": {
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "draft_v": 4,
            "success": True,
        },
    }]
    assert manager.sent == []
    assert manager.broadcasts[0]["data"] == {
        "encrypted_draft_md": "cipher-md",
        "encrypted_draft_preview": "cipher-preview",
    }
    assert sent_tasks == [{
        "name": "app.tasks.persistence_tasks.persist_user_draft",
        "kwargs": {
            "hashed_user_id": hashlib.sha256("user-1".encode()).hexdigest(),
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "encrypted_draft_content": "cipher-md",
            "draft_version": 4,
        },
        "queue": "persistence",
    }]
    assert "plaintext" not in str(websocket.sent + manager.broadcasts).lower()


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_superseded_update_draft_still_acknowledges_sender_without_publishing(monkeypatch) -> None:
    manager = _Manager()
    websocket = _WebSocket()
    sent_tasks = []

    monkeypatch.setattr(
        "backend.core.api.app.routes.handlers.websocket_handlers.draft_update_handler.celery_app_instance",
        SimpleNamespace(send_task=lambda **kwargs: sent_tasks.append(kwargs)),
    )

    class Cache:
        async def increment_user_draft_version(self, user_id, chat_id):
            return 6

        async def update_user_draft_in_cache(self, user_id, chat_id, encrypted_md, draft_v, *, encrypted_draft_preview):
            assert encrypted_md == "stale-cipher-md"
            assert encrypted_draft_preview == "stale-cipher-preview"
            assert draft_v == 6
            return False

    directus = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=lambda chat_id, user_id: _async(True),
            get_chat_metadata=lambda chat_id: _async({"id": chat_id}),
        )
    )

    await handle_update_draft(
        websocket=websocket,
        manager=manager,
        cache_service=Cache(),
        directus_service=directus,
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "encrypted_draft_md": "stale-cipher-md",
            "encrypted_draft_preview": "stale-cipher-preview",
        },
    )

    assert websocket.sent == [{
        "type": "draft_update_receipt",
        "payload": {
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "draft_v": 6,
            "success": True,
            "superseded": True,
        },
    }]
    assert manager.sent == []
    assert manager.broadcasts == []
    assert sent_tasks == []


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_update_draft_broadcasts_ideabucket_metadata_without_plaintext(monkeypatch) -> None:
    manager = _Manager()
    websocket = _WebSocket()
    captured_metadata = []

    monkeypatch.setattr(
        "backend.core.api.app.routes.handlers.websocket_handlers.draft_update_handler.celery_app_instance",
        SimpleNamespace(send_task=lambda **_kwargs: None),
    )

    class Cache:
        async def increment_user_draft_version(self, user_id, chat_id):
            return 5

        async def update_user_draft_in_cache(self, user_id, chat_id, encrypted_md, draft_v, *, encrypted_draft_preview):
            return True

        async def update_user_draft_metadata_in_cache(self, user_id, chat_id, **metadata):
            captured_metadata.append(metadata)
            return True

        async def check_chat_exists_for_user(self, user_id, chat_id):
            return True

        async def get_chat_last_edited_overall_timestamp(self, user_id, chat_id):
            return 1234

    directus = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=lambda chat_id, user_id: _async(True),
            get_chat_metadata=lambda chat_id: _async({"id": chat_id}),
        )
    )

    await handle_update_draft(
        websocket=websocket,
        manager=manager,
        cache_service=Cache(),
        directus_service=directus,
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "encrypted_draft_md": "cipher-md",
            "encrypted_draft_preview": "cipher-preview",
            "ideabucket": True,
            "ideabucket_processing_window_id": "2026-07-18T09:00:00Z",
        },
    )

    assert captured_metadata == [{
        "ideabucket": True,
        "ideabucket_processing_window_id": "2026-07-18T09:00:00Z",
    }]
    assert manager.broadcasts[0]["data"] == {
        "encrypted_draft_md": "cipher-md",
        "encrypted_draft_preview": "cipher-preview",
        "ideabucket": True,
        "ideabucket_processing_window_id": "2026-07-18T09:00:00Z",
    }
    assert websocket.sent[0]["payload"]["ideabucket"] is True
    assert "captured ideas" not in str(websocket.sent + manager.broadcasts).lower()


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_update_draft_replaces_ideabucket_processing_window_payload(monkeypatch) -> None:
    manager = _Manager()
    websocket = _WebSocket()
    captured_metadata = []
    captured_windows = []
    sent_tasks = []

    monkeypatch.setattr(
        "backend.core.api.app.routes.handlers.websocket_handlers.draft_update_handler.celery_app_instance",
        SimpleNamespace(send_task=lambda **kwargs: sent_tasks.append(kwargs)),
    )

    class Cache:
        async def increment_user_draft_version(self, user_id, chat_id):
            return 6

        async def update_user_draft_in_cache(self, user_id, chat_id, encrypted_md, draft_v, *, encrypted_draft_preview):
            return True

        async def update_user_draft_metadata_in_cache(self, user_id, chat_id, **metadata):
            captured_metadata.append(metadata)
            return True

        async def replace_ideabucket_processing_window_in_cache(self, user_id, processing_window_id, **payload):
            captured_windows.append((user_id, processing_window_id, payload))
            return True

        async def check_chat_exists_for_user(self, user_id, chat_id):
            return True

        async def get_chat_last_edited_overall_timestamp(self, user_id, chat_id):
            return 1234

    directus = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=lambda chat_id, user_id: _async(True),
            get_chat_metadata=lambda chat_id: _async({"id": chat_id}),
        )
    )

    await handle_update_draft(
        websocket=websocket,
        manager=manager,
        cache_service=Cache(),
        directus_service=directus,
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "encrypted_draft_md": "cipher-md",
            "encrypted_draft_preview": "cipher-preview",
            "ideabucket": True,
            "ideabucket_processing_window_id": "2026-07-18T09:00:00Z",
            "ideabucket_processing_version": 7,
            "encrypted_chat_key": "wrapped-chat-key-v7",
            "scheduled_send_at": 123456,
            "server_vault_encrypted_processing_payload": "server-cipher-v7",
            "client_encrypted_future_user_message": "client-cipher-v7",
            "client_encrypted_ideabucket_system_event": "system-cipher-v7",
            "payload_hash": "hash-v7",
        },
    )

    assert captured_windows == [(
        "user-1",
        "2026-07-18T09:00:00Z",
        {
            "version": 7,
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "scheduled_send_at": 123456,
            "encrypted_chat_key": "wrapped-chat-key-v7",
            "server_vault_encrypted_processing_payload": "server-cipher-v7",
            "client_encrypted_future_user_message": "client-cipher-v7",
            "client_encrypted_ideabucket_system_event": "system-cipher-v7",
            "payload_hash": "hash-v7",
        },
    )]
    assert captured_metadata == [{
        "ideabucket": True,
        "ideabucket_processing_window_id": "2026-07-18T09:00:00Z",
        "encrypted_chat_key": "wrapped-chat-key-v7",
    }]
    assert sent_tasks == [{
        "name": "app.tasks.persistence_tasks.persist_user_draft",
        "kwargs": {
            "hashed_user_id": hashlib.sha256("user-1".encode()).hexdigest(),
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "encrypted_draft_content": "cipher-md",
            "draft_version": 6,
            "user_id": "user-1",
            "ideabucket_processing_window_id": "2026-07-18T09:00:00Z",
        },
        "queue": "persistence",
    }]
    assert websocket.sent[0]["payload"]["processing_payload_synced"] is True


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_late_ideabucket_draft_persistence_skips_sent_window(monkeypatch) -> None:
    closed = []

    class Cache:
        async def get_ideabucket_processing_window_from_cache(self, user_id, processing_window_id):
            assert user_id == "user-1"
            assert processing_window_id == "window-1"
            return {"status": "sent", "chat_id": "chat-1"}

        async def close(self):
            closed.append(True)

    class Directus:
        def __init__(self):
            raise AssertionError("stale sent-window drafts must not reach Directus")

    monkeypatch.setattr("backend.core.api.app.tasks.persistence_tasks.CacheService", Cache)
    monkeypatch.setattr("backend.core.api.app.tasks.persistence_tasks.DirectusService", Directus)

    await _async_persist_user_draft_task(
        hashed_user_id=hashlib.sha256("user-1".encode()).hexdigest(),
        chat_id="chat-1",
        encrypted_draft_content="cipher-md",
        draft_version=6,
        task_id="task-1",
        user_id="user-1",
        ideabucket_processing_window_id="window-1",
    )

    assert closed == [True]


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_offline_draft_sync_uses_user_specific_draft_version() -> None:
    manager = _Manager()
    draft_updates = []

    class Cache:
        async def get_chat_versions(self, user_id, chat_id):
            return CachedChatVersions(
                messages_v=0,
                title_v=0,
                **{"user_draft_v:user-1": 4},
            )

        async def increment_user_draft_version(self, user_id, chat_id):
            draft_updates.append(("increment", user_id, chat_id))
            return 5

        async def update_user_draft_in_cache(self, user_id, chat_id, encrypted_md, draft_v, *, encrypted_draft_preview):
            draft_updates.append(("update", user_id, chat_id, encrypted_md, draft_v, encrypted_draft_preview))
            return True

    await handle_sync_offline_changes(
        websocket=_WebSocket(),
        manager=manager,
        cache_service=Cache(),
        directus_service=SimpleNamespace(),
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"changes": [{
            "chat_id": "chat-1",
            "type": "draft",
            "value": "cipher-md",
            "version_before_edit": 4,
            "change_id": "change-1",
        }]},
    )

    assert draft_updates[0] == ("increment", "user-1", "chat-1")
    assert draft_updates[1] == ("update", "user-1", "chat-1", "cipher-md", 5, None)
    assert len(draft_updates) == 2
    assert manager.broadcasts[0]["event"] == "chat_draft_updated"
    assert manager.broadcasts[0]["versions"] == {"draft_v": 5}
    assert "user_draft_v" not in str(manager.broadcasts[0])
    assert manager.sent[-1] == {
        "type": "offline_sync_complete",
        "payload": {"processed": 1, "conflicts": 0, "errors": 0},
    }


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
@pytest.mark.anyio
async def test_delete_draft_accepts_canonical_chat_id_and_tombstones_draft_only_chat() -> None:
    manager = _Manager()
    removed = []
    tombstones = []

    class Cache:
        async def increment_user_draft_version(self, user_id, chat_id):
            return 3

        async def tombstone_user_draft_in_cache(self, *, user_id, chat_id, draft_version):
            tombstones.append((user_id, chat_id, draft_version))
            return True

        async def remove_chat_from_ids_versions(self, user_id, chat_id):
            removed.append(chat_id)
            return True

    class Chat:
        async def check_chat_ownership(self, chat_id, user_id):
            return False

        async def get_chat_metadata(self, chat_id):
            return None

    class Directus:
        chat = Chat()

        async def get_items(self, collection, params):
            return []

    await handle_delete_draft(
        websocket=None,
        manager=manager,
        cache_service=Cache(),
        directus_service=Directus(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chat_id": "11111111-1111-4111-8111-111111111111"},
    )

    assert removed == ["11111111-1111-4111-8111-111111111111"]
    assert tombstones == [("user-1", "11111111-1111-4111-8111-111111111111", 3)]
    assert manager.sent[-1] == {
        "type": "draft_delete_receipt",
        "payload": {
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "success": True,
            "draft_v": 3,
        },
    }
    assert manager.broadcasts[-1] == {
        "type": "draft_deleted",
        "payload": {
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "draft_v": 3,
        },
    }


# contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_delete_draft_cas_rejection_preserves_newer_persisted_draft() -> None:
    manager = _Manager()

    class Cache:
        async def increment_user_draft_version(self, user_id, chat_id):
            return 3

        async def tombstone_user_draft_in_cache(self, *, user_id, chat_id, draft_version):
            return False

    class Chat:
        async def check_chat_ownership(self, chat_id, user_id):
            return False

        async def get_chat_metadata(self, chat_id):
            return None

    class Directus:
        chat = Chat()

        async def get_items(self, collection, params):
            raise AssertionError("rejected deletion must not read or delete the persisted draft")

    await handle_delete_draft(
        websocket=None,
        manager=manager,
        cache_service=Cache(),
        directus_service=Directus(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chat_id": "11111111-1111-4111-8111-111111111111"},
    )

    assert manager.sent[-1] == {
        "type": "draft_delete_receipt",
        "payload": {
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "success": False,
        },
    }
    assert manager.broadcasts == []


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_get_draft_versions_does_not_turn_cache_errors_into_deletions() -> None:
    manager = _Manager()
    websocket = _WebSocket()

    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            if chat_id == "available":
                return ("cipher", 3, "preview")
            if chat_id == "deleted":
                return (None, 4, None)
            raise RuntimeError("cache unavailable")

        async def is_user_draft_tombstoned(self, user_id, chat_id):
            return chat_id == "deleted"

        async def update_user_draft_in_cache(self, *args, **kwargs):
            return True

    class Directus:
        async def get_items(self, collection, params, **_kwargs):
            return []

    await handle_get_draft_versions(
        websocket=websocket,
        manager=manager,
        cache_service=Cache(),
        directus_service=Directus(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chats": [
            {"chat_id": "available", "client_draft_v": 2},
            {"chat_id": "deleted", "client_draft_v": 2},
            {"chat_id": "unknown", "client_draft_v": 2},
        ]},
    )

    assert websocket.sent == [{
        "type": "draft_versions_response",
        "payload": {
            "versions": {"available": 3, "deleted": 0},
            "tombstone_versions": {"deleted": 4},
            "unavailable_chat_ids": ["unknown"],
        },
    }]
    assert manager.sent == []


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_draft_cache_miss_falls_back_to_encrypted_directus_row() -> None:
    warmed = []

    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return None

        async def update_user_draft_in_cache(self, *args, **kwargs):
            warmed.append((args, kwargs))
            return True

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert kwargs == {"admin_required": True}
            return [{"encrypted_content": "persisted-cipher", "version": 7}]

    draft = await get_authoritative_user_draft(
        Cache(),
        Directus(),
        "user-1",
        "chat-1",
    )

    assert draft == ("persisted-cipher", 7, None)
    assert warmed[0][0][2:] == ("persisted-cipher", 7)


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_version_only_draft_cache_falls_back_to_encrypted_directus_row() -> None:
    warmed = []

    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return None, 8, None

        async def update_user_draft_in_cache(self, *args, **kwargs):
            warmed.append((args, kwargs))
            return True

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert collection == "drafts"
            assert kwargs == {"admin_required": True}
            return [{"encrypted_content": "persisted-cipher-v8", "version": 8}]

    draft = await get_authoritative_user_draft(
        Cache(),
        Directus(),
        "user-1",
        "chat-1",
    )

    assert draft == ("persisted-cipher-v8", 8, None)
    assert warmed[0][0][2:] == ("persisted-cipher-v8", 8)


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_empty_cached_draft_does_not_hide_persisted_ciphertext() -> None:
    warmed = []

    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return None, 2, None

        async def update_user_draft_in_cache(self, *args, **kwargs):
            warmed.append((args, kwargs))
            return True

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert kwargs == {"admin_required": True}
            assert params["filter[hashed_user_id][_eq]"] == hashlib.sha256("user-1".encode()).hexdigest()
            assert params["filter[chat_id][_eq]"] == "chat-1"
            return [{"encrypted_content": "persisted-cipher", "version": 2}]

    draft = await get_authoritative_user_draft(
        Cache(),
        Directus(),
        "user-1",
        "chat-1",
    )

    assert draft == ("persisted-cipher", 2, None)
    assert warmed[0][0][2:] == ("persisted-cipher", 2)


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_tombstoned_cached_draft_hides_stale_persisted_ciphertext() -> None:
    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return None, 3, None

        async def is_user_draft_tombstoned(self, user_id, chat_id):
            return True

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            raise AssertionError("tombstoned drafts must not fall back to Directus")

    draft = await get_authoritative_user_draft(
        Cache(),
        Directus(),
        "user-1",
        "chat-1",
    )

    assert draft is None


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_newer_persisted_draft_overrides_stale_cached_ciphertext() -> None:
    warmed = []

    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return "cached-cipher-v1", 1, "cached-preview-v1"

        async def update_user_draft_in_cache(self, *args, **kwargs):
            warmed.append((args, kwargs))
            return True

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert collection == "drafts"
            assert kwargs == {"admin_required": True}
            return [{"encrypted_content": "persisted-cipher-v2", "version": 2}]

    draft = await get_authoritative_user_draft(
        Cache(),
        Directus(),
        "user-1",
        "chat-1",
    )

    assert draft == ("persisted-cipher-v2", 2, None)
    assert warmed[0][0][2:] == ("persisted-cipher-v2", 2)


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_stale_draft_cache_write_does_not_replace_newer_ciphertext() -> None:
    class Redis(_DraftWriteRedis):
        def __init__(self) -> None:
            self.data = {
                "user:user-1:chat:chat-1:draft": {
                    "draft_v": "2",
                    "encrypted_draft_md": "newer-cipher",
                    "encrypted_draft_preview": "newer-preview",
                }
            }

        async def hget(self, key, field):
            value = self.data.get(key, {}).get(field)
            return value.encode("utf-8") if isinstance(value, str) else value

        async def hmset(self, key, mapping):
            self.data.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

        async def expire(self, key, ttl):
            return True

    class Cache(ChatCacheMixin):
        USER_DRAFT_TTL = 60
        CHAT_VERSIONS_TTL = 120

        def __init__(self) -> None:
            self.redis = Redis()

        @property
        async def client(self):
            return self.redis

    cache = Cache()

    updated = await cache.update_user_draft_in_cache(
        "user-1",
        "chat-1",
        "stale-cipher",
        1,
        encrypted_draft_preview="stale-preview",
    )

    assert updated is False
    assert cache.redis.data["user:user-1:chat:chat-1:draft"] == {
        "draft_v": "2",
        "encrypted_draft_md": "newer-cipher",
        "encrypted_draft_preview": "newer-preview",
    }


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_stale_draft_cache_write_does_not_replace_equal_version_tombstone() -> None:
    class Redis(_DraftWriteRedis):
        def __init__(self) -> None:
            self.data = {
                "user:user-1:chat:chat-1:draft": {
                    "draft_v": "2",
                    "encrypted_draft_md": "null",
                    "encrypted_draft_preview": "null",
                    "deleted": "true",
                }
            }

        async def hget(self, key, field):
            value = self.data.get(key, {}).get(field)
            return value.encode("utf-8") if isinstance(value, str) else value

        async def hmset(self, key, mapping):
            self.data.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

        async def expire(self, key, ttl):
            return True

    class Cache(ChatCacheMixin):
        USER_DRAFT_TTL = 60
        CHAT_VERSIONS_TTL = 120

        def __init__(self) -> None:
            self.redis = Redis()

        @property
        async def client(self):
            return self.redis

    cache = Cache()

    updated = await cache.update_user_draft_in_cache(
        "user-1",
        "chat-1",
        "stale-directus-cipher",
        2,
        encrypted_draft_preview="stale-directus-preview",
    )

    assert updated is False
    assert cache.redis.data["user:user-1:chat:chat-1:draft"] == {
        "draft_v": "2",
        "encrypted_draft_md": "null",
        "encrypted_draft_preview": "null",
        "deleted": "true",
    }


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_newer_draft_cache_write_replaces_older_tombstone() -> None:
    class Redis(_DraftWriteRedis):
        def __init__(self) -> None:
            self.data = {
                "user:user-1:chat:chat-1:draft": {
                    "draft_v": "2",
                    "encrypted_draft_md": "null",
                    "encrypted_draft_preview": "null",
                    "deleted": "true",
                }
            }

        async def hget(self, key, field):
            value = self.data.get(key, {}).get(field)
            return value.encode("utf-8") if isinstance(value, str) else value

        async def hmset(self, key, mapping):
            self.data.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

        async def expire(self, key, ttl):
            return True

    class Cache(ChatCacheMixin):
        USER_DRAFT_TTL = 60
        CHAT_VERSIONS_TTL = 120

        def __init__(self) -> None:
            self.redis = Redis()

        @property
        async def client(self):
            return self.redis

    cache = Cache()

    updated = await cache.update_user_draft_in_cache(
        "user-1",
        "chat-1",
        "new-cipher",
        3,
        encrypted_draft_preview="new-preview",
    )

    assert updated is True
    assert cache.redis.data["user:user-1:chat:chat-1:draft"] == {
        "draft_v": "3",
        "encrypted_draft_md": "new-cipher",
        "encrypted_draft_preview": "new-preview",
        "deleted": "false",
    }


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_session_draft_route_returns_authoritative_ciphertext() -> None:
    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            assert user_id == "user-1"
            assert chat_id == "chat-1"
            return "cipher-md", 2, "cipher-preview"

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                cache_service=Cache(),
                directus_service=SimpleNamespace(get_items=lambda *args, **kwargs: _async([])),
            )
        )
    )

    response = await get_draft("chat-1", request, SimpleNamespace(id="user-1"))

    assert response == {
        "draft": {
            "chat_id": "chat-1",
            "encrypted_draft_md": "cipher-md",
            "encrypted_draft_preview": "cipher-preview",
            "draft_v": 2,
        }
    }
    assert "plaintext" not in str(response).lower()


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_session_draft_route_prefers_newer_persisted_directus_draft() -> None:
    class Cache:
        def __init__(self):
            self.updated = []

        async def get_user_draft_from_cache(self, user_id, chat_id):
            assert user_id == "user-1"
            assert chat_id == "chat-1"
            return "stale-cache-cipher", 2, "stale-cache-preview"

        async def update_user_draft_in_cache(self, user_id, chat_id, encrypted_md, draft_v, encrypted_draft_preview=None):
            self.updated.append((user_id, chat_id, encrypted_md, draft_v, encrypted_draft_preview))
            return True

    calls = []
    cache = Cache()

    async def get_items(collection, *, params, admin_required=False):
        calls.append((collection, params, admin_required))
        return [{"encrypted_content": "persisted-cipher", "version": 3}]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                cache_service=cache,
                directus_service=SimpleNamespace(get_items=get_items),
            )
        )
    )

    response = await get_draft("chat-1", request, SimpleNamespace(id="user-1"))

    assert response == {
        "draft": {
            "chat_id": "chat-1",
            "encrypted_draft_md": "persisted-cipher",
            "encrypted_draft_preview": None,
            "draft_v": 3,
        }
    }
    assert calls == [(
        "drafts",
        {
            "filter[hashed_user_id][_eq]": hashlib.sha256("user-1".encode()).hexdigest(),
            "filter[chat_id][_eq]": "chat-1",
            "fields": "encrypted_content,version",
            "limit": 1,
        },
        True,
    )]
    assert cache.updated == [("user-1", "chat-1", "persisted-cipher", 3, None)]
    assert "plaintext" not in str(response).lower()


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_session_draft_route_prefers_newer_cache_draft_before_persistence() -> None:
    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            assert user_id == "user-1"
            assert chat_id == "chat-1"
            return "fresh-cache-cipher", 4, "fresh-cache-preview"

    async def get_items(collection, *, params, admin_required=False):
        assert collection == "drafts"
        assert params["filter[hashed_user_id][_eq]"] == hashlib.sha256("user-1".encode()).hexdigest()
        assert params["filter[chat_id][_eq]"] == "chat-1"
        assert admin_required is True
        return [{"encrypted_content": "persisted-cipher", "version": 3}]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                cache_service=Cache(),
                directus_service=SimpleNamespace(get_items=get_items),
            )
        )
    )

    response = await get_draft("chat-1", request, SimpleNamespace(id="user-1"))

    assert response == {
        "draft": {
            "chat_id": "chat-1",
            "encrypted_draft_md": "fresh-cache-cipher",
            "encrypted_draft_preview": "fresh-cache-preview",
            "draft_v": 4,
        }
    }
    assert "plaintext" not in str(response).lower()


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
def test_authoritative_reconciliation_requires_a_complete_server_set() -> None:
    partial = _authoritative_chat_reconciliation(
        client_chat_ids=["kept", "deleted"],
        server_chat_ids=["kept"],
        total_chat_count=2,
    )
    complete = _authoritative_chat_reconciliation(
        client_chat_ids=["kept", "deleted"],
        server_chat_ids=["kept"],
        total_chat_count=1,
    )

    assert partial == {"authoritative": False}
    assert complete == {
        "authoritative": True,
        "authoritative_chat_ids": ["kept"],
        "deleted_chat_ids": ["deleted"],
    }


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
def test_phase2_delta_sync_resends_newer_draft_ciphertext() -> None:
    server_versions = SimpleNamespace(
        messages_v=2,
        title_v=3,
        metadata_v=3,
    )
    chat_details = {"messages_v": 2, "draft_v": 4}

    assert not _phase2_metadata_is_current(
        {"messages_v": 2, "title_v": 3, "metadata_v": 3, "draft_v": 3},
        server_versions,
        chat_details,
    )
    assert _phase2_metadata_is_current(
        {"messages_v": 2, "title_v": 3, "metadata_v": 3, "draft_v": 4},
        server_versions,
        chat_details,
    )


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
def test_phase2_delta_sync_resends_authoritative_draft_deletion() -> None:
    server_versions = SimpleNamespace(
        messages_v=2,
        title_v=3,
        metadata_v=3,
    )
    chat_details = {"messages_v": 2, "draft_v": 0}

    assert not _phase2_metadata_is_current(
        {"messages_v": 2, "title_v": 3, "metadata_v": 3, "draft_v": 4},
        server_versions,
        chat_details,
    )


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_phase2_targeted_refresh_bypasses_delta_skip() -> None:
    manager = _Manager()

    class Cache:
        async def get_all_user_draft_chat_ids(self, user_id):
            return []

        async def get_user_draft_from_cache(self, user_id, chat_id):
            return "cipher-md", 2, "cipher-preview"

        async def get_batch_chat_versions(self, user_id, chat_ids):
            return {
                "chat-1": SimpleNamespace(
                    messages_v=0,
                    title_v=0,
                    metadata_v=0,
                )
            }

    class Directus:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                get_user_chat_count=lambda user_id, team_id=None: _async(1),
                get_core_chats_and_user_drafts_for_cache_warming=lambda user_id, limit, team_id=None: _async([
                    {
                        "chat_details": {
                            "id": "chat-1",
                            "messages_v": 0,
                            "title_v": 0,
                            "metadata_v": 0,
                            "draft_v": 2,
                        }
                    }
                ]),
            )
            self.chat_key_wrapper = SimpleNamespace(
                get_wrappers_by_hashed_chat_ids_batch=lambda hashed_chat_ids, hashed_user_id: _async([]),
            )

        async def get_items(self, collection, params, **kwargs):
            return []

    await _handle_phase2_sync(
        manager=manager,
        cache_service=Cache(),
        directus_service=Directus(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        client_chat_versions={"chat-1": {"messages_v": 0, "title_v": 0, "metadata_v": 0, "draft_v": 2}},
        client_chat_ids=["chat-1"],
        sent_embed_ids=set(),
        refresh_chat_ids=["chat-1"],
    )

    payload = manager.sent[0]["payload"]
    assert payload["chat_count"] == 1
    assert payload["chats"][0]["chat_details"]["id"] == "chat-1"
    assert payload["chats"][0]["chat_details"]["encrypted_draft_md"] == "cipher-md"


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_phase2_tombstone_suppresses_stale_directus_chat_row() -> None:
    manager = _Manager()

    class Cache:
        async def get_all_user_draft_chat_ids(self, user_id):
            return []

        async def get(self, key):
            assert key == "chat:chat-1:metadata"
            return {"id": "chat-1", "deleted": True}

    class Directus:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                get_user_chat_count=lambda user_id, team_id=None: _async(1),
                get_core_chats_and_user_drafts_for_cache_warming=lambda user_id, limit, team_id=None: _async([
                    {
                        "chat_details": {
                            "id": "chat-1",
                            "messages_v": 2,
                            "title_v": 2,
                            "metadata_v": 2,
                            "draft_v": 0,
                        }
                    }
                ]),
            )

    await _handle_phase2_sync(
        manager=manager,
        cache_service=Cache(),
        directus_service=Directus(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        client_chat_versions={"chat-1": {"messages_v": 2, "title_v": 2, "metadata_v": 2, "draft_v": 0}},
        client_chat_ids=["chat-1"],
        sent_embed_ids=set(),
    )

    payload = manager.sent[0]["payload"]
    assert payload["chats"] == []
    assert payload["chat_count"] == 0
    assert payload["total_chat_count"] == 0
    assert payload["authoritative"] is True
    assert payload["deleted_chat_ids"] == ["chat-1"]


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
@pytest.mark.anyio
async def test_phase2_metadata_only_does_not_fetch_chat_key_wrappers() -> None:
    manager = _Manager()
    wrapper_fetches = []

    class Cache:
        async def get_all_user_draft_chat_ids(self, user_id):
            return []

        async def get(self, key):
            return None

        async def get_user_draft_from_cache(self, user_id, chat_id):
            return None

        async def get_batch_chat_versions(self, user_id, chat_ids):
            return {}

    class ChatKeyWrapper:
        async def get_wrappers_by_hashed_chat_ids_batch(self, hashed_chat_ids, hashed_user_id):
            wrapper_fetches.append((hashed_chat_ids, hashed_user_id))
            return [{"id": "wrapper-1"}]

    class Directus:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                get_user_chat_count=lambda user_id, team_id=None: _async(1),
                get_core_chats_and_user_drafts_for_cache_warming=lambda user_id, limit, team_id=None: _async([
                    {
                        "chat_details": {
                            "id": "chat-1",
                            "messages_v": 1,
                            "title_v": 1,
                            "metadata_v": 1,
                            "draft_v": 0,
                        }
                    }
                ]),
            )
            self.chat_key_wrapper = ChatKeyWrapper()

        async def get_items(self, collection, params, **kwargs):
            return []

    await _handle_phase2_sync(
        manager=manager,
        cache_service=Cache(),
        directus_service=Directus(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        client_chat_versions={},
        client_chat_ids=[],
        sent_embed_ids=set(),
    )

    payload = manager.sent[0]["payload"]
    assert payload["chat_count"] == 1
    assert payload["phase"] == "phase2"
    assert "chat_key_wrappers" not in payload
    assert wrapper_fetches == []


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_phase2_emits_client_tombstone_when_deleted_chat_is_outside_result_window() -> None:
    manager = _Manager()

    class Cache:
        async def get_all_user_draft_chat_ids(self, user_id):
            return []

        async def get(self, key):
            if key == "chat:stale-deleted:metadata":
                return {"id": "stale-deleted", "deleted": True}
            return None

        async def get_user_draft_from_cache(self, user_id, chat_id):
            return None

        async def get_batch_chat_versions(self, user_id, chat_ids):
            return {}

    class Directus:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                get_user_chat_count=lambda user_id, team_id=None: _async(2),
                get_core_chats_and_user_drafts_for_cache_warming=lambda user_id, limit, team_id=None: _async([
                    {
                        "chat_details": {
                            "id": "kept-chat",
                            "messages_v": 1,
                            "title_v": 1,
                            "metadata_v": 1,
                            "draft_v": 0,
                        }
                    }
                ]),
            )
            self.chat_key_wrapper = SimpleNamespace(
                get_wrappers_by_hashed_chat_ids_batch=lambda hashed_chat_ids, hashed_user_id: _async([]),
            )

        async def get_items(self, collection, params, **kwargs):
            return []

    await _handle_phase2_sync(
        manager=manager,
        cache_service=Cache(),
        directus_service=Directus(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        client_chat_versions={},
        client_chat_ids=["kept-chat", "stale-deleted"],
        sent_embed_ids=set(),
    )

    payload = manager.sent[0]["payload"]
    assert payload["authoritative"] is False
    assert payload["deleted_chat_ids"] == ["stale-deleted"]
    assert [chat["chat_details"]["id"] for chat in payload["chats"]] == ["kept-chat"]


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
def test_phase2_emits_explicit_authoritative_draft_deletion_fields() -> None:
    chat_details = {"id": "chat-1", "draft_v": 4, "encrypted_draft_md": "stale"}

    _apply_authoritative_draft_metadata(chat_details, None)

    assert chat_details["draft_v"] == 0
    assert chat_details["encrypted_draft_md"] is None
    assert chat_details["encrypted_draft_preview"] is None


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
@pytest.mark.anyio
async def test_phase2_synthesizes_encrypted_draft_only_chat_metadata() -> None:
    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return "cipher-md", 5, "cipher-preview"

        async def get_user_draft_metadata_from_cache(self, user_id, chat_id):
            return {}

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            return []

    wrapper = await _build_draft_only_phase2_wrapper(Cache(), Directus(), "user-1", "chat-1")

    assert wrapper["chat_details"]["id"] == "chat-1"
    assert wrapper["chat_details"]["draft_v"] == 5
    assert wrapper["chat_details"]["encrypted_draft_md"] == "cipher-md"
    assert wrapper["chat_details"]["encrypted_draft_preview"] == "cipher-preview"
    assert "plaintext" not in str(wrapper).lower()


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
@pytest.mark.anyio
async def test_phase2_synthesizes_ideabucket_draft_only_metadata() -> None:
    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return "cipher-md", 6, "cipher-preview"

        async def get_user_draft_metadata_from_cache(self, user_id, chat_id):
            return {
                "ideabucket": True,
                "ideabucket_processing_window_id": "2026-07-18T09:00:00Z",
                "encrypted_chat_key": "wrapped-chat-key-v7",
            }

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            return []

    wrapper = await _build_draft_only_phase2_wrapper(Cache(), Directus(), "user-1", "chat-1")

    assert wrapper["chat_details"]["ideabucket"] is True
    assert wrapper["chat_details"]["ideabucket_processing_window_id"] == "2026-07-18T09:00:00Z"
    assert wrapper["chat_details"]["encrypted_chat_key"] == "wrapped-chat-key-v7"
    assert "captured ideas" not in str(wrapper).lower()


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
@pytest.mark.anyio
async def test_phase2_synthesizes_persisted_draft_only_metadata_after_cache_miss() -> None:
    warmed = []

    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return None

        async def update_user_draft_in_cache(self, *args, **kwargs):
            warmed.append((args, kwargs))
            return True

        async def get_user_draft_metadata_from_cache(self, user_id, chat_id):
            return {}

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert collection == "drafts"
            assert kwargs == {"admin_required": True}
            assert params["filter[chat_id][_eq]"] == "chat-1"
            return [{"encrypted_content": "persisted-cipher", "version": 2}]

    wrapper = await _build_draft_only_phase2_wrapper(Cache(), Directus(), "user-1", "chat-1")

    assert wrapper["chat_details"]["id"] == "chat-1"
    assert wrapper["chat_details"]["draft_v"] == 2
    assert wrapper["chat_details"]["encrypted_draft_md"] == "persisted-cipher"
    assert warmed[0][0][2:] == ("persisted-cipher", 2)


async def _async(value):
    return value
