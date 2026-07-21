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


@pytest.mark.anyio
async def test_token_ref_exchange_requires_matching_provider_id() -> None:
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
        provider_id="google",
        allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": "refresh-secret", "provider": "google"},
    )

    metadata = await broker.get_turn_token_ref_metadata(turn_token_ref=ref.turn_token_ref)
    assert metadata and metadata["provider_id"] == "google"

    with pytest.raises(PermissionError, match="provider"):
        await broker.exchange_turn_token_ref(
            turn_token_ref=ref.turn_token_ref,
            user_id="user-1",
            user_vault_key_id="vault-key",
            chat_id="chat-1",
            message_id="msg-1",
            app_id="calendar",
            provider_id="revolut_business",
            action="read",
        )


@pytest.mark.anyio
async def test_turn_token_ref_is_single_use_after_successful_exchange() -> None:
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
        provider_id="google",
        allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": "refresh-secret", "provider": "google"},
    )

    handle = await broker.exchange_turn_token_ref(
        turn_token_ref=ref.turn_token_ref,
        user_id="user-1",
        user_vault_key_id="vault-key",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        provider_id="google",
        action="read",
    )

    assert handle.access_token_handle.startswith("ath_")
    with pytest.raises(PermissionError, match="expired or not found"):
        await broker.exchange_turn_token_ref(
            turn_token_ref=ref.turn_token_ref,
            user_id="user-1",
            user_vault_key_id="vault-key",
            chat_id="chat-1",
            message_id="msg-1",
            app_id="calendar",
            provider_id="google",
            action="read",
        )


@pytest.mark.anyio
async def test_turn_token_ref_creation_rejects_actions_outside_app_provider_registry() -> None:
    from backend.core.api.app.services.token_broker import TokenBrokerService

    async def exchange(_refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        return {"access_token": "access-secret", "expires_in": 3600}

    broker = TokenBrokerService(
        cache_service=FakeCache(),
        encryption_service=FakeEncryption(),
        exchange_refresh_token=exchange,
    )

    with pytest.raises(ValueError, match="unsupported connected-account action"):
        await broker.create_turn_token_ref(
            user_id="user-1",
            user_vault_key_id="vault-key",
            connected_account_id="acct-1",
            chat_id="chat-1",
            message_id="msg-1",
            app_id="finance",
            provider_id="revolut_business",
            allowed_actions=["write"],
            refresh_token_envelope={"refresh_token": "refresh-secret", "provider": "revolut_business"},
        )


def test_token_broker_route_rejects_connected_account_provider_mismatch() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.models.user import User
    from backend.core.api.app.routes import token_broker
    from backend.core.api.app.services.directus.team_methods import hash_id

    class FakeDirectus:
        async def get_items(self, _collection: str, params: dict[str, Any] | None = None):
            assert params and params["filter[id][_eq]"] == "acct-1"
            return [
                {
                    "id": "acct-1",
                    "hashed_user_id": hash_id("user-1"),
                    "provider_type_hash": hash_id("revolut_business"),
                }
            ]

    app = FastAPI()
    app.state.cache_service = FakeCache()
    app.state.encryption_service = FakeEncryption()
    app.state.directus_service = FakeDirectus()
    app.include_router(token_broker.router)
    app.dependency_overrides[token_broker.get_current_user] = lambda: User(
        id="user-1",
        username="alice",
        vault_key_id="vault-key",
    )
    client = TestClient(app)

    response = client.post(
        "/v1/token-broker/turn-token-refs",
        json={
            "chat_id": "chat-1",
            "message_id": "msg-1",
            "refs": [
                {
                    "connected_account_id": "acct-1",
                    "app_id": "calendar",
                    "provider_id": "google",
                    "allowed_actions": ["read"],
                    "refresh_token_envelope": {"refresh_token": "refresh-secret", "provider": "google"},
                }
            ],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Connected account provider mismatch"
