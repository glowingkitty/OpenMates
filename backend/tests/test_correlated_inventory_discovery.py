"""PRIVATE UNRUN: real ConnectionManager replacement with synthetic blocked reads.

No network/Redis/Directus/inference. Opaque test request IDs are never logged.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from starlette.websockets import WebSocketState

from backend.core.api.app.routes import websockets
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.routes.handlers.websocket_handlers import (
    chat_recovery_job_handlers as main,
    chat_metadata_recovery_handlers as metadata,
    task_update_job_handlers as task,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Socket:
    def __init__(self, request_id=None):
        self.application_state = WebSocketState.CONNECTING
        self.messages = []
        self.inventory_request_id = request_id

    async def accept(self):
        self.application_state = WebSocketState.CONNECTED

    async def send_json(self, message):
        if self.application_state != WebSocketState.CONNECTED:
            raise RuntimeError("synthetic closed socket")
        self.messages.append(message)


class Cache:
    def __init__(self, client):
        self.raw = client
        self.get_keys_by_pattern = AsyncMock(return_value=[])
        self.get = AsyncMock(return_value=None)
        self.set = AsyncMock()

    @property
    async def client(self):
        return self.raw


async def connect(manager, socket, *, opted_in):
    await manager.connect(socket, "owner", "device", supports_task_update_jobs=opted_in,
                          supports_chat_metadata_recovery=opted_in,
                          supports_typed_recovery_outputs=True)


async def cleanup(manager):
    pending = list(manager.grace_period_tasks.values())
    for pending_task in pending:
        pending_task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def blocked_discovery(monkeypatch, kind, manager, started, release, request_id):
    async def query(operation, data):
        assert operation in {"list_available_jobs", "list_metadata_jobs"}
        assert data["hashed_user_id"] == "owner-hash"
        if operation == "list_available_jobs":
            assert data["device_hash"] == "device"
        started.set()
        await release.wait()
        # Stored metadata must not inject request correlation into a legacy reply.
        return {"jobs": [], "inventory_request_id": str(uuid.uuid4())}

    if kind in {"main", "metadata", "paused-main"}:
        module = metadata if kind == "metadata" else main
        monkeypatch.setattr(module, "ChatRecoveryService", lambda _: SimpleNamespace(execute=query))
        if kind == "metadata":
            return await metadata.send_available_metadata_jobs(manager=manager, directus_service=object(),
                user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device",
                inventory_request_id=request_id)
        if kind == "paused-main":
            class Cutover:
                def __init__(self, *_):
                    pass

                async def get_epoch(self, *, authoritative):
                    assert authoritative is True
                    return 0

            monkeypatch.setattr(websockets, "ChatRecoveryCutoverController", Cutover)
            return await websockets._discover_foreground_recovery(manager=manager, cache_service=object(),
                directus_service=object(), user_id="owner", user_id_hash="owner-hash",
                device_fingerprint_hash="device", supports_typed_recovery_outputs=True,
                user_otel_attrs={}, inventory_empty_ack=True, inventory_request_id=request_id)
        return await main.send_available_recovery_jobs(manager=manager, directus_service=object(),
            user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device",
            inventory_request_id=request_id)

    async def scan(**_):
        started.set()
        await release.wait()
        return 0, []

    cache = Cache(SimpleNamespace(scan=scan, get=AsyncMock()))
    await task.send_available_task_update_jobs(manager=manager, cache_service=cache,
        user_id="owner", device_fingerprint_hash="device", complete_inventory=True,
        inventory_request_id=request_id)
    cache.set.assert_not_awaited()


def matching_ack(messages, expected):
    return any(message.get("type") in {"recovery_jobs_available", "metadata_jobs_available", "task_update_jobs_available"}
               and message.get("payload", {}).get("inventory_request_id") == expected for message in messages)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["main", "metadata", "Task", "paused-main"])
@pytest.mark.parametrize("replacement_opted_in", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_original_request_ack_cannot_certify_replacement_socket(monkeypatch, kind, replacement_opted_in):
    manager = ConnectionManager()
    original_request, replacement_request = str(uuid.uuid4()), str(uuid.uuid4())
    original, replacement = Socket(original_request), Socket(replacement_request)
    await connect(manager, original, opted_in=True)
    started, release = asyncio.Event(), asyncio.Event()
    operation = asyncio.create_task(blocked_discovery(monkeypatch, kind, manager, started, release, original_request))
    try:
        await asyncio.wait_for(started.wait(), 3)
        await connect(manager, replacement, opted_in=replacement_opted_in)
        release.set()
        await asyncio.wait_for(operation, 3)
        assert not matching_ack(replacement.messages, replacement_request)
        assert original.messages == []
        # Correlated completion queries are now origin-bound, including paused
        # absence checks. Other inventory families retain their held contract.
        if kind in {"main", "paused-main"}:
            assert replacement.messages == []
        elif kind != "Task" or replacement_opted_in:
            assert matching_ack(replacement.messages, original_request)
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await cleanup(manager)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["main", "metadata", "Task"])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_legacy_unbound_query_never_becomes_correlated_after_replacement(monkeypatch, kind):
    manager = ConnectionManager()
    expected = str(uuid.uuid4())
    original, replacement = Socket(), Socket(expected)
    await connect(manager, original, opted_in=True)
    started, release = asyncio.Event(), asyncio.Event()
    operation = asyncio.create_task(blocked_discovery(monkeypatch, kind, manager, started, release, None))
    try:
        await asyncio.wait_for(started.wait(), 3)
        await connect(manager, replacement, opted_in=True)
        release.set()
        await asyncio.wait_for(operation, 3)
        assert not matching_ack(replacement.messages, expected)
        assert all("inventory_request_id" not in message.get("payload", {}) for message in replacement.messages)
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await cleanup(manager)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["main", "metadata", "Task"])
@pytest.mark.parametrize("transition", ["background", "disconnected", "expired-authority"])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_lost_authority_or_foreground_cannot_complete_all_proof_domains(monkeypatch, kind, transition):
    manager = ConnectionManager()
    request_id = str(uuid.uuid4())
    socket = Socket(request_id)
    await connect(manager, socket, opted_in=True)
    started, release = asyncio.Event(), asyncio.Event()
    operation = asyncio.create_task(blocked_discovery(monkeypatch, kind, manager, started, release, request_id))
    try:
        await asyncio.wait_for(started.wait(), 3)
        if transition == "background":
            manager.set_connection_foreground("owner", "device", False)
        else:
            socket.application_state = WebSocketState.DISCONNECTED
            if transition == "expired-authority":
                manager.disconnect(socket, reason="synthetic authority expired")
        release.set()
        await asyncio.wait_for(operation, 3)
        # Metadata retains compatible notification behavior in background, but
        # main and Task checks close the required three-domain proof fence.
        if transition != "background" or kind != "metadata":
            assert not matching_ack(socket.messages, request_id)
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await cleanup(manager)


@pytest.mark.parametrize("value", [None, "", "bad", "0" * 36, str(uuid.UUID(int=0, version=1)), str(uuid.UUID(int=10 << 124, version=4)).upper()])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover

def test_noncanonical_or_non_v4_request_identity_cannot_be_admitted(value):
    assert websockets._validated_inventory_request_id(value) is None


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover

def test_metadata_retry_correlation_comes_from_original_route_and_requires_same_request():
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[2] /
                      "backend/core/api/app/routes/websockets.py").read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "send_available_metadata_jobs"]
    values = [next(kw.value for kw in call.keywords if kw.arg == "inventory_request_id") for call in calls]
    assert len(values) == 2
    assert any(isinstance(value, ast.Name) and value.id == "inventory_request_id" for value in values)
    retry = next(value for value in values if isinstance(value, ast.IfExp))
    assert isinstance(retry.body, ast.Name) and retry.body.id == "inventory_request_id"
    assert isinstance(retry.orelse, ast.Constant) and retry.orelse.value is None
    assert isinstance(retry.test, ast.Compare) and len(retry.test.ops) == 1 and isinstance(retry.test.ops[0], ast.Eq)
    assert isinstance(retry.test.comparators[0], ast.Name) and retry.test.comparators[0].id == "inventory_request_id"
    assert isinstance(retry.test.left, ast.Call) and isinstance(retry.test.left.func, ast.Attribute)
    assert isinstance(retry.test.left.func.value, ast.Name) and retry.test.left.func.value.id == "payload"
    assert retry.test.left.func.attr == "get"
    assert isinstance(retry.test.left.args[0], ast.Constant) and retry.test.left.args[0].value == "inventory_request_id"
