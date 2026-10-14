"""One-frame admission preserves persistence, identity and dispatch boundaries."""
import copy
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import chat_turn_admit_handler as handler


@pytest.fixture
def admission(monkeypatch):
    dispatch = AsyncMock()
    module = ModuleType("backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler")
    module.handle_message_received = dispatch
    monkeypatch.setitem(sys.modules, module.__name__, module)
    preflight = AsyncMock(return_value={
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "state": "PREPARED",
    })
    monkeypatch.setattr(handler, "handle_chat_turn_preflight", preflight)
    payload = {
        "protocol_version": 1,
        "chat_id": "11111111-1111-4111-8111-111111111111",
        "turn_id": "22222222-2222-4222-8222-222222222222",
        "message_id": "1111111111-33333333-3333-4333-8333-333333333333",
        "encrypted_user_message": {"encrypted_content": "client-ciphertext"},
    }
    payload["inference_request"] = {
        "chat_id": payload["chat_id"], "turn_id": payload["turn_id"],
        "message": {"message_id": payload["message_id"], "content": "What’s the capital of Spain?"},
        "is_incognito": False,
    }
    args = dict(websocket=SimpleNamespace(send_json=AsyncMock()), manager=object(),
                cache_service=SimpleNamespace(get_active_ai_task=AsyncMock(return_value=None)),
                directus_service=object(), encryption_service=object(),
                user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device",
                payload=payload)
    return args, preflight, dispatch


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_committed_ack_dispatches_same_turn_without_second_client_frame(admission):
    args, preflight, dispatch = admission
    original = copy.deepcopy(args["payload"])
    await handler.handle_chat_turn_admit(**args)
    preflight.assert_awaited_once()
    dispatch.assert_awaited_once()
    request = dispatch.await_args.kwargs["payload"]
    assert request["preflight_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert request["protocol_version"] == 1
    assert request["turn_id"] == original["turn_id"]
    assert request["message"] == original["inference_request"]["message"]
    assert dispatch.await_args.kwargs["client_context_turn_id"] is None
    assert args["payload"] == original


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_rejected_persistence_never_dispatches(admission):
    args, preflight, dispatch = admission
    preflight.return_value = None
    await handler.handle_chat_turn_admit(**args)
    dispatch.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["chat", "turn", "message", "team", "incognito", "authority", "context_turn_id"])
