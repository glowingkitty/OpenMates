# backend/tests/test_websocket_startup_disconnect.py
"""Verify failed WebSocket startup before receive-loop cleanup begins.

Actual Starlette sockets and the connection manager exercise transport closure,
registration cleanup, replacement authority, and genuine exception propagation.
The browser startup case supplies separate reconnect integration coverage.
"""

import ast
import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from backend.core.api.app.routes.connection_manager import ConnectionManager


def startup_sender():
    # Execute the production boundary without importing unrelated route handlers.
    route = Path(__file__).parents[1] / "core/api/app/routes/websockets.py"
    tree = ast.parse(route.read_text())
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                 and node.name == "_send_initial_server_capabilities"]
    assert len(functions) == 1
    namespace = {"WebSocket": WebSocket, "WebSocketDisconnect": WebSocketDisconnect,
                 "ConnectionManager": ConnectionManager,
                 "logger": logging.getLogger("test.websocket.startup")}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(route), "exec"), namespace)
    return namespace["_send_initial_server_capabilities"]


def socket_with_transport(send):
    async def receive():
        return {"type": "websocket.connect"}
    return WebSocket({"type": "websocket"}, receive, send)


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,sync.startup.bounded-phases
def test_lost_capability_transport_releases_registration_and_volatile_authority(caplog):
    async def run():
        async def send(message):
            if message["type"] == "websocket.send":
                assert json.loads(message["text"])["type"] == "server_capabilities"
                raise OSError("synthetic closed transport")
        manager = ConnectionManager()
        manager.GRACE_PERIOD_SECONDS = 0
        revoke = AsyncMock()
        socket = socket_with_transport(send)
        nonce = await manager.connect(socket, "owner", "device", volatile_session_revoker=revoke)
        with caplog.at_level(logging.DEBUG, logger="test.websocket.startup"):
            assert await startup_sender()(socket, manager) is False
        assert socket.application_state == WebSocketState.DISCONNECTED
        assert id(socket) not in manager.volatile_session_nonce_by_ws
        assert manager.get_volatile_session_nonce("owner", "device") is None
        await manager.grace_period_tasks[("owner", "device")]
        revoke.assert_awaited_once_with(nonce)
        assert id(socket) not in manager.reverse_lookup
        assert "owner" not in manager.active_connections
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
@pytest.mark.parametrize("failure", [RuntimeError("synthetic genuine send failure"), asyncio.CancelledError()])
def test_genuine_send_failure_or_cancellation_propagates_after_cleanup(failure):
    async def run():
        async def send(message):
            if message["type"] == "websocket.send":
                raise failure
        manager = ConnectionManager()
        manager.GRACE_PERIOD_SECONDS = 0
        socket = socket_with_transport(send)
        await manager.connect(socket, "owner", "device")
        with pytest.raises(type(failure)) as error:
            await startup_sender()(socket, manager)
        assert error.value is failure
        await manager.grace_period_tasks[("owner", "device")]
        assert id(socket) not in manager.reverse_lookup
        assert "owner" not in manager.active_connections
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
def test_cleanup_failure_does_not_replace_genuine_send_exception(caplog):
    async def run():
        failure = RuntimeError("synthetic genuine send failure")
        async def send(message):
            if message["type"] == "websocket.send":
                raise failure
        manager = ConnectionManager()
        socket = socket_with_transport(send)
        await manager.connect(socket, "owner", "device")
        manager.disconnect = MagicMock(side_effect=RuntimeError("synthetic cleanup failure"))
        manager.mark_volatile_session_unavailable = MagicMock()
        with pytest.raises(RuntimeError) as error:
            await startup_sender()(socket, manager)
        assert error.value is failure
        manager.mark_volatile_session_unavailable.assert_called_once_with(socket)
        assert any(record.levelno == logging.ERROR and "clean up" in record.message for record in caplog.records)
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,sync.startup.bounded-phases
def test_stale_startup_cleanup_preserves_fresh_reconnect_and_its_nonce():
    async def run():
        manager = ConnectionManager()
        manager.GRACE_PERIOD_SECONDS = 0
        revoke_old = AsyncMock()
        revoke_new = AsyncMock()
        async def good_send(message):
            pass
        replacement = socket_with_transport(good_send)
        replacement_nonce = None
        async def failed_send(message):
            nonlocal replacement_nonce
            if message["type"] == "websocket.send":
                replacement_nonce = await manager.connect(
                    replacement, "owner", "device", volatile_session_revoker=revoke_new,
                )
                assert manager.confirm_volatile_session(replacement, replacement_nonce)
                raise OSError("old transport closed after replacement")
        old_socket = socket_with_transport(failed_send)
        old_nonce = await manager.connect(old_socket, "owner", "device", volatile_session_revoker=revoke_old)
        assert await startup_sender()(old_socket, manager) is False
        await asyncio.sleep(0)
        assert manager.active_connections["owner"]["device"] is replacement
        assert manager.reverse_lookup[id(replacement)] == ("owner", "device")
        assert manager.get_volatile_session_nonce("owner", "device") == replacement_nonce
        revoke_old.assert_awaited_once_with(old_nonce)
        revoke_new.assert_not_called()
        assert not manager.grace_period_tasks
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=sync.startup.bounded-phases
def test_successful_capability_send_retains_registration():
    async def run():
        sent = []
        async def send(message):
            sent.append(message)
        manager = ConnectionManager()
        socket = socket_with_transport(send)
        await manager.connect(socket, "owner", "device")
        assert await startup_sender()(socket, manager) is True
        payload = json.loads(sent[-1]["text"])
        assert payload["type"] == "server_capabilities"
        assert "chat_turn_admit_v1" in payload["payload"]["capabilities"]
        assert manager.active_connections["owner"]["device"] is socket
        assert id(socket) in manager.volatile_session_nonce_by_ws
        assert not manager.grace_period_tasks
    asyncio.run(run())
