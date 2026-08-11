"""
Regression coverage for metadata sync dispatch in the WebSocket endpoint.

Cold accounts can have hundreds of older chats to sync after the initial
phased sync. That metadata response is useful but not latency-sensitive.
The receive loop must remain free to process chat-turn preflight messages,
otherwise a send can time out before its durable ACK is emitted.
"""

import importlib
import sys
from types import ModuleType, SimpleNamespace


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
