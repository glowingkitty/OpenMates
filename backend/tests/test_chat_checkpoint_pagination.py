"""Opaque checkpoint discovery and separately admitted large summaries."""
import uuid

import pytest
from fastapi import HTTPException

from backend.core.api.app.services.chat_checkpoint_pagination import checkpoint_by_id, checkpoint_window


class Checkpoints:
    def __init__(self, count=30, size=100):
        self.rows = [{"id": str(uuid.UUID(int=i + 1)), "chat_id": "owner-chat", "created_at": 100,
                      "encrypted_summary": "x" * size} for i in range(count)]
        self.queries = []

    async def get_items(self, collection, *, params, **kwargs):
        assert collection == "chat_compression_checkpoints"
        assert kwargs["admin_required"] and kwargs["raise_on_error"]
        assert "covered_message_ids" not in params["fields"]
        self.queries.append(params)
        filters = params["filter"]
        if "_and" not in filters:
            return [r for r in self.rows if r["chat_id"] == filters["chat_id"]["_eq"]
                    and r["id"] == filters["id"]["_eq"]][:1]
        chat_id = filters["_and"][0]["chat_id"]["_eq"]
        rows = [r for r in self.rows if r["chat_id"] == chat_id]
        if len(filters["_and"]) > 1:
            boundary = filters["_and"][1]["_or"]
            timestamp = boundary[0]["created_at"]["_lt"]
            identity = boundary[1]["_and"][1]["id"]["_lt"]
            rows = [r for r in rows if (r["created_at"], r["id"]) < (timestamp, identity)]
        return sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)[:params["limit"]]


# contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive,storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_checkpoint_cursor_preserves_all_same_timestamp_rows_without_manifest_preload():
    directus = Checkpoints()
    first = await checkpoint_window(directus, chat_id="owner-chat", limit=20)
    assert len(first["checkpoints"]) == 20 and first["has_more_before"]
    cursor = first["start_cursor"]
    second = await checkpoint_window(directus, chat_id="owner-chat", limit=20,
                                     before_timestamp=cursor["created_at"], before_id=cursor["id"])
    assert not second["has_more_before"]
    assert second["checkpoints"] + first["checkpoints"] == directus.rows
    assert all(q["limit"] == 21 for q in directus.queries)


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages,storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_checkpoint_byte_boundary_has_an_exact_read_without_losing_next_cursor():
    directus = Checkpoints(count=3, size=150000)
    page = await checkpoint_window(directus, chat_id="owner-chat")
    assert not page["checkpoints"] and page["has_more_before"]
    identity = page["oversized_checkpoint_id"]
    selected = await checkpoint_by_id(directus, chat_id="owner-chat", checkpoint_id=identity)
    assert selected["checkpoint"] == directus.rows[-1]
    earlier = await checkpoint_window(directus, chat_id="owner-chat", before_timestamp=100, before_id=identity)
    assert earlier["oversized_checkpoint_id"] == directus.rows[-2]["id"]


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.cold.independent-message-pages
@pytest.mark.asyncio
async def test_selected_checkpoint_remains_chat_scoped_and_rejects_unsupported_legacy_size():
    directus = Checkpoints(count=1, size=2 * 1024 * 1024)
    identity = directus.rows[0]["id"]
    with pytest.raises(HTTPException) as foreign:
        await checkpoint_by_id(directus, chat_id="foreign-chat", checkpoint_id=identity)
    assert foreign.value.status_code == 404
    with pytest.raises(HTTPException) as large:
        await checkpoint_by_id(directus, chat_id="owner-chat", checkpoint_id=identity)
    assert large.value.status_code == 413
    assert directus.rows[0]["encrypted_summary"]  # the authoritative copy is retained
