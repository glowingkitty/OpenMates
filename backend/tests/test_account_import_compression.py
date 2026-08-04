"""Account Import V1 compression contracts.

Compression accepts only sanitized batches previously acknowledged by scanning.
It uses the production threshold and returns summaries transiently for clients to
encrypt; no plaintext summary or imported message is retained by job metadata.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.chat_compressor import DEFAULT_COMPRESSION_TRIGGER_THRESHOLD, _response_token_usage
from backend.core.api.app.services.account_import_service import AccountImportService, ImportCompressionError, InMemoryImportJobStore


async def _scan(service: AccountImportService, content: str) -> dict:
    return await service.scan_import_batch(user_id="user-1", import_id="import-1", batch_id="scan-0", sequence=0,
                                           final_batch=True, chats=[{"messages": [{"role": "user", "content": content}]}])


def test_compressor_extracts_measured_provider_usage() -> None:
    response = SimpleNamespace(usage=SimpleNamespace(prompt_token_count=20, candidates_token_count=5))

    assert _response_token_usage(response) == (20, 5)


@pytest.mark.anyio
async def test_compression_rejects_unacknowledged_or_changed_sanitized_batch() -> None:
    service = AccountImportService(scanner=lambda content, **_: {"content": content, "usage": {"credits": 0}},
                                   compressor=AsyncMock(), job_store=InMemoryImportJobStore())
    with pytest.raises(ImportCompressionError, match="acknowledged sanitized batch"):
        await service.compress_import_batch(user_id="user-1", import_id="import-1", batch_id="compress-0", sequence=0,
                                            final_batch=True, scan_sequence=0,
                                            sanitized_messages=[{"role": "user", "content": "raw"}])
    await _scan(service, "sanitized")
    with pytest.raises(ImportCompressionError, match="does not match"):
        await service.compress_import_batch(user_id="user-1", import_id="import-1", batch_id="compress-0", sequence=0,
                                            final_batch=True, scan_sequence=0,
                                            sanitized_messages=[{"role": "user", "content": "changed"}])


@pytest.mark.anyio
async def test_production_threshold_controls_compression_and_summary_is_transient() -> None:
    compressor = AsyncMock(return_value=SimpleNamespace(was_compressed=True, summary_content="transient summary",
                                                        compressed_message_count=1, summary_token_estimate=4, error=None))
    service = AccountImportService(scanner=lambda content, **_: {"content": content, "usage": {"credits": 1}},
                                   compressor=compressor, job_store=InMemoryImportJobStore())
    content = "x" * ((DEFAULT_COMPRESSION_TRIGGER_THRESHOLD - 15_000) * 4)
    scan = await _scan(service, content)
    result = await service.compress_import_batch(
        user_id="user-1", import_id="import-1", batch_id="compress-0", sequence=0, final_batch=True,
        scan_sequence=0, sanitized_messages=scan["chats"][0]["messages"],
    )
    compressor.assert_awaited_once()
    assert result["summary"] == "transient summary"
    assert result["status"] == "acknowledged"
    assert "transient summary" not in repr(service.job_store.records)
    assert content not in repr(service.job_store.records)


@pytest.mark.anyio
async def test_below_production_threshold_acknowledges_without_provider_call() -> None:
    compressor = AsyncMock()
    service = AccountImportService(scanner=lambda content, **_: {"content": content, "usage": {"credits": 0}},
                                   compressor=compressor, job_store=InMemoryImportJobStore())
    scan = await _scan(service, "short sanitized text")
    result = await service.compress_import_batch(
        user_id="user-1", import_id="import-1", batch_id="compress-0", sequence=0, final_batch=True,
        scan_sequence=0, sanitized_messages=scan["chats"][0]["messages"],
    )
    assert result["summary"] is None
    compressor.assert_not_awaited()
