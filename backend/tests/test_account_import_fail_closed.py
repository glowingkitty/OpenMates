"""Account Import V1 fail-closed behavior tests.

Malformed input, scanner failures, and partial client persistence must surface as
explicit failures instead of charging blindly or claiming complete success.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.account_import_service import AccountImportService, ImportScanError


@pytest.mark.anyio
async def test_scanner_unavailable_blocks_import_before_plaintext_persistence() -> None:
    directus = SimpleNamespace(create_item=AsyncMock(), update_item=AsyncMock())
    scanner = AsyncMock(side_effect=RuntimeError("scanner offline"))
    service = AccountImportService(directus_service=directus, scanner=scanner)

    with pytest.raises(ImportScanError, match="scanner unavailable"):
        await service.scan_selected_chats(
            user_id="user-1",
            import_id="import-1",
            chats=[{"source_fingerprint": "fingerprint-1", "messages": [{"role": "user", "content": "Synthetic selected text."}]}],
        )

    directus.create_item.assert_not_awaited()
    directus.update_item.assert_not_awaited()


@pytest.mark.anyio
async def test_partial_client_persistence_reports_partial_not_complete() -> None:
    service = AccountImportService(directus_service=SimpleNamespace(create_item=AsyncMock(return_value=(True, {"id": "usage-1"}))))

    result = await service.complete_import(
        user_id="user-1",
        import_id="import-1",
        imported_chat_ids=["new-chat-1"],
        source_fingerprints=["fingerprint-1", "fingerprint-2"],
        encrypted_record_counts={"chats": 1, "messages": 3},
        client_failures=[{"source_fingerprint": "fingerprint-2", "reason": "client_encryption_failed"}],
    )

    assert result["status"] == "partial"
    assert result["imported_count"] == 1
    assert result["failures"] == [{"source_fingerprint": "fingerprint-2", "reason": "client_encryption_failed"}]


@pytest.mark.anyio
async def test_unsupported_domains_are_reported_explicitly() -> None:
    service = AccountImportService()

    result = await service.report_skipped_domains(source="openmates", domains=["projects", "tasks", "memories"])

    assert result == {
        "source": "openmates",
        "skipped_domains": ["memories", "projects", "tasks"],
        "reason": "unsupported_in_account_import_v1",
        "follow_up": "OPE-588",
    }
