"""Bounded epoch-0 queue handoff checks without broker, provider, or Redis service."""

import asyncio
import hashlib
import json
import base64
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from backend.apps.ai.tasks.ask_skill_task import (
    _legacy_queued_batch_proof,
    _validated_queued_messages,
    _verify_legacy_batch_proof,
    resume_legacy_queued_handoff,
)
from backend.apps.ai.tasks import ask_skill_task
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.skills.ask_skill import AskSkill
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError


class _AtomicLock:
    def __init__(self, redis, name):
        self.redis = redis
        self.name = name
        self.local = SimpleNamespace(token=b"queue-admission-token")
        self.mutex = redis.locks.setdefault(name, asyncio.Lock())

    async def __aenter__(self):
        await self.mutex.acquire()
        self.redis.strings[self.name] = self.local.token
        return self

    async def __aexit__(self, *_):
        if await self.owned():
            self.redis.strings.pop(self.name, None)
        self.mutex.release()

    async def owned(self):
        return self.redis.strings.get(self.name) == self.local.token

    async def extend(self, *_args, **_kwargs):
        return await self.owned()


class _AtomicRedis:
    def __init__(self):
        self.lists = {}
        self.strings = {}
        self.hashes = {}
        self.zsets = {}
        self.locks = {}

    async def eval(self, script, key_count, *args):
        keys, values = args[:key_count], args[key_count:]
        if script == ChatCacheMixin._APPEND_QUEUED_MESSAGE_LUA:
            self.lists.setdefault(keys[0], []).append(values[0])
            return len(self.lists[keys[0]])
        if script == ChatCacheMixin._LEASE_QUEUED_PREFIX_LUA:
            queue, lease = keys
            existing = self.strings.get(lease)
            if existing:
                token, count = existing.rsplit(":", 1)
                count = int(count)
            else:
                prefix = self.lists.get(queue, [])[:int(values[0])]
                count = 0
                size = 0
                for item in prefix:
                    size += len(item.encode())
                    if size > int(values[3]):
                        if not count:
                            raise ValueError("oversized_queued_message")
                        break
                    count += 1
                if not count:
                    return []
                token = values[2]
                self.strings[lease] = f"{token}:{count}"
            return [token, str(count), *self.lists[queue][:count]]
        if script == ChatCacheMixin._ACK_QUEUED_PREFIX_LUA:
            queue, lease, receipt, paused = keys
            token, count = values[:2]
            count = int(count)
            def clear_paused():
                record = self.strings.get(paused)
                if record and json.loads(record)["lease_token"] == token:
                    self.strings.pop(paused)
            if receipt in self.strings:
                clear_paused()
                return 1
            if self.strings.get(lease) != f"{token}:{count}":
                return 0
            if self.lists.get(queue, [])[:count] != list(values[2:]):
                return 0
            self.lists[queue] = self.lists[queue][count:]
            del self.strings[lease]
            self.strings[receipt] = "1"
            clear_paused()
            return 1
        if script == ChatCacheMixin._TRANSFER_ACTIVE_TASK_LUA:
            old, old_reverse, new_reverse = keys
            if self.strings.get(old) != values[0]:
                return 0
            self.strings[old] = values[1]
            self.strings.pop(old_reverse, None)
            self.strings[new_reverse] = values[3]
            return 1
        if script == ChatCacheMixin._ACTIVATE_COMPLETED_FOLLOWERS_LUA:
            active, old_reverse, new_reverse, paused, bytes_key, paused_bytes_key, lock_key = keys
            if self.strings.get(lock_key) != values[9]:
                return 0
            active_value = self.strings.get(active)
            if ((active_value != values[0] and not (values[8] == "1" and active_value is None))
                    or paused in self.strings):
                return 0
            self.strings[paused] = values[3]
            self.strings[active] = values[1]
            self.strings.pop(old_reverse, None)
            self.strings[new_reverse] = values[4]
            self.hashes.setdefault(bytes_key, {})[values[4]] = str(values[5])
            self.hashes.setdefault(paused_bytes_key, {})[values[4]] = str(values[6])
            return 1
        if script == ChatCacheMixin._STORE_PAUSED_QUEUE_HANDOFF_LUA:
            paused, active, bytes_key, paused_bytes_key, lock_key = keys
            if self.strings.get(lock_key) != values[7]:
                return 0
            if self.strings.get(active) != values[0] or paused in self.strings:
                return 0
            self.strings[paused] = values[1]
            self.hashes.setdefault(bytes_key, {})[values[3]] = str(values[4])
            self.hashes.setdefault(paused_bytes_key, {})[values[3]] = str(values[5])
            return 1
        if script == ChatCacheMixin._STORE_COMPLETED_QUEUE_CONTEXT_LUA:
            completed, active, bytes_key, completion_bytes_key, lock_key = keys
            if self.strings.get(lock_key) != values[8]:
                return 0
            if self.strings.get(active) != values[0]:
                return 0
            if self.strings.get(completed) != (values[1] or None):
                return 0
            self.strings[completed] = values[2]
            self.hashes.setdefault(bytes_key, {})[values[3]] = str(values[4])
            self.hashes.setdefault(completion_bytes_key, {})[values[3]] = str(values[5])
            return 1
        if script == ChatCacheMixin._AI_LRU_ADMIT_LUA:
            if self.strings.get(keys[0]) != values[0]:
                return 0
            for index, chat_id in enumerate(json.loads(values[4])):
                for key in keys[5 + index * 3:8 + index * 3]:
                    await self.delete(key)
                for key in keys[2:5]:
                    await self.hdel(key, chat_id)
                await self.zrem(keys[1], chat_id)
            await self.zadd(keys[1], {values[2]: values[1]})
            return 1
        if script == ChatCacheMixin._CLEAR_ACTIVE_IF_MATCHES_LUA:
            active, reverse = keys
            if self.strings.get(active) != values[0]:
                return 0
            self.strings.pop(active)
            self.strings.pop(reverse, None)
            return 1
        if script == ChatCacheMixin._COMPLETE_ACTIVE_IF_QUEUE_EMPTY_LUA:
            active, reverse, queue = keys
            if self.strings.get(active) != values[0]:
                return 2
            if self.lists.get(queue):
                return 0
            self.strings.pop(active, None)
            self.strings.pop(reverse, None)
            return 1
        raise AssertionError("Unexpected Redis script")

    async def get(self, key):
        value = self.strings.get(key)
        return value.encode() if isinstance(value, str) else value

    async def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.strings:
            return False
        self.strings[key] = value
        return True

    async def delete(self, key):
        self.strings.pop(key, None)
        self.lists.pop(key, None)

    def lock(self, name, **kwargs):
        return _AtomicLock(self, name)

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = str(value)

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)

    async def strlen(self, key):
        return len(self.strings.get(key, "").encode())

    async def exists(self, key):
        return key in self.strings or bool(self.lists.get(key))

    async def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def zrange(self, key, start, end):
        return list(self.zsets.get(key, {}))

    async def zscore(self, key, member):
        return self.zsets.get(key, {}).get(member)

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    async def zrem(self, key, member):
        self.zsets.get(key, {}).pop(member, None)

    async def smembers(self, key):
        return set()

    async def expire(self, key, ttl):
        return True


