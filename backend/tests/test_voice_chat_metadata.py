"""Voice metadata admission, sealed recovery and version-bound ciphertext commits."""

import asyncio
import copy
import base64
import json
import sys
import uuid
from types import SimpleNamespace, ModuleType
from unittest.mock import AsyncMock, Mock

import fakeredis.aioredis
import pytest

from backend.shared.python_utils import voice_chat_metadata as metadata
from backend.shared.python_utils.voice_call_registry import (
    register_active_call,
    issue_message_id,
    finalize_active_call,
)

OWNER = str(uuid.UUID(int=1))
CHAT = str(uuid.UUID(int=2))


class Cache:
    def __init__(self):
        self.redis = fakeredis.aioredis.FakeRedis()
        self.versions = SimpleNamespace(title_v=1, metadata_v=2)
        self.publish_event = AsyncMock()
        self.delete_chat_list_item_data = AsyncMock()
        self.set_chat_version_component = AsyncMock()

    @property
    async def client(self):
        return self.redis

    async def get_user_vault_key_id(self, _user_id):
        return "owner-key"

    async def get_chat_versions(self, *_args):
        return self.versions


class Encryption:
    def __init__(self):
        self.plaintexts = {}

    async def encrypt_with_user_key(self, text, _key):
        sealed = "vault:v1:" + uuid.uuid4().hex
        self.plaintexts[sealed] = text
        return sealed, 1

    async def decrypt_with_user_key(self, sealed, _key):
        return self.plaintexts[sealed]


@pytest.fixture
async def setup(monkeypatch):
    cache, encryption = Cache(), Encryption()
    chat = {
        "id": CHAT,
        "hashed_user_id": "owner-hash",
        "metadata_v": 2,
        "title_v": 1,
        "encrypted_chat_key": "wrapped-key",
        "encrypted_title": "old-title",
        "encrypted_chat_summary": "old-summary",
        "title_is_manual": False,
    }
    rows = [
        {"client_message_id": "issued-user", "role": "user", "queue_revision": 1},
        {
            "client_message_id": "issued-assistant",
            "role": "assistant",
            "queue_revision": 1,
        },
    ]

    async def cas(_collection, _id, fields, expected_version, **kwargs):
        if chat["metadata_v"] != expected_version or any(
            chat.get(k) != v for k, v in kwargs["extra_filters"].items()
        ):
            return None
        chat.update(fields)
        return dict(chat)

    directus = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(side_effect=lambda *_, **_kwargs: dict(chat))
        ),
        get_items=AsyncMock(
            side_effect=lambda collection, **_kwargs: (
                rows if collection == "messages" else []
            )
        ),
        update_item_if_version=AsyncMock(side_effect=cas),
    )
    app = SimpleNamespace(send_task=Mock())
    module = ModuleType("backend.core.api.app.tasks.celery_config")
    module.app = app
    monkeypatch.setitem(sys.modules, module.__name__, module)
    call_id = uuid.uuid4().hex
    call = dict(user_id=OWNER, session_id="session", chat_id=CHAT, call_id=call_id)
    await register_active_call(cache, **call)
    for row in rows:
        await issue_message_id(
            cache, **call, message_id=row["client_message_id"], role=row["role"]
        )
    payload = dict(
        request_id=str(uuid.uuid4()),
        chat_id=CHAT,
        call_id=call_id,
        source_messages=[
            dict(message_id=row["client_message_id"], role=row["role"], revision=1)
            for row in rows
        ],
        context={
            "summary": "Earlier budget and preferences",
            "messages": [
                {"role": "user", "content": "How do I make ramen?"},
                {"role": "assistant", "content": "Use vegetable broth."},
            ],
        },
        current_title="Ramen cooking",
        current_summary="Earlier recipe discussion",
        source_title_v=1,
        source_metadata_v=2,
        encrypted_chat_key="wrapped-key",
        final=False,
    )
    auth = dict(
        cache=cache,
        directus=directus,
        encryption=encryption,
        user_id=OWNER,
        user_hash="owner-hash",
    )
    return SimpleNamespace(
        cache=cache,
        encryption=encryption,
        chat=chat,
        rows=rows,
        directus=directus,
        app=app,
        call=call,
        payload=payload,
        auth=auth,
    )


