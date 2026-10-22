"""Encrypted voice transcript writes never enter the ordinary inference path."""

import base64
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import call_message_completed_handler as handler
from backend.shared.python_utils import chat_ciphertext_fingerprint as fingerprint_tools


OWNER = "owner-uuid"
OWNER_HASH = "owner-hash"
SESSION = "a" * 64
CHAT = "chat-uuid-1234"
CALL = "call-uuid-1234"
MESSAGE = "message-uuid-1234"
CIPHER_A = base64.b64encode(b"a" * 40).decode()
CIPHER_B = base64.b64encode(b"b" * 40).decode()
CIPHER_OLD = base64.b64encode(b"c" * 40).decode()


def payload(ciphertext=CIPHER_A, revision=1, **changes):
    return {
        "request_id": "request-uuid-1234", "call_id": CALL, "chat_id": CHAT,
        "message_id": MESSAGE, "role": "assistant", "encrypted_content": ciphertext,
        "created_at": 1_700_000_000, "revision": revision,
        **changes,
    }


class FakeCache:
    def __init__(self):
        self.deleted = []

    async def delete(self, key): self.deleted.append(key)
    async def delete_chat_versions(self, user_id, chat_id): self.deleted.append(("versions", user_id, chat_id))
    async def delete_sync_messages_history(self, user_id, chat_id): self.deleted.append(("sync", user_id, chat_id))


class FakeDirectus:
    def __init__(self):
        self.metadata = {"hashed_user_id": OWNER_HASH, "messages_v": 0, "last_edited_overall_timestamp": 0}
        self.message = None
        self.chat = self
        self.writes = []
        self.fingerprint_rows = []
        self.fail_advance_once = False
        self.lose_update_to_pending_once = False

    async def get_chat_metadata(self, chat_id):
        assert chat_id == CHAT
        return dict(self.metadata)

    async def get_items(self, collection, params, **_kwargs):
        assert collection == "messages"
        if "filter[chat_id][_eq]" in params:
            offset = int(params.get("offset", 0))
            return self.fingerprint_rows[offset:offset + int(params.get("limit", 100))]
        return [dict(self.message)] if self.message else []

    async def create_message_in_directus(self, data):
        self.writes.append(dict(data))
        if self.message:
            return {"id": self.message["id"], "client_message_id": MESSAGE}
        self.message = {"id": "directus-uuid", "client_message_id": MESSAGE,
                        **{k: v for k, v in data.items() if k != "message_id"}}
        return dict(self.message)

    async def update_item_if_version(self, collection, item_id, data, expected_version, **_kwargs):
        if collection == "chats":
            assert item_id == CHAT
            if self.fail_advance_once:
                self.fail_advance_once = False
                raise RuntimeError("transient chat revision failure")
            if self.metadata["messages_v"] != expected_version:
                return None
            self.metadata.update(data)
            return dict(self.metadata)
        assert collection == "messages" and item_id == "directus-uuid"
        if self.lose_update_to_pending_once and "queue_pending_revision" in data and data["queue_pending_revision"] is not None:
            self.lose_update_to_pending_once = False
            self.message.update(data)  # A concurrent writer won the ciphertext CAS.
            return None
        if self.message["queue_revision"] != expected_version:
            return None
        self.message.update(data)
        self.writes.append(dict(data))
        return dict(self.message)


class FakeManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []
    async def send_personal_message(self, message, *_args): self.sent.append(message)
    async def broadcast_to_user(self, message, *_args, **_kwargs): self.broadcasts.append(message)


@pytest.fixture
def rig(monkeypatch):
    async def authorized(cache, **identity):
        assert identity == {"user_id": OWNER, "session_id": SESSION, "chat_id": CHAT,
                            "call_id": CALL, "message_id": MESSAGE, "role": "assistant"}
        return SimpleNamespace(state="active", grace_expires_at=None)

    monkeypatch.setattr(handler, "require_active_call", authorized)
    monkeypatch.setattr(handler, "authoritative_chat_fingerprint", lambda *_: None)
    monkeypatch.setattr(handler, "validate_message_matches_authoritative_fingerprint",
                        lambda *_: SimpleNamespace(valid=True))
    return FakeDirectus(), FakeCache(), FakeManager()


