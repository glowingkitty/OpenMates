"""Regression tests for store_embed backend write authorization.

Shared-chat recipients can decrypt embeds client-side when they have the shared
fragment key, but that never grants permission to rewrite owner embed rows on
the server. These tests keep that guarantee in the WebSocket handler, where the
server can enforce it regardless of what the frontend sends.
"""

import hashlib
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
directus_module_stub = types.ModuleType("backend.core.api.app.services.directus.directus")
directus_module_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_module_stub)
sys.modules.setdefault("backend.core.api.app.services.directus.directus", directus_module_stub)


def get_handle_store_embed():
    from backend.core.api.app.routes.handlers.websocket_handlers.store_embed_handler import (
        handle_store_embed,
    )

    return handle_store_embed


OWNER_ID = "owner-user"
RECIPIENT_ID = "shared-recipient"
OWNER_HASH = hashlib.sha256(OWNER_ID.encode()).hexdigest()
RECIPIENT_HASH = hashlib.sha256(RECIPIENT_ID.encode()).hexdigest()


class FakeEmbedMethods:
    def __init__(self, existing_embed=None):
        self.existing_embed = existing_embed
        self.updated = []
        self.created = []

    async def get_embed_by_id(self, embed_id):
        return self.existing_embed

    async def update_embed(self, embed_id, payload):
        self.updated.append((embed_id, payload))
        return {"embed_id": embed_id, **payload}

    async def create_embed(self, payload):
        self.created.append(payload)
        return payload


class FakeDirectusService:
    def __init__(self, existing_embed=None):
        self.embed = FakeEmbedMethods(existing_embed)


class FakeCacheService:
    @property
    async def client(self):
        return None

    async def remove_pending_embed(self, user_id, embed_id):
        return True


class FakeConnectionManager:
    def __init__(self):
        self.personal_messages = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.personal_messages.append((message, user_id, device_fingerprint_hash))

    async def broadcast_to_user(self, message, user_id, exclude_device_hash):
        self.broadcasts.append((message, user_id, exclude_device_hash))


def store_payload(**overrides):
    payload = {
        "embed_id": "embed-1",
        "encrypted_type": "encrypted-type",
        "encrypted_content": "encrypted-content",
        "status": "finished",
        "hashed_chat_id": "hashed-chat",
        "hashed_message_id": "hashed-message",
        "hashed_user_id": OWNER_HASH,
        "created_at": 1,
        "updated_at": 2,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_store_embed_rejects_existing_embed_update_from_non_owner():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH})

    handle_store_embed = get_handle_store_embed()
    await handle_store_embed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=RECIPIENT_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(hashed_user_id=RECIPIENT_HASH),
    )

    assert directus.embed.updated == []
    assert directus.embed.created == []
    assert manager.broadcasts == []
    assert manager.personal_messages[0][0]["payload"]["message"] == "Not authorized to store embed"


@pytest.mark.asyncio
async def test_store_embed_rejects_new_embed_create_with_forged_owner_hash():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed=None)

    handle_store_embed = get_handle_store_embed()
    await handle_store_embed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=RECIPIENT_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(hashed_user_id=OWNER_HASH),
    )

    assert directus.embed.updated == []
    assert directus.embed.created == []
    assert manager.broadcasts == []
    assert manager.personal_messages[0][0]["payload"]["message"] == "Not authorized to store embed"


@pytest.mark.asyncio
async def test_store_embed_allows_existing_embed_update_from_owner():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH})

    handle_store_embed = get_handle_store_embed()
    await handle_store_embed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(hashed_user_id=RECIPIENT_HASH),
    )

    assert len(directus.embed.updated) == 1
    assert directus.embed.updated[0][1]["hashed_user_id"] == OWNER_HASH
    assert manager.personal_messages == []
    assert len(manager.broadcasts) == 1