async def complete(state, result=None):
    request_id = await metadata.admit(
        **state.auth, session_id="session", payload=state.payload
    )
    ciphertext = state.app.send_task.call_args.kwargs["kwargs"]["ciphertext"]
    data = json.loads(state.encryption.plaintexts[ciphertext])
    await metadata.publish_result(
        **{k: state.auth[k] for k in ("cache", "directus", "encryption")},
        data=data,
        result=result
        or {
            "updated_chat_title": "Vegetarian ramen",
            "chat_summary": "Discussed vegetable broth and ramen.",
        },
    )
    return request_id


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
async def test_uncertain_queue_ack_keeps_the_same_inference_identity(setup):
    s = setup
    s.app.send_task.side_effect = RuntimeError("Broker acknowledgement unavailable")
    with pytest.raises(RuntimeError):
        await metadata.admit(**s.auth, session_id="session", payload=s.payload)
    original = s.app.send_task.call_args.kwargs["task_id"]
    s.app.send_task.side_effect = None
    accepted = await metadata.admit(
        **s.auth,
        session_id="session",
        payload={**s.payload, "request_id": str(uuid.uuid4())},
    )
    assert accepted == original == s.app.send_task.call_args.kwargs["task_id"]


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle,video-call.privacy


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
async def test_admission_is_sealed_and_repeated_snapshot_never_dispatches_again(setup):
    s = setup
    request_id = await metadata.admit(**s.auth, session_id="session", payload=s.payload)
    queued = s.app.send_task.call_args.kwargs
    assert queued["queue"] == "app_ai"
    assert "ramen" not in json.dumps(queued)
    await finalize_active_call(s.cache, **s.call)
    await s.cache.redis.delete(*await s.cache.redis.keys("voice:call:*"))
    assert (
        await metadata.admit(
            **s.auth,
            session_id="session",
            payload={**s.payload, "request_id": str(uuid.uuid4())},
        )
        == request_id
    )
    assert s.app.send_task.call_count == 1


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "session", "revision", "key", "team"])
async def test_unowned_or_unpersisted_sources_cannot_start_paid_work(setup, change):
    s = setup
    session = "session"
    if change == "owner":
        s.chat["hashed_user_id"] = "other-owner"
    if change == "session":
        session = "other-session"
    if change == "revision":
        s.rows[0]["queue_revision"] = 2
    if change == "key":
        s.payload["encrypted_chat_key"] = "stale-key"
    if change == "team":
        s.chat["hashed_team_id"] = "team"
    with pytest.raises(ValueError):
        await metadata.admit(**s.auth, session_id=session, payload=s.payload)
    s.app.send_task.assert_not_called()


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-lifecycle


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
async def test_recovery_after_hangup_commits_only_ciphertext_and_replays_ack(setup):
    s = setup
    request_id = await complete(s)
    await s.cache.redis.delete(*await s.cache.redis.keys("voice:call:*"))
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await metadata.send_pending(
        manager=manager,
        cache_service=s.cache,
        directus_service=s.directus,
        encryption_service=s.encryption,
        user_id=OWNER,
        user_id_hash="owner-hash",
        device_fingerprint_hash="new-device",
    )
    assert (
        manager.send_personal_message.call_args.args[0]["type"]
        == "voice_metadata_completed"
    )
    payload = {
        "request_id": request_id,
        "encrypted_metadata": {
            "encrypted_title": base64.b64encode(
                b"636c69656e742d6369706865722d7469746c65" * 4
            ).decode(),
            "encrypted_chat_summary": base64.b64encode(
                b"636c69656e742d6369706865722d73756d6d617279" * 4
            ).decode(),
        },
    }
    saved = await metadata.commit(**s.auth, payload=payload)
    assert saved["versions"] == {"title_v": 2, "metadata_v": 3}
    assert (
        s.chat["encrypted_chat_summary"]
        == base64.b64encode(b"636c69656e742d6369706865722d73756d6d617279" * 4).decode()
    )
    assert await metadata.commit(**s.auth, payload=payload) == saved
    assert s.directus.update_item_if_version.await_count == 1
    # A lost commit ACK may cause the client to re-admit the same snapshot.
    # Exact receipt recovery remains available after its pending index is gone.
    manager.send_personal_message.reset_mock()
    await metadata.send_pending(
        manager=manager,
        cache_service=s.cache,
        directus_service=s.directus,
        encryption_service=s.encryption,
        user_id=OWNER,
        user_id_hash="owner-hash",
        device_fingerprint_hash="new-device",
        request_id=request_id,
    )
    assert manager.send_personal_message.await_count == 1
    assert await s.cache.redis.scard(metadata.key("pending", OWNER)) == 0
    for item in await s.cache.redis.keys("voice:metadata:*"):
        if await s.cache.redis.type(item) == b"string":
            assert b"vegetable broth" not in await s.cache.redis.get(item)


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
async def test_manual_title_is_preserved_while_summary_updates(setup):
    s = setup
    s.chat["title_is_manual"] = True
    request_id = await complete(s)
    saved = await metadata.commit(
        **s.auth,
        payload={
            "request_id": request_id,
            "encrypted_metadata": {
                "encrypted_title": base64.b64encode(
                    b"67656e6572617465642d7469746c65" * 4
                ).decode(),
                "encrypted_chat_summary": base64.b64encode(
                    b"67656e6572617465642d73756d6d617279" * 4
                ).decode(),
            },
        },
    )
    assert saved["encrypted_metadata"] == {
        "encrypted_chat_summary": base64.b64encode(
            b"67656e6572617465642d73756d6d617279" * 4
        ).decode()
    }
    assert s.chat["encrypted_title"] == "old-title"


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["metadata", "transcript", "key", "new-text-turn", "new-voice-job"]
)
async def test_newer_metadata_transcripts_and_key_rotation_supersede_result(
    setup, change
):
    s = setup
    request_id = await complete(s)
    if change == "metadata":
        s.cache.versions.metadata_v = 3
    if change == "new-voice-job":
        await s.cache.redis.set(metadata.key("latest", OWNER, CHAT), str(uuid.uuid4()))
    if change == "transcript":
        s.rows[0]["queue_revision"] = 2
    if change == "key":
        s.chat["encrypted_chat_key"] = "rotated-key"
    if change == "new-text-turn":
        s.directus.get_items.side_effect = lambda collection, **_kwargs: (
            [{"id": "newer-text-turn"}]
            if collection == "chat_turn_preflights"
            else s.rows
        )
    saved = await metadata.commit(
        **s.auth,
        payload={
            "request_id": request_id,
            "encrypted_metadata": {
                "encrypted_chat_summary": base64.b64encode(
                    b"6f6c642d67656e6572617465642d73756d6d617279" * 4
                ).decode()
            },
        },
    )
    assert saved["superseded"] is True
    assert saved["encrypted_metadata"] == {}
    s.directus.update_item_if_version.assert_not_called()


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
async def test_failed_commit_remains_pending_for_free_recovery(setup):
    s = setup
    request_id = await complete(s)
    s.directus.update_item_if_version.side_effect = None
    s.directus.update_item_if_version.return_value = None
    with pytest.raises(RuntimeError):
        await metadata.commit(
            **s.auth,
            payload={
                "request_id": request_id,
                "encrypted_metadata": {
                    "encrypted_chat_summary": base64.b64encode(
                        b"636c69656e742d63697068657274657874" * 4
                    ).decode()
                },
            },
        )
    assert await s.cache.redis.scard(metadata.key("pending", OWNER)) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_metadata_v", True),
        ("context", {"summary": "x" * 48_001, "messages": []}),
        ("source_messages", []),
        ("final", "yes"),
    ],
)
# contract-test: supporting surface=rest_api assertions=video-call.privacy
def test_request_bounds_reject_invalid_inputs(field, value):
    # Validation is tested against a complete minimum request rather than
    # relying on the admission fixture's external state.
    value_before = dict(
        request_id=str(uuid.uuid4()),
        chat_id=CHAT,
        call_id=uuid.uuid4().hex,
        source_messages=[{"message_id": "issued-user", "role": "user", "revision": 1}],
        context={"summary": "", "messages": [{"role": "user", "content": "Ramen"}]},
        current_title="",
        current_summary="",
        source_title_v=0,
        source_metadata_v=0,
        encrypted_chat_key="wrapped-key",
        final=False,
    )
    with pytest.raises(ValueError):
        metadata.validate_request({**value_before, field: copy.deepcopy(value)})


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
async def test_new_call_admission_waits_for_commit_and_refreshes_stale_baseline_without_paid_work(setup):
    s = setup
    request_id = await complete(s)
    await finalize_active_call(s.cache, **s.call)
    next_call = {**s.call, "call_id": uuid.uuid4().hex}
    await register_active_call(s.cache, **next_call)
    next_sources = []
    for role in ("user", "assistant"):
        message_id = f"issued-next-{role}"
        await issue_message_id(s.cache, **next_call, message_id=message_id, role=role)
        s.rows.append({"client_message_id": message_id, "role": role, "queue_revision": 1})
        next_sources.append({"message_id": message_id, "role": role, "revision": 1})
    entered, release = asyncio.Event(), asyncio.Event()

    async def source_query(collection, **_kwargs):
        if collection == "messages":
            entered.set()
            await release.wait()
            return s.rows
        return []

    s.directus.get_items.side_effect = source_query
    stored = asyncio.create_task(metadata.commit(**s.auth, payload={"request_id": request_id,
        "encrypted_metadata": {"encrypted_chat_summary": base64.b64encode(b"first-call-ciphertext" * 4).decode()}}))
    await asyncio.wait_for(entered.wait(), 1)
    next_payload = {**s.payload, "request_id": str(uuid.uuid4()), "call_id": next_call["call_id"],
                    "source_messages": next_sources}
    admitted = asyncio.create_task(metadata.admit(**s.auth, session_id="session", payload=next_payload))
    await asyncio.sleep(0)
    assert not admitted.done()
    release.set()
    assert (await stored)["versions"]["metadata_v"] == 3
    with pytest.raises(metadata.MetadataStale):
        await admitted
    assert s.app.send_task.call_count == 1
    next_payload["source_metadata_v"] = 3
    await metadata.admit(**s.auth, session_id="session", payload=next_payload)
    assert s.app.send_task.call_count == 2


# contract-test: supporting surface=rest_api assertions=video-call.chat.metadata-lifecycle
@pytest.mark.asyncio
async def test_text_admission_after_freshness_query_cannot_be_overwritten(setup):
    s = setup
    s.chat["messages_v"] = 5
    request_id = await complete(s)

    async def concurrent_text(collection, **_kwargs):
        if collection == "messages":
            s.chat["messages_v"] = 6
            return s.rows
        return []

    s.directus.get_items.side_effect = concurrent_text
    with pytest.raises(RuntimeError):
        await metadata.commit(**s.auth, payload={"request_id": request_id, "encrypted_metadata": {
            "encrypted_chat_summary": base64.b64encode(b"old-call-ciphertext" * 4).decode()}})
    assert s.chat["encrypted_chat_summary"] == "old-summary"
    assert await s.cache.redis.scard(metadata.key("pending", OWNER)) == 1
