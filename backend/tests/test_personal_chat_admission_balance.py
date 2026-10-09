"""Personal chat admission reads the encrypted wallet before inference."""

# contract-test-file: infrastructure
# contract-test: supporting surface=rest_api assertions=billing.credits.personal-chat-admission

from contextlib import asynccontextmanager
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import preprocessor
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.utils import server_mode


USER_ID = "personal-test-user"
USER_HASH = hashlib.sha256(USER_ID.encode("utf-8")).hexdigest()


class AdmissionLock:
    def __init__(self):
        self.subjects = []

    @asynccontextmanager
    async def hold(self, subject):
        self.subjects.append(subject)
        yield SimpleNamespace(acquired=True, lock_lost=False)


def billing_with_encrypted_balance(balance, *, projection=None, decrypted=None):
    cache = SimpleNamespace(
        get_billing_projection=AsyncMock(return_value=projection),
        set_billing_projection=AsyncMock(return_value=True),
    )
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[{
        "id": USER_ID, "vault_key_id": "vault-test", "encrypted_credit_balance": "cipher-current",
    }]))
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(
        return_value=str(balance) if decrypted is None else decrypted
    ))
    billing = BillingService(cache, directus, encryption)
    billing.settlement_lock = AdmissionLock()
    return billing, cache, directus, encryption


@pytest.mark.asyncio
@pytest.mark.parametrize("balance", [1, 0, -1, -500])
async def test_admission_reads_authoritative_encrypted_balance_without_ledger_write(balance):
    projection = {
        "credits": balance, "encrypted_balance": "cipher-current", "vault_key_id": "vault-test",
    }
    billing, cache, directus, encryption = billing_with_encrypted_balance(balance, projection=projection)

    assert await billing.get_authoritative_personal_balance(user_id=USER_ID, user_id_hash=USER_HASH) == balance
    assert billing.settlement_lock.subjects == [USER_HASH]
    directus.get_items.assert_awaited_once()
    assert directus.get_items.await_args.kwargs["no_cache"] is True
    encryption.decrypt_with_user_key.assert_awaited_once_with("cipher-current", "vault-test")
    cache.set_billing_projection.assert_not_awaited()
    assert not hasattr(directus, "update_item")


@pytest.mark.asyncio
@pytest.mark.parametrize("projection", [None, {
    "credits": 9, "encrypted_balance": "cipher-old", "vault_key_id": "vault-test",
}, {
    "credits": 9, "encrypted_balance": "cipher-current", "vault_key_id": "vault-test",
}])
async def test_admission_repairs_missing_or_stale_cache_from_durable_wallet(projection):
    billing, cache, _, _ = billing_with_encrypted_balance(-1, projection=projection)

    assert await billing.get_authoritative_personal_balance(user_id=USER_ID, user_id_hash=USER_HASH) == -1
    cache.set_billing_projection.assert_awaited_once_with(
        USER_ID, credits=-1, encrypted_balance="cipher-current", vault_key_id="vault-test",
    )


@pytest.mark.asyncio
async def test_admission_rejects_invalid_identity_or_undecryptable_wallet():
    billing, cache, directus, _ = billing_with_encrypted_balance(1, decrypted="invalid")
    with pytest.raises(ValueError, match="identity"):
        await billing.get_authoritative_personal_balance(user_id=USER_ID, user_id_hash="wrong")
    directus.get_items.assert_not_awaited()

    with pytest.raises(ValueError, match="balance"):
        await billing.get_authoritative_personal_balance(user_id=USER_ID, user_id_hash=USER_HASH)
    cache.set_billing_projection.assert_not_awaited()


@pytest.mark.asyncio
async def test_admission_does_not_repair_projection_after_lock_loss():
    billing, cache, _, _ = billing_with_encrypted_balance(-1)

    class LostLock(AdmissionLock):
        @asynccontextmanager
        async def hold(self, subject):
            self.subjects.append(subject)
            yield SimpleNamespace(acquired=False, lock_lost=True)

    billing.settlement_lock = LostLock()
    assert await billing.get_authoritative_personal_balance(user_id=USER_ID, user_id_hash=USER_HASH) == -1
    cache.get_billing_projection.assert_not_awaited()
    cache.set_billing_projection.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("balance,admitted", [(1, True), (0, False), (-1, False), (-500, False)])
