# backend/tests/test_phased_sync_handler.py
"""
Regression tests for Phase 1a chat metadata assembly.

Phase 1a combines Redis list-item cache data with Directus fallback metadata.
When Redis is partially warm, missing encrypted header fields must be filled
from Directus so the client has metadata to decrypt on cold boot.
"""

from types import SimpleNamespace

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import phased_sync_handler
from backend.core.api.app.routes.handlers.websocket_handlers.phased_sync_handler import (
    _count_directus_filled_metadata_fields,
    _handle_phase1_sync,
    _is_parent_chat_details,
    _merge_partial_cache_chat_details,
    _phase1_metadata_invariant_violations,
    handle_phased_sync_request,
)


def test_phase1_partial_cache_metadata_is_filled_from_directus(doc_assert) -> None:
    doc_assert("phase1-partial-cache-metadata-fills-from-directus")
    cached_details = {
        "id": "chat-1",
        "encrypted_title": None,
        "encrypted_chat_key": "cached-key",
        "encrypted_icon": None,
        "encrypted_category": None,
        "messages_v": 0,
        "title_v": 0,
        "unread_count": 0,
    }
    directus_details = {
        "id": "chat-1",
        "encrypted_title": "directus-title",
        "encrypted_chat_key": "directus-key",
        "encrypted_icon": "directus-icon",
        "encrypted_category": "directus-category",
        "messages_v": 4,
        "title_v": 1,
        "unread_count": 2,
        "parent_id": "parent-chat-1",
        "is_sub_chat": True,
        "budget_limit": 500,
        "budget_spent": 125,
    }

    merged = _merge_partial_cache_chat_details(
        cached_details,
        directus_details,
        prefer_directus_versions=True,
    )

    assert merged["encrypted_title"] == "directus-title"
    assert merged["encrypted_icon"] == "directus-icon"
    assert merged["encrypted_category"] == "directus-category"
    assert merged["messages_v"] == 4
    assert merged["title_v"] == 1
    assert merged["unread_count"] == 0
    assert merged["encrypted_chat_key"] == "cached-key"
    assert merged["parent_id"] == "parent-chat-1"
    assert merged["is_sub_chat"] is True
    assert merged["budget_limit"] == 500
    assert merged["budget_spent"] == 125

    assert _count_directus_filled_metadata_fields(cached_details, directus_details) == 3
    assert _phase1_metadata_invariant_violations(merged) == []


def test_phase1_partial_cache_keeps_cached_versions_when_present() -> None:
    cached_details = {
        "id": "chat-1",
        "encrypted_title": None,
        "encrypted_chat_key": "cached-key",
        "messages_v": 4,
        "title_v": 1,
    }
    directus_details = {
        "id": "chat-1",
        "encrypted_title": "directus-title",
        "encrypted_chat_key": "directus-key",
        "messages_v": 5,
        "title_v": 2,
    }

    merged = _merge_partial_cache_chat_details(cached_details, directus_details)

    assert merged["encrypted_title"] == "directus-title"
    assert merged["encrypted_chat_key"] == "cached-key"
    assert merged["messages_v"] == 4
    assert merged["title_v"] == 1


def test_phase1_metadata_invariant_reports_missing_titled_header() -> None:
    violations = _phase1_metadata_invariant_violations(
        {
            "id": "chat-1",
            "encrypted_title": None,
            "encrypted_chat_key": "key",
            "encrypted_icon": "icon",
            "encrypted_category": "category",
            "title_v": 1,
        }
    )

    assert violations == ["encrypted_title"]


def test_parent_chat_detection_excludes_sub_chats() -> None:
    assert _is_parent_chat_details({"id": "parent", "parent_id": None, "is_sub_chat": False}) is True
    assert _is_parent_chat_details({"id": "child", "parent_id": "parent", "is_sub_chat": True}) is False
    assert _is_parent_chat_details({"id": "child", "parent_id": "parent", "is_sub_chat": False}) is False
    assert _is_parent_chat_details({"id": "child", "parent_id": None, "is_sub_chat": True}) is False


@pytest.mark.anyio
async def test_phase_all_does_not_run_phase3_background_content_sync(monkeypatch, doc_assert) -> None:
    doc_assert("phase-all-does-not-run-background-content-sync")
    calls = []

    async def fake_phase1(*args, **kwargs):
        calls.append("phase1")
        return ["parent-1"]

    async def fake_phase1b(*args, **kwargs):
        calls.append("phase1b")

    async def fake_phase2(*args, **kwargs):
        calls.append("phase2")

    async def fake_phase3(*args, **kwargs):
        calls.append("phase3")

    async def fake_app_settings(*args, **kwargs):
        calls.append("app_settings")

    monkeypatch.setattr(phased_sync_handler, "_handle_phase1_sync", fake_phase1)
    monkeypatch.setattr(phased_sync_handler, "_handle_phase1b_sync", fake_phase1b)
    monkeypatch.setattr(phased_sync_handler, "_handle_phase2_sync", fake_phase2)
    monkeypatch.setattr(phased_sync_handler, "_handle_phase3_sync", fake_phase3)
    monkeypatch.setattr(phased_sync_handler, "_handle_app_settings_memories_sync", fake_app_settings)

    manager = SimpleNamespace(sent=[])

    async def send_personal_message(message, user_id, device_fingerprint_hash):
        manager.sent.append(message)

    manager.send_personal_message = send_personal_message

    await handle_phased_sync_request(
        websocket=None,
        manager=manager,
        cache_service=SimpleNamespace(),
        directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"phase": "all"},
    )

    assert calls == ["phase1", "phase1b", "phase2", "app_settings"]
    assert all(message["type"] != "background_message_sync" for message in manager.sent)


