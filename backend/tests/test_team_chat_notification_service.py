"""Committed Team message mail and explicit-preview consent boundaries."""

import base64

import pytest

from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.services import team_chat_notification_service as service


class Redis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


class Cache:
    def __init__(self):
        self.redis = Redis()

    @property
    async def client(self):
        return self.redis


class Team:
    async def require_team_role(self, team_id, user_id, allowed):
        if team_id != "team-1" or user_id != "alice":
            raise PermissionError()

    async def list_active_member_hashes(self, team_id):
        return {hash_id(name) for name in ("alice", "bob", "carol")}


class Chat:
    async def get_chat_metadata(self, chat_id, admin_required=False):
        return {"hashed_team_id": hash_id("team-1" if chat_id == "chat-1" else "other")}


class Directus:
    team = Team()
    chat = Chat()

    async def get_user_id_from_hashed_user_id(self, member_hash):
        return next((name for name in ("alice", "bob", "carol") if hash_id(name) == member_hash), None)

    async def get_items(self, collection, params, **kwargs):
        if collection == "teams" and params.get("filter[hashed_team_id][_eq]") == hash_id("team-1"):
            return [{"team_id": "team-1", "hashed_team_id": hash_id("team-1")}]
        return []

    async def get_user_fields_direct(self, user_id, fields, *, no_cache=False):
        if user_id == "alice":
            return {"id": "alice", "encrypted_username": "encrypted name", "vault_key_id": "alice-key"}
        return None


class Encryption:
    async def encrypt_with_user_key(self, plaintext, key):
        return "sealed:" + key + ":" + base64.b64encode(plaintext.encode()).decode(), None

    async def decrypt_with_user_key(self, ciphertext, key):
        if ciphertext == "encrypted name":
            return "Alice\r\nInjected"
        prefix = "sealed:" + key + ":"
        assert ciphertext.startswith(prefix)
        return base64.b64decode(ciphertext[len(prefix):]).decode()


def _user(user_id, *, enabled=True, include_content=False):
    return {"id": user_id, "email_notifications_enabled": enabled,
            "email_notification_preferences": {"aiResponses": True, "includeContent": include_content},
            "email_notification_preference_choices": {
                "includeContent": {"value": include_content, "source": "user"},
            },
            "vault_key_id": user_id + "-key"}


# contract-test: supporting surface=rest_api assertions=teams.chat.member-mentions-notify,teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_preview_requires_scope_and_explicit_recipient_consent(monkeypatch):
    users = {"bob": _user("bob", include_content=True), "carol": _user("carol")}
    async def load(_, user_id):
        return users.get(user_id)
    monkeypatch.setattr(service, "load_notification_user", load)
    cache = Cache()
    directus = Directus()
    with pytest.raises(PermissionError):
        await service.issue_preview_capability(directus=directus, cache=cache, team_id="team-1", chat_id="foreign-chat", sender_id="alice")
    capability = await service.issue_preview_capability(directus=directus, cache=cache, team_id="team-1", chat_id="chat-1", sender_id="alice")
    assert capability["recipient_count"] == 1
    staged = await service.stage_team_preview(
        directus=directus, cache=cache, encryption=Encryption(),
        team_id="team-1", chat_id="chat-1", message_id="msg-1", sender_id="alice",
        capability_id=capability["capability_id"], preview="private message",
    )
    assert staged == 1
    assert all("private message" not in str(value) for value in cache.redis.values.values())
    assert service._preview_key("team-1", "chat-1", "msg-1", "alice", "carol") not in cache.redis.values


