# backend/tests/test_revolut_connected_accounts.py
#
# Contract tests for Revolut Business connected-account execution plumbing.
# They verify read-only action mapping and encrypted-row secret boundaries without
# contacting Revolut Sandbox or production APIs.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

"""Revolut Business connected-account contract tests.

Revolut Business must use the existing encrypted connected-account and active-turn
token broker path. These tests avoid live provider calls and verify only local
registration, read-scope mapping, and plaintext-secret rejection.
"""

from __future__ import annotations

from typing import Any
from types import SimpleNamespace

import pytest

from backend.tests.test_token_broker_refs import FakeCache, FakeEncryption


def test_revolut_sensitive_fields_are_rejected_from_connected_account_rows() -> None:
    from backend.core.api.app.services.connected_accounts_service import ConnectedAccountRow

    with pytest.raises(ValueError, match="plaintext"):
        ConnectedAccountRow.validate_for_storage(
            {
                "id": "acct-1",
                "hashed_user_id": "hash-user",
                "encrypted_provider_type": "enc:revolut_business",
                "provider_type_hash": "hash:revolut_business",
                "encrypted_account_label": "enc:business",
                "encrypted_refresh_token_bundle": "enc:bundle",
                "encrypted_capabilities": "enc:caps",
                "encrypted_app_permissions": "enc:perms",
                "client_id": "client-secret-ish",
                "private_key": "-----BEGIN PRIVATE KEY-----",
            }
        )


@pytest.mark.anyio
async def test_revolut_connected_account_skill_maps_to_read_action(monkeypatch) -> None:
    from backend.apps.ai.processing import connected_account_execution
    from backend.apps.ai.processing.connected_account_execution import (
        connected_account_action_for_skill,
        is_connected_account_skill,
        prepare_connected_account_skill_execution,
    )
    from backend.core.api.app.services.token_broker import TokenBrokerService

    async def exchange(refresh_token: str, scope_context: dict[str, Any]) -> dict[str, Any]:
        assert scope_context["app_id"] == "finance"
        assert scope_context["action"] == "read"
        return {"access_token": f"revolut-access-for-{refresh_token}", "expires_in": 2400}

    monkeypatch.setattr(connected_account_execution, "exchange_refresh_token_for_provider", lambda _provider_id: exchange)

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
        app_id="finance",
        allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": "refresh-secret", "client_id": "client-1"},
        action_scope={"provider": "revolut_business"},
    )

    assert is_connected_account_skill("finance", "check_accounts") is True
    assert connected_account_action_for_skill("finance", "check_accounts") == "read"

    context = await prepare_connected_account_skill_execution(
        app_id="finance",
        skill_id="check_accounts",
        skill_arguments={"connected_account_requests": [{"source_ref": "revolut:sandbox"}]},
        connected_account_token_refs=[
            {
                "connected_account_id": "acct-1",
                "app_id": "finance",
                "provider_id": "revolut_business",
                "allowed_actions": ["read"],
                "turn_token_ref": ref.turn_token_ref,
                "action_scope": {"provider": "revolut_business"},
            }
        ],
        user_id="user-1",
        user_vault_key_id="vault-key",
        chat_id="chat-1",
        message_id="msg-1",
        cache_service=cache,
        encryption_service=FakeEncryption(),
    )

    request = context.skill_arguments["connected_account_requests"][0]
    handle = request["access_token_handle"]
    assert handle.startswith("ath_")
    assert context.skill_arguments["_connected_account_access_tokens"] == {
        handle: "revolut-access-for-refresh-secret"
    }
    assert context.token_artifacts[0]["app_id"] == "finance"
    assert context.token_artifacts[0]["provider_id"] == "revolut_business"
    assert context.token_artifacts[0]["action"] == "read"


