"""Authenticated wrapper writes must follow the canonical encrypted embed head."""

import hashlib
import sys
import types

import pytest


redis_stub = types.ModuleType("redis")
redis_asyncio_stub = types.ModuleType("redis.asyncio")
redis_asyncio_stub.Redis = object
redis_stub.asyncio = redis_asyncio_stub
redis_stub.exceptions = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception)
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
directus_stub = types.ModuleType("backend.core.api.app.services.directus.directus")
directus_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)
sys.modules.setdefault("backend.core.api.app.services.directus.directus", directus_stub)


def _handler():
    from backend.core.api.app.routes.handlers.websocket_handlers.store_embed_keys_handler import (
        handle_store_embed_keys,
    )
    return handle_store_embed_keys


USER_ID = "owner-user"
USER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
EMBED_ID = "embed-1"
EMBED_HASH = hashlib.sha256(EMBED_ID.encode()).hexdigest()
CHAT_HASH = hashlib.sha256(b"chat-1").hexdigest()
SECOND_CHAT_HASH = hashlib.sha256(b"chat-2").hexdigest()


@pytest.fixture(autouse=True)
def archive_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")


class FakeResponse:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return {"data": self.data}


class FakeManager:
    def __init__(self):
        self.messages = []

    async def send_personal_message(self, message, *_args):
        self.messages.append(message)


class FakeEmbeds:
    def __init__(self, directus):
        self.directus = directus

    async def create_embed_key(self, data):
        stored = {"id": "wrapper-1", **data}
        self.directus.wrappers = [stored]
        self.directus.writes.append(("create", dict(data)))
        return stored

    async def update_embed_key(self, key_id, data):
        self.directus.wrappers[0].update(data)
        self.directus.writes.append(("update", key_id, dict(data)))
        return self.directus.wrappers[0]


class FakeDirectus:
    def __init__(self):
        self.head = {
            "embed_id": EMBED_ID, "hashed_embed_id": EMBED_HASH,
            "hashed_user_id": USER_HASH, "hashed_chat_id": CHAT_HASH,
            "version_number": 4,
        }
        self.wrappers = []
        self.links = []
        self.chats = {
            CHAT_HASH: {"id": "11111111-1111-4111-8111-111111111111",
                        "hashed_chat_id": CHAT_HASH, "hashed_user_id": USER_HASH,
                        "hashed_team_id": None, "storage_state": "hot"},
            SECOND_CHAT_HASH: {"id": "22222222-2222-4222-8222-222222222222",
                               "hashed_chat_id": SECOND_CHAT_HASH, "hashed_user_id": USER_HASH,
                               "hashed_team_id": None, "storage_state": "hot"},
        }
        self.memberships = []
        self.teams = []
        self.writes = []
        self.fail_collection = None
        self.embed = FakeEmbeds(self)
        self.base_url = "http://directus.test"
        self.recovery_calls = []
        self.manager = None

    async def _make_api_request(self, method, url, *, headers, json):
        assert method == "POST"
        if url.endswith("/chat-archive-transaction"):
            assert json["operation"] == "resolve_chat_hashes"
            return FakeResponse({"chats": [self.chats[value] for value in json["data"]["hashes"]
                                           if value in self.chats]})
        assert url.endswith("/chat-recovery-transaction")
        assert json["operation"] == "complete_authorized_direct_by_embed"
        if self.manager is not None:
            assert self.manager.messages[0]["type"] == "store_embed_keys_confirmed"
        self.recovery_calls.append(json["data"])
        return FakeResponse({"completed": True, "intent_kind": "direct_skill"})

    async def get_items(self, collection, params, *, no_cache, admin_required, raise_on_error):
        assert no_cache and admin_required and raise_on_error
        if collection == self.fail_collection:
            raise RuntimeError("Directus unavailable")
        fields = params["filter"]
        if collection == "embeds":
            return [self.head] if self.head and fields["hashed_embed_id"]["_eq"] == EMBED_HASH else []
        if collection == "project_items":
            return self.links
        if collection == "embed_keys":
            expected_chat = fields["hashed_chat_id"]
            return [row for row in self.wrappers if row["hashed_embed_id"] == fields["hashed_embed_id"]["_eq"]
                    and row["key_type"] == fields["key_type"]["_eq"]
                    and (row.get("hashed_chat_id") == expected_chat.get("_eq") if "_eq" in expected_chat
                         else row.get("hashed_chat_id") is None)]
        if collection == "team_memberships":
            return [row for row in self.memberships
                    if row["hashed_team_id"] == fields["hashed_team_id"]["_eq"]
                    and row["hashed_user_id"] == fields["hashed_user_id"]["_eq"]
                    and row["status"] == "active"]
        if collection == "teams":
            return [row for row in self.teams
                    if row["hashed_team_id"] == fields["hashed_team_id"]["_eq"]
                    and row["status"] == "active"]
        raise AssertionError(collection)


def _key(**overrides):
    return {
        "hashed_embed_id": EMBED_HASH,
        "key_type": "chat",
        "hashed_chat_id": CHAT_HASH,
        "encrypted_embed_key": "cipher-wrapper-1",
        "hashed_user_id": USER_HASH,
        "created_at": 10,
        **overrides,
    }