# contract-test: supporting surface=rest_api assertions=teams.chat.member-mentions-notify,teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_commit_fans_out_to_active_recipients_only_and_consumes_preview(monkeypatch):
    users = {"bob": _user("bob", include_content=True), "carol": _user("carol")}
    async def load(_, user_id):
        return users.get(user_id)
    monkeypatch.setattr(service, "load_notification_user", load)
    calls = []
    async def enqueue(**kwargs):
        calls.append(kwargs)
        return True
    from backend.core.api.app.services import chat_email_notification_service
    monkeypatch.setattr(chat_email_notification_service, "enqueue_chat_email", enqueue)
    cache = Cache()
    directus = Directus()
    capability = await service.issue_preview_capability(directus=directus, cache=cache, team_id="team-1", chat_id="chat-1", sender_id="alice")
    await service.stage_team_preview(
        directus=directus, cache=cache, encryption=Encryption(), team_id="team-1", chat_id="chat-1",
        message_id="msg-1", sender_id="alice", capability_id=capability["capability_id"], preview="private message",
    )
    count = await service.queue_committed_team_message(
        directus=directus, cache=cache, encryption=Encryption(), team_id="team-1",
        chat_id="chat-1", message_id="msg-1", sender_id="alice",
    )
    assert count == 2
    assert {call["user_id"] for call in calls} == {"bob", "carol"}
    assert all(call["source"] == "team" and call["sender_user_id"] == "alice" for call in calls)
    assert next(call for call in calls if call["user_id"] == "bob")["preview"] == "private message"
    assert next(call for call in calls if call["user_id"] == "carol")["preview"] is None
    assert all(call["sender_name"] == "Alice Injected" for call in calls)
    assert service._preview_key("team-1", "chat-1", "msg-1", "alice", "bob") not in cache.redis.values


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked,teams.chat.member-mentions-notify
@pytest.mark.anyio
async def test_staged_preview_requires_matching_committed_chat_and_sender(monkeypatch):
    async def load(_, user_id):
        return _user("bob", include_content=True) if user_id == "bob" else None

    class ScopedTeam(Team):
        async def require_team_role(self, team_id, user_id, allowed):
            if team_id != "team-1" or user_id not in {"alice", "carol"}:
                raise PermissionError()

    class ScopedChat(Chat):
        async def get_chat_metadata(self, chat_id, admin_required=False):
            return {"hashed_team_id": hash_id("team-1" if chat_id in {"chat-1", "chat-2"} else "other")}

    directus = Directus()
    directus.team = ScopedTeam()
    directus.chat = ScopedChat()
    cache = Cache()
    encryption = Encryption()
    calls = []

    async def enqueue(**kwargs):
        if kwargs["user_id"] == "bob":
            calls.append(kwargs)
        return True

    from backend.core.api.app.services import chat_email_notification_service
    monkeypatch.setattr(service, "load_notification_user", load)
    monkeypatch.setattr(chat_email_notification_service, "enqueue_chat_email", enqueue)

    capability = await service.issue_preview_capability(
        directus=directus, cache=cache, team_id="team-1", chat_id="chat-1", sender_id="alice",
    )
    assert await service.stage_team_preview(
        directus=directus, cache=cache, encryption=encryption, team_id="team-1",
        chat_id="chat-1", message_id="shared-id", sender_id="alice",
        capability_id=capability["capability_id"], preview="private preview",
    ) == 1
    staged_key = service._preview_key("team-1", "chat-1", "shared-id", "alice", "bob")

    for chat_id, sender_id in (("chat-2", "alice"), ("chat-1", "carol")):
        await service.queue_committed_team_message(
            directus=directus, cache=cache, encryption=encryption, team_id="team-1",
            chat_id=chat_id, message_id="shared-id", sender_id=sender_id,
        )
        assert calls[-1]["preview"] is None
        assert staged_key in cache.redis.values

    await service.queue_committed_team_message(
        directus=directus, cache=cache, encryption=encryption, team_id="team-1",
        chat_id="chat-1", message_id="shared-id", sender_id="alice",
    )
    assert calls[-1]["preview"] == "private preview"
    assert staged_key not in cache.redis.values


