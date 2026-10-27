"""Durable disqualification must precede personal draft admission/clear."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from backend.core.api.app.routes.handlers.websocket_handlers import draft_scope
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService


@pytest.fixture
def anyio_backend():
    return "asyncio"


def directus(metadata=None, owner=True):
    return SimpleNamespace(chat=SimpleNamespace(
        get_chat_metadata=AsyncMock(return_value=metadata),
        check_chat_ownership=AsyncMock(return_value=owner),
    ))


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("metadata", [None, {"hashed_user_id": "owner"}])
async def test_personal_draft_including_missing_shell_requires_durable_exclusion(monkeypatch, metadata):
    execute = AsyncMock(return_value={"disqualified": True})
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    assert await draft_scope.draft_change_allowed(directus(metadata), "owner", "chat-id", None)
    execute.assert_awaited_once_with("update_call_cleanup_candidate", {
        "protocol_version": 1, "hashed_user_id": draft_scope.hash_id("owner"),
        "chat_id": "chat-id", "mode": "disqualify",
    })


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_unavailable_durable_authority_rejects_before_draft_can_be_admitted(monkeypatch):
    monkeypatch.setattr(ChatRecoveryService, "execute", AsyncMock(side_effect=RuntimeError("unavailable")))
    assert not await draft_scope.draft_change_allowed(directus(), "owner", "chat-id", None)


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_foreign_personal_draft_never_disqualifies_another_owner_candidate(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    assert not await draft_scope.draft_change_allowed(directus({"hashed_user_id": "other"}, False),
        "owner", "chat-id", None)
    execute.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_team_draft_retains_its_existing_authorization_path(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    api = directus({"hashed_team_id": draft_scope.hash_id("team")})
    api.team = SimpleNamespace(require_team_role=AsyncMock())
    assert await draft_scope.draft_change_allowed(api, "owner", "chat-id", "team")
    execute.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_bootstrap_old_clients_omit_optional_cleanup_wire_field(monkeypatch):
    execute = AsyncMock(return_value={"chat_id": "chat-id", "created": False})
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    service = ChatRecoveryService(object())
    await service.register_personal_chat_draft(hashed_user_id="owner", chat_id="chat-id",
        encrypted_chat_key="wrapped", created_at=1)
    assert "cleanup_attempt_id" not in execute.await_args.args[1]
    await service.register_personal_chat_draft(hashed_user_id="owner", chat_id="chat-id",
        encrypted_chat_key="wrapped", created_at=1, cleanup_attempt_id="attempt-id")
    assert execute.await_args.args[1]["cleanup_attempt_id"] == "attempt-id"


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_project_item_admission_disqualifies_before_plain_crud(monkeypatch):
    from backend.core.api.app.services.directus.project_methods import ProjectMethods
    execute = AsyncMock(side_effect=RuntimeError("already fenced"))
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    api = SimpleNamespace(create_item=AsyncMock())
    with pytest.raises(RuntimeError, match="already fenced"):
        await ProjectMethods(api).create_item("owner", {"item_type": "chat", "target_id_hash": "a" * 64})
    assert execute.await_args.args[1]["hashed_chat_id"] == "a" * 64
    api.create_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_chat_preference_admission_preserves_shell_before_plain_crud(monkeypatch):
    import base64
    from backend.core.api.app.services.directus.chat_model_preference_methods import ChatModelPreferenceMethods
    execute = AsyncMock(side_effect=RuntimeError("already fenced"))
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    api = SimpleNamespace(get_items=AsyncMock(), create_item=AsyncMock())
    with pytest.raises(RuntimeError, match="already fenced"):
        await ChatModelPreferenceMethods(api).upsert_preference(user_id="owner", chat_id="chat-id",
            encrypted_selected_ai_model=base64.b64encode(b"a" * 32).decode())
    api.create_item.assert_not_awaited()
    api.get_items.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_lifecycle_confirmation_uses_durable_version_without_a_second_increment(monkeypatch):
    import asyncio
    from backend.core.api.app.routes.handlers.websocket_handlers.system_message_handler import _handle_call_lifecycle
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock(),
        empty_call_cleanup_gate=lambda _owner: asyncio.Lock(),
        all_user_connections_support_empty_call_cleanup=lambda _owner: True)
    async def execute(_self, operation, data):
        assert operation == "persist_call_lifecycle"
        manager.send_personal_message.assert_not_awaited()
        return {"messages_v": 7, "created": True}
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    cache = SimpleNamespace(delete_chat_versions=AsyncMock(), delete=AsyncMock(),
        delete_sync_messages_history=AsyncMock(), set=AsyncMock())
    await _handle_call_lifecycle(manager=manager, cache_service=cache, directus_service=object(),
        user_id="owner", device_hash="device", owner_hash="a" * 64, chat_id="chat",
        message_id="00000000-voice-call-" + "f" * 32 + "-started", content="encrypted", created_at=1,
        message_status="synced", encrypted_chat_key="wrapped")
    assert manager.send_personal_message.await_args.args[0]["payload"]["messages_v"] == 7
    cache.delete_chat_versions.assert_awaited_once_with("owner", "chat")
    cache.delete_sync_messages_history.assert_awaited_once_with("owner", "chat")
    assert manager.broadcast_to_user.await_args.args[0]["data"]["status"] == "synced"


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_legacy_lifecycle_receiver_is_excluded_before_durable_commit_and_broadcast(monkeypatch):
    import asyncio
    from backend.core.api.app.routes.handlers.websocket_handlers.system_message_handler import _handle_call_lifecycle
    operations = []
    async def execute(_self, operation, data):
        operations.append(operation)
        if operation == "persist_call_lifecycle":
            raise RuntimeError("fenced")
        return {"disqualified": True}
    monkeypatch.setattr(ChatRecoveryService, "execute", execute)
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock(),
        empty_call_cleanup_gate=lambda _owner: asyncio.Lock(),
        all_user_connections_support_empty_call_cleanup=lambda _owner: False)
    with pytest.raises(RuntimeError, match="fenced"):
        await _handle_call_lifecycle(manager=manager, cache_service=object(), directus_service=object(),
            user_id="owner", device_hash="device", owner_hash="a" * 64, chat_id="chat",
            message_id="00000000-voice-call-" + "f" * 32 + "-started", content="encrypted", created_at=1,
            message_status="synced", encrypted_chat_key="wrapped")
    assert operations == ["update_call_cleanup_candidate", "persist_call_lifecycle"]
    manager.send_personal_message.assert_not_awaited()
    manager.broadcast_to_user.assert_not_awaited()
