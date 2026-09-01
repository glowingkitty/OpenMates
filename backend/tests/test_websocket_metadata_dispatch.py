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


async def _noop_async(*args, **kwargs):
    return None


def _install_websockets_import_stubs(monkeypatch):
    base = "backend.core.api.app.routes.handlers.websocket_handlers"
    handler_modules = {
        "title_update_handler": ["handle_update_title"],
        "draft_update_handler": ["handle_update_draft"],
        "message_received_handler": ["handle_message_received"],
        "delete_chat_handler": ["handle_delete_chat"],
        "delete_message_handler": ["handle_delete_message"],
        "message_highlight_handlers": [
            "handle_add_message_highlight",
            "handle_update_message_highlight",
            "handle_remove_message_highlight",
        ],
        "code_run_output_handlers": ["handle_upsert_code_run_output", "handle_request_code_run_output"],
        "notebook_run_output_handlers": ["handle_upsert_notebook_run_output", "handle_request_notebook_run_output"],
        "offline_sync_handler": ["handle_sync_offline_changes"],
        "get_chat_messages_handler": ["handle_get_chat_messages"],
        "delete_draft_handler": ["handle_delete_draft"],
        "delete_draft_embed_handler": ["handle_delete_draft_embed"],
        "cancel_pdf_processing_handler": ["handle_cancel_pdf_processing"],
        "chat_content_batch_handler": ["handle_chat_content_batch"],
        "cancel_ai_task_handler": ["handle_cancel_ai_task"],
        "cancel_skill_handler": ["handle_cancel_skill"],
        "focus_mode_deactivate_handler": ["handle_focus_mode_deactivate"],
        "focus_mode_rejected_handler": ["handle_focus_mode_rejected"],
        "sub_chat_confirmation_handler": ["handle_sub_chat_confirmation"],
        "sub_chat_stop_handler": ["handle_sub_chat_stop"],
        "ai_response_completed_handler": ["handle_ai_response_completed"],
        "encrypted_chat_metadata_handler": ["handle_encrypted_chat_metadata"],
        "chat_turn_preflight_handler": ["handle_chat_turn_preflight"],
        "chat_recovery_job_handlers": [
            "handle_recovery_job_claim",
            "handle_recovery_job_persist",
            "handle_recovery_job_renew",
            "send_available_recovery_jobs",
        ],
        "workflow_chat_delivery_handlers": [
            "handle_workflow_chat_delivery_ack",
            "handle_workflow_chat_delivery_claim",
            "handle_workflow_chat_delivery_persist",
            "send_available_workflow_chat_deliveries",
        ],
        "task_update_job_handlers": [
            "handle_task_update_job_claim",
            "handle_task_update_job_event_confirmed",
            "handle_task_update_job_persist",
            "send_available_task_update_jobs",
        ],
        "post_processing_metadata_handler": ["handle_post_processing_metadata"],
        "phased_sync_handler": ["handle_phased_sync_request", "handle_sync_status_request"],
        "app_settings_memories_confirmed_handler": ["handle_app_settings_memories_confirmed"],
        "connected_account_permission_confirmed_handler": ["handle_connected_account_permission_confirmed"],
        "store_app_settings_memories_handler": ["handle_store_app_settings_memories_entry"],
        "delete_app_settings_memories_handler": ["handle_delete_app_settings_memories_entry"],
        "store_embed_handler": ["handle_store_embed"],
        "store_embed_keys_handler": ["handle_store_embed_keys"],
        "store_embed_diff_handler": ["handle_store_embed_diff"],
        "delete_new_chat_suggestion_handler": ["handle_delete_new_chat_suggestion"],
        "system_message_handler": ["handle_chat_system_message_added"],
        "email_notification_settings_handler": ["handle_email_notification_settings"],
        "load_more_chats_handler": ["handle_load_more_chats"],
        "sync_metadata_chats_handler": ["handle_sync_metadata_chats"],
        "inspiration_viewed_handler": ["handle_inspiration_viewed"],
        "inspiration_received_handler": ["handle_inspiration_received"],
        "sync_inspiration_chat_handler": ["handle_sync_inspiration_chat"],
        "project_remote_access_handlers": [
            "handle_project_remote_access_complete",
            "handle_project_remote_access_disconnect",
            "handle_project_remote_access_heartbeat",
            "handle_project_remote_access_register",
        ],
        "update_chat_pinned_handler": ["handle_update_chat_pinned"],
        "key_received_handler": ["handle_key_received"],
        "chat_compression_checkpoint_handler": [
            "handle_get_compressed_chat_old_messages",
            "handle_store_chat_compression_checkpoint",
        ],
        "assistant_speech_handler": ["handle_assistant_speech_event"],
        "chat_model_preference_handler": ["handle_chat_model_preference"],
    }
    for module_name, names in handler_modules.items():
        _stub_module(monkeypatch, f"{base}.{module_name}", **{name: _noop_async for name in names})

    _stub_module(
        monkeypatch,
        f"{base}.active_chat_handler",
        AI_STREAM_SNAPSHOT_TTL_SECONDS=60,
        ai_stream_snapshot_cache_key=lambda *args, **kwargs: "snapshot-key",
        handle_set_active_chat=_noop_async,
    )
    _stub_module(monkeypatch, "backend.core.api.app.services.cache", CacheService=object)
    _stub_module(monkeypatch, "backend.core.api.app.services.directus", DirectusService=object)
    _stub_module(
        monkeypatch,
        "backend.core.api.app.services.chat_recovery_cutover",
        ChatRecoveryCutoverController=object,
    )
    _stub_module(
        monkeypatch,
        "backend.core.api.app.services.notification_event_service",
        NotificationEventService=object,
    )
    _stub_module(monkeypatch, "backend.core.api.app.utils.encryption", EncryptionService=object)
    _stub_module(monkeypatch, "backend.core.api.app.routes.connection_manager", ConnectionManager=object)
    _stub_module(monkeypatch, "backend.core.api.app.routes.auth_ws", get_current_user_ws=_noop_async)


def _load_websockets_module(monkeypatch):
    _install_websockets_import_stubs(monkeypatch)
    module_name = "backend.core.api.app.routes.websockets"
    module = sys.modules.get(module_name)
    if module is not None and (
        not hasattr(module, "_schedule_sync_metadata_chats_background")
        or not hasattr(module, "_schedule_phased_sync_background")
    ):
        sys.modules.pop(module_name, None)
        routes_package = sys.modules.get("backend.core.api.app.routes")
        if routes_package is not None and getattr(routes_package, "websockets", None) is module:
            delattr(routes_package, "websockets")
    return importlib.import_module(module_name)


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
                    **extra_status,
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
@pytest.mark.asyncio
async def test_pending_embed_replay_is_capped_per_connection(monkeypatch):
    websockets = _load_websockets_module(monkeypatch)
    sent = []

    async def no_sleep(_seconds):
        return None

    class RedisClient:
        async def get(self, key):
            embed_id = key.removeprefix("embed:")
            return json.dumps(
                {
                    "status": "finished",
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

    assert [event[0]["payload"]["embed_id"] for event in sent] == ["embed-0", "embed-1"]
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
