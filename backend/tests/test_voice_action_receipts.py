"""Committed voice artifact recovery retains exact owner/session row authority."""
import base64
import hashlib
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from backend.shared.python_utils import voice_action_receipts as receipts
from backend.shared.python_utils.voice_call_registry import register_active_call, issue_message_id
from backend.core.api.app.routes.handlers.websocket_handlers import voice_action_completed_handler as recovery


class Cache:
    def __init__(self):
        self.redis = fakeredis.aioredis.FakeRedis()
        self.publish_event = AsyncMock()

    @property
    async def client(self):
        return self.redis

    async def get_user_vault_key_id(self, user_id):
        return "owner-key"


class Encryption:
    """Opaque test cipher; no plaintext is present in Redis values."""
    def __init__(self):
        self.texts = {}

    async def encrypt_with_user_key(self, text, key):
        token = "vault:v1:" + uuid.uuid4().hex
        self.texts[token] = text
        return token, 1

    async def decrypt_with_user_key(self, token, key):
        return self.texts.get(token)


async def setup():
    cache, encryption = Cache(), Encryption()
    binding = dict(user_id="owner", user_hash="owner-hash", session_id="original-session",
        chat_id="personal-chat", call_id=uuid.uuid4().hex, user_message_id="issued-user-123",
        assistant_message_id="issued-assistant-123", operation_id="committed-operation",
        assistant_created_at=int(time.time()))
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(
        return_value={"hashed_user_id": binding["user_hash"]})))
    call = {k: binding[k] for k in ("user_id", "session_id", "chat_id", "call_id")}
    await register_active_call(cache, **call)
    await issue_message_id(cache, **call, message_id=binding["assistant_message_id"], role="assistant")
    await issue_message_id(cache, **call, message_id=binding["user_message_id"], role="user")
    return cache, encryption, binding, directus


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_completed_write_survives_lost_call_without_reexecution():
    cache, encryption, binding, directus = await setup()
    args = dict(cache_service=cache, directus_service=directus, encryption_service=encryption,
                binding=binding, request_id="completion-request")
    await receipts.admit_voice_action_receipt(**args)
    await cache.redis.delete(f"voice:call:{binding['call_id']}", f"voice:call:{binding['call_id']}:messages")
    result = await receipts.persist_voice_action_receipt(**args, embed_refs=["artifact-ref"])
    assert result["assistant_message_id"] == binding["assistant_message_id"]
    assert result["created_at"] == binding["assistant_created_at"]
    assert result["embed_refs"] == ["artifact-ref"]
    retry = await receipts.persist_voice_action_receipt(**args, embed_refs=["different-artifact"])
    assert retry == result  # Receipt recovery never executes a skill.
    assert cache.publish_event.await_count == 1
    event = cache.publish_event.await_args.args[1]
    assert event["payload"] == {"request_id": "completion-request", "initiator_session_id": "original-session"}
    for key in await cache.redis.keys("voice:action:*"):
        if await cache.redis.type(key) == b"string":
            assert b"artifact-ref" not in await cache.redis.get(key)
    message = dict(call_id=binding["call_id"], chat_id=binding["chat_id"],
                   message_id=binding["assistant_message_id"], role="assistant",
                   user_message_id=binding["user_message_id"], created_at=binding["assistant_created_at"])
    auth = dict(cache_service=cache, directus_service=directus, encryption_service=encryption,
                user_id="owner", user_hash="owner-hash", session_id="original-session")
    await receipts.require_committed_voice_action(**auth, message=message)
    for change in ({"message_id": "forged-assistant"}, {"role": "user"}, {"user_message_id": "forged-user"}):
        with pytest.raises(ValueError):
            await receipts.require_committed_voice_action(**auth, message={**message, **change})
    with pytest.raises(ValueError):
        await receipts.require_committed_voice_action(**{**auth, "session_id": "other-session"}, message=message)
    directus.chat.get_chat_metadata.return_value["hashed_team_id"] = "team"
    with pytest.raises(ValueError):
        await receipts.require_committed_voice_action(**auth, message=message)


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_unadmitted_and_mismatched_action_cannot_mint_receipt():
    cache, encryption, binding, directus = await setup()
    args = dict(cache_service=cache, directus_service=directus, encryption_service=encryption,
                binding=binding, request_id="completion-request")
    with pytest.raises(ValueError, match="not admitted"):
        await receipts.persist_voice_action_receipt(**args, embed_refs=["artifact-ref"])
    await receipts.admit_voice_action_receipt(**args)
    with pytest.raises(ValueError, match="mismatch"):
        await receipts.persist_voice_action_receipt(**{**args, "binding": {**binding, "assistant_message_id": "forged-assistant"}},
                                                   embed_refs=["artifact-ref"])


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_replay_scoped_to_original_session_and_ack_needs_durable_ciphertext():
    cache, encryption, binding, directus = await setup()
    args = dict(cache_service=cache, directus_service=directus, encryption_service=encryption,
                binding=binding, request_id="completion-request")
    await receipts.admit_voice_action_receipt(**args)
    completed = await receipts.persist_voice_action_receipt(**args, embed_refs=["artifact-ref"])
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    auth = dict(manager=manager, cache_service=cache, directus_service=directus, encryption_service=encryption,
                user_id="owner", user_id_hash="owner-hash", session_hash="original-session",
                device_fingerprint_hash="device")
    await recovery.send_pending_voice_actions(**{**auth, "session_hash": "another-session"})
    manager.send_personal_message.assert_not_awaited()
    await recovery.send_pending_voice_actions(**auth)
    assert manager.send_personal_message.await_args.args[0]["payload"] == completed
    ack = {k: completed[k] for k in ("request_id", "call_id", "chat_id", "assistant_message_id")}
    ack.update(revision=1, ciphertext_hash=hashlib.sha256(base64.b64encode(b"x" * 40)).hexdigest())
    directus.get_items = AsyncMock(return_value=[])
    await recovery.handle_voice_action_completed(**auth, payload=ack, confirmed=True)
    pending = receipts._key("pending", "owner", "original-session")
    assert await cache.redis.scard(pending) == 1
    row = dict(client_message_id=binding["assistant_message_id"], chat_id=binding["chat_id"],
        hashed_user_id="owner-hash", role="assistant", user_message_id=binding["user_message_id"],
        created_at=binding["assistant_created_at"], encrypted_content=base64.b64encode(b"x" * 40).decode(),
        queue_revision=1, queue_pending_revision=None)
    directus.get_items.return_value = [row]
    await recovery.handle_voice_action_completed(**auth, payload={**ack, "assistant_message_id": "forged-assistant"}, confirmed=True)
    assert await cache.redis.scard(pending) == 1
    # An older spoken-row ACK must not acknowledge the newer artifact revision.
    manager.send_personal_message.reset_mock()
    row["queue_revision"] = 2
    row["encrypted_content"] = base64.b64encode(b"y" * 40).decode()
    await recovery.handle_voice_action_completed(**auth, payload=ack, confirmed=True)
    assert await cache.redis.scard(pending) == 1
    manager.send_personal_message.assert_awaited_once()
    assert manager.send_personal_message.await_args.args[0] == {"type": "voice_action_completed", "payload": completed}
    manager.send_personal_message.reset_mock()
    ciphertext = row["encrypted_content"]
    row["encrypted_content"] = "invalid ciphertext"
    await recovery.handle_voice_action_completed(**auth, payload=ack, confirmed=True)
    manager.send_personal_message.assert_not_awaited()
    row["encrypted_content"] = ciphertext
    ack.update(revision=2, ciphertext_hash=hashlib.sha256(row["encrypted_content"].encode()).hexdigest())
    await recovery.handle_voice_action_completed(**auth, payload=ack, confirmed=True)
    assert await cache.redis.scard(pending) == 0
    assert await cache.redis.zcard(receipts._key("slots", "owner", "original-session")) == 0


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_expired_call_ciphertext_writer_uses_sealed_exact_assistant_authority():
    from backend.tests.test_call_message_completed_handler import (
        FakeDirectus, OWNER, OWNER_HASH, CHAT, MESSAGE, payload,
    )
    from backend.core.api.app.routes.handlers.websocket_handlers import call_message_completed_handler as writer
    cache, encryption = Cache(), Encryption()
    cache.delete_chat_versions = AsyncMock()
    cache.delete = AsyncMock()
    cache.delete_sync_messages_history = AsyncMock()
    directus = FakeDirectus()
    binding = dict(user_id=OWNER, user_hash=OWNER_HASH, session_id="original-session",
        chat_id=CHAT, call_id=uuid.uuid4().hex, user_message_id="issued-user-123",
        assistant_message_id=MESSAGE, operation_id="committed-operation",
        assistant_created_at=1_700_000_000)
    call = {k: binding[k] for k in ("user_id", "session_id", "chat_id", "call_id")}
    await register_active_call(cache, **call)
    await issue_message_id(cache, **call, message_id=MESSAGE, role="assistant")
    await issue_message_id(cache, **call, message_id=binding["user_message_id"], role="user")
    args = dict(cache_service=cache, directus_service=directus, encryption_service=encryption,
                binding=binding, request_id="completion-request")
    await receipts.admit_voice_action_receipt(**args)
    await cache.redis.delete(f"voice:call:{binding['call_id']}", f"voice:call:{binding['call_id']}:messages")
    await receipts.persist_voice_action_receipt(**args, embed_refs=["artifact-ref"])
    message = writer._validated_message(payload(call_id=binding["call_id"], user_message_id=binding["user_message_id"]))
    auth = dict(directus_service=directus, cache_service=cache, user_id=OWNER,
                user_id_hash=OWNER_HASH, session_hash="original-session", encryption_service=encryption)
    assert await writer.persist_encrypted_call_message(**auth, message=message) == ("created", 1)
    assert await writer.persist_encrypted_call_message(**auth, message=message) == ("replayed", 1)
    assert len(directus.writes) == 2  # One row creation and its counted marker.
    with pytest.raises(writer.CallMessageError, match="not_authorized"):
        await writer.persist_encrypted_call_message(**{**auth, "session_hash": "another-session"}, message=message)


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_capacity_reserved_before_dispatch_and_cleanup_is_idempotent(monkeypatch):
    cache, encryption, binding, directus = await setup()
    monkeypatch.setattr(receipts, "MAX_PENDING_RECEIPTS", 2)
    args = dict(cache_service=cache, directus_service=directus, encryption_service=encryption, binding=binding)
    await receipts.admit_voice_action_receipt(**args, request_id="first-action-request")
    await receipts.admit_voice_action_receipt(**args, request_id="first-action-request")
    second_binding = {**binding, "operation_id": "second-operation"}
    await receipts.admit_voice_action_receipt(**{**args, "binding": second_binding}, request_id="second-action-request")
    slots = receipts._key("slots", binding["user_id"], binding["session_id"])
    assert await cache.redis.zcard(slots) == 2
    with pytest.raises(RuntimeError, match="admission capacity"):
        await receipts.admit_voice_action_receipt(**args, request_id="third-action-request")
    assert not await cache.redis.exists(receipts._key("permit", binding["user_id"], binding["session_id"], "third-action-request"))
    release = dict(cache_service=cache, binding=binding, request_id="first-action-request")
    await receipts.release_voice_action_admission(**release)
    await receipts.release_voice_action_admission(**release)
    assert await cache.redis.zcard(slots) == 1
    third_binding = {**binding, "operation_id": "third-operation"}
    await receipts.admit_voice_action_receipt(**{**args, "binding": third_binding}, request_id="third-action-request")
    # Completion converts its reserved slot even while capacity is full.
    await receipts.persist_voice_action_receipt(**{**args, "binding": second_binding},
        request_id="second-action-request", embed_refs=["committed-artifact"])
    assert await cache.redis.zcard(slots) == 2
    await receipts.release_voice_action_admission(cache_service=cache, binding=second_binding,
                                                request_id="second-action-request")
    assert await cache.redis.zcard(slots) == 2  # Cannot discard a committed result.
