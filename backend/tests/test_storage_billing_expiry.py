# contract-test: supporting surface=rest_api assertions=billing.storage.personal-expiry-selection,billing.storage.expiry-invoice-closure,billing.storage.four-warning-expiry
"""An authoritative affordability read gates expiry."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.tasks import storage_billing_tasks as tasks
from backend.core.api.app.services.storage_billing_notice_service import read_storage_notice

OWNER = "22222222-2222-4222-8222-222222222222"
EPISODE = "33333333-3333-4333-8333-333333333333"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry,billing.storage.personal-expiry-selection
async def test_disabled_expiry_does_not_read_or_remove(monkeypatch):
    monkeypatch.delenv("STORAGE_UNPAID_EXPIRY_ENABLED", raising=False)
    result = await tasks._apply_due_expiry(
        OWNER, EPISODE, directus=None, encryption=None, orchestration=None,
    )
    assert result == {"applied": False, "held": True, "reason": "expiry_disabled"}


@pytest.mark.asyncio
@pytest.mark.parametrize("credits,applies", [(100, False), (-497, False), (-498, True), (-500, True)])
# contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement,billing.storage.personal-expiry-selection
async def test_fresh_balance_and_exact_ciphertext_gate_removal(monkeypatch, credits, applies):
    monkeypatch.setenv("STORAGE_UNPAID_EXPIRY_ENABLED", "1")
    monkeypatch.setenv("S3_REGIONS", "nbg1,hel1")
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock(return_value={
        "encrypted_credit_balance": "fresh-sealed", "vault_key_id": "key",
    }))
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value=str(credits)))
    async def operation(name, data):
        if name == "list_storage_debt":
            return {"periods": [{"id": "warned", "credits_due": 3}]}
        assert name == "apply_storage_expiry"
        assert data["expected_encrypted_balance"] == "fresh-sealed"
        assert data["regions"] == ["nbg1", "hel1"]
        assert data["hashed_user_id"] == tasks.hashlib.sha256(OWNER.encode()).hexdigest()
        return {"applied": True, "waived_period_ids": ["warned"]}
    orchestration = SimpleNamespace(execute=AsyncMock(side_effect=operation))
    result = await tasks._apply_due_expiry(
        OWNER, EPISODE, directus=directus, encryption=encryption, orchestration=orchestration,
    )
    assert result["applied"] is applies
    assert orchestration.execute.await_count == (2 if applies else 1)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement,billing.storage.personal-expiry-selection
async def test_balance_outage_prevents_expiry(monkeypatch):
    monkeypatch.setenv("STORAGE_UNPAID_EXPIRY_ENABLED", "1")
    orchestration = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(RuntimeError, match="balance is unavailable"):
        await tasks._apply_due_expiry(
            OWNER, EPISODE, directus=SimpleNamespace(get_user_fields_direct=AsyncMock(return_value=None)),
            encryption=None, orchestration=orchestration,
        )
    orchestration.execute.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry,billing.storage.personal-expiry-selection
async def test_notice_is_owner_scoped_and_drops_internal_routing():
    unit_id = "a" * 64
    internal = {
        "episode_id": EPISODE, "warning_count": 1, "deadline_at": 1000,
        "manual_review": False, "has_more": False,
        "units": [{"unit_id": unit_id, "kind": "upload", "resource_id": "file-id",
                   "oldest_at": 10, "bytes": 20, "fingerprint": "private",
                   "object_key": "private/key"}],
    }
    orchestration = SimpleNamespace(execute=AsyncMock(return_value=internal))
    notice = await read_storage_notice(orchestration, OWNER)
    payload = notice.model_dump()
    assert "fingerprint" not in payload["units"][0]
    assert "object_key" not in payload["units"][0]
    assert orchestration.execute.await_args.args[1]["user_id"] == OWNER


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry,billing.storage.personal-expiry-selection
async def test_incomplete_notice_cursor_is_visible_failure():
    orchestration = SimpleNamespace(execute=AsyncMock(return_value={
        "episode_id": EPISODE, "units": [], "has_more": True,
    }))
    with pytest.raises(RuntimeError, match="cursor"):
        await read_storage_notice(orchestration, OWNER)
