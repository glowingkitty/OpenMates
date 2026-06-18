# backend/tests/test_token_broker_refs.py
#
# Token broker contract tests for client-mediated connected-account actions.
# The broker keeps active-turn refresh-token envelopes Vault-encrypted until an
# exact account/action is authorized, then lazily exchanges only the selected ref.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import base64
import json
from typing import Any

import pytest


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.deleted: list[str] = []

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        self.values[key] = {"value": value, "ttl": ttl}
        return True

    async def get(self, key: str) -> Any:
        item = self.values.get(key)
        return None if item is None else item["value"]

    async def delete(self, key: str) -> bool:
        self.deleted.append(key)
        self.values.pop(key, None)
        return True


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext: str, key_id: str) -> tuple[str, int]:
        encoded = base64.urlsafe_b64encode(plaintext.encode()).decode()
        return f"vault:{key_id}:{encoded}", 1

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str:
        prefix = f"vault:{key_id}:"
        if not ciphertext.startswith(prefix):
            raise ValueError("wrong key")
        return base64.urlsafe_b64decode(ciphertext.removeprefix(prefix)).decode()


@pytest.mark.anyio
async def test_token_ref_stores_refresh_envelope_encrypted_without_eager_exchange() -> None:
    from backend.core.api.app.services.token_broker import TokenBrokerService

    exchange_calls: list[str] = []

    async def exchange(refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        exchange_calls.append(refresh_token)
        return {"access_token": "access", "expires_in": 3600}

    broker = TokenBrokerService(
        cache_service=FakeCache(),
        encryption_service=FakeEncryption(),
        exchange_refresh_token=exchange,
    )

    ref = await broker.create_turn_token_ref(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": "refresh-secret"},
    )

    stored_values = list(broker.cache.values.values())
    assert ref.turn_token_ref.startswith("tref_")
    assert exchange_calls == []
    assert "refresh-secret" not in json.dumps(stored_values)
    assert "vault:vault-key" in json.dumps(stored_values)


@pytest.mark.anyio
async def test_lazy_exchange_requires_matching_scope_and_deletes_refs() -> None:
    from backend.core.api.app.services.token_broker import TokenBrokerService

    exchange_calls: list[str] = []

    async def exchange(refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        exchange_calls.append(refresh_token)
        return {"access_token": "access-secret", "expires_in": 3600}

    cache = FakeCache()
    broker = TokenBrokerService(
        cache_service=cache,
        encryption_service=FakeEncryption(),
        exchange_refresh_token=exchange,
    )

    ref = await broker.create_turn_token_ref(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": "refresh-secret"},
    )

    with pytest.raises(PermissionError, match="action"):
        await broker.exchange_turn_token_ref(
            turn_token_ref=ref.turn_token_ref,
            user_id="user-1",
            user_vault_key_id="vault-key",
            chat_id="chat-1",
            message_id="msg-1",
            app_id="calendar",
            action="delete",
        )

    handle = await broker.exchange_turn_token_ref(
        turn_token_ref=ref.turn_token_ref,
        user_id="user-1",
        user_vault_key_id="vault-key",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        action="read",
    )

    assert exchange_calls == ["refresh-secret"]
    assert handle.access_token_handle.startswith("ath_")
    assert "access-secret" not in json.dumps(cache.values)

    await broker.delete_turn_artifacts(ref.turn_token_ref, handle.access_token_handle)
    assert any(ref.turn_token_ref in key for key in cache.deleted)
    assert any(handle.access_token_handle in key for key in cache.deleted)


@pytest.mark.anyio
async def test_access_token_handle_resolves_only_for_matching_scope() -> None:
    from backend.core.api.app.services.token_broker import TokenBrokerService

    async def exchange(_refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        return {"access_token": "access-secret", "expires_in": 3600}

    broker = TokenBrokerService(
        cache_service=FakeCache(),
        encryption_service=FakeEncryption(),
        exchange_refresh_token=exchange,
    )
    ref = await broker.create_turn_token_ref(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": "refresh-secret"},
        action_scope={"calendar_id": "primary"},
    )
    handle = await broker.exchange_turn_token_ref(
        turn_token_ref=ref.turn_token_ref,
        user_id="user-1",
        user_vault_key_id="vault-key",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        action="read",
        action_scope={"calendar_id": "primary"},
    )

    with pytest.raises(PermissionError, match="action scope"):
        await broker.resolve_access_token_handle(
            access_token_handle=handle.access_token_handle,
            user_id="user-1",
            user_vault_key_id="vault-key",
            chat_id="chat-1",
            message_id="msg-1",
            app_id="calendar",
            action="read",
            action_scope={"calendar_id": "other"},
        )

    access_token = await broker.resolve_access_token_handle(
        access_token_handle=handle.access_token_handle,
        user_id="user-1",
        user_vault_key_id="vault-key",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        action="read",
        action_scope={"calendar_id": "primary"},
    )

    assert access_token == "access-secret"
