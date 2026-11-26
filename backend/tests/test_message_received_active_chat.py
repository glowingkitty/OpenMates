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
from unittest.mock import AsyncMock, Mock

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
def stub_chat_orchestration_hooks(monkeypatch):
    """Treat every turn as a user-typed message in an ordinary chat.

    Chat orchestration (origin, streak, spawned-chat classification) needs a
    live Redis client and is covered by its own tests; these dispatch tests
    use cache fakes without one.
    """
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler
    from backend.shared.python_utils import chat_orchestration_interpretation, chat_orchestration_safety

    monkeypatch.setattr(chat_orchestration_safety, "record_message_origin",
                        AsyncMock(return_value={"origin": "user"}))
    monkeypatch.setattr(chat_orchestration_interpretation, "reset_streak", AsyncMock())
    monkeypatch.setattr(message_received_handler, "classify_chat_message", AsyncMock(return_value=None))


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
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler
    monkeypatch.setattr(message_received_handler, "paused_code_work", AsyncMock(return_value=[]))


class FakeManager:
    def __init__(self):
        self.calls = []
        self.messages = []
        self.broadcasts = []

    def get_volatile_session_nonce(self, user_id, device_fingerprint_hash):
        return "test-live-session-nonce"

    def set_active_chat(self, user_id, device_fingerprint_hash, chat_id):
        self.calls.append(("set_active_chat", user_id, device_fingerprint_hash, chat_id))

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.calls.append(("send_personal_message", message.get("type"), user_id, device_fingerprint_hash))
        self.messages.append(message)

    async def broadcast_to_user(self, message, user_id, exclude_device_hash=None):
        self.broadcasts.append(message)
        self.calls.append(("broadcast_to_user", message.get("type"), user_id, exclude_device_hash))

    async def broadcast_to_user_specific_event(self, user_id, event_name, payload):
        self.calls.append(("broadcast_to_user_specific_event", event_name, user_id, payload.get("chat_id")))


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.scope = {}

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
        return {"task_id": (request_payload.get("recovery_task_id") or request_payload.get("legacy_cutover_task_id")
                            or request_payload.get("volatile_dispatch_task_id") or "task-123")}


class FakeNoTaskSkillRegistry:
    def __init__(self, manager):
        self.manager = manager

    async def dispatch_skill(self, app_name, skill_name, request_payload):
        assert app_name == "ai"
        assert skill_name == "ask"
        self.manager.request_payload = request_payload
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
    {"hashed_user_id": hash_id("user-123"), "chat_visibility": None, "messages_v": 0, "title_v": 0},
    {"id": "chat-123", "hashed_user_id": hash_id("user-123"), "chat_visibility": None,
     "messages_v": 0, "title_v": 0},
])
@pytest.mark.parametrize("context_bound", [False, True])
@pytest.mark.parametrize("related_discovery", [None, False, True])
def test_message_send_marks_origin_connection_active_before_ai_dispatch(monkeypatch, chat_metadata, context_bound, related_discovery):
    _exercise_ordinary_dispatch(monkeypatch, chat_metadata, context_bound, related_discovery)


def test_saved_child_user_message_gets_fresh_ordinary_admission(monkeypatch):
    result = _exercise_ordinary_dispatch(monkeypatch, {
        "id": "chat-123", "hashed_user_id": hash_id("user-123"), "chat_visibility": None,
        "parent_id": "canonical-parent", "is_sub_chat": True,
        "budget_limit": 200, "budget_spent": 40, "messages_v": 2,
    }, related_discovery=False)
    request = result.manager.request_payload
    assert request["is_sub_chat"] is False
    assert request["parent_id"] == "canonical-parent"
    assert request["legacy_cutover_task_id"] == hashlib.sha256(b"user-123:chat-123:msg-123").hexdigest()


