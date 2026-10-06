"""Actual Starlette socket state after session-watchers send a close frame."""

import asyncio
import json

import pytest
from starlette.websockets import WebSocket, WebSocketDisconnect

from backend.core.api.app.utils.websocket_lifecycle import receive_json_or_disconnect


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("close_code", [1008, 4406])
def test_server_close_while_receiving_uses_disconnect_cleanup(close_code):
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        sent = []
        connecting = True

        async def receive():
            nonlocal connecting
            if connecting:
                connecting = False
                return {"type": "websocket.connect"}
            entered.set()
            await release.wait()
            return {"type": "websocket.receive", "text": json.dumps({"type": "ping"})}

        async def send(message):
            sent.append(message)

        socket = WebSocket({"type": "websocket"}, receive, send)
        await socket.accept()
        entered.clear()
        release.clear()
        pending = asyncio.create_task(receive_json_or_disconnect(socket))
        await entered.wait()
        await socket.close(code=close_code)
        release.set()
        assert await pending == {"type": "ping"}
        with pytest.raises(WebSocketDisconnect):
            await receive_json_or_disconnect(socket)
        assert [message for message in sent if message["type"] == "websocket.close"] == [
            {"type": "websocket.close", "code": close_code, "reason": ""},
        ]

    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
def test_unaccepted_socket_still_reports_programming_error():
    async def receive():
        raise AssertionError("Unaccepted socket should not receive")

    socket = WebSocket({"type": "websocket"}, receive, receive)
    with pytest.raises(RuntimeError, match="accept"):
        asyncio.run(receive_json_or_disconnect(socket))