async def _send(directus, *keys):
    manager = FakeManager()
    directus.manager = manager
    await _handler()(
        websocket=None, manager=manager, cache_service=None,
        directus_service=directus, user_id=USER_ID,
        device_fingerprint_hash="device-1",
        payload={"request_id": "request-1", "keys": list(keys)},
    )
    return manager.messages[0]["payload"]


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_owner_wrapper_create_retry_and_reencryption_keep_receipt_counts():
    directus = FakeDirectus()
    first = await _send(directus, _key())
    retry = await _send(directus, _key())
    changed = await _send(directus, _key(encrypted_embed_key="cipher-wrapper-2"))
    assert [(result["created_count"], result["failed_count"]) for result in (first, retry, changed)] == [
        (1, 0), (1, 0), (1, 0),
    ]
    assert [write[0] for write in directus.writes] == ["create", "update"]
    assert directus.wrappers[0]["hashed_user_id"] == USER_HASH
    assert directus.wrappers[0]["encrypted_embed_key"] == "cipher-wrapper-2"


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_wrapper_receipt_precedes_exact_direct_intent_completion(monkeypatch):
    from backend.core.api.app.services import chat_recovery_service
    monkeypatch.setattr(
        chat_recovery_service,
        "RECOVERY_OPERATIONS",
        chat_recovery_service.RECOVERY_OPERATIONS | {"complete_authorized_direct_by_embed"},
    )
    directus = FakeDirectus()
    receipt = await _send(directus, _key())
    assert receipt == {
        "request_id": "request-1", "created_count": 1, "failed_count": 0,
        "requested_count": 1,
    }
    assert directus.recovery_calls == [{
        "protocol_version": 1,
        "intent_kind": "direct_skill",
        "hashed_user_id": USER_HASH,
        "primary_embed_id": EMBED_ID,
        "target_chat_id": "11111111-1111-4111-8111-111111111111",
        "canonical_version": 4,
    }]


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_forged_owner_and_foreign_embed_are_rejected_without_key_write():
    directus = FakeDirectus()
    forged = await _send(directus, _key(hashed_user_id="f" * 64))
    directus.head["hashed_user_id"] = "f" * 64
    foreign_head = await _send(directus, _key())
    assert forged["failed_count"] == foreign_head["failed_count"] == 1
    assert directus.writes == []


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_foreign_chat_or_project_link_cannot_receive_wrapper():
    directus = FakeDirectus()
    directus.chats["f" * 64] = {"hashed_chat_id": "f" * 64,
                               "hashed_user_id": "f" * 64, "hashed_team_id": None,
                               "storage_state": "hot"}
    wrong_chat = await _send(directus, _key(hashed_chat_id="f" * 64))
    directus.links = [{"id": "project-item-1"}]
    project_linked = await _send(directus, _key())
    assert wrong_chat["failed_count"] == project_linked["failed_count"] == 1
    assert directus.writes == []

    directus.links = []
    directus.chats[CHAT_HASH]["storage_state"] = "deleting"
    deleting = await _send(directus, _key())
    assert deleting["failed_count"] == 1
    assert directus.writes == []


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_owner_can_copy_wrapper_to_second_personal_chat():
    directus = FakeDirectus()
    directus.chats[SECOND_CHAT_HASH]["storage_state"] = None  # Legacy hot row.
    receipt = await _send(directus, _key(hashed_chat_id=SECOND_CHAT_HASH))
    assert receipt["created_count"] == 1 and receipt["failed_count"] == 0
    assert directus.wrappers[0]["hashed_chat_id"] == SECOND_CHAT_HASH


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_owner_created_team_chat_requires_active_writer_membership():
    directus = FakeDirectus()
    team_hash = "b" * 64
    directus.chats[SECOND_CHAT_HASH] = {"hashed_chat_id": SECOND_CHAT_HASH,
                                       "hashed_user_id": None, "hashed_team_id": team_hash,
                                       "storage_state": "hot"}
    denied = await _send(directus, _key(hashed_chat_id=SECOND_CHAT_HASH))
    directus.memberships = [{"hashed_team_id": team_hash, "hashed_user_id": USER_HASH,
                             "role": "viewer", "status": "active"}]
    directus.teams = [{"id": "team-1", "hashed_team_id": team_hash, "status": "active"}]
    viewer = await _send(directus, _key(hashed_chat_id=SECOND_CHAT_HASH))
    directus.memberships[0]["role"] = "member"
    allowed = await _send(directus, _key(hashed_chat_id=SECOND_CHAT_HASH))
    assert denied["failed_count"] == 1
    assert viewer["failed_count"] == 1
    assert allowed["created_count"] == 1 and allowed["failed_count"] == 0


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_foreign_existing_wrapper_is_never_upserted():
    directus = FakeDirectus()
    directus.wrappers = [{"id": "foreign-wrapper", **_key(
        hashed_user_id="f" * 64, encrypted_embed_key="foreign-cipher",
    )}]
    receipt = await _send(directus, _key(encrypted_embed_key="attacker-cipher"))
    assert receipt["created_count"] == 0 and receipt["failed_count"] == 1
    assert directus.wrappers[0]["encrypted_embed_key"] == "foreign-cipher"
    assert directus.writes == []


# contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.asyncio
async def test_missing_head_and_directus_read_failure_fail_closed():
    directus = FakeDirectus()
    directus.head = None
    absent = await _send(directus, _key())
    directus.head = {"embed_id": EMBED_ID, "hashed_embed_id": EMBED_HASH,
                    "hashed_user_id": USER_HASH, "hashed_chat_id": CHAT_HASH}
    directus.fail_collection = "embed_keys"
    unavailable = await _send(directus, _key())
    assert absent["failed_count"] == unavailable["failed_count"] == 1
    assert directus.writes == []

    directus.fail_collection = None
    directus.chats[CHAT_HASH].pop("storage_state")
    incomplete_scope = await _send(directus, _key())
    assert incomplete_scope["failed_count"] == 1
    assert directus.writes == []