def _exercise_ordinary_dispatch(monkeypatch, chat_metadata=None, context_bound=False, related_discovery=None,
                                outcome="processing", *, voice=False, queued=False, active_task_id=None,
                                durable=False, exact_retry=False, independent=False, native_terminal=False,
                                parallel_capable=True, web_socket=False,
                                user_content=None, newly_enqueued=False, independent_retry=False):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    reconcile = AsyncMock()
    alert = AsyncMock()
    monkeypatch.setattr(message_received_handler, "_reconcile_existing_legacy_turn", reconcile)
    monkeypatch.setattr(message_received_handler, "notify_chat_failure", alert)
    dispatch = FakeSkillRegistry.dispatch_skill

    async def dispatch_with_outcome(registry, *args):
        response = await dispatch(registry, *args)
        if outcome == "mismatch":
            raise message_received_handler.ChatRecoveryProtocolError(409, "legacy_dispatch_mismatch")
        if outcome == "broker_failure":
            raise RuntimeError("broker unavailable")
        return {**response, "status": outcome}

    monkeypatch.setattr(FakeSkillRegistry, "dispatch_skill", dispatch_with_outcome)
    manager = FakeManager()
    cutover = SimpleNamespace(
        get_epoch=AsyncMock(return_value=int(durable)),
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
        delete_ai_messages_history=AsyncMock(return_value=True),
        add_message_to_chat_history=AsyncMock(return_value=True),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=active_task_id),
        get_active_artifact_steer_target=AsyncMock(return_value=True),
        queue_message=AsyncMock(return_value=True),
        mark_sync_message_queued=AsyncMock(return_value=True),
        has_queued_messages=AsyncMock(return_value=False),
        set_active_ai_task=AsyncMock(),
        try_claim_active_ai_task=AsyncMock(return_value=True),
        clear_active_ai_task_if_matches=AsyncMock(return_value=True),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value=chat_metadata),
            release_inference_outbox=AsyncMock(return_value={"status": "released"}),
            mark_queued_message_pending=AsyncMock(return_value={"status": "queued", "messages_v": 3}),
            check_chat_ownership=AsyncMock(return_value=True),
        ),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    encryption_service = SimpleNamespace(
        encrypt_with_user_key=AsyncMock(return_value=("encrypted", 1)),
        encrypt_many_with_user_key=AsyncMock(side_effect=lambda contents, _: [(f"vault:v1:history-{index}", 1) for index, _ in enumerate(contents)]),
    )
    routing_restrictions = {"disabled_ai_models": ["mercury-3"],
                            "disabled_ai_servers": {"gemini-3.8-flash": ["google_ai_studio"]}}
    payload = {
        "model_routing_restrictions": routing_restrictions,
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
    task_id = "11111111-aaaa-4111-8111-111111111111"
    if exact_retry:
        cache_service.get_active_ai_task.return_value = task_id
    turn_id = "22222222-aaaa-4222-8222-222222222222"
    preflight_id = "33333333-aaaa-4333-8333-333333333333"
    outbox_id = "44444444-aaaa-4444-8444-444444444444"
    voice_check = AsyncMock()
    if voice:
        from backend.shared.python_utils import voice_call_admission

        call_id = "a" * 32
        voice_check.return_value = voice_call_admission.VoiceCallDelivery(True, call_id, "msg-123")
        monkeypatch.setattr(voice_call_admission, "admit_voice_call_turn", voice_check)
        payload["message"].update(voice_mode=True, voice_call_id=call_id, voice_turn_id="msg-123")
    if durable:
        monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "test-active-input-commitment")
        enqueue = AsyncMock(return_value={
            "inference_task_id": task_id, "outbox_id": outbox_id, "state": "ENQUEUED",
            **({"newly_enqueued": True} if newly_enqueued else {}),
        })
        monkeypatch.setattr(message_received_handler, "enqueue_chat_turn", enqueue)
        monkeypatch.setattr(message_received_handler, "ChatRecoveryService", lambda _: SimpleNamespace(
            execute=AsyncMock(),
        ))
        payload.update(protocol_version=1, turn_id=turn_id, preflight_id=preflight_id)
    if queued:
        import types

        worker = types.ModuleType("backend.apps.ai.tasks.ask_skill_task")
        worker.resume_legacy_queued_handoff = AsyncMock()
        monkeypatch.setitem(sys.modules, worker.__name__, worker)
    if related_discovery is not None:
        payload["related_task_candidates"] = [
            {"task_id": "discovery-task", "summary": "Unrelated prior work", "explicit_dependency": related_discovery},
        ]
        payload["message"]["content"] = "And France?"
        payload["message_history"] = [
            {"role": "user", "content": "What is the capital of Spain?", "created_at": 1_699_999_998},
            {"role": "assistant", "content": "Madrid.", "created_at": 1_699_999_999},
        ]
    context_turn_id = "22222222-2222-4222-8222-222222222222" if context_bound else None
    if context_bound:
        payload.update(
            turn_id=context_turn_id,
            client_context_pending=True,
            client_context_request_id="44444444-4444-4444-8444-444444444444",
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
    monkeypatch.setattr(
        message_received_handler,
        "ChatRecoveryCutoverController",
        lambda cache, directus: cutover,
    )

    websocket = FakeWebSocket()
    if native_terminal:
        websocket.headers = {} if web_socket else {"x-openmates-sdk": "cli"}
        websocket.scope["parallel_chat_turns_v1"] = parallel_capable
        cache_service.get.return_value = "older-user-turn"
        cache_service.delete = AsyncMock(return_value=True)
        payload["message"]["content"] = "What does the cache flag do?"
        payload["message_history"] = [
            {"message_id": "definition", "role": "assistant",
             "content": "The cache flag reuses completed build output.", "created_at": 1_699_999_998},
            {"message_id": "older-user-turn", "role": "user",
             "content": "Build the application", "created_at": 1_699_999_999},
        ]
    if user_content is not None:
        payload["message"]["content"] = user_content

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
            client_context_binding_ref="server-binding" if context_bound else None,
            client_context_turn_id=context_turn_id,
        )
    )

    assert manager.calls[0] == ("set_active_chat", "user-123", "device-123", "chat-123")
    if exact_retry or independent_retry:
        cache_service.queue_message.assert_not_awaited()
        cache_service.try_claim_active_ai_task.assert_not_awaited()
        directus_service.chat.release_inference_outbox.assert_not_awaited()
        assert ("dispatch_skill", "ai", "ask", "chat-123") not in manager.calls
        response = manager.messages[-1]["payload"]
        assert response["ai_task_id"] == task_id
        assert response.get("independent_reply", False) is independent_retry
        return SimpleNamespace(manager=manager, cache=cache_service)
    if queued:
        cache_service.queue_message.assert_awaited_once()
        directus_service.chat.release_inference_outbox.assert_not_awaited()
        assert ("dispatch_skill", "ai", "ask", "chat-123") not in manager.calls
        return SimpleNamespace(manager=manager, cache=cache_service, enqueue=enqueue, payload=payload)
    assert manager.calls.count(("dispatch_skill", "ai", "ask", "chat-123")) == 1
    if voice:
        assert voice_check.await_count == 2
        assert manager.request_payload["voice_turn_id"] == "msg-123"
        assert manager.request_payload["voice_mode"] is True
    if durable:
        enqueue.assert_awaited_once()
        directus_service.chat.release_inference_outbox.assert_awaited_once_with(
            preflight_id, task_id, outbox_id, "user-123",
        )
    assert manager.request_payload["user_preferences"]["disabled_ai_models"] == ["mercury-3"]
    assert manager.request_payload["user_preferences"]["disabled_ai_servers"] == {"gemini-3.8-flash": ["google_ai_studio"]}
    # These local encrypted preferences are not copied into the account cache.
    for call in cache_service.update_user.call_args_list:
        assert "disabled_ai_models" not in call.args[1]
        assert "disabled_ai_servers" not in call.args[1]
    assert routing_restrictions == payload["model_routing_restrictions"]
    expected_title = bool(chat_metadata and (
        (chat_metadata.get("title_v") or 0) > 0
        or (chat_metadata.get("encrypted_title") and chat_metadata.get("title_v") is None)
    ))
    assert manager.request_payload["chat_has_title"] is expected_title
    assert manager.request_payload["project_focus_candidates"] == payload["project_focus_candidates"]
    assert manager.request_payload["active_project_focus"] is None
    assert manager.request_payload["client_context_pending"] is context_bound
    assert manager.request_payload["admission_context"]["scope_complete"] is (
        not context_bound and related_discovery is not True
    )
    if related_discovery is not None:
        assert [row["content"] for row in manager.request_payload["message_history"]] == [
            "What is the capital of Spain?", "Madrid.", "And France?",
        ]
        assert manager.request_payload["related_task_candidates"] == payload["related_task_candidates"]
    assert manager.request_payload["client_context_turn_id"] == context_turn_id
    assert manager.request_payload["recovery_turn_id"] == (turn_id if durable else None)
    if not durable:
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
    if chat_metadata and chat_metadata.get("id") == "chat-123":
        directus_service.chat.check_chat_ownership.assert_awaited_once_with(
            "chat-123", "user-123", authoritative_metadata=chat_metadata,
        )
    elif chat_metadata:
        directus_service.chat.check_chat_ownership.assert_awaited_once_with(
            "chat-123", "user-123",
        )
    claimed_task = task_id if durable else hashlib.sha256(b"user-123:chat-123:msg-123").hexdigest()
    if independent:
        cache_service.try_claim_active_ai_task.assert_not_awaited()
    else:
        cache_service.try_claim_active_ai_task.assert_awaited_once_with("chat-123", claimed_task)
    cache_service.set_active_ai_task.assert_not_awaited()
    cache_service.increment_and_tombstone_user_draft.assert_awaited_once_with("user-123", "chat-123")
    assert {
        "type": "draft_deleted",
        "payload": {"chat_id": "chat-123", "draft_v": 4},
    } in manager.broadcasts

    return SimpleNamespace(manager=manager, cache=cache_service, reconcile=reconcile, alert=alert)


# contract-test: direct surface=rest_api assertions=chats.message.identity-idempotent,operational-monitoring.chat-failures.email-trigger
@pytest.mark.parametrize("outcome", ["already_dispatched", "mismatch", "broker_failure"])
def test_legacy_dispatch_retry_reconciles_but_genuine_failures_still_alert(monkeypatch, outcome):
    context = _exercise_ordinary_dispatch(monkeypatch, outcome=outcome)
    if outcome == "already_dispatched":
        context.reconcile.assert_awaited_once()
        assert context.reconcile.await_args.kwargs["task_id"] == hashlib.sha256(b"user-123:chat-123:msg-123").hexdigest()
        context.alert.assert_not_awaited()
        assert not any(call[1] in ("ai_task_initiated", "error") for call in context.manager.calls)
    else:
        context.reconcile.assert_not_awaited()
        context.alert.assert_awaited_once_with("chat-123:msg-123", stage="dispatch")
        assert any(call[1] == "error" for call in context.manager.calls)
        error = next(message["payload"] for message in context.manager.messages if message["type"] == "error")
        # An immutable-binding rejection can never succeed on retry; a broker failure can.
        if outcome == "mismatch":
            assert (error["code"], error["retryable"]) == ("inference_temporarily_paused", False)
        else:
            assert (error["code"], error["retryable"]) == ("ai_dispatch_failed", True)


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", ["canonical", "pending", "running"])
# contract-test: direct surface=rest_api assertions=chats.message.identity-idempotent,chats.completion.recovery-takeover
async def test_existing_legacy_turn_replays_without_restarting_processing(monkeypatch, completed):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    canonical = {"role": "assistant", "chat_id": "chat", "message_id": "task",
                 "hashed_user_id": hash_id("owner"), "encrypted_content": "ciphertext"}
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_message_for_chat_by_client_id=AsyncMock(return_value=canonical if completed == "canonical" else None),
    ))
    snapshot = {"user_id_uuid": "owner", "chat_id": "chat", "message_id": "task",
                "full_content_so_far": "partial", "is_final_chunk": False}
    cache = SimpleNamespace(get=AsyncMock(return_value=snapshot),
                            clear_active_ai_task_if_matches=AsyncMock(return_value=True))
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    result = {"content": "completed answer", "fired_at": 1_700_000_000}
    monkeypatch.setattr(handler, "_read_completed_legacy_response",
                        lambda _: result if completed == "pending" else None)

    await handler._reconcile_existing_legacy_turn(
        cache_service=cache, directus_service=directus, manager=manager, user_id="owner", device_fingerprint_hash="device",
        chat_id="chat", task_id="task",
    )
    frames = [call.args[0] for call in manager.send_personal_message.await_args_list]
    assert all(call.args[1:] == ("owner", "device") for call in manager.send_personal_message.await_args_list)
    assert not any(frame["type"] in ("ai_task_initiated", "error") for frame in frames)
    if completed == "running":
        assert frames == [{"type": "ai_message_update", "payload": snapshot}]
        cache.clear_active_ai_task_if_matches.assert_not_awaited()
    else:
        cache.clear_active_ai_task_if_matches.assert_awaited_once_with("chat", "task")
        assert [frame["type"] for frame in frames[-2:]] == ["ai_message_ready", "ai_typing_ended"]
        if completed == "canonical":
            assert frames[0]["type"] == "chat_content_batch_response"
            # The exact row is replayed, independent of latest-window bounds.
            rows = frames[0]["payload"]["messages_by_chat_id"]["chat"]
            assert [json.loads(row) for row in rows] == [{**canonical, "status": "synced"}]
        else:
            assert frames[0] == {"type": "pending_ai_response", "payload": {
                "type": "ai_response", "chat_id": "chat", "message_id": "task",
                "user_id": "owner", **result,
            }}


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [{"user_id_uuid": "foreign"}, {"chat_id": "foreign"},
                                    {"message_id": "newer-task"}, {"external_request": True},
                                    {"is_final_chunk": True}])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.access.scoped,chats.message.identity-idempotent
