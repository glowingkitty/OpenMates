# backend/tests/test_app_settings_memories_continuation.py
#
# Regression tests for app settings/memories permission continuations.
# These continuations restart the normal AI ask pipeline after a user confirms
# memory access, so request-level context must survive while message history
# remains in the encrypted chat cache.

import json
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

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
    def __init__(self):
        self.deleted = []

    async def get_pending_app_settings_memories_request(self, chat_id):
        assert chat_id == "chat-1"
        return {
            "task_id": "original-task-1",
            "chat_id": "chat-1",
            "message_id": "message-1",
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


@pytest.mark.asyncio
async def test_app_settings_memories_continuation_preserves_request_context(monkeypatch):
    fake_task = _FakeApplyAsyncTask()
    fake_task_module = ModuleType("backend.apps.ai.tasks.ask_skill_task")
    fake_task_module.process_ai_skill_ask_task = fake_task
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.ask_skill_task", fake_task_module)
    monkeypatch.setattr(handler, "_load_ask_skill_config_from_app_yml", lambda: {"default_llms": {}})

    cache = _FakeCache()
    await handler._trigger_continuation(
        cache_service=cache,
        directus_service=SimpleNamespace(),
        encryption_service=_FakeEncryption(),
        user_id="user-1",
        chat_id="chat-1",
        device_fingerprint_hash="device-1",
        is_rejection=False,
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
    assert request_payload["app_settings_memories_metadata"] == ["code-preferred_technologies"]
    assert request_payload["is_app_settings_memories_continuation"] is True
    assert cache.deleted == [("chat-1", "user-1")]
