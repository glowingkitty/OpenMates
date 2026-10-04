"""AI working-cache admission tests; no Redis service or inference required."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin
from backend.core.api.app.services.cache_reminder_mixin import PENDING_EMBED_KEY_PREFIX


class FakeLock:
    def __init__(self, name):
        self.name = name
        self.local = SimpleNamespace(token=b"test-lock")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def extend(self, *_args, **_kwargs):
        return True

    async def owned(self):
        return True


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.zsets = {}
        self.hashes = {}
        self.sets = {}
        self.strings = {}
        self.deleted = []

    def lock(self, name, **kwargs):
        return FakeLock(name)

    async def eval(self, script, key_count, *values):
        keys, args = values[:key_count], values[key_count:]
        if script == ChatCacheMixin._AI_EMBED_COMMIT_LUA:
            await self.sadd(keys[1], args[1])
            await self.set(keys[2], args[3])
            return 1
        if script == ChatCacheMixin._AI_CHILD_REGISTER_LUA:
            await self.zadd(keys[1], {args[2]: args[1]})
            await self.zrem(keys[2], args[2])
            return 1
        if script == ChatCacheMixin._AI_CHILD_RELEASE_LUA:
            for key in keys[1:4]:
                await self.delete(key)
            for key in keys[4:7]:
                await self.hdel(key, args[1])
            await self.zrem(keys[7], args[1])
            return 1
        if script == ChatCacheMixin._AI_LRU_ADMIT_LUA:
            import json
            for index, chat_id in enumerate(json.loads(args[4])):
                for key in keys[5 + index * 3:8 + index * 3]:
                    await self.delete(key)
                for key in keys[2:5]:
                    await self.hdel(key, chat_id)
                await self.zrem(keys[1], chat_id)
            await self.zadd(keys[1], {args[2]: args[1]})
            return 1
        if script == ChatCacheMixin._AI_MESSAGE_COMMIT_LUA:
            if args[1] == "replace":
                await self.delete(keys[1])
                if len(args) > 10:
                    await self.rpush(keys[1], *args[10:])
            else:
                await self.lpush(keys[1], args[10])
                if args[4] > 0:
                    await self.ltrim(keys[1], 0, args[4] - 1)
            await self.hset(keys[2], args[2], args[5])
            await self.hset(keys[3], args[2], args[6])
            await self.hset(keys[4], args[2], args[7])
            return 1
        raise AssertionError("Unexpected Redis script")

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start:end + 1]

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value.encode())

    async def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(value.encode() for value in values)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:end + 1]

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    async def zscore(self, key, member):
        return self.zsets.get(key, {}).get(member)

    async def zcard(self, key):
        return len(self.zsets.get(key, {}))

    async def zrange(self, key, start, end):
        entries = self.zsets.get(key, {})
        values = sorted(entries, key=entries.get)
        return values[start:] if end == -1 else values[start:end + 1]

    async def zrem(self, key, member):
        self.zsets.get(key, {}).pop(member, None)

    async def smembers(self, key):
        return self.sets.get(key, set())

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def strlen(self, key):
        return len(self.strings.get(key, ""))

    async def get(self, key):
        return self.strings.get(key)

    async def set(self, key, value, **kwargs):
        self.strings[key] = value

    async def exists(self, key):
        return int(key in self.strings or key in self.lists)

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        self.deleted.append(key)
        self.lists.pop(key, None)
        self.sets.pop(key, None)
        self.strings.pop(key, None)


class Cache(ChatCacheMixin):
    CHAT_MESSAGES_TTL = 259200
    TOP_N_MESSAGES_COUNT = 3

    def __init__(self):
        self.redis = FakeRedis()

    @property
    def client(self):
        async def value():
            return self.redis
        return value()


@pytest.mark.anyio
# contract-test: infrastructure
async def test_children_do_not_consume_three_main_chat_slots(monkeypatch):
    monkeypatch.setenv("AI_ACTIVE_CHILD_CONTEXT_MAX_COUNT", "2")
    cache = Cache()
    for chat_id in ("main-1", "main-2", "main-3"):
        assert await cache.add_ai_message_to_history("user", chat_id, "encrypted")
    assert await cache.register_active_ai_child_context("user", "child-1")
    assert await cache.add_ai_message_to_history("user", "child-1", "encrypted")
    assert await cache.register_active_ai_child_context("user", "child-2")
    assert await cache.register_active_ai_child_context("user", "child-3") is False

    assert set(cache.redis.zsets[cache._get_ai_cache_lru_key("user")]) == {"main-1", "main-2", "main-3"}
    assert set(cache.redis.zsets[cache._get_active_ai_children_key("user")]) == {"child-1", "child-2"}
    assert all(cache._get_ai_messages_key("user", chat_id) in cache.redis.lists for chat_id in ("main-1", "main-2", "main-3"))


@pytest.mark.anyio
# contract-test: infrastructure
async def test_byte_admission_preserves_existing_context(monkeypatch):
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "8")
    monkeypatch.setenv("AI_ACTIVE_CHILD_CONTEXT_MAX_BYTES", "12")
    cache = Cache()
    assert await cache.register_active_ai_child_context("user", "child-1")
    assert await cache.add_ai_message_to_history("user", "child-1", "12345678")
    assert await cache.add_ai_message_to_history("user", "child-1", "9") is False
    assert await cache.get_ai_messages_history("user", "child-1") == ["12345678"]

    assert await cache.register_active_ai_child_context("user", "child-2")
    assert await cache.set_ai_messages_history("user", "child-2", ["12345"]) is False
    assert await cache.get_ai_messages_history("user", "child-2") == []


@pytest.mark.anyio
# contract-test: infrastructure
async def test_main_admission_never_evicts_active_or_pending_output():
    cache = Cache()
    for chat_id in ("active", "pending", "third"):
        assert await cache.add_ai_message_to_history("user", chat_id, "cipher")
    cache.redis.strings[cache._get_active_task_key("active")] = "task"
    assert await cache.mark_ai_context_pending_persistence("user", "active")
    cache.redis.sets["chat:pending:embed_ids"] = {"embed-pending"}
    cache.redis.zsets[f"{PENDING_EMBED_KEY_PREFIX}user"] = {"embed-pending": 1.0}

    assert await cache.add_ai_message_to_history("user", "new-main", "cipher")
    assert cache._get_ai_messages_key("user", "active") in cache.redis.lists
    assert cache._get_ai_messages_key("user", "pending") in cache.redis.lists
    assert cache._get_ai_messages_key("user", "third") not in cache.redis.lists
    assert "embed:embed-pending" not in cache.redis.deleted

    cache.redis.strings[cache._get_active_task_key("new-main")] = "task-2"
    assert await cache.add_ai_message_to_history("user", "blocked-main", "cipher") is False
    assert cache._get_ai_messages_key("user", "blocked-main") not in cache.redis.lists
    cache.redis.strings.pop(cache._get_active_task_key("active"))
    assert await cache.add_ai_message_to_history("user", "blocked-main", "cipher") is False
    assert await cache.acknowledge_ai_context_persistence("user", "active")
    assert await cache.add_ai_message_to_history("user", "blocked-main", "cipher")


@pytest.mark.anyio
# contract-test: infrastructure
async def test_child_registration_moves_legacy_context_out_of_main_lru():
    cache = Cache()
    assert await cache.add_ai_message_to_history("user", "child", "cipher")
    assert await cache.register_active_ai_child_context("user", "child")
    assert "child" not in cache.redis.zsets[cache._get_ai_cache_lru_key("user")]
    assert await cache.release_active_ai_child_context("user", "child")
    assert "child" not in cache.redis.zsets[cache._get_active_ai_children_key("user")]
    assert cache._get_ai_messages_key("user", "child") not in cache.redis.lists


@pytest.mark.anyio
# contract-test: infrastructure
async def test_required_embed_byte_budget_counts_pending_payloads(monkeypatch):
    monkeypatch.setenv("AI_REQUIRED_EMBED_MAX_BYTES", "10")
    cache = Cache()
    cache.redis.strings["embed:pending"] = "123456"
    cache.redis.zsets[f"{PENDING_EMBED_KEY_PREFIX}user"] = {"pending": 1.0}

    assert await cache.cache_required_ai_embed("user", "child", "new", "12345", payload_ttl=100, index_ttl=100) is False
    assert "embed:new" not in cache.redis.strings
    assert await cache.cache_required_ai_embed("user", "child", "new", "1234", payload_ttl=100, index_ttl=100)
    assert cache.redis.strings["embed:new"] == "1234"
    assert "new" in cache.redis.sets["chat:child:embed_ids"]


@pytest.mark.anyio
# contract-test: infrastructure
async def test_later_main_and_child_writes_share_user_byte_cap(monkeypatch):
    monkeypatch.setenv("AI_USER_CONTEXT_MAX_BYTES", "16")
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "20")
    monkeypatch.setenv("AI_MAIN_CONTEXT_MAX_BYTES", "40")
    monkeypatch.setenv("AI_ACTIVE_CHILD_CONTEXT_MAX_BYTES", "40")
    cache = Cache()
    assert await cache.register_active_ai_child_context("user", "child")
    assert await cache.add_ai_message_to_history("user", "child", "12345678")
    assert await cache.add_ai_message_to_history("user", "main", "abcdefgh")
    assert await cache.add_ai_message_to_history("user", "main", "extra") is False
    assert await cache.add_ai_message_to_history("user", "child", "extra") is False
    assert await cache.get_ai_messages_history("user", "main") == ["abcdefgh"]
    assert await cache.get_ai_messages_history("user", "child") == ["12345678"]
    assert cache.redis.deleted == []


@pytest.mark.anyio
# contract-test: infrastructure
async def test_child_registration_refuses_preexisting_context_over_user_cap(monkeypatch):
    monkeypatch.setenv("AI_USER_CONTEXT_MAX_BYTES", "16")
    cache = Cache()
    assert await cache.add_ai_message_to_history("user", "main", "123456789012")
    child_key = cache._get_ai_messages_key("user", "child")
    cache.redis.lists[child_key] = [b"12345678"]  # Legacy pre-registration cache.
    assert await cache.register_active_ai_child_context("user", "child") is False
    assert child_key in cache.redis.lists
    assert "child" not in cache.redis.zsets.get(cache._get_active_ai_children_key("user"), {})
    assert await cache.get_ai_messages_history("user", "main") == ["123456789012"]


@pytest.mark.anyio
# contract-test: infrastructure
async def test_protected_main_contexts_are_not_partially_evicted_on_user_cap_refusal(monkeypatch):
    monkeypatch.setenv("AI_USER_CONTEXT_MAX_BYTES", "20")
    monkeypatch.setenv("AI_MAIN_CONTEXT_MAX_BYTES", "40")
    cache = Cache()
    assert await cache.add_ai_message_to_history("user", "pending", "12345678")
    assert await cache.add_ai_message_to_history("user", "active", "abcdefgh")
    assert await cache.register_active_ai_child_context("user", "child")
    assert await cache.add_ai_message_to_history("user", "child", "1234")
    assert await cache.mark_ai_context_pending_persistence("user", "pending")
    cache.redis.strings[cache._get_active_task_key("active")] = "running"
    before = {key: list(value) for key, value in cache.redis.lists.items()}
    assert await cache.add_ai_message_to_history("user", "new-main", "x") is False
    assert cache.redis.lists == before
    assert cache.redis.deleted == []


@pytest.mark.anyio
# contract-test: infrastructure
async def test_expired_auxiliary_bytes_are_removed_from_user_measurement():
    cache = Cache()
    key = cache._get_ai_messages_key("user", "main")
    cache.redis.lists[key] = [b"1234"]
    cache.redis.hashes[cache._get_ai_cache_bytes_key("user")] = {"main": 14}
    cache.redis.hashes[cache._get_ai_queue_completion_bytes_key("user")] = {"main": 10}
    assert await cache._ai_context_bytes(cache.redis, "user", "main") == 4
    # Reading the expired ciphertext does not race a newer writer's byte ledger.
    assert cache.redis.hashes[cache._get_ai_cache_bytes_key("user")]["main"] == 14
    assert cache.redis.hashes[cache._get_ai_queue_completion_bytes_key("user")]["main"] == 10


class ExpiringFakeLock(FakeLock):
    def __init__(self, store, name, timeout):
        super().__init__(name)
        self.store = store
        self.timeout = timeout
        self.local.token = str(store.next_token()).encode()

    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        while True:
            owner, expires = self.store.owners.get(self.name, (None, 0))
            if owner is None or expires <= loop.time():
                self.store.owners[self.name] = (self.local.token, loop.time() + self.timeout)
                return self
            await asyncio.sleep(0.002)

    async def __aexit__(self, *_):
        if await self.owned():
            self.store.owners.pop(self.name, None)

    async def extend(self, timeout, *, replace_ttl=False):
        if self.store.fail_next_renew:
            self.store.fail_next_renew = False
            return False
        if not await self.owned():
            return False
        self.store.owners[self.name] = (self.local.token, asyncio.get_running_loop().time() + timeout)
        return True

    async def owned(self):
        token, expires = self.store.owners.get(self.name, (None, 0))
        return token == self.local.token and expires > asyncio.get_running_loop().time()


class ExpiringFakeRedis(FakeRedis):
    def __init__(self):
        super().__init__()
        self.owners = {}
        self.serial = 0
        self.commit_entered = asyncio.Event()
        self.allow_first_commit = asyncio.Event()
        self.pause_first_commit = False
        self.fail_next_renew = False
        self.pause_ai_read = False
        self.ai_read_entered = asyncio.Event()
        self.allow_ai_read = asyncio.Event()

    def next_token(self):
        self.serial += 1
        return self.serial

    def lock(self, name, **kwargs):
        return ExpiringFakeLock(self, name, kwargs["timeout"])

    async def lrange(self, key, start, end):
        if self.pause_ai_read and key.endswith(":messages:ai"):
            self.pause_ai_read = False
            self.ai_read_entered.set()
            await self.allow_ai_read.wait()
        return await super().lrange(key, start, end)

    async def eval(self, script, key_count, *values):
        keys, args = values[:key_count], values[key_count:]
        if (self.pause_first_commit and script == ChatCacheMixin._AI_MESSAGE_COMMIT_LUA
                and args[2] == "child-a"):
            self.pause_first_commit = False
            self.commit_entered.set()
            await self.allow_first_commit.wait()
        token, expires = self.owners.get(keys[0], (None, 0))
        if token != args[0] or expires <= asyncio.get_running_loop().time():
            return 0
        return await super().eval(script, key_count, *values)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
# contract-test: infrastructure
async def test_expired_writer_cannot_commit_over_user_cap_after_other_child_acquires(monkeypatch):
    monkeypatch.setenv("AI_USER_CONTEXT_MAX_BYTES", "12")
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "16")
    monkeypatch.setenv("AI_ACTIVE_CHILD_CONTEXT_MAX_BYTES", "16")
    cache = Cache()
    cache.redis = ExpiringFakeRedis()
    cache.AI_CACHE_ADMISSION_LOCK_SECONDS = 0.04
    cache.AI_CACHE_ADMISSION_RENEW_SECONDS = 0.2  # Force token expiry at the commit boundary.
    for child in ("child-a", "child-b"):
        assert await cache.register_active_ai_child_context("user", child)
    cache.redis.pause_first_commit = True
    stale = asyncio.create_task(cache.add_ai_message_to_history("user", "child-a", "12345678"))
    await asyncio.wait_for(cache.redis.commit_entered.wait(), 1)
    current = asyncio.create_task(cache.add_ai_message_to_history("user", "child-b", "abcdefgh"))
    assert await asyncio.wait_for(current, 1)
    cache.redis.allow_first_commit.set()
    assert await asyncio.wait_for(stale, 1) is False
    assert await cache.get_ai_messages_history("user", "child-a") == []
    assert await cache.get_ai_messages_history("user", "child-b") == ["abcdefgh"]


@pytest.mark.anyio
# contract-test: infrastructure
async def test_renewed_user_lock_serializes_two_child_writers_at_limit(monkeypatch):
    monkeypatch.setenv("AI_USER_CONTEXT_MAX_BYTES", "12")
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "16")
    monkeypatch.setenv("AI_ACTIVE_CHILD_CONTEXT_MAX_BYTES", "16")
    cache = Cache()
    cache.redis = ExpiringFakeRedis()
    cache.AI_CACHE_ADMISSION_LOCK_SECONDS = 0.04
    cache.AI_CACHE_ADMISSION_RENEW_SECONDS = 0.01
    for child in ("child-a", "child-b"):
        assert await cache.register_active_ai_child_context("user", child)
    cache.redis.pause_first_commit = True
    first = asyncio.create_task(cache.add_ai_message_to_history("user", "child-a", "12345678"))
    await asyncio.wait_for(cache.redis.commit_entered.wait(), 1)
    second = asyncio.create_task(cache.add_ai_message_to_history("user", "child-b", "abcdefgh"))
    await asyncio.sleep(0.08)  # Longer than the initial lease; renewal must keep ownership.
    assert not second.done()
    cache.redis.allow_first_commit.set()
    assert await asyncio.wait_for(first, 1)
    assert await asyncio.wait_for(second, 1) is False
    assert await cache.get_ai_messages_history("user", "child-a") == ["12345678"]
    assert await cache.get_ai_messages_history("user", "child-b") == []


@pytest.mark.anyio
# contract-test: infrastructure
async def test_client_history_recache_uses_same_user_admission(monkeypatch):
    monkeypatch.setenv("AI_USER_CONTEXT_MAX_BYTES", "12")
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "16")
    cache = Cache()
    assert await cache.register_active_ai_child_context("user", "child")
    assert await cache.add_ai_message_to_history("user", "child", "12345678")
    assert await cache.add_message_to_chat_history("user", "main", "abcdefgh") is False
    assert await cache.get_ai_messages_history("user", "main") == []
    assert await cache.get_ai_messages_history("user", "child") == ["12345678"]


@pytest.mark.anyio
# contract-test: infrastructure
async def test_renewal_loss_returns_false_without_stale_message_commit():
    cache = Cache()
    cache.redis = ExpiringFakeRedis()
    cache.AI_CACHE_ADMISSION_LOCK_SECONDS = 0.04
    cache.AI_CACHE_ADMISSION_RENEW_SECONDS = 0.01
    cache.redis.pause_first_commit = True
    cache.redis.fail_next_renew = True
    writer = asyncio.create_task(cache.add_ai_message_to_history("user", "child-a", "cipher"))
    await asyncio.wait_for(cache.redis.commit_entered.wait(), 1)
    assert await asyncio.wait_for(writer, 1) is False
    assert writer.cancelling() == 0
    assert await cache.get_ai_messages_history("user", "child-a") == []


@pytest.mark.anyio
# contract-test: infrastructure
async def test_renewal_loss_raises_visible_queue_admission_error():
    cache = Cache()
    cache.redis = ExpiringFakeRedis()
    cache.AI_CACHE_ADMISSION_LOCK_SECONDS = 0.04
    cache.AI_CACHE_ADMISSION_RENEW_SECONDS = 0.01
    cache.redis.pause_ai_read = True
    cache.redis.fail_next_renew = True
    cache.redis.strings[cache._get_active_task_key("main")] = "task"
    sealed = {
        "task_id": "task", "lease_token": "lease", "vault_key_id": "key",
        "ciphertext": "vault:v1:cipher",
    }
    writer = asyncio.create_task(cache.store_paused_queue_handoff("user", "main", "task", sealed))
    await asyncio.wait_for(cache.redis.ai_read_entered.wait(), 1)
    with pytest.raises(RuntimeError, match="AI cache admission lock expired"):
        await asyncio.wait_for(writer, 1)
    assert writer.cancelling() == 0
    assert cache._get_paused_queue_handoff_key("main") not in cache.redis.strings


@pytest.mark.anyio
# contract-test: infrastructure
async def test_external_cancellation_still_propagates():
    cache = Cache()
    cache.redis = ExpiringFakeRedis()
    cache.AI_CACHE_ADMISSION_LOCK_SECONDS = 0.04
    cache.AI_CACHE_ADMISSION_RENEW_SECONDS = 0.2
    cache.redis.pause_ai_read = True
    writer = asyncio.create_task(cache.add_ai_message_to_history("user", "child-a", "cipher"))
    await asyncio.wait_for(cache.redis.ai_read_entered.wait(), 1)
    writer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await writer
    assert await cache.get_ai_messages_history("user", "child-a") == []