async def test_existing_legacy_retry_never_replays_another_stream(monkeypatch, changed):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    monkeypatch.setattr(handler, "_read_completed_legacy_response", lambda _: None)
    snapshot = {"user_id_uuid": "owner", "chat_id": "chat", "message_id": "task", **changed}
    cache = SimpleNamespace(get=AsyncMock(return_value=snapshot),
                            clear_active_ai_task_if_matches=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handler._reconcile_existing_legacy_turn(
        cache_service=cache, directus_service=SimpleNamespace(chat=SimpleNamespace(
            get_message_for_chat_by_client_id=AsyncMock(return_value=None))),
        manager=manager, user_id="owner",
        device_fingerprint_hash="device", chat_id="chat", task_id="task",
    )
    manager.send_personal_message.assert_not_awaited()
    cache.clear_active_ai_task_if_matches.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [{"hashed_user_id": "foreign"}, {"chat_id": "foreign"},
                                    {"message_id": "other"}, {"role": "user"}])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.access.scoped
async def test_existing_legacy_canonical_replay_requires_exact_owner_and_message(monkeypatch, changed):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    canonical = {"role": "assistant", "chat_id": "chat", "message_id": "task",
                 "hashed_user_id": hash_id("owner"), **changed}
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    cache = SimpleNamespace(clear_active_ai_task_if_matches=AsyncMock())
    with pytest.raises(RuntimeError, match="identity is inconsistent"):
        await handler._reconcile_existing_legacy_turn(
            cache_service=cache, directus_service=SimpleNamespace(chat=SimpleNamespace(
                get_message_for_chat_by_client_id=AsyncMock(return_value=canonical))),
            manager=manager, user_id="owner", device_fingerprint_hash="device",
            chat_id="chat", task_id="task",
        )
    manager.send_personal_message.assert_not_awaited()
    cache.clear_active_ai_task_if_matches.assert_not_awaited()


@pytest.mark.parametrize("state,changed,expected", [
    ("SUCCESS", {}, True), ("PENDING", {}, False),
    ("SUCCESS", {"task_id": "foreign"}, False),
    ("SUCCESS", {"interrupted_by_revocation": True}, False),
    ("SUCCESS", {"main_processing_output": None}, False),
])
# contract-test: direct surface=rest_api assertions=chats.completion.recovery-takeover
def test_existing_legacy_result_replay_requires_successful_matching_completion(monkeypatch, state, changed, expected):
    from datetime import datetime, timezone
    import celery.result
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    response = {"_celery_task_state": "SUCCESS", "task_id": "task",
                "main_processing_output": "answer", **changed}
    result = SimpleNamespace(state=state, result=response,
                             date_done=datetime(2026, 10, 22, 17, 30, tzinfo=timezone.utc))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=object()))
    monkeypatch.setattr(celery.result, "AsyncResult", lambda task_id, app: result)
    replay = handler._read_completed_legacy_response("task")
    assert (replay is not None) is expected
    if expected:
        assert replay == {"content": "answer", "fired_at": int(result.date_done.timestamp())}


@pytest.mark.parametrize("server_code,cache_ack", [(False, True), (True, True), (True, False)])
def test_message_send_forwards_client_embed_ref_index(monkeypatch, server_code, cache_ack):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    warning = Mock(wraps=message_received_handler.logger.warning)
    error = Mock(wraps=message_received_handler.logger.error)
    monkeypatch.setattr(message_received_handler.logger, "warning", warning)
    monkeypatch.setattr(message_received_handler.logger, "error", error)
    manager = FakeManager()
    captured: dict[str, object] = {}
    cached_embeds = []

    async def cache_embed(*, embed_id, embed_data, chat_id, ttl=86400):
        # Enforce the real cache contract rather than accepting arbitrary kwargs.
        cached_embeds.append((embed_id, embed_data, chat_id, ttl))
        return cache_ack

    class CodeEmbedService(FakeEmbedService):
        async def extract_code_blocks_from_user_message(self, **kwargs):
            return "Review [!](embed:sample.py)", [{
                "embed_id": "extracted-code-1", "type": "code", "status": "finished",
                "content": "type: code\ncode: print('synthetic code sentinel')",
                "filename": "sample.py",
            }]

    class CapturingSkillRegistry:
        async def dispatch_skill(self, app_name, skill_name, request_payload):
            assert app_name == "ai"
            assert skill_name == "ask"
            captured.update(request_payload)
            return {"task_id": request_payload["legacy_cutover_task_id"]}

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
        set_embed_in_cache=AsyncMock(side_effect=cache_embed),
        add_embed_id_to_chat_index=AsyncMock(),
        get_ai_messages_history=AsyncMock(return_value=[]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
        set_active_ai_task=AsyncMock(),
        try_claim_active_ai_task=AsyncMock(return_value=True),
        clear_active_ai_task_if_matches=AsyncMock(return_value=True),
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
    if server_code:
        payload["message"]["content"] = "Review this code:\n```python\nprint('synthetic code sentinel')\n```"
        payload["embeds"] = []

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.embed_service",
        SimpleNamespace(EmbedService=CodeEmbedService),
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
            websocket=SimpleNamespace(scope={}),
            manager=manager,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_id="user-123",
            device_fingerprint_hash="device-123",
            payload=payload,
        )
    )

    assert captured["embed_file_path_index"] == (None if server_code else {"mockup-png-abc123": "embed-image-1"})
    assert captured["has_image_upload_embed"] is (not server_code)
    assert len(cached_embeds) == 1
    embed_id, embed_data, indexed_chat, ttl = cached_embeds[0]
    assert embed_id == ("extracted-code-1" if server_code else "embed-image-1")
    assert indexed_chat == "chat-123" and ttl == 86400
    assert embed_data["encrypted_content"] == embed_data["encrypted_type"] == "encrypted"
    assert "synthetic code sentinel" not in json.dumps(embed_data)
    cache_service.add_embed_id_to_chat_index.assert_not_awaited()
    if not cache_ack:
        warning.assert_any_call("Code embed cache registration was not acknowledged")
    error.assert_not_called()
    cache_service.try_claim_active_ai_task.assert_awaited_once_with("chat-123", hashlib.sha256(b"user-123:chat-123:msg-123").hexdigest())
    cache_service.set_active_ai_task.assert_not_awaited()


