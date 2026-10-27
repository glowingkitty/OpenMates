"""PRIVATE UNRUN: paused inventory acknowledges query-scoped absence only.

Services are mocked; no sockets, Redis, Directus or inference requests are made.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes import websockets
from backend.core.api.app.routes.handlers.websocket_handlers import chat_recovery_job_handlers as jobs
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Manager:
    def __init__(self, capable=True):
        self.capable, self.messages = capable, []
        self.active_connections = {"owner": {"device": object()}}

    def is_connection_completion_capable(self, user, device):
        assert (user, device) == ("owner", "device")
        return self.capable

    async def send_personal_message(self, message, user, device, *, expected_websocket=None):
        assert (user, device) == ("owner", "device")
        if expected_websocket is not None and self.active_connections[user][device] is not expected_websocket:
            return False
        self.messages.append(message)
        return True


def setup_read(monkeypatch, *, epoch=0, result=None, error=None, manager=None):
    manager = manager or Manager()

    class Cutover:
        def __init__(self, *_):
            pass

        async def get_epoch(self, *, authoritative):
            assert authoritative is True
            if epoch is None:
                raise RuntimeError("synthetic epoch failure")
            return epoch

    query = AsyncMock(side_effect=error, return_value=result)
    outputs = AsyncMock()
    monkeypatch.setattr(websockets, "ChatRecoveryCutoverController", Cutover)
    monkeypatch.setattr(jobs, "ChatRecoveryService", lambda _: SimpleNamespace(execute=query))
    monkeypatch.setattr(websockets, "send_available_recovery_outputs", outputs)
    return manager, query, outputs


async def discover(manager, *, opt_in=False, typed=True):
    await websockets._discover_foreground_recovery(
        manager=manager, cache_service=object(), directus_service=object(),
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device",
        supports_typed_recovery_outputs=typed, user_otel_attrs={}, inventory_empty_ack=opt_in,
        inventory_request_id=_REQUEST_ID if opt_in else None,
    )


def assert_read_only(query):
    query.assert_awaited_once_with("list_available_jobs", {
        "protocol_version": 1, "hashed_user_id": "owner-hash", "device_hash": "device",
    })


DISABLED = {"type": "recovery_outputs_discovery_complete", "payload": {"status": "disabled"}}
_REQUEST_ID = str(uuid.uuid4())
EMPTY = {"type": "recovery_jobs_available", "payload": {"jobs": [], "inventory_request_id": _REQUEST_ID}}
BOUND_DISABLED = {"type": "recovery_outputs_discovery_complete", "payload": {"status": "disabled", "inventory_request_id": _REQUEST_ID}}


@pytest.mark.anyio
@pytest.mark.parametrize("typed", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_paused_opt_in_empty_ack_precedes_unchanged_disabled_fence(monkeypatch, typed):
    manager, query, outputs = setup_read(monkeypatch, result={"jobs": []})
    await discover(manager, opt_in=True, typed=typed)
    assert_read_only(query)
    assert manager.messages == [EMPTY, BOUND_DISABLED]
    outputs.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("result", [{"jobs": [{"job_id": "available"}]}, {}, {"jobs": None}, {"jobs": {}}, None])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_paused_nonempty_or_malformed_query_never_offers_or_certifies_empty(monkeypatch, result):
    manager, query, outputs = setup_read(monkeypatch, result=result)
    await discover(manager, opt_in=True)
    assert_read_only(query)
    assert manager.messages == [BOUND_DISABLED]
    outputs.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [ChatRecoveryProtocolError(403, "denied"), ChatRecoveryProtocolError(404, "missing"),
    ChatRecoveryProtocolError(503, "unavailable"), RuntimeError("synthetic missing table or column")])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_paused_query_failure_never_becomes_empty_success(monkeypatch, error):
    manager, query, outputs = setup_read(monkeypatch, error=error)
    await discover(manager, opt_in=True)
    assert_read_only(query)
    assert manager.messages == [BOUND_DISABLED]
    outputs.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("typed", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_paused_legacy_keeps_disabled_fence_without_job_query(monkeypatch, typed):
    manager, query, outputs = setup_read(monkeypatch, result={"jobs": []})
    await discover(manager, typed=typed)
    assert manager.messages == [DISABLED]
    query.assert_not_awaited()
    outputs.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("lost_during_read", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_paused_ineligible_or_lost_device_never_acknowledges(monkeypatch, lost_during_read):
    manager, query, outputs = setup_read(monkeypatch, manager=Manager(capable=lost_during_read))

    async def lose(*_):
        manager.capable = False
        return {"jobs": []}

    query.side_effect = lose
    await discover(manager, opt_in=True)
    assert query.await_count == int(lost_during_read)
    assert manager.messages == []
    outputs.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("opt_in", [False, True])
@pytest.mark.parametrize("typed", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_active_epoch_retains_existing_offers_and_output_dispatch(monkeypatch, opt_in, typed):
    offered = {"jobs": [{"job_id": "available"}]}
    manager, query, outputs = setup_read(monkeypatch, epoch=1, result=offered)
    await discover(manager, opt_in=opt_in, typed=typed)
    assert_read_only(query)
    expected = {**offered, **({"inventory_request_id": _REQUEST_ID} if opt_in else {})}
    assert manager.messages == [{"type": "recovery_jobs_available", "payload": expected}]
    assert outputs.await_count == int(typed)


@pytest.mark.anyio
@pytest.mark.parametrize("opt_in", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_unknown_epoch_never_queries_or_certifies_absence(monkeypatch, opt_in):
    manager, query, outputs = setup_read(monkeypatch, epoch=None, result={"jobs": []})
    await discover(manager, opt_in=opt_in)
    assert manager.messages == [{"type": "recovery_outputs_discovery_complete", "payload": {"status": "failed", **({"inventory_request_id": _REQUEST_ID} if opt_in else {})}}]
    query.assert_not_awaited()
    outputs.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_inventory_flag_is_default_off_and_propagated_from_existing_opt_in():
    source = (Path(__file__).resolve().parents[2] / "backend/core/api/app/routes/websockets.py").read_text()
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_discover_foreground_recovery")
    defaults = dict(zip([arg.arg for arg in function.args.kwonlyargs], function.args.kw_defaults))
    assert isinstance(defaults["inventory_empty_ack"], ast.Constant) and defaults["inventory_empty_ack"].value is False
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_discover_foreground_recovery"]
    assert len(calls) == 1
    flag = next(kw.value for kw in calls[0].keywords if kw.arg == "inventory_empty_ack")
    assert isinstance(flag, ast.Name) and flag.id == "complete_task_inventory"
    assert 'complete_task_inventory = "task_update_jobs_inventory_v1" in connection_capabilities' in source


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_available_query_stays_owner_device_validated_bounded_select_only():
    source = (Path(__file__).resolve().parents[2] /
              "backend/core/directus/extensions/chat-recovery-transaction/src/operations.js").read_text()
    query = source.split("async function listAvailableJobs(", 1)[1].split("\nfunction activeJob(", 1)[0]
    assert "operationBody(raw, 'list_available_jobs')" in query
    assert "string(body.hashed_user_id, 'invalid_owner', 64)" in query
    assert "string(body.device_hash, 'invalid_device', 128)" in query
    assert ".where({ hashed_user_id: ownerHash })" in query
    assert ".whereNull('invalidated_at')" in query
    assert ".limit(MAX_AVAILABLE_JOBS)" in query and ".select([" in query
    assert not re.search(r"\.(?:insert|update|delete|del|transaction|increment|decrement)\s*\(", query)
    assert not re.search(r"epoch|sends_paused|activate", query, re.IGNORECASE)


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_nonzero_disabled_epoch_is_not_an_empty_inventory_query(monkeypatch):
    manager, query, outputs = setup_read(monkeypatch, epoch=-1, result={"jobs": []})
    await discover(manager, opt_in=True)
    assert manager.messages == [BOUND_DISABLED]
    query.assert_not_awaited()
    outputs.assert_not_awaited()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_paused_opt_in_without_request_correlation_keeps_proof_closed(monkeypatch):
    manager, query, outputs = setup_read(monkeypatch, result={"jobs": []})
    await websockets._discover_foreground_recovery(
        manager=manager, cache_service=object(), directus_service=object(),
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device",
        supports_typed_recovery_outputs=True, user_otel_attrs={}, inventory_empty_ack=True,
    )
    assert manager.messages == [DISABLED]
    query.assert_not_awaited()
    outputs.assert_not_awaited()
