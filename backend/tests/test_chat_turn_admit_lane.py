"""The same socket may deliver bound context while dispatch is still admitting."""
import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import chat_turn_admit_handler as handler


@pytest.fixture
def lane_admission(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = asyncio.Event()

    async def held_dispatch(**kwargs):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    dispatch = AsyncMock(side_effect=held_dispatch)
    module = ModuleType("backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler")
    module.handle_message_received = dispatch
    monkeypatch.setitem(sys.modules, module.__name__, module)
    preflight = AsyncMock(return_value={
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "state": "PREPARED",
        "client_context_binding_ref": "server-binding",
    })
    monkeypatch.setattr(handler, "handle_chat_turn_preflight", preflight)
    payload = {
        "protocol_version": 1,
        "chat_id": "11111111-1111-4111-8111-111111111111",
        "turn_id": "22222222-2222-4222-8222-222222222222",
        "message_id": "1111111111-33333333-3333-4333-8333-333333333333",
    }
    request_id = "44444444-4444-4444-8444-444444444444"
    payload["inference_request"] = {
        "chat_id": payload["chat_id"], "turn_id": payload["turn_id"],
        "message": {"message_id": payload["message_id"], "content": "What is the capital of Spain?"},
        "client_context_pending": True, "client_context_request_id": request_id,
        "is_incognito": False,
    }
    args = dict(
        websocket=SimpleNamespace(send_json=AsyncMock()), manager=object(),
        cache_service=object(), directus_service=object(), encryption_service=object(),
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device",
        payload=payload,
    )
    return args, preflight, dispatch, started, release, cancelled


def context_frame(payload, message_type):
    return {"type": message_type, "payload": {
        "chat_id": payload["chat_id"], "turn_id": payload["turn_id"],
        "message_id": payload["message_id"],
        "request_id": payload["inference_request"]["client_context_request_id"],
        "team_id": None,
        **({"phase": "initial", "context": {}} if message_type == "chat_turn_context_ready"
           else {"reason": "unavailable"}),
    }}


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_lane_opens_only_after_durable_ack_and_context_binding(lane_admission):
    args, preflight, _, started, _, _ = lane_admission
    commit_started = asyncio.Event()
    commit_release = asyncio.Event()
    acknowledgement = preflight.return_value

    async def held_preflight(**kwargs):
        commit_started.set()
        await commit_release.wait()
        return acknowledgement

    preflight.side_effect = held_preflight
    lanes = []
    admitting = asyncio.create_task(
        handler.handle_chat_turn_admit(**args, schedule_context_dispatch=lanes.append),
    )
    await commit_started.wait()
    assert lanes == []
    commit_release.set()
    await admitting
    await started.wait()
    assert len(lanes) == 1
    assert lanes[0].request_id == args["payload"]["inference_request"]["client_context_request_id"]
    await lanes[0].close()


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
@pytest.mark.parametrize("message_type", ["chat_turn_context_ready", "chat_turn_context_failed"])
async def test_real_context_handler_accepts_bound_phase_before_dispatch_release(
    lane_admission, message_type,
):
    from backend.core.api.app.routes.handlers.websocket_handlers.client_context_ready_handler import (
        handle_client_context_failed, handle_client_context_ready,
    )
    from backend.core.api.app.services import client_context_continuation as context
    from backend.tests.test_client_context_continuation import Redis, Vault

    args, preflight, dispatch, started, release, _ = lane_admission
    redis, vault = Redis(), Vault()

    class Cache:
        @property
        async def client(self):
            return redis

        async def get_user_vault_key_id(self, user_id):
            return "key:" + user_id

    events = []
    cache = Cache()
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    directus = SimpleNamespace(team=SimpleNamespace(require_team_role=AsyncMock()))
    websocket = SimpleNamespace(send_json=AsyncMock())
    args.update(
        cache_service=cache, encryption_service=vault, manager=manager,
        directus_service=directus, websocket=websocket,
    )
    binding_refs = []

    async def committed_preflight(**kwargs):
        # The real binding service runs before the simulated durable ACK.
        reference = await kwargs["atomic_before_ack"]({})
        binding_refs.append(reference)
        assert context._key(reference) in redis.values
        await websocket.send_json({"type": "chat_turn_preflight_result", "payload": {
            "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        }})
        events.append("ack")
        return {
            "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "state": "PREPARED",
            "client_context_binding_ref": reference,
        }

    preflight.side_effect = committed_preflight

    async def held_dispatch(**kwargs):
        assert events == ["ack"]
        assert kwargs["client_context_binding_ref"] is not None
        started.set()
        await release.wait()

    dispatch.side_effect = held_dispatch
    lanes = []
    await handler.handle_chat_turn_admit(**args, schedule_context_dispatch=lanes.append)
    await started.wait()
    assert len(lanes) == 1
    if message_type == "chat_turn_context_ready":
        frame = context_frame(args["payload"], message_type)
        frame["payload"].update(phase="routing", context={"project_focus_candidates": []})
        context_handler = handle_client_context_ready
        marker = ":routing"
        ack_type = "chat_turn_context_ack"
    else:
        frame = context_frame(args["payload"], message_type)
        frame["payload"]["reason"] = "context_preparation_failed"
        context_handler = handle_client_context_failed
        marker = ":failed"
        ack_type = "chat_turn_context_failed_ack"

    received, active = await lanes[0].receive_next(lambda: asyncio.sleep(0, result=frame))
    assert active and received is frame and not release.is_set()
    await context_handler(
        manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=vault, user_id="owner", device_fingerprint_hash="device",
        payload=received["payload"],
    )
    ack = manager.send_personal_message.await_args.args[0]
    assert ack["type"] == ack_type
    assert ack["payload"]["status"] == "accepted"
    assert not lanes[0].task.done()
    assert redis.values[context._key(binding_refs[0]) + marker].startswith("vault:v1:")
    assert set(redis.expiry.values()) == {120}
    release.set()
    await lanes[0].close()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.send.immediate-admission
@pytest.mark.asyncio
@pytest.mark.parametrize("message_type", ["chat_turn_context_ready", "chat_turn_context_failed"])
async def test_exact_context_passes_before_held_dispatch_finishes(lane_admission, message_type):
    args, preflight, dispatch, started, release, _ = lane_admission
    lanes = []
    await handler.handle_chat_turn_admit(**args, schedule_context_dispatch=lanes.append)
    assert len(lanes) == 1
    preflight.assert_awaited_once()
    await started.wait()
    assert dispatch.await_args.kwargs["client_context_binding_ref"] == "server-binding"
    frame = context_frame(args["payload"], message_type)
    received, active = await asyncio.wait_for(
        lanes[0].receive_next(lambda: asyncio.sleep(0, result=frame)), 0.1,
    )
    assert (received, active) == (frame, True)
    assert not lanes[0].task.done()
    release.set()
    await lanes[0].close()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.send.immediate-admission
@pytest.mark.asyncio
async def test_unrelated_frame_waits_for_dispatch_before_second_admission(lane_admission):
    args, _, _, started, release, _ = lane_admission
    lanes = []
    await handler.handle_chat_turn_admit(**args, schedule_context_dispatch=lanes.append)
    await started.wait()
    second = {"type": "chat_turn_admit", "payload": {"turn_id": "another"}}
    receive_count = 0
    second_processed = asyncio.Event()

    async def receive():
        nonlocal receive_count
        receive_count += 1
        return second

    async def receive_then_process():
        frame, active = await lanes[0].receive_next(receive)
        second_processed.set()
        return frame, active

    pending = asyncio.create_task(receive_then_process())
    await asyncio.sleep(0)
    assert receive_count == 1
    assert not pending.done()
    assert not second_processed.is_set()
    # An unrelated frame is held locally; no second receive or admission occurs.
    assert receive_count == 1
    release.set()
    assert await pending == (second, False)
    assert second_processed.is_set()
    await lanes[0].close()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.send.immediate-admission
@pytest.mark.asyncio
async def test_disconnect_cancels_held_continuation(lane_admission):
    args, _, _, started, _, cancelled = lane_admission
    lanes = []
    await handler.handle_chat_turn_admit(**args, schedule_context_dispatch=lanes.append)
    await started.wait()
    await lanes[0].close()
    assert cancelled.is_set()
    assert lanes[0].task.cancelled()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.send.immediate-admission
@pytest.mark.asyncio
async def test_dispatch_exception_is_captured_and_unrelated_frame_not_processed(lane_admission, monkeypatch, caplog):
    args, _, _, _, _, _ = lane_admission
    module = sys.modules["backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler"]
    module.handle_message_received = AsyncMock(side_effect=RuntimeError("private dispatch detail"))
    lanes = []
    await handler.handle_chat_turn_admit(**args, schedule_context_dispatch=lanes.append)
    unrelated = {"type": "chat_turn_admit", "payload": {"turn_id": "another"}}
    with pytest.raises(RuntimeError, match="private dispatch detail"):
        await lanes[0].receive_next(lambda: asyncio.sleep(0, result=unrelated))
    await lanes[0].close()
    await asyncio.sleep(0)  # Let the task completion callback record the failure.
    assert "Admitted chat continuation failed: RuntimeError" in caplog.text
    assert "private dispatch detail" not in caplog.text


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.send.immediate-admission
@pytest.mark.asyncio
async def test_mismatched_context_is_buffered_until_dispatch_finishes(lane_admission):
    args, _, _, started, release, _ = lane_admission
    lanes = []
    await handler.handle_chat_turn_admit(**args, schedule_context_dispatch=lanes.append)
    await started.wait()
    wrong = context_frame(args["payload"], "chat_turn_context_ready")
    wrong["payload"]["request_id"] = "55555555-5555-4555-8555-555555555555"
    pending = asyncio.create_task(lanes[0].receive_next(lambda: asyncio.sleep(0, result=wrong)))
    await asyncio.sleep(0)
    assert not pending.done()
    release.set()
    assert await pending == (wrong, False)
    await lanes[0].close()