def test_recovery_send_requires_preflight_even_while_another_task_is_active(monkeypatch):
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
            websocket=SimpleNamespace(scope={}),
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
            },
        )
    )

    enqueue.assert_not_awaited()
    cutover.get_epoch.assert_awaited_once_with(authoritative=True)
    assert manager.calls == [
        ("send_personal_message", "error", "user-123", "device-123")
    ]


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
def test_authoritative_epoch_and_chat_read_overlap_before_preflight_rejection(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    metadata_started = asyncio.Event()
    reads = []

    async def get_epoch(*, authoritative):
        assert authoritative is True
        reads.append("epoch")
        await metadata_started.wait()
        return 1

    async def get_metadata(chat_id):
        assert chat_id == "chat-123"
        reads.append("metadata")
        metadata_started.set()
        return {"id": chat_id, "hashed_user_id": hash_id("user-123")}

    monkeypatch.setattr(
        message_received_handler, "ChatRecoveryCutoverController",
        lambda *_args: SimpleNamespace(get_epoch=get_epoch),
    )
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_chat_metadata=get_metadata,
        check_chat_ownership=AsyncMock(return_value=True),
    ))

    async def run():
        await asyncio.wait_for(message_received_handler.handle_message_received(
            websocket=SimpleNamespace(scope={}), manager=manager,
            cache_service=SimpleNamespace(), directus_service=directus,
            encryption_service=SimpleNamespace(), user_id="user-123",
            device_fingerprint_hash="device-123",
            payload={"chat_id": "chat-123", "message": {"message_id": "msg-123", "content": "hello"},
                     "protocol_version": 1},
        ), timeout=1)

    asyncio.run(run())
    assert reads == ["epoch", "metadata"]
    directus.chat.check_chat_ownership.assert_not_awaited()
    assert manager.calls == [("send_personal_message", "error", "user-123", "device-123")]


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
def test_chat_row_never_authorizes_send_when_epoch_read_fails(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    metadata = AsyncMock(return_value={"id": "chat-123", "hashed_user_id": hash_id("user-123")})
    ownership = AsyncMock(return_value=True)
    epoch = AsyncMock(side_effect=RuntimeError("cutover unavailable"))
    monkeypatch.setattr(
        message_received_handler, "ChatRecoveryCutoverController",
        lambda *_args: SimpleNamespace(get_epoch=epoch),
    )

    asyncio.run(message_received_handler.handle_message_received(
        websocket=SimpleNamespace(scope={}), manager=manager,
        cache_service=SimpleNamespace(),
        directus_service=SimpleNamespace(chat=SimpleNamespace(
            get_chat_metadata=metadata, check_chat_ownership=ownership,
        )),
        encryption_service=SimpleNamespace(), user_id="user-123",
        device_fingerprint_hash="device-123",
        payload={"chat_id": "chat-123", "message": {"message_id": "msg-123", "content": "hello"},
                 "protocol_version": 1, "preflight_id": "prepared-turn"},
    ))

    epoch.assert_awaited_once_with(authoritative=True)
    metadata.assert_awaited_once_with("chat-123")
    ownership.assert_not_awaited()
    assert manager.calls == [("send_personal_message", "error", "user-123", "device-123")]


@pytest.mark.parametrize("active_task,stale_queue", [
    (None, False), ("active-task-123", False), (None, True),
])
def test_team_recovery_send_skips_personal_cache_completeness_gate(monkeypatch, active_task, stale_queue):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    monkeypatch.setenv("CHAT_RECOVERY_COMMITMENT_KEY", "test-chat-recovery-commitment")

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
        get_active_ai_task=AsyncMock(return_value=active_task),
        has_queued_messages=AsyncMock(return_value=stale_queue),
        queue_message=AsyncMock(return_value=True),
        mark_sync_message_queued=AsyncMock(return_value=True),
        set_active_ai_task=AsyncMock(),
        try_claim_active_ai_task=AsyncMock(return_value=True),
        clear_active_ai_task_if_matches=AsyncMock(return_value=True),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(
                return_value={"messages_v": 4, "title_v": 1, "hashed_team_id": hash_id("team-123")}
            ),
            check_chat_ownership=AsyncMock(return_value=False),
            release_inference_outbox=AsyncMock(return_value={"status": "released"}),
            mark_queued_message_pending=AsyncMock(return_value={"status": "queued", "messages_v": 5}),
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
        encrypt_many_with_user_key=AsyncMock(side_effect=lambda contents, _: [(f"vault:v1:history-{index}", 1) for index, _ in enumerate(contents)]),
        decrypt_with_user_key=AsyncMock(side_effect=["@openmates summarize this", "Earlier owner note"]),
    )
    enqueue = AsyncMock(
        return_value={
            "inference_task_id": "task-123",
            "outbox_id": "outbox-123",
        }
    )
    fresh_project = {"project_id": "authorized-project", "team_id": "team-123"}
    fresh_focus = {**fresh_project, "activation_id": "authorized-activation"}
    read_fresh_focus = AsyncMock(return_value=(fresh_project, fresh_focus))
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
    monkeypatch.setattr(message_received_handler, "_active_project_context", read_fresh_focus)
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
            websocket=SimpleNamespace(scope={}),
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
                "current_project": {"project_id": "untrusted-project"},
                "active_project_focus": {"project_id": "untrusted-project"},
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

    if active_task or stale_queue:
        assert ("dispatch_skill", "ai", "ask", "team-chat-123") not in manager.calls
        cache_service.queue_message.assert_awaited_once()
        assert cache_service.queue_message.await_args.kwargs["expected_active_task_id"] == active_task
        directus_service.chat.mark_queued_message_pending.assert_awaited_once()
        assert directus_service.chat.mark_queued_message_pending.await_args.kwargs["recovery_task_id"] == "task-123"
        assert any(call[1] == "message_queued" for call in manager.calls if call[0] == "send_personal_message")
        queued = next(message for message in manager.messages if message["type"] == "message_queued")
        # The queued row's committed sync revision is the next follow-up's expected version.
        assert queued["payload"]["messages_v"] == 5
        status = next(message for message in manager.broadcasts if message["type"] == "queued_message_status")
        assert status["payload"]["messages_v"] == 5
        directus_service.chat.release_inference_outbox.assert_not_awaited()
    else:
        assert ("dispatch_skill", "ai", "ask", "team-chat-123") in manager.calls
    assert not any(call[1] == "request_chat_history" for call in manager.calls if call[0] == "send_personal_message")
    enqueue.assert_awaited_once()
    committed_request = enqueue.await_args.kwargs["inference_request"]
    assert committed_request["current_project"] is None
    assert committed_request["active_project_focus"] is None
    read_fresh_focus.assert_awaited_once_with(
        directus_service=directus_service, cache_service=cache_service,
        user_id="user-123", chat_id="team-chat-123",
    )
    if not active_task and not stale_queue:
        assert recovery_calls[0][0] == "mark_outbox_dispatched"
        cache_service.try_claim_active_ai_task.assert_awaited_once_with("team-chat-123", "task-123")
        assert manager.request_payload["current_project"] == fresh_project
        assert manager.request_payload["active_project_focus"] == fresh_focus
    cache_service.set_active_ai_task.assert_not_awaited()
    directus_service.chat.check_chat_ownership.assert_not_awaited()


