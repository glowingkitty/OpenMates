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


@pytest.fixture(autouse=True)
def internal_transaction_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")


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
    def __init__(self, existing_embed=None, *, project_linked=False, chats=None):
        self.embed = FakeEmbedMethods(existing_embed)
        self.project_linked = project_linked
        self.chats = chats or {}
        self.recovery_calls = []
        self.manager = None

    async def get_items(self, collection, params, **kwargs):
        if collection == "chats":
            chat = self.chats.get(params["filter[id][_eq]"])
            return [chat] if chat else []
        assert collection == "project_items"
        return [{"id": "project-item-1"}] if self.project_linked else []

    base_url = "http://directus.test"

    async def _make_api_request(self, method, url, *, headers, json):
        assert method == "POST"
        if url.endswith("/chat-recovery-transaction"):
            assert json["operation"] == "complete_authorized_direct_by_embed"
            if self.manager is not None:
                assert self.manager.personal_messages[0][0]["type"] == "store_embed_confirmed"
            self.recovery_calls.append(json["data"])
            return FakeResponse(200, {"data": {
                "completed": False, "reason_code": "pending_wrappers",
            }})
        assert url.endswith("/legacy-embed-write")
        payload = json["payload"]
        embed_id = json["embed_id"]
        actor_hash = json["actor_user_hash"]
        if self.project_linked:
            return FakeResponse(403, {"error": {"code": "project_context_required"}})
        if self.embed.existing_embed:
            if self.embed.existing_embed.get("hashed_user_id") != actor_hash:
                return FakeResponse(403, {"error": {"code": "embed_access_denied"}})
            stored = {**payload, "hashed_user_id": actor_hash}
            await self.embed.update_embed(embed_id, stored)
            self.embed.existing_embed = {"embed_id": embed_id, **stored}
            return FakeResponse(200, {"data": {"status": "updated", "embed_id": embed_id}})
        if payload.get("hashed_user_id") != actor_hash:
            return FakeResponse(403, {"error": {"code": "embed_access_denied"}})
        await self.embed.create_embed(payload)
        self.embed.existing_embed = dict(payload)
        return FakeResponse(200, {"data": {"status": "created", "embed_id": embed_id}})


class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data

    def json(self):
        return self.data


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


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
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


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
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


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_personal_chat_projection_ignores_forged_team_and_root_fields():
    manager = FakeConnectionManager()
    chat_id = "personal-chat"
    directus = FakeDirectusService(chats={chat_id: {"id": chat_id, "hashed_user_id": OWNER_HASH, "hashed_team_id": None}})
    await get_handle_store_embed()(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(
            chat_id=chat_id,
            hashed_chat_id=hashlib.sha256(chat_id.encode()).hexdigest(),
            app_id="events", skill_id="search",
            hashed_team_id=hashlib.sha256(b"another-team").hexdigest(),
            workspace_origin="web_apps", root_embed_id="forged-root",
            apps_workspace_root_id="forged-root",
        ),
    )
    assert not manager.personal_messages
    assert len(directus.embed.created) == 1
    created = directus.embed.created[0]
    assert created["workspace_origin"] == "chat"
    assert created["root_embed_id"] == created["embed_id"]
    assert "hashed_team_id" not in created
    assert "apps_workspace_root_id" not in created


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
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


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.files.concurrent-chat-safety
@pytest.mark.asyncio
async def test_store_embed_rejects_legacy_update_for_project_linked_embed():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH},
        project_linked=True,
    )

    handle_store_embed = get_handle_store_embed()
    await handle_store_embed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(),
    )

    assert directus.embed.updated == []
    assert directus.embed.created == []
    assert manager.personal_messages[0][0]["payload"]["message"] == "Not authorized to store embed"


# contract-test: supporting surface=rest_api assertions=projects.files.concurrent-chat-safety
@pytest.mark.asyncio
async def test_store_embed_rejects_project_link_added_after_precheck():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(
        existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH},
    )

    async def link_after_precheck(collection, params, **kwargs):
        directus.project_linked = True
        return []

    directus.get_items = link_after_precheck
    await get_handle_store_embed()(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(),
    )

    assert directus.embed.updated == []
    assert directus.embed.created == []
    assert manager.broadcasts == []
    assert manager.personal_messages[0][0]["payload"]["message"] == "Not authorized to store embed"


