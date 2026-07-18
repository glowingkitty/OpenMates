"""Cross-client encrypted draft protocol regression tests.

These tests pin the existing WebSocket draft lifecycle and the explicit
authoritative-deletion contract used by non-web clients. Draft payloads are
opaque ciphertext; no server-side test or implementation decrypts them.
"""

from types import SimpleNamespace

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
    _phase2_metadata_is_current,
)


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
async def test_update_draft_acknowledges_sender_and_broadcasts_only_ciphertext() -> None:
    manager = _Manager()
    websocket = _WebSocket()

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
    assert "plaintext" not in str(websocket.sent + manager.broadcasts).lower()


@pytest.mark.anyio
async def test_update_draft_broadcasts_ideabucket_metadata_without_plaintext() -> None:
    manager = _Manager()
    websocket = _WebSocket()
    captured_metadata = []

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
async def test_update_draft_replaces_ideabucket_processing_window_payload() -> None:
    manager = _Manager()
    websocket = _WebSocket()
    captured_windows = []

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

    class Cache:
        async def delete_user_draft_from_cache(self, user_id, chat_id):
            return True

        async def delete_user_draft_version_from_chat_versions(self, user_id, chat_id):
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
        async def get_items(self, collection, params):
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
        async def get_items(self, collection, params):
            return [{"encrypted_content": "persisted-cipher", "version": 7}]

    draft = await get_authoritative_user_draft(
        Cache(),
        Directus(),
        "user-1",
        "chat-1",
    )

    assert draft == ("persisted-cipher", 7, None)
    assert warmed[0][0][2:] == ("persisted-cipher", 7)


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

    wrapper = await _build_draft_only_phase2_wrapper(Cache(), "user-1", "chat-1")

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

    wrapper = await _build_draft_only_phase2_wrapper(Cache(), "user-1", "chat-1")

    assert wrapper["chat_details"]["ideabucket"] is True
    assert wrapper["chat_details"]["ideabucket_processing_window_id"] == "2026-07-18T09:00:00Z"
    assert "captured ideas" not in str(wrapper).lower()


async def _async(value):
    return value