# contract-test: supporting surface=rest_api assertions=teams.chat.member-mentions-notify
@pytest.mark.anyio
async def test_password_only_member_resolves_from_id_only_page():
    class PasswordOnlyDirectus(Directus):
        def __init__(self):
            self.queries = []

        async def get_user_id_from_hashed_user_id(self, member_hash):
            return None

        async def get_items(self, collection, params, **kwargs):
            self.queries.append((collection, params, kwargs))
            return [{"id": "alice"}, {"id": "bob"}, {"id": "carol"}]

    directus = PasswordOnlyDirectus()
    recipients = await service.active_team_recipient_ids(directus, "team-1", "alice")
    assert set(recipients) == {"bob", "carol"}
    assert directus.queries == [
        ("directus_users", {"fields": "id", "page": 1, "limit": 200},
         {"no_cache": True, "admin_required": True}),
    ]


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_preview_opt_out_after_capability_prevents_staging(monkeypatch):
    user = _user("bob", include_content=True)
    async def load(_, user_id):
        return user if user_id == "bob" else None
    monkeypatch.setattr(service, "load_notification_user", load)
    cache = Cache()
    directus = Directus()
    capability = await service.issue_preview_capability(
        directus=directus, cache=cache, team_id="team-1", chat_id="chat-1", sender_id="alice",
    )
    user["email_notification_preference_choices"]["includeContent"]["value"] = False
    staged = await service.stage_team_preview(
        directus=directus, cache=cache, encryption=Encryption(),
        team_id="team-1", chat_id="chat-1", message_id="msg-1", sender_id="alice",
        capability_id=capability["capability_id"], preview="sensitive",
    )
    assert staged == 0
    assert service._preview_key("team-1", "chat-1", "msg-1", "alice", "bob") not in cache.redis.values


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_completed_mate_team_response_includes_initiator_and_active_peers(monkeypatch):
    users = {"alice": _user("alice"), "bob": _user("bob", include_content=True),
             "carol": _user("carol", enabled=False)}
    async def load(_, user_id):
        return users.get(user_id)
    monkeypatch.setattr(service, "load_notification_user", load)
    calls = []
    async def enqueue(**kwargs):
        calls.append(kwargs)
        return True
    from backend.core.api.app.services import chat_email_notification_service
    monkeypatch.setattr(chat_email_notification_service, "enqueue_chat_email", enqueue)
    handled = await service.queue_completed_team_mate_response(
        directus=Directus(), cache=Cache(), encryption=Encryption(),
        initiating_user_id="alice", chat_id="chat-1", message_id="mate-1",
        mate_category="general", preview="Mate response", title="Private Team chat",
    )
    assert handled is True
    assert {call["user_id"] for call in calls} == {"alice", "bob"}
    assert all(call["source"] == "chat" and call["team_id"] == "team-1"
               and call.get("sender_user_id") is None for call in calls)
    assert all(call["mate_category"] == "general" for call in calls)
    assert next(call for call in calls if call["user_id"] == "alice")["preview"] is None
    assert next(call for call in calls if call["user_id"] == "bob")["preview"] == "Mate response"


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_completed_mate_team_response_denies_removed_initiator_and_private_fallback(monkeypatch):
    from backend.core.api.app.services import chat_email_notification_service
    calls = []
    async def enqueue(**kwargs):
        calls.append(kwargs)
        return True
    monkeypatch.setattr(chat_email_notification_service, "enqueue_chat_email", enqueue)
    handled = await service.queue_completed_team_mate_response(
        directus=Directus(), cache=Cache(), encryption=Encryption(),
        initiating_user_id="removed", chat_id="chat-1", message_id="mate-2",
    )
    assert handled is True
    assert calls == []

    class PrivateChat:
        async def get_chat_metadata(self, chat_id, admin_required=False):
            return {"hashed_team_id": None}
    private_directus = Directus()
    private_directus.chat = PrivateChat()
    handled = await service.queue_completed_team_mate_response(
        directus=private_directus, cache=Cache(), encryption=Encryption(),
        initiating_user_id="alice", chat_id="personal-chat", message_id="mate-3",
    )
    assert handled is False
    assert calls == []


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_completed_mate_response_excludes_revoked_member(monkeypatch):
    users = {name: _user(name) for name in ("alice", "bob", "carol")}
    async def load(_, user_id):
        return users.get(user_id)
    monkeypatch.setattr(service, "load_notification_user", load)
    calls = []
    async def enqueue(**kwargs):
        calls.append(kwargs)
        return True
    from backend.core.api.app.services import chat_email_notification_service
    monkeypatch.setattr(chat_email_notification_service, "enqueue_chat_email", enqueue)

    class RevokedTeam(Team):
        async def list_active_member_hashes(self, team_id):
            return {hash_id("alice"), hash_id("carol")}
    directus = Directus()
    directus.team = RevokedTeam()
    handled = await service.queue_completed_team_mate_response(
        directus=directus, cache=Cache(), encryption=Encryption(),
        initiating_user_id="alice", chat_id="chat-1", message_id="mate-4",
    )
    assert handled is True
    assert {call["user_id"] for call in calls} == {"alice", "carol"}
