# backend/tests/test_connected_account_permission_confirmed_handler.py
#
# Tests for connected-account permission confirmation handling. The handler must
# reject token-bearing confirmation payloads and dispatch continuation requests
# with only opaque token refs.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest


def import_handler_module():
    sys.modules.setdefault(
        "backend.apps.ai.tasks.ask_skill_task",
        SimpleNamespace(
            process_ai_skill_ask_task=SimpleNamespace(
                apply_async=lambda **kwargs: SimpleNamespace(id="task-continuation")
            )
        ),
    )
    return __import__(
        "backend.core.api.app.routes.handlers.websocket_handlers.connected_account_permission_confirmed_handler",
        fromlist=["handle_connected_account_permission_confirmed"],
    )


class FakeChatService:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return chat_id == "chat-1" and user_id == "user-1"


class FakeDirectus:
    chat = FakeChatService()

    async def get_user_profile(self, user_id: str):
        return True, {"vault_key_id": "vault-1"}


class FakeEncryption:
    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str:
        assert key_id == "vault-1"
        return ciphertext.replace("enc:", "")


class FakeCache:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def get_pending_connected_account_permission_request(self, request_id: str):
        if request_id != "cap-1":
            return None
        return {
            "request_id": "cap-1",
            "chat_id": "chat-1",
            "message_id": "msg-1",
            "user_id": "user-1",
            "user_id_hash": "hash-1",
            "app_id": "calendar",
            "skill_id": "create-event",
            "action": "write",
            "accounts": [{"connected_account_id": "acct-1", "app_id": "calendar"}],
        }

    async def delete_pending_connected_account_permission_request(self, request_id: str) -> bool:
        self.deleted.append(request_id)
        return True

    async def get_ai_messages_history(self, user_id: str, chat_id: str):
        return [
            json.dumps({"role": "user", "encrypted_content": "enc:create meeting", "created_at": 1}),
        ]

    async def get_user_vault_key_id(self, user_id: str) -> str:
        return "vault-1"


class FakeManager:
    async def send_personal_message(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_connected_account_permission_confirmation_dispatches_continuation(monkeypatch) -> None:
    module = import_handler_module()
    captured: dict = {}

    class FakeTask:
        @staticmethod
        def apply_async(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id="task-2")

    monkeypatch.setitem(
        sys.modules,
        "backend.apps.ai.tasks.ask_skill_task",
        SimpleNamespace(process_ai_skill_ask_task=FakeTask),
    )
    monkeypatch.setattr(module, "_load_ask_skill_config_from_app_yml", lambda: {"default_llms": {}})

    cache = FakeCache()
    await module.handle_connected_account_permission_confirmed(
        websocket=None,
        manager=FakeManager(),
        cache_service=cache,
        directus_service=FakeDirectus(),
        encryption_service=FakeEncryption(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={
            "request_id": "cap-1",
            "chat_id": "chat-1",
            "approved": True,
            "connected_account_token_refs": [
                {
                    "connected_account_id": "acct-1",
                    "app_id": "calendar",
                    "turn_token_ref": "tref_1",
                    "allowed_actions": ["write"],
                    "action_scope": {"calendar_id": "primary"},
                }
            ],
        },
    )

    request_data = captured["kwargs"]["request_data_dict"]
    assert request_data["is_connected_account_permission_continuation"] is True
    assert request_data["connected_account_token_refs"][0]["turn_token_ref"] == "tref_1"
    assert request_data["message_history"][0]["content"] == "create meeting"
    assert cache.deleted == ["cap-1"]


@pytest.mark.asyncio
async def test_connected_account_permission_confirmation_rejects_secret_fields() -> None:
    module = import_handler_module()

    await module.handle_connected_account_permission_confirmed(
        websocket=None,
        manager=FakeManager(),
        cache_service=FakeCache(),
        directus_service=FakeDirectus(),
        encryption_service=FakeEncryption(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={
            "request_id": "cap-1",
            "chat_id": "chat-1",
            "approved": True,
            "connected_account_token_refs": [{"turn_token_ref": "tref_1", "refresh_token": "secret"}],
        },
    )
