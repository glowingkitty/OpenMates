"""Completed call turns retain ordinary request schemas and strict paid authority."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from backend.shared.python_utils.voice_call_admission import (
    admit_voice_call_turn, require_active_voice_dispatch, queued_voice_delivery,
)
from backend.shared.python_utils.voice_call_registry import (
    finalize_active_call, issue_message_id, register_active_call, require_active_call,
)


class Cache:
    def __init__(self):
        self.redis = fakeredis.aioredis.FakeRedis()

    @property
    async def client(self):
        return self.redis


@pytest.fixture
async def admitted():
    cache = Cache()
    base = dict(user_id="owner", session_id="authenticated-session", chat_id=str(uuid.uuid4()), call_id=uuid.uuid4().hex)
    message_id = str(uuid.uuid4())
    await register_active_call(cache, **base)
    await issue_message_id(cache, **base, message_id=message_id, role="user")
    message = {"voice_mode": True, "voice_call_id": base["call_id"], "voice_turn_id": message_id}
    scope = {"voice_call_session_hash": base["session_id"]}
    return cache, base, message_id, message, scope


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.audio.complete-turn-admission
async def test_canonical_admission_accepts_only_issued_user_turn_of_exact_session_and_chat(admitted):
    cache, base, message_id, message, scope = admitted
    args = dict(message=message, websocket_scope=scope, user_id=base["user_id"], chat_id=base["chat_id"], message_id=message_id)
    result = await admit_voice_call_turn(cache, **args)
    assert result.voice_mode and result.voice_call_id == base["call_id"] and result.voice_turn_id == message_id
    for changed in [
        {"user_id": "other-owner"}, {"chat_id": "another-chat"},
        {"message_id": "partial-unissued"}, {"websocket_scope": {}},
        {"websocket_scope": {"voice_call_session_hash": "other-session"}},
        {"message": {**message, "voice_call_id": uuid.uuid4().hex}},
        {"message": {**message, "voice_turn_id": "different-turn"}},
        {"message": {**message, "voice_call_id": "malformed"}},
    ]:
        with pytest.raises(ValueError):
            await admit_voice_call_turn(cache, **{**args, **changed})
    await issue_message_id(cache, **base, message_id="assistant-id", role="assistant")
    with pytest.raises(ValueError):
        await admit_voice_call_turn(cache, **{**args, "message_id": "assistant-id", "message": {**message, "voice_turn_id": "assistant-id"}})


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.lifecycle.recovery-and-billing
async def test_hangup_blocks_new_paid_requests_but_keeps_ciphertext_retry_grace(admitted):
    cache, base, message_id, message, scope = admitted
    request = {**message, "message_id": message_id, "user_id": base["user_id"], "chat_id": base["chat_id"]}
    await require_active_voice_dispatch(cache, request)
    await finalize_active_call(cache, **base)
    with pytest.raises(ValueError, match="ended"):
        await require_active_voice_dispatch(cache, request)
    with pytest.raises(ValueError, match="ended"):
        await admit_voice_call_turn(cache, message=message, websocket_scope=scope,
                                   user_id=base["user_id"], chat_id=base["chat_id"], message_id=message_id)
    retry = await require_active_call(cache, **base, message_id=message_id, role="user")
    assert retry.state == "finalizing"


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.provider.boundary
async def test_paid_dispatch_rejects_foreign_deleted_unissued_and_nonpersonal_requests(admitted):
    cache, base, message_id, message, _scope = admitted
    request = {**message, "message_id": message_id, "user_id": base["user_id"], "chat_id": base["chat_id"]}
    for changed in [{"user_id": "other-owner"}, {"chat_id": "other-chat"}, {"voice_call_id": uuid.uuid4().hex},
                    {"message_id": "partial", "voice_turn_id": "partial"}, {"is_external": True},
                    {"is_incognito": True}, {"is_anonymous": True}, {"team_id": "team"}]:
        with pytest.raises(ValueError):
            await require_active_voice_dispatch(cache, {**request, **changed})
    await cache.redis.delete(f"voice:call:{base['call_id']}")
    with pytest.raises(ValueError, match="ended"):
        await require_active_voice_dispatch(cache, request)


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.chat.launch-and-provider
async def test_nonvoice_request_needs_no_call_authority_and_cannot_inherit_voice_ids():
    cache = SimpleNamespace()
    result = await admit_voice_call_turn(cache, message={"voice_call_id": "untrusted"},
        websocket_scope={}, user_id="owner", chat_id="chat", message_id="message")
    assert not result.voice_mode and result.voice_call_id is None and result.voice_turn_id is None
    await require_active_voice_dispatch(cache, {"voice_mode": False})


# contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.audio.spoken-rich-response
def test_both_ask_schemas_and_recovery_commitment_preserve_nested_voice_delivery():
    # This test's own request data proves schema pass-through without inference.
    from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as APIRequest
    from backend.apps.ai.skills.ask_skill import AskSkillRequest as WorkerRequest
    from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import canonicalize_inference_request
    call_id, message_id = uuid.uuid4().hex, str(uuid.uuid4())
    message = {"voice_mode": True, "voice_call_id": call_id, "voice_turn_id": message_id}
    raw = {"chat_id": "chat", "message_id": message_id, "user_id": "owner", "user_id_hash": hashlib.sha256(b"owner").hexdigest(),
           "message_history": [{"role": "user", "message_id": message_id, "content": "Find ramen", "created_at": 1}],
           "auto_speak_response": True, **message}
    api = APIRequest.model_validate(raw)
    worker = WorkerRequest.model_validate(api.model_dump())
    roundtrip = APIRequest.model_validate(worker.model_dump()).model_dump()
    assert all(roundtrip[key] == value for key, value in message.items())
    assert roundtrip["auto_speak_response"] is True
    # Voice delivery never inserts model/provider overrides.
    assert not any(key in raw for key in ("model", "model_id", "provider", "full_model_reference"))
    payload = {"chat_id": "chat", "message": {"message_id": message_id, "content": "Find ramen", **message}}
    committed = json.loads(canonicalize_inference_request(payload))
    assert all(committed["message"][key] == value for key, value in message.items())
    changed = {**payload, "message": {**payload["message"], "voice_turn_id": "changed"}}
    assert canonicalize_inference_request(payload) != canonicalize_inference_request(changed)


# contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.audio.spoken-rich-response
def test_legacy_queue_retains_voice_delivery_without_inheriting_prior_turn_preferences():
    fields = {"voice_mode": True, "voice_call_id": "call", "voice_turn_id": "turn", "auto_speak_response": False, "assistant_speech_lazy_dispatch": True,
              "voice_heard_boundary": {"assistant_message_id": "answer", "completed_sequences": [0], "active_sequence": 1, "active_offset_ms": 420}}
    delivery = queued_voice_delivery([fields])
    assert delivery == {**fields, "auto_speak_response": True, "assistant_speech_lazy_dispatch": False}
    plain = queued_voice_delivery([{"auto_speak_response": False}, fields])
    assert not plain["voice_mode"] and plain["voice_call_id"] is None and plain["voice_heard_boundary"] is None


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.audio.complete-turn-admission
async def test_routing_lane_checks_call_before_paid_routing_even_with_ordinary_durable_authority(admitted, monkeypatch):
    from backend.apps.ai.tasks import stage_one_task
    cache, base, message_id, message, _scope = admitted
    request = SimpleNamespace(**message, message_id=message_id, user_id=base["user_id"], chat_id=base["chat_id"])
    ordinary = AsyncMock(return_value=True)
    monkeypatch.setattr(stage_one_task, "routing_turn_is_current", ordinary)
    monkeypatch.setattr(stage_one_task, "routing_admission_is_current", ordinary)
    assert await stage_one_task._routing_authority_is_current(cache, object(), request, "task")
    await finalize_active_call(cache, **base)
    ordinary.reset_mock()
    assert not await stage_one_task._routing_authority_is_current(cache, object(), request, "task")
    ordinary.assert_not_awaited()
