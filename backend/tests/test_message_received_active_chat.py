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


class FakeNoTaskSkillRegistry:
    def __init__(self, manager):
        self.manager = manager

    async def dispatch_skill(self, app_name, skill_name, request_payload):
        assert app_name == "ai"
        assert skill_name == "ask"
        self.manager.calls.append(("dispatch_skill", app_name, skill_name, request_payload["chat_id"]))
        return {"status": "accepted_without_task"}


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


def test_message_send_forwards_client_embed_ref_index(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    captured: dict[str, object] = {}

    class CapturingSkillRegistry:
        async def dispatch_skill(self, app_name, skill_name, request_payload):
            assert app_name == "ai"
            assert skill_name == "ask"
            captured.update(request_payload)
            return {"task_id": "task-123"}

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
        set_embed_in_cache=AsyncMock(),
        add_embed_id_to_chat_index=AsyncMock(),
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
            "content": "Turn this into HTML\n[!](embed:mockup-png-abc123)",
            "created_at": 1_700_000_000,
            "chat_has_title": False,
        },
        "embeds": [
            {
                "embed_id": "embed-image-1",
                "type": "image",
                "content": json.dumps({
                    "type": "image",
                    "embed_ref": "mockup-png-abc123",
                    "status": "finished",
                    "filename": "mockup.png",
                }),
                "status": "finished",
                "text_preview": "mockup.png",
            }
        ],
    }

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.embed_service",
        SimpleNamespace(EmbedService=FakeEmbedService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.skill_registry",
        SimpleNamespace(get_global_registry=lambda: CapturingSkillRegistry()),
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

    assert captured["embed_file_path_index"] == {"mockup-png-abc123": "embed-image-1"}
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


def test_team_recovery_send_skips_personal_cache_completeness_gate(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    cutover = SimpleNamespace(get_epoch=AsyncMock(return_value=1))
    cached_messages = [
        json.dumps(
            {
                "id": "msg-current",
                "chat_id": "team-chat-123",
                "role": "user",
                "sender_name": "user",
                "encrypted_content": "encrypted-current",
                "created_at": 1_700_000_010,
            }
        ),
        json.dumps(
            {
                "id": "msg-owner-previous",
                "chat_id": "team-chat-123",
                "role": "user",
                "sender_name": "user",
                "encrypted_content": "encrypted-previous",
                "created_at": 1_700_000_000,
            }
        ),
    ]
    cache_service = SimpleNamespace(
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 5, "last_edited_overall_timestamp": 1_700_000_010}
        ),
        delete_user_draft_from_cache=AsyncMock(return_value=False),
        delete_user_draft_version_from_chat_versions=AsyncMock(return_value=False),
        get_ai_messages_history=AsyncMock(return_value=cached_messages),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        set_active_ai_task=AsyncMock(),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value={"messages_v": 4, "title_v": 1}),
            check_chat_ownership=AsyncMock(return_value=False),
        ),
        team=SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "owner"})),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    encryption_service = SimpleNamespace(
        encrypt_with_user_key=AsyncMock(return_value=("encrypted-current", 1)),
        decrypt_with_user_key=AsyncMock(side_effect=["@openmates summarize this", "Earlier owner note"]),
    )
    enqueue = AsyncMock(
        return_value={
            "inference_task_id": "task-123",
            "outbox_id": "outbox-123",
        }
    )
    recovery_calls = []

    class FakeRecoveryService:
        def __init__(self, directus_service):
            self.directus_service = directus_service

        async def execute(self, operation, data):
            recovery_calls.append((operation, data))
            return {"dispatched": True}

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
    monkeypatch.setattr(message_received_handler, "enqueue_chat_turn", enqueue)
    monkeypatch.setattr(message_received_handler, "ChatRecoveryService", FakeRecoveryService)
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
                "chat_id": "team-chat-123",
                "team_id": "team-123",
                "protocol_version": 1,
                "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "turn_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "recovery_public_key": "recovery-public-key",
                "chat_key_version": 1,
                "message": {
                    "message_id": "msg-current",
                    "role": "user",
                    "content": "@openmates summarize this",
                    "created_at": 1_700_000_010,
                    "chat_has_title": True,
                },
            },
        )
    )

    assert ("dispatch_skill", "ai", "ask", "team-chat-123") in manager.calls
    assert not any(call[1] == "request_chat_history" for call in manager.calls if call[0] == "send_personal_message")
    enqueue.assert_awaited_once()
    assert recovery_calls[0][0] == "mark_outbox_dispatched"
    cache_service.set_active_ai_task.assert_awaited_once_with("team-chat-123", "task-123")
    directus_service.chat.check_chat_ownership.assert_not_awaited()


def test_recovery_send_marks_enqueue_failed_when_dispatch_returns_no_task(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    cutover = SimpleNamespace(get_epoch=AsyncMock(return_value=1))
    cached_current_message = json.dumps(
        {
            "id": "msg-current",
            "chat_id": "chat-123",
            "role": "user",
            "sender_name": "user",
            "encrypted_content": "encrypted-current",
            "created_at": 1_700_000_010,
        }
    )
    cache_service = SimpleNamespace(
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 2, "last_edited_overall_timestamp": 1_700_000_010}
        ),
        delete_user_draft_from_cache=AsyncMock(return_value=False),
        delete_user_draft_version_from_chat_versions=AsyncMock(return_value=False),
        get_ai_messages_history=AsyncMock(return_value=[cached_current_message]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        set_active_ai_task=AsyncMock(),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value={"messages_v": 1, "title_v": 1}),
            check_chat_ownership=AsyncMock(return_value=True),
        ),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    encryption_service = SimpleNamespace(
        encrypt_with_user_key=AsyncMock(return_value=("encrypted-current", 1)),
        decrypt_with_user_key=AsyncMock(return_value="retry me"),
    )
    enqueue = AsyncMock(
        return_value={
            "inference_task_id": "task-123",
            "outbox_id": "outbox-123",
            "committed_messages_v": 2,
        }
    )
    recovery_calls = []

    class FakeRecoveryService:
        def __init__(self, directus_service):
            self.directus_service = directus_service

        async def execute(self, operation, data):
            recovery_calls.append((operation, data))
            return {"failed": True}

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.embed_service",
        SimpleNamespace(EmbedService=FakeEmbedService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.skill_registry",
        SimpleNamespace(get_global_registry=lambda: FakeNoTaskSkillRegistry(manager)),
    )
    monkeypatch.setattr(message_received_handler, "enqueue_chat_turn", enqueue)
    monkeypatch.setattr(message_received_handler, "ChatRecoveryService", FakeRecoveryService)
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
                "protocol_version": 1,
                "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "turn_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "recovery_public_key": "recovery-public-key",
                "chat_key_version": 1,
                "message": {
                    "message_id": "msg-current",
                    "role": "user",
                    "content": "retry me",
                    "created_at": 1_700_000_010,
                    "chat_has_title": True,
                },
            },
        )
    )

    assert ("dispatch_skill", "ai", "ask", "chat-123") in manager.calls
    assert recovery_calls == [
        (
            "mark_inference_failed",
            {
                "protocol_version": 1,
                "inference_task_id": "task-123",
                "failure_category": "dispatch_failed",
            },
        )
    ]
    cache_service.set_active_ai_task.assert_not_awaited()
    error_payloads = [call for call in manager.calls if call[:2] == ("send_personal_message", "error")]
    assert error_payloads


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
