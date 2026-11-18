"""A superseded socket that registers late never strands the socket the client keeps.

Authentication latency varies per attempt, so a reconnect attempt the client
already superseded can finish its accept after the socket the client keeps.
When the client then closes the superseded socket, routed replies (acks,
receipts) must reach the kept socket immediately, not after a reconnect.
"""

import asyncio

from starlette.websockets import WebSocket, WebSocketState

from backend.core.api.app.routes.connection_manager import ConnectionManager


def _socket(frames: list):
    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        if message["type"] == "websocket.send":
            frames.append(message)

    return WebSocket({"type": "websocket"}, receive, send)


def _close(websocket: WebSocket) -> None:
    websocket.application_state = WebSocketState.DISCONNECTED


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
def test_late_registered_superseded_socket_hands_route_back_on_close():
    async def run():
        manager = ConnectionManager()
        kept_frames, stale_frames = [], []
        kept, stale = _socket(kept_frames), _socket(stale_frames)
        await manager.connect(kept, "owner", "route")
        await manager.connect(stale, "owner", "route")  # superseded attempt registers last
        _close(stale)
        manager.disconnect(stale, reason="client closed superseded socket")

        assert await manager.send_personal_message({"type": "native_client_lifecycle_ack"}, "owner", "route")
        assert len(kept_frames) == 1 and not stale_frames
        assert not manager.grace_period_tasks
        assert manager.reverse_lookup[id(kept)] == ("owner", "route")
        assert not manager.standby_connections and not manager.standby_lookup

        # The kept socket's own close follows the ordinary grace-period path.
        _close(kept)
        manager.disconnect(kept, reason="closed")
        assert ("owner", "route") in manager.grace_period_tasks
        manager.grace_period_tasks.pop(("owner", "route")).cancel()

    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
def test_ordinary_reconnect_drops_closed_standby_without_touching_route():
    async def run():
        manager = ConnectionManager()
        old_frames, new_frames = [], []
        old, new = _socket(old_frames), _socket(new_frames)
        await manager.connect(old, "owner", "route")
        await manager.connect(new, "owner", "route")
        _close(old)
        manager.disconnect(old, reason="old socket closed after reconnect")

        assert manager.active_connections["owner"]["route"] is new
        assert not manager.grace_period_tasks and not manager.standby_lookup
        assert await manager.send_personal_message({"type": "probe"}, "owner", "route")
        assert len(new_frames) == 1 and not old_frames

        # A closed standby is never promoted: the route then takes the grace path.
        third = _socket([])
        await manager.connect(third, "owner", "route")
        _close(new)
        _close(third)
        manager.disconnect(third, reason="closed")
        assert ("owner", "route") in manager.grace_period_tasks
        manager.grace_period_tasks.pop(("owner", "route")).cancel()

    asyncio.run(run())
