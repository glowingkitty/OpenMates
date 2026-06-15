"""Regression tests for encrypted embed diff WebSocket writes.

Embed version rows are long-term stored only after client-side encryption with
the parent embed key. The WebSocket handler must therefore reject plaintext or
unauthorized writes and must derive ownership from the authenticated session,
not from client-provided hashes.
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


def get_handle_store_embed_diff():
    from backend.core.api.app.routes.handlers.websocket_handlers.store_embed_diff_handler import (
        handle_store_embed_diff,
    )

    return handle_store_embed_diff


OWNER_ID = "owner-user"
RECIPIENT_ID = "shared-recipient"
OWNER_HASH = hashlib.sha256(OWNER_ID.encode()).hexdigest()
RECIPIENT_HASH = hashlib.sha256(RECIPIENT_ID.encode()).hexdigest()


class FakeEmbedMethods:
    def __init__(self, existing_embed=None):
        self.existing_embed = existing_embed

    async def get_embed_by_id(self, embed_id):
        if self.existing_embed and self.existing_embed.get("embed_id") == embed_id:
            return self.existing_embed
        return None


class FakeDirectusService:
    def __init__(self, existing_embed=None):
        self.embed = FakeEmbedMethods(existing_embed)
        self.rows = []

    async def read_items(self, collection, params):
        assert collection == "embed_diffs"
        filters = params.get("filter", {})
        embed_id = filters.get("embed_id", {}).get("_eq")
        version_number = filters.get("version_number", {}).get("_eq")
        hashed_user_id = filters.get("hashed_user_id", {}).get("_eq")
        return [
            row
            for row in self.rows
            if row["embed_id"] == embed_id
            and row["version_number"] == version_number
            and row["hashed_user_id"] == hashed_user_id
        ]

    async def create_item(self, collection, payload):
        assert collection == "embed_diffs"
        self.rows.append(payload)
        return payload


class FakeConnectionManager:
    def __init__(self):
        self.personal_messages = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.personal_messages.append((message, user_id, device_fingerprint_hash))

    async def broadcast_to_user(self, message, user_id, exclude_device_hash):
        self.broadcasts.append((message, user_id, exclude_device_hash))


def diff_payload(**overrides):
    payload = {
        "embed_id": "embed-1",
        "version_number": 1,
        "encrypted_snapshot": "encrypted-snapshot",
        "hashed_user_id": RECIPIENT_HASH,
        "created_at": 123,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_store_embed_diff_allows_owner_encrypted_row_and_derives_owner_hash():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH})

    handle_store_embed_diff = get_handle_store_embed_diff()
    await handle_store_embed_diff(
        websocket=None,
        manager=manager,
        cache_service=None,
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=diff_payload(hashed_user_id=RECIPIENT_HASH),
    )

    assert len(directus.rows) == 1
    assert directus.rows[0]["hashed_user_id"] == OWNER_HASH
    assert directus.rows[0]["encrypted_snapshot"] == "encrypted-snapshot"
    assert directus.rows[0]["encrypted_patch"] is None
    assert manager.personal_messages == []
    assert len(manager.broadcasts) == 1


@pytest.mark.asyncio
async def test_store_embed_diff_rejects_shared_recipient_write():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH})

    handle_store_embed_diff = get_handle_store_embed_diff()
    await handle_store_embed_diff(
        websocket=None,
        manager=manager,
        cache_service=None,
        directus_service=directus,
        user_id=RECIPIENT_ID,
        device_fingerprint_hash="device-1",
        payload=diff_payload(hashed_user_id=RECIPIENT_HASH),
    )

    assert directus.rows == []
    assert manager.broadcasts == []
    assert manager.personal_messages[0][0]["payload"]["message"] == "Not authorized to store embed diff"


@pytest.mark.asyncio
async def test_store_embed_diff_rejects_unencrypted_or_empty_row():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH})

    handle_store_embed_diff = get_handle_store_embed_diff()
    await handle_store_embed_diff(
        websocket=None,
        manager=manager,
        cache_service=None,
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=diff_payload(encrypted_snapshot=None, encrypted_patch=None),
    )

    assert directus.rows == []
    assert manager.broadcasts == []
    assert manager.personal_messages[0][0]["payload"]["message"] == "Embed diff row must be encrypted"


@pytest.mark.asyncio
async def test_store_embed_diff_does_not_duplicate_existing_version_row():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH})
    directus.rows.append(
        {
            "embed_id": "embed-1",
            "version_number": 1,
            "encrypted_snapshot": "encrypted-snapshot",
            "encrypted_patch": None,
            "hashed_user_id": OWNER_HASH,
            "created_at": 1,
        }
    )

    handle_store_embed_diff = get_handle_store_embed_diff()
    await handle_store_embed_diff(
        websocket=None,
        manager=manager,
        cache_service=None,
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=diff_payload(encrypted_snapshot="new-ciphertext"),
    )

    assert len(directus.rows) == 1
    assert directus.rows[0]["encrypted_snapshot"] == "encrypted-snapshot"
    assert manager.personal_messages == []
    assert manager.broadcasts == []