class _Cache(ChatCacheMixin):
    TOP_N_MESSAGES_COUNT = 3
    CHAT_MESSAGES_TTL = 3600

    def __init__(self):
        self.redis = _AtomicRedis()

    @property
    def client(self):
        async def get():
            return self.redis
        return get()


class _FakeVault:
    def __init__(self, *, cache_service):
        pass

    async def encrypt_with_user_key(self, plaintext, key_id):
        return "vault:v1:" + base64.b64encode(plaintext.encode()).decode(), "v1"

    async def decrypt_with_user_key(self, ciphertext, key_id):
        return base64.b64decode(ciphertext.removeprefix("vault:v1:")).decode()


def _member(message_id, content, *, user_id="owner", chat_id="chat"):
    return {
        "chat_id": chat_id,
        "message_id": message_id,
        "user_id": user_id,
        "user_id_hash": hashlib.sha256(user_id.encode()).hexdigest(),
        "is_incognito": False,
        "is_external": False,
        "is_anonymous": False,
        "team_id": None,
        "team_id_hash": None,
        "team_workspace_type": "chat",
        "team_object_id_hash": None,
        "message_history": [{"role": "user", "message_id": message_id,
                             "content": content, "created_at": 1}],
    }


def _request():
    return SimpleNamespace(**_member("old", "old content"),
                           legacy_cutover_task_id=None)


