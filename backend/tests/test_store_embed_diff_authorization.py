"""Regression tests for encrypted embed diff WebSocket writes.

Embed version rows are long-term stored only after client-side encryption with
the parent embed key. The WebSocket handler must therefore reject plaintext or
unauthorized writes and must derive ownership from the authenticated session,
not from client-provided hashes.
"""

import hashlib
import sys
import types
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def internal_history_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "synthetic-internal-history-token")

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
    def __init__(self, existing_embed=None, *, project_linked=False):
        self.embed = FakeEmbedMethods(existing_embed)
        self.rows = []
        self.project_linked = project_linked
        self.base_url = "http://internal-directus"

    async def _make_api_request(self, method, url, *, headers, json):
        assert method == "POST" and url.endswith("/legacy-embed-diff-write")
        assert headers["X-Internal-Service-Token"] == "synthetic-internal-history-token"
        row = {"embed_id": json["embed_id"], "hashed_user_id": json["actor_user_hash"], **json["row"]}
        existing = next((r for r in self.rows if r["embed_id"] == row["embed_id"]
                         and r["version_number"] == row["version_number"]), None)
        if existing and (any(existing.get(k) != row[k] for k in ("encrypted_snapshot", "encrypted_patch"))
                         or (row.get("created_at") and existing.get("created_at") != row["created_at"])):
            return SimpleNamespace(status_code=409, json=lambda: {"error": {"code": "immutable_version_mismatch"}})
        if existing is None:
            self.rows.append(row)
        import json as json_module
        digest = hashlib.sha256(json_module.dumps([row.get("encrypted_snapshot"), row.get("encrypted_patch")],
            separators=(",", ":")).encode()).hexdigest()
        return SimpleNamespace(status_code=200, json=lambda: {"data": {"embed_id": row["embed_id"],
            "version_number": row["version_number"], "canonical_source": "version_row",
            "canonical_digest": digest, "idempotent": existing is not None}})

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

    async def get_items(self, collection, params, **kwargs):
        assert collection == "project_items"
        return [{"id": "project-item-1"}] if self.project_linked else []

    async def create_item(self, collection, payload):
        assert collection == "embed_diffs"
        self.rows.append(payload)
        return payload

    async def update_item(self, collection, item_id, payload):
        assert collection == "embed_diffs"
        for row in self.rows:
            if row.get("id") == item_id:
                row.update(payload)
                return row
        return None


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


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_store_embed_diff_allows_owner_encrypted_row_and_derives_owner_hash():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH}
    )

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


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_store_embed_diff_confirms_request_after_persisting_row():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH}
    )

    handle_store_embed_diff = get_handle_store_embed_diff()
    await handle_store_embed_diff(
        websocket=None,
        manager=manager,
        cache_service=None,
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=diff_payload(request_id="request-1", version_number=2, encrypted_snapshot=None, encrypted_patch="encrypted-patch"),
    )

    assert len(directus.rows) == 1
    assert len(manager.broadcasts) == 1
    assert manager.personal_messages == [
        (
            {
                "type": "store_embed_diff_confirmed",
                "payload": {
                    "request_id": "request-1",
                    "embed_id": "embed-1",
                    "version_number": 2,
                    "canonical_digest": hashlib.sha256(b'[null,"encrypted-patch"]').hexdigest(),
                    "canonical_source": "version_row",
                },
            },
            OWNER_ID,
            "device-1",
        )
    ]


# contract-test: supporting surface=rest_api assertions=storage.versions.metadata-and-payload
@pytest.mark.asyncio
async def test_store_embed_diff_retry_without_timestamp_returns_canonical_digest():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH}
    )
    directus.rows.append({
        "id": "row-1", "embed_id": "embed-1", "version_number": 1,
        "encrypted_snapshot": "encrypted-snapshot", "encrypted_patch": None,
        "hashed_user_id": OWNER_HASH, "created_at": 123,
    })
    await get_handle_store_embed_diff()(
        websocket=None, manager=manager, cache_service=None,
        directus_service=directus, user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=diff_payload(created_at=None, request_id="retry-1"),
    )
    assert len(directus.rows) == 1
    assert manager.personal_messages[0][0]["payload"]["canonical_digest"] == hashlib.sha256(
        b'["encrypted-snapshot",null]'
    ).hexdigest()


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_store_embed_diff_rejects_shared_recipient_write():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH}
    )

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


# contract-test: supporting surface=rest_api assertions=projects.files.no-server-decryption-authority
@pytest.mark.asyncio
async def test_store_embed_diff_rejects_unencrypted_or_empty_row():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH}
    )

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


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_store_embed_diff_rejects_mutation_of_existing_version_ciphertext():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH}
    )
    directus.rows.append(
        {
            "id": "row-1",
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
        payload=diff_payload(encrypted_snapshot="new-ciphertext", request_id="competing-write"),
    )

    assert len(directus.rows) == 1
    assert directus.rows[0]["encrypted_snapshot"] == "encrypted-snapshot"
    assert directus.rows[0]["encrypted_patch"] is None
    assert manager.personal_messages[0][0]["payload"]["message"] == "Immutable embed version mismatch"
    assert manager.personal_messages[0][0]["payload"]["request_id"] == "competing-write"
    assert manager.personal_messages[0][0]["payload"]["code"] == "embed_diff_conflict"
    assert manager.broadcasts == []


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.files.concurrent-chat-safety
@pytest.mark.asyncio
async def test_store_embed_diff_rejects_legacy_history_write_for_project_embed():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH},
        project_linked=True,
    )

    handle_store_embed_diff = get_handle_store_embed_diff()
    await handle_store_embed_diff(
        websocket=None,
        manager=manager,
        cache_service=None,
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=diff_payload(),
    )

    assert directus.rows == []
    assert manager.broadcasts == []
    assert manager.personal_messages[0][0]["payload"]["message"] == "Project file revisions require atomic commit"


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_diagram_history_allows_initial_snapshot_but_fences_later_legacy_versions():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed={
        "embed_id": "embed-1", "hashed_user_id": OWNER_HASH,
        "app_id": "diagrams", "skill_id": "html",
    })
    handle = get_handle_store_embed_diff()
    common = dict(
        websocket=None, manager=manager, cache_service=None,
        directus_service=directus, user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
    )
    await handle(**common, payload=diff_payload())
    assert [(row["version_number"], row["encrypted_snapshot"]) for row in directus.rows] == [
        (1, "encrypted-snapshot")
    ]

    await handle(**common, payload=diff_payload(
        version_number=2, encrypted_snapshot=None, encrypted_patch="encrypted-patch",
    ))
    assert len(directus.rows) == 1
    assert manager.personal_messages[-1][0]["payload"]["message"] == "Diagram revisions require atomic commit"
