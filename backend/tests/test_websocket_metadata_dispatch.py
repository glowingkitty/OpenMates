"""
Regression coverage for metadata sync dispatch in the WebSocket endpoint.

Cold accounts can have hundreds of older chats to sync after the initial
phased sync. That metadata response is useful but not latency-sensitive.
The receive loop must remain free to process chat-turn preflight messages,
otherwise a send can time out before its durable ACK is emitted.
"""

import importlib
import asyncio
import hashlib
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest


def _stub_module(monkeypatch, module_name, **attributes):
    module = ModuleType(module_name)
    for name, value in attributes.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, module_name, module)


def _load_websockets_module(_monkeypatch):
    # Exercise the actual listener and its imports. Individual test transports
    # are injected below; unrelated handler-module stubs hid real routing drift.
    return importlib.import_module("backend.core.api.app.routes.websockets")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "extra_status"),
    [
        ("queued", {}),
        ("ready", {"generated_asset_id": "asset-1", "duration_seconds": 1.2}),
        ("error", {"error": "Speech is temporarily unavailable.", "retryable": True}),
    ],
)
# contract-test: supporting surface=gui.web assertions=assistant-speech.access.first-party-owner-scoped,assistant-speech.failure.nonblocking-visible-resumable
async def test_assistant_speech_status_listener_routes_safe_updates_only_to_owner_active_chat(
    monkeypatch,
    status,
    extra_status,
):
    websockets = _load_websockets_module(monkeypatch)
    owner_id = "owner-1"
    owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()
    sent = []

    class Cache:
        @property
        def client(self):
            async def connected_client():
                return object()

            return connected_client()

        async def subscribe_to_channel(self, channel):
            assert channel == "chat_stream::*"
            yield {
                "channel": "chat_stream::chat-1",
                "data": {
                    "type": "assistant_speech_status",
                    "chat_id": "chat-1",
                    "user_id_hash": owner_hash,
                    "message_id": "message-1",
                    "payload": {
                        "segment_id": "segment-1",
                        "status": status,
                        "sequence": 0,
                        "speakable_text": "must not leave the worker",
                        **extra_status,
                    },
                },
            }

    class Manager:
        active_connections = {
            owner_id: {"owner-active": object(), "owner-other-chat": object()},
            "other-user": {"other-active": object()},
        }

        def get_connections_for_user(self, user_id):
            return self.active_connections.get(user_id, {})

        def get_active_chat(self, _user_id, device_hash):
            return {"owner-active": "chat-1", "owner-other-chat": "chat-2", "other-active": "chat-1"}.get(device_hash)

        async def send_personal_message(self, message, user_id, device_fingerprint_hash):
            sent.append((message, user_id, device_fingerprint_hash))

    monkeypatch.setattr(websockets, "manager", Manager())
    await websockets.listen_for_ai_chat_streams(SimpleNamespace(state=SimpleNamespace(cache_service=Cache())))

    assert sent == [
        (
            {
                "type": "assistant_speech_status",
                "payload": {
                    "chat_id": "chat-1",
                    "message_id": "message-1",
                    "segment_id": "segment-1",
                    "status": status,
                    "sequence": 0,
                    **extra_status,
                },
            },
            owner_id,
            "owner-active",
        ),
    ]


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=assistant-speech.access.first-party-owner-scoped,assistant-speech.acknowledgement.deterministic-free
async def test_assistant_speech_acknowledgement_routes_only_safe_static_metadata_to_owner(monkeypatch):
    websockets = _load_websockets_module(monkeypatch)
    owner_id = "owner-1"
    owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()
    sent = []

    class Cache:
        @property
        def client(self):
            async def connected_client():
                return object()

            return connected_client()

        async def subscribe_to_channel(self, channel):
            assert channel == "chat_stream::*"
            yield {
                "channel": "chat_stream::chat-1",
                "data": {
                    "type": "assistant_speech_acknowledgement",
                    "chat_id": "chat-1",
                    "user_id_hash": owner_hash,
                    "message_id": "message-1",
                    "payload": {
                        "clip_id": "hiro-en-US-general-1",
                        "audio_url": "/audio/assistant-acknowledgements/hiro/en-US/general-1.mp3",
                        "text": "must not leave the server",
                        "provider_voice_id": "must-not-leak",
                    },
                },
            }

    class Manager:
        active_connections = {
            owner_id: {"owner-active": object(), "owner-other-chat": object()},
            "other-user": {"other-active": object()},
        }

        def get_connections_for_user(self, user_id):
            return self.active_connections.get(user_id, {})

        def get_active_chat(self, _user_id, device_hash):
            return {"owner-active": "chat-1", "owner-other-chat": "chat-2", "other-active": "chat-1"}.get(device_hash)

        async def send_personal_message(self, message, user_id, device_fingerprint_hash):
            sent.append((message, user_id, device_fingerprint_hash))

    monkeypatch.setattr(websockets, "manager", Manager())
    await websockets.listen_for_ai_chat_streams(SimpleNamespace(state=SimpleNamespace(cache_service=Cache())))

    assert sent == [
        (
            {
                "type": "assistant_speech_acknowledgement",
                "payload": {
                    "chat_id": "chat-1",
                    "message_id": "message-1",
                    "clip_id": "hiro-en-US-general-1",
                    "audio_url": "/audio/assistant-acknowledgements/hiro/en-US/general-1.mp3",
                },
            },
            owner_id,
            "owner-active",
        ),
    ]


# contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases,sync.phase2.metadata-only
def test_sync_metadata_chats_is_scheduled_without_awaiting(monkeypatch):
    websockets = _load_websockets_module(monkeypatch)
    created_coroutines = []
    handler_awaited = False

    async def fake_handle_sync_metadata_chats(**kwargs):
        nonlocal handler_awaited
        handler_awaited = True

    def fake_create_task(coroutine):
        created_coroutines.append(coroutine)
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setitem(
        websockets._schedule_sync_metadata_chats_background.__globals__,
        "handle_sync_metadata_chats",
        fake_handle_sync_metadata_chats,
    )
    monkeypatch.setattr(websockets.asyncio, "create_task", fake_create_task)

    task = websockets._schedule_sync_metadata_chats_background(
        websocket=object(),
        manager=object(),
        cache_service=object(),
        directus_service=object(),
        encryption_service=object(),
        user_id="user-123",
        device_fingerprint_hash="device-123",
        payload={"existing_chat_ids": []},
        user_otel_attrs={"is_admin": False, "debug_opted_in": False},
    )

    assert task.done() is False
    assert len(created_coroutines) == 1
    assert handler_awaited is False


# contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases,assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.parametrize("embed_type,status,delivered", [
    ("app_skill_use", "finished", True),
    ("app_skill_use", "error", True),
    ("app_skill_use", "cancelled", False),
    ("application", "error", False),
])
@pytest.mark.asyncio
async def test_pending_embed_replay_is_capped_per_connection(monkeypatch, embed_type, status, delivered):
    websockets = _load_websockets_module(monkeypatch)
    sent = []

    async def no_sleep(_seconds):
        return None

    class RedisClient:
        async def get(self, key):
            embed_id = key.removeprefix("embed:")
            return json.dumps(
                {
                    "status": status,
                    "type": embed_type,
                    "vault_key_id": "vault-1",
                    "encrypted_content": f"ciphertext-{embed_id}",
                    "chat_id": "chat-1",
                    "message_id": "message-1",
                }
            )

    class Cache:
        async def get_pending_embed_ids(self, _user_id):
            return [f"embed-{index}" for index in range(5)]

        @property
        def client(self):
            async def connected_client():
                return RedisClient()

            return connected_client()

        async def remove_pending_embed(self, *_args):
            raise AssertionError("fresh pending embeds must not be removed by capped replay")

    class Encryption:
        async def decrypt_with_user_key(self, encrypted_content, _vault_key_id):
            return f"plaintext for {encrypted_content}"

    class Manager:
        async def send_personal_message(self, message, user_id, device_fingerprint_hash):
            sent.append((message, user_id, device_fingerprint_hash))

    monkeypatch.setattr(websockets.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(websockets, "MAX_PENDING_EMBED_REPLAY_PER_CONNECTION", 2)

    await websockets._deliver_pending_embeds(
        Cache(),
        Encryption(),
        Manager(),
        "owner-1",
        hashlib.sha256(b"owner-1").hexdigest(),
        "device-1",
    )

    assert [event[0]["payload"]["embed_id"] for event in sent] == (["embed-0", "embed-1"] if delivered else [])
    assert all(event[0]["payload"]["status"] == status for event in sent)
    assert all(event[0]["type"] == "send_embed_data" for event in sent)


# contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases,sync.phase2.metadata-only
def test_phased_sync_is_scheduled_without_awaiting(monkeypatch):
    websockets = _load_websockets_module(monkeypatch)
    created_coroutines = []
    handler_awaited = False

    async def fake_handle_phased_sync_request(**kwargs):
        nonlocal handler_awaited
        handler_awaited = True

    def fake_create_task(coroutine):
        created_coroutines.append(coroutine)
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setitem(
        websockets._schedule_phased_sync_background.__globals__,
        "handle_phased_sync_request",
        fake_handle_phased_sync_request,
    )
    monkeypatch.setattr(websockets.asyncio, "create_task", fake_create_task)

    task = websockets._schedule_phased_sync_background(
        websocket=object(),
        manager=object(),
        cache_service=object(),
        directus_service=object(),
        encryption_service=object(),
        user_id="user-123",
        device_fingerprint_hash="device-123",
        payload={"phase": "all"},
        user_otel_attrs={"is_admin": False, "debug_opted_in": False},
    )

    assert task.done() is False
    assert len(created_coroutines) == 1
    assert handler_awaited is False


# contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
async def test_phased_sync_context_switch_cancels_queue_and_runs_replacement(monkeypatch):
    websockets = _load_websockets_module(monkeypatch)
    old_started = asyncio.Event()
    replacement_completed = asyncio.Event()

    async def fake_handle_phased_sync_request(**kwargs):
        if kwargs["payload"].get("context_epoch") == 1:
            old_started.set()
            await asyncio.Event().wait()
        replacement_completed.set()

    monkeypatch.setitem(
        websockets._schedule_phased_sync_background.__globals__,
        "handle_phased_sync_request",
        fake_handle_phased_sync_request,
    )
    common_kwargs = {
        "websocket": object(),
        "manager": object(),
        "cache_service": object(),
        "directus_service": object(),
        "encryption_service": object(),
        "user_id": "user-123",
        "device_fingerprint_hash": "device-123",
    }
    running = websockets._schedule_phased_sync_background(
        **common_kwargs,
        payload={"phase": "all", "context_epoch": 1},
    )
    queued = websockets._schedule_phased_sync_background(
        **common_kwargs,
        payload={"phase": "all", "context_epoch": 1},
        previous_task=running,
    )
    tasks = {running, queued}
    await old_started.wait()
    next_context, changed, should_schedule = websockets._cancel_superseded_phased_sync_tasks(
        tasks,
        (None, 1),
        {"team_id": "team-123", "context_epoch": 2},
    )
    cancelled_results = await asyncio.gather(*tasks, return_exceptions=True)
    replacement = websockets._schedule_phased_sync_background(
        **common_kwargs,
        payload={"phase": "all", "team_id": "team-123", "context_epoch": 2},
    )
    await replacement

    assert changed is True
    assert should_schedule is True
    assert next_context == ("team-123", 2)
    assert all(isinstance(result, asyncio.CancelledError) for result in cancelled_results)
    assert replacement_completed.is_set()


# contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
def test_same_context_phased_sync_stays_serialized(monkeypatch):
    websockets = _load_websockets_module(monkeypatch)

    class PendingTask:
        cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    pending_task = PendingTask()
    next_context, changed, should_schedule = websockets._cancel_superseded_phased_sync_tasks(
        {pending_task},
        ("team-123", 2),
        {"team_id": "team-123", "context_epoch": 2},
    )

    assert changed is False
    assert should_schedule is True
    assert next_context == ("team-123", 2)
    assert pending_task.cancelled is False


# contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
@pytest.mark.parametrize("context_epoch", [None, True, "2", -1])
def test_phased_sync_rejects_malformed_context_epoch(monkeypatch, context_epoch):
    websockets = _load_websockets_module(monkeypatch)

    with pytest.raises(ValueError, match="context_epoch must be a non-negative integer"):
        websockets._cancel_superseded_phased_sync_tasks(
            set(),
            (None, 1),
            {"team_id": "team-123", "context_epoch": context_epoch},
        )


# contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
def test_stale_phased_sync_epoch_does_not_cancel_newer_context(monkeypatch):
    websockets = _load_websockets_module(monkeypatch)

    class PendingTask:
        cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    pending_task = PendingTask()
    next_context, changed, should_schedule = websockets._cancel_superseded_phased_sync_tasks(
        {pending_task},
        ("team-123", 2),
        {"context_epoch": 1},
    )

    assert changed is False
    assert should_schedule is False
    assert next_context == ("team-123", 2)
    assert pending_task.cancelled is False


# contract-test: supporting surface=gui.web assertions=projects.files.executor-wait,projects.files.no-server-decryption-authority
@pytest.mark.asyncio
async def test_project_file_available_uses_app_directus_and_only_current_capable_device(monkeypatch):
    websockets = _load_websockets_module(monkeypatch)
    directus_service = object()
    authorization_inputs = []
    sent = []

    class Authorization:
        def __init__(self, directus, cache):
            authorization_inputs.append((directus, cache))

        async def get_active_focus(self, *, user_id, chat_id):
            assert (user_id, chat_id) == ("user-1", "chat-1")
            return {"project_id": "project-1"}

    _stub_module(
        monkeypatch,
        "backend.core.api.app.services.project_write_authorization_service",
        ProjectWriteAuthorizationService=Authorization,
    )

    class Cache:
        def __init__(self):
            async def ready():
                return self
            self.client = ready()

        async def subscribe_to_channel(self, channel):
            assert channel == "user_updates::*"
            yield {
                "channel": "user_updates::user-1",
                "data": {
                    "event_for_client": "project_file_operation_available",
                    "user_id_uuid": "user-1",
                    "payload": {
                        "operation_id": "operation-1",
                        "chat_id": "chat-1",
                        "project_id": "project-1",
                    },
                },
            }

    cache = Cache()

    class Manager:
        def get_connections_for_user(self, user_id):
            assert user_id == "user-1"
            return ["current-device", "other-device"]

        def can_execute_project_file_job(self, user_id, device, chat_id):
            return (user_id, device, chat_id) == (
                "user-1", "current-device", "chat-1"
            )

        async def send_personal_message(self, message, user_id, device):
            sent.append((message, user_id, device))

    monkeypatch.setattr(websockets, "manager", Manager())
    app = SimpleNamespace(
        state=SimpleNamespace(
            cache_service=cache,
            directus_service=directus_service,
        )
    )

    await websockets.listen_for_user_updates(app)

    assert authorization_inputs == [(directus_service, cache)]
    assert sent == [(
        {
            "type": "project_file_operation_available",
            "payload": {
                "operation_id": "operation-1",
                "chat_id": "chat-1",
                "project_id": "project-1",
            },
        },
        "user-1",
        "current-device",
    )]


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "authority"), [
    ("queued", "active"), ("ready", "active"), ("queued", "ended"),
    ("ready", "wrong_owner"), ("queued", "wrong_chat"), ("ready", "wrong_session"),
    ("queued", "unknown"), ("ready", "malformed"),
])
# contract-test: supporting surface=gui.web assertions=video-call.audio.single-owner,video-call.audio.localized-waiting,video-call.lifecycle.recovery-and-billing,assistant-speech.access.first-party-owner-scoped
async def test_call_speech_status_keeps_language_and_routes_only_live_call_session_in_background(monkeypatch, status, authority):
    import fakeredis.aioredis
    from backend.shared.python_utils.voice_call_registry import register_active_call, finalize_active_call

    websockets = _load_websockets_module(monkeypatch)
    owner_id, chat_id, session_id = "call-owner", "call-chat", "call-auth-session"
    call_id = "a" * 32 if authority != "malformed" else "invalid-call"
    owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()
    sent = []
    speech = {"segment_id": "speech-segment", "sequence": 0, "status": status,
              "voice_call_id": call_id, "language": "de", "kind": "waiting",
              "speakable_text": "PRIVATE spoken text", "private_provider_response": {"secret": "PRIVATE"}}
    if status == "ready":
        speech.update(generated_asset_id="owner-encrypted-asset", duration_seconds=1.2)

    class Cache:
        def __init__(self):
            self.redis = fakeredis.aioredis.FakeRedis()

        @property
        async def client(self):
            return self.redis

        async def subscribe_to_channel(self, channel):
            assert channel == "chat_stream::*"
            yield {"channel": f"chat_stream::{chat_id}", "data": {
                "type": "assistant_speech_status", "chat_id": chat_id,
                "user_id_hash": owner_hash, "message_id": "canonical-assistant", "payload": speech,
            }}

    class Manager:
        active_connections = {
            owner_id: {
                "call-tab-background": SimpleNamespace(scope={"voice_call_session_hash": session_id}),
                "other-session-active-chat": SimpleNamespace(scope={"voice_call_session_hash": "different-session"}),
            },
            "other-user": {"other-user-tab": SimpleNamespace(scope={"voice_call_session_hash": session_id})},
        }

        def get_connections_for_user(self, user_id):
            return self.active_connections.get(user_id, {})

        def get_active_chat(self, _user_id, device_hash):
            return "unrelated-open-chat" if device_hash == "call-tab-background" else chat_id

        async def send_personal_message(self, message, user_id, device_fingerprint_hash):
            sent.append((message, user_id, device_fingerprint_hash))

    cache = Cache()
    binding = dict(user_id="another-owner" if authority == "wrong_owner" else owner_id,
                   session_id="unconnected-session" if authority == "wrong_session" else session_id,
                   chat_id="another-chat" if authority == "wrong_chat" else chat_id, call_id=call_id)
    if authority not in {"unknown", "malformed"}:
        await register_active_call(cache, **binding)
        if authority == "ended":
            await finalize_active_call(cache, **binding)
    monkeypatch.setattr(websockets, "manager", Manager())
    await websockets.listen_for_ai_chat_streams(SimpleNamespace(state=SimpleNamespace(cache_service=cache)))
    if authority != "active":
        assert sent == []
        return
    assert len(sent) == 1 and sent[0][1:] == (owner_id, "call-tab-background")
    payload = sent[0][0]["payload"]
    assert payload["voice_call_id"] == call_id and payload["language"] == "de"
    assert payload["status"] == status and payload["kind"] == "waiting"
    assert "speakable_text" not in payload and "private_provider_response" not in payload
    if status == "ready":
        assert payload["generated_asset_id"] == "owner-encrypted-asset"
