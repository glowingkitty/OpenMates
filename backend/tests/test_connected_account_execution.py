# backend/tests/test_connected_account_execution.py
#
# Contract tests for main-processor connected-account execution helpers.
# These tests ensure Calendar skills receive only server-injected access-token
# handles and hidden access-token context after exact token-ref matching.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from typing import Any

import pytest

from backend.tests.test_token_broker_refs import FakeCache, FakeEncryption


@pytest.mark.anyio
async def test_prepare_connected_account_execution_injects_handles_and_cleans_up(monkeypatch) -> None:
    from backend.apps.ai.processing import connected_account_execution
    from backend.apps.ai.processing.connected_account_execution import (
        cleanup_connected_account_token_artifacts,
        prepare_connected_account_skill_execution,
    )
    from backend.core.api.app.services.token_broker import TokenBrokerService

    async def exchange(refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        return {"access_token": f"access-for-{refresh_token}", "expires_in": 3600}

    monkeypatch.setattr(connected_account_execution, "exchange_google_refresh_token", exchange)

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
        action_scope={
            "calendar_id": "primary",
            "time_min": "2026-06-15T00:00:00Z",
            "time_max": "2026-06-16T00:00:00Z",
        },
    )

    context = await prepare_connected_account_skill_execution(
        app_id="calendar",
        skill_id="get-events",
        skill_arguments={
            "requests": [
                {
                    "calendar_id": "primary",
                    "time_min": "2026-06-15T00:00:00Z",
                    "time_max": "2026-06-16T00:00:00Z",
                }
            ]
        },
        connected_account_token_refs=[
            {
                "connected_account_id": "acct-1",
                "app_id": "calendar",
                "allowed_actions": ["read"],
                "turn_token_ref": ref.turn_token_ref,
                "action_scope": {
                    "calendar_id": "primary",
                    "time_min": "2026-06-15T00:00:00Z",
                    "time_max": "2026-06-16T00:00:00Z",
                },
            }
        ],
        user_id="user-1",
        user_vault_key_id="vault-key",
        chat_id="chat-1",
        message_id="msg-1",
        cache_service=cache,
        encryption_service=FakeEncryption(),
    )

    request = context.skill_arguments["requests"][0]
    handle = request["access_token_handle"]
    assert handle.startswith("ath_")
    assert context.skill_arguments["_connected_account_access_tokens"] == {
        handle: "access-for-refresh-secret"
    }
    assert context.token_artifacts == [
        {
            "turn_token_ref": ref.turn_token_ref,
            "access_token_handle": handle,
            "connected_account_id": "acct-1",
            "app_id": "calendar",
            "action": "read",
            "action_scope": {
                "calendar_id": "primary",
                "time_min": "2026-06-15T00:00:00Z",
                "time_max": "2026-06-16T00:00:00Z",
            },
        }
    ]

    await cleanup_connected_account_token_artifacts(
        token_artifacts=context.token_artifacts,
        cache_service=cache,
        encryption_service=FakeEncryption(),
    )

    assert any(ref.turn_token_ref in key for key in cache.deleted)
    assert any(handle in key for key in cache.deleted)


@pytest.mark.anyio
async def test_prepare_connected_account_execution_rejects_missing_ref() -> None:
    from backend.apps.ai.processing.connected_account_execution import prepare_connected_account_skill_execution

    with pytest.raises(PermissionError, match="permission"):
        await prepare_connected_account_skill_execution(
            app_id="calendar",
            skill_id="delete-event",
            skill_arguments={"requests": [{"calendar_id": "primary", "event_id": "event-1"}]},
            connected_account_token_refs=[],
            user_id="user-1",
            user_vault_key_id="vault-key",
            chat_id="chat-1",
            message_id="msg-1",
            cache_service=FakeCache(),
            encryption_service=FakeEncryption(),
        )
