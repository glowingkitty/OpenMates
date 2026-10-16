"""Real Starlette send failures retain peer delivery and connection fencing."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager


async def send_path(manager, path):
    if path == "personal":
        return await manager.send_personal_message({"type": "probe"}, "owner", "failed")
    if path == "broadcast":
        return await manager.broadcast_to_user({"type": "probe"}, "owner")
    return await manager.broadcast_to_user_specific_event("owner", "probe", {})


def socket(send):
    async def receive():
        return {"type": "websocket.connect"}
    return WebSocket({"type": "websocket"}, receive, send)


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("path", ["personal", "broadcast", "event"])
@pytest.mark.parametrize("failure", ["transport", "closed_state", "genuine", "cancelled"])
def test_send_failure_classification_and_peer_delivery(path, failure, caplog):
    caplog.set_level(logging.DEBUG, logger="backend.core.api.app.routes.connection_manager")

    async def run():
        manager = ConnectionManager()
        revoker = AsyncMock()
        peer_frames = []

        async def fail_send(message):
            if message["type"] != "websocket.send":
                return
            if failure == "transport":
                raise OSError("transport closed")
            if failure == "closed_state":
                raise RuntimeError('Cannot call "send" once a close message has been sent.')
            if failure == "cancelled":
                raise asyncio.CancelledError()
            raise ValueError("serialization failed")

        async def peer_send(message):
            peer_frames.append(message)

        failed = socket(fail_send)
        peer = socket(peer_send)
        nonce = await manager.connect(failed, "owner", "failed", volatile_session_revoker=revoker)
        peer_nonce = await manager.connect(peer, "owner", "peer")
        caplog.clear()
        try:
            if failure == "cancelled":
                with pytest.raises(asyncio.CancelledError):
                    await send_path(manager, path)
                assert id(failed) in manager.volatile_session_nonce_by_ws
                assert not [r for r in caplog.records if hasattr(r, "exception_type") or r.levelno >= logging.ERROR]
            else:
                result = await send_path(manager, path)
                if path == "personal":
                    assert result is False
                assert ("owner", "failed") in manager.grace_period_tasks
                assert id(failed) not in manager.volatile_session_nonce_by_ws
                await asyncio.sleep(0)
                revoker.assert_awaited_once_with(nonce)
                records = [r for r in caplog.records if hasattr(r, "exception_type")]
                assert len(records) == 1
                record = records[0]
                assert record.levelno == (logging.ERROR if failure == "genuine" else logging.DEBUG)
                if failure == "transport":
                    assert record.exception_type == "WebSocketDisconnect"
                    assert record.close_code == 1006
                elif failure == "closed_state":
                    assert record.exception_type == "RuntimeError"
                else:
                    assert record.exception_type == "ValueError"
                assert sum(m["type"] == "websocket.send" for m in peer_frames) == (path != "personal")
                assert manager.volatile_session_nonce_by_ws[id(peer)] == peer_nonce
        finally:
            tasks = list(manager.grace_period_tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("path", ["personal", "broadcast", "event"])
def test_late_transport_failure_preserves_replacement_socket_nonce(path, caplog):
    async def run():
        manager = ConnectionManager()
        started, release = asyncio.Event(), asyncio.Event()
        revoker = AsyncMock()

        async def old_send(message):
            if message["type"] == "websocket.send":
                started.set()
                await release.wait()
                raise OSError("old transport closed")

        old = socket(old_send)
        old_nonce = await manager.connect(old, "owner", "failed", volatile_session_revoker=revoker)
        pending = asyncio.create_task(send_path(manager, path))
        await started.wait()
        replacement = socket(AsyncMock())
        new_nonce = await manager.connect(replacement, "owner", "failed")
        release.set()
        await pending
        assert manager.active_connections["owner"]["failed"] is replacement
        assert manager.volatile_session_nonce_by_ws[id(replacement)] == new_nonce
        assert manager.confirm_volatile_session(replacement, new_nonce)
        assert ("owner", "failed") not in manager.grace_period_tasks
        revoker.assert_awaited_once_with(old_nonce)
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("path", ["broadcast", "event"])
def test_cancelled_peer_does_not_skip_failed_and_stale_peer_cleanup(path):
    async def run():
        manager = ConnectionManager()
        healthy_frames = []

        async def cancelled_send(message):
            if message["type"] == "websocket.send":
                raise asyncio.CancelledError()

        async def closed_send(message):
            if message["type"] == "websocket.send":
                raise OSError("transport closed")

        async def healthy_send(message):
            healthy_frames.append(message)

        cancelled = socket(cancelled_send)
        failed = socket(closed_send)
        stale = socket(AsyncMock())
        healthy = socket(healthy_send)
        for name, ws in [("cancelled", cancelled), ("failed", failed), ("stale", stale), ("healthy", healthy)]:
            await manager.connect(ws, "owner", name)
        await stale.close()
        try:
            with pytest.raises(asyncio.CancelledError):
                await send_path(manager, path)
            assert ("owner", "failed") in manager.grace_period_tasks
            assert ("owner", "stale") in manager.grace_period_tasks
            assert id(failed) not in manager.volatile_session_nonce_by_ws
            assert id(stale) not in manager.volatile_session_nonce_by_ws
            assert id(healthy) in manager.volatile_session_nonce_by_ws
            assert [m["type"] for m in healthy_frames] == ["websocket.accept", "websocket.send"]
        finally:
            tasks = list(manager.grace_period_tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(run())
