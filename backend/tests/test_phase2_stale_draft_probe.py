# contract-test-file: infrastructure
# backend/tests/test_phase2_stale_draft_probe.py
"""
Phase 2 answer to the client's stale-draft probe: an idle local draft whose
draft was deleted on another device (while this one was closed, after the
30-minute tombstones expired) is reported only with the durable delete record
at a version >= the probed one; a merely missing server draft, a re-created
draft, or a chat of another user/Team is never reported.
"""

import hashlib
import json
import sys
import types
from types import SimpleNamespace

if "redis.asyncio" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedis:
        pass

    redis_asyncio_module.Redis = FakeRedis
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import phased_sync_handler
from backend.core.api.app.routes.handlers.websocket_handlers.phase2_stale_draft_probe import (
    STALE_DRAFT_PROBE_LIMIT,
    StaleDraftProbeUnavailable,
    evaluate_stale_draft_probe,
    parse_stale_draft_probe,
    stale_draft_probe_fields,
)

USER = "user-1"
OWNER_HASH = hashlib.sha256(USER.encode()).hexdigest()
OTHER_HASH = hashlib.sha256(b"user-2").hexdigest()
TEAM_HASH = hashlib.sha256(b"team-1").hexdigest()

ABSENT = "00000000-0000-4000-8000-000000000001"
PERSISTED_DRAFT = "00000000-0000-4000-8000-000000000002"
CACHED_DRAFT = "00000000-0000-4000-8000-000000000003"
OWN_CHAT_NO_DRAFT = "00000000-0000-4000-8000-000000000004"
SHARED_FOREIGN_CHAT = "00000000-0000-4000-8000-000000000005"
TEAM_CHAT = "00000000-0000-4000-8000-000000000006"
CACHED_ONLY_CHAT = "00000000-0000-4000-8000-000000000007"
TOMBSTONED_DRAFT = "00000000-0000-4000-8000-000000000008"


class _Pipe:
    def __init__(self, store, fail):
        self.store, self.fail, self.ops = store, fail, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def hgetall(self, key):
        self.ops.append(self.store.get(key, {}))

    def get(self, key):
        self.ops.append(self.store.get(key))

    async def execute(self):
        if self.fail:
            raise ConnectionError("redis down")
        return self.ops


class FakeCache:
    def __init__(self, store=None, fail=False):
        self.store, self.fail, self.pipelines = store or {}, fail, 0

    @property
    async def client(self):
        cache = self

        class _Client:
            def pipeline(self, transaction=False):
                cache.pipelines += 1
                return _Pipe(cache.store, cache.fail)

        return _Client()

    def _get_user_chat_draft_key(self, user_id, chat_id):
        return f"user:{user_id}:chat:{chat_id}:draft"


class FakeDirectus:
    def __init__(self, drafts=(), chats=(), fail=False):
        self.drafts, self.chats, self.fail, self.calls = list(drafts), list(chats), fail, []

    async def get_items(self, collection, params, **kwargs):
        assert kwargs.get("raise_on_error") is True
        self.calls.append((collection, params))
        if self.fail:
            raise RuntimeError("directus down")
        ids = set(params["filter[id][_in]" if collection == "chats" else "filter[chat_id][_in]"].split(","))
        if collection == "drafts":
            assert params["filter[hashed_user_id][_eq]"] == OWNER_HASH
            return [row for row in self.drafts if row["chat_id"] in ids]
        return [row for row in self.chats if row["id"] in ids]


RECREATED = "00000000-0000-4000-8000-000000000009"
NEWER_LOCAL = "00000000-0000-4000-8000-000000000010"
UNRECORDED = "00000000-0000-4000-8000-000000000011"
STALE_PERSISTED_COPY = "00000000-0000-4000-8000-000000000012"

def _record(chat_id, version):
    return {f"user:{USER}:chat:{chat_id}:draft_deleted": {b"draft_v": str(version).encode(), b"deleted_at": b"1"}}