def test_recovery_send_marks_enqueue_failed_when_dispatch_returns_no_task(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    manager = FakeManager()
    cutover = SimpleNamespace(get_epoch=AsyncMock(return_value=1))
    preference_started = asyncio.Event()
    release_preferences = asyncio.Event()

    async def delayed_preferences(*_args):
        preference_started.set()
        await release_preferences.wait()
        return {"language": "de"}

    async def enqueue_after_preference_start(**_kwargs):
        # The preference RPC is deliberately held open until enqueue starts.
        await asyncio.wait_for(preference_started.wait(), timeout=1)
        release_preferences.set()
        return {
            "inference_task_id": "task-123", "outbox_id": "outbox-123",
            "committed_messages_v": 2,
        }
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
        try_claim_active_ai_task=AsyncMock(return_value=True),
        clear_active_ai_task_if_matches=AsyncMock(return_value=True),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value={
                "id": "chat-123", "hashed_user_id": hash_id("user-123"),
                "chat_visibility": None, "messages_v": 1, "title_v": 1,
            }),
            check_chat_ownership=AsyncMock(return_value=True),
            release_inference_outbox=AsyncMock(return_value={"status": "released"}),
        ),
        get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(side_effect=delayed_preferences),
    )
    encryption_service = SimpleNamespace(
        encrypt_with_user_key=AsyncMock(return_value=("encrypted-current", 1)),
        decrypt_with_user_key=AsyncMock(return_value="retry me"),
    )
    enqueue = AsyncMock(side_effect=enqueue_after_preference_start)
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
        asyncio.wait_for(message_received_handler.handle_message_received(
            websocket=SimpleNamespace(scope={}),
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
        ), timeout=3)
    )

    assert ("dispatch_skill", "ai", "ask", "chat-123") in manager.calls
    assert preference_started.is_set()
    assert manager.request_payload["user_preferences"]["language"] == "de"
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


@pytest.mark.parametrize("guard_override", [
    {"protocol_epoch": 0}, {"is_incognito": True}, {"is_team_chat": True},
    {"metadata": None},
    {"metadata": {"id": "chat-123", "hashed_user_id": hash_id("user-123"),
                  "chat_visibility": None, "messages_v": 2}},
    {"metadata": {"id": "chat-123", "hashed_user_id": hash_id("user-123"),
                  "chat_visibility": None, "messages_v": 1, "hashed_team_id": hash_id("team-123")}},
    {"metadata": {"id": "chat-123", "hashed_user_id": hash_id("user-123"),
                  "chat_visibility": None, "messages_v": 1, "parent_id": "source-chat"}},
    {"payload": {"preflight_id": "p", "message_history": [{"role": "user"}]}},
    {"payload": {"preflight_id": "p", "encrypted_embeds": [{}]}},
    {"payload": {"preflight_id": "p", "current_project": {"project_id": "p"}}},
    {"payload": {"preflight_id": "p", "queue_mode": "steer"}},
])
def test_first_personal_turn_prefetch_requires_authoritative_ordinary_turn(guard_override):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    inputs = {
        "payload": {"preflight_id": "p"},
        "message": {"role": "user"},
        "metadata": {"id": "chat-123", "hashed_user_id": hash_id("user-123"),
                     "chat_visibility": None, "messages_v": 1},
        "chat_id": "chat-123", "user_id": "user-123", "protocol_epoch": 1,
        "is_incognito": False, "is_team_chat": False,
    }
    assert message_received_handler._can_prefetch_first_personal_turn(**inputs)
    inputs.update(guard_override)
    assert not message_received_handler._can_prefetch_first_personal_turn(**inputs)


