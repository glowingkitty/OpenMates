"""Account Import V1 scan endpoint contract tests.

The route may receive selected plaintext normalized chats for transient scanning,
but it must return sanitized output without writing plaintext Directus records.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

if "redis" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedisClient:
        pass

    redis_asyncio_module.Redis = FakeRedisClient
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

from backend.core.api.app.routes import account_imports


class FakeImportService:
    def __init__(self) -> None:
        self.directus = SimpleNamespace(create_item=AsyncMock(), update_item=AsyncMock())

    async def scan_selected_chats(self, *, user_id: str, import_id: str, chats: list[dict]) -> dict:
        assert user_id == "user-1"
        assert import_id == "import-1"
        assert chats[0]["messages"][0]["content"] == "Synthetic plaintext selected for scan."
        return {
            "chats": [
                {
                    **chats[0],
                    "messages": [{"role": "user", "content": "Synthetic sanitized content.", "source_message_id": "msg-1"}],
                }
            ],
            "credits_reserved": 1,
            "messages_blocked": [],
            "failures": [],
        }


class FakeChatDirectus:
    def __init__(self) -> None:
        self.created_chats = []
        self.created_messages = []

    async def create_chat_in_directus(self, payload: dict):
        self.created_chats.append(payload)
        return payload, False

    async def create_message_in_directus(self, payload: dict):
        self.created_messages.append(payload)
        return payload


def _client(service: FakeImportService) -> TestClient:
    app = FastAPI()
    app.include_router(account_imports.router)
    app.state.directus_service = SimpleNamespace(chat=FakeChatDirectus())
    app.dependency_overrides[account_imports.get_account_import_service] = lambda: service
    app.dependency_overrides[account_imports.get_current_user_info] = lambda: {"user_id": "user-1"}
    return TestClient(app)


def test_scan_endpoint_returns_sanitized_messages_without_directus_plaintext_writes() -> None:
    service = FakeImportService()
    response = _client(service).post(
        "/v1/account-imports/import-1/scan",
        json={
            "chats": [
                {
                    "provider": "claude",
                    "source_chat_id": "claude-chat-1",
                    "source_fingerprint": "fingerprint-1",
                    "messages": [{"role": "user", "content": "Synthetic plaintext selected for scan.", "source_message_id": "msg-1"}],
                    "embeds": [],
                    "uploads": [],
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["credits_reserved"] == 1
    assert body["chats"][0]["messages"][0]["content"] == "Synthetic sanitized content."
    service.directus.create_item.assert_not_awaited()
    service.directus.update_item.assert_not_awaited()


def test_persist_encrypted_endpoint_writes_only_client_encrypted_fields() -> None:
    service = FakeImportService()
    client = _client(service)
    directus = client.app.state.directus_service

    response = client.post(
        "/v1/account-imports/import-1/persist-encrypted",
        json={
            "chats": [
                {
                    "chat_id": "chat-1",
                    "encrypted_title": "client-encrypted-title",
                    "encrypted_chat_key": "client-encrypted-key",
                    "created_at": 100,
                    "updated_at": 110,
                    "source_fingerprint": "fingerprint-1",
                    "messages": [
                        {
                            "message_id": "message-1",
                            "role": "user",
                            "encrypted_content": "client-encrypted-content",
                            "encrypted_sender_name": "client-encrypted-sender",
                            "created_at": 100,
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert directus.chat.created_chats[0]["encrypted_title"] == "client-encrypted-title"
    assert "title" not in directus.chat.created_chats[0]
    assert directus.chat.created_messages[0]["encrypted_content"] == "client-encrypted-content"
    assert "content" not in directus.chat.created_messages[0]
