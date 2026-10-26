"""In-process final fanout with real listener and recovery discovery handlers."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from fastapi import HTTPException

from backend.core.api.app.routes import websockets
from backend.core.api.app.routes.handlers.websocket_handlers import chat_recovery_job_handlers as recovery


OWNER = "owner-private-canary"
CHAT = "chat-private-canary"


class Manager:
    def __init__(self, devices):
        self.active_connections = {OWNER: {device: object() for device in devices}}
        self.capable = set(devices)
        self.messages = []
        self.background = set()
        self.final_received = asyncio.Event()
        self.raise_send_for = None
        self.false_send = None

    def get_connections_for_user(self, owner):
        # Deliberately expose a mutable mapping to verify the listener snapshots.
        return self.active_connections.get(owner, {})

    def is_connection_completion_capable(self, owner, device):
        return owner == OWNER and device in self.capable

    def supports_typed_recovery_outputs(self, owner, device):
        return self.is_connection_completion_capable(owner, device)

    def get_active_chat(self, owner, device):
        return "other-chat" if device in self.background else CHAT

    def has_foreground_connection_for_chat(self, owner, chat):
        return True

    async def send_personal_message(self, message, user_id, device_fingerprint_hash, *, expected_websocket=None):
        current = self.active_connections.get(user_id, {}).get(device_fingerprint_hash)
        assert expected_websocket is not None
        if current is not expected_websocket:
            return False
        if device_fingerprint_hash == self.raise_send_for:
            raise RuntimeError("transport-private-canary")
        if (device_fingerprint_hash, message["type"]) == self.false_send:
            return False
        self.messages.append((device_fingerprint_hash, message))
        if message["type"] in {"ai_message_update", "ai_background_response_completed"}:
            self.final_received.set()
        return True


def payload(**overrides):
    return {
        "type": "ai_message_chunk", "user_id_uuid": OWNER, "user_id_hash": "owner-hash-private-canary",
        "chat_id": CHAT, "message_id": "assistant-private-canary", "user_message_id": "user-private-canary",
        "full_content_so_far": "content-private-canary", "is_final_chunk": True,
        "recovery_protocol_version": 1, "recovery_provisional": False,
        "recovery_job_id": "job-private-canary", "recovery_turn_id": "turn-private-canary",
        "created_at": 1793022695, **overrides,
    }


def install(monkeypatch, manager, execute, message=None):
    class Cache:
        @property
        def client(self):
            async def connected():
                return object()
            return connected()

        async def delete(self, key):
            pass

        async def subscribe_to_channel(self, channel):
            assert channel == "chat_stream::*"
            yield {"channel": "chat_stream::" + CHAT, "data": message if message is not None else payload()}

    class RecoveryService:
        def __init__(self, service):
            assert service is directus

        async def execute(self, operation, data):
            return await execute(operation, data["device_hash"])

    directus = object()
    monkeypatch.setattr(websockets, "manager", manager)
    monkeypatch.setattr(recovery, "ChatRecoveryService", RecoveryService)
    monkeypatch.setattr(websockets, "_send_offline_email_notification", AsyncMock())
    return SimpleNamespace(state=SimpleNamespace(cache_service=Cache(), directus_service=directus))


def result_for(operation):
    return {"jobs": []} if operation == "list_available_jobs" else {"outputs": []}


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_blocked_failing_first_device_does_not_hold_healthy_final(monkeypatch):
    manager = Manager(["slow", "healthy"])
    entered, release = asyncio.Event(), asyncio.Event()

    async def execute(operation, device):
        if device == "slow":
            entered.set()
            await release.wait()
            raise RuntimeError("query-private-canary")
        return result_for(operation)

    app = install(monkeypatch, manager, execute)
    task = asyncio.create_task(websockets.listen_for_ai_chat_streams(app))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(manager.final_received.wait(), 1)
        assert not task.done(), "healthy delivery precedes release of the blocked peer"
    finally:
        release.set()
        await asyncio.wait_for(task, 1)
    assert [(device, frame["type"]) for device, frame in manager.messages] == [
        ("healthy", "recovery_jobs_available"),
        ("healthy", "recovery_outputs_discovery_complete"),
        ("healthy", "ai_message_update"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["list_available_jobs", "list_pending_outputs"])
@pytest.mark.parametrize("mutation", ["replace", "disconnect", "background"])
# contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_discovery_rechecks_origin_and_completion_capability(monkeypatch, stage, mutation):
    manager = Manager(["changing", "healthy"])
    calls = []

    async def execute(operation, device):
        calls.append((device, operation))
        await asyncio.sleep(0)
        if device == "changing" and operation == stage:
            if mutation == "replace":
                manager.active_connections[OWNER][device] = object()
            elif mutation == "disconnect":
                del manager.active_connections[OWNER][device]
            else:
                manager.capable.remove(device)
        return result_for(operation)

    await websockets.listen_for_ai_chat_streams(install(monkeypatch, manager, execute))
    changing = [frame["type"] for device, frame in manager.messages if device == "changing"]
    assert changing == ([] if stage == "list_available_jobs" else ["recovery_jobs_available"])
    assert any(device == "healthy" and frame["type"] == "ai_message_update" for device, frame in manager.messages)
    if stage == "list_available_jobs":
        assert ("changing", "list_pending_outputs") not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["false", "exception", "transport", "outputs_transport_false", "read_timeout", "pool_timeout"])
# contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_failed_device_is_fail_closed_without_aborting_remaining_peers(monkeypatch, caplog, failure):
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    monkeypatch.setattr(websockets.logger, "handlers", [caplog.handler])
    caplog.set_level(logging.INFO, logger=websockets.__name__)
    manager = Manager(["failed", "healthy"])
    if failure == "transport":
        manager.raise_send_for = "failed"
    if failure == "outputs_transport_false":
        manager.false_send = ("failed", "recovery_outputs_discovery_complete")

    async def execute(operation, device):
        if device == "failed":
            if failure == "false" and operation == "list_available_jobs":
                return {"jobs": "invalid-private-canary"}
            if failure == "exception" and operation == "list_pending_outputs":
                raise recovery.ChatRecoveryProtocolError(403, "forbidden")
            if failure == "read_timeout" and operation == "list_pending_outputs":
                raise httpx.ReadTimeout("request-private-canary")
            if failure == "pool_timeout" and operation == "list_pending_outputs":
                raise httpx.PoolTimeout("request-private-canary")
        return result_for(operation)

    await websockets.listen_for_ai_chat_streams(install(monkeypatch, manager, execute))
    assert not any(device == "failed" and frame["type"] == "ai_message_update" for device, frame in manager.messages)
    assert any(device == "healthy" and frame["type"] == "ai_message_update" for device, frame in manager.messages)
    if failure == "exception":
        assert "Final stream delivery stage=outputs_result device=1 success=false exception=ChatRecoveryProtocolError code=forbidden" in [
            record.getMessage() for record in caplog.records
        ]
    if failure in {"read_timeout", "pool_timeout"}:
        expected_class = "ReadTimeout" if failure == "read_timeout" else "PoolTimeout"
        assert f"Final stream delivery stage=outputs_result device=1 success=false exception={expected_class} code=none" in [
            record.getMessage() for record in caplog.records
        ]


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_final_discovery_concurrency_is_bounded_to_four(monkeypatch):
    manager = Manager([f"device-{n}" for n in range(12)])
    release, entered_four = asyncio.Event(), asyncio.Event()
    active = maximum = 0

    async def execute(operation, device):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 4:
            entered_four.set()
        try:
            await release.wait()
            return result_for(operation)
        finally:
            active -= 1

    task = asyncio.create_task(websockets.listen_for_ai_chat_streams(install(monkeypatch, manager, execute)))
    try:
        await asyncio.wait_for(entered_four.wait(), 1)
        assert active == 4
    finally:
        release.set()
        await asyncio.wait_for(task, 1)
    assert maximum == 4
    assert sum(frame["type"] == "ai_message_update" for _, frame in manager.messages) == 12


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
async def test_background_final_preserves_identity_and_discovery_order(monkeypatch):
    manager = Manager(["background"])
    manager.background.add("background")

    async def execute(operation, device):
        return result_for(operation)

    original = payload(is_sub_chat_continuation=True, awaiting_focus_mode_continuation=True)
    await websockets.listen_for_ai_chat_streams(install(monkeypatch, manager, execute, original))
    assert [frame["type"] for _, frame in manager.messages] == [
        "recovery_jobs_available", "recovery_outputs_discovery_complete",
        "ai_background_response_completed", "ai_typing_ended",
    ]
    delivered = manager.messages[2][1]["payload"]
    for field in ("chat_id", "message_id", "user_message_id", "recovery_job_id", "recovery_turn_id",
                  "recovery_protocol_version", "created_at", "is_sub_chat_continuation", "awaiting_focus_mode_continuation"):
        assert delivered[field] == original[field]
    assert delivered["full_content"] == original["full_content_so_far"]


@pytest.mark.parametrize("ci", [None, "0", "true", "1"])
# contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery
def test_ci_stage_trace_has_fixed_values_and_no_private_fields(monkeypatch, caplog, ci):
    monkeypatch.setattr(websockets.logger, "handlers", [caplog.handler])
    if ci is None:
        monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
    else:
        monkeypatch.setenv("OPENMATES_CI_ISOLATED", ci)
    caplog.set_level(logging.INFO, logger=websockets.__name__)
    error = type("ExceptionWithPrivateCanary", (Exception,), {})("content https://private.invalid/ SECRET")
    error.code = {"key-private-canary": "sensitive"}
    websockets._trace_final_stream_delivery("outputs_result", 9000, False, error)
    websockets._trace_final_stream_delivery("unknown-private-canary", 1)
    messages = [record.getMessage() for record in caplog.records]
    assert messages == (["Final stream delivery stage=outputs_result device=128 success=false exception=other code=other"]
                        if ci == "1" else [])


@pytest.mark.parametrize("exception_type", [
    httpx.ReadTimeout, httpx.PoolTimeout, httpx.WriteTimeout, httpx.ConnectTimeout, httpx.ConnectError,
    httpx.ReadError, httpx.RemoteProtocolError, AttributeError, KeyError, IndexError, json.JSONDecodeError, HTTPException,
])
# contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery
def test_ci_stage_trace_exposes_only_allowlisted_standard_exception_class(monkeypatch, caplog, exception_type):
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    monkeypatch.setattr(websockets.logger, "handlers", [caplog.handler])
    caplog.set_level(logging.INFO, logger=websockets.__name__)
    if exception_type is json.JSONDecodeError:
        error = exception_type("message-private-canary", "document-private-canary", 0)
    elif exception_type is HTTPException:
        error = exception_type(403, "detail-private-canary")
    else:
        error = exception_type("https://private.invalid/key-private-canary")
    websockets._trace_final_stream_delivery("outputs_result", 1, False, error)
    assert [record.getMessage() for record in caplog.records] == [
        f"Final stream delivery stage=outputs_result device=1 success=false exception={exception_type.__name__} code=none"
    ]


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery
async def test_ci_stage_sequence_is_content_free_and_received_precedes_lookup(monkeypatch, caplog):
    monkeypatch.setattr(websockets.logger, "handlers", [caplog.handler])
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    caplog.set_level(logging.INFO, logger=websockets.__name__)
    manager = Manager(["device-private-canary"])

    async def execute(operation, device):
        return result_for(operation)

    await websockets.listen_for_ai_chat_streams(install(monkeypatch, manager, execute))
    traces = [record.getMessage() for record in caplog.records if record.getMessage().startswith("Final stream delivery stage=")]
    assert traces == [
        "Final stream delivery stage=final_received device=0 success=none exception=none code=none",
        "Final stream delivery stage=jobs_begin device=1 success=none exception=none code=none",
        "Final stream delivery stage=jobs_result device=1 success=true exception=none code=none",
        "Final stream delivery stage=outputs_begin device=1 success=none exception=none code=none",
        "Final stream delivery stage=outputs_result device=1 success=true exception=none code=none",
        "Final stream delivery stage=final_send device=1 success=true exception=none code=none",
    ]
    assert "private-canary" not in "\n".join(traces)
    caplog.clear()
    await websockets.listen_for_ai_chat_streams(install(monkeypatch, manager, execute, payload(user_id_uuid=None)))
    assert [record.getMessage() for record in caplog.records if record.getMessage().startswith("Final stream delivery stage=")] == traces[:1]
