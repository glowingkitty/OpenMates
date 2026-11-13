# contract-test-file: infrastructure
# backend/tests/test_app_settings_memories_continuation.py
#
# Regression tests for app settings/memories permission continuations.
# These continuations restart the normal AI ask pipeline after a user confirms
# memory access, so request-level context must survive while message history
# remains in the encrypted chat cache.

import asyncio
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace

cache_stub = ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
directus_stub = ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
encryption_stub = ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)
sys.modules.setdefault("backend.core.api.app.services.directus", directus_stub)
sys.modules.setdefault("backend.core.api.app.utils.encryption", encryption_stub)

handler = importlib.import_module(
    "backend.core.api.app.routes.handlers.websocket_handlers.app_settings_memories_confirmed_handler"
)


class _FakeApplyAsyncTask:
    def __init__(self):
        self.calls = []

    def apply_async(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="continuation-task-1")


class _FakeCache:
    def __init__(self, pending_extra=None):
        self.deleted = []
        self.active = None
        self.pending_extra = pending_extra or {}

    async def try_claim_active_ai_task(self, chat_id, task_id, ttl=600):
        if self.active is not None:
            return False
        self.active = task_id
        return True

    async def transfer_active_ai_task(self, chat_id, prior_task_id, next_task_id):
        if self.active != prior_task_id:
            return False
        self.active = next_task_id
        return True

    async def get_pending_app_settings_memories_request(self, chat_id):
        assert chat_id == "chat-1"
        return {
            "task_id": "original-task-1",
            "recovery_inference_task_id": "original-task-1",
            "recovery_preflight_id": "preflight-1",
            "root_legacy_cutover_task_id": "legacy-root-1",
            "recovery_turn_id": "turn-1",
            "recovery_public_key": "public-key-1",
            "chat_key_version": 1,
            "chat_id": "chat-1",
            "message_id": "message-1",
            "preprocessing_resume_ref": "server-owned-routing-ref",
            "user_id_hash": "user-hash-1",
            "mate_id": "mate-1",
            "active_focus_id": "focus-1",
            "chat_has_title": True,
            "is_incognito": False,
            "requested_keys": ["code:preferred_technologies"],
            "user_preferences": {
                "default_ai_model_simple": "mistral/mistral-small-latest",
                "timezone": "Europe/Berlin",
            },
            "current_chat_title": "Coding help",
            "embed_file_path_index": {"snippet.py": "embed-1"},
            "has_image_upload_embed": True,
            **self.pending_extra,
        }

    async def get_ai_messages_history(self, user_id, chat_id):
        assert user_id == "user-1"
        assert chat_id == "chat-1"
        return [
            json.dumps(
                {
                    "role": "user",
                    "encrypted_content": "encrypted-user-message",
                    "created_at": 123,
                    "sender_name": "User",
                }
            )
        ]

    async def get_user_vault_key_id(self, user_id):
        assert user_id == "user-1"
        return "vault-key-1"

    async def delete_pending_app_settings_memories_request(self, chat_id, user_id=None):
        self.deleted.append((chat_id, user_id))
        return True


class _FakeEncryption:
    async def decrypt_with_user_key(self, encrypted_content, user_vault_key_id):
        assert encrypted_content == "encrypted-user-message"
        assert user_vault_key_id == "vault-key-1"
        return "Use my code preferences."


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
def test_app_settings_memories_continuation_preserves_request_context(monkeypatch):
    fake_task = _FakeApplyAsyncTask()
    fake_task_module = ModuleType("backend.apps.ai.tasks.ask_skill_task")
    fake_task_module.process_ai_skill_ask_task = fake_task
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.ask_skill_task", fake_task_module)
    monkeypatch.setattr(handler, "_load_ask_skill_config_from_app_yml", lambda: {"default_llms": {}})

    cache = _FakeCache()
    asyncio.run(
        handler._trigger_continuation(
            cache_service=cache,
            directus_service=SimpleNamespace(),
            encryption_service=_FakeEncryption(),
            user_id="user-1",
            chat_id="chat-1",
            device_fingerprint_hash="device-1",
            is_rejection=False,
        )
    )

    assert len(fake_task.calls) == 1
    request_payload = fake_task.calls[0]["kwargs"]["request_data_dict"]
    assert request_payload["user_preferences"] == {
        "default_ai_model_simple": "mistral/mistral-small-latest",
        "timezone": "Europe/Berlin",
    }
    assert request_payload["current_user_content"] == "Use my code preferences."
    assert request_payload["current_chat_title"] == "Coding help"
    assert request_payload["embed_file_path_index"] == {"snippet.py": "embed-1"}
    assert request_payload["has_image_upload_embed"] is True
    assert request_payload["app_settings_memories_metadata"] == ["code-preferred_technologies"]
    assert request_payload["is_app_settings_memories_continuation"] is True
    assert request_payload["preprocessing_resume_ref"] == "server-owned-routing-ref"
    assert cache.deleted == [("chat-1", "user-1")]

    assert request_payload["recovery_inference_task_id"] == "original-task-1"
    assert request_payload["recovery_preflight_id"] == "preflight-1"
    assert request_payload["root_legacy_cutover_task_id"] == "legacy-root-1"
    assert request_payload["recovery_turn_id"] == "turn-1"
    assert request_payload["recovery_public_key"] == "public-key-1"
    assert request_payload["chat_key_version"] == 1
    assert not request_payload.get("recovery_task_id")
    # The continuation owns the chat's active marker under its dispatched id.
    assert cache.active == fake_task.calls[0]["task_id"]