async def test_scope_mismatch_rejected_before_persistence(admission, change):
    args, preflight, dispatch = admission
    request = args["payload"]["inference_request"]
    if change in {"chat", "turn"}:
        request[change + "_id"] = "different"
    elif change == "message":
        request["message"]["message_id"] = "different"
    elif change == "team":
        request["team_id"] = "another-team"
    elif change == "incognito":
        request["is_incognito"] = True
    elif change == "context_turn_id":
        request["client_context_turn_id"] = args["payload"]["turn_id"]
    else:
        request["admission_context"] = {"scope_complete": True}
    await handler.handle_chat_turn_admit(**args)
    preflight.assert_not_awaited()
    dispatch.assert_not_awaited()
    assert args["websocket"].send_json.await_args.args[0]["payload"]["code"] == "invalid_chat_turn_admission"


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", ["", "x" * 256, 123])
async def test_invalid_message_identity_rejected_before_persistence(admission, message_id):
    args, preflight, dispatch = admission
    args["payload"]["message_id"] = message_id
    args["payload"]["inference_request"]["message"]["message_id"] = message_id
    await handler.handle_chat_turn_admit(**args)
    preflight.assert_not_awaited()
    dispatch.assert_not_awaited()
    assert args["websocket"].send_json.await_args.args[0]["payload"]["code"] == "invalid_chat_turn_admission"


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["PREPARED", "LEGACY"])
async def test_cold_context_binding_registered_after_commit_before_dispatch(admission, monkeypatch, state):
    args, preflight, dispatch = admission
    from backend.core.api.app.services import client_context_continuation
    register = AsyncMock(return_value="server-binding")
    monkeypatch.setattr(client_context_continuation, "register_client_context", register)
    request = args["payload"]["inference_request"]
    request.update(client_context_pending=True, client_context_request_id="44444444-4444-4444-8444-444444444444")
    async def commit(**kwargs):
        register.assert_not_awaited()
        dispatch.assert_not_awaited()
        return {"preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "state": state}
    preflight.side_effect = commit
    await handler.handle_chat_turn_admit(**args)
    assert dispatch.await_args.kwargs["client_context_binding_ref"] == "server-binding"
    assert dispatch.await_args.kwargs["client_context_turn_id"] == args["payload"]["turn_id"]
    assert "client_context_binding_ref" not in dispatch.await_args.kwargs["payload"]
    assert "client_context_turn_id" not in dispatch.await_args.kwargs["payload"]
    assert register.await_args.kwargs["message_id"] == args["payload"]["message_id"]
    if state == "LEGACY":
        assert "protocol_version" not in dispatch.await_args.kwargs["payload"]
        assert "preflight_id" not in dispatch.await_args.kwargs["payload"]


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_epoch_zero_uses_existing_legacy_dispatch(admission):
    args, preflight, dispatch = admission
    preflight.return_value["state"] = "LEGACY"
    await handler.handle_chat_turn_admit(**args)
    assert "protocol_version" not in dispatch.await_args.kwargs["payload"]
    assert "preflight_id" not in dispatch.await_args.kwargs["payload"]


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_only_committed_first_personal_turn_gets_server_internal_projection_hint(admission):
    args, preflight, dispatch = admission
    payload = args["payload"]
    payload.update(expected_messages_v=0, encrypted_chat_metadata={"encrypted_title": "ciphertext"})
    payload["encrypted_chat_key"] = "wrapped-key-1"
    payload["inference_request"]["encrypted_chat_key"] = "wrapped-key-1"
    payload["inference_request"]["message"]["role"] = "user"
    preflight.return_value = {
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "state": "PREPARED", "committed_messages_v": 1,
    }
    await handler.handle_chat_turn_admit(**args)
    assert dispatch.await_args.kwargs["first_personal_admission"] == {
        "chat_id": payload["chat_id"], "turn_id": payload["turn_id"],
        "message_id": payload["message_id"],
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "wrapped_chat_key": "wrapped-key-1",
    }
    assert "first_personal_admission" not in dispatch.await_args.kwargs["payload"]

    dispatch.reset_mock()
    payload["expected_messages_v"] = 1
    await handler.handle_chat_turn_admit(**args)
    assert dispatch.await_args.kwargs["first_personal_admission"] is None

    dispatch.reset_mock()
    payload["expected_messages_v"] = 0
    payload["inference_request"]["first_personal_admission"] = {"preflight_id": "forged"}
    await handler.handle_chat_turn_admit(**args)
    dispatch.assert_not_awaited()
    assert args["websocket"].send_json.await_args.args[0]["payload"]["code"] == "invalid_chat_turn_admission"


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_epoch_zero_first_personal_admission_keeps_legacy_dispatch(admission):
    args, preflight, dispatch = admission
    args["payload"].update(expected_messages_v=0,
                           encrypted_chat_metadata={"encrypted_title": "ciphertext"})
    args["payload"]["encrypted_chat_key"] = "wrapped-key-1"
    args["payload"]["inference_request"]["encrypted_chat_key"] = "wrapped-key-1"
    args["payload"]["inference_request"]["message"]["role"] = "user"
    preflight.return_value = {
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "state": "LEGACY", "committed_messages_v": 1,
    }
    await handler.handle_chat_turn_admit(**args)
    request = dispatch.await_args.kwargs["payload"]
    assert "protocol_version" not in request
    assert "preflight_id" not in request
    assert dispatch.await_args.kwargs["first_personal_admission"] is None


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_first_personal_wrapper_mismatch_rejected_before_enqueue(admission):
    args, preflight, dispatch = admission
    preflight.return_value["committed_messages_v"] = 1
    payload = args["payload"]
    payload.update(expected_messages_v=0, encrypted_chat_metadata={"encrypted_title": "ciphertext"},
                   encrypted_chat_key="wrapped-key-1")
    payload["inference_request"]["encrypted_chat_key"] = "wrong-wrapper"
    await handler.handle_chat_turn_admit(**args)
    preflight.assert_awaited_once()
    dispatch.assert_not_awaited()
    assert args["websocket"].send_json.await_args.args[0]["payload"]["code"] == "invalid_chat_turn_admission"


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_client_cannot_forge_expected_wrapped_chat_key(admission):
    args, preflight, dispatch = admission
    args["payload"]["inference_request"]["expected_wrapped_chat_key"] = "forged"
    await handler.handle_chat_turn_admit(**args)
    preflight.assert_not_awaited()
    dispatch.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_atomic_enqueued_ack_passes_server_only_projection_to_handler(admission):
    args, preflight, dispatch = admission
    payload = args["payload"]
    payload.update(expected_messages_v=0, encrypted_chat_metadata={"encrypted_title": "ciphertext"},
                   encrypted_chat_key="wrapped-key-1")
    payload["inference_request"].update(encrypted_chat_key="wrapped-key-1")
    payload["inference_request"]["message"]["role"] = "user"
    preflight.return_value = {
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "state": "ENQUEUED", "committed_messages_v": 1,
        "admission_chat_projection": {"id": payload["chat_id"]},
        "admission_protocol_epoch": 1, "admission_sends_paused": False,
    }
    await handler.handle_chat_turn_admit(**args)
    hint = dispatch.await_args.kwargs["first_personal_admission"]
    assert hint["enqueue_result"] is preflight.return_value
    assert hint["wrapped_chat_key"] == "wrapped-key-1"
    assert "enqueue_result" not in dispatch.await_args.kwargs["payload"]


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_atomic_context_binding_is_completed_before_ack_and_not_repeated(admission, monkeypatch):
    args, preflight, dispatch = admission
    from backend.core.api.app.services import client_context_continuation
    register = AsyncMock(return_value="server-binding")
    monkeypatch.setattr(client_context_continuation, "register_client_context", register)
    payload = args["payload"]
    payload.update(expected_messages_v=0, encrypted_chat_metadata={"encrypted_title": "ciphertext"},
                   encrypted_chat_key="wrapped-key-1")
    payload["inference_request"].update(
        encrypted_chat_key="wrapped-key-1", client_context_pending=True,
        client_context_request_id="44444444-4444-4444-8444-444444444444",
    )
    payload["inference_request"]["message"]["role"] = "user"
    async def atomic_preflight(**kwargs):
        binding = await kwargs["atomic_before_ack"]({"state": "ENQUEUED"})
        assert binding == "server-binding"
        dispatch.assert_not_awaited()
        return {"preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "state": "ENQUEUED", "committed_messages_v": 1,
                "client_context_binding_ref": binding}
    preflight.side_effect = atomic_preflight
    await handler.handle_chat_turn_admit(**args)
    register.assert_awaited_once()
    assert dispatch.await_args.kwargs["client_context_binding_ref"] == "server-binding"
    assert dispatch.await_args.kwargs["client_context_turn_id"] == payload["turn_id"]
    assert "client_context_binding_ref" not in dispatch.await_args.kwargs["payload"]
    # An exact one-frame retry rebinds the same scoped reference; the durable
    # transaction's replay keeps its canonical preflight/outbox identities.
    dispatch.reset_mock()
    await handler.handle_chat_turn_admit(**args)
    assert register.await_count == 2
    assert preflight.await_count == 2
    assert dispatch.await_args.kwargs["client_context_binding_ref"] == "server-binding"


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_queue_proof_hint_comes_only_from_server_active_task(admission):
    args, preflight, dispatch = admission
    args["payload"]["expected_messages_v"] = 1
    active = "11111111-2222-4333-8444-555555555555"
    args["cache_service"].get_active_ai_task.return_value = active
    await handler.handle_chat_turn_admit(**args)
    assert preflight.await_args.kwargs["server_queued_after_task_id"] == active
    args["cache_service"].get_active_ai_task.assert_awaited_once_with(args["payload"]["chat_id"])


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.asyncio
async def test_legacy_active_task_hint_never_rejects_preflight(admission):
    args, preflight, dispatch = admission
    args["payload"]["expected_messages_v"] = 1
    args["cache_service"].get_active_ai_task.return_value = "a" * 64
    await handler.handle_chat_turn_admit(**args)
    assert preflight.await_args.kwargs["server_queued_after_task_id"] is None
    dispatch.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy,chats.message.identity-idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
async def test_privacy_receipt_replay_authority_is_marked_only_after_durable_acceptance(admission, accepted):
    from unittest.mock import Mock
    args, preflight, dispatch = admission
    marked = Mock()
    if not accepted:
        preflight.return_value = None
    await handler.handle_chat_turn_admit(**args, on_durable_admission=marked)
    if accepted:
        marked.assert_called_once_with()
        dispatch.assert_awaited_once()
    else:
        marked.assert_not_called()
        dispatch.assert_not_awaited()
