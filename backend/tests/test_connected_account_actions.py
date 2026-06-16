# backend/tests/test_connected_account_actions.py
#
# Route-level tests for connected-account operation actions.
# Undo must remain client-mediated through fresh token refs and encrypted journal
# payloads, never long-lived server-side provider grants.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from backend.tests.test_token_broker_refs import FakeCache, FakeEncryption

redis_stub = types.ModuleType("redis")
redis_stub.__path__ = []
redis_stub.exceptions = types.SimpleNamespace(ConnectionError=ConnectionError)
redis_asyncio_stub = types.ModuleType("redis.asyncio")
redis_asyncio_stub.Redis = object
redis_stub.asyncio = redis_asyncio_stub
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)


class FakeUser:
    id = "user-1"
    vault_key_id = "vault-key"


class FakeDirectus:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.updated: dict[str, Any] | None = None

    async def get_items(self, collection: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        assert collection == "connected_account_operation_journal"
        assert params["filter[action_id][_eq]"] == self.row["action_id"]
        return [self.row]

    async def update_item(self, collection: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert collection == "connected_account_operation_journal"
        assert item_id == self.row["id"]
        self.updated = payload
        return self.row | payload


class FakeCalendarEvent:
    def __init__(self, event_id: str) -> None:
        self.id = event_id


@pytest.mark.anyio
async def test_undo_create_event_deletes_created_event_and_marks_journal(monkeypatch) -> None:
    from backend.core.api.app.routes import connected_account_actions
    from backend.core.api.app.routes.connected_account_actions import (
        UndoConnectedAccountActionRequest,
        undo_connected_account_action,
    )
    from backend.core.api.app.services.connected_account_operation_journal import (
        ConnectedAccountOperationJournalService,
    )
    from backend.core.api.app.services.token_broker import TokenBrokerService

    deleted_events: list[dict[str, str]] = []

    async def exchange(refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        return {"access_token": f"access-for-{refresh_token}"}

    class FakeCalendarClient:
        def __init__(self, *, access_token: str) -> None:
            assert access_token == "access-for-refresh-secret"

        async def delete_event(self, *, calendar_id: str, event_id: str) -> dict[str, str]:
            deleted_events.append({"calendar_id": calendar_id, "event_id": event_id})
            return {"status": "deleted", "event_id": event_id}

    monkeypatch.setattr(connected_account_actions, "exchange_google_refresh_token", exchange)
    monkeypatch.setattr(connected_account_actions, "GoogleCalendarClient", FakeCalendarClient)

    encryption = FakeEncryption()
    journal = ConnectedAccountOperationJournalService(encryption_service=encryption)
    row = await journal.build_entry(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        app_id="calendar",
        action="write",
        decision="completed",
        action_id="act-1",
        undo_payload={
            "events": [
                {
                    "undo_type": "delete_created_event",
                    "calendar_id": "primary",
                    "event_id": "event-1",
                }
            ]
        },
    )
    directus = FakeDirectus(row)
    cache = FakeCache()
    broker = TokenBrokerService(
        cache_service=cache,
        encryption_service=encryption,
        exchange_refresh_token=exchange,
    )
    ref = await broker.create_turn_token_ref(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        allowed_actions=["delete"],
        refresh_token_envelope={"refresh_token": "refresh-secret"},
        action_scope={"calendar_id": "primary", "event_id": "event-1"},
    )

    response = await undo_connected_account_action(
        "act-1",
        UndoConnectedAccountActionRequest(
            turn_token_ref=ref.turn_token_ref,
            chat_id="chat-1",
            message_id="msg-1",
        ),
        current_user=FakeUser(),
        directus_service=directus,
        cache_service=cache,
        encryption_service=encryption,
    )

    assert response.status == "undone"
    assert response.undo_type == "delete_created_event"
    assert deleted_events == [{"calendar_id": "primary", "event_id": "event-1"}]
    assert directus.updated is not None
    assert directus.updated["decision"] == "undo_success"
    assert "refresh-secret" not in str(directus.updated)


@pytest.mark.anyio
async def test_undo_update_restores_previous_event_snapshot(monkeypatch) -> None:
    from backend.core.api.app.routes import connected_account_actions
    from backend.core.api.app.routes.connected_account_actions import (
        UndoConnectedAccountActionRequest,
        undo_connected_account_action,
    )
    from backend.core.api.app.services.connected_account_operation_journal import (
        ConnectedAccountOperationJournalService,
    )
    from backend.core.api.app.services.token_broker import TokenBrokerService

    updated_events: list[dict[str, Any]] = []

    async def exchange(refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        return {"access_token": f"access-for-{refresh_token}"}

    class FakeCalendarClient:
        def __init__(self, *, access_token: str) -> None:
            assert access_token == "access-for-refresh-secret"

        async def update_event(self, **kwargs) -> FakeCalendarEvent:
            updated_events.append(kwargs)
            return FakeCalendarEvent(kwargs["event_id"])

    monkeypatch.setattr(connected_account_actions, "exchange_google_refresh_token", exchange)
    monkeypatch.setattr(connected_account_actions, "GoogleCalendarClient", FakeCalendarClient)

    encryption = FakeEncryption()
    journal = ConnectedAccountOperationJournalService(encryption_service=encryption)
    row = await journal.build_entry(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        app_id="calendar",
        action="update",
        decision="completed",
        action_id="act-update",
        undo_payload={
            "events": [
                {
                    "undo_type": "restore_updated_event",
                    "calendar_id": "primary",
                    "event_id": "event-1",
                    "snapshot": {
                        "title": "Original title",
                        "start": "2026-06-15T10:00:00Z",
                        "end": "2026-06-15T11:00:00Z",
                    },
                }
            ]
        },
    )
    cache = FakeCache()
    broker = TokenBrokerService(cache_service=cache, encryption_service=encryption, exchange_refresh_token=exchange)
    ref = await broker.create_turn_token_ref(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        allowed_actions=["update"],
        refresh_token_envelope={"refresh_token": "refresh-secret"},
        action_scope={"calendar_id": "primary", "event_id": "event-1"},
    )

    response = await undo_connected_account_action(
        "act-update",
        UndoConnectedAccountActionRequest(turn_token_ref=ref.turn_token_ref, chat_id="chat-1", message_id="msg-1"),
        current_user=FakeUser(),
        directus_service=FakeDirectus(row),
        cache_service=cache,
        encryption_service=encryption,
    )

    assert response.status == "undone"
    assert response.undo_type == "restore_updated_event"
    assert response.events == [{"calendar_id": "primary", "event_id": "event-1", "status": "restored"}]
    assert updated_events[0]["title"] == "Original title"


@pytest.mark.anyio
async def test_undo_delete_recreates_deleted_event_snapshot(monkeypatch) -> None:
    from backend.core.api.app.routes import connected_account_actions
    from backend.core.api.app.routes.connected_account_actions import (
        UndoConnectedAccountActionRequest,
        undo_connected_account_action,
    )
    from backend.core.api.app.services.connected_account_operation_journal import (
        ConnectedAccountOperationJournalService,
    )
    from backend.core.api.app.services.token_broker import TokenBrokerService

    created_events: list[dict[str, Any]] = []

    async def exchange(refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        return {"access_token": f"access-for-{refresh_token}"}

    class FakeCalendarClient:
        def __init__(self, *, access_token: str) -> None:
            assert access_token == "access-for-refresh-secret"

        async def create_event(self, **kwargs) -> FakeCalendarEvent:
            created_events.append(kwargs)
            return FakeCalendarEvent("event-recreated")

    monkeypatch.setattr(connected_account_actions, "exchange_google_refresh_token", exchange)
    monkeypatch.setattr(connected_account_actions, "GoogleCalendarClient", FakeCalendarClient)

    encryption = FakeEncryption()
    journal = ConnectedAccountOperationJournalService(encryption_service=encryption)
    row = await journal.build_entry(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        app_id="calendar",
        action="delete",
        decision="completed",
        action_id="act-delete",
        undo_payload={
            "events": [
                {
                    "undo_type": "recreate_deleted_event",
                    "calendar_id": "primary",
                    "event_id": "event-1",
                    "snapshot": {
                        "title": "Deleted title",
                        "start": "2026-06-15T10:00:00Z",
                        "end": "2026-06-15T11:00:00Z",
                    },
                }
            ]
        },
    )
    cache = FakeCache()
    broker = TokenBrokerService(cache_service=cache, encryption_service=encryption, exchange_refresh_token=exchange)
    ref = await broker.create_turn_token_ref(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        allowed_actions=["write"],
        refresh_token_envelope={"refresh_token": "refresh-secret"},
        action_scope={"calendar_id": "primary", "event_id": "event-1"},
    )

    response = await undo_connected_account_action(
        "act-delete",
        UndoConnectedAccountActionRequest(turn_token_ref=ref.turn_token_ref, chat_id="chat-1", message_id="msg-1"),
        current_user=FakeUser(),
        directus_service=FakeDirectus(row),
        cache_service=cache,
        encryption_service=encryption,
    )

    assert response.status == "undone"
    assert response.undo_type == "recreate_deleted_event"
    assert response.events == [{"calendar_id": "primary", "event_id": "event-recreated", "status": "recreated"}]
    assert created_events[0]["title"] == "Deleted title"


@pytest.mark.anyio
async def test_undo_rejects_already_undone_action() -> None:
    from fastapi import HTTPException

    from backend.core.api.app.routes.connected_account_actions import (
        UndoConnectedAccountActionRequest,
        undo_connected_account_action,
    )
    from backend.core.api.app.services.connected_account_operation_journal import (
        ConnectedAccountOperationJournalService,
    )

    encryption = FakeEncryption()
    journal = ConnectedAccountOperationJournalService(encryption_service=encryption)
    row = await journal.build_entry(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        app_id="calendar",
        action="write",
        decision="undo_success",
        action_id="act-1",
        undo_payload={"events": []},
    )

    with pytest.raises(HTTPException) as exc_info:
        await undo_connected_account_action(
            "act-1",
            UndoConnectedAccountActionRequest(
                turn_token_ref="tref_1",
                chat_id="chat-1",
                message_id="msg-1",
            ),
            current_user=FakeUser(),
            directus_service=FakeDirectus(row),
            cache_service=FakeCache(),
            encryption_service=encryption,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.anyio
async def test_undo_rejects_token_ref_for_different_connected_account() -> None:
    from fastapi import HTTPException

    from backend.core.api.app.routes.connected_account_actions import (
        UndoConnectedAccountActionRequest,
        undo_connected_account_action,
    )
    from backend.core.api.app.services.connected_account_operation_journal import (
        ConnectedAccountOperationJournalService,
    )
    from backend.core.api.app.services.token_broker import TokenBrokerService

    async def exchange(_refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        return {"access_token": "access"}

    encryption = FakeEncryption()
    journal = ConnectedAccountOperationJournalService(encryption_service=encryption)
    row = await journal.build_entry(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-1",
        app_id="calendar",
        action="write",
        decision="completed",
        action_id="act-1",
        undo_payload={
            "events": [
                {
                    "undo_type": "delete_created_event",
                    "calendar_id": "primary",
                    "event_id": "event-1",
                }
            ]
        },
    )
    cache = FakeCache()
    broker = TokenBrokerService(
        cache_service=cache,
        encryption_service=encryption,
        exchange_refresh_token=exchange,
    )
    ref = await broker.create_turn_token_ref(
        user_id="user-1",
        user_vault_key_id="vault-key",
        connected_account_id="acct-2",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        allowed_actions=["delete"],
        refresh_token_envelope={"refresh_token": "refresh-secret"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await undo_connected_account_action(
            "act-1",
            UndoConnectedAccountActionRequest(
                turn_token_ref=ref.turn_token_ref,
                chat_id="chat-1",
                message_id="msg-1",
            ),
            current_user=FakeUser(),
            directus_service=FakeDirectus(row),
            cache_service=cache,
            encryption_service=encryption,
        )

    assert exc_info.value.status_code == 403
    assert "account mismatch" in str(exc_info.value.detail)
