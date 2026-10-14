"""Authenticated session routing for several browser tabs sharing one cookie."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState

from backend.core.api.app.routes.connection_manager import ConnectionManager


def socket():
    return SimpleNamespace(
        accept=AsyncMock(), send_json=AsyncMock(),
        application_state=WebSocketState.CONNECTED,
    )


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
def test_revocation_targets_all_tabs_of_one_owner_session_and_excludes_siblings():
    async def scenario():
        manager = ConnectionManager()
        first, cloned, other_session, other_owner, unbound = (socket() for _ in range(5))
        await manager.connect(first, "owner", "route-a", logical_session_id="session-a")
        await manager.connect(cloned, "owner", "route-b", logical_session_id="session-a")
        await manager.connect(other_session, "owner", "route-c", logical_session_id="session-b")
        await manager.connect(other_owner, "other-owner", "route-a", logical_session_id="session-a")
        await manager.connect(unbound, "owner", "legacy-route")

        event = {"reason": "session_revoked"}
        await manager.broadcast_to_user_specific_event(
            "owner", "force_logout", event, target_logical_session_id="session-a",
        )
        first.send_json.assert_awaited_once_with({"type": "force_logout", "payload": event})
        cloned.send_json.assert_awaited_once_with({"type": "force_logout", "payload": event})
        other_session.send_json.assert_not_awaited()
        other_owner.send_json.assert_not_awaited()
        unbound.send_json.assert_not_awaited()

        first.send_json.reset_mock()
        cloned.send_json.reset_mock()
        await manager.broadcast_to_user_specific_event(
            "owner", "force_logout", {"reason": "all_other_sessions_revoked"},
            exclude_logical_session_id="session-a",
        )
        first.send_json.assert_not_awaited()
        cloned.send_json.assert_not_awaited()
        other_session.send_json.assert_awaited_once()
        unbound.send_json.assert_not_awaited()

        await manager.broadcast_to_user_specific_event(
            "owner", "force_logout", {"reason": "account_deleted"},
        )
        first.send_json.assert_awaited_once()
        cloned.send_json.assert_awaited_once()
        unbound.send_json.assert_awaited_once()
        other_owner.send_json.assert_not_awaited()

    asyncio.run(scenario())


# contract-test: supporting surface=rest_api assertions=auth.session.isolation
def test_malformed_session_selector_never_becomes_a_user_wide_event():
    async def scenario():
        manager = ConnectionManager()
        active = socket()
        await manager.connect(active, "owner", "route", logical_session_id="session-a")
        for selector in (
            {"target_logical_session_id": ""},
            {"target_logical_session_id": "  "},
            {"exclude_logical_session_id": ""},
            {"exclude_logical_session_id": "  "},
            {"target_logical_session_id": "session-a", "exclude_logical_session_id": "session-b"},
        ):
            with pytest.raises(ValueError):
                await manager.broadcast_to_user_specific_event(
                    "owner", "force_logout", {"reason": "session_revoked"}, **selector,
                )
        active.send_json.assert_not_awaited()

    asyncio.run(scenario())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
def test_replaced_socket_cannot_clear_new_session_binding():
    async def scenario():
        manager = ConnectionManager()
        old, replacement = socket(), socket()
        await manager.connect(old, "owner", "route", logical_session_id="session-a")
        await manager.connect(replacement, "owner", "route", logical_session_id="session-b")
        await manager._finalize_disconnect("owner", "route", id(old))
        assert manager.logical_session_per_connection[("owner", "route")] == "session-b"
        await manager.broadcast_to_user_specific_event(
            "owner", "force_logout", {"reason": "session_revoked"},
            target_logical_session_id="session-b",
        )
        replacement.send_json.assert_awaited_once()
        old.send_json.assert_not_awaited()
        await manager._finalize_disconnect("owner", "route", id(replacement))
        assert ("owner", "route") not in manager.logical_session_per_connection

    asyncio.run(scenario())
