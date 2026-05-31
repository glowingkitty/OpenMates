# backend/tests/test_phased_sync_handler.py
"""
Regression tests for Phase 1a chat metadata assembly.

Phase 1a combines Redis list-item cache data with Directus fallback metadata.
When Redis is partially warm, missing encrypted header fields must be filled
from Directus so the client has metadata to decrypt on cold boot.
"""

from backend.core.api.app.routes.handlers.websocket_handlers.phased_sync_handler import (
    _count_directus_filled_metadata_fields,
    _merge_partial_cache_chat_details,
    _phase1_metadata_invariant_violations,
)


def test_phase1_partial_cache_metadata_is_filled_from_directus() -> None:
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
