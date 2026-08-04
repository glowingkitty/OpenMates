"""Regression tests for Account Import V1 review findings.

These contracts cover authoritative preview state, paid reservation and measured
usage, cumulative multi-batch compression, persistence gates, retry metadata,
and concurrency-safe idempotency. No fixture contains production user content.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.account_import_service import (
    FREE_IMPORT_CHAT_TOKEN_CAP,
    AccountImportService,
    BillingServiceImportBilling,
    ImportCreditError,
    ImportPersistenceError,
    ImportScanError,
    InMemoryImportJobStore,
    InMemoryImportLock,
    RedisImportLock,
    _message_chain,
)


def _chat(fingerprint: str, content: str) -> dict:
    return {
        "source_fingerprint": fingerprint,
        "estimated_input_tokens": max(1, len(content) // 4),
        "messages": [{"role": "user", "content": content}],
    }


@pytest.mark.anyio
async def test_billing_service_adapter_charges_reservation_and_refunds_unused_credits() -> None:
    user = {"credits": 50}
    billing_service = SimpleNamespace(
        cache_service=SimpleNamespace(get_user_by_id=AsyncMock(side_effect=lambda _: dict(user))),
        charge_user_credits=AsyncMock(),
        refund_user_credits=AsyncMock(),
    )
    adapter = BillingServiceImportBilling(billing_service)

    reservation = await adapter.reserve(user_id="user-1", import_id="import-1", estimated_credits=20)
    settlement = await adapter.settle(
        user_id="user-1", import_id="import-1", reserved_credits=20, measured_credits=7,
    )

    assert reservation == {"credits_reserved": 20}
    billing_service.charge_user_credits.assert_awaited_once()
    billing_service.refund_user_credits.assert_awaited_once()
    assert settlement == {"credits_charged": 7, "credits_released": 13, "balance": 50}


@pytest.mark.anyio
async def test_billing_adapter_refreshes_cache_from_directus_before_rejecting() -> None:
    profile = {"id": "user-1", "credits": 30, "vault_key_id": "vault-1"}
    cache = SimpleNamespace(
        get_user_by_id=AsyncMock(side_effect=[None, profile]),
        set_user=AsyncMock(),
    )
    directus = SimpleNamespace(get_user_profile=AsyncMock(return_value=(True, profile, "ok")))
    billing_service = SimpleNamespace(
        cache_service=cache,
        directus_service=directus,
        charge_user_credits=AsyncMock(),
        refund_user_credits=AsyncMock(),
    )

    result = await BillingServiceImportBilling(billing_service).reserve(
        user_id="user-1", import_id="import-1", estimated_credits=20,
    )

    assert result == {"credits_reserved": 20}
    directus.get_user_profile.assert_awaited_once_with("user-1")
    cache.set_user.assert_awaited_once_with(profile, user_id="user-1")
    billing_service.charge_user_credits.assert_awaited_once()


@pytest.mark.anyio
async def test_paid_preview_does_not_charge_and_explicit_confirmation_reserves() -> None:
    billing = AsyncMock()
    billing.reserve.return_value = {"credits_reserved": 20}
    scanner = AsyncMock(return_value={
        "content": "safe",
        "usage": {"model_id": "provider/scanner", "input_tokens": 8, "output_tokens": 2},
    })
    def pricer(model_id: str, input_tokens: int, output_tokens: int) -> int:
        del model_id
        return input_tokens + output_tokens
    service = AccountImportService(
        scanner=scanner,
        billing=billing,
        usage_pricer=pricer,
        job_store=InMemoryImportJobStore(),
        import_lock=InMemoryImportLock(),
        require_billing_for_paid=True,
    )

    preview = await service.preview_import(
        user_id="user-1",
        source="claude",
        chats=[_chat("fp-1", "selected")],
        available_credits=50,
        imported_count_last_30_days=0,
        existing_fingerprints=set(),
        estimated_credits=20,
    )
    billing.reserve.assert_not_awaited()
    confirmation = await service.confirm_import(
        user_id="user-1",
        import_id=preview["import_id"],
        selected_fingerprints=["fp-1"],
        available_credits=50,
    )
    result = await service.scan_import_batch(
        user_id="user-1",
        import_id=preview["import_id"],
        batch_id="scan-0",
        sequence=0,
        final_batch=True,
        chats=[_chat("fp-1", "selected")],
    )

    billing.reserve.assert_awaited_once()
    assert preview["can_import"] is True
    assert confirmation["status"] == "confirmed"
    assert result["usage"] == {
        "credits": 10,
        "input_tokens": 8,
        "output_tokens": 2,
    }


@pytest.mark.anyio
async def test_free_preview_uses_durable_history_and_scan_enforces_contract_and_actual_cap() -> None:
    store = InMemoryImportJobStore()
    await store.save(user_id="user-1", import_id="old", metadata={
        "status": "complete",
        "processing_mode": "free",
        "source_fingerprints": ["duplicate"],
        "server_content_fingerprints": {
            "duplicate": _message_chain([{"role": "user", "content": "selected"}]),
        },
        "created_at": "2099-01-01T00:00:00Z",
    })
    service = AccountImportService(
        scanner=lambda content, **_: {"content": content, "usage": {"model_id": "free", "input_tokens": 1, "output_tokens": 0}},
        usage_pricer=lambda *_: 0,
        job_store=store,
        import_lock=InMemoryImportLock(),
        require_billing_for_paid=True,
    )
    preview = await service.preview_import(
        user_id="user-1",
        source="claude",
        chats=[_chat("duplicate", "selected"), _chat("fp-2", "selected")],
        available_credits=0,
        imported_count_last_30_days=0,
        existing_fingerprints=set(),
    )

    assert preview["free_remaining"] == 2
    assert preview["duplicate_fingerprints"] == ["duplicate"]
    second_preview = await service.preview_import(
        user_id="user-1",
        source="claude",
        chats=[_chat("fp-3", "selected")],
        available_credits=0,
        imported_count_last_30_days=0,
        existing_fingerprints=set(),
    )
    assert second_preview["free_remaining"] == 2
    await service.confirm_import(
        user_id="user-1",
        import_id=preview["import_id"],
        selected_fingerprints=["duplicate"],
        available_credits=0,
    )
    with pytest.raises(ImportScanError, match="preview contract"):
        await service.scan_import_batch(
            user_id="user-1",
            import_id=preview["import_id"],
            batch_id="scan-0",
            sequence=0,
            final_batch=True,
            chats=[_chat("not-selected", "selected")],
        )

    duplicate_result = await service.scan_import_batch(
        user_id="user-1",
        import_id=preview["import_id"],
        batch_id="scan-0",
        sequence=0,
        final_batch=True,
        chats=[_chat("duplicate", "selected")],
    )
    assert duplicate_result["duplicate_fingerprints"] == ["duplicate"]

    oversized = "x" * ((FREE_IMPORT_CHAT_TOKEN_CAP + 1) * 4)
    capped_preview = await service.preview_import(
        user_id="other-user",
        source="claude",
        chats=[_chat("fp-large", "claimed small")],
        available_credits=0,
        imported_count_last_30_days=0,
        existing_fingerprints=set(),
    )
    await service.confirm_import(
        user_id="other-user",
        import_id=capped_preview["import_id"],
        selected_fingerprints=["fp-large"],
        available_credits=0,
    )
    with pytest.raises(ImportCreditError, match="100000"):
        await service.scan_import_batch(
            user_id="other-user",
            import_id=capped_preview["import_id"],
            batch_id="scan-0",
            sequence=0,
            final_batch=True,
            chats=[_chat("fp-large", oversized)],
        )


@pytest.mark.anyio
async def test_only_confirmed_unexpired_free_reservations_consume_allowance() -> None:
    store = InMemoryImportJobStore()
    service = AccountImportService(
        job_store=store,
        import_lock=InMemoryImportLock(),
        require_billing_for_paid=True,
    )
    abandoned = await service.preview_import(
        user_id="user-1", source="claude", chats=[_chat("fp-a", "short")], available_credits=0,
        imported_count_last_30_days=0, existing_fingerprints=set(),
    )
    assert abandoned["free_remaining"] == 3
    another = await service.preview_import(
        user_id="user-1", source="claude", chats=[_chat("fp-b", "short")], available_credits=0,
        imported_count_last_30_days=0, existing_fingerprints=set(),
    )
    assert another["free_remaining"] == 3
    await service.confirm_import(
        user_id="user-1", import_id=another["import_id"], selected_fingerprints=["fp-b"], available_credits=0,
    )
    active = await service.preview_import(
        user_id="user-1", source="claude", chats=[_chat("fp-c", "short")], available_credits=0,
        imported_count_last_30_days=0, existing_fingerprints=set(),
    )
    assert active["free_remaining"] == 2
    record = await store.get(user_id="user-1", import_id=another["import_id"])
    record["reservation_expires_at"] = "2000-01-01T00:00:00+00:00"
    await store.save(user_id="user-1", import_id=another["import_id"], metadata=record)
    after_expiry = await service.preview_import(
        user_id="user-1", source="claude", chats=[_chat("fp-d", "short")], available_credits=0,
        imported_count_last_30_days=0, existing_fingerprints=set(),
    )
    assert after_expiry["free_remaining"] == 3

@pytest.mark.anyio
async def test_multi_batch_compression_requires_complete_acknowledged_chat() -> None:
    service = AccountImportService(
        scanner=lambda content, **_: {"content": content, "usage": {"model_id": "free", "input_tokens": 1, "output_tokens": 0}},
        usage_pricer=lambda *_: 0,
        compressor=AsyncMock(return_value=SimpleNamespace(
            was_compressed=True,
            summary_content="summary two",
            input_tokens=10,
            output_tokens=2,
            model_id="provider/compressor",
            error=None,
        )),
        job_store=InMemoryImportJobStore(),
        import_lock=InMemoryImportLock(),
    )
    first = _chat("fp-1", "first batch")
    second = _chat("fp-1", "second batch")
    await service.scan_import_batch(
        user_id="user-1", import_id="import-1", batch_id="scan-0", sequence=0,
        final_batch=False, chats=[first],
    )
    first_result = await service.compress_import_batch(
        user_id="user-1", import_id="import-1", batch_id="compress-0", sequence=0,
        final_batch=False, scan_sequence=0, source_fingerprint="fp-1",
        sanitized_messages=first["messages"], prior_summary=None,
    )
    await service.scan_import_batch(
        user_id="user-1", import_id="import-1", batch_id="scan-1", sequence=1,
        final_batch=True, chats=[second],
    )

    with pytest.raises(Exception, match="acknowledged scanned batch"):
        await service.compress_import_batch(
            user_id="user-1", import_id="import-1", batch_id="compress-1", sequence=1,
            final_batch=True, scan_sequence=1, source_fingerprint="fp-1",
            sanitized_messages=first["messages"] + second["messages"], prior_summary=first_result["summary"],
        )
    result = await service.compress_import_batch(
        user_id="user-1", import_id="import-1", batch_id="compress-1", sequence=1,
        final_batch=True, scan_sequence=1, source_fingerprint="fp-1",
        sanitized_messages=second["messages"], prior_summary=first_result["summary"],
    )
    assert result["status"] == "acknowledged"


@pytest.mark.anyio
async def test_cumulative_compression_requirement_forces_final_incremental_summary() -> None:
    from backend.apps.ai.processing.chat_compressor import (
        DEFAULT_COMPRESSION_TRIGGER_THRESHOLD,
        ESTIMATED_SYSTEM_PROMPT_OVERHEAD,
    )

    compressor = AsyncMock(return_value=SimpleNamespace(
        was_compressed=True,
        summary_content="cumulative summary",
        input_tokens=10,
        output_tokens=2,
        model_id="provider/compressor",
        error=None,
    ))
    store = InMemoryImportJobStore()
    service = AccountImportService(
        scanner=lambda content, **_: {"content": content, "usage": {"credits": 0}},
        compressor=compressor,
        job_store=store,
        import_lock=InMemoryImportLock(),
    )
    cumulative_chars = (DEFAULT_COMPRESSION_TRIGGER_THRESHOLD - ESTIMATED_SYSTEM_PROMPT_OVERHEAD) * 4
    first = _chat("fp-1", "a" * (cumulative_chars - 40))
    final = _chat("fp-1", "b" * 40)
    await service.scan_import_batch(
        user_id="user-1", import_id="import-1", batch_id="scan-0", sequence=0,
        final_batch=False, chats=[first],
    )
    await service.scan_import_batch(
        user_id="user-1", import_id="import-1", batch_id="scan-1", sequence=1,
        final_batch=True, chats=[final],
    )
    job = await store.get(user_id="user-1", import_id="import-1")
    job["selected_fingerprints"] = ["fp-1"]
    await store.save(user_id="user-1", import_id="import-1", metadata=job)

    with pytest.raises(ImportPersistenceError, match="scan and compression"):
        await service.validate_encrypted_persistence(
            user_id="user-1", import_id="import-1", source_fingerprints=["fp-1"],
        )
    result = await service.compress_import_batch(
        user_id="user-1", import_id="import-1", batch_id="compress-0", sequence=0,
        final_batch=True, scan_sequence=1, source_fingerprint="fp-1",
        sanitized_messages=final["messages"], prior_summary=None,
    )

    assert result["summary"] == "cumulative summary"
    compressor.assert_awaited_once()
    assert compressor.await_args.kwargs["force"] is True
    await service.validate_encrypted_persistence(
        user_id="user-1", import_id="import-1", source_fingerprints=["fp-1"],
    )


@pytest.mark.anyio
async def test_persistence_requires_scan_and_compression_acknowledgements() -> None:
    service = AccountImportService(job_store=InMemoryImportJobStore(), import_lock=InMemoryImportLock())

    with pytest.raises(ImportPersistenceError, match="scan and compression"):
        await service.validate_encrypted_persistence(
            user_id="user-1",
            import_id="import-1",
            source_fingerprints=["fp-1"],
        )

    service = AccountImportService(
        job_store=InMemoryImportJobStore(),
        import_lock=InMemoryImportLock(),
        require_billing_for_paid=True,
    )
    preview = await service.preview_import(
        user_id="user-2", source="claude", chats=[_chat("fp-2", "short")],
        available_credits=0, imported_count_last_30_days=0, existing_fingerprints=set(),
    )
    await service.confirm_import(
        user_id="user-2", import_id=preview["import_id"], selected_fingerprints=["fp-2"], available_credits=0,
    )
    with pytest.raises(ImportPersistenceError, match="before any chat was imported"):
        await service.complete_import(
            user_id="user-2", import_id=preview["import_id"], imported_chat_ids=[],
            source_fingerprints=[], encrypted_record_counts={},
        )


@pytest.mark.anyio
async def test_single_batch_below_threshold_preserves_shipped_scan_then_persist_flow() -> None:
    service = AccountImportService(
        scanner=lambda content, **_: {
            "content": content,
            "usage": {"credits": 0, "model_id": "provider/scanner", "input_tokens": 1, "output_tokens": 0},
        },
        job_store=InMemoryImportJobStore(),
        import_lock=InMemoryImportLock(),
        require_billing_for_paid=True,
    )
    preview = await service.preview_import(
        user_id="user-1", source="claude", chats=[_chat("fp-1", "short")],
        available_credits=0, imported_count_last_30_days=0, existing_fingerprints=set(),
    )
    await service.confirm_import(
        user_id="user-1", import_id=preview["import_id"], selected_fingerprints=["fp-1"], available_credits=0,
    )
    await service.scan_import_batch(
        user_id="user-1", import_id=preview["import_id"], batch_id="scan-0", sequence=0,
        final_batch=True, chats=[_chat("fp-1", "short")],
    )

    await service.validate_encrypted_persistence(
        user_id="user-1", import_id=preview["import_id"], source_fingerprints=["fp-1"],
    )


@pytest.mark.anyio
async def test_concurrent_reservation_and_completion_are_exactly_once() -> None:
    billing = AsyncMock()
    billing.reserve.return_value = {"credits_reserved": 10}
    billing.settle.return_value = {"credits_charged": 4, "credits_released": 6, "balance": 5}
    store = InMemoryImportJobStore()
    service = AccountImportService(
        billing=billing,
        job_store=store,
        import_lock=InMemoryImportLock(),
    )

    await asyncio.gather(*[
        service.reserve_import_credits(
            user_id="user-1", import_id="import-1", selected_chat_count=1,
            available_credits=10, estimated_credits=10,
        )
        for _ in range(2)
    ])
    job = await store.get(user_id="user-1", import_id="import-1")
    job.update({"usage": {"credits": 4}, "persisted_chat_ids": ["chat-1"], "persisted_fingerprints": ["fp-1"]})
    await store.save(user_id="user-1", import_id="import-1", metadata=job)
    kwargs = {
        "user_id": "user-1", "import_id": "import-1", "imported_chat_ids": ["chat-1"],
        "source_fingerprints": ["fp-1"], "encrypted_record_counts": {"chats": 1, "messages": 1},
    }
    first, second = await asyncio.gather(service.complete_import(**kwargs), service.complete_import(**kwargs))

    billing.reserve.assert_awaited_once()
    billing.settle.assert_awaited_once()
    assert first == second


@pytest.mark.anyio
async def test_paid_reservation_refunds_when_final_metadata_save_fails() -> None:
    class FinalSaveFailureStore(InMemoryImportJobStore):
        failed = False

        async def save(self, *, user_id: str, import_id: str, metadata: dict) -> None:
            if metadata.get("status") == "reserved" and not self.failed:
                self.failed = True
                raise RuntimeError("metadata unavailable")
            await super().save(user_id=user_id, import_id=import_id, metadata=metadata)

    billing = AsyncMock()
    billing.reserve.return_value = {"credits_reserved": 10}
    billing.settle.return_value = {"credits_charged": 0, "credits_released": 10, "balance": 10}
    store = FinalSaveFailureStore()
    service = AccountImportService(billing=billing, job_store=store, import_lock=InMemoryImportLock())

    with pytest.raises(RuntimeError, match="metadata unavailable"):
        await service.reserve_import_credits(
            user_id="user-1", import_id="import-1", selected_chat_count=1,
            available_credits=10, estimated_credits=10,
        )

    billing.settle.assert_awaited_once_with(
        user_id="user-1", import_id="import-1", reserved_credits=10, measured_credits=0,
    )
    job = await store.get(user_id="user-1", import_id="import-1")
    assert job["status"] == "blocked"
    assert job["credits_reserved"] == 0


@pytest.mark.anyio
async def test_paid_reservation_persists_reconciliation_state_when_refund_fails() -> None:
    billing = AsyncMock()
    billing.reserve.return_value = {"credits_reserved": 11}
    billing.settle.side_effect = RuntimeError("refund unavailable")
    store = InMemoryImportJobStore()
    service = AccountImportService(billing=billing, job_store=store, import_lock=InMemoryImportLock())

    with pytest.raises(ImportCreditError, match="reconciliation"):
        await service.reserve_import_credits(
            user_id="user-1", import_id="import-1", selected_chat_count=1,
            available_credits=10, estimated_credits=10,
        )

    job = await store.get(user_id="user-1", import_id="import-1")
    assert job["status"] == "reservation_reconciliation_required"
    assert job["credits_reserved"] == 11
    assert job["retryable_failure"] == "reservation_refund_failed"


@pytest.mark.anyio
async def test_redis_lock_cleanup_preserves_operation_error_when_renewal_raises() -> None:
    client = SimpleNamespace(
        set=AsyncMock(return_value=True),
        eval=AsyncMock(side_effect=[RuntimeError("renewal failed"), 1]),
    )
    client_future = asyncio.get_running_loop().create_future()
    client_future.set_result(client)
    lock = RedisImportLock(SimpleNamespace(client=client_future))
    lock.LOCK_SECONDS = 0.003

    with pytest.raises(ValueError, match="operation failed"):
        async with lock.hold(user_id="user-1", import_id="import-1"):
            await asyncio.sleep(0.01)
            raise ValueError("operation failed")

    assert client.eval.await_count == 2
    assert "del" in client.eval.await_args_list[-1].args[0]


@pytest.mark.anyio
async def test_redis_lock_loss_is_visible_after_token_checked_cleanup() -> None:
    client = SimpleNamespace(
        set=AsyncMock(return_value=True),
        eval=AsyncMock(side_effect=[0, RuntimeError("cleanup failed")]),
    )
    client_future = asyncio.get_running_loop().create_future()
    client_future.set_result(client)
    lock = RedisImportLock(SimpleNamespace(client=client_future))
    lock.LOCK_SECONDS = 0.003

    with pytest.raises(RuntimeError, match="lock was lost"):
        async with lock.hold(user_id="user-1", import_id="import-1"):
            await asyncio.sleep(0.01)

    assert client.eval.await_count == 2
    assert "del" in client.eval.await_args_list[-1].args[0]


@pytest.mark.anyio
async def test_retryable_scanner_failure_is_durable_without_plaintext() -> None:
    store = InMemoryImportJobStore()
    service = AccountImportService(
        scanner=AsyncMock(side_effect=TimeoutError("provider timeout")),
        job_store=store,
        import_lock=InMemoryImportLock(),
    )
    with pytest.raises(ImportScanError):
        await service.scan_import_batch(
            user_id="user-1", import_id="import-1", batch_id="scan-0", sequence=0,
            final_batch=True, chats=[_chat("fp-1", "selected")],
        )

    status = await service.get_import_status(user_id="user-1", import_id="import-1")
    assert status["retryable_failure"] == "scanner_unavailable"
    assert "'content': 'selected'" not in repr(store.records)