@pytest.mark.anyio
async def test_revolut_refresh_exchange_generates_sandbox_client_assertion(monkeypatch) -> None:
    from backend.shared.providers.revolut_business import oauth

    signed_payloads: list[dict[str, Any]] = []
    posted: list[dict[str, Any]] = []

    def fake_jwt_encode(payload: dict[str, Any], private_key: str, algorithm: str) -> str:
        signed_payloads.append({"payload": payload, "private_key": private_key, "algorithm": algorithm})
        return "signed-assertion"

    class FakeResponse:
        is_error = False
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"access_token": "access-token", "refresh_token": "rotated-refresh", "expires_in": 3600}

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, url: str, *, data: dict[str, Any]) -> FakeResponse:
            posted.append({"url": url, "data": data})
            return FakeResponse()

    monkeypatch.setattr(oauth.jwt, "encode", fake_jwt_encode)
    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeAsyncClient)

    result = await oauth.exchange_revolut_business_refresh_token(
        "refresh-secret",
        {
            "refresh_token_envelope": {
                "provider": "revolut_business",
                "environment": "sandbox",
                "client_id": "client-1",
                "private_key_pem": "test-private-key",
            }
        },
    )

    assert result == {
        "access_token": "access-token",
        "expires_in": 3600,
        "rotated_refresh_token_bundle": {
            "provider": "revolut_business",
            "environment": "sandbox",
            "client_id": "client-1",
            "private_key_pem": "test-private-key",
            "refresh_token": "rotated-refresh",
        },
    }
    assert posted == [
        {
            "url": oauth.REVOLUT_SANDBOX_TOKEN_URL,
            "data": {
                "grant_type": "refresh_token",
                "refresh_token": "refresh-secret",
                "client_id": "client-1",
                "client_assertion_type": oauth.REVOLUT_CLIENT_ASSERTION_TYPE,
                "client_assertion": "signed-assertion",
            },
        }
    ]
    assert signed_payloads[0]["algorithm"] == "RS256"
    assert signed_payloads[0]["private_key"] == "test-private-key"
    assert signed_payloads[0]["payload"]["iss"] == "api.dev.openmates.org"
    assert signed_payloads[0]["payload"]["sub"] == "client-1"
    assert signed_payloads[0]["payload"]["aud"] == oauth.REVOLUT_AUDIENCE


@pytest.mark.anyio
async def test_revolut_connected_account_import_validation_reads_accounts(monkeypatch) -> None:
    from backend.core.api.app.routes import connected_accounts

    exchanged: list[dict[str, Any]] = []
    clients: list[dict[str, Any]] = []

    async def fake_exchange(refresh_token: str, scope_context: dict[str, Any]) -> dict[str, Any]:
        exchanged.append({"refresh_token": refresh_token, "scope_context": scope_context})
        return {"access_token": "access-token", "expires_in": 2400}

    class FakeRevolutClient:
        def __init__(self, *, access_token: str, base_url: str) -> None:
            clients.append({"access_token": access_token, "base_url": base_url})

        async def list_accounts(self) -> list[dict[str, str]]:
            return [{"id": "acct-1"}]

    monkeypatch.setattr(connected_accounts, "exchange_revolut_business_refresh_token", fake_exchange)
    monkeypatch.setattr(connected_accounts, "RevolutBusinessClient", FakeRevolutClient)

    response = await connected_accounts._validate_revolut_business_import(
        connected_accounts.ConnectedAccountImportValidationRequest(
            provider_id="revolut_business",
            app_id="finance",
            capabilities=["read"],
            refresh_token_envelope={
                "provider": "revolut_business",
                "environment": "sandbox",
                "client_id": "client-1",
                "private_key_pem": "private-key",
                "refresh_token": "refresh-token",
            },
        ),
        SimpleNamespace(id="user-1"),
    )

    assert response.valid is True
    assert response.provider_id == "revolut_business"
    assert response.app_id == "finance"
    assert exchanged[0]["refresh_token"] == "refresh-token"
    assert exchanged[0]["scope_context"]["app_id"] == "finance"
    assert clients == [{"access_token": "access-token", "base_url": connected_accounts.REVOLUT_BUSINESS_SANDBOX_API_BASE_URL}]
