"""PRIVATE UNRUN: phased metadata and fences cannot migrate to replacement sockets.

Actual ConnectionManager and top-level handler; all transport/storage work is inert.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketState

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.routes.handlers.websocket_handlers import phased_sync_handler as phased


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Socket:
    def __init__(self, *, started=None, release=None, failure=False):
        self.application_state = WebSocketState.CONNECTING
        self.messages = []
        self.started, self.release, self.failure = started, release, failure

    async def accept(self):
        self.application_state = WebSocketState.CONNECTED

    async def send_json(self, message):
        if self.started is not None:
            self.started.set()
            await self.release.wait()
        if self.failure:
            raise RuntimeError("synthetic old socket write failed")
        if self.application_state != WebSocketState.CONNECTED:
            raise RuntimeError("synthetic socket closed")
        self.messages.append(message)


async def connect(manager, socket, opted):
    await manager.connect(socket, "owner", "device", supports_task_update_jobs=opted,
                          supports_chat_metadata_recovery=opted,
                          supports_typed_recovery_outputs=opted)


async def cleanup(manager):
    tasks = list(manager.grace_period_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize("opted", [False, True])
@pytest.mark.parametrize("kind", ["phase_2_last_20_chats_ready", "background_message_sync", "phased_sync_complete", "error"])
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,teams.context.full-switch-local
async def test_current_bound_send_preserves_exact_data_and_fence_envelopes(opted, kind):
    manager = ConnectionManager()
    socket = Socket()
    await connect(manager, socket, opted)
    message = {"type": kind, "payload": {"context_epoch": 0, "chats": []}}
    assert await manager.send_personal_message(message, "owner", "device", expected_websocket=socket) is True
    assert socket.messages == [message]
    # Existing unbound callers still send normally through the same primitive.
    assert await manager.send_personal_message(message, "owner", "device") is True
    assert socket.messages == [message, message]
    await cleanup(manager)


@pytest.mark.anyio
@pytest.mark.parametrize("old_opted,new_opted", [(False, False), (False, True), (True, False), (True, True)])
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,teams.context.full-switch-local
async def test_bound_send_never_reroutes_legacy_or_opted_producer(old_opted, new_opted):
    manager = ConnectionManager()
    old, new = Socket(), Socket()
    await connect(manager, old, old_opted)
    await connect(manager, new, new_opted)
    assert await manager.send_personal_message({"type": "phased_sync_complete"}, "owner", "device",
                                               expected_websocket=old) is False
    assert old.messages == [] and new.messages == []
    assert manager.active_connections["owner"]["device"] is new
    await cleanup(manager)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("kind", ["phase_2_last_20_chats_ready", "phased_sync_complete", "error"])
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,teams.context.full-switch-local
async def test_replacement_during_blocked_write_never_receives_or_loses_its_connection(failure, bound, kind):
    manager = ConnectionManager()
    started, release = asyncio.Event(), asyncio.Event()
    old, new = Socket(started=started, release=release, failure=failure), Socket()
    await connect(manager, old, False)
    disconnects = []
    real_disconnect = manager.disconnect

    def disconnect(socket, reason=""):
        disconnects.append(socket)
        return real_disconnect(socket, reason)

    manager.disconnect = disconnect
    message = {"type": kind, "payload": {"chats": []}}
    operation = asyncio.create_task(manager.send_personal_message(message, "owner", "device",
        **({"expected_websocket": old} if bound else {})))
    try:
        await asyncio.wait_for(started.wait(), 3)
        await connect(manager, new, True)
        release.set()
        result = await asyncio.wait_for(operation, 3)
        assert result is (not bound and not failure)
        assert new.messages == []
        assert old.messages == ([] if failure else [message])
        assert disconnects == []
        assert manager.active_connections["owner"]["device"] is new
        assert manager.reverse_lookup[id(new)] == ("owner", "device")
        assert ("owner", "device") not in manager.grace_period_tasks
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await cleanup(manager)


def install_phase_helpers(monkeypatch, started, release, *, phase, error=False):
    async def emit(manager, kind):
        started.set()
        await release.wait()
        if error:
            raise RuntimeError("synthetic sync read failed")
        await manager.send_personal_message({"type": kind, "payload": {"chats": [], "context_epoch": 0}}, "owner", "device")

    async def phase1(manager, *_args, **_kwargs):
        if phase == "phase1":
            await emit(manager, "phase_1_last_chat_ready")
        return ["chat"] if phase == "phase1b" else []

    async def phase1b(manager, *_args, **_kwargs):
        await emit(manager, "phase_1b_messages_ready")

    async def phase2(manager, *_args, **_kwargs):
        if phase == "phase2":
            await emit(manager, "phase_2_last_20_chats_ready")

    async def phase3(manager, *_args, **_kwargs):
        await emit(manager, "background_message_sync")
        await manager.send_personal_message({"type": "code_run_outputs_sync_ready", "payload": {"outputs": []}}, "owner", "device")
        await manager.send_personal_message({"type": "notebook_run_outputs_sync_ready", "payload": {"outputs": []}}, "owner", "device")

    async def settings(manager, *_args, **_kwargs):
        if phase == "settings":
            await emit(manager, "app_settings_memories_sync_ready")

    for name, helper in [("_handle_phase1_sync", phase1), ("_handle_phase1b_sync", phase1b),
                         ("_handle_phase2_sync", phase2), ("_handle_phase3_sync", phase3),
                         ("_handle_app_settings_memories_sync", settings)]:
        monkeypatch.setattr(phased, name, helper)


async def run_handler(socket, manager, phase):
    return await phased.handle_phased_sync_request(websocket=socket, manager=manager,
        cache_service=SimpleNamespace(), directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(), user_id="owner", device_fingerprint_hash="device",
        payload={"phase": "all" if phase in {"phase1b", "settings"} else phase, "context_epoch": 0})


@pytest.mark.anyio
@pytest.mark.parametrize("old_opted,new_opted", [(False, True), (True, False), (True, True)])
@pytest.mark.parametrize("phase", ["phase1", "phase1b", "phase2", "phase3", "settings"])
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,teams.context.full-switch-local
async def test_replaced_handler_cannot_send_any_phase_data_or_completion(monkeypatch, old_opted, new_opted, phase):
    manager = ConnectionManager()
    old, new = Socket(), Socket()
    await connect(manager, old, old_opted)
    started, release = asyncio.Event(), asyncio.Event()
    install_phase_helpers(monkeypatch, started, release, phase=phase)
    operation = asyncio.create_task(run_handler(old, manager, phase))
    try:
        await asyncio.wait_for(started.wait(), 3)
        await connect(manager, new, new_opted)
        release.set()
        await asyncio.wait_for(operation, 3)
        assert old.messages == [] and new.messages == []
        assert manager.active_connections["owner"]["device"] is new
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await cleanup(manager)


@pytest.mark.anyio
@pytest.mark.parametrize("old_opted", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,teams.context.full-switch-local
async def test_replaced_handler_error_does_not_reach_new_request(monkeypatch, old_opted):
    manager = ConnectionManager()
    old, new = Socket(), Socket()
    await connect(manager, old, old_opted)
    started, release = asyncio.Event(), asyncio.Event()
    install_phase_helpers(monkeypatch, started, release, phase="phase2", error=True)
    operation = asyncio.create_task(run_handler(old, manager, "phase2"))
    try:
        await asyncio.wait_for(started.wait(), 3)
        await connect(manager, new, True)
        release.set()
        await asyncio.wait_for(operation, 3)
        assert old.messages == [] and new.messages == []
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await cleanup(manager)


@pytest.mark.anyio
@pytest.mark.parametrize("error", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,teams.context.full-switch-local
async def test_current_handler_keeps_normal_data_complete_and_error_behavior(monkeypatch, error):
    manager = ConnectionManager()
    socket = Socket()
    await connect(manager, socket, False)
    started, release = asyncio.Event(), asyncio.Event()
    release.set()
    install_phase_helpers(monkeypatch, started, release, phase="phase2", error=error)
    await run_handler(socket, manager, "phase2")
    assert [message["type"] for message in socket.messages] == (["error"] if error else
        ["phase_2_last_20_chats_ready", "phased_sync_complete"])
    await cleanup(manager)
