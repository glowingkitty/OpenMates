"""Authenticated, source-fenced storage of client-encrypted composer suggestions."""

import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.suggested_followup_metadata_handler import (
    handle_suggested_followup_metadata,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id


USER = "owner-id"
CHAT = "chat-id"
ASSISTANT = "assistant-id"
TASK = "task-id"
USER_MESSAGE = "user-message-id"
CIPHERTEXT = base64.b64encode(b"OM" + b"a" * 40).decode()


class Manager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device_hash):
        self.sent.append(message)

    async def broadcast_to_user(self, *, message, user_id, exclude_device_hash):
        self.broadcasts.append(message)


class Cache:
    def __init__(self):
        self.history = [json.dumps({"id": ASSISTANT, "role": "assistant", "created_at": 20})]
        self.active_task = None
        self.updates = []

    async def get_ai_messages_history(self, user_id, chat_id, start, end):
        assert (user_id, chat_id, start, end) == (USER, CHAT, -1, -1)
        return self.history

    async def get_active_ai_task(self, chat_id):
        return self.active_task

    async def update_chat_list_item_field(self, user_id, chat_id, field, value):
        self.updates.append((user_id, chat_id, field, value))
        return True


class Directus:
    def __init__(self):
        self.chat_row = {
            "hashed_user_id": hashlib.sha256(USER.encode()).hexdigest(),
            "hashed_team_id": None,
            "encrypted_chat_key": "wrapped-chat-key",
        }
        self.messages = [{"client_message_id": "old-id", "role": "assistant", "created_at": 10}]
        self.updates = []
        self.role_allowed = True
        self.chat = SimpleNamespace(
            get_chat_metadata=self.get_chat_metadata,
            update_chat_fields_in_directus=self.update_chat_fields_in_directus,
        )
        self.team = SimpleNamespace(require_team_role=self.require_team_role)

    async def get_chat_metadata(self, chat_id, admin_required=False):
        assert admin_required
        return self.chat_row

    async def update_chat_fields_in_directus(self, chat_id, fields):
        self.updates.append((chat_id, fields))
        return True

    async def get_items(self, collection, params, admin_required=False):
        assert collection == "messages" and admin_required
        return self.messages

    async def require_team_role(self, team_id, user_id, roles):
        if not self.role_allowed:
            raise TeamPermissionError("denied")


def payload(**changes):
    data = {
        "chat_id": CHAT,
        "source_message_id": ASSISTANT,
        "source_task_id": TASK,
        "source_user_message_id": USER_MESSAGE,
        "encrypted_chat_key": "wrapped-chat-key",
        "encrypted_suggested_followup_message": CIPHERTEXT,
    }
    data.update(changes)
    return data


