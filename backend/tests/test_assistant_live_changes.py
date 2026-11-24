"""Assistant edits of live-capable embeds: events, offline cache, base check, outcomes."""

import base64
import json
from types import SimpleNamespace

import pytest

from backend.apps.ai import assistant_live_changes as live
from backend.apps.ai.tasks import stream_consumer
from backend.apps.ai.tasks.stream_consumer import _apply_diff_block_to_existing_embed
from backend.tests.test_embed_diff_full_replacement import _FakeDirectusService


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.published: list[tuple[str, dict]] = []

    async def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))

    async def set(self, key, value, ex=None):
        self.kv[key] = value

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, key):
        self.kv.pop(key, None)

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    async def zrem(self, key, member):
        self.zsets.get(key, {}).pop(member, None)

    async def zrange(self, key, _a, _b):
        return list(self.zsets.get(key, {}))

    async def zremrangebyscore(self, key, _lo, hi):
        z = self.zsets.get(key, {})
        for k in [k for k, v in z.items() if v <= hi]:
            del z[k]

    async def expire(self, *_a):
        return True

    async def eval(self, _script, _n, key, expected, new, _ttl):
        """Mirror of the compare-and-set Lua script in assistant_live_changes."""
        cur = self.kv.get(key, expected)
        if int(cur) != int(expected):
            return 0
        self.kv[key] = new
        return 1


class FakeCache:
    def __init__(self, embeds):
        self.embeds = embeds
        self.redis = FakeRedis()

    @property
    async def client(self):
        return self.redis

    async def get_embed_from_cache(self, embed_id):
        return self.embeds.get(embed_id)


class FakeEncryption:
    def __init__(self, plaintext: str) -> None:
        self.plaintext = plaintext

    async def decrypt_with_user_key(self, ciphertext, _key):
        return self.plaintext if ciphertext == "encrypted" else base64.b64decode(ciphertext[len("sealed:"):]).decode()

    async def encrypt_with_user_key(self, plaintext, _key):
        return "sealed:" + base64.b64encode(plaintext.encode()).decode(), "v1"


class RecordingEmbedService:
    def __init__(self) -> None:
        self.writes = 0

    async def update_document_embed_content(self, **_kw):
        self.writes += 1

    async def update_table_embed_content(self, **_kw):
        self.writes += 1

    async def update_code_embed_content(self, **_kw):
        self.writes += 1


PATCH = "@@ -1,2 +1,2 @@\n first line\n-second line\n+updated line"
REQUEST = SimpleNamespace(
    chat_id="chat-1", message_id="turn-1", user_id="user-1", user_id_hash="hash-1",
    mate_id="sophia", embed_file_path_index={"sheet.csv-AbC": "embed-1"},
)


def _setup(monkeypatch, *, flag: bool, online: bool, version: int = 3, embed_type: str = "sheet"):
    from toon_format import encode

    monkeypatch.setattr(
        stream_consumer.celery_config, "config_manager",
        SimpleNamespace(get_backend_config=lambda: {"feature_flags": {"live_collaboration": flag}}),
        raising=False,
    )

    async def presence(_cache, _user, _chat):
        return online

    monkeypatch.setattr(live, "_requester_online", presence)
    cache = FakeCache({"embed-1": {
        "embed_id": "embed-1", "type": embed_type, "status": "finished",
        "version_number": version, "encrypted_content": "encrypted",
    }})
    plaintext = encode({"type": embed_type, "table": "first line\nsecond line", "content": "first line\nsecond line"})
    return cache, FakeEncryption(plaintext), RecordingEmbedService()


async def _run(cache, encryption, service):
    return await _apply_diff_block_to_existing_embed(
        diff_content=PATCH, diff_embed_ref=None, request_data=REQUEST, cache_service=cache,
        directus_service=_FakeDirectusService(), encryption_service=encryption,
        embed_service=service, user_vault_key_id="vault-1", log_prefix="[test]",
    )


