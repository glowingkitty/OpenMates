"""Tests for the delete_chat WebSocket handler.

The handler owns the user decision about whether project-referenced embeds are
kept or removed when a chat is manually deleted.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import delete_chat_handler


class _Pipeline:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def delete(self, key: str) -> None:
        return None

    async def execute(self) -> list[int]:
        return [1, 1, 1]


class _RedisClient:
    def pipeline(self, transaction: bool = False) -> _Pipeline:
        return _Pipeline()


class _CacheService:
    remove_chat_from_ids_versions = AsyncMock(return_value=True)
    delete_chat_app_settings_memories = AsyncMock(return_value=0)
    delete_chat_embed_cache = AsyncMock(return_value=0)

    @property
    def client(self):
        async def _get_client():
            return _RedisClient()

        return _get_client()

    def _get_chat_versions_key(self, user_id: str, chat_id: str) -> str:
        return f"versions:{user_id}:{chat_id}"

    def _get_chat_list_item_data_key(self, user_id: str, chat_id: str) -> str:
        return f"list:{user_id}:{chat_id}"

    def _get_chat_messages_key(self, user_id: str, chat_id: str) -> str:
        return f"messages:{user_id}:{chat_id}"


@pytest.mark.asyncio
async def test_delete_chat_handler_forwards_remove_project_embeds(monkeypatch) -> None:
    queue_delete_chat_task = Mock()
    monkeypatch.setattr(delete_chat_handler, "_queue_delete_chat_task", queue_delete_chat_task)

    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=AsyncMock(return_value=True),
            get_chat_metadata=AsyncMock(return_value={"id": "chat-1"}),
        )
    )
    manager = SimpleNamespace(
        send_personal_message=AsyncMock(),
        broadcast_to_user=AsyncMock(),
    )

    await delete_chat_handler.handle_delete_chat(
        websocket=SimpleNamespace(),
        manager=manager,
        cache_service=_CacheService(),
        directus_service=directus_service,
        encryption_service=SimpleNamespace(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chatId": "chat-1", "removeProjectEmbeds": True},
    )

    queue_delete_chat_task.assert_called_once_with("user-1", "chat-1", True)