_CALL_TURN = {
    "auto_speak_response": True,
    "voice_mode": True,
    "voice_call_id": "a" * 32,
    "voice_turn_id": "message-1",
    "voice_heard_boundary": None,
    "assistant_speech_lazy_dispatch": False,
    "assistant_response_source_revision": 3,
}


def _continuation_payload(monkeypatch, cache):
    fake_task = _FakeApplyAsyncTask()
    fake_task_module = ModuleType("backend.apps.ai.tasks.ask_skill_task")
    fake_task_module.process_ai_skill_ask_task = fake_task
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.ask_skill_task", fake_task_module)
    monkeypatch.setattr(handler, "_load_ask_skill_config_from_app_yml", lambda: {"default_llms": {}})
    asyncio.run(handler._trigger_continuation(
        cache_service=cache, directus_service=SimpleNamespace(), encryption_service=_FakeEncryption(),
        user_id="user-1", chat_id="chat-1", device_fingerprint_hash="device-1", is_rejection=False,
    ))
    assert len(fake_task.calls) == 1
    return fake_task.calls[0]["kwargs"]["request_data_dict"]


# contract-test: supporting surface=rest_api assertions=video-call.audio.localized-waiting
def test_paused_call_turn_stores_its_spoken_delivery_for_the_continuation():
    from backend.apps.ai.processing.memory_permission_request import (
        build_pending_app_settings_memories_context,
    )

    request = SimpleNamespace(
        chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="user-hash-1",
        mate_id=None, active_focus_id=None, chat_has_title=False, current_chat_title=None,
        is_incognito=False, user_preferences={}, embed_file_path_index=None,
        voice_heard_boundary=SimpleNamespace(model_dump=lambda mode: {"message_id": "prior", "heard_chars": 12}),
        **{key: value for key, value in _CALL_TURN.items() if key != "voice_heard_boundary"},
    )
    context = build_pending_app_settings_memories_context(
        request_data=request, request_id="request-1", missing_keys=["memory:personal"], task_id="task-1",
    )
    assert {key: context[key] for key in _CALL_TURN} == _CALL_TURN | {
        "voice_heard_boundary": {"message_id": "prior", "heard_chars": 12},
    }
    json.dumps(context)


# contract-test: supporting surface=rest_api assertions=video-call.audio.localized-waiting
def test_memory_approval_during_an_active_call_continues_as_the_same_spoken_turn(monkeypatch):
    from backend.shared.python_utils import voice_call_admission

    rechecked = []

    async def active_call(cache, request):
        rechecked.append(request)

    monkeypatch.setattr(voice_call_admission, "require_active_voice_dispatch", active_call)
    payload = _continuation_payload(monkeypatch, _FakeCache(_CALL_TURN))

    assert {key: payload[key] for key in _CALL_TURN} == _CALL_TURN
    assert payload["is_app_settings_memories_continuation"] is True
    # The call is rechecked for the exact owner, chat and turn before dispatch.
    assert rechecked[0]["user_id"] == "user-1" and rechecked[0]["chat_id"] == "chat-1"
    assert rechecked[0]["message_id"] == rechecked[0]["voice_turn_id"] == "message-1"


# contract-test: supporting surface=rest_api assertions=video-call.audio.localized-waiting
def test_memory_approval_after_the_call_ended_continues_as_a_text_turn(monkeypatch):
    from backend.shared.python_utils import voice_call_admission

    async def ended_call(cache, request):
        raise ValueError("Voice call has ended")

    monkeypatch.setattr(voice_call_admission, "require_active_voice_dispatch", ended_call)
    payload = _continuation_payload(monkeypatch, _FakeCache(_CALL_TURN))

    assert payload["voice_mode"] is False and payload["auto_speak_response"] is False
    assert payload["voice_call_id"] is None and payload["voice_turn_id"] is None
    assert payload["assistant_response_source_revision"] == 3


# contract-test: supporting surface=rest_api assertions=video-call.audio.localized-waiting
def test_typed_turn_continuation_keeps_its_own_speech_preference(monkeypatch):
    payload = _continuation_payload(monkeypatch, _FakeCache({"auto_speak_response": True}))

    assert payload["auto_speak_response"] is True
    assert payload["voice_mode"] is False and payload["voice_call_id"] is None
    assert payload["assistant_response_source_revision"] == 1