def _cache_store():
    store = {
        f"user:{USER}:chat:{CACHED_DRAFT}:draft": {b"encrypted_draft_md": b"cipher", b"draft_v": b"3"},
        f"user:{USER}:chat:{TOMBSTONED_DRAFT}:draft": {b"deleted": b"true", b"draft_v": b"9"},
        f"chat:{CACHED_ONLY_CHAT}:metadata": json.dumps({"id": CACHED_ONLY_CHAT}).encode(),
        f"chat:{ABSENT}:metadata": json.dumps({"deleted": True}).encode(),
    }
    # Every id except UNRECORDED has a delete record; NEWER_LOCAL's is older
    # than the local draft, RECREATED has a newer persisted draft after it.
    for chat_id in (ABSENT, PERSISTED_DRAFT, CACHED_DRAFT, OWN_CHAT_NO_DRAFT, SHARED_FOREIGN_CHAT,
                    TEAM_CHAT, CACHED_ONLY_CHAT, RECREATED, STALE_PERSISTED_COPY):
        store.update(_record(chat_id, 2))
    store.update(_record(TOMBSTONED_DRAFT, 9))
    store.update(_record(NEWER_LOCAL, 1))
    return store

def _directus():
    return FakeDirectus(
        drafts=[
            {"chat_id": PERSISTED_DRAFT, "encrypted_content": "cipher", "version": 3},
            {"chat_id": TOMBSTONED_DRAFT, "encrypted_content": "old-cipher", "version": 4},
            {"chat_id": RECREATED, "encrypted_content": "new-cipher", "version": 5},
            {"chat_id": STALE_PERSISTED_COPY, "encrypted_content": "old-cipher", "version": 2},
        ],
        chats=[
            {"id": OWN_CHAT_NO_DRAFT, "hashed_user_id": OWNER_HASH, "hashed_team_id": None},
            {"id": SHARED_FOREIGN_CHAT, "hashed_user_id": OTHER_HASH, "hashed_team_id": None},
            {"id": TEAM_CHAT, "hashed_user_id": OWNER_HASH, "hashed_team_id": TEAM_HASH},
        ],
    )

PROBE = {ABSENT: 2, PERSISTED_DRAFT: 2, CACHED_DRAFT: 2, OWN_CHAT_NO_DRAFT: 2, SHARED_FOREIGN_CHAT: 2,
         TEAM_CHAT: 2, CACHED_ONLY_CHAT: 2, TOMBSTONED_DRAFT: 2, RECREATED: 2, NEWER_LOCAL: 2,
         UNRECORDED: 2, STALE_PERSISTED_COPY: 2}

@pytest.mark.anyio
async def test_probe_reports_only_recorded_deletes() -> None:
    cache, directus = FakeCache(_cache_store()), _directus()
    result = await evaluate_stale_draft_probe(cache, directus, USER, PROBE)

    assert result["absent_chat_ids"] == [ABSENT, TOMBSTONED_DRAFT, STALE_PERSISTED_COPY]
    assert result["draft_absent_chat_ids"] == [OWN_CHAT_NO_DRAFT]
    reported = set(result["absent_chat_ids"]) | set(result["draft_absent_chat_ids"])
    assert not reported & {PERSISTED_DRAFT, CACHED_DRAFT, SHARED_FOREIGN_CHAT, TEAM_CHAT, CACHED_ONLY_CHAT,
                           RECREATED, NEWER_LOCAL, UNRECORDED}
    assert cache.pipelines == 1
    assert [collection for collection, _ in directus.calls] == ["drafts", "chats"]
    assert UNRECORDED not in directus.calls[0][1]["filter[chat_id][_in]"]

@pytest.mark.anyio
async def test_missing_server_draft_without_record_is_not_reported() -> None:
    # Nothing on the server at all (e.g. a replayed draft whose Redis copy
    # expired before persistence): without a delete record it stays local.
    directus = FakeDirectus()
    result = await evaluate_stale_draft_probe(FakeCache(), directus, USER, {UNRECORDED: 1})
    assert result == {"absent_chat_ids": [], "draft_absent_chat_ids": []}
    assert directus.calls == []

@pytest.mark.anyio
async def test_record_older_than_local_draft_is_not_reported() -> None:
    cache = FakeCache(_record(ABSENT, 3))
    assert (await evaluate_stale_draft_probe(cache, FakeDirectus(), USER, {ABSENT: 4}))["absent_chat_ids"] == []
    assert (await evaluate_stale_draft_probe(cache, FakeDirectus(), USER, {ABSENT: 3}))["absent_chat_ids"] == [ABSENT]

