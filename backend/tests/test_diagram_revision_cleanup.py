"""Diagram revision receipts are removed with their authorized embed heads."""

from __future__ import annotations

import pytest

from backend.core.api.app.services.storage_reference_service import delete_chat_diagram_revision_receipts


class FakeDirectus:
    def __init__(self) -> None:
        self.rows = [
            {"id": "receipt-a", "embed_id": "deleted-a"},
            {"id": "receipt-b", "embed_id": "deleted-a"},
            {"id": "receipt-c", "embed_id": "survivor"},
        ]

    async def get_items(self, collection, *, params, **_kwargs):
        assert collection == "chat_diagram_revision_commits"
        embed_id = params["filter"]["embed_id"]["_eq"]
        return [{"id": row["id"]} for row in self.rows if row["embed_id"] == embed_id]

    async def bulk_delete_items(self, collection, ids):
        assert collection == "chat_diagram_revision_commits"
        self.rows = [row for row in self.rows if row["id"] not in ids]
        return True


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_deleted_embed_receipts_are_removed_without_touching_survivor() -> None:
    store = FakeDirectus()
    count = await delete_chat_diagram_revision_receipts(
        directus_service=store, embed_ids=["deleted-a", "deleted-a"],
    )
    assert count == 2
    assert store.rows == [{"id": "receipt-c", "embed_id": "survivor"}]