async def run(data=None, *, cache=None, directus=None):
    manager = Manager()
    cache = cache or Cache()
    directus = directus or Directus()
    await handle_suggested_followup_metadata(
        manager=manager, cache_service=cache, directus_service=directus,
        user_id=USER, device_fingerprint_hash="device-id", payload=data or payload(),
    )
    return manager, cache, directus


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
async def test_persists_only_ciphertext_and_fans_out_source_identity():
    manager, cache, directus = await run()
    assert directus.updates == [(CHAT, {"encrypted_suggested_followup_message": CIPHERTEXT})]
    assert cache.updates[0][2:] == ("encrypted_suggested_followup_message", CIPHERTEXT)
    assert manager.sent[0]["type"] == "encrypted_suggested_followup_message_stored"
    assert manager.broadcasts[0]["type"] == "encrypted_chat_metadata"
    assert manager.broadcasts[0]["payload"]["source_message_id"] == ASSISTANT
    assert "suggested_followup_message" not in manager.broadcasts[0]["payload"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
async def test_cache_miss_falls_back_to_latest_directus_assistant():
    cache = Cache()
    cache.history = []
    directus = Directus()
    directus.messages = [{"client_message_id": ASSISTANT, "role": "assistant", "created_at": 20}]
    manager, _, directus = await run(cache=cache, directus=directus)
    assert directus.updates
    assert manager.sent[0]["type"] == "encrypted_suggested_followup_message_stored"


@pytest.mark.asyncio
@pytest.mark.parametrize("change,code", [
    ({"suggested_followup_message": "plaintext"}, "invalid_suggested_followup_metadata"),
    ({"encrypted_suggested_followup_message": "plaintext"}, "invalid_suggested_followup_metadata"),
    ({"encrypted_chat_key": "stale-key"}, "chat_key_mismatch"),
    ({"source_message_id": "old-id"}, "stale_suggested_followup_source"),
])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
async def test_rejects_invalid_and_stale_writes(change, code):
    manager, _, directus = await run(payload(**change))
    assert manager.sent[0]["payload"]["code"] == code
    assert manager.sent[0]["type"] == (
        "encrypted_suggested_followup_message_not_stored"
        if code == "stale_suggested_followup_source" else "error"
    )
    assert not directus.updates
    assert not manager.broadcasts


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
async def test_newer_durable_user_turn_defeats_stale_cache_assistant():
    directus = Directus()
    directus.messages = [{"client_message_id": "new-user", "role": "user", "created_at": 21}]
    manager, _, directus = await run(directus=directus)
    assert manager.sent[0]["type"] == "encrypted_suggested_followup_message_not_stored"
    assert manager.sent[0]["payload"]["source_message_id"] == ASSISTANT
    assert manager.sent[0]["payload"]["source_task_id"] == TASK
    assert manager.sent[0]["payload"]["source_user_message_id"] == USER_MESSAGE
    assert manager.sent[0]["payload"]["code"] == "stale_suggested_followup_source"
    assert manager.sent[0]["payload"]["source_task_id"] == TASK
    assert not directus.updates


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
async def test_new_active_task_defeats_previous_completed_suggestion():
    cache = Cache()
    cache.active_task = "new-task-id"
    manager, _, directus = await run(cache=cache)
    assert manager.sent[0]["type"] == "encrypted_suggested_followup_message_not_stored"
    assert manager.sent[0]["payload"]["source_message_id"] == ASSISTANT
    assert manager.sent[0]["payload"]["source_task_id"] == TASK
    assert manager.sent[0]["payload"]["source_user_message_id"] == USER_MESSAGE
    assert manager.sent[0]["payload"]["code"] == "stale_suggested_followup_source"
    assert not directus.updates


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
async def test_personal_chat_owner_is_checked_fresh():
    directus = Directus()
    directus.chat_row["hashed_user_id"] = "another-owner"
    manager, _, directus = await run(directus=directus)
    assert manager.sent[0]["type"] == "error"
    assert manager.sent[0]["payload"]["code"] == "chat_permission_denied"
    assert not directus.updates


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
async def test_team_scope_and_role_are_required():
    directus = Directus()
    directus.chat_row["hashed_team_id"] = hash_id("team-id")
    manager, _, directus = await run(directus=directus)
    assert manager.sent[0]["payload"]["code"] == "team_chat_scope_mismatch"
    assert not directus.updates
    directus.role_allowed = False
    manager, _, directus = await run(payload(team_id="team-id"), directus=directus)
    assert manager.sent[0]["payload"]["code"] == "team_chat_permission_denied"
    assert not directus.updates


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
async def test_allowed_team_chat_stores_only_ciphertext():
    directus = Directus()
    directus.chat_row["hashed_team_id"] = hash_id("team-id")
    manager, _, directus = await run(payload(team_id="team-id"), directus=directus)
    assert directus.updates == [(CHAT, {"encrypted_suggested_followup_message": CIPHERTEXT})]
    assert manager.sent[0]["type"] == "encrypted_suggested_followup_message_stored"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
async def test_actual_storage_failure_is_not_reported_as_stale_result():
    directus = Directus()
    async def fail_storage(*args):
        return False
    directus.chat.update_chat_fields_in_directus = fail_storage
    with pytest.raises(RuntimeError, match="Could not store encrypted suggested follow-up metadata"):
        await run(directus=directus)
