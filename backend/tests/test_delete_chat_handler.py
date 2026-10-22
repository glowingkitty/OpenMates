"""Tests for the delete_chat WebSocket handler.

The handler owns the user decision about whether project-referenced embeds are
kept or removed when a chat is manually deleted.
"""

# contract-test-file: infrastructure

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import delete_chat_handler


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
    def __init__(self) -> None:
        self.mark_chat_deleted = AsyncMock(return_value=True)
        self.remove_chat_from_ids_versions = AsyncMock(return_value=True)
        self.delete_chat_app_settings_memories = AsyncMock(return_value=0)
        self.delete_chat_embed_cache = AsyncMock(return_value=0)
        self.delete = AsyncMock(return_value=True)

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


@pytest.mark.anyio
async def test_delete_chat_handler_forwards_remove_project_embeds(monkeypatch) -> None:
    queue_delete_chat_task = Mock()
    monkeypatch.setattr(delete_chat_handler, "_queue_delete_chat_task", queue_delete_chat_task)
    monkeypatch.setattr(
        delete_chat_handler,
        "invalidate_recovery_jobs_for_chat_deletion",
        AsyncMock(),
    )

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

    cache_service = _CacheService()

    await delete_chat_handler.handle_delete_chat(
        websocket=SimpleNamespace(),
        manager=manager,
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=SimpleNamespace(),
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chatId": "chat-1", "removeProjectEmbeds": True},
    )

    queue_delete_chat_task.assert_called_once_with("user-1", "chat-1", True)
    delete_chat_handler.invalidate_recovery_jobs_for_chat_deletion.assert_awaited_once()
    cache_service.mark_chat_deleted.assert_awaited_once_with("chat-1")
    assert cache_service.delete.await_count == 2


# contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_delete_chat_stops_before_cache_removal_when_durable_fence_fails(monkeypatch) -> None:
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

    queue_delete_chat_task = Mock()
    monkeypatch.setattr(delete_chat_handler, "_queue_delete_chat_task", queue_delete_chat_task)
    invalidation = AsyncMock(side_effect=ChatRecoveryProtocolError(404, "missing_extension"))
    monkeypatch.setattr(
        delete_chat_handler, "invalidate_recovery_jobs_for_chat_deletion", invalidation,
    )
    directus_service = SimpleNamespace(chat=SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=True),
        get_chat_metadata=AsyncMock(return_value={"id": "chat-1"}),
    ))
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    cache_service = _CacheService()
    await delete_chat_handler.handle_delete_chat(
        websocket=SimpleNamespace(), manager=manager, cache_service=cache_service,
        directus_service=directus_service, encryption_service=SimpleNamespace(),
        user_id="user-1", device_fingerprint_hash="device-1",
        payload={"chatId": "chat-1"},
    )
    invalidation.assert_awaited_once()
    cache_service.mark_chat_deleted.assert_not_awaited()
    queue_delete_chat_task.assert_not_called()
    manager.broadcast_to_user.assert_not_awaited()
    assert manager.send_personal_message.await_args.kwargs["message"]["type"] == "error"


# contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
@pytest.mark.anyio
@pytest.mark.parametrize("ownership_lookup_fails", [False, True])
async def test_delete_unpersisted_draft_shell_cleans_cache_when_no_saved_chat_fence_exists(
    monkeypatch, ownership_lookup_fails: bool,
) -> None:
    queue_delete_chat_task = Mock()
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

    invalidation = AsyncMock(side_effect=ChatRecoveryProtocolError(404, "chat_not_found"))
    monkeypatch.setattr(delete_chat_handler, "_queue_delete_chat_task", queue_delete_chat_task)
    monkeypatch.setattr(delete_chat_handler, "invalidate_recovery_jobs_for_chat_deletion", invalidation)
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=AsyncMock(
                return_value=False,
                side_effect=RuntimeError("ownership unavailable") if ownership_lookup_fails else None,
            ),
            get_chat_metadata=AsyncMock(return_value=None),
        ),
        get_items=AsyncMock(return_value=[]),
    )
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    cache_service = _CacheService()

    await delete_chat_handler.handle_delete_chat(
        websocket=SimpleNamespace(), manager=manager, cache_service=cache_service,
        directus_service=directus_service, encryption_service=SimpleNamespace(),
        user_id="user-1", device_fingerprint_hash="device-1", payload={"chatId": "draft-1"},
    )

    directus_service.get_items.assert_awaited_once_with(
        "chats", params={"filter[id][_eq]": "draft-1", "fields": "id", "limit": 1},
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    invalidation.assert_awaited_once()
    queue_delete_chat_task.assert_not_called()
    cache_service.mark_chat_deleted.assert_awaited_once_with("draft-1")
    cache_service.remove_chat_from_ids_versions.assert_awaited_once_with("user-1", "draft-1")
    manager.send_personal_message.assert_not_awaited()
    assert manager.broadcast_to_user.await_args.args == (
        {"type": "chat_deleted", "payload": {"chat_id": "draft-1", "tombstone": True}}, "user-1",
    )


# contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("authoritative_result", [None, [{"id": "chat-1"}], RuntimeError("Directus unavailable")])
async def test_draft_shell_cleanup_fails_closed_without_confirmed_absence(
    monkeypatch, authoritative_result,
) -> None:
    queue_delete_chat_task = Mock()
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

    invalidation = AsyncMock(side_effect=ChatRecoveryProtocolError(404, "chat_not_found"))
    monkeypatch.setattr(delete_chat_handler, "_queue_delete_chat_task", queue_delete_chat_task)
    monkeypatch.setattr(delete_chat_handler, "invalidate_recovery_jobs_for_chat_deletion", invalidation)
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=AsyncMock(return_value=False),
            get_chat_metadata=AsyncMock(return_value=None),
        ),
        get_items=AsyncMock(
            return_value=authoritative_result,
            side_effect=authoritative_result if isinstance(authoritative_result, Exception) else None,
        ),
    )
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    cache_service = _CacheService()

    await delete_chat_handler.handle_delete_chat(
        websocket=SimpleNamespace(), manager=manager, cache_service=cache_service,
        directus_service=directus_service, encryption_service=SimpleNamespace(),
        user_id="user-1", device_fingerprint_hash="device-1", payload={"chatId": "chat-1"},
    )

    invalidation.assert_awaited_once()
    queue_delete_chat_task.assert_not_called()
    cache_service.mark_chat_deleted.assert_not_awaited()
    cache_service.remove_chat_from_ids_versions.assert_not_awaited()
    manager.broadcast_to_user.assert_not_awaited()
    assert manager.send_personal_message.await_args.kwargs["message"]["type"] == "error"


# contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_delete_chat_rejects_another_users_saved_chat(monkeypatch) -> None:
    queue_delete_chat_task = Mock()
    invalidation = AsyncMock()
    monkeypatch.setattr(delete_chat_handler, "_queue_delete_chat_task", queue_delete_chat_task)
    monkeypatch.setattr(delete_chat_handler, "invalidate_recovery_jobs_for_chat_deletion", invalidation)
    directus_service = SimpleNamespace(chat=SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=False),
        get_chat_metadata=AsyncMock(return_value={"id": "chat-1"}),
    ))
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    cache_service = _CacheService()

    await delete_chat_handler.handle_delete_chat(
        websocket=SimpleNamespace(), manager=manager, cache_service=cache_service,
        directus_service=directus_service, encryption_service=SimpleNamespace(),
        user_id="user-1", device_fingerprint_hash="device-1", payload={"chatId": "chat-1"},
    )

    invalidation.assert_not_awaited()
    queue_delete_chat_task.assert_not_called()
    cache_service.mark_chat_deleted.assert_not_awaited()
    manager.broadcast_to_user.assert_not_awaited()
    assert "permission" in manager.send_personal_message.await_args.kwargs["message"]["payload"]["message"]


# contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_delete_chat_retry_uses_existing_fence_after_chat_row_is_removed(monkeypatch) -> None:
    queue_delete_chat_task = Mock()
    invalidation = AsyncMock(return_value={"chat_deletion_fenced": True, "chat_id": "chat-1"})
    monkeypatch.setattr(delete_chat_handler, "_queue_delete_chat_task", queue_delete_chat_task)
    monkeypatch.setattr(delete_chat_handler, "invalidate_recovery_jobs_for_chat_deletion", invalidation)
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=AsyncMock(return_value=False),
            get_chat_metadata=AsyncMock(return_value=None),
        ),
        get_items=AsyncMock(),
    )
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    cache_service = _CacheService()

    await delete_chat_handler.handle_delete_chat(
        websocket=SimpleNamespace(), manager=manager, cache_service=cache_service,
        directus_service=directus_service, encryption_service=SimpleNamespace(),
        user_id="user-1", device_fingerprint_hash="device-1", payload={"chatId": "chat-1"},
    )

    invalidation.assert_awaited_once()
    directus_service.get_items.assert_not_awaited()
    queue_delete_chat_task.assert_called_once_with("user-1", "chat-1", False)
    cache_service.mark_chat_deleted.assert_awaited_once_with("chat-1")
    manager.send_personal_message.assert_not_awaited()
    manager.broadcast_to_user.assert_awaited_once()