def test_first_turn_prefetch_is_cancelled_when_enqueue_rejects(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def held_preference_read(*_args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def rejected_enqueue(**_kwargs):
        await asyncio.wait_for(started.wait(), timeout=1)
        raise message_received_handler.ChatRecoveryProtocolError(409, "preflight_conflict")

    manager = FakeManager()
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_chat_metadata=AsyncMock(return_value={
            "id": "chat-123", "hashed_user_id": hash_id("user-123"),
            "chat_visibility": None, "messages_v": 1,
        }),
        check_chat_ownership=AsyncMock(return_value=True),
    ))
    monkeypatch.setattr(message_received_handler, "ChatRecoveryCutoverController",
                        lambda *_args: SimpleNamespace(get_epoch=AsyncMock(return_value=1)))
    monkeypatch.setattr(message_received_handler, "_read_ai_preference_fields", held_preference_read)
    monkeypatch.setattr(message_received_handler, "enqueue_chat_turn", rejected_enqueue)

    asyncio.run(asyncio.wait_for(message_received_handler.handle_message_received(
        websocket=FakeWebSocket(), manager=manager, cache_service=SimpleNamespace(),
        directus_service=directus, encryption_service=SimpleNamespace(),
        user_id="user-123", device_fingerprint_hash="device-123",
        payload={
            "chat_id": "chat-123", "protocol_version": 1, "preflight_id": "p",
            "message": {"message_id": "msg-123", "role": "user", "content": "hello",
                        "created_at": 1_700_000_000},
        },
    ), timeout=3))
    assert started.is_set() and cancelled.is_set()
    assert manager.calls == [("send_personal_message", "error", "user-123", "device-123")]


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
        try_claim_active_ai_task=AsyncMock(return_value=True),
        clear_active_ai_task_if_matches=AsyncMock(return_value=True),
        lease_queued_message_prefix=AsyncMock(return_value=None),
        complete_active_ai_task_if_queue_empty=AsyncMock(return_value=1),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(),
            check_chat_ownership=AsyncMock(),
            release_inference_outbox=AsyncMock(return_value={"status": "released"}),
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
            websocket=SimpleNamespace(scope={}),
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
        try_claim_active_ai_task=AsyncMock(return_value=True),
        clear_active_ai_task_if_matches=AsyncMock(return_value=True),
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
            websocket=SimpleNamespace(scope={}),
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
            return {"task_id": request_payload["legacy_cutover_task_id"]}

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
        try_claim_active_ai_task=AsyncMock(return_value=True),
        clear_active_ai_task_if_matches=AsyncMock(return_value=True),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value={"messages_v": 2, "title_v": 1}),
            check_chat_ownership=AsyncMock(return_value=True),
            get_message_count_for_chat=AsyncMock(return_value=2),
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
            websocket=SimpleNamespace(scope={}),
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


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("projected,fallback_epoch,atomic", [(True, 1, False), (True, 1, True), (False, 1, False), (False, 0, False)])
async def test_first_personal_enqueue_projection_skips_duplicate_reads_or_falls_back(
    monkeypatch, projected, fallback_epoch, atomic,
):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    user_id, chat_id, turn_id, preflight_id, message_id = (
        "user-123", "chat-123", "turn-123", "preflight-123", "message-123",
    )
    projection = {
        "id": chat_id, "hashed_user_id": hash_id(user_id), "hashed_team_id": None,
        "chat_visibility": None, "participant_user_hashes": None,
        "participant_key_envelopes": None, "messages_v": 1, "title_v": 0,
        "encrypted_title": "title-ciphertext", "encrypted_chat_key": "wrapped-key-1",
        "is_shared": False, "parent_id": None,
        "is_sub_chat": False, "budget_limit": None, "budget_spent": 0,
    }
    enqueue_result = {"preflight_id": preflight_id, "state": "ENQUEUED", "committed_messages_v": 1}
    if projected:
        enqueue_result.update(admission_protocol_epoch=1, admission_sends_paused=False,
                              admission_chat_projection=projection)
    enqueue = AsyncMock(return_value=enqueue_result)
    fresh_read = AsyncMock(side_effect=RuntimeError("fresh fallback reached"))
    owner_check = AsyncMock(side_effect=RuntimeError("ownership stage reached"))
    epoch = AsyncMock(return_value=fallback_epoch)
    monkeypatch.setattr(handler, "enqueue_chat_turn", enqueue)
    monkeypatch.setattr(handler, "ChatRecoveryCutoverController",
                        lambda *_: SimpleNamespace(get_epoch=epoch))
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_chat_metadata=fresh_read, check_chat_ownership=owner_check,
    ))
    message = {"message_id": message_id, "role": "user", "content": "hello", "created_at": 1}
    payload = {"chat_id": chat_id, "turn_id": turn_id, "protocol_version": 1,
               "preflight_id": preflight_id, "encrypted_chat_key": "wrapped-key-1", "message": message}
    await handler.handle_message_received(
        websocket=FakeWebSocket(), manager=FakeManager(), cache_service=SimpleNamespace(),
        directus_service=directus, encryption_service=SimpleNamespace(),
        user_id=user_id, device_fingerprint_hash="device-123", payload=payload,
        first_personal_admission={"chat_id": chat_id, "turn_id": turn_id,
                                  "message_id": message_id, "preflight_id": preflight_id,
                                  "wrapped_chat_key": "wrapped-key-1",
                                  **({"enqueue_result": enqueue_result} if atomic else {})},
    )
    if atomic:
        enqueue.assert_not_awaited()
    else:
        enqueue.assert_awaited_once()
        assert enqueue.await_args.kwargs["include_first_personal_projection"] is True
        assert enqueue.await_args.kwargs["expected_wrapped_chat_key"] == "wrapped-key-1"
    assert fresh_read.await_count == (0 if projected else 1)
    assert epoch.await_count == (0 if projected else 1)
    assert owner_check.await_count == (1 if projected else 0)
    if projected:
        assert owner_check.await_args.kwargs["authoritative_metadata"] == projection


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.persistence.client-encrypted
@pytest.mark.asyncio
@pytest.mark.parametrize("atomic,content,expected_content,history_reads", [
    (True, "hello first turn", "hello first turn", 0),
    (True, "hello\u200b first turn", "hello first turn", 0),
    (True, '```json\n{"type":"image","embed_id":"embed-123"}\n```',
     '```json\n{"type":"image","embed_id":"embed-123"}\n```', 1),
    (False, "hello first turn", "hello first turn", 1),
])
async def test_atomic_first_personal_plain_history_reuses_saved_row(
    monkeypatch, atomic, content, expected_content, history_reads,
):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    user_id, chat_id, turn_id, preflight_id, message_id = (
        "user-123", "chat-123", "turn-123", "preflight-123", "message-123",
    )
    projection = {
        "id": chat_id, "hashed_user_id": hash_id(user_id), "hashed_team_id": None,
        "chat_visibility": None, "participant_user_hashes": None,
        "participant_key_envelopes": None, "messages_v": 1, "title_v": 0,
        "encrypted_title": "title-ciphertext", "encrypted_chat_key": "wrapped-key-1",
        "is_shared": False, "parent_id": None, "is_sub_chat": False,
        "budget_limit": None, "budget_spent": 0,
    }
    enqueue_result = {
        "preflight_id": preflight_id, "state": "ENQUEUED", "committed_messages_v": 1,
        "admission_protocol_epoch": 1, "admission_sends_paused": False,
        "admission_chat_projection": projection,
        "inference_task_id": "task-123", "outbox_id": "outbox-123",
    }
    cached_row = json.dumps({
        "id": message_id, "chat_id": chat_id, "role": "user",
        "sender_name": "user", "encrypted_content": "encrypted-current",
        "created_at": 1_700_000_000,
    })
    cache = SimpleNamespace(
        get=AsyncMock(return_value=None),
        set=AsyncMock(return_value=True),
        get_user_vault_key_id=AsyncMock(return_value="vault-key-123"),
        save_chat_message_and_update_versions=AsyncMock(return_value={
            "messages_v": 1, "last_edited_overall_timestamp": 1_700_000_000,
        }),
        increment_and_tombstone_user_draft=AsyncMock(return_value=1),
        get_ai_messages_history=AsyncMock(return_value=[cached_row]),
        get_user_by_id=AsyncMock(return_value={"language": "en"}),
        get_active_ai_task=AsyncMock(return_value=None),
        has_queued_messages=AsyncMock(return_value=False),
        try_claim_active_ai_task=AsyncMock(return_value=True),
        update_user=AsyncMock(),
    )
    directus = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(),
            check_chat_ownership=AsyncMock(return_value=True),
            release_inference_outbox=AsyncMock(return_value={"status": "released"}),
        ),
        get_user_fields_direct=AsyncMock(return_value={}),
    )
    encryption = SimpleNamespace(
        encrypt_with_user_key=AsyncMock(return_value=("encrypted-current", 1)),
        decrypt_with_user_key=AsyncMock(return_value=expected_content),
    )
    manager = FakeManager()
    enqueue = AsyncMock(return_value=enqueue_result)
    recovery = AsyncMock(return_value={"dispatched": True})

    class FakeRecoveryService:
        def __init__(self, _directus):
            pass

        execute = recovery

    monkeypatch.setattr(handler, "enqueue_chat_turn", enqueue)
    monkeypatch.setattr(handler, "ChatRecoveryService", FakeRecoveryService)
    monkeypatch.setattr(handler, "_active_project_context", AsyncMock(return_value=(None, None)))
    monkeypatch.setitem(
        sys.modules, "backend.core.api.app.services.embed_service",
        SimpleNamespace(EmbedService=FakeEmbedService),
    )
    monkeypatch.setitem(
        sys.modules, "backend.core.api.app.services.skill_registry",
        SimpleNamespace(get_global_registry=lambda: FakeSkillRegistry(manager)),
    )
    payload = {
        "chat_id": chat_id, "turn_id": turn_id, "protocol_version": 1,
        "preflight_id": preflight_id, "encrypted_chat_key": "wrapped-key-1",
        "message": {"message_id": message_id, "role": "user",
                    "content": content, "created_at": 1_700_000_000},
    }
    await handler.handle_message_received(
        websocket=FakeWebSocket(), manager=manager, cache_service=cache,
        directus_service=directus, encryption_service=encryption,
        user_id=user_id, device_fingerprint_hash="device-123", payload=payload,
        first_personal_admission={
            "chat_id": chat_id, "turn_id": turn_id, "message_id": message_id,
            "preflight_id": preflight_id, "wrapped_chat_key": "wrapped-key-1",
            **({"enqueue_result": enqueue_result} if atomic else {}),
        },
    )

    assert ("dispatch_skill", "ai", "ask", chat_id) in manager.calls
    assert cache.get_ai_messages_history.await_count == history_reads
    assert encryption.decrypt_with_user_key.await_count == history_reads
    assert encryption.encrypt_with_user_key.await_args.args[0] == expected_content
    assert cache.save_chat_message_and_update_versions.await_count == 1
    assert cache.save_chat_message_and_update_versions.await_args.kwargs["explicit_messages_v"] == 1
    assert [entry["content"] for entry in manager.request_payload["message_history"]] == [expected_content]
    assert manager.request_payload["message_history"][0][
        "native_cache_canonical_content_sha256"
    ] == handler.canonical_content_sha256(expected_content)
    if atomic:
        enqueue.assert_not_awaited()
    else:
        enqueue.assert_awaited_once()
    directus.chat.get_chat_metadata.assert_not_awaited()
    directus.chat.release_inference_outbox.assert_awaited_once()
    recovery.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.parametrize("mutation", [
    "owner", "direct", "missing", "epoch", "paused", "version",
    "missing_key", "bad_key_type", "bad_budget_type", "bad_title_type",
    "missing_required_field", "bad_subchat_type",
])
def test_first_personal_projection_fails_closed_to_fresh_read(mutation):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    user_id, chat_id, preflight_id = "user-123", "chat-123", "preflight-123"
    projection = {"id": chat_id, "hashed_user_id": hash_id(user_id),
                  "hashed_team_id": None, "chat_visibility": None,
                  "participant_user_hashes": None, "participant_key_envelopes": None,
                  "messages_v": 1, "title_v": 0, "encrypted_title": "title-ciphertext",
                  "encrypted_chat_key": "wrapped-key-1", "is_shared": False, "parent_id": None, "is_sub_chat": False,
                  "budget_limit": None, "budget_spent": 0}
    result = {"preflight_id": preflight_id, "state": "ENQUEUED", "committed_messages_v": 1,
              "admission_protocol_epoch": 1,
              "admission_sends_paused": False, "admission_chat_projection": projection}
    if mutation == "owner":
        projection["hashed_user_id"] = "wrong"
    elif mutation == "direct":
        projection["chat_visibility"] = "direct"
    elif mutation == "missing":
        del result["admission_chat_projection"]
    elif mutation == "epoch":
        result["admission_protocol_epoch"] = 0
    elif mutation == "paused":
        result["admission_sends_paused"] = True
    elif mutation == "version":
        projection["messages_v"] = 2
    elif mutation == "missing_key":
        del projection["encrypted_chat_key"]
    elif mutation == "bad_key_type":
        projection["encrypted_chat_key"] = 1
    elif mutation == "bad_budget_type":
        projection["budget_spent"] = "0"
    elif mutation == "bad_title_type":
        projection["title_v"] = "0"
    elif mutation == "missing_required_field":
        del projection["parent_id"]
    elif mutation == "bad_subchat_type":
        projection["is_sub_chat"] = 0
    assert handler._authorized_first_personal_projection(
        result, chat_id=chat_id, user_id=user_id, preflight_id=preflight_id,
    ) is None


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_first_personal_enqueue_rejects_wrong_locked_wrapper_before_processing(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    user_id, chat_id, turn_id, preflight_id, message_id = (
        "user-123", "chat-123", "turn-123", "preflight-123", "message-123",
    )
    enqueue = AsyncMock(side_effect=handler.ChatRecoveryProtocolError(409, "immutable_chat_key_mismatch"))
    fresh_read = AsyncMock()
    owner_check = AsyncMock()
    monkeypatch.setattr(handler, "enqueue_chat_turn", enqueue)
    manager = FakeManager()
    await handler.handle_message_received(
        websocket=FakeWebSocket(), manager=manager, cache_service=SimpleNamespace(),
        directus_service=SimpleNamespace(chat=SimpleNamespace(
            get_chat_metadata=fresh_read, check_chat_ownership=owner_check,
        )), encryption_service=SimpleNamespace(), user_id=user_id,
        device_fingerprint_hash="device-123",
        payload={"chat_id": chat_id, "turn_id": turn_id, "protocol_version": 1,
                 "preflight_id": preflight_id, "encrypted_chat_key": "wrapped-key-1",
                 "message": {"message_id": message_id, "role": "user", "content": "hello"}},
        first_personal_admission={"chat_id": chat_id, "turn_id": turn_id,
                                  "message_id": message_id, "preflight_id": preflight_id,
                                   "wrapped_chat_key": "wrapped-key-1"},
    )
    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["expected_wrapped_chat_key"] == "wrapped-key-1"
    fresh_read.assert_not_awaited()
    owner_check.assert_not_awaited()
    assert manager.calls == [("send_personal_message", "error", user_id, "device-123")]


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.parametrize("rows", [
    [{"task_id": "explicit", "explicit_dependency": True}],
    [{"task_id": "unknown"}],
    [{"task_id": "unknown", "explicit_dependency": 0}],
    [{"task_id": "unknown", "explicit_dependency": "false"}],
    [{"explicit_dependency": False}],
    [{"task_id": 123, "explicit_dependency": False}],
    [{"task_id": "", "explicit_dependency": False}],
    [{"task_id": "selected", "explicit_dependency": False, "selected": True}],
    [{"task_id": "private", "explicit_dependency": False, "content": "Private body"}],
    [None], "unknown", {},
])
def test_unknown_or_explicit_related_context_keeps_admission_incomplete(rows):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    assert handler._client_selection_context_required({"related_task_candidates": rows}, None)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
@pytest.mark.parametrize("field", [
    "accepted_plan_context", "project_focus_documents", "project_context_documents",
    "custom_memory_documents", "custom_rule_documents", "client_context_pending", "active_focus",
])
def test_unselected_task_discovery_cannot_hide_required_admission_context(field):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    payload = {"related_task_candidates": [{"task_id": "hint", "explicit_dependency": False}]}
    if field != "active_focus":
        payload[field] = True if field == "client_context_pending" else {"id": "required"}
    assert handler._client_selection_context_required(payload, "active" if field == "active_focus" else None)


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.contextual-compact-assembly
def test_complete_synchronous_discovery_matches_phased_empty_scope_without_changing_binding_guards():
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler
    from backend.core.api.app.services.client_context_continuation import _complete_empty_admission_context

    rows = [{"task_id": "hint", "explicit_dependency": False}]
    snapshot = {"scope_complete": False, "active_project_id": None,
                "active_project_activation_id": None, "active_focus_id": None,
                "accepted_plan_ref": None, "explicit_related_task_ids": [],
                "context_revision": "server-admission-v1"}
    phased = SimpleNamespace(admission_context=snapshot, related_task_candidates=rows)
    _complete_empty_admission_context(phased)
    synchronous_complete = not handler._client_selection_context_required({"related_task_candidates": rows}, None)
    assert phased.admission_context["scope_complete"] is synchronous_complete is True
    assert snapshot["active_project_id"] is None and snapshot["active_focus_id"] is None


@pytest.mark.parametrize("voice", [False, True])
@pytest.mark.parametrize("intent,expected_reply", [
    ("independent", None), ("status", "1 of 2 execution steps"),
    ("clarify", "Which work do you mean"),
])
def test_active_input_uses_canonical_durable_admission(monkeypatch, voice, intent, expected_reply):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    work = handler.ActiveWork(
        task_id="original", turn_id="original-message", batch_id="paused-batch",
        source_task_id="source", task_count=2, completed_count=1,
    )
    discover = AsyncMock(return_value=[work])

    async def preserve(cache, *, user_id, chat_id, work):
        assert (user_id, chat_id, work.batch_id) == ("user-123", "chat-123", "paused-batch")
        assert not any(call.args[0] == "turn:user-123:chat-123" for call in cache.set.await_args_list)
        cache.try_claim_active_ai_task.assert_awaited_once()
        return True

    classifier = AsyncMock(return_value=handler.ActiveInput(intent, work if intent == "status" else None))
    monkeypatch.setattr(handler, "paused_code_work", discover)
    monkeypatch.setattr(handler, "preserve_active_work", AsyncMock(side_effect=preserve))
    monkeypatch.setattr(handler, "decide_active_chat_input", classifier)
    result = _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1}, related_discovery=False, voice=voice, durable=True,
    )
    classifier.assert_awaited_once()
    assert classifier.await_args.kwargs["candidates"] == [work]
    assert result.manager.request_payload["message_id"] == "msg-123"
    reply = result.manager.request_payload["active_input_reply"]
    if expected_reply is None:
        assert reply is None
    else:
        assert expected_reply in reply



