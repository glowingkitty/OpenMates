"""Account Import V1 resumability contracts.

Only bounded hashes, counters, usage, and sequence cursors may survive requests.
Acknowledged retries must not repeat provider work or advance billing twice.
Plaintext remains client-held and is never returned by the status endpoint.
"""

from __future__ import annotations

import pytest

from backend.core.api.app.services.account_import_service import AccountImportService, ImportSequenceError, InMemoryImportJobStore


@pytest.mark.anyio
async def test_acknowledged_scan_retry_is_idempotent_and_status_is_metadata_only() -> None:
    calls = 0

    async def scanner(content: str, **_: object) -> dict:
        nonlocal calls
        calls += 1
        return {"content": content.replace("unsafe", "sanitized"), "usage": {"credits": 2}}

    service = AccountImportService(scanner=scanner, job_store=InMemoryImportJobStore())
    request = {"user_id": "user-1", "import_id": "import-1", "batch_id": "batch-0", "sequence": 0,
               "final_batch": False, "chats": [{"messages": [{"role": "user", "content": "unsafe text"}]}]}
    first = await service.scan_import_batch(**request)
    retry = await service.scan_import_batch(**request)
    status = await service.get_import_status(user_id="user-1", import_id="import-1")
    assert retry["status"] == first["status"] == "acknowledged"
    assert retry["already_acknowledged"] is True
    assert retry["chats"] == []
    assert calls == 1
    assert status == {"status": "scanning", "last_scan_sequence": 0, "last_compression_sequence": -1,
                      "usage": {"credits": 2, "input_tokens": 0, "output_tokens": 0},
                      "credits_reserved": 0, "retryable_failure": None}
    assert "unsafe text" not in repr(service.job_store.records)
    assert "sanitized text" not in repr(service.job_store.records)


@pytest.mark.anyio
async def test_scan_sequence_is_bounded_and_can_continue_across_many_batches() -> None:
    service = AccountImportService(scanner=lambda content, **_: {"content": content, "usage": {"credits": 0}},
                                   job_store=InMemoryImportJobStore(), max_batch_messages=1)
    for sequence in range(25):
        result = await service.scan_import_batch(
            user_id="user-1", import_id="import-1", batch_id=f"batch-{sequence}", sequence=sequence,
            final_batch=sequence == 24, chats=[{"messages": [{"role": "user", "content": f"message {sequence}"}]}],
        )
        assert result["sequence"] == sequence
    with pytest.raises(ImportSequenceError, match="expected sequence 25"):
        await service.scan_import_batch(user_id="user-1", import_id="import-1", batch_id="batch-26", sequence=26,
                                        final_batch=True, chats=[{"messages": [{"role": "user", "content": "gap"}]}])
    with pytest.raises(ValueError, match="at most 1 messages"):
        await service.scan_import_batch(
            user_id="user-1", import_id="other-import", batch_id="too-large", sequence=0, final_batch=True,
            chats=[{"messages": [{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}]}],
        )
