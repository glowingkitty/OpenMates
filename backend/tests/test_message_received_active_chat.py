# backend/tests/test_message_received_active_chat.py
#
# Regression coverage for WebSocket message dispatch ordering.
# New-chat sends can race with set_active_chat acknowledgements when the
# ack path is delayed by last_opened persistence. The message handler must
# make the originating connection active before AI dispatch so stream chunks
# are routed back to the sending browser deterministically.

# contract-test-file: infrastructure

import asyncio
import base64
import hashlib
import json
import sys

import pytest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from backend.core.api.app.services.directus.team_methods import hash_id

sys.modules.setdefault(
    "backend.core.api.app.services.cache",
    SimpleNamespace(CacheService=object),
)
sys.modules.setdefault(
    "backend.core.api.app.services.directus.directus",
    SimpleNamespace(DirectusService=object),
)


@pytest.fixture(autouse=True)
def stub_async_skill_turn_fence(monkeypatch):
    """Keep turn-fencing tests isolated from worker/Celery imports."""
    tasks_module = ModuleType("backend.apps.ai.tasks")
    tasks_module.__path__ = []
    continuation = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    continuation.ASYNC_SKILL_CONTINUATION_TTL_SECONDS = 900
    continuation.async_skill_latest_user_turn_key = lambda user_id, chat_id: f"turn:{user_id}:{chat_id}"
    monkeypatch.setitem(sys.modules, tasks_module.__name__, tasks_module)
    monkeypatch.setitem(sys.modules, continuation.__name__, continuation)

class FakeManager:
    def __init__(self):
        self.calls = []
        self.broadcasts = []

    def get_volatile_session_nonce(self, user_id, device_fingerprint_hash):
        return "test-live-session-nonce"

    def set_active_chat(self, user_id, device_fingerprint_hash, chat_id):
        self.calls.append(("set_active_chat", user_id, device_fingerprint_hash, chat_id))

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.calls.append(("send_personal_message", message.get("type"), user_id, device_fingerprint_hash))

    async def broadcast_to_user(self, message, user_id, exclude_device_hash=None):
        self.broadcasts.append(message)
        self.calls.append(("broadcast_to_user", message.get("type"), user_id, exclude_device_hash))

    async def broadcast_to_user_specific_event(self, user_id, event_name, payload):
        self.calls.append(("broadcast_to_user_specific_event", event_name, user_id, payload.get("chat_id")))


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, message):
        self.sent.append(message)


class FakeEmbedService:
    def __init__(self, cache_service, directus_service, encryption_service):
        pass

    async def resolve_embed_references_in_content(self, content, user_vault_key_id, log_prefix, seen_embed_refs):
        return content, {}


def client_ciphertext(label: bytes = b"ciphertext-ok") -> str:
    return base64.b64encode(b"OM" + bytes.fromhex("1a5b3b7c") + (b"0" * 12) + label + (b"t" * 16)).decode("ascii")


# contract-test: direct surface=rest_api assertions=teams.chat.encrypted-until-invoked,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_ordinary_team_relay_proof_sends_only_hashed_identity_and_ciphertext_digest(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    calls = []

    class Recovery:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, data):
            calls.append((operation, data))
            return {"committed": True}

    monkeypatch.setattr(message_received_handler, "ChatRecoveryService", Recovery)
    ciphertext = client_ciphertext()
    assert await message_received_handler._ordinary_team_message_is_committed(
        object(), preflight_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        team_id="team-123", chat_id="chat-123", message_id="msg-123",
        user_id="user-123", encrypted_content=ciphertext,
    )
    assert calls == [("verify_committed_team_message", {
        "protocol_version": 1,
        "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "hashed_user_id": hash_id("user-123"),
        "hashed_team_id": hash_id("team-123"),
        "chat_id": "chat-123",
        "user_message_id": "msg-123",
        "encrypted_content_digest": hashlib.sha256(ciphertext.encode()).hexdigest(),
    })]


# contract-test: direct surface=rest_api assertions=teams.chat.encrypted-until-invoked,teams.collaboration.realtime-team-sync
@pytest.mark.asyncio
async def test_uncommitted_ordinary_team_message_has_no_fanout_or_confirmation(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    websocket = FakeWebSocket()
    broadcast = AsyncMock()
    mentions = AsyncMock()
    proof = AsyncMock(return_value=False)
    monkeypatch.setattr(message_received_handler, "broadcast_team_event", broadcast)
    monkeypatch.setattr(message_received_handler, "notify_team_member_mentions", mentions)
    monkeypatch.setattr(message_received_handler, "_ordinary_team_message_is_committed", proof)
    monkeypatch.setattr(message_received_handler, "ChatRecoveryCutoverController", lambda *_: SimpleNamespace(
        get_epoch=AsyncMock(return_value=0),
    ))
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "member"})),
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_team_id": hash_id("team-123"), "messages_v": 1,
        })),
    )
    await message_received_handler.handle_message_received(
        websocket=websocket, manager=manager, cache_service=SimpleNamespace(),
        directus_service=directus, encryption_service=SimpleNamespace(),
        user_id="user-123", device_fingerprint_hash="device-123",
        payload={
            "chat_id": "team-chat-123", "team_id": "team-123",
            "preflight_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "message": {"message_id": "msg-123", "role": "user",
                        "encrypted_content": client_ciphertext(), "created_at": 100},
        },
    )
    proof.assert_awaited_once()
    broadcast.assert_not_awaited()
    mentions.assert_not_awaited()
    assert websocket.sent == []
    assert manager.calls == [("send_personal_message", "error", "user-123", "device-123")]


