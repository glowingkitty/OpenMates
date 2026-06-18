"""Regression tests for versioned embed update publication.

Diff edits update an already-finished embed in place. Normal finished updates are
deduplicated, but versioned updates must deliberately publish `send_embed_data`
again so web, CLI, and Apple clients encrypt and persist the latest snapshot.
"""

import json
import sys
import types

import pytest

redis_stub = types.ModuleType("redis")
redis_asyncio_stub = types.ModuleType("redis.asyncio")
redis_exceptions_stub = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception)
redis_asyncio_stub.Redis = object
redis_stub.asyncio = redis_asyncio_stub
redis_stub.exceptions = redis_exceptions_stub
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

cache_module_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_module_stub.CacheService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_module_stub)

directus_module_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_module_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus", directus_module_stub)

toon_stub = types.ModuleType("toon_format")
toon_stub.encode = lambda value: json.dumps(value)
toon_stub.decode = lambda value: json.loads(value)
sys.modules.setdefault("toon_format", toon_stub)

youtube_stub = types.ModuleType("backend.shared.providers.youtube.youtube_metadata")
youtube_stub.extract_youtube_id_from_url = lambda url: None
sys.modules.setdefault("backend.shared.providers.youtube.youtube_metadata", youtube_stub)

github_stub = types.ModuleType("backend.shared.providers.github")
github_stub.build_github_repo_embed = lambda url: None
github_stub.is_github_repo_url = lambda url: isinstance(url, str) and url.rstrip("/").count("/") == 4 and url.startswith("https://github.com/")
sys.modules.setdefault("backend.shared.providers.github", github_stub)

e2b_preview_stub = types.ModuleType("backend.shared.providers.e2b_application_preview")
e2b_preview_stub.ApplicationPreviewEntrypoint = object
e2b_preview_stub.ApplicationPreviewFile = object
e2b_preview_stub.ApplicationPreviewPlanningError = Exception
e2b_preview_stub.plan_application_preview_startup = lambda *args, **kwargs: None
sys.modules.setdefault("backend.shared.providers.e2b_application_preview", e2b_preview_stub)

from backend.core.api.app.services.embed_service import EmbedService  # noqa: E402  # Import after stubbing optional dependencies.

encode = toon_stub.encode


class FakeRedisClient:
    def __init__(self, embed_data: dict):
        self.values = {"embed:embed-1": json.dumps(embed_data)}
        self.published = []

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value

    async def sadd(self, key: str, value: str):
        return 1

    async def expire(self, key: str, ttl: int):
        return True

    async def publish(self, channel: str, message: str):
        self.published.append((channel, json.loads(message)))
        return 1


class FakeCacheService:
    def __init__(self, embed_data: dict):
        self._client = FakeRedisClient(embed_data)

    @property
    async def client(self):
        return self._client


class FakeEncryptionService:
    async def encrypt_with_user_key(self, content: str, vault_key_id: str):
        return content, "test-key-version"

    async def decrypt_with_user_key(self, encrypted_content: str, vault_key_id: str):
        return encrypted_content


@pytest.mark.asyncio
async def test_versioned_finished_code_update_publishes_same_embed_snapshot():
    initial_toon = encode(
        {
            "type": "code",
            "language": "python",
            "filename": "main.py",
            "code": "def old():\n    return 1",
            "embed_ref": "main.py",
            "status": "finished",
        }
    )
    cache = FakeCacheService(
        {
            "embed_id": "embed-1",
            "encrypted_content": initial_toon,
            "status": "finished",
            "message_id": "message-1",
            "hashed_task_id": "task-hash",
            "is_private": False,
            "is_shared": False,
            "created_at": 1760000000,
            "updated_at": 1760000000,
        }
    )
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    ok = await service.update_code_embed_content(
        embed_id="embed-1",
        code_content="def old() -> int:\n    return 2",
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        status="finished",
        version_number=2,
        content_hash="content-hash-v2",
    )

    assert ok is True
    assert len(cache._client.published) == 1
    channel, message = cache._client.published[0]
    payload = message["payload"]
    assert channel == "websocket:user:user-hash"
    assert payload["embed_id"] == "embed-1"
    assert payload["version_number"] == 2
    assert payload["content_hash"] == "content-hash-v2"
    assert "def old() -> int" in payload["content"]

    cached_after = json.loads(cache._client.values["embed:embed-1"])
    assert cached_after["version_number"] == 2
    assert cached_after["content_hash"] == "content-hash-v2"
