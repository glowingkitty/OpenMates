# backend/tests/test_finished_turn_resend.py
#
# A client resend of an already finished chat turn is acknowledged quietly:
# no error frame, no reprocessing, exactly one WARNING log line.

# contract-test-file: infrastructure

import asyncio
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.team_methods import hash_id

sys.modules.setdefault("backend.core.api.app.services.cache", SimpleNamespace(CacheService=object))
sys.modules.setdefault("backend.core.api.app.services.directus.directus", SimpleNamespace(DirectusService=object))

from backend.core.api.app.routes.handlers.websocket_handlers import (  # noqa: E402
    chat_turn_preflight_handler,
    finished_turn_resend,
    message_received_handler,
)
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError  # noqa: E402

FINISHED = {
    "finished": True, "state": "TERMINAL", "preflight_id": "pf-1", "turn_id": "turn-1",
    "inference_task_id": "task-1", "assistant_message_id": "assistant-1",
    "committed_messages_v": 4, "recovery_job": None,
}
FIXED_TEXT = "Resend of a finished turn acknowledged without processing"


class Manager:
    def __init__(self):
        self.messages = []

    def get_volatile_session_nonce(self, *_args):
        return "nonce"

    async def send_personal_message(self, message, *_args):
        self.messages.append(message)


class Socket:
    def __init__(self):
        self.sent = []
        self.scope = {}

    async def send_json(self, message):
        self.sent.append(message)


def _lookup(monkeypatch, response):
    calls = []

    class FakeService:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, data):
            calls.append((operation, data))
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(finished_turn_resend, "ChatRecoveryService", FakeService)
    return calls


def _run_send(monkeypatch, *, payload_extra, enqueue, lookup):
    cache = SimpleNamespace(
        set=AsyncMock(), get=AsyncMock(return_value=None),
        get_active_ai_task=AsyncMock(return_value=None), try_claim_active_ai_task=AsyncMock(),
    )
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_chat_metadata=AsyncMock(return_value={
            "id": "chat-123", "hashed_user_id": hash_id("user-123"),
            "chat_visibility": None, "messages_v": 1,
        }),
        check_chat_ownership=AsyncMock(return_value=True),
    ))
    calls = _lookup(monkeypatch, lookup)
    monkeypatch.setattr(message_received_handler, "ChatRecoveryCutoverController",
                        lambda *_a: SimpleNamespace(get_epoch=AsyncMock(return_value=1)))
    monkeypatch.setattr(message_received_handler, "enqueue_chat_turn", enqueue)
    dispatch = AsyncMock()
    monkeypatch.setattr(message_received_handler, "dispatch_skill", dispatch, raising=False)
    manager, socket = Manager(), Socket()
    asyncio.run(asyncio.wait_for(message_received_handler.handle_message_received(
        websocket=socket, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=SimpleNamespace(), user_id="user-123", device_fingerprint_hash="device-123",
        payload={
            "chat_id": "chat-123", "protocol_version": 1,
            "message": {"message_id": "msg-123", "temp_id": "tmp-1", "role": "user",
                        "content": "hello", "created_at": 1_700_000_000},
            **payload_extra,
        },
    ), timeout=3))
    return manager, socket, cache, dispatch, calls