@pytest.mark.parametrize("intent", ["independent", "status", "status_after_replacement"])
# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work
def test_parent_followup_preserves_linked_subchats_and_uses_fresh_scoped_progress(monkeypatch, intent):
    from dataclasses import replace
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler
    from backend.shared.python_utils.active_input_authority import ACTIVE_INPUT_UNAVAILABLE

    original = handler.ActiveWork(
        task_id="linked-original-task", turn_id="linked-original-turn", linked_sub_chat=True,
        task_count=3, completed_count=1,
    )
    refreshed = replace(original, completed_count=2)
    if intent == "status_after_replacement":
        refreshed = replace(refreshed, task_id="replacement-task", turn_id="replacement-turn")
    read = AsyncMock(side_effect=[original, refreshed])
    decide = AsyncMock(return_value=handler.ActiveInput(
        "independent" if intent == "independent" else "status", None if intent == "independent" else original,
    ))
    monkeypatch.setattr(handler, "linked_sub_chat_work", read)
    monkeypatch.setattr(handler, "decide_active_chat_input", decide)
    result = _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1}, related_discovery=False, durable=True,
    )
    decide.assert_awaited_once()
    assert decide.await_args.kwargs["candidates"] == [original]
    assert read.await_count == (1 if intent == "independent" else 2)
    assert all(call.kwargs == {
        "user_id": "user-123", "user_hash": hash_id("user-123"), "chat_id": "chat-123",
    } for call in read.await_args_list)
    reply = result.manager.request_payload["active_input_reply"]
    if intent == "independent":
        assert reply is None
    elif intent == "status":
        assert reply.startswith("2 of 3 execution steps")
    else:
        assert reply == ACTIVE_INPUT_UNAVAILABLE
    result.cache.queue_message.assert_not_awaited()
    result.cache.try_claim_active_ai_task.assert_awaited_once()
    assert result.manager.request_payload["message_id"] == "msg-123"
    assert not any(str(call.args[0]).startswith(("sub_chat_pending:", "sub_chat_completion:"))
                   for call in result.cache.set.await_args_list)


