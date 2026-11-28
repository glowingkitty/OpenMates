# backend/tests/test_connected_account_usage_metadata.py
#
# Usage metadata on connected accounts: last use is client-encrypted (a plaintext
# last_used_at is refused) and reconnect_required is marked when the provider
# rejects the stored grant.
#
# Specification: architecture.connected-accounts

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.services.connected_accounts_service import (
    find_plaintext_connected_account_fields,
)
from backend.core.api.app.services.token_broker import TokenBrokerService
from backend.shared.python_utils.connected_account_errors import ConnectedAccountTokenExchangeError


class FakeDirectus:
    def __init__(self) -> None:
        self.updates: list[tuple[str, str, dict[str, Any]]] = []

    async def update_item(self, collection: str, item_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self.updates.append((collection, item_id, data))
        return data


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        self.values[key] = value
        return True

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext: str, key_id: str) -> tuple[str, str]:
        return plaintext, key_id

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str:
        return ciphertext


# contract-test: supporting surface=rest_api assertions=connected-accounts.lifecycle.last-used
def test_last_use_is_only_accepted_client_encrypted() -> None:
    assert find_plaintext_connected_account_fields({"last_used_at": 1_000}) == ["last_used_at"]
    assert find_plaintext_connected_account_fields({"lastUsedAt": 1_000}) == ["lastUsedAt"]
    assert find_plaintext_connected_account_fields({"encrypted_last_used_at": "ciphertext"}) == []


async def _exchange_with_error(error: Exception, directus: FakeDirectus) -> None:
    async def failing(_token: str, _context: dict[str, Any]) -> dict[str, Any]:
        raise error

    broker = TokenBrokerService(
        cache_service=FakeCache(), encryption_service=FakeEncryption(),
        exchange_refresh_token=failing, directus_service=directus,
    )
    ref = await broker.create_turn_token_ref(
        user_id="u1", user_vault_key_id="k1", connected_account_id="acc_1", chat_id="c1",
        message_id="m1", app_id="calendar", provider_id="google", allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": "rt_synthetic"},
    )
    await broker.exchange_turn_token_ref(
        turn_token_ref=ref.turn_token_ref, user_id="u1", user_vault_key_id="k1", chat_id="c1",
        message_id="m1", app_id="calendar", action="read", provider_id="google",
    )


# contract-test: supporting surface=rest_api assertions=connected-accounts.lifecycle.reconnect-status
@pytest.mark.asyncio
async def test_invalid_grant_marks_account_reconnect_required() -> None:
    directus = FakeDirectus()
    error = ConnectedAccountTokenExchangeError(
        "rejected", provider_id="google", status_code=400, provider_error="invalid_grant",
    )
    with pytest.raises(ConnectedAccountTokenExchangeError):
        await _exchange_with_error(error, directus)
    assert directus.updates == [("connected_accounts", "acc_1", {"connector_status": "reconnect_required"})]


# contract-test: supporting surface=rest_api assertions=connected-accounts.lifecycle.reconnect-status
@pytest.mark.asyncio
async def test_transient_exchange_failure_does_not_mark_reconnect() -> None:
    directus = FakeDirectus()
    error = ConnectedAccountTokenExchangeError("down", provider_id="google", status_code=503)
    with pytest.raises(ConnectedAccountTokenExchangeError):
        await _exchange_with_error(error, directus)
    assert directus.updates == []