async def _answer(cache, outcome):
    await live.record_outcome(cache, user_id_hash="hash-1", embed_id="embed-1", turn_id="turn-1", outcome=outcome)


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.live-edits,live-collab.assistant.human-wins
@pytest.mark.anyio
async def test_flag_on_emits_events_and_writes_no_version(monkeypatch) -> None:
    cache, enc, service = _setup(monkeypatch, flag=True, online=True)
    monkeypatch.setattr(live, "OUTCOME_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(stream_consumer, "resolve_outcome_details", lambda *_a: _resolved(("done", {})))
    await _run(cache, enc, service)
    events = [p["event"] for _c, p in cache.redis.published]
    assert events == ["embed_assistant_editing", "embed_assistant_change"]
    assert all(p["user_id_uuid"] == REQUEST.user_id for _c, p in cache.redis.published)
    assert cache.redis.published[0][1]["payload"]["mate_name"] == "sophia"
    change = cache.redis.published[1][1]["payload"]
    assert change["embed_id"] == "embed-1" and change["turn_id"] == "turn-1" and change["base_version"] == 3
    assert change["mate_name"] == "sophia" and change["scope"] == ["@@ -1,2 +1,2 @@"]
    assert change["new_text_form"] and cache.redis.published[0][0] == "websocket:user:hash-1"
    assert service.writes == 0


async def _resolved(value):
    return value


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.one-change-for-everyone
@pytest.mark.anyio
async def test_offline_requester_change_waits_sealed_then_flushes(monkeypatch) -> None:
    cache, enc, service = _setup(monkeypatch, flag=True, online=False)
    result = await _run(cache, enc, service)
    assert "embed-1" in result and service.writes == 0
    assert [p["event"] for _c, p in cache.redis.published] == ["embed_assistant_editing"]
    stored = [v for k, v in cache.redis.kv.items() if k.startswith("assistant_live_change:hash-1:embed-1:turn-1")]
    assert stored and "updated line" not in stored[0]  # sealed, no plaintext at rest
    sent = await live.flush_pending_assistant_changes(cache, enc, "user-1", "hash-1", "vault-1")
    assert sent == 1
    flushed = cache.redis.published[-1][1]
    assert flushed["event"] == "embed_assistant_change" and flushed["payload"]["base_version"] == 3
    assert flushed["user_id_uuid"] == REQUEST.user_id
    assert await live.flush_pending_assistant_changes(cache, enc, "user-1", "hash-1", "vault-1") == 0


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.human-wins
@pytest.mark.anyio
async def test_flag_off_refuses_to_overwrite_newer_human_version(monkeypatch) -> None:
    cache, enc, service = _setup(monkeypatch, flag=False, online=True)
    original = cache.get_embed_from_cache

    async def moving(embed_id):
        first = dict(await original(embed_id))
        calls.append(1)
        if len(calls) > 1:
            first["version_number"] = 4  # a human saved meanwhile
        return first

    calls: list[int] = []
    cache.get_embed_from_cache = moving
    result = await _run(cache, enc, service)
    assert service.writes == 0 and "changed" in result
    assert cache.redis.published == []


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.human-wins
@pytest.mark.anyio
async def test_flag_off_still_writes_when_version_unchanged(monkeypatch) -> None:
    cache, enc, service = _setup(monkeypatch, flag=False, online=True)
    await _run(cache, enc, service)
    assert service.writes == 1 and cache.redis.published == []


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.human-wins
@pytest.mark.anyio
@pytest.mark.parametrize("outcome,marker", [
    ("same_spot", "suggestion"), ("target_deleted", "dropped"), ("applied", "embed-1"),
])
async def test_outcome_decides_reply(monkeypatch, outcome, marker) -> None:
    cache, enc, service = _setup(monkeypatch, flag=True, online=True)
    await _seed_outcome_after_delivery(cache, monkeypatch, outcome)
    result = await _run(cache, enc, service)
    assert marker in result and service.writes == 0


async def _seed_outcome_after_delivery(cache, monkeypatch, outcome):
    real = live.deliver_assistant_change

    async def deliver(**kw):
        status = await real(**kw)
        await _answer(cache, outcome)
        return status

    monkeypatch.setattr(stream_consumer, "deliver_assistant_change", deliver)


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.human-wins
@pytest.mark.anyio
async def test_needs_recheck_then_unresolved_falls_back_to_card(monkeypatch) -> None:
    cache, enc, service = _setup(monkeypatch, flag=True, online=True)
    monkeypatch.setattr(live, "OUTCOME_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(live, "OUTCOME_POLL_SECONDS", 0.05)
    await _seed_outcome_after_delivery(cache, monkeypatch, "needs_recheck")
    real_await = live.await_outcome

    async def short(cache_, e, t, *, timeout=0.3, ignore_outcome=None):
        return await real_await(cache_, e, t, timeout=0.2, ignore_outcome=ignore_outcome)

    monkeypatch.setattr(live, "await_outcome", short)
    assert "suggestion" in await _run(cache, enc, service)


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.human-wins
@pytest.mark.anyio
async def test_outcome_auth_and_state_transitions() -> None:
    cache = FakeCache({})
    await cache.redis.set("assistant_live_turn:e:t", "hash-1")
    with pytest.raises(PermissionError):
        await live.record_outcome(cache, user_id_hash="other", embed_id="e", turn_id="t", outcome="applied")
    with pytest.raises(LookupError):
        await live.record_outcome(cache, user_id_hash="hash-1", embed_id="e", turn_id="nope", outcome="applied")
    with pytest.raises(ValueError):
        await live.record_outcome(cache, user_id_hash="hash-1", embed_id="e", turn_id="t", outcome="bogus")
    await live.record_outcome(cache, user_id_hash="hash-1", embed_id="e", turn_id="t", outcome="needs_recheck")
    await live.record_outcome(cache, user_id_hash="hash-1", embed_id="e", turn_id="t", outcome="same_spot")
    await live.record_outcome(cache, user_id_hash="hash-1", embed_id="e", turn_id="t", outcome="same_spot")
    with pytest.raises(ValueError):
        await live.record_outcome(cache, user_id_hash="hash-1", embed_id="e", turn_id="t", outcome="applied")


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.human-wins
@pytest.mark.anyio
async def test_flag_off_cas_rejects_version_bumped_between_read_and_write(monkeypatch) -> None:
    cache, enc, service = _setup(monkeypatch, flag=False, online=True)
    # A human revision commits after the assistant's reads: only the CAS key knows.
    await live.record_committed_embed_version(cache, "embed-1", 4)
    result = await _run(cache, enc, service)
    assert service.writes == 0 and "changed" in result


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.human-wins
@pytest.mark.anyio
async def test_claim_embed_version_is_exclusive() -> None:
    cache = FakeCache({})
    assert await live.claim_embed_version(cache, "e", 3, 4) is True
    assert await live.claim_embed_version(cache, "e", 3, 4) is False


# contract-test: supporting surface=rest_api assertions=live-collab.assistant.human-wins
@pytest.mark.anyio
async def test_same_spot_regenerates_once_then_card(monkeypatch) -> None:
    cache, enc, service = _setup(monkeypatch, flag=True, online=True)
    text = "first line\nsecond line\nthird"
    real_deliver = live.deliver_assistant_change

    async def deliver(**kwargs):
        status = await real_deliver(**kwargs)
        turn = kwargs["turn_id"]
        await live.record_outcome(
            cache, user_id_hash="hash-1", embed_id="embed-1", turn_id=turn, outcome="same_spot",
            details={"current_text_form": text, "current_version": kwargs["base_version"] + 1},
            encryption_service=enc, user_vault_key_id="vault-1",
        )
        stored = json.loads(await cache.redis.get(live._outcome_key("embed-1", turn)))
        assert stored["sealed_details"] and "current_text_form" not in stored
        return status

    monkeypatch.setattr(stream_consumer, "deliver_assistant_change", deliver)
    result = await _run(cache, enc, service)
    changes = [m for m in cache.redis.published if m[1]["event"] == "embed_assistant_change"]
    assert len(changes) == 2 and changes[1][1]["payload"]["base_version"] == 4
    assert changes[1][1]["payload"]["turn_id"] == "turn-1:r1"
    assert "suggestion" in result and service.writes == 0