@pytest.mark.parametrize("parked", [False, True])
def test_inferred_steer_queues_exact_durable_message_and_target(monkeypatch, parked):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    work = handler.ActiveWork(
        task_id="artifact-producer", turn_id="original-message", artifact=True,
        batch_id="paused-batch" if parked else None, source_task_id="source",
    )
    monkeypatch.setattr(handler, "paused_code_work", AsyncMock(return_value=[work] if parked else []))
    monkeypatch.setattr(handler, "decide_active_chat_input",
                        AsyncMock(return_value=handler.ActiveInput("steer", work)))
    result = _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1}, related_discovery=False,
        active_task_id=None if parked else work.task_id, queued=True, durable=True,
    )
    queued = result.cache.queue_message.await_args.kwargs
    assert queued["expected_active_task_id"] == (None if parked else work.task_id)
    assert queued.get("expected_paused_turn_id") == (work.turn_id if parked else None)
    member = queued["message_data"]
    assert member["queue_mode"] == "steer"
    assert member["active_input_steer_task_id"] == work.task_id
    assert member["active_input_steer_batch_id"] == work.batch_id
    assert member["message_id"] == "msg-123"
    original = result.enqueue.await_args.kwargs["inference_request"]
    assert member["recovery_inference_request"] == original
    assert not any(field in original for field in ("active_input_steer_task_id", "active_input_steer_batch_id"))
    assert member["recovery_outbox_id"] == "44444444-aaaa-4444-8444-444444444444"


@pytest.mark.parametrize("web_socket", [False, True])
@pytest.mark.parametrize("slot_state, parallel_capable", [(0, True), (1, True), (1, False)])
def test_standalone_answer_starts_only_with_its_own_negotiated_durable_slot(
    monkeypatch, slot_state, parallel_capable, web_socket,
):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    source = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    classify = AsyncMock(return_value=handler.ActiveInput("independent", standalone_answer=True))
    reserve = AsyncMock(return_value=slot_state)

    async def reserve_exact(cache, request):
        assert await cache.get_active_ai_task(request.chat_id) == source
        assert request.active_input_parallel_source == source
        assert request.active_input_parallel_source_message == "older-user-turn"
        assert request.recovery_preflight_id and request.recovery_turn_id
        assert request.current_user_content == "What does the cache flag do?"
        return slot_state

    reserve.side_effect = reserve_exact
    monkeypatch.setattr(handler, "decide_active_chat_input", classify)
    monkeypatch.setattr(handler, "reserve_independent_reply", reserve)
    started = bool(slot_state and parallel_capable)
    result = _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1}, active_task_id=source, durable=True,
        independent=started, queued=not started, native_terminal=True, newly_enqueued=True,
        parallel_capable=parallel_capable, web_socket=web_socket,
    )
    classify.assert_awaited_once()
    assert classify.await_args.kwargs["include_completed_context"] is parallel_capable
    assert reserve.await_count == int(parallel_capable)
    assert not any(call.args[0] == "turn:user-123:chat-123" for call in result.cache.set.await_args_list)
    if started:
        result.cache.queue_message.assert_not_awaited()
        assert result.manager.request_payload["active_input_parallel_source"] == source
        assert result.manager.messages[-1]["payload"]["ai_task_id"] == result.manager.request_payload["recovery_task_id"]
        assert result.manager.messages[-1]["payload"]["independent_reply"] is True
    else:
        envelope = result.cache.queue_message.await_args.kwargs["message_data"]
        assert envelope["active_input_parallel_source"] is None
        assert envelope["active_input_parallel_source_message"] is None


def test_idle_admission_skips_active_input_decision(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    classifier = AsyncMock()
    monkeypatch.setattr(handler, "decide_active_chat_input", classifier)
    _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1}, related_discovery=False, durable=True,
    )
    classifier.assert_not_awaited()



@pytest.mark.parametrize("durable,newly_enqueued,expected_slot_reads", [
    (True, True, 0),  # The canonical first-enqueue proof exempts only this exact ID.
    (True, False, 1),  # Older or replayed transaction results still check the slot.
    (False, False, 0),  # Legacy dispatch keeps its existing authority and behavior.
])
def test_independent_retry_slot_is_skipped_only_for_fresh_durable_admission(
    monkeypatch, durable, newly_enqueued, expected_slot_reads,
):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    slot = AsyncMock(return_value=False)
    monkeypatch.setattr(handler, "independent_reply_is_active", slot)
    result = _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1}, related_discovery=False,
        durable=durable, newly_enqueued=newly_enqueued,
    )
    assert slot.await_count == expected_slot_reads
    if expected_slot_reads:
        slot.assert_awaited_once_with(
            result.cache, user_id="user-123", chat_id="chat-123",
            task_id="11111111-aaaa-4111-8111-111111111111",
        )


def test_exact_durable_independent_retry_reuses_its_active_delivery(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    slot = AsyncMock(return_value=True)
    classifier = AsyncMock()
    monkeypatch.setattr(handler, "independent_reply_is_active", slot)
    monkeypatch.setattr(handler, "decide_active_chat_input", classifier)
    result = _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1},
        active_task_id="foreground", durable=True, independent_retry=True, native_terminal=True,
    )
    slot.assert_awaited_once_with(
        result.cache, user_id="user-123", chat_id="chat-123",
        task_id="11111111-aaaa-4111-8111-111111111111",
    )
    classifier.assert_not_awaited()


def test_exact_durable_resend_does_not_route_or_queue_its_own_task(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    classifier = AsyncMock()
    monkeypatch.setattr(handler, "decide_active_chat_input", classifier)
    _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1}, related_discovery=False,
        durable=True, exact_retry=True,
    )
    classifier.assert_not_awaited()


@pytest.mark.parametrize("parallel_capable", [True, False])
def test_only_negotiated_terminal_can_resolve_confirmed_stop_before_queue(monkeypatch, parallel_capable):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler
    from backend.core.api.app.routes.handlers.websocket_handlers import natural_chat_stop
    from backend.shared.python_utils.explicit_chat_stop import STOP_RUN_REQUESTED

    classify = AsyncMock(return_value=handler.ActiveInput("independent"))
    stop = AsyncMock(return_value=natural_chat_stop.StopDecision(STOP_RUN_REQUESTED))
    monkeypatch.setattr(handler, "decide_active_chat_input", classify)
    monkeypatch.setattr(natural_chat_stop, "resolve_natural_chat_stop", stop)
    result = _exercise_ordinary_dispatch(
        monkeypatch, {"messages_v": 2, "title_v": 1}, active_task_id="assistant-foreground",
        durable=True, queued=True, native_terminal=True, newly_enqueued=True,
        user_content="cancel the Safari run", parallel_capable=parallel_capable,
    )

    queued = result.cache.queue_message.await_args.kwargs["message_data"]
    if not parallel_capable:
        stop.assert_not_awaited()
        classify.assert_awaited_once()
        assert queued["active_input_reply"] is None
        return

    stop.assert_awaited_once()
    arguments = stop.await_args.kwargs
    assert arguments["newly_enqueued"] is True
    request = arguments["request"]
    assert request.current_user_content == "cancel the Safari run"
    assert request.user_id == "user-123" and request.chat_id == "chat-123"
    assert request.recovery_task_id and request.recovery_preflight_id
    classify.assert_not_awaited()
    assert queued["active_input_reply"] == STOP_RUN_REQUESTED
    assert "active_input_reply" not in queued["recovery_inference_request"]
