"""Issued voice transcript identities remain owner/session scoped through retry grace."""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest

from backend.shared.python_utils.voice_call_registry import (
    finalize_active_call, issue_message_id, register_active_call,
    require_active_call, renew_active_call,
)


class Cache:
    def __init__(self) -> None:
        self.redis = fakeredis.aioredis.FakeRedis()

    @property
    async def client(self):
        return self.redis


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.chat.transcripts
@pytest.mark.asyncio
async def test_registry_rejects_forged_identity_and_keeps_issued_retry() -> None:
    cache = Cache()
    call_id = uuid.uuid4().hex
    base = dict(user_id="owner", session_id="session-hash", chat_id="personal-chat", call_id=call_id)
    await register_active_call(cache, **base)
    await issue_message_id(cache, **base, message_id="transcript-1", role="assistant")
    binding = await require_active_call(cache, **base, message_id="transcript-1", role="assistant")
    assert binding.state == "active"
    for changed in (
        {"user_id": "intruder"}, {"session_id": "other-session"},
        {"chat_id": "other-chat"}, {"message_id": "forged"}, {"role": "user"},
    ):
        with pytest.raises(ValueError, match="not authorized"):
            await require_active_call(cache, **{**base, "message_id": "transcript-1", "role": "assistant", **changed})
    await finalize_active_call(cache, **base, grace_seconds=30)
    retry = await require_active_call(cache, **base, message_id="transcript-1", role="assistant")
    assert retry.state == "finalizing" and retry.grace_expires_at is not None
    with pytest.raises(ValueError, match="not authorized"):
        await issue_message_id(cache, **base, message_id="late-forgery", role="assistant")


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_registry_lease_loss_fails_closed() -> None:
    cache = Cache()
    base = dict(user_id="owner", session_id="session-hash", chat_id="chat", call_id=uuid.uuid4().hex)
    await register_active_call(cache, **base)
    await cache.redis.delete(f"voice:call:{base['call_id']}")
    with pytest.raises(RuntimeError, match="authority lost"):
        await renew_active_call(cache, **base)
    with pytest.raises(ValueError, match="not authorized"):
        await require_active_call(cache, **base, message_id="anything", role="user")


# contract-test: supporting surface=gui.web assertions=video-call.audio.single-owner,video-call.privacy
@pytest.mark.asyncio
async def test_status_session_lookup_requires_active_owner_chat_binding():
    from backend.shared.python_utils.voice_call_registry import active_call_session
    cache = Cache()
    base = dict(user_id="owner", session_id="call-session", chat_id="call-chat", call_id=uuid.uuid4().hex)
    await register_active_call(cache, **base)
    lookup = {key: base[key] for key in ("user_id", "chat_id", "call_id")}
    assert await active_call_session(cache, **lookup) == "call-session"
    for changed in ({"user_id": "other"}, {"chat_id": "different"}, {"call_id": "malformed"}, {"call_id": uuid.uuid4().hex}):
        assert await active_call_session(cache, **{**lookup, **changed}) is None
    await finalize_active_call(cache, **base)
    assert await active_call_session(cache, **lookup) is None