@pytest.mark.anyio
async def test_phase1_full_content_ids_are_limited_to_recent_parent_chats(doc_assert) -> None:
    doc_assert("phase1-full-content-limited-to-recent-parent-chats")
    parent_ids = [f"parent-{idx}" for idx in range(12)]
    recent_ids = []
    for idx, parent_id in enumerate(parent_ids):
        recent_ids.append(parent_id)
        recent_ids.append(f"sub-{idx}")

    metadata = {
        "last-sub": {
            "id": "last-sub",
            "encrypted_title": "title-last-sub",
            "encrypted_chat_key": "key-last-sub",
            "encrypted_icon": "icon-last-sub",
            "encrypted_category": "category-last-sub",
            "messages_v": 1,
            "title_v": 1,
            "parent_id": "parent-old",
            "is_sub_chat": True,
        }
    }
    for idx, parent_id in enumerate(parent_ids):
        metadata[parent_id] = {
            "id": parent_id,
            "encrypted_title": f"title-{parent_id}",
            "encrypted_chat_key": f"key-{parent_id}",
            "encrypted_icon": f"icon-{parent_id}",
            "encrypted_category": f"category-{parent_id}",
            "messages_v": idx + 1,
            "title_v": 1,
            "parent_id": None,
            "is_sub_chat": False,
        }
        metadata[f"sub-{idx}"] = {
            "id": f"sub-{idx}",
            "encrypted_title": f"title-sub-{idx}",
            "encrypted_chat_key": f"key-sub-{idx}",
            "encrypted_icon": f"icon-sub-{idx}",
            "encrypted_category": f"category-sub-{idx}",
            "messages_v": idx + 1,
            "title_v": 1,
            "parent_id": parent_id,
            "is_sub_chat": True,
        }
        metadata[f"preview-{idx}"] = {
            "id": f"preview-{idx}",
            "encrypted_title": f"title-preview-{idx}",
            "encrypted_chat_key": f"key-preview-{idx}",
            "encrypted_icon": f"icon-preview-{idx}",
            "encrypted_category": f"category-preview-{idx}",
            "messages_v": 1,
            "title_v": 1,
            "parent_id": parent_id,
            "is_sub_chat": True,
        }

    class FakeCache:
        async def get_new_chat_suggestions(self, hashed_user_id):
            return []

        async def get_daily_inspirations_sync(self, hashed_user_id):
            return []

        async def get_chat_ids_versions(self, user_id, start=0, end=99, with_scores=False):
            return recent_ids[start : end + 1]

        async def get_user_by_id(self, user_id):
            return {"last_opened": "chats/last-sub"}

        async def get_batch_chat_list_item_data(self, user_id, chat_ids):
            return {}

        async def get_batch_chat_versions(self, user_id, chat_ids):
            return {}

    class FakeDirectusChat:
        async def get_new_chat_suggestions_for_user(self, hashed_user_id, limit=30):
            return []

        async def get_chats_metadata_batch(self, chat_ids):
            return {chat_id: metadata[chat_id] for chat_id in chat_ids if chat_id in metadata}

        async def get_chat_metadata(self, chat_id):
            return metadata.get(chat_id)

    class FakeDirectus:
        def __init__(self):
            self.chat = FakeDirectusChat()

        async def get_items(self, collection, params, admin_required=True):
            parent_filter = params["filter[parent_id][_in]"].split(",")
            return [
                {"id": f"preview-{idx}", "parent_id": parent_id, "is_sub_chat": True}
                for idx, parent_id in enumerate(parent_filter)
            ]

    manager = SimpleNamespace(sent=[])

    async def send_personal_message(message, user_id, device_fingerprint_hash):
        manager.sent.append(message)

    manager.send_personal_message = send_personal_message

    content_ids = await _handle_phase1_sync(
        manager=manager,
        cache_service=FakeCache(),
        directus_service=FakeDirectus(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        client_chat_versions={},
        client_chat_ids=[],
        sent_embed_ids=set(),
    )

    assert content_ids == parent_ids[:10]
    phase1_payload = manager.sent[0]["payload"]
    assert phase1_payload["chat_details"]["id"] == "last-sub"
    sent_metadata_ids = {chat["id"] for chat in phase1_payload["recent_chat_metadata"]}
    assert set(parent_ids[:10]).issubset(sent_metadata_ids)
    assert "preview-0" in sent_metadata_ids
    assert "sub-0" not in content_ids
    assert "last-sub" not in content_ids
