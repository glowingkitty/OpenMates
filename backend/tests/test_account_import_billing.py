"""Account Import V1 strict billing collaborator contracts.

Paid model work requires a conservative reservation before scanning. Settlement
uses measured usage, releases unused credits, prevents debt, and is idempotent.
Production must fail closed when no safe billing collaborator is configured.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.account_import_service import AccountImportService, ImportCreditError, InMemoryImportJobStore


@pytest.mark.anyio
async def test_paid_work_reserves_first_and_settles_measured_usage_exactly_once() -> None:
    billing = AsyncMock()
    billing.reserve.return_value = {"credits_reserved": 20}
    billing.settle.return_value = {"credits_charged": 7, "credits_released": 13, "balance": 3}
    scanner = AsyncMock(return_value={"content": "safe", "usage": {"credits": 7}})
    service = AccountImportService(scanner=scanner, billing=billing, job_store=InMemoryImportJobStore())
    await service.reserve_import_credits(user_id="user-1", import_id="import-1", selected_chat_count=1,
                                         available_credits=20, estimated_credits=20)
    await service.scan_import_batch(user_id="user-1", import_id="import-1", batch_id="scan-0", sequence=0,
                                    final_batch=True, chats=[{"messages": [{"role": "user", "content": "selected"}]}])
    kwargs = {"user_id": "user-1", "import_id": "import-1", "imported_chat_ids": ["chat-1"],
              "source_fingerprints": ["hash-1"], "encrypted_record_counts": {"chats": 1, "messages": 1}}
    first = await service.complete_import(**kwargs)
    second = await service.complete_import(**kwargs)
    billing.reserve.assert_awaited_once()
    billing.settle.assert_awaited_once_with(user_id="user-1", import_id="import-1", reserved_credits=20, measured_credits=7)
    assert first["credits_charged"] == 7
    assert first["credits_released"] == 13
    assert second == first


@pytest.mark.anyio
async def test_insufficient_or_missing_billing_prevents_paid_model_work() -> None:
    scanner = AsyncMock(return_value={"content": "safe", "usage": {"credits": 1}})
    service = AccountImportService(scanner=scanner, job_store=InMemoryImportJobStore())
    with pytest.raises(ImportCreditError, match="billing unavailable"):
        await service.reserve_import_credits(user_id="user-1", import_id="import-1", selected_chat_count=1,
                                             available_credits=100, estimated_credits=20)
    scanner.assert_not_awaited()


@pytest.mark.anyio
async def test_production_scan_cannot_bypass_preview_or_reservation() -> None:
    scanner = AsyncMock(return_value={"content": "safe", "usage": {"credits": 0}})
    service = AccountImportService(
        scanner=scanner,
        job_store=InMemoryImportJobStore(),
        require_billing_for_paid=True,
    )

    with pytest.raises(ImportCreditError, match="valid free allowance or paid reservation"):
        await service.scan_import_batch(
            user_id="user-1",
            import_id="unpreviewed-import",
            batch_id="scan-0",
            sequence=0,
            final_batch=True,
            chats=[{"messages": [{"role": "user", "content": "selected"}]}],
        )

    scanner.assert_not_awaited()


@pytest.mark.anyio
async def test_settlement_rejects_usage_above_reservation_to_prevent_debt() -> None:
    billing = AsyncMock()
    billing.reserve.return_value = {"credits_reserved": 5}
    service = AccountImportService(scanner=AsyncMock(return_value={"content": "safe", "usage": {"credits": 6}}),
                                   billing=billing, job_store=InMemoryImportJobStore())
    await service.reserve_import_credits(user_id="user-1", import_id="import-1", selected_chat_count=1,
                                         available_credits=5, estimated_credits=5)
    with pytest.raises(ImportCreditError, match="exceeds reserved credits"):
        await service.scan_import_batch(user_id="user-1", import_id="import-1", batch_id="scan-0", sequence=0,
                                        final_batch=True, chats=[{"messages": [{"role": "user", "content": "selected"}]}])
    billing.settle.assert_not_awaited()
