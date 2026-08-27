# backend/tests/test_draft_version_atomicity.py
# Regression coverage for monotonic draft versions across concurrent updates.
# Draft writes and deletion tombstones share one atomic counter so stale content
# cannot reuse a version after message-send cleanup or dedicated-key expiry.
# The test models Redis script execution under concurrent callers.

import asyncio
import pytest

from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin


class _AtomicRedis:
    def __init__(self) -> None:
        self.values = {"versions:user-1:chat-1:user_draft_v:user-1": 5}
        self.lock = asyncio.Lock()
        self.eval_calls = 0

    async def eval(self, script, _key_count, draft_key, versions_key, field, *arguments):
        async with self.lock:
            self.eval_calls += 1
            def parse_version(value):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    if ") or 0" in script:
                        return 0
                    raise

            dedicated = parse_version(self.values.get(f"{draft_key}:draft_v", 0))
            general = parse_version(self.values.get(f"{versions_key}:{field}", 0))
            is_update = "local incoming_version" in script
            if is_update:
                incoming_version = int(arguments[0])
                deleted = self.values.get(f"{draft_key}:deleted")
                if dedicated > incoming_version or general > incoming_version:
                    return 0
                if deleted == "true" and dedicated >= incoming_version:
                    return 0
                self.values[f"{draft_key}:draft_v"] = incoming_version
                self.values[f"{draft_key}:encrypted_draft_md"] = arguments[1]
                self.values[f"{draft_key}:deleted"] = "false"
                self.values[f"{versions_key}:{field}"] = incoming_version
                return 1

            is_conditional_tombstone = "local tombstone_version" in script
            if is_conditional_tombstone:
                tombstone_version = int(arguments[0])
                if dedicated > tombstone_version or general > tombstone_version:
                    return 0
                self.values[f"{draft_key}:draft_v"] = tombstone_version
                self.values[f"{draft_key}:deleted"] = "true"
                self.values[f"{versions_key}:{field}"] = tombstone_version
                return 1

            is_tombstone = "'deleted', 'true'" in script
            increment = 1 if is_tombstone else int(arguments[0])
            next_version = max(dedicated, general) + increment
            self.values[f"{versions_key}:{field}"] = next_version
            if is_tombstone:
                self.values[f"{draft_key}:draft_v"] = next_version
                self.values[f"{draft_key}:deleted"] = "true"
            return next_version


class _Cache(ChatCacheMixin):
    USER_DRAFT_TTL = 60
    CHAT_VERSIONS_TTL = 120

    def __init__(self, client: _AtomicRedis) -> None:
        self._client = client

    @property
    def client(self):
        async def resolve():
            return self._client

        return resolve()

    def _get_chat_versions_key(self, user_id: str, chat_id: str) -> str:
        return f"versions:{user_id}:{chat_id}"


class _LegacyCacheBase:
    _UPDATE_DRAFT_IF_CURRENT_LUA = "legacy one-key draft script"


class _ConcreteCache(_LegacyCacheBase, _Cache):
    pass


# contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_concrete_cache_service_uses_version_authoritative_draft_script() -> None:
    redis = _AtomicRedis()
    cache = _ConcreteCache(redis)

    write_result = await cache.update_user_draft_in_cache(
        "user-1",
        "chat-1",
        "encrypted-draft",
        6,
        "encrypted-preview",
    )

    assert write_result is True
    assert redis.values["user:user-1:chat:chat-1:draft:draft_v"] == 6
    assert redis.values["versions:user-1:chat-1:user_draft_v:user-1"] == 6


# contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_concurrent_draft_version_increments_remain_monotonic() -> None:
    redis = _AtomicRedis()
    cache = _Cache(redis)

    versions = await asyncio.gather(
        cache.increment_user_draft_version("user-1", "chat-1"),
        cache.increment_user_draft_version("user-1", "chat-1"),
    )

    assert sorted(versions) == [6, 7]
    assert "user:user-1:chat:chat-1:draft:draft_v" not in redis.values
    assert redis.values["versions:user-1:chat-1:user_draft_v:user-1"] == 7
    assert redis.eval_calls == 2

    redis.values["user:user-1:chat:chat-2:draft:draft_v"] = "null"
    redis.values["versions:user-1:chat-2:user_draft_v:user-1"] = "null"

    assert await cache.increment_user_draft_version("user-1", "chat-2") == 1


# contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_message_send_tombstone_reserves_and_deletes_in_one_operation() -> None:
    redis = _AtomicRedis()
    cache = _Cache(redis)

    deleted_version = await cache.increment_and_tombstone_user_draft("user-1", "chat-1")

    assert deleted_version == 6
    assert redis.values["user:user-1:chat:chat-1:draft:draft_v"] == 6
    assert redis.values["user:user-1:chat:chat-1:draft:deleted"] == "true"
    assert redis.values["versions:user-1:chat-1:user_draft_v:user-1"] == 6


# contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_delayed_draft_write_cannot_replace_message_send_tombstone() -> None:
    redis = _AtomicRedis()
    cache = _Cache(redis)

    reserved_draft_v = await cache.increment_user_draft_version("user-1", "chat-1")
    deleted_draft_v = await cache.increment_and_tombstone_user_draft("user-1", "chat-1")
    write_result = await cache.update_user_draft_in_cache(
        "user-1",
        "chat-1",
        "stale-encrypted-draft",
        reserved_draft_v,
        "stale-encrypted-preview",
    )

    assert write_result is False
    assert reserved_draft_v == 6
    assert deleted_draft_v == 7
    assert redis.values["user:user-1:chat:chat-1:draft:draft_v"] == 7
    assert redis.values["user:user-1:chat:chat-1:draft:deleted"] == "true"
    assert redis.values["versions:user-1:chat-1:user_draft_v:user-1"] == 7


# contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_draft_cache_update_reports_cache_failure_separately_from_superseded_write() -> None:
    class BrokenRedis:
        async def eval(self, *_args):
            raise RuntimeError("redis unavailable")

    cache = _Cache(BrokenRedis())

    write_result = await cache.update_user_draft_in_cache(
        "user-1",
        "chat-1",
        "encrypted-draft",
        6,
        "encrypted-preview",
    )

    assert write_result is None


# contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_newer_reserved_draft_can_replace_older_tombstone() -> None:
    redis = _AtomicRedis()
    cache = _Cache(redis)

    deleted_draft_v = await cache.increment_and_tombstone_user_draft("user-1", "chat-1")
    reserved_draft_v = await cache.increment_user_draft_version("user-1", "chat-1")
    write_result = await cache.update_user_draft_in_cache(
        "user-1",
        "chat-1",
        "new-encrypted-draft",
        reserved_draft_v,
        "new-encrypted-preview",
    )

    assert write_result is True
    assert deleted_draft_v == 6
    assert reserved_draft_v == 7
    assert redis.values["user:user-1:chat:chat-1:draft:draft_v"] == 7
    assert redis.values["user:user-1:chat:chat-1:draft:deleted"] == "false"
    assert redis.values["user:user-1:chat:chat-1:draft:encrypted_draft_md"] == "new-encrypted-draft"


# contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_delayed_explicit_tombstone_cannot_clear_newer_reserved_draft() -> None:
    redis = _AtomicRedis()
    cache = _Cache(redis)

    delayed_delete_v = await cache.increment_user_draft_version("user-1", "chat-1")
    newer_draft_v = await cache.increment_user_draft_version("user-1", "chat-1")
    delete_result = await cache.tombstone_user_draft_in_cache(
        "user-1",
        "chat-1",
        delayed_delete_v,
    )
    write_result = await cache.update_user_draft_in_cache(
        "user-1",
        "chat-1",
        "newer-encrypted-draft",
        newer_draft_v,
        "newer-encrypted-preview",
    )

    assert delete_result is False
    assert write_result is True
    assert delayed_delete_v == 6
    assert newer_draft_v == 7
    assert redis.values["user:user-1:chat:chat-1:draft:draft_v"] == 7
    assert redis.values["user:user-1:chat:chat-1:draft:deleted"] == "false"
