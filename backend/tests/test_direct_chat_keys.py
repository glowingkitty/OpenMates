"""Account-key immutability and Team direct-chat creation security.

These focused tests exercise registration races, malformed keys, membership
denials, two-person envelope projection and content-free notification routing.
They use fake Directus storage and never call product HTTP or WebSocket paths.
The account-delete trigger is probed against isolated PostgreSQL in CI.
"""

import asyncio
import base64
import hashlib
import sys
import types
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

if "slowapi" not in sys.modules:
    slowapi = types.ModuleType("slowapi")
    util = types.ModuleType("slowapi.util")

    class FakeLimiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *_args, **_kwargs):
            return lambda function: function

    slowapi.Limiter = FakeLimiter
    util.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi
    sys.modules["slowapi.util"] = util

from backend.core.api.app.routes import direct_chats
from backend.core.api.app.services import direct_chat_notification_service
from backend.core.api.app.services.direct_chat_access import project_direct_chat_metadata
from backend.core.api.app.services.direct_chat_key_service import (
    KeyConflictError, register_account_key, validate_public_key,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id


def _key(seed: int) -> dict[str, str]:
    public = bytes([seed]) * 32
    return {"key_id": hashlib.sha256(public).hexdigest(),
            "public_key": base64.urlsafe_b64encode(public).decode().rstrip("="),
            "encrypted_private_key": f"cipher-{seed}"}


class FakeDirectus:
    def __init__(self):
        self.keys = {}
        self.chats = {}
        self.members = {}
        self.active_teams = set()
        self.create_race_key = None
        self.team = self

    async def require_team_role(self, team_id, user_id, _roles):
        if team_id not in self.active_teams or (team_id, hash_id(user_id)) not in self.members:
            raise TeamPermissionError("denied")
        return self.members[(team_id, hash_id(user_id))]

    async def get_items(self, collection, params=None, **_kwargs):
        params = params or {}
        if collection == "account_chat_keys":
            key = self.keys.get(params["filter[hashed_user_id][_eq]"])
            return [key] if key else []
        if collection == "team_memberships":
            team_hash = params["filter[hashed_team_id][_eq]"]
            member_hash = params["filter[hashed_user_id][_eq]"]
            return [row for (team_id, hashed), row in self.members.items()
                    if hash_id(team_id) == team_hash and hashed == member_hash]
        if collection == "teams":
            return [{"id": team_id} for team_id in self.active_teams
                    if hash_id(team_id) == params["filter[hashed_team_id][_eq]"]]
        if collection == "chats":
            chat = self.chats.get(params["filter[id][_eq]"])
            return [chat] if chat else []
        raise AssertionError(collection)

    async def create_item(self, collection, payload, **_kwargs):
        if collection == "account_chat_keys":
            if self.create_race_key is not None:
                self.keys[payload["hashed_user_id"]] = self.create_race_key
                return False, {"status_code": 400}
            if payload["hashed_user_id"] in self.keys:
                return False, {"status_code": 400}
            self.keys[payload["hashed_user_id"]] = payload
            return True, payload
        if collection == "chats":
            if payload["id"] in self.chats:
                return False, {"status_code": 400}
            self.chats[payload["id"]] = payload
            return True, payload
        raise AssertionError(collection)

# contract-test: supporting surface=rest_api assertions=teams.direct-chat.account-key-exchange
@pytest.mark.asyncio
async def test_register_account_key_is_immutable_and_idempotent_across_insert_race():
    directus = FakeDirectus()
    first = _key(1)
    assert (await register_account_key(directus, "alice", **first))["key_id"] == first["key_id"]
    assert await register_account_key(directus, "alice", **first)
    with pytest.raises(KeyConflictError):
        await register_account_key(directus, "alice", **_key(2))

    race = FakeDirectus()
    race.create_race_key = {"hashed_user_id": hash_id("alice"), **first,
                            "algorithm": "x25519-xsalsa20poly1305", "version": 1}
    assert await register_account_key(race, "alice", **first)
    with pytest.raises(KeyConflictError):
        await register_account_key(race, "bob", **_key(2))

    class ConcurrentDirectus(FakeDirectus):
        def __init__(self):
            super().__init__()
            self.at_insert = 0
            self.release = asyncio.Event()

        async def create_item(self, collection, payload, **kwargs):
            self.at_insert += 1
            if self.at_insert == 2:
                self.release.set()
            await self.release.wait()
            return await super().create_item(collection, payload, **kwargs)

    concurrent = ConcurrentDirectus()
    outcomes = await asyncio.gather(
        register_account_key(concurrent, "carol", **_key(3)),
        register_account_key(concurrent, "carol", **_key(4)),
        return_exceptions=True,
    )
    accepted = [result for result in outcomes if isinstance(result, dict)]
    conflicts = [result for result in outcomes if isinstance(result, KeyConflictError)]
    assert len(accepted) == len(conflicts) == 1
    assert concurrent.keys[hash_id("carol")]["key_id"] == accepted[0]["key_id"]


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.account-key-exchange
def test_public_key_must_be_canonical_and_match_key_id():
    valid = _key(3)
    validate_public_key(valid["public_key"], valid["key_id"])
    for public, key_id in ((valid["public_key"] + "=", valid["key_id"]),
                           (valid["public_key"], _key(4)["key_id"]),
                           ("!" * 43, valid["key_id"]),
                           (_key(0)["public_key"], _key(0)["key_id"])):
        with pytest.raises(ValueError):
            validate_public_key(public, key_id)


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
@pytest.mark.asyncio
async def test_directory_and_creation_deny_nonmember_without_key_disclosure(monkeypatch):
    directus = FakeDirectus()
    team_id = "team"
    directus.active_teams.add(team_id)
    alice, bob, stranger = "alice", "bob", "stranger"
    for user_id in (alice, bob):
        directus.members[(team_id, hash_id(user_id))] = {"user_id": user_id, "hashed_user_id": hash_id(user_id), "status": "active"}
        directus.keys[hash_id(user_id)] = {"hashed_user_id": hash_id(user_id), **_key(1 if user_id == alice else 2),
                                           "algorithm": "x25519-xsalsa20poly1305", "version": 1}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=directus)))
    with pytest.raises(HTTPException) as denied:
        await direct_chats.get_member_chat_encryption_key(team_id, hash_id(bob), request, None,
                                                           SimpleNamespace(id=stranger))
    assert denied.value.status_code == 403

    body = direct_chats.DirectChatCreateRequest(
        chat_id=uuid4(), recipient_user_hash=hash_id(bob),
        participant_key_envelopes={
            hash_id(alice): {"key_id": _key(1)["key_id"], "encrypted_chat_key": "OMDM1." + "a" * 32},
            hash_id(bob): {"key_id": _key(2)["key_id"], "encrypted_chat_key": "OMDM1." + "b" * 32},
        },
    )
    notifications = []

    async def record_notification(_request, recipient_id, _team_id, _chat_id, recipient_chat):
        notifications.append((recipient_id, recipient_chat))

    monkeypatch.setattr(direct_chats, "_notify_recipient", record_notification)
    result = await direct_chats.create_direct_chat(team_id, body, request, None, SimpleNamespace(id=alice))
    assert result["chat"]["encrypted_chat_key"] == "OMDM1." + "a" * 32
    assert "participant_key_envelopes" not in result["chat"]
    assert await direct_chats.create_direct_chat(team_id, body, request, None, SimpleNamespace(id=alice)) == result
    peer_retry = body.model_copy(deep=True)
    peer_retry.recipient_user_hash = hash_id(alice)
    peer_result = await direct_chats.create_direct_chat(team_id, peer_retry, request, None, SimpleNamespace(id=bob))
    assert peer_result["chat"]["encrypted_chat_key"] == "OMDM1." + "b" * 32
    assert len(notifications) == 1
    assert notifications[0][0] == bob
    assert notifications[0][1]["encrypted_chat_key"] == "OMDM1." + "b" * 32
    assert "participant_key_envelopes" not in notifications[0][1]
    assert "encrypted_private_key" not in notifications[0][1]
    changed = body.model_copy(deep=True)
    changed.participant_key_envelopes[hash_id(bob)].encrypted_chat_key = "OMDM1." + "c" * 32
    with pytest.raises(HTTPException) as conflict:
        await direct_chats.create_direct_chat(team_id, changed, request, None, SimpleNamespace(id=alice))
    assert conflict.value.status_code == 409
    no_key = body.model_copy(deep=True)
    no_key.chat_id = uuid4()
    del directus.keys[hash_id(bob)]
    with pytest.raises(HTTPException) as pending:
        await direct_chats.get_member_chat_encryption_key(team_id, hash_id(bob), request, None,
                                                           SimpleNamespace(id=alice))
    assert pending.value.status_code == 404
    assert pending.value.detail == "CHAT_ENCRYPTION_KEY_PENDING"
    with pytest.raises(HTTPException) as pending:
        await direct_chats.create_direct_chat(team_id, no_key, request, None, SimpleNamespace(id=alice))
    assert pending.value.status_code == 409
    directus.keys[hash_id(bob)] = {"hashed_user_id": hash_id(bob), **_key(2),
                                   "algorithm": "x25519-xsalsa20poly1305", "version": 1}
    own_key_response = await direct_chats.get_own_chat_encryption_key(request, None, SimpleNamespace(id=alice))
    assert own_key_response["key"]["encrypted_private_key"] == "cipher-1"
    peer_public_response = await direct_chats.get_member_chat_encryption_key(team_id, hash_id(bob), request, None,
                                                                              SimpleNamespace(id=alice))
    assert peer_public_response == {"key_id": _key(2)["key_id"], "public_key": _key(2)["public_key"]}
    assert "encrypted_private_key" not in peer_public_response
    self_dm = body.model_copy(deep=True)
    self_dm.chat_id = uuid4()
    self_dm.recipient_user_hash = hash_id(alice)
    with pytest.raises(HTTPException) as denied:
        await direct_chats.create_direct_chat(team_id, self_dm, request, None, SimpleNamespace(id=alice))
    assert denied.value.status_code == 400
    wrong_key = body.model_copy(deep=True)
    wrong_key.chat_id = uuid4()
    wrong_key.participant_key_envelopes[hash_id(bob)].key_id = _key(5)["key_id"]
    with pytest.raises(HTTPException) as conflict:
        await direct_chats.create_direct_chat(team_id, wrong_key, request, None, SimpleNamespace(id=alice))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as denied:
        await direct_chats.create_direct_chat(team_id, body, request, None, SimpleNamespace(id=stranger))
    assert denied.value.status_code == 403


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.member-entry-and-notifications
@pytest.mark.asyncio
@pytest.mark.parametrize("push_enabled", [False, True])
async def test_new_dm_notification_is_recipient_only_and_content_free(monkeypatch, push_enabled):
    from backend.core.api.app.services import chat_email_notification_service, team_realtime_service

    calls = {"events": [], "websocket": [], "email": [], "push": []}

    class Events:
        def __init__(self, _cache):
            pass

        async def store_and_publish(self, event):
            calls["events"].append(event.public_dict())

    async def broadcast(**kwargs):
        calls["websocket"].append(kwargs)

    async def email(**kwargs):
        calls["email"].append(kwargs)

    def push(**kwargs):
        calls["push"].append(kwargs)

    class RecipientDirectus:
        async def get_user_fields_direct(self, *_args, **_kwargs):
            return {"push_notification_enabled": push_enabled,
                    "push_notification_subscription": "recipient-subscription",
                    "push_notification_preferences": {"aiResponses": True}}

    class Cache:
        async def get_user_by_id(self, _user_id):
            return None

    monkeypatch.setattr(direct_chat_notification_service, "NotificationEventService", Events)
    monkeypatch.setattr(team_realtime_service, "broadcast_team_event", broadcast)
    monkeypatch.setattr(chat_email_notification_service, "enqueue_chat_email", email)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config",
                        SimpleNamespace(app=SimpleNamespace(send_task=push)))
    chat_id = str(uuid4())
    team_id = "team"
    metadata = {
        "id": chat_id, "hashed_team_id": hash_id(team_id), "chat_visibility": "direct",
        "participant_user_hashes": [hash_id("alice"), hash_id("bob")],
        "participant_key_envelopes": {
            hash_id("alice"): {"key_id": _key(1)["key_id"], "encrypted_chat_key": "OMDM1." + "a" * 32},
            hash_id("bob"): {"key_id": _key(2)["key_id"], "encrypted_chat_key": "OMDM1." + "b" * 32},
        },
        "encrypted_chat_key": None,
    }
    recipient_chat = project_direct_chat_metadata(metadata, "bob")
    recipient_chat["team_id"] = team_id
    app = SimpleNamespace(state=SimpleNamespace(cache_service=Cache(), directus_service=RecipientDirectus(),
                                                 encryption_service=object()))
    await direct_chat_notification_service.notify_new_direct_chat(
        app, recipient_id="bob", team_id=team_id, chat_id=chat_id, recipient_chat=recipient_chat,
    )
    assert len(calls["events"]) == len(calls["websocket"]) == len(calls["email"]) == 1
    assert calls["events"][0]["routing"] == {"team_id": team_id, "chat_id": chat_id}
    assert "encrypted_chat_key" not in str(calls["events"][0])
    assert calls["websocket"][0]["active_member_hashes"] == (hash_id("bob"),)
    assert calls["websocket"][0]["payload"]["chat"]["encrypted_chat_key"] == "OMDM1." + "b" * 32
    assert "participant_key_envelopes" not in calls["websocket"][0]["payload"]["chat"]
    assert calls["email"][0]["user_id"] == "bob"
    assert "preview" not in calls["email"][0] and "title" not in calls["email"][0]
    assert len(calls["push"]) == int(push_enabled)
    if push_enabled:
        payload = calls["push"][0]["kwargs"]
        assert payload["user_id"] == "bob"
        assert payload["url"] == f"/#chat-id={chat_id}&team-id={team_id}"
        assert payload["body"] == "You have a new direct chat."
        assert "encrypted_chat_key" not in str(payload)
        assert "participant_key_envelopes" not in str(payload)


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
@pytest.mark.asyncio
async def test_first_party_gate_rejects_generic_developer_key(monkeypatch):
    async def authenticate(**kwargs):
        kwargs["request"].state.auth_info = {"auth_source": "api_key", "user_id": "alice"}
        return SimpleNamespace(id="alice")

    monkeypatch.setattr(direct_chats, "get_current_user_or_api_key", authenticate)
    state = SimpleNamespace(directus_service=object(), cache_service=object())
    request = SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace(), cookies={})
    with pytest.raises(HTTPException) as denied:
        await direct_chats._first_party_user(request, None)
    assert denied.value.status_code == 403

    async def approved(**kwargs):
        kwargs["request"].state.auth_info = {"auth_source": "api_key", "user_id": "alice", "device_hash": "device"}
        return SimpleNamespace(id="alice")

    monkeypatch.setattr(direct_chats, "get_current_user_or_api_key", approved)
    assert (await direct_chats._first_party_user(request, None)).id == "alice"
