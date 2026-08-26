"""Bounded cold archive discovery contract tests.

Opaque owner-scoped cursors produce stable pages without duplicate resource IDs.
Partial pages are discovery results only and never imply deletion authority.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import pytest

from backend.core.api.app.services.cold_archive_service import (
    ColdArchiveCursorError,
    decode_archive_cursor,
    encode_archive_cursor,
    merge_archive_metadata_page,
)


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,sync.deletion.partial-window-not-authoritative
def test_hot_and_cold_metadata_merge_stably_without_duplicates() -> None:
    hot = [{"resource_id": "chat-3", "sort_timestamp": 30, "source": "hot"}, {"resource_id": "chat-2", "sort_timestamp": 20, "source": "hot"}]
    cold = [{"resource_id": "chat-2", "sort_timestamp": 20, "source": "cold"}, {"resource_id": "chat-1", "sort_timestamp": 10, "source": "cold"}]

    page = merge_archive_metadata_page(hot, cold, limit=2)

    assert [item["resource_id"] for item in page["items"]] == ["chat-3", "chat-2"]
    assert page["complete"] is False
    assert "deleted_ids" not in page


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded
def test_cursor_is_scope_bound_and_round_trips_stably() -> None:
    cursor = encode_archive_cursor(sort_timestamp=20, archive_id="archive-2", scope_hash="owner-hash")

    assert decode_archive_cursor(cursor, expected_scope_hash="owner-hash") == (20, "archive-2")
    with pytest.raises(ColdArchiveCursorError):
        decode_archive_cursor(cursor, expected_scope_hash="other-owner")


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded
def test_final_bounded_page_reports_complete() -> None:
    page = merge_archive_metadata_page([], [{"resource_id": "chat-1", "sort_timestamp": 10, "source": "cold"}], limit=100)

    assert page == {"items": [{"resource_id": "chat-1", "sort_timestamp": 10, "source": "cold"}], "next_cursor": None, "complete": True}