@pytest.mark.anyio
# contract-test: infrastructure
async def test_prefix_ack_preserves_concurrent_followers_and_retry_identity():
    cache = _Cache()
    for message_id in ("first", "second"):
        assert await cache.queue_message("chat", _member(message_id, message_id))
    lease = await cache.lease_queued_message_prefix("chat", limit=2)
    assert [item["message_id"] for item in lease["messages"]] == ["first", "second"]
    assert await cache.queue_message("chat", _member("later", "later"))
    retry = await cache.lease_queued_message_prefix("chat", limit=2)
    assert retry == lease
    queue_key = cache._get_chat_queue_key("chat")
    assert len(cache.redis.lists[queue_key]) == 3
    assert await cache.acknowledge_queued_message_prefix("chat", lease)
    assert [json.loads(item)["message_id"] for item in cache.redis.lists[queue_key]] == ["later"]
    assert await cache.acknowledge_queued_message_prefix("chat", lease)


@pytest.mark.anyio
# contract-test: infrastructure
async def test_prefix_ack_rejects_wrong_bytes_and_old_task_cannot_clear_new_marker():
    cache = _Cache()
    await cache.queue_message("chat", _member("first", "content"))
    lease = await cache.lease_queued_message_prefix("chat")
    bad = {**lease, "raw_messages": [lease["raw_messages"][0] + " "]}
    assert not await cache.acknowledge_queued_message_prefix("chat", bad)
    assert len(cache.redis.lists[cache._get_chat_queue_key("chat")]) == 1
    cache.redis.strings[cache._get_active_task_key("chat")] = "old"
    assert await cache.transfer_active_ai_task("chat", "old", "new")
    assert not await cache.clear_active_ai_task_if_matches("chat", "old")
    assert cache.redis.strings[cache._get_active_task_key("chat")] == "new"
    assert await cache.complete_active_ai_task_if_queue_empty("chat", "old") == 2
    assert await cache.complete_active_ai_task_if_queue_empty("chat", "new") == 0
    assert await cache.acknowledge_queued_message_prefix("chat", lease)
    assert await cache.complete_active_ai_task_if_queue_empty("chat", "new") == 1
    assert cache._get_active_task_key("chat") not in cache.redis.strings


@pytest.mark.anyio
# contract-test: infrastructure
async def test_vault_completion_context_is_measured_and_rejected_over_budget(monkeypatch):
    cache = _Cache()
    cache.redis.strings[cache._get_active_task_key("chat")] = "task-one"
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "180")
    monkeypatch.setenv("AI_USER_CONTEXT_MAX_BYTES", "180")
    assert await cache.store_completed_queue_context(
        "owner", "chat", "task-one", "vault-key", "vault:v1:sealed",
    )
    stored = cache.redis.strings[cache._get_completed_queue_context_key("chat")]
    assert json.loads(stored)["ciphertext"] == "vault:v1:sealed"
    assert int(cache.redis.hashes[cache._get_ai_cache_bytes_key("owner")]["chat"]) == len(stored.encode())
    assert await cache._ai_context_bytes(cache.redis, "owner", "chat") == len(stored.encode())
    cache.redis.strings[cache._get_active_task_key("chat")] = "task-two"
    with pytest.raises(RuntimeError, match="budget"):
        await cache.store_completed_queue_context(
            "owner", "chat", "task-two", "vault-key", "vault:v1:" + "x" * 200,
        )
    assert cache.redis.strings[cache._get_completed_queue_context_key("chat")] == stored


@pytest.mark.anyio
# contract-test: infrastructure
async def test_vault_paused_handoff_refuses_unmeasured_extra_context(monkeypatch):
    cache = _Cache()
    cache.redis.strings[cache._get_active_task_key("chat")] = "old-task"
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "128")
    sealed = {
        "task_id": "new-task", "lease_token": "lease",
        "vault_key_id": "user-key", "ciphertext": "vault:v1:" + "x" * 200,
    }
    with pytest.raises(RuntimeError, match="Vault ciphertext"):
        await cache.store_paused_queue_handoff(
            "owner", "chat", "old-task", {**sealed, "request_data_dict": {"content": "secret"}},
        )
    with pytest.raises(RuntimeError, match="budget"):
        await cache.store_paused_queue_handoff("owner", "chat", "old-task", sealed)
    assert await cache.get_paused_queue_handoff("chat") is None
    assert await cache.get_active_ai_task("chat") == "old-task"


