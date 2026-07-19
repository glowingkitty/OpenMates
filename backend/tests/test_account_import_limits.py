"""Account Import V1 allowance and credit limit contract tests.

The import preview must be stricter than generic skill billing: no negative
credits, source-agnostic free allowance, and bounded paid batches.
"""

from __future__ import annotations

import pytest

from backend.core.api.app.services.account_import_service import AccountImportService, ImportCreditError


def _chats(count: int) -> list[dict]:
    return [
        {
            "provider": "claude",
            "source_chat_id": f"chat-{index}",
            "source_fingerprint": f"fingerprint-{index}",
            "title": f"Synthetic chat {index}",
            "updated_at": f"2026-07-{index + 1:02d}T00:00:00Z",
            "messages": [{"role": "user", "content": "Synthetic message."}],
            "embeds": [],
            "uploads": [],
        }
        for index in range(count)
    ]


@pytest.mark.anyio
async def test_zero_credit_accounts_are_capped_at_three_imports_per_rolling_window() -> None:
    service = AccountImportService()

    preview = await service.preview_import(
        user_id="user-1",
        source="claude",
        chats=_chats(40),
        available_credits=0,
        imported_count_last_30_days=0,
        existing_fingerprints=set(),
    )

    assert preview["free_remaining"] == 3
    assert preview["default_selection_count"] == 3
    assert preview["max_batch_count"] == 3
    assert preview["can_import"] is True


@pytest.mark.anyio
async def test_free_allowance_is_source_agnostic() -> None:
    service = AccountImportService()

    preview = await service.preview_import(
        user_id="user-1",
        source="openmates",
        chats=_chats(4),
        available_credits=0,
        imported_count_last_30_days=2,
        existing_fingerprints=set(),
    )

    assert preview["free_remaining"] == 1
    assert preview["max_batch_count"] == 1
    assert preview["reason"] == "free_import_allowance_remaining"


@pytest.mark.anyio
async def test_paid_accounts_default_newest_twenty_and_cap_thirty_per_batch() -> None:
    service = AccountImportService(credits_per_chat_estimate=2)

    preview = await service.preview_import(
        user_id="user-1",
        source="claude",
        chats=_chats(120),
        available_credits=100,
        imported_count_last_30_days=3,
        existing_fingerprints=set(),
    )

    assert preview["free_remaining"] == 0
    assert preview["default_selection_count"] == 20
    assert preview["max_batch_count"] == 30
    assert preview["estimated_credits"] == 40
    assert preview["can_import"] is True


@pytest.mark.anyio
async def test_insufficient_credits_block_scan_without_negative_balance() -> None:
    service = AccountImportService(credits_per_chat_estimate=5)

    with pytest.raises(ImportCreditError, match="Insufficient credits"):
        await service.reserve_import_credits(
            user_id="user-1",
            import_id="import-1",
            selected_chat_count=4,
            available_credits=10,
        )