def _assert_quiet(manager, socket, cache, dispatch, calls, caplog, path):
    frames = socket.sent + manager.messages
    assert not [f for f in frames if f["type"] == "error"]
    assert calls[0][0] == "get_finished_turn"
    assert calls[0][1] == {"protocol_version": 1, "hashed_user_id": hash_id("user-123"),
                           "chat_id": "chat-123", "user_message_id": "msg-123"}
    confirmed = [f for f in frames if f["type"] == "chat_message_confirmed"]
    assert confirmed == [{"type": "chat_message_confirmed", "payload": {
        "chat_id": "chat-123", "message_id": "msg-123", "temp_id": "tmp-1",
        "turn_already_completed": True, "turn_id": "turn-1",
        "assistant_message_id": "assistant-1", "new_messages_v": 4}}]
    assert {"type": "ai_typing_ended", "payload": {
        "chat_id": "chat-123", "message_id": "assistant-1", "user_message_id": "msg-123"}} in frames
    cache.set.assert_not_awaited()
    cache.try_claim_active_ai_task.assert_not_awaited()
    dispatch.assert_not_awaited()
    records = [r for r in caplog.records if FIXED_TEXT in r.getMessage()]
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert f"path={path}" in records[0].getMessage() and "turn_state=TERMINAL" in records[0].getMessage()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
def test_missing_preflight_resend_of_finished_turn_is_acknowledged(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    enqueue = AsyncMock()
    result = _run_send(monkeypatch, payload_extra={}, enqueue=enqueue, lookup=FINISHED)
    enqueue.assert_not_awaited()
    _assert_quiet(*result, caplog, "missing_preflight")


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.parametrize("code", ["preflight_not_found", "preflight_mismatch"])
def test_rejected_enqueue_resend_of_finished_turn_is_acknowledged(monkeypatch, caplog, code):
    caplog.set_level(logging.WARNING)
    enqueue = AsyncMock(side_effect=ChatRecoveryProtocolError(409, code))
    result = _run_send(monkeypatch, payload_extra={"preflight_id": "pf-1"}, enqueue=enqueue, lookup=FINISHED)
    _assert_quiet(*result, caplog, "enqueue_rejected")


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
def test_enqueue_returning_finished_preflight_is_acknowledged_without_processing(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    enqueue = AsyncMock(return_value={"state": "CONSUMED", "preflight_id": "pf-1"})
    result = _run_send(monkeypatch, payload_extra={"preflight_id": "pf-1"}, enqueue=enqueue, lookup=FINISHED)
    _assert_quiet(*result, caplog, "enqueue_finished")


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.parametrize("lookup", [{"finished": False}, ChatRecoveryProtocolError(503, "unavailable")])
def test_finished_enqueue_is_acknowledged_even_when_lookup_finds_nothing(monkeypatch, caplog, lookup):
    caplog.set_level(logging.WARNING)
    enqueue = AsyncMock(return_value={
        "state": "TERMINAL", "preflight_id": "pf-1", "turn_id": "turn-1", "committed_messages_v": 4})
    manager, socket, cache, dispatch, _calls = _run_send(
        monkeypatch, payload_extra={"preflight_id": "pf-1"}, enqueue=enqueue, lookup=lookup)
    frames = socket.sent + manager.messages
    assert not [f for f in frames if f["type"] == "error"]
    assert [f["payload"] for f in frames if f["type"] == "chat_message_confirmed"] == [{
        "chat_id": "chat-123", "message_id": "msg-123", "temp_id": "tmp-1",
        "turn_already_completed": True, "turn_id": "turn-1", "new_messages_v": 4}]
    assert {"type": "ai_typing_ended", "payload": {
        "chat_id": "chat-123", "user_message_id": "msg-123"}} in frames
    cache.set.assert_not_awaited()
    cache.try_claim_active_ai_task.assert_not_awaited()
    dispatch.assert_not_awaited()
    records = [r for r in caplog.records if FIXED_TEXT in r.getMessage()]
    assert len(records) == 1 and "path=enqueue_finished" in records[0].getMessage()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.parametrize("lookup", [
    {"finished": False}, ChatRecoveryProtocolError(503, "unavailable"),
])
def test_unfinished_turn_keeps_existing_error(monkeypatch, caplog, lookup):
    caplog.set_level(logging.WARNING)
    enqueue = AsyncMock(side_effect=ChatRecoveryProtocolError(409, "preflight_mismatch"))
    manager, socket, cache, dispatch, _calls = _run_send(
        monkeypatch, payload_extra={"preflight_id": "pf-1"}, enqueue=enqueue, lookup=lookup)
    assert [m["payload"]["code"] for m in manager.messages if m["type"] == "error"] == ["preflight_mismatch"]
    assert not [f for f in socket.sent + manager.messages if f["type"] == "chat_message_confirmed"]
    assert not [r for r in caplog.records if FIXED_TEXT in r.getMessage()]


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
def test_preflight_mismatch_for_finished_turn_returns_ack_not_error(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    _lookup(monkeypatch, FINISHED)
    monkeypatch.setattr(chat_turn_preflight_handler, "find_finished_turn",
                        finished_turn_resend.find_finished_turn)
    manager = Manager()

    async def boom(*_a, **_k):
        raise ChatRecoveryProtocolError(409, "preflight_mismatch")

    monkeypatch.setattr(chat_turn_preflight_handler, "ChatRecoveryService",
                        lambda _d: SimpleNamespace(execute=boom))
    payload = {"chat_id": "chat-123", "message_id": "msg-123", "turn_id": "turn-1",
               "temp_id": "tmp-1", "protocol_version": 1}
    asyncio.run(chat_turn_preflight_handler.handle_chat_turn_preflight(
        manager=manager, directus_service=SimpleNamespace(), user_id="user-123",
        user_id_hash=hash_id("user-123"), device_fingerprint_hash="device-123", payload=payload,
    ))
    frames = manager.messages
    assert [f["type"] for f in frames] == [
        "chat_turn_preflight_ack", "chat_message_confirmed", "ai_typing_ended"]
    assert frames[1]["payload"] == {
        "chat_id": "chat-123", "message_id": "msg-123", "temp_id": "tmp-1",
        "turn_already_completed": True, "turn_id": "turn-1",
        "assistant_message_id": "assistant-1", "new_messages_v": 4}
    assert frames[2]["payload"] == {
        "chat_id": "chat-123", "message_id": "assistant-1", "user_message_id": "msg-123"}
    assert frames[0]["payload"] == {"preflight_id": "pf-1", "state": "TERMINAL",
                                    "committed_messages_v": 4, "turn_id": "turn-1"}
    assert len([r for r in caplog.records if FIXED_TEXT in r.getMessage()]) == 1
