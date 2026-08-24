# contract-test-file: billing settlement reliability
"""Red contract tests for cache-first, completion-safe personal settlement.

The service currently performs an authoritative Directus read before every
charge and re-raises exhausted conflicts. These tests define the approved
settlement boundary before the reliability implementation is introduced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.core.api.app.services import billing_settlement_service as billing_settlement_tasks


def _charge_source() -> str:
    service_path = Path(__file__).parents[1] / "core/api/app/services/billing_service.py"
    source = service_path.read_text(encoding="utf-8")
    method_start = source.index("    async def charge_user_credits(")
    method_end = source.index("    async def refund_user_credits(", method_start)
    return source[method_start:method_end]


def _stream_finalization_source() -> str:
    consumer_path = Path(__file__).parents[1] / "apps/ai/tasks/stream_consumer.py"
    source = consumer_path.read_text(encoding="utf-8")
    final_marker_index = source.rindex("is_final=True")
    return source[final_marker_index:]


# contract-test: direct surface=rest_api assertions=billing.credits.encrypted-authority-cache-projection,billing.credits.minimal-durable-io
def test_valid_cache_projection_avoids_precommit_directus_balance_read() -> None:
    source = _charge_source()

    assert "get_billing_projection" in source
    assert "get_items(\n                    \"directus_users\"" not in source


# contract-test: direct surface=rest_api assertions=billing.credits.encrypted-authority-cache-projection,billing.credits.minimal-durable-io
def test_cache_miss_recovers_one_encrypted_projection_and_rebuilds_cache() -> None:
    source = _charge_source()

    assert "get_billing_projection" in source
    assert "set_billing_projection" in source
    assert "encrypted_balance" in source


# contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge,billing.credits.minimal-durable-io
def test_personal_charges_use_a_hashed_subject_lock() -> None:
    source = _charge_source()

    assert "billing_subject" in source
    assert "settlement_lock" in source
    assert "user_id_hash" in source


# contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge,billing.credits.encrypted-authority-cache-projection
def test_lock_loss_uses_durable_cas_without_duplicate_mutation() -> None:
    source = _charge_source()

    assert "lock_lost" in source
    assert "stale_credit_balance" in source
    assert "commit_personal_charge" in source
    assert "expected_encrypted_balance" in source


# contract-test: direct surface=rest_api assertions=billing.credits.retryable-completion-safe
def test_retryable_conflict_creates_or_reuses_a_durable_pending_settlement() -> None:
    source = _charge_source()

    assert "create_or_reuse_pending_settlement" in source
    assert "idempotency_key" in source
    assert "retry_scheduled" in source


# contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge,billing.credits.retryable-completion-safe
@pytest.mark.asyncio
async def test_crash_after_commit_replay_reads_the_original_charge_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def execute(_self: object, operation: str, _data: object) -> dict[str, object]:
        calls.append(operation)
        return {"state": "committed", "charge_id": "charge-1", "idempotent": True}

    monkeypatch.setattr(billing_settlement_tasks.SubChatOrchestrationService, "execute", execute)
    result = await billing_settlement_tasks.process_pending_settlement(
        outbox_id="outbox-1",
        charge_id="charge-1",
        user_id_hash="owner-hash",
        directus_service=object(),
        cache_service=object(),
        encryption_service=object(),
    )

    assert result["state"] == "committed"
    assert result["idempotent"] is True
    assert calls == ["replay_pending_settlement"]


# contract-test: direct surface=rest_api assertions=billing.credits.retryable-completion-safe
@pytest.mark.asyncio
async def test_exhausted_settlement_retries_transition_to_observable_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[str] = []

    async def execute(_self: object, operation: str, _data: object) -> dict[str, object]:
        operations.append(operation)
        if operation == "replay_pending_settlement":
            return {
                "state": "retry_scheduled",
                "claimed": True,
                "attempts": billing_settlement_tasks.MAX_SETTLEMENT_ATTEMPTS,
                "user_id": "user-1",
                "vault_key_id": "key-1",
                "encrypted_settlement_payload": "ciphertext",
            }
        return {"state": "manual_review", "alert_required": True}

    class Encryption:
        async def decrypt_with_user_key(self, _ciphertext: str, _key_id: str) -> str:
            return json.dumps({
                "credits_to_deduct": 8,
                "app_id": "ai",
                "skill_id": "ask",
                "idempotency_key": "charge-1",
            })

    class Cache:
        def __init__(self) -> None:
            self.metrics: list[tuple[str, int]] = []

        async def increment_stat(self, name: str, amount: int) -> None:
            self.metrics.append((name, amount))

    class StaleBilling:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def charge_user_credits(self, **_kwargs: object) -> None:
            raise HTTPException(status_code=409, detail="stale_credit_balance")

    cache = Cache()
    monkeypatch.setattr(billing_settlement_tasks.SubChatOrchestrationService, "execute", execute)
    result = await billing_settlement_tasks.process_pending_settlement(
        outbox_id="outbox-1",
        charge_id="charge-1",
        user_id_hash="owner-hash",
        directus_service=object(),
        cache_service=cache,
        encryption_service=Encryption(),
        billing_service_factory=StaleBilling,
    )

    assert result == {"state": "manual_review", "alert_required": True}
    assert operations == ["replay_pending_settlement", "transition_pending_settlement_to_manual_review"]
    assert cache.metrics == [("billing_settlement_manual_review", 1)]


# contract-test: direct surface=rest_api assertions=billing.credits.retryable-completion-safe
@pytest.mark.asyncio
async def test_retryable_settlement_attempt_uses_bounded_durable_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    async def execute(_self: object, _operation: str, _data: object) -> dict[str, object]:
        return {
            "state": "retry_scheduled",
            "claimed": True,
            "attempts": 1,
            "user_id": "user-1",
            "vault_key_id": "key-1",
            "encrypted_settlement_payload": "ciphertext",
        }

    class Encryption:
        async def decrypt_with_user_key(self, _ciphertext: str, _key_id: str) -> str:
            return json.dumps({
                "credits_to_deduct": 8,
                "app_id": "ai",
                "skill_id": "ask",
                "idempotency_key": "charge-1",
            })

    class StaleBilling:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def charge_user_credits(self, **kwargs: object) -> None:
            assert kwargs["idempotency_key"] == "charge-1"
            assert kwargs["_defer_exhausted_conflict"] is False
            raise HTTPException(status_code=409, detail="stale_credit_balance")

    monkeypatch.setattr(billing_settlement_tasks.SubChatOrchestrationService, "execute", execute)
    result = await billing_settlement_tasks.process_pending_settlement(
        outbox_id="outbox-1",
        charge_id="charge-1",
        user_id_hash="owner-hash",
        directus_service=object(),
        cache_service=object(),
        encryption_service=Encryption(),
        billing_service_factory=StaleBilling,
    )

    assert result == {"state": "retry_scheduled", "attempts": 1, "countdown": 5}


# contract-test: direct surface=rest_api assertions=billing.credits.retryable-completion-safe
@pytest.mark.asyncio
async def test_nonretryable_settlement_failure_moves_directly_to_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[str] = []

    async def execute(_self: object, operation: str, _data: object) -> dict[str, object]:
        operations.append(operation)
        if operation == "replay_pending_settlement":
            return {
                "state": "retry_scheduled",
                "claimed": True,
                "attempts": 1,
                "user_id": "user-1",
                "vault_key_id": "key-1",
                "encrypted_settlement_payload": "ciphertext",
            }
        return {"state": "manual_review", "alert_required": True}

    class Encryption:
        async def decrypt_with_user_key(self, _ciphertext: str, _key_id: str) -> str:
            return json.dumps({
                "credits_to_deduct": 8,
                "app_id": "ai",
                "skill_id": "ask",
                "idempotency_key": "charge-1",
            })

    class Cache:
        async def increment_stat(self, _name: str, _amount: int) -> None:
            pass

    class InvalidBilling:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def charge_user_credits(self, **_kwargs: object) -> None:
            raise HTTPException(status_code=400, detail="invalid_charge")

    monkeypatch.setattr(billing_settlement_tasks.SubChatOrchestrationService, "execute", execute)
    result = await billing_settlement_tasks.process_pending_settlement(
        outbox_id="outbox-1",
        charge_id="charge-1",
        user_id_hash="owner-hash",
        directus_service=object(),
        cache_service=Cache(),
        encryption_service=Encryption(),
        billing_service_factory=InvalidBilling,
    )

    assert result["state"] == "manual_review"
    assert operations == ["replay_pending_settlement", "transition_pending_settlement_to_manual_review"]


# contract-test: supporting surface=rest_api assertions=billing.credits.retryable-completion-safe
def test_only_durably_deferred_conflicts_avoid_post_finalization_failure() -> None:
    assert "raise billing_error" in _stream_finalization_source()
    assert "create_or_reuse_pending_settlement" in _charge_source()
    assert "durable_charge_result" in _charge_source()
    assert "Post-commit billing projection failed" in _charge_source()
