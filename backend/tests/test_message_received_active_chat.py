# backend/tests/test_message_received_active_chat.py
#
# Regression coverage for WebSocket message dispatch ordering.
# New-chat sends can race with set_active_chat acknowledgements when the
# ack path is delayed by last_opened persistence. The message handler must
# make the originating connection active before AI dispatch so stream chunks
# are routed back to the sending browser deterministically.

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.modules.setdefault(
    "backend.core.api.app.services.cache",
    SimpleNamespace(CacheService=object),
)
sys.modules.setdefault(
    "backend.core.api.app.services.directus.directus",
    SimpleNamespace(DirectusService=object),
)

class FakeManager:
    def __init__(self):
        self.calls = []

    def set_active_chat(self, user_id, device_fingerprint_hash, chat_id):
        self.calls.append(("set_active_chat", user_id, device_fingerprint_hash, chat_id))

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.calls.append(("send_personal_message", message.get("type"), user_id, device_fingerprint_hash))

    async def broadcast_to_user(self, message, user_id, exclude_device_hash=None):
        self.calls.append(("broadcast_to_user", message.get("type"), user_id, exclude_device_hash))

    async def broadcast_to_user_specific_event(self, user_id, event_name, payload):
        self.calls.append(("broadcast_to_user_specific_event", event_name, user_id, payload.get("chat_id")))


class FakeEmbedService:
    def __init__(self, cache_service, directus_service, encryption_service):
        pass

    async def resolve_embed_references_in_content(self, content, user_vault_key_id, log_prefix, seen_embed_refs):
        return content, {}


class FakeSkillRegistry:
    def __init__(self, manager):
        self.manager = manager

    async def dispatch_skill(self, app_name, skill_name, request_payload):
        assert app_name == "ai"
        assert skill_name == "ask"
        assert self.manager.calls[0][0] == "set_active_chat"
        self.manager.calls.append(("dispatch_skill", app_name, skill_name, request_payload["chat_id"]))
        return {"task_id": "task-123"}


def test_message_send_marks_origin_connection_active_before_ai_dispatch(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    cutover = SimpleNamespace(
        get_epoch=AsyncMock(return_value=0),
        admit_legacy_inference=AsyncMock(return_value={"admitted": True}),
        release_legacy_inference=AsyncMock(return_value={"released": True}),
    )
    cache_service = SimpleNamespace(
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 1, "last_edited_overall_timestamp": 1_700_000_000}
        ),
        delete_user_draft_from_cache=AsyncMock(return_value=False),
        delete_user_draft_version_from_chat_versions=AsyncMock(return_value=False),
        get_ai_messages_history=AsyncMock(return_value=[]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        set_active_ai_task=AsyncMock(),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value=None),
            check_chat_ownership=AsyncMock(return_value=True),
        ),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    encryption_service = SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("encrypted", 1)))
    payload = {
        "chat_id": "chat-123",
        "message": {
            "message_id": "msg-123",
            "role": "user",
            "content": "What is the capital of France?",
            "created_at": 1_700_000_000,
            "chat_has_title": False,
        },
    }

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.embed_service",
        SimpleNamespace(EmbedService=FakeEmbedService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.skill_registry",
        SimpleNamespace(get_global_registry=lambda: FakeSkillRegistry(manager)),
    )
    monkeypatch.setattr(
        message_received_handler,
        "ChatRecoveryCutoverController",
        lambda cache, directus: cutover,
    )

    asyncio.run(
        message_received_handler.handle_message_received(
            websocket=SimpleNamespace(),
            manager=manager,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_id="user-123",
            device_fingerprint_hash="device-123",
            payload=payload,
        )
    )

    assert manager.calls[0] == ("set_active_chat", "user-123", "device-123", "chat-123")
    assert ("dispatch_skill", "ai", "ask", "chat-123") in manager.calls
    cutover.get_epoch.assert_awaited_once_with(authoritative=True)
    cache_service.set_active_ai_task.assert_awaited_once_with("chat-123", "task-123")


