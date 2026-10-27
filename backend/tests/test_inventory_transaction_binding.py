"""PRIVATE UNRUN: complete inventory transaction binding, inert services only."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from starlette.websockets import WebSocketState

from backend.core.api.app.routes import websockets
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.routes.handlers.websocket_handlers import (
    phased_sync_handler as phased,
    chat_recovery_job_handlers as recovery,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Socket:
    def __init__(self, request_id=None, opted=True):
        self.application_state = WebSocketState.CONNECTING
        self.messages = []
        self.query_params = {"client_capabilities": "task_update_jobs_inventory_v1" if opted else ""}
        if request_id is not None:
            self.query_params["inventory_request_id"] = request_id

    async def accept(self):
        self.application_state = WebSocketState.CONNECTED

    async def send_json(self, message):
        self.messages.append(message)


async def connected(request_id=None, opted=True):
    manager, socket = ConnectionManager(), Socket(request_id, opted)
    await manager.connect(socket, "owner", "device", supports_typed_recovery_outputs=True)
    return manager, socket


@pytest.mark.anyio
@pytest.mark.parametrize("correlated", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.completion.recovery-takeover
async def test_welcome_echo_selects_only_requested_correlated_protocol(correlated):
    request_id = str(uuid.uuid4()) if correlated else None
    manager, socket = await connected(request_id)
    assert await websockets._send_initial_server_capabilities(socket, manager, request_id) is True
    payload = socket.messages[0]["payload"]
    assert socket.messages[0]["type"] == "server_capabilities"
    assert "chat_turn_admit_v1" in payload["capabilities"]
    if correlated:
        assert bool(payload.get("inventory_request_id") == request_id)
    else:
        assert "inventory_request_id" not in payload


@pytest.mark.parametrize("scenario", ["missing-query", "legacy-capability", "foreign-payload", "malformed-query"])
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.completion.recovery-takeover
def test_phase_payload_cannot_inject_or_select_correlation(scenario):
    request_id, foreign = str(uuid.uuid4()), str(uuid.uuid4())
    socket = Socket(None if scenario == "missing-query" else request_id, opted=scenario != "legacy-capability")
    payload = {"inventory_request_id": foreign if scenario == "foreign-payload" else request_id}
    if scenario == "malformed-query":
        socket.query_params["inventory_request_id"] = "invalid"
        payload["inventory_request_id"] = "invalid"
    assert phased._phase_inventory_request_id(socket, payload) is None


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.completion.recovery-takeover
async def test_actual_handler_tags_all_current_phase_data_and_completion_from_original_query(monkeypatch):
    request_id = str(uuid.uuid4())
    manager, socket = await connected(request_id)

    async def phase2(bound, *_args, **_kwargs):
        await bound.send_personal_message({"type": "phase_2_last_20_chats_ready", "payload": {"chats": []}}, "owner", "device")

    monkeypatch.setattr(phased, "_handle_phase2_sync", phase2)
    await phased.handle_phased_sync_request(websocket=socket, manager=manager, cache_service=SimpleNamespace(),
        directus_service=SimpleNamespace(), encryption_service=SimpleNamespace(), user_id="owner",
        device_fingerprint_hash="device", payload={"phase": "phase2", "context_epoch": 0,
                                                  "inventory_request_id": request_id})
    assert [frame["type"] for frame in socket.messages] == ["phase_2_last_20_chats_ready", "phased_sync_complete"]
    assert all(bool(frame["payload"].get("inventory_request_id") == request_id) for frame in socket.messages)


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.completion.recovery-takeover
async def test_bound_adapter_retains_original_identity_and_overrides_foreign_payload():
    request_id, foreign = str(uuid.uuid4()), str(uuid.uuid4())
    manager, socket = await connected(request_id)
    bound = phased._OriginBoundSyncManager(manager, socket, phased._phase_inventory_request_id(socket, {"inventory_request_id": request_id}))
    socket.query_params["inventory_request_id"] = foreign
    assert await bound.send_personal_message({"type": "phased_sync_complete", "payload": {"inventory_request_id": foreign}}, "owner", "device") is True
    assert bool(socket.messages[0]["payload"]["inventory_request_id"] == request_id)
    replacement = Socket(foreign)
    await manager.connect(replacement, "owner", "device")
    assert await bound.send_personal_message({"type": "phase_2_last_20_chats_ready", "payload": {"chats": []}}, "owner", "device") is False
    assert replacement.messages == []


@pytest.mark.anyio
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("correlated", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_typed_output_complete_and_failed_fences_use_original_request(monkeypatch, failed, correlated):
    request_id = str(uuid.uuid4()) if correlated else None
    manager, socket = await connected(request_id)
    query = AsyncMock(side_effect=RuntimeError("synthetic schema failure") if failed else None,
                      return_value={"outputs": []})
    monkeypatch.setattr(recovery, "ChatRecoveryService", lambda _: SimpleNamespace(execute=query))
    call = recovery.send_available_recovery_outputs(manager=manager, directus_service=object(),
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device", inventory_request_id=request_id)
    if failed:
        with pytest.raises(RuntimeError):
            await call
    else:
        await call
    assert len(socket.messages) == 1
    frame = socket.messages[0]
    assert frame["type"] == "recovery_outputs_discovery_complete"
    assert frame["payload"]["status"] == ("failed" if failed else "completed")
    if correlated:
        assert bool(frame["payload"].get("inventory_request_id") == request_id)
    else:
        assert "inventory_request_id" not in frame["payload"]
    query.assert_awaited_once_with("list_pending_outputs", {
        "protocol_version": 1, "hashed_user_id": "owner-hash", "device_hash": "device",
    })


@pytest.mark.anyio
@pytest.mark.parametrize("epoch", [0, None])
@pytest.mark.parametrize("correlated", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_initial_legacy_disabled_or_failed_fence_retains_original_optional_correlation(epoch, correlated):
    request_id = str(uuid.uuid4()) if correlated else None
    manager, socket = await connected(request_id)

    async def get_epoch():
        if epoch is None:
            raise RuntimeError("synthetic epoch failure")
        return epoch

    tasks = await recovery.begin_initial_recovery_discovery(manager=manager, directus_service=object(),
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device",
        supports_typed_recovery_outputs=False, get_epoch=get_epoch, inventory_request_id=request_id)
    assert tasks == []
    assert len(socket.messages) == 1
    payload = socket.messages[0]["payload"]
    assert payload["status"] == ("disabled" if epoch == 0 else "failed")
    if correlated:
        assert bool(payload.get("inventory_request_id") == request_id)
    else:
        assert "inventory_request_id" not in payload