@pytest.mark.anyio
# contract-test: infrastructure
async def test_legacy_batch_proof_is_exact_and_mixed_scope_fails(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    cache = _Cache()
    await cache.queue_message("chat", _member("one", "one"))
    await cache.queue_message("chat", _member("two", "two"))
    lease = await cache.lease_queued_message_prefix("chat", limit=20)
    request = _request()
    ids, contents = _validated_queued_messages(request, lease)
    assert ids == ["one", "two"] and contents == ["one", "two"]
    proof = _legacy_queued_batch_proof(request, lease, ids)
    request.message_id = "one"
    request.legacy_cutover_task_id = proof["task_identity"]
    assert _verify_legacy_batch_proof(proof, request, proof["celery_task_id"]) == proof
    altered = {**proof, "members": [*proof["members"]]}
    altered["members"][1] = {**altered["members"][1], "payload_commitment": "0" * 64}
    with pytest.raises(RequiredRecoveryOutputError):
        _verify_legacy_batch_proof(altered, request, proof["celery_task_id"])
    mixed = {**lease, "messages": [lease["messages"][0], _member("two", "two", user_id="other")]}
    with pytest.raises(RequiredRecoveryOutputError):
        _validated_queued_messages(_request(), mixed)


@pytest.mark.anyio
# contract-test: infrastructure
async def test_broker_failure_keeps_exact_batch_ahead_of_fresh_input(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setattr(ask_skill_task, "EncryptionService", _FakeVault)
    cache = _Cache()
    await cache.queue_message("chat", _member("first", "first"))
    lease = await cache.lease_queued_message_prefix("chat", limit=20)
    request = AskSkillRequest(**_member("first", "first"))
    proof = _legacy_queued_batch_proof(request, lease, ["first"])
    request.legacy_cutover_task_id = proof["task_identity"]
    request.root_user_message_id = "first"
    task_id = proof["celery_task_id"]
    handoff = {
        "task_id": task_id, "chat_id": "chat", "owner_id": "owner",
        "hashed_team_id": None, "request_data_dict": request.model_dump(),
        "skill_config_dict": {}, "legacy_batch_proof": proof,
        "lease": {"token": lease["token"], "raw_messages": lease["raw_messages"]},
    }
    cache.redis.strings[cache._get_active_task_key("chat")] = "old"
    sealed = await ask_skill_task._seal_legacy_queue_handoff(
        handoff, vault_key_id="test-user-key", cache_service=cache,
    )
    await cache.store_paused_queue_handoff("owner", "chat", "old", sealed)
    assert await cache.transfer_active_ai_task("chat", "old", task_id)

    calls = []

    class Recovery:
        def __init__(self, service):
            pass

        async def execute(self, operation, payload):
            calls.append((operation, payload["task_identity"]))
            return {
                "status": "PREPARED", "task_identity": proof["task_identity"],
                "execution_claimed": False,
            }

    broker_ids = []

    def send_task(*, task_id, **kwargs):
        broker_ids.append(task_id)
        if len(broker_ids) == 1:
            raise RuntimeError("broker unavailable")
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(ask_skill_task.celery_config.app, "send_task", send_task)
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await resume_legacy_queued_handoff(
            cache_service=cache, directus_service=object(), chat_id="chat",
            actor_user_id="owner", hashed_team_id=None,
        )
    assert await cache.queue_message("chat", _member("fresh", "fresh"))
    assert await cache.get_active_ai_task("chat") == task_id
    assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["first", "fresh"]
    with pytest.raises(RequiredRecoveryOutputError, match="scope"):
        await resume_legacy_queued_handoff(
            cache_service=cache, directus_service=object(), chat_id="chat",
            actor_user_id="other", hashed_team_id=None,
        )
    assert broker_ids == [task_id]
    resumed_id = await resume_legacy_queued_handoff(
        cache_service=cache, directus_service=object(), chat_id="chat",
        actor_user_id="owner", hashed_team_id=None,
    )
    assert resumed_id == task_id
    assert broker_ids == [task_id, task_id]
    assert [item[0] for item in calls] == ["prepare_legacy_batch", "prepare_legacy_batch"]
    assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["fresh"]
    assert await cache.get_paused_queue_handoff("chat") is None


@pytest.mark.anyio
@pytest.mark.parametrize("durable_status", ["CLAIMED", "COMPLETED"])
# contract-test: infrastructure
async def test_claimed_batch_reconciles_lost_prefix_ack_without_broker_replay(
    monkeypatch, durable_status,
):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setattr(ask_skill_task, "EncryptionService", _FakeVault)
    cache = _Cache()
    await cache.queue_message("chat", _member("first", "first"))
    lease = await cache.lease_queued_message_prefix("chat", limit=20)
    request = AskSkillRequest(**_member("first", "first"))
    proof = _legacy_queued_batch_proof(request, lease, ["first"])
    request.legacy_cutover_task_id = proof["task_identity"]
    request.root_user_message_id = "first"
    task_id = proof["celery_task_id"]
    handoff = {
        "task_id": task_id, "chat_id": "chat", "owner_id": "owner",
        "hashed_team_id": None, "request_data_dict": request.model_dump(),
        "skill_config_dict": {}, "legacy_batch_proof": proof,
        "lease": {"token": lease["token"], "raw_messages": lease["raw_messages"]},
    }
    cache.redis.strings[cache._get_active_task_key("chat")] = task_id
    sealed = await ask_skill_task._seal_legacy_queue_handoff(
        handoff, vault_key_id="test-user-key", cache_service=cache,
    )
    await cache.store_paused_queue_handoff("owner", "chat", task_id, sealed)
    paused_bytes = cache.redis.strings[cache._get_paused_queue_handoff_key("chat")]
    assert "request_data_dict" not in paused_bytes
    assert "first assistant response" not in paused_bytes
    if durable_status == "COMPLETED":
        completion_plaintext = {
            "task_id": task_id, "chat_id": "chat", "owner_id": "owner",
            "hashed_team_id": None, "request_data_dict": request.model_dump(),
            "skill_config_dict": {}, "legacy_batch_proof": proof,
            "assistant_response": "first assistant response",
        }
        completion_ciphertext, _ = await _FakeVault(cache_service=cache).encrypt_with_user_key(
            json.dumps(completion_plaintext), "test-user-key",
        )
        await cache.store_completed_queue_context(
            "owner", "chat", task_id, "test-user-key", completion_ciphertext,
        )
        completion_bytes = cache.redis.strings[cache._get_completed_queue_context_key("chat")]
        assert "first assistant response" not in completion_bytes
        assert await cache._ai_context_bytes(cache.redis, "owner", "chat") == (
            len(paused_bytes.encode()) + len(completion_bytes.encode())
        )

    class Recovery:
        calls = 0

        def __init__(self, service):
            pass

        async def execute(self, operation, payload):
            assert operation == "prepare_legacy_batch"
            if payload != proof:
                assert durable_status == "COMPLETED"
                assert payload["first_message_id"] == "follower"
                return {
                    "task_identity": payload["task_identity"],
                    "status": "PREPARED", "execution_claimed": False,
                }
            Recovery.calls += 1
            if Recovery.calls == 1:
                return {
                    "task_identity": proof["task_identity"],
                    "status": "PREPARED", "execution_claimed": False,
                }
            return {
                "task_identity": proof["task_identity"],
                "status": durable_status, "execution_claimed": True,
                "idempotent": Recovery.calls > 2,
            }

    broker_ids = []
    broker_kwargs = []

    def send_task(*, task_id, **kwargs):
        broker_ids.append(task_id)
        broker_kwargs.append(kwargs)
        return SimpleNamespace(id=task_id)

    original_ack = cache.acknowledge_queued_message_prefix
    ack_calls = 0

    async def lost_ack(chat_id, queued_lease):
        nonlocal ack_calls
        ack_calls += 1
        if ack_calls == 1:
            return False
        return await original_ack(chat_id, queued_lease)

    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(ask_skill_task.celery_config.app, "send_task", send_task)
    monkeypatch.setattr(cache, "acknowledge_queued_message_prefix", lost_ack)
    with pytest.raises(RequiredRecoveryOutputError, match="prefix ACK failed"):
        await resume_legacy_queued_handoff(
            cache_service=cache, directus_service=object(), chat_id="chat",
            actor_user_id="owner", hashed_team_id=None,
        )
    assert broker_ids == [task_id]
    await cache.queue_message("chat", _member("follower", "follower"))
    with pytest.raises(RequiredRecoveryOutputError, match="claim is unverified"):
        await resume_legacy_queued_handoff(
            cache_service=cache, directus_service=object(), chat_id="chat",
            actor_user_id="owner", hashed_team_id=None,
        )
    assert broker_ids == [task_id]
    assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["first", "follower"]
    if durable_status == "COMPLETED":
        original_activate = cache.activate_completed_queue_followers
        activation_calls = 0

        async def interrupted_activation(*args, **kwargs):
            nonlocal activation_calls
            activation_calls += 1
            if activation_calls == 1:
                raise RuntimeError("Redis transfer interrupted")
            return await original_activate(*args, **kwargs)

        monkeypatch.setattr(cache, "activate_completed_queue_followers", interrupted_activation)
        with pytest.raises(RuntimeError, match="transfer interrupted"):
            await resume_legacy_queued_handoff(
                cache_service=cache, directus_service=object(), chat_id="chat",
                actor_user_id="owner", hashed_team_id=None,
            )
        assert await cache.get_active_ai_task("chat") == task_id
        assert await cache.get_paused_queue_handoff("chat") is None
        assert broker_ids == [task_id]
        assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["follower"]
        # The old marker may expire before an authenticated retry. The durable
        # completed proof still allows exactly one atomic new follower owner.
        cache.redis.strings.pop(cache._get_active_task_key("chat"))
    resumed_id = await resume_legacy_queued_handoff(
        cache_service=cache, directus_service=object(), chat_id="chat",
        actor_user_id="owner", hashed_team_id=None,
    )
    assert Recovery.calls == (4 if durable_status == "COMPLETED" else 3)
    if durable_status == "COMPLETED":
        assert len(broker_ids) == 2 and broker_ids[0] == task_id
        assert broker_ids[1] != task_id
        assert resumed_id == broker_ids[1]
        next_request = broker_kwargs[1]["kwargs"]["request_data_dict"]
        assert next_request["message_id"] == "follower"
        assert any(
            item["role"] == "assistant" and item["content"] == "first assistant response"
            for item in next_request["message_history"]
        )
        assert cache.redis.lists[cache._get_chat_queue_key("chat")] == []
        assert await cache.get_active_ai_task("chat") == broker_ids[1]
    else:
        assert resumed_id == task_id
        assert broker_ids == [task_id]
        assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["follower"]
        assert await cache.get_active_ai_task("chat") == task_id
    assert await cache.get_paused_queue_handoff("chat") is None


@pytest.mark.anyio
# contract-test: infrastructure
async def test_ordinary_exact_broker_retry_reuses_binding_and_changed_config_holds(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    import backend.core.api.app.services.chat_recovery_service as recovery_module
    import backend.core.api.app.services.directus as directus_module

    task_id = hashlib.sha256(b"owner:chat:first").hexdigest()
    request = AskSkillRequest(**_member("first", "first"), legacy_cutover_task_id=task_id)
    skill = AskSkill.__new__(AskSkill)
    skill.parsed_default_config = None
    skill.celery_producer = object()
    skill.skill_name = "ask"
    bindings = []
    broker_ids = []

    class Directus:
        async def close(self):
            pass

    class Recovery:
        def __init__(self, service):
            pass

        async def execute(self, operation, data):
            assert operation == "bind_ordinary_legacy_dispatch"
            assert data["broker_task_id"] == task_id
            binding = data["dispatch_binding"]
            if bindings and binding != bindings[0]:
                raise ChatRecoveryProtocolError(409, "legacy_dispatch_binding_mismatch")
            bindings.append(binding)
            return {"bound": True, "idempotent": len(bindings) > 1,
                    "enqueue_allowed": True}

    def publish(*, task_id, **kwargs):
        broker_ids.append(task_id)
        if len(broker_ids) == 1:
            raise RuntimeError("broker unavailable")
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(directus_module, "DirectusService", Directus)
    monkeypatch.setattr(recovery_module, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", publish)
    monkeypatch.setattr(ask_skill_task, "notify_chat_failure", AsyncMock())
    import backend.apps.ai.skills.ask_skill as ask_module
    monkeypatch.setattr(ask_module, "notify_chat_failure", AsyncMock())

    with pytest.raises(Exception, match="Failed to initiate AI processing"):
        await skill._handle_internal_request(request)
    response = await skill._handle_internal_request(request)
    assert response.task_id == task_id
    assert len(bindings) == 2 and bindings[0] == bindings[1]
    assert broker_ids == [task_id, task_id]
    skill.parsed_default_config = SimpleNamespace(model_dump=lambda: {"changed": True})
    with pytest.raises(ChatRecoveryProtocolError):
        await skill._handle_internal_request(request)
    assert broker_ids == [task_id, task_id]