def test_recovery_send_does_not_enqueue_while_another_task_is_active(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    cache_service = SimpleNamespace(
        get_active_ai_task=AsyncMock(return_value="active-task-123"),
    )
    enqueue = AsyncMock()
    cutover = SimpleNamespace(get_epoch=AsyncMock(return_value=1))
    monkeypatch.setattr(message_received_handler, "enqueue_chat_turn", enqueue)
    monkeypatch.setattr(
        message_received_handler,
        "ChatRecoveryCutoverController",
        lambda cache, directus: cutover,
    )

    asyncio.run(
        message_received_handler.handle_message_received(
            websocket=SimpleNamespace(),
            manager=manager,
            cache_service=cache_service,
            directus_service=SimpleNamespace(),
            encryption_service=SimpleNamespace(),
            user_id="user-123",
            device_fingerprint_hash="device-123",
            payload={
                "chat_id": "chat-123",
                "message": {"message_id": "msg-123", "content": "retry me"},
                "protocol_version": 1,
                "preflight_id": "preflight-123",
            },
        )
    )

    enqueue.assert_not_awaited()
    cutover.get_epoch.assert_awaited_once_with(authoritative=True)
    assert manager.calls == [
        ("send_personal_message", "error", "user-123", "device-123")
    ]


def test_incognito_send_skips_durable_cutover_lookup(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    controller_calls = []
    manager = FakeManager()
    cache_service = SimpleNamespace(
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        delete_chat_messages_history=AsyncMock(),
        add_message_to_chat_history=AsyncMock(),
        get_ai_messages_history=AsyncMock(return_value=[]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        set_active_ai_task=AsyncMock(),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(),
            check_chat_ownership=AsyncMock(),
        ),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        message_received_handler,
        "ChatRecoveryCutoverController",
        lambda *args: controller_calls.append(args),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.embed_service",
        SimpleNamespace(EmbedService=FakeEmbedService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.skill_registry",
        SimpleNamespace(get_global_registry=lambda: FakeSkillRegistry(manager)),
    )

    asyncio.run(
        message_received_handler.handle_message_received(
            websocket=SimpleNamespace(),
            manager=manager,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("encrypted", 1))),
            user_id="user-123",
            device_fingerprint_hash="device-123",
            payload={
                "chat_id": "incognito-chat-123",
                "is_incognito": True,
                "message": {
                    "message_id": "msg-123",
                    "role": "user",
                    "content": "private",
                    "created_at": 1_700_000_000,
                    "chat_has_title": False,
                },
                "message_history": [
                    {
                        "message_id": "msg-123",
                        "role": "user",
                        "content": "private",
                        "created_at": 1_700_000_000,
                    }
                ],
            },
        )
    )

    assert controller_calls == []
    assert ("dispatch_skill", "ai", "ask", "incognito-chat-123") in manager.calls
    directus_service.chat.get_chat_metadata.assert_not_awaited()


def test_contextual_pdf_processing_preserves_embed_ref(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    captured_tasks = []
    cutover = SimpleNamespace(
        get_epoch=AsyncMock(return_value=0),
        admit_legacy_inference=AsyncMock(return_value={"admitted": True}),
        release_legacy_inference=AsyncMock(return_value={"released": True}),
    )
    cache_service = SimpleNamespace(
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 1, "last_edited_overall_timestamp": 1_700_000_000}
        ),
        delete_user_draft_from_cache=AsyncMock(return_value=False),
        delete_user_draft_version_from_chat_versions=AsyncMock(return_value=False),
        get_ai_messages_history=AsyncMock(return_value=[]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        set_active_ai_task=AsyncMock(),
        update_user=AsyncMock(),
        set_embed_in_cache=AsyncMock(),
        add_embed_id_to_chat_index=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value=None),
            check_chat_ownership=AsyncMock(return_value=True),
        ),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    encryption_service = SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("encrypted", 1)))

    def fake_send_task_validated(**kwargs):
        captured_tasks.append(kwargs)
        return SimpleNamespace(id="task-123")

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.embed_service",
        SimpleNamespace(EmbedService=FakeEmbedService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.skill_registry",
        SimpleNamespace(get_global_registry=lambda: FakeSkillRegistry(manager)),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.tasks.celery_config",
        SimpleNamespace(send_task_validated=fake_send_task_validated),
    )
    monkeypatch.setattr(
        message_received_handler,
        "ChatRecoveryCutoverController",
        lambda cache, directus: cutover,
    )

    asyncio.run(
        message_received_handler.handle_message_received(
            websocket=SimpleNamespace(),
            manager=manager,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_id="user-123",
            device_fingerprint_hash="device-123",
            payload={
                "chat_id": "chat-123",
                "message": {
                    "message_id": "msg-123",
                    "role": "user",
                    "content": "Read [Document](embed:pdf_document_embed_ref)",
                    "created_at": 1_700_000_000,
                    "chat_has_title": False,
                },
                "embeds": [
                    {
                        "embed_id": "pdf-embed-123",
                        "type": "pdf",
                        "status": "processing",
                        "text_preview": "document.pdf",
                        "content": json.dumps(
                            {
                                "type": "pdf",
                                "filename": "document.pdf",
                                "embed_ref": "pdf_document_embed_ref",
                                "status": "processing",
                                "files": {"original": {"s3_key": "uploads/user/document.pdf"}},
                                "vault_wrapped_aes_key": "wrapped-key",
                                "aes_nonce": "nonce",
                                "s3_base_url": "s3://bucket",
                                "page_count": 3,
                            }
                        ),
                    }
                ],
            },
        )
    )

    assert captured_tasks
    arguments = captured_tasks[0]["kwargs"]["arguments"]
    assert arguments["embed_ref"] == "pdf_document_embed_ref"
    assert arguments["chat_id"] == "chat-123"
    assert arguments["message_id"] == "msg-123"