async def test_personal_preprocessor_stops_before_provider_when_balance_not_positive(monkeypatch, balance, admitted):
    class ReachedRouting(Exception):
        pass

    request = AskSkillRequest(
        chat_id="chat-test", message_id="message-test", user_id=USER_ID,
        user_id_hash=USER_HASH,
        message_history=[{"role": "user", "content": "Help", "created_at": 1}],
        current_user_content="Help",
    )
    cached_user = {"auto_topup_low_balance_enabled": False}  # No plaintext credits field.
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value=cached_user))
    balance_read = AsyncMock(return_value=balance)
    load_ledger = AsyncMock(side_effect=ReachedRouting)
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(BillingService, "get_authoritative_personal_balance", balance_read)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", load_ledger)

    kwargs = dict(
        request_data=request, base_instructions={}, skill_config=SimpleNamespace(),
        cache_service=cache, secrets_manager=None, directus_service=None,
        encryption_service=None,
    )
    if admitted:
        result = await preprocessor.handle_preprocessing(**kwargs)
        assert result.rejection_reason != "insufficient_credits"
        load_ledger.assert_awaited_once()
        cache.get_user_by_id.assert_not_awaited()
    else:
        result = await preprocessor.handle_preprocessing(**kwargs)
        assert result.can_proceed is False
        assert result.rejection_reason == "insufficient_credits"
        load_ledger.assert_not_awaited()
    balance_read.assert_awaited_once_with(user_id=USER_ID, user_id_hash=USER_HASH)


@pytest.mark.asyncio
async def test_personal_preprocessor_fails_closed_when_balance_unavailable(monkeypatch):
    request = AskSkillRequest(
        chat_id="chat-test", message_id="message-test", user_id=USER_ID,
        user_id_hash=USER_HASH,
        message_history=[{"role": "user", "content": "Help", "created_at": 1}],
        current_user_content="Help",
    )
    load_ledger = AsyncMock()
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(
        BillingService, "get_authoritative_personal_balance",
        AsyncMock(side_effect=ValueError("No decryptable balance")),
    )
    monkeypatch.setattr(preprocessor, "load_skill_ledger", load_ledger)
    result = await preprocessor.handle_preprocessing(
        request_data=request, base_instructions={}, skill_config=SimpleNamespace(),
        cache_service=SimpleNamespace(get_user_by_id=AsyncMock(return_value={"credits": 100})),
        secrets_manager=None, directus_service=None, encryption_service=None,
    )
    assert result.can_proceed is False
    assert result.rejection_reason == "credit_balance_unavailable"
    load_ledger.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_topup_must_raise_authoritative_balance_before_admission(monkeypatch):
    request = AskSkillRequest(
        chat_id="chat-test", message_id="message-test", user_id=USER_ID,
        user_id_hash=USER_HASH,
        message_history=[{"role": "user", "content": "Help", "created_at": 1}],
        current_user_content="Help",
    )
    cached_user = {"auto_topup_low_balance_enabled": True}
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value=cached_user))
    balance_read = AsyncMock(side_effect=[0, 1])
    trigger = AsyncMock(return_value=True)
    load_ledger = AsyncMock(side_effect=RuntimeError("Routing reached"))
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(BillingService, "get_authoritative_personal_balance", balance_read)
    monkeypatch.setattr(BillingService, "_get_decrypted_payment_method", AsyncMock(return_value="payment-test"))
    monkeypatch.setattr(BillingService, "_trigger_low_balance_topup", trigger)
    monkeypatch.setattr(preprocessor, "load_skill_ledger", load_ledger)
    monkeypatch.setattr(preprocessor.asyncio, "sleep", AsyncMock())

    result = await preprocessor.handle_preprocessing(
        request_data=request, base_instructions={}, skill_config=SimpleNamespace(),
        cache_service=cache, secrets_manager=None, directus_service=None,
        encryption_service=None,
    )
    assert result.rejection_reason != "insufficient_credits"
    assert balance_read.await_count == 2
    trigger.assert_awaited_once_with(USER_ID, cached_user)
    load_ledger.assert_awaited_once()
