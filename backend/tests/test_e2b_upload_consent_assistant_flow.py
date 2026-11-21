"""Assistant path of the E2B upload consent: pause, answer, continuation, declined result."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import e2b_upload_consent_request as pending
from backend.core.api.app.services import e2b_upload_consent as consent
from backend.core.api.app.routes.handlers.websocket_handlers import e2b_upload_consent_answer_handler as handler

FIELD, AT = consent.CONSENT_FIELD, consent.CONSENT_AT_FIELD


class FakeRedis:
    def __init__(self):
        self.store, self.published = {}, []

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)

    async def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))


class FakeCache:
    def __init__(self):
        self.redis = FakeRedis()

    @property
    def client(self):
        async def _get():
            return self.redis
        return _get()

    async def get_user_vault_key_id(self, user_id):
        return "vault-1"


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext, key_id):
        return "enc:" + plaintext, "v1"

    async def decrypt_with_user_key(self, ciphertext, key_id):
        return ciphertext.removeprefix("enc:")


class FakeChat:
    async def check_chat_ownership(self, chat_id, user_id):
        return chat_id == "chat-1" and user_id == "user-1"


class FakeDirectus:
    chat = FakeChat()

    def __init__(self, fields=None):
        self.fields = dict(fields or {})

    async def get_user_fields_direct(self, user_id, fields, *, no_cache=False):
        return {name: self.fields.get(name) for name in fields}

    async def update_user(self, user_id, data):
        self.fields.update(data)
        return True

    async def get_user_profile(self, user_id):
        return True, {"vault_key_id": "vault-1"}


class FakeManager:
    def __init__(self):
        self.sent = []

    async def send_personal_message(self, message, user_id, device):
        self.sent.append(message)


REQUEST = SimpleNamespace(
    user_id="user-1", user_id_hash="hash-1", chat_id="chat-1", message_id="msg-1",
    preprocessing_resume_ref=None, team_id=None, team_role=None,
)


async def _gate(cache, directus):
    return await pending.gate_e2b_upload_before_skill(
        request_data=REQUEST, cache_service=cache, encryption_service=FakeEncryption(),
        directus_service=directus, user_vault_key_id="vault-1", task_id="task-1",
    )


@pytest.fixture
def queued(monkeypatch):
    calls = []

    class FakeTask:
        @staticmethod
        def apply_async(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id="task-cont")

    monkeypatch.setitem(
        sys.modules, "backend.apps.ai.tasks.ask_skill_task", SimpleNamespace(process_ai_skill_ask_task=FakeTask)
    )
    monkeypatch.setattr(handler, "_load_ask_skill_config_from_app_yml", lambda: {})

    async def history(**kwargs):
        return [{"role": "user", "content": "run it"}]

    monkeypatch.setattr(handler, "_load_cached_message_history", history)
    return calls


async def _answer(cache, directus, manager, **payload):
    base = {"request_id": "req-1", "chat_id": "chat-1", "choice": "allow"}
    await handler.handle_e2b_upload_consent_answer(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=FakeEncryption(), user_id="user-1", device_fingerprint_hash="d1",
        payload={**base, **payload},
    )


async def _seed_pending(cache, request_id="req-1"):
    await pending.store_pending_context(
        cache_service=cache, encryption_service=FakeEncryption(), vault_key_id="vault-1", chat_id="chat-1",
        context={"request_id": request_id, "chat_id": "chat-1", "message_id": "msg-1", "user_id": "user-1",
                 "user_id_hash": "hash-1"},
    )


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_no_decision_publishes_request_and_pauses_without_queueing(queued):
    cache = FakeCache()
    gate = await _gate(cache, FakeDirectus())
    assert gate.kind == "paused" and gate.request_id
    channel, event = cache.redis.published[0]
    assert channel == "user_cache_events:user-1"
    assert event["event_type"] == "send_e2b_upload_consent_request"
    assert event["payload"] == {"request_id": gate.request_id, "chat_id": "chat-1", "version": 1}
    stored = cache.redis.store["pending_e2b_upload_consent:chat-1"]
    assert stored.startswith("enc:")
    assert queued == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_allow_records_allowed_queues_continuation_and_gate_proceeds(queued):
    cache, directus, manager = FakeCache(), FakeDirectus(), FakeManager()
    await _seed_pending(cache)
    await _answer(cache, directus, manager, choice="allow")
    assert directus.fields[FIELD] == "allowed"
    assert len(queued) == 1
    assert queued[0]["kwargs"]["request_data_dict"]["is_connected_account_permission_continuation"] is True
    assert queued[0]["kwargs"]["request_data_dict"]["is_e2b_upload_consent_continuation"] is True
    assert "pending_e2b_upload_consent:chat-1" not in cache.redis.store
    updated = [e for _, e in cache.redis.published if e["event_type"] == "send_e2b_upload_consent_updated"]
    assert updated[0]["payload"]["decision"] == "allowed" and updated[0]["payload"]["version"] == 1
    assert (await _gate(cache, directus)).kind == "allowed"


@pytest.mark.parametrize("choice", ["not_now", "own_machine"])
@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_decline_choices_record_declined_and_continuation_gets_declined_result(queued, choice):
    cache, directus, manager = FakeCache(), FakeDirectus(), FakeManager()
    await _seed_pending(cache)
    await _answer(cache, directus, manager, choice=choice)
    assert directus.fields[FIELD] == "declined"
    assert len(queued) == 1
    before = len(cache.redis.published)
    gate = await _gate(cache, directus)
    assert gate.kind == "declined"
    assert len(cache.redis.published) == before  # no new request
    result = pending.declined_tool_result()
    assert result["status"] == "e2b_consent_declined"
    assert "openmates remote-access" in result["reason"]


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_unknown_choice_is_rejected_and_nothing_recorded(queued):
    cache, directus, manager = FakeCache(), FakeDirectus(), FakeManager()
    await _seed_pending(cache)
    await _answer(cache, directus, manager, choice="always")
    assert FIELD not in directus.fields
    assert queued == []
    assert manager.sent[0]["type"] == "error"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_mismatched_request_id_and_unowned_chat_are_rejected(queued):
    cache, directus, manager = FakeCache(), FakeDirectus(), FakeManager()
    await _seed_pending(cache)
    await _answer(cache, directus, manager, request_id="other")
    await _answer(cache, directus, manager, chat_id="chat-9")
    assert FIELD not in directus.fields
    assert queued == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_expired_context_only_records_the_decision(queued):
    cache, directus, manager = FakeCache(), FakeDirectus(), FakeManager()
    await _answer(cache, directus, manager, choice="allow")
    assert directus.fields[FIELD] == "allowed"
    assert queued == []