@pytest.mark.anyio
async def test_draft_recreated_after_delete_is_not_reported() -> None:
    cached = FakeCache({**_record(ABSENT, 3),
                        f"user:{USER}:chat:{ABSENT}:draft": {b"encrypted_draft_md": b"c", b"draft_v": b"4"}})
    persisted = FakeDirectus(drafts=[{"chat_id": ABSENT, "encrypted_content": "c", "version": 4}])
    for cache, directus in ((cached, FakeDirectus()), (FakeCache(_record(ABSENT, 3)), persisted)):
        result = await evaluate_stale_draft_probe(cache, directus, USER, {ABSENT: 2})
        assert result["absent_chat_ids"] == []

@pytest.mark.anyio
async def test_probe_lookup_failure_reports_nothing() -> None:
    with pytest.raises(StaleDraftProbeUnavailable):
        await evaluate_stale_draft_probe(FakeCache(fail=True), _directus(), USER, {ABSENT: 2})
    with pytest.raises(StaleDraftProbeUnavailable):
        await evaluate_stale_draft_probe(FakeCache(_record(ABSENT, 2)), FakeDirectus(fail=True), USER, {ABSENT: 2})
    failing = FakeDirectus(fail=True)
    assert await stale_draft_probe_fields(FakeCache(_record(ABSENT, 2)), failing, USER, {ABSENT: 2}, None) == {}

@pytest.mark.anyio
async def test_team_workspace_is_never_probed() -> None:
    directus = _directus()
    assert await stale_draft_probe_fields(FakeCache(_cache_store()), directus, USER, {ABSENT: 2}, "team-1") == {}
    assert directus.calls == []

INVALID_VERSION = "11111111-1111-4111-8111-111111111111"

def test_probe_request_is_bounded_and_validated() -> None:
    raw = [{"chat_id": f"00000000-0000-4000-8000-{index:012d}", "draft_v": 1}
           for index in range(STALE_DRAFT_PROBE_LIMIT + 50)]
    raw[:0] = [{"chat_id": "not-a-uuid", "draft_v": 1}, "garbage", {"chat_id": raw[0]["chat_id"]},
               {"chat_id": INVALID_VERSION, "draft_v": 0}, {"chat_id": INVALID_VERSION, "draft_v": True}]
    parsed = parse_stale_draft_probe(raw)
    assert len(parsed) == STALE_DRAFT_PROBE_LIMIT
    assert next(iter(parsed)) == raw[5]["chat_id"]
    assert INVALID_VERSION not in parsed
    assert parse_stale_draft_probe(None) == {}
    assert parse_stale_draft_probe({"chat_id": ABSENT}) == {}

@pytest.mark.anyio
async def test_phase2_payload_carries_probe_result(monkeypatch) -> None:
    class FakeChat:
        async def get_user_chat_count(self, user_id, team_id=None):
            return 0

        async def get_core_chats_and_user_drafts_for_cache_warming(self, user_id, limit=100, team_id=None):
            return []

        async def get_all_user_drafts(self, user_id):
            return {}

    class Phase2Directus(FakeDirectus):
        chat = FakeChat()

    class Phase2Cache(FakeCache):
        async def get_all_user_draft_chat_ids(self, user_id):
            return []

        async def get(self, key):
            return None

    async def no_fences(directus_service, user_id, chat_ids):
        return set()

    monkeypatch.setattr(phased_sync_handler, "_lookup_durable_deleted_chat_ids", no_fences)
    sent = []

    async def send_personal_message(message, user_id, device_fingerprint_hash):
        sent.append(message)

    manager = SimpleNamespace(send_personal_message=send_personal_message)
    await phased_sync_handler._handle_phase2_sync(
        manager=manager, cache_service=Phase2Cache(_record(ABSENT, 2)), directus_service=Phase2Directus(),
        user_id=USER, device_fingerprint_hash="device-1", client_chat_versions={},
        client_chat_ids=[ABSENT], sent_embed_ids=set(), stale_draft_probe_ids={ABSENT: 2},
    )
    payload = sent[0]["payload"]
    assert payload["stale_draft_probe_result"] == {"absent_chat_ids": [ABSENT], "draft_absent_chat_ids": []}
    assert ABSENT not in payload["explicit_deleted_chat_ids"]
