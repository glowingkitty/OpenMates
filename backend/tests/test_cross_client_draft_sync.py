"""Cross-client encrypted draft protocol regression tests.

These tests pin the existing WebSocket draft lifecycle and the explicit
authoritative-deletion contract used by non-web clients. Draft payloads are
opaque ciphertext; no server-side test or implementation decrypts them.
"""

from types import SimpleNamespace
import hashlib

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.draft_update_handler import (
    handle_update_draft,
)
from backend.core.api.app.routes.handlers.websocket_handlers.delete_draft_handler import (
    handle_delete_draft,
)
from backend.core.api.app.routes.handlers.websocket_handlers.get_draft_versions_handler import (
    get_authoritative_user_draft,
    handle_get_draft_versions,
)
from backend.core.api.app.routes.handlers.websocket_handlers.phased_sync_handler import (
    _apply_authoritative_draft_metadata,
    _authoritative_chat_reconciliation,
    _build_draft_only_phase2_wrapper,
    _handle_phase2_sync,
    _phase2_metadata_is_current,
)
from backend.core.api.app.routes.chats import get_draft
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin


class _Manager:
    def __init__(self) -> None:
        self.sent = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.sent.append(message)

    async def broadcast_to_user(self, message, user_id, exclude_device_hash):
        self.broadcasts.append(message)


class _WebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_json(self, message) -> None:
        self.sent.append(message)


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


@pytest.mark.anyio
async def test_update_draft_replaces_ideabucket_processing_window_payload(monkeypatch) -> None:
    manager = _Manager()
    websocket = _WebSocket()
    captured_windows = []

    monkeypatch.setattr(
        "backend.core.api.app.routes.handlers.websocket_handlers.draft_update_handler.celery_app_instance",
        SimpleNamespace(send_task=lambda **_kwargs: None),
    )

    class Cache:
        async def increment_user_draft_version(self, user_id, chat_id):
            return 6

        async def update_user_draft_in_cache(self, user_id, chat_id, encrypted_md, draft_v, *, encrypted_draft_preview):
            return True

        async def update_user_draft_metadata_in_cache(self, user_id, chat_id, **metadata):
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
            "server_vault_encrypted_processing_payload": "server-cipher-v7",
            "client_encrypted_future_user_message": "client-cipher-v7",
            "client_encrypted_ideabucket_system_event": "system-cipher-v7",
            "payload_hash": "hash-v7",
        },
    )]
    assert websocket.sent[0]["payload"]["processing_payload_synced"] is True


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
        },
    }
    assert manager.broadcasts[-1] == {
        "type": "draft_deleted",
        "payload": {"chat_id": "11111111-1111-4111-8111-111111111111"},
    }


@pytest.mark.anyio
async def test_get_draft_versions_does_not_turn_cache_errors_into_deletions() -> None:
    manager = _Manager()
    websocket = _WebSocket()

    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            if chat_id == "available":
                return ("cipher", 3, "preview")
            if chat_id == "deleted":
                return None
            raise RuntimeError("cache unavailable")

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
            "unavailable_chat_ids": ["unknown"],
        },
    }]
    assert manager.sent == []


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


@pytest.mark.anyio
async def test_stale_draft_cache_write_does_not_replace_newer_ciphertext() -> None:
    class Redis:
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

    assert updated is True
    assert cache.redis.data["user:user-1:chat:chat-1:draft"] == {
        "draft_v": "2",
        "encrypted_draft_md": "newer-cipher",
        "encrypted_draft_preview": "newer-preview",
    }


@pytest.mark.anyio
async def test_stale_draft_cache_write_does_not_replace_equal_version_tombstone() -> None:
    class Redis:
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

    assert updated is True
    assert cache.redis.data["user:user-1:chat:chat-1:draft"] == {
        "draft_v": "2",
        "encrypted_draft_md": "null",
        "encrypted_draft_preview": "null",
        "deleted": "true",
    }


@pytest.mark.anyio
async def test_newer_draft_cache_write_replaces_older_tombstone() -> None:
    class Redis:
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


def test_phase2_emits_explicit_authoritative_draft_deletion_fields() -> None:
    chat_details = {"id": "chat-1", "draft_v": 4, "encrypted_draft_md": "stale"}

    _apply_authoritative_draft_metadata(chat_details, None)

    assert chat_details["draft_v"] == 0
    assert chat_details["encrypted_draft_md"] is None
    assert chat_details["encrypted_draft_preview"] is None


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


@pytest.mark.anyio
async def test_phase2_synthesizes_ideabucket_draft_only_metadata() -> None:
    class Cache:
        async def get_user_draft_from_cache(self, user_id, chat_id):
            return "cipher-md", 6, "cipher-preview"

        async def get_user_draft_metadata_from_cache(self, user_id, chat_id):
            return {
                "ideabucket": True,
                "ideabucket_processing_window_id": "2026-07-18T09:00:00Z",
            }

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            return []

    wrapper = await _build_draft_only_phase2_wrapper(Cache(), Directus(), "user-1", "chat-1")

    assert wrapper["chat_details"]["ideabucket"] is True
    assert wrapper["chat_details"]["ideabucket_processing_window_id"] == "2026-07-18T09:00:00Z"
    assert "captured ideas" not in str(wrapper).lower()


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