# contract-test: supporting surface=rest_api assertions=projects.files.concurrent-chat-safety
@pytest.mark.asyncio
@pytest.mark.parametrize("stored_version,expected_version", [(3, 3), (None, 1)])
async def test_store_embed_guarded_write_preserves_canonical_receipt(monkeypatch, stored_version, expected_version):
    from backend.core.api.app.services import chat_recovery_service
    monkeypatch.setattr(
        chat_recovery_service,
        "RECOVERY_OPERATIONS",
        chat_recovery_service.RECOVERY_OPERATIONS | {"complete_authorized_direct_by_embed"},
    )
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed=None)
    directus.manager = manager
    await get_handle_store_embed()(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(
            request_id="store-request-1", recovery_record_id="recovery-record-1",
            text_length_chars=12, version_number=stored_version,
            chat_id="11111111-1111-4111-8111-111111111111",
            hashed_chat_id=hashlib.sha256(
                b"11111111-1111-4111-8111-111111111111"
            ).hexdigest(),
        ),
    )

    assert "text_length_chars" not in directus.embed.created[0]
    assert "recovery_record_id" not in directus.embed.created[0]
    assert manager.personal_messages[0][0] == {
        "type": "store_embed_confirmed",
        "payload": {
            "request_id": "store-request-1",
            "embed_id": "embed-1",
            "canonical_digest": hashlib.sha256(b"encrypted-content").hexdigest(),
            "canonical_source": "head",
        },
    }
    assert directus.recovery_calls == [{
        "protocol_version": 1,
        "intent_kind": "direct_skill",
        "hashed_user_id": OWNER_HASH,
        "primary_embed_id": "embed-1",
        "target_chat_id": "11111111-1111-4111-8111-111111111111",
        "canonical_version": expected_version,
    }]


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_recovered_embed_write_failure_rejects_exact_request_without_receipt():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed=None)

    async def failed_write(method, url, *, headers, json):
        if url.endswith("/legacy-embed-write"):
            raise RuntimeError("synthetic canonical storage failure")
        raise AssertionError("Unexpected Directus operation")

    directus._make_api_request = failed_write
    await get_handle_store_embed()(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(
            request_id="recovery-store-request-1",
            recovery_record_id="recovery-record-1",
        ),
    )

    assert directus.embed.created == []
    assert manager.broadcasts == []
    assert [message[0] for message in manager.personal_messages] == [{
        "type": "error",
        "payload": {
            "code": "embed_storage_failed",
            "request_id": "recovery-store-request-1",
            "message": "Failed to store embed",
        },
    }]


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_early_embed_authorization_denial_correlates_exact_request():
    manager = FakeConnectionManager()
    directus = FakeDirectusService()
    await get_handle_store_embed()(
        websocket=None, manager=manager, cache_service=FakeCacheService(),
        directus_service=directus, user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(
            request_id="nonce-early-1", recovery_record_id="recovery-record-1",
            app_id="Invalid App", skill_id="search", chat_id="chat-1",
        ),
    )

    assert directus.embed.created == [] and directus.embed.updated == []
    assert manager.broadcasts == []
    assert [message[0] for message in manager.personal_messages] == [{
        "type": "error",
        "payload": {"code": "embed_write_denied", "request_id": "nonce-early-1",
                    "message": "Not authorized to store embed"},
    }]


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_transaction_catalog_denial_correlates_nonce_without_exposing_internal_reason():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed={"embed_id": "embed-1", "hashed_user_id": OWNER_HASH})

    async def deny_catalog(method, url, *, headers, json):
        assert url.endswith("/legacy-embed-write")
        return FakeResponse(403, {"error": {"code": "embed_catalog_context_mismatch"}})

    directus._make_api_request = deny_catalog
    await get_handle_store_embed()(
        websocket=None, manager=manager, cache_service=FakeCacheService(),
        directus_service=directus, user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(request_id="nonce-catalog-2", recovery_record_id="recovery-record-2"),
    )

    assert directus.embed.created == [] and directus.embed.updated == []
    assert manager.broadcasts == []
    assert [message[0] for message in manager.personal_messages] == [{
        "type": "error",
        "payload": {"code": "embed_write_denied", "request_id": "nonce-catalog-2",
                    "message": "Not authorized to store embed"},
    }]


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.files.concurrent-chat-safety
@pytest.mark.asyncio
async def test_store_embed_rejects_reserved_hosted_create_before_project_link_exists():
    manager = FakeConnectionManager()
    directus = FakeDirectusService(existing_embed=None)

    handle_store_embed = get_handle_store_embed()
    await handle_store_embed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=directus,
        user_id=OWNER_ID,
        device_fingerprint_hash="device-1",
        payload=store_payload(embed_id="11111111-1111-5111-8111-111111111111"),
    )

    assert directus.embed.updated == []
    assert directus.embed.created == []