# contract-test: supporting surface=rest_api assertions=video-call.privacy
def test_rejects_plaintext_and_unknown_fields_without_mutation():
    with pytest.raises(handler.CallMessageError):
        handler._validated_message(payload(content="spoken secret"))
    with pytest.raises(handler.CallMessageError):
        handler._validated_message(payload(encrypted_content="spoken secret"))


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.privacy,video-call.chat.transcripts
async def test_trace_injected_transport_envelope_stores_only_ciphertext(rig):
    directus, cache, manager = rig
    traceparent = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    await handler.handle_call_message_completed(
        manager=manager, cache_service=cache, directus_service=directus,
        user_id=OWNER, user_id_hash=OWNER_HASH, session_hash=SESSION,
        device_fingerprint_hash="device", payload=payload(_traceparent=traceparent),
    )
    assert manager.sent[-1]["type"] == "call_message_confirmed"
    assert directus.message["encrypted_content"] == CIPHER_A
    assert all("_traceparent" not in write for write in directus.writes)
    with pytest.raises(handler.CallMessageError, match="invalid_call_message"):
        handler._validated_message(payload(_traceparent="invalid"))


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts,video-call.privacy
async def test_create_correction_and_stale_replay_keep_one_encrypted_message(rig):
    directus, cache, manager = rig
    async def receive(body):
        await handler.handle_call_message_completed(
            manager=manager, cache_service=cache, directus_service=directus,
            user_id=OWNER, user_id_hash=OWNER_HASH, session_hash=SESSION,
            device_fingerprint_hash="device", payload=body,
        )

    # Ordinary text turns already advanced the chat independently of this row.
    directus.metadata["messages_v"] = 41
    await receive(payload())
    assert directus.metadata["messages_v"] == 42
    assert directus.message["encrypted_content"] == CIPHER_A
    assert manager.sent[-1]["payload"]["outcome"] == "created"
    assert manager.sent[-1]["payload"]["messages_v"] == 42
    assert manager.broadcasts[-1]["payload"]["messages_v"] == 42
    assert manager.sent[-1]["payload"]["revision"] == 1
    await receive(payload(CIPHER_B, 2))
    assert directus.metadata["messages_v"] == 43  # Sync revision advances; row count stays one.
    assert directus.message["encrypted_content"] == CIPHER_B
    assert manager.sent[-1]["payload"]["outcome"] == "updated"
    assert manager.sent[-1]["payload"]["messages_v"] == 43
    assert manager.broadcasts[-1]["payload"]["messages_v"] == 43
    assert manager.sent[-1]["payload"]["revision"] == 2
    # A replay after subsequent ordinary text reads the current canonical version
    # without creating a new version or rebroadcasting the old ciphertext.
    directus.metadata["messages_v"] = 50
    await receive(payload(CIPHER_B, 2))
    assert manager.sent[-1]["payload"]["outcome"] == "replayed"
    assert manager.sent[-1]["payload"]["messages_v"] == 50
    assert directus.metadata["messages_v"] == 50
    await receive(payload(CIPHER_OLD, 1))
    assert directus.message["encrypted_content"] == CIPHER_B
    assert manager.sent[-1]["payload"]["outcome"] == "stale"
    assert manager.sent[-1]["payload"]["messages_v"] == 50
    assert directus.metadata["messages_v"] == 50
    assert len(manager.broadcasts) == 2
    assert all("content" not in write for write in directus.writes)
    assert ("sync", OWNER, CHAT) in cache.deleted


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.privacy
async def test_wrong_owner_or_unissued_call_does_not_write(rig, monkeypatch):
    directus, cache, _manager = rig
    directus.metadata["hashed_user_id"] = "another-owner"
    with pytest.raises(handler.CallMessageError, match="call_chat_not_owned"):
        await handler.persist_encrypted_call_message(
            directus_service=directus, cache_service=cache, user_id=OWNER,
            user_id_hash=OWNER_HASH, session_hash=SESSION,
            message=handler._validated_message(payload()),
        )
    assert directus.writes == []
    directus.metadata["hashed_user_id"] = OWNER_HASH

    async def denied(*_args, **_kwargs): raise ValueError("Call message not authorized")
    monkeypatch.setattr(handler, "require_active_call", denied)
    with pytest.raises(handler.CallMessageError, match="call_message_not_authorized"):
        await handler.persist_encrypted_call_message(
            directus_service=directus, cache_service=cache, user_id=OWNER,
            user_id_hash=OWNER_HASH, session_hash=SESSION,
            message=handler._validated_message(payload()),
        )
    assert directus.writes == []


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts
async def test_retry_repairs_row_after_chat_revision_failure(rig):
    directus, cache, _manager = rig
    directus.fail_advance_once = True
    message = handler._validated_message(payload())
    with pytest.raises(RuntimeError, match="transient"):
        await handler.persist_encrypted_call_message(
            directus_service=directus, cache_service=cache, user_id=OWNER,
            user_id_hash=OWNER_HASH, session_hash=SESSION, message=message)
    assert directus.message["queue_revision"] == 0
    assert directus.metadata["messages_v"] == 0
    outcome, revision = await handler.persist_encrypted_call_message(
        directus_service=directus, cache_service=cache, user_id=OWNER,
        user_id_hash=OWNER_HASH, session_hash=SESSION, message=message)
    assert (outcome, revision) == ("replayed", 1)
    assert directus.message["queue_revision"] == 1
    assert directus.metadata["messages_v"] == 1
    assert ("sync", OWNER, CHAT) in cache.deleted


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts,video-call.privacy
async def test_same_revision_different_ciphertext_is_rejected(rig):
    directus, cache, _manager = rig
    original = handler._validated_message(payload())
    await handler.persist_encrypted_call_message(
        directus_service=directus, cache_service=cache, user_id=OWNER,
        user_id_hash=OWNER_HASH, session_hash=SESSION, message=original)
    with pytest.raises(handler.CallMessageError) as conflict:
        await handler.persist_encrypted_call_message(
            directus_service=directus, cache_service=cache, user_id=OWNER,
            user_id_hash=OWNER_HASH, session_hash=SESSION,
            message=handler._validated_message(payload(CIPHER_B)))
    assert conflict.value.code == "call_message_revision_conflict"
    assert conflict.value.current_revision == 1
    assert directus.message["encrypted_content"] == CIPHER_A


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts
async def test_retry_repairs_correction_visibility_after_chat_revision_failure(rig):
    directus, cache, _manager = rig
    base = handler._validated_message(payload())
    await handler.persist_encrypted_call_message(
        directus_service=directus, cache_service=cache, user_id=OWNER,
        user_id_hash=OWNER_HASH, session_hash=SESSION, message=base)
    directus.fail_advance_once = True
    corrected = handler._validated_message(payload(CIPHER_B, 2))
    with pytest.raises(RuntimeError, match="transient"):
        await handler.persist_encrypted_call_message(
            directus_service=directus, cache_service=cache, user_id=OWNER,
            user_id_hash=OWNER_HASH, session_hash=SESSION, message=corrected)
    assert directus.message["queue_pending_revision"] == 2
    assert directus.metadata["messages_v"] == 1
    outcome, revision = await handler.persist_encrypted_call_message(
        directus_service=directus, cache_service=cache, user_id=OWNER,
        user_id_hash=OWNER_HASH, session_hash=SESSION, message=corrected)
    assert (outcome, revision) == ("replayed", 2)
    assert directus.message["queue_pending_revision"] is None
    assert directus.metadata["messages_v"] == 2


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts
async def test_identical_cas_loser_never_acks_unpublished_correction(rig):
    directus, cache, _manager = rig
    base = handler._validated_message(payload())
    await handler.persist_encrypted_call_message(
        directus_service=directus, cache_service=cache, user_id=OWNER,
        user_id_hash=OWNER_HASH, session_hash=SESSION, message=base)
    directus.lose_update_to_pending_once = True
    directus.fail_advance_once = True
    corrected = handler._validated_message(payload(CIPHER_B, 2))
    with pytest.raises(RuntimeError, match="transient"):
        await handler.persist_encrypted_call_message(
            directus_service=directus, cache_service=cache, user_id=OWNER,
            user_id_hash=OWNER_HASH, session_hash=SESSION, message=corrected)
    assert directus.message["queue_pending_revision"] == 2
    assert directus.metadata["messages_v"] == 1
    outcome, revision = await handler.persist_encrypted_call_message(
        directus_service=directus, cache_service=cache, user_id=OWNER,
        user_id_hash=OWNER_HASH, session_hash=SESSION, message=corrected)
    assert (outcome, revision) == ("replayed", 2)
    assert directus.message["queue_pending_revision"] is None
    assert directus.metadata["messages_v"] == 2


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.privacy
async def test_empty_title_chat_rejects_existing_message_key_mismatch(rig, monkeypatch):
    directus, cache, _manager = rig
    monkeypatch.setattr(handler, "authoritative_chat_fingerprint",
                        fingerprint_tools.authoritative_chat_fingerprint)
    monkeypatch.setattr(handler, "validate_message_matches_authoritative_fingerprint",
                        fingerprint_tools.validate_message_matches_authoritative_fingerprint)
    old = base64.b64encode(b"OM" + b"\x01\x02\x03\x04" + b"a" * 40).decode()
    new = base64.b64encode(b"OM" + b"\x05\x06\x07\x08" + b"b" * 40).decode()
    directus.fingerprint_rows = [{"encrypted_content": old}]
    with pytest.raises(handler.CallMessageError, match="chat_key_mismatch"):
        await handler.persist_encrypted_call_message(
            directus_service=directus, cache_service=cache, user_id=OWNER,
            user_id_hash=OWNER_HASH, session_hash=SESSION,
            message=handler._validated_message(payload(new)))
    assert directus.writes == []


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.privacy
async def test_untitled_legacy_history_finds_late_modern_key_header(rig, monkeypatch):
    directus, cache, _manager = rig
    monkeypatch.setattr(handler, "authoritative_chat_fingerprint",
                        fingerprint_tools.authoritative_chat_fingerprint)
    monkeypatch.setattr(handler, "validate_message_matches_authoritative_fingerprint",
                        fingerprint_tools.validate_message_matches_authoritative_fingerprint)
    old = base64.b64encode(b"legacy" * 8).decode()
    modern = base64.b64encode(b"OM" + b"\x01\x02\x03\x04" + b"a" * 40).decode()
    wrong = base64.b64encode(b"OM" + b"\x05\x06\x07\x08" + b"b" * 40).decode()
    directus.fingerprint_rows = [{"encrypted_content": old} for _ in range(100)] + [
        {"encrypted_content": modern}]
    with pytest.raises(handler.CallMessageError, match="chat_key_mismatch"):
        await handler.persist_encrypted_call_message(
            directus_service=directus, cache_service=cache, user_id=OWNER,
            user_id_hash=OWNER_HASH, session_hash=SESSION,
            message=handler._validated_message(payload(wrong)))
    assert directus.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("correction", [False, True])
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts,video-call.privacy
async def test_call_receipt_waits_for_committed_chat_version_and_repair(rig, correction):
    directus, cache, manager = rig
    directus.metadata["messages_v"] = 20

    async def receive(body):
        await handler.handle_call_message_completed(
            manager=manager, cache_service=cache, directus_service=directus,
            user_id=OWNER, user_id_hash=OWNER_HASH, session_hash=SESSION,
            device_fingerprint_hash="device", payload=body,
        )

    if correction:
        await receive(payload())
        manager.sent.clear()
        manager.broadcasts.clear()
    directus.fail_advance_once = True
    body = payload(CIPHER_B, 2) if correction else payload()
    await receive(body)
    assert manager.sent[-1]["type"] == "call_message_rejected"
    assert "messages_v" not in manager.sent[-1]["payload"]
    assert manager.broadcasts == []
    assert directus.metadata["messages_v"] == (21 if correction else 20)

    await receive(body)
    assert manager.sent[-1]["type"] == "call_message_confirmed"
    assert manager.sent[-1]["payload"]["outcome"] == "replayed"
    assert manager.sent[-1]["payload"]["messages_v"] == (22 if correction else 21)
    assert directus.message["queue_revision"] == body["revision"]
    assert directus.message.get("queue_pending_revision") is None
    assert len(manager.broadcasts) == 1
    assert manager.broadcasts[0]["payload"]["messages_v"] == (22 if correction else 21)
    assert manager.broadcasts[0]["payload"]["encrypted_content"] == body["encrypted_content"]
    assert manager.broadcasts[0]["payload"]["revision"] == body["revision"]
    assert sum("message_id" in write for write in directus.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable_version", ["missing_chat", None, "7", True, -1])
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts
async def test_receipt_never_fabricates_chat_version(rig, monkeypatch, unavailable_version):
    directus, cache, manager = rig
    await handler.handle_call_message_completed(
        manager=manager, cache_service=cache, directus_service=directus,
        user_id=OWNER, user_id_hash=OWNER_HASH, session_hash=SESSION,
        device_fingerprint_hash="device", payload=payload(),
    )
    manager.sent.clear()
    manager.broadcasts.clear()
    read = directus.get_chat_metadata
    reads = 0

    async def unavailable_receipt_authority(chat_id):
        nonlocal reads
        reads += 1
        chat = await read(chat_id)
        if reads == 1:
            return chat  # Existing authorization check still succeeds.
        if unavailable_version == "missing_chat":
            return None
        return {**chat, "messages_v": unavailable_version}

    monkeypatch.setattr(directus, "get_chat_metadata", unavailable_receipt_authority)
    await handler.handle_call_message_completed(
        manager=manager, cache_service=cache, directus_service=directus,
        user_id=OWNER, user_id_hash=OWNER_HASH, session_hash=SESSION,
        device_fingerprint_hash="device", payload=payload(),
    )
    assert manager.sent[-1]["type"] == "call_message_rejected"
    assert manager.sent[-1]["payload"]["code"] == "call_message_storage_failed"
    assert manager.broadcasts == []
    assert directus.metadata["messages_v"] == 1
    assert sum("message_id" in write for write in directus.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("correction", [False, True])
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts,video-call.privacy
async def test_committed_version_survives_metadata_outage_and_retry_without_duplicate_history(rig, monkeypatch, correction):
    directus, cache, manager = rig

    async def receive(body):
        await handler.handle_call_message_completed(
            manager=manager, cache_service=cache, directus_service=directus,
            user_id=OWNER, user_id_hash=OWNER_HASH, session_hash=SESSION,
            device_fingerprint_hash="device", payload=body,
        )

    if correction:
        await receive(payload())
        manager.sent.clear()
        manager.broadcasts.clear()
    finish_name = "_finish_revision" if correction else "_finish_new_message"
    finish = getattr(handler, finish_name)
    read = directus.get_chat_metadata
    outage_reads = 0

    async def unavailable_chat(_chat_id):
        nonlocal outage_reads
        outage_reads += 1
        raise RuntimeError("metadata outage after commit")

    async def commit_then_lose_metadata(*args, **kwargs):
        result = await finish(*args, **kwargs)  # Real row, chat CAS, and marker commits.
        monkeypatch.setattr(directus, "get_chat_metadata", unavailable_chat)
        return result

    monkeypatch.setattr(handler, finish_name, commit_then_lose_metadata)
    body = payload(CIPHER_B, 2) if correction else payload()
    await receive(body)
    expected_version = 2 if correction else 1
    assert outage_reads == 0  # No fallible authority lookup after commit.
    assert manager.sent[-1]["type"] == "call_message_confirmed"
    assert manager.sent[-1]["payload"]["messages_v"] == expected_version
    assert len(manager.broadcasts) == 1
    assert manager.broadcasts[0]["payload"]["encrypted_content"] == body["encrypted_content"]
    assert manager.broadcasts[0]["payload"]["messages_v"] == expected_version

    # A lost receipt may cause a retry during and after the outage. Its durable
    # encrypted row and the already delivered remote event remain exactly once.
    await receive(body)
    assert manager.sent[-1]["type"] == "call_message_rejected"
    assert outage_reads == 1
    monkeypatch.setattr(handler, finish_name, finish)
    monkeypatch.setattr(directus, "get_chat_metadata", read)
    await receive(body)
    assert manager.sent[-1]["payload"]["outcome"] == "replayed"
    assert manager.sent[-1]["payload"]["messages_v"] == expected_version
    assert directus.metadata["messages_v"] == expected_version
    assert directus.message["encrypted_content"] == body["encrypted_content"]
    assert directus.message["queue_revision"] == body["revision"]
    assert directus.message.get("queue_pending_revision") is None
    assert sum("message_id" in write for write in directus.writes) == 1
    assert len(manager.broadcasts) == 1


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=video-call.chat.transcripts,video-call.privacy
async def test_stale_partial_repair_broadcasts_only_stored_winning_ciphertext(rig):
    directus, cache, manager = rig

    async def receive(body):
        await handler.handle_call_message_completed(
            manager=manager, cache_service=cache, directus_service=directus,
            user_id=OWNER, user_id_hash=OWNER_HASH, session_hash=SESSION,
            device_fingerprint_hash="device", payload=body,
        )

    await receive(payload())
    directus.fail_advance_once = True
    await receive(payload(CIPHER_B, 2))
    assert manager.sent[-1]["type"] == "call_message_rejected"
    assert directus.message["queue_pending_revision"] == 2
    manager.broadcasts.clear()
    await receive(payload())
    assert manager.sent[-1]["payload"]["outcome"] == "stale"
    assert manager.sent[-1]["payload"]["messages_v"] == 2
    assert len(manager.broadcasts) == 1
    remote = manager.broadcasts[0]["payload"]
    assert remote["encrypted_content"] == CIPHER_B
    assert remote["revision"] == 2
    assert remote["messages_v"] == 2
    assert directus.message["encrypted_content"] == CIPHER_B
    assert directus.message.get("queue_pending_revision") is None
    assert sum("message_id" in write for write in directus.writes) == 1
    await receive(payload())
    assert directus.metadata["messages_v"] == 2
    assert len(manager.broadcasts) == 1


# contract-test: supporting surface=rest_api assertions=video-call.chat.assistant-identity,video-call.chat.transcripts,video-call.privacy
@pytest.mark.asyncio
async def test_attribution_ciphertext_persists_replays_and_broadcasts_exactly(rig):
    directus, cache, manager = rig
    fields = {"encrypted_category": CIPHER_B, "encrypted_model_name": CIPHER_OLD, "encrypted_sender_name": CIPHER_A}
    async def receive(**changes):
        await handler.handle_call_message_completed(manager=manager, cache_service=cache,
            directus_service=directus, user_id=OWNER, user_id_hash=OWNER_HASH,
            session_hash=SESSION, device_fingerprint_hash="device", payload=payload(**{**fields, **changes}))
    await receive()
    assert manager.sent[-1]["payload"]["outcome"] == "created"
    for field, value in fields.items():
        assert directus.message[field] == value
        assert manager.broadcasts[-1]["payload"][field] == value
    await receive()
    assert manager.sent[-1]["payload"]["outcome"] == "replayed"
    await receive(encrypted_category=CIPHER_OLD)
    assert manager.sent[-1]["type"] == "call_message_rejected"
    assert manager.sent[-1]["payload"]["code"] == "call_message_revision_conflict"
    for value in ("plaintext mate", "bad ciphertext"):
        with pytest.raises(handler.CallMessageError):
            handler._validated_message(payload(encrypted_category=value))


# contract-test: supporting surface=rest_api assertions=video-call.privacy,video-call.lifecycle.recovery-and-billing
@pytest.mark.asyncio
async def test_finalizing_call_allows_issued_ciphertext_retry_without_paid_dispatch(rig, monkeypatch):
    directus, cache, manager = rig
    async def grace_authority(*args, **kwargs):
        return SimpleNamespace(state="finalizing", grace_expires_at=2_000_000_000)
    monkeypatch.setattr(handler, "require_active_call", grace_authority)
    await handler.handle_call_message_completed(
        manager=manager, cache_service=cache, directus_service=directus,
        user_id=OWNER, user_id_hash=OWNER_HASH, session_hash=SESSION,
        device_fingerprint_hash="device", payload=payload(),
    )
    assert directus.message["encrypted_content"] == CIPHER_A
    assert manager.sent[-1]["type"] == "call_message_confirmed"
