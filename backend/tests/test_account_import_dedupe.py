"""Account Import V1 dedupe contract tests.

Dedupe is advisory only: matching source fingerprints warn the user but never
authorize merge, overwrite, or destructive updates to existing chats.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.account_import_service import AccountImportService, InMemoryImportJobStore


@pytest.mark.anyio
async def test_preview_returns_duplicate_fingerprint_warnings() -> None:
    service = AccountImportService()
    chats = [
        {"source_fingerprint": "fingerprint-existing", "updated_at": "2026-07-17T00:00:00Z", "messages": []},
        {"source_fingerprint": "fingerprint-new", "updated_at": "2026-07-18T00:00:00Z", "messages": []},
    ]

    preview = await service.preview_import(
        user_id="user-1",
        source="claude",
        chats=chats,
        available_credits=50,
        imported_count_last_30_days=0,
        existing_fingerprints={"fingerprint-existing"},
    )

    assert preview["duplicate_fingerprints"] == ["fingerprint-existing"]
    assert preview["can_import"] is True


@pytest.mark.anyio
async def test_complete_records_new_import_without_updating_existing_chats() -> None:
    directus = SimpleNamespace(
        update_item=AsyncMock(),
    )
    store = InMemoryImportJobStore()
    service = AccountImportService(directus_service=directus, job_store=store)

    result = await service.complete_import(
        user_id="user-1",
        import_id="import-1",
        imported_chat_ids=["new-chat-1"],
        source_fingerprints=["fingerprint-existing"],
        encrypted_record_counts={"chats": 1, "messages": 2},
        client_failures=[],
    )

    assert result["status"] == "complete"
    assert result["imported_count"] == 1
    metadata = await store.get(user_id="user-1", import_id="import-1")
    assert metadata["source_fingerprints"] == ["fingerprint-existing"]
    directus.update_item.assert_not_awaited()
