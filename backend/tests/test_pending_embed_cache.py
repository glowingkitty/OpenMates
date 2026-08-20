"""
Infrastructure tests for pending embed cache retention.

Pending client-encryption records and their recoverable embed payload must share
the same retention window so bounded safety-net batches cannot lose later work.
The tests use a minimal async Redis pipeline fake and perform no network I/O.
"""

import pytest

from backend.core.api.app.services.cache_reminder_mixin import (
    EMBED_CACHE_EXTENDED_TTL,
    PENDING_EMBED_KEY_PREFIX,
    PENDING_EMBED_TTL,
    ReminderCacheMixin,
)
from backend.core.api.app.services.embed_service import (
    EMBED_CACHE_TTL_SECONDS,
    EmbedService,
)


class FakePipeline:
    def __init__(self) -> None:
        self.operations: list[tuple] = []

    def zadd(self, key: str, values: dict[str, float]):
        self.operations.append(("zadd", key, values))
        return self

    def expire(self, key: str, ttl: int):
        self.operations.append(("expire", key, ttl))
        return self

    async def execute(self) -> list[bool]:
        return [True] * len(self.operations)


class FakeRedis:
    def __init__(self) -> None:
        self.pipeline_instance = FakePipeline()
        self.set_calls: list[tuple] = []

    async def set(self, key: str, value: str, **kwargs) -> None:
        self.set_calls.append((key, kwargs))

    async def sadd(self, key: str, value: str) -> None:
        return None

    async def expire(self, key: str, ttl: int) -> None:
        return None

    def pipeline(self, transaction: bool) -> FakePipeline:
        assert transaction is True
        return self.pipeline_instance


class CacheHarness(ReminderCacheMixin):
    def __init__(self) -> None:
        self.redis = FakeRedis()

    @property
    def client(self):
        async def get_client():
            return self.redis

        return get_client()


class EmbedCacheHarness:
    def __init__(self) -> None:
        self.redis = FakeRedis()

    @property
    def client(self):
        async def get_client():
            return self.redis

        return get_client()


@pytest.mark.anyio
# contract-test: infrastructure
async def test_pending_embed_tracking_extends_payload_to_full_pending_ttl() -> None:
    cache = CacheHarness()

    assert await cache.add_pending_embed("user-1", "embed-1") is True

    operations = cache.redis.pipeline_instance.operations
    assert operations[0][0:2] == (
        "zadd",
        f"{PENDING_EMBED_KEY_PREFIX}user-1",
    )
    assert operations[1] == (
        "expire",
        f"{PENDING_EMBED_KEY_PREFIX}user-1",
        PENDING_EMBED_TTL,
    )
    assert operations[2] == (
        "expire",
        "embed:embed-1",
        EMBED_CACHE_EXTENDED_TTL,
    )
    assert EMBED_CACHE_EXTENDED_TTL == PENDING_EMBED_TTL


@pytest.mark.anyio
# contract-test: infrastructure
async def test_finished_embed_cache_starts_with_full_pending_retention() -> None:
    service = EmbedService.__new__(EmbedService)
    service.cache_service = EmbedCacheHarness()

    await service._cache_embed(
        "embed-1",
        {"status": "finished", "encrypted_content": "ciphertext"},
        "chat-1",
        "user-hash",
        "vault-key",
        "user-1",
    )

    assert service.cache_service.redis.set_calls == [
        ("embed:embed-1", {"ex": EMBED_CACHE_EXTENDED_TTL})
    ]


@pytest.mark.anyio
# contract-test: infrastructure
async def test_processing_embed_cache_keeps_standard_retention() -> None:
    service = EmbedService.__new__(EmbedService)
    service.cache_service = EmbedCacheHarness()

    await service._cache_embed(
        "embed-1",
        {"status": "processing", "encrypted_content": "ciphertext"},
        "chat-1",
        "user-hash",
        "vault-key",
        "user-1",
    )

    assert service.cache_service.redis.set_calls == [
        ("embed:embed-1", {"ex": EMBED_CACHE_TTL_SECONDS})
    ]
