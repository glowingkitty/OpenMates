"""Tests for the delete_chat WebSocket handler.

The handler owns the user decision about whether project-referenced embeds are
kept or removed when a chat is manually deleted.
"""

# contract-test-file: infrastructure

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

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
        self.increment_and_tombstone_user_draft = AsyncMock(return_value=4)

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

    assert directus_service.get_items.await_args_list[0] == call(
        "chats", params={"filter[id][_eq]": "draft-1", "fields": "id", "limit": 1},
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    cache_service.increment_and_tombstone_user_draft.assert_awaited_once_with("user-1", "draft-1")
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


def _draft_shell_directus(draft_rows, *, bulk_delete_result=True):
    """Directus double: no chat row for the shell, `draft_rows` in `drafts`."""
    async def get_items(collection, **_kwargs):
        return [] if collection == "chats" else draft_rows

    return SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=AsyncMock(return_value=False),
            get_chat_metadata=AsyncMock(return_value=None),
        ),
        get_items=AsyncMock(side_effect=get_items),
        bulk_delete_items=AsyncMock(return_value=bulk_delete_result),
    )


async def _delete_draft_shell(monkeypatch, directus_service, cache_service, manager) -> Mock:
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

    queue_delete_chat_task = Mock()
    monkeypatch.setattr(delete_chat_handler, "_queue_delete_chat_task", queue_delete_chat_task)
    monkeypatch.setattr(
        delete_chat_handler, "invalidate_recovery_jobs_for_chat_deletion",
        AsyncMock(side_effect=ChatRecoveryProtocolError(404, "chat_not_found")),
    )
    await delete_chat_handler.handle_delete_chat(
        websocket=SimpleNamespace(), manager=manager, cache_service=cache_service,
        directus_service=directus_service, encryption_service=SimpleNamespace(),
        user_id="user-1", device_fingerprint_hash="device-1", payload={"chatId": "draft-1"},
    )
    return queue_delete_chat_task


# contract-test: supporting surface=rest_api assertions=drafts.draft-only.lifecycle,chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_deleting_draft_shell_deletes_only_the_owners_persisted_draft_rows(monkeypatch) -> None:
    """Regression: delete_chat on a draft-only chat left its encrypted Directus draft behind."""
    directus_service = _draft_shell_directus([{"id": "draft-row-1"}, {"id": "draft-row-2"}])
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    cache_service = _CacheService()

    queue_delete_chat_task = await _delete_draft_shell(monkeypatch, directus_service, cache_service, manager)

    assert directus_service.get_items.await_args_list[1] == call(
        "drafts",
        params={
            "filter[hashed_user_id][_eq]": hashlib.sha256(b"user-1").hexdigest(),
            "filter[chat_id][_eq]": "draft-1",
            "fields": "id",
            "limit": -1,
        },
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    directus_service.bulk_delete_items.assert_awaited_once_with(
        collection="drafts", item_ids=["draft-row-1", "draft-row-2"],
    )
    queue_delete_chat_task.assert_not_called()
    manager.send_personal_message.assert_not_awaited()
    assert manager.broadcast_to_user.await_args.args[0]["type"] == "chat_deleted"


# contract-test: supporting surface=rest_api assertions=drafts.draft-only.lifecycle,chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["tombstone", "bulk_delete"])
async def test_draft_shell_deletion_fails_closed_when_draft_removal_fails(monkeypatch, failure) -> None:
    directus_service = _draft_shell_directus(
        [{"id": "draft-row-1"}], bulk_delete_result=failure != "bulk_delete",
    )
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    cache_service = _CacheService()
    if failure == "tombstone":
        cache_service.increment_and_tombstone_user_draft = AsyncMock(return_value=None)

    await _delete_draft_shell(monkeypatch, directus_service, cache_service, manager)

    if failure == "tombstone":
        directus_service.bulk_delete_items.assert_not_awaited()
    cache_service.mark_chat_deleted.assert_not_awaited()
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


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_conditional_cleanup_fans_out_only_canonical_transaction_guard(monkeypatch):
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    payload = {"request_id": "018fabcd-abcd-7abc-8abc-abcdefabcdef", "chat_id": "chat",
        "cleanup_attempt_id": "018fabcd-abcd-7abc-8abc-abcdefabcdef", "call_id": None,
        "lifecycle_message_ids": [], "expected_messages_v": 0}
    guard = {key: payload[key] for key in ("cleanup_attempt_id", "call_id", "lifecycle_message_ids", "expected_messages_v")}
    execute = AsyncMock(return_value={"empty_call_cleanup": guard})
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    delete = AsyncMock()
    monkeypatch.setattr(delete_chat_handler, "handle_delete_chat", delete)
    from contextlib import nullcontext
    manager = SimpleNamespace(send_personal_message=AsyncMock(),
        empty_call_cleanup_gate=lambda _user: nullcontext())
    await delete_chat_handler.handle_delete_empty_call_chat(None, manager, object(), object(), object(),
        "owner", "device", payload)
    assert execute.await_args.args[0] == "invalidate_deletion"
    assert manager.send_personal_message.await_args.args[0]["payload"]["accepted"] is True
    assert delete.await_args.kwargs == {"empty_call_cleanup_guard": guard}


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_conditional_cleanup_rejection_never_falls_back_to_generic_delete(monkeypatch):
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    execute = AsyncMock(side_effect=RuntimeError("authority unavailable"))
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    delete = AsyncMock()
    monkeypatch.setattr(delete_chat_handler, "handle_delete_chat", delete)
    from contextlib import nullcontext
    manager = SimpleNamespace(send_personal_message=AsyncMock(),
        empty_call_cleanup_gate=lambda _user: nullcontext())
    await delete_chat_handler.handle_delete_empty_call_chat(None, manager, object(), object(), object(),
        "owner", "device", {"request_id": "018fabcd-abcd-7abc-8abc-abcdefabcdef", "chat_id": "chat",
            "cleanup_attempt_id": "018fabcd-abcd-7abc-8abc-abcdefabcdef", "call_id": None,
            "lifecycle_message_ids": [], "expected_messages_v": 0})
    assert manager.send_personal_message.await_args.args[0]["payload"]["accepted"] is False
    delete.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_cli_or_native_connections_do_not_disqualify_conditional_cleanup(monkeypatch):
    """A connected CLI/TUI/Apple client must not keep empty call shells forever."""
    from contextlib import nullcontext
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    payload = {"request_id": "018fabcd-abcd-7abc-8abc-abcdefabcdef", "chat_id": "chat",
        "cleanup_attempt_id": "018fabcd-abcd-7abc-8abc-abcdefabcdef", "call_id": None,
        "lifecycle_message_ids": [], "expected_messages_v": 0}
    guard = {key: payload[key] for key in ("cleanup_attempt_id", "call_id", "lifecycle_message_ids", "expected_messages_v")}
    execute = AsyncMock(return_value={"empty_call_cleanup": guard})
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    delete = AsyncMock()
    monkeypatch.setattr(delete_chat_handler, "handle_delete_chat", delete)
    manager = SimpleNamespace(send_personal_message=AsyncMock(),
        empty_call_cleanup_gate=lambda _user: nullcontext())
    await delete_chat_handler.handle_delete_empty_call_chat(None, manager, object(), object(), object(),
        "owner", "device", payload)
    assert [call.args[0] for call in execute.await_args_list] == ["invalidate_deletion"]
    assert manager.send_personal_message.await_args.args[0]["payload"]["accepted"] is True
    delete.assert_awaited_once()