class FakeSkillRegistry:
    def __init__(self, manager):
        self.manager = manager

    async def dispatch_skill(self, app_name, skill_name, request_payload):
        assert app_name == "ai"
        assert skill_name == "ask"
        assert self.manager.calls[0][0] == "set_active_chat"
        self.manager.request_payload = request_payload
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


# contract-test: supporting surface=rest_api assertions=projects.focus.inferred-consent
@pytest.mark.parametrize("message, expected", [
    ('Read my Project named "Garden notes".', ["project-project-a"]),
    ("Update GARDEN   NOTES/readme.md", ["project-project-a"]),
    ("Read Garden notebook", []),
    ("Read MyGarden notesArchive", []),
    ("Please change the second line", []),
])
def test_exact_project_name_remains_a_routing_hint_without_access(message, expected):
    from backend.core.api.app.services.project_focus_request_service import explicitly_named_project_focus_ids

    assert explicitly_named_project_focus_ids(message, [{"project_id": "project-a", "name": "Garden notes"}]) == expected


# contract-test: supporting surface=rest_api assertions=chats.fork.non-destructive-boundary,projects.focus.inferred-consent
@pytest.mark.parametrize("chat_metadata", [
    None,
    {"messages_v": 0, "title_v": None},
    {"messages_v": 0, "title_v": None, "encrypted_title": "cipher-title"},
    {"messages_v": 0, "title_v": 0, "encrypted_title": "cipher-title"},
])
def test_message_send_marks_origin_connection_active_before_ai_dispatch(monkeypatch, chat_metadata):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    cutover = SimpleNamespace(
        get_epoch=AsyncMock(return_value=0),
        admit_legacy_inference=AsyncMock(return_value={"admitted": True}),
        release_legacy_inference=AsyncMock(return_value={"released": True}),
    )
    cache_service = SimpleNamespace(
        set=AsyncMock(return_value=True),
        get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 1, "last_edited_overall_timestamp": 1_700_000_000}
        ),
        increment_and_tombstone_user_draft=AsyncMock(return_value=4),
        get_ai_messages_history=AsyncMock(return_value=[]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
        set_active_ai_task=AsyncMock(),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value=chat_metadata),
            check_chat_ownership=AsyncMock(return_value=True),
        ),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    encryption_service = SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("encrypted", 1)))
    payload = {
        "chat_id": "chat-123",
        "project_focus_candidates": [{"project_id": "11111111-1111-4111-8111-111111111111", "name": "Garden notes"}],
        "message": {
            "message_id": "msg-123",
            "role": "user",
            "content": "What is the capital of France?",
            "created_at": 1_700_000_000,
            "chat_has_title": False,
            "project_focus_candidates": [{"project_id": "nested-decoy", "name": "Ignore nested routing data"}],
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

    websocket = FakeWebSocket()

    asyncio.run(
        message_received_handler.handle_message_received(
            websocket=websocket,
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
    expected_title = bool(chat_metadata and chat_metadata.get("encrypted_title") and chat_metadata.get("title_v") is None)
    assert manager.request_payload["chat_has_title"] is expected_title
    assert manager.request_payload["project_focus_candidates"] == payload["project_focus_candidates"]
    assert manager.request_payload["active_project_focus"] is None
    assert websocket.sent[0] == {
        "type": "chat_message_confirmed",
        "payload": {
            "chat_id": "chat-123",
            "message_id": "msg-123",
            "temp_id": None,
            "new_messages_v": 1,
            "new_last_edited_overall_timestamp": 1_700_000_000,
        },
    }
    assert not any(call[0] == "broadcast_to_user_specific_event" and call[1] == "chat_message_confirmed" for call in manager.calls)
    cutover.get_epoch.assert_awaited_once_with(authoritative=True)
    cache_service.set_active_ai_task.assert_awaited_once_with("chat-123", "task-123")
    cache_service.increment_and_tombstone_user_draft.assert_awaited_once_with("user-123", "chat-123")
    assert {
        "type": "draft_deleted",
        "payload": {"chat_id": "chat-123", "draft_v": 4},
    } in manager.broadcasts


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
        set=AsyncMock(return_value=True),
        get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 1, "last_edited_overall_timestamp": 1_700_000_000}
        ),
        increment_and_tombstone_user_draft=AsyncMock(return_value=1),
        set_embed_in_cache=AsyncMock(),
        add_embed_id_to_chat_index=AsyncMock(),
        get_ai_messages_history=AsyncMock(return_value=[]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
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
    assert captured["has_image_upload_embed"] is True
    cache_service.set_active_ai_task.assert_awaited_once_with("chat-123", "task-123")


def test_recovery_send_does_not_enqueue_while_another_task_is_active(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    cache_service = SimpleNamespace(
        set=AsyncMock(return_value=True),
        get=AsyncMock(return_value=None),
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
        set=AsyncMock(return_value=True),
        get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 5, "last_edited_overall_timestamp": 1_700_000_010}
        ),
        increment_and_tombstone_user_draft=AsyncMock(return_value=1),
        get_ai_messages_history=AsyncMock(return_value=cached_messages),
        delete_ai_messages_history=AsyncMock(),
        add_message_to_chat_history=AsyncMock(),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
        set_active_ai_task=AsyncMock(),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(
                return_value={"messages_v": 4, "title_v": 1, "hashed_team_id": hash_id("team-123")}
            ),
            check_chat_ownership=AsyncMock(return_value=False),
        ),
        team=SimpleNamespace(
            require_team_role=AsyncMock(return_value={"role": "owner"}),
            list_active_member_hashes=AsyncMock(return_value=set()),
        ),
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

    async def fake_broadcast_team_event(**_kwargs):
        return None

    async def fake_notify_team_member_mentions(**_kwargs):
        return None

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
    monkeypatch.setattr(message_received_handler, "broadcast_team_event", fake_broadcast_team_event)
    monkeypatch.setattr(message_received_handler, "notify_team_member_mentions", fake_notify_team_member_mentions)
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
                    "encrypted_content": client_ciphertext(b"team-current"),
                    "created_at": 1_700_000_010,
                    "chat_has_title": True,
                },
                "team_ai_invocation": {
                    "history": [
                        {
                            "role": "user",
                            "content": "@openmates summarize this",
                            "created_at": 1_700_000_010,
                        }
                    ]
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
        set=AsyncMock(return_value=True),
        get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 2, "last_edited_overall_timestamp": 1_700_000_010}
        ),
        increment_and_tombstone_user_draft=AsyncMock(return_value=1),
        get_ai_messages_history=AsyncMock(return_value=[cached_current_message]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
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
        set=AsyncMock(return_value=True),
        get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        delete_ai_messages_history=AsyncMock(),
        add_message_to_chat_history=AsyncMock(),
        get_ai_messages_history=AsyncMock(return_value=[]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
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
        set=AsyncMock(return_value=True),
        get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 1, "last_edited_overall_timestamp": 1_700_000_000}
        ),
        increment_and_tombstone_user_draft=AsyncMock(return_value=1),
        get_ai_messages_history=AsyncMock(return_value=[]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
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


def test_existing_personal_chat_rejects_user_user_ai_cache_history(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    captured: dict[str, object] = {}

    class CapturingSkillRegistry:
        async def dispatch_skill(self, app_name, skill_name, request_payload):
            captured.update(request_payload)
            return {"task_id": "task-123"}

    cutover = SimpleNamespace(
        get_epoch=AsyncMock(return_value=0),
        admit_legacy_inference=AsyncMock(return_value={"admitted": True}),
        release_legacy_inference=AsyncMock(return_value={"released": True}),
    )
    cached_messages = [
        json.dumps(
            {
                "id": "msg-current",
                "chat_id": "chat-123",
                "role": "user",
                "sender_name": "user",
                "encrypted_content": "encrypted-current",
                "created_at": 1_700_000_020,
            }
        ),
        json.dumps(
            {
                "id": "msg-first",
                "chat_id": "chat-123",
                "role": "user",
                "sender_name": "user",
                "encrypted_content": "encrypted-first",
                "created_at": 1_700_000_000,
            }
        ),
    ]
    cache_service = SimpleNamespace(
        set=AsyncMock(return_value=True),
        get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(
            return_value={"messages_v": 3, "last_edited_overall_timestamp": 1_700_000_020}
        ),
        increment_and_tombstone_user_draft=AsyncMock(return_value=1),
        get_ai_messages_history=AsyncMock(return_value=cached_messages),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
        set_active_ai_task=AsyncMock(),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value={"messages_v": 2, "title_v": 1}),
            check_chat_ownership=AsyncMock(return_value=True),
        ),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    encryption_service = SimpleNamespace(
        encrypt_with_user_key=AsyncMock(return_value=("encrypted-current", 1)),
        decrypt_with_user_key=AsyncMock(side_effect=["follow-up", "first question"]),
    )

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
            payload={
                "chat_id": "chat-123",
                "message": {
                    "message_id": "msg-current",
                    "role": "user",
                    "content": "follow-up",
                    "created_at": 1_700_000_020,
                    "chat_has_title": True,
                },
            },
        )
    )

    assert not captured
    history_requests = [
        call
        for call in manager.calls
        if call[:2] == ("send_personal_message", "request_chat_history")
    ]
    assert history_requests
    cache_service.set_active_ai_task.assert_not_awaited()
