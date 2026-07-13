"""
Focused contracts for recovery lifecycle invalidation and retention wiring.

These tests keep deletion and revocation hooks ordered before access removal,
and verify the periodic cleanup task preserves epoch-zero deployments while
surfacing real cleanup failures to Celery.
"""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _function_source(path: str, function_name: str) -> str:
    source = (REPO_ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == function_name
    )
    return ast.get_source_segment(source, node) or ""


def _assert_call_precedes(source: str, prerequisite: str, access_removal: str) -> None:
    assert prerequisite in source
    assert access_removal in source
    assert source.index(prerequisite) < source.index(access_removal)


def test_deletion_and_revocation_hooks_precede_access_removal() -> None:
    _assert_call_precedes(
        _function_source("backend/core/api/app/routes/handlers/websocket_handlers/delete_chat_handler.py", "handle_delete_chat"),
        "invalidate_recovery_jobs_for_chat_deletion",
        "remove_chat_from_ids_versions",
    )
    _assert_call_precedes(
        _function_source("backend/core/api/app/routes/settings.py", "delete_account"),
        "invalidate_recovery_jobs_for_account_deletion",
        "app.send_task",
    )
    _assert_call_precedes(
        _function_source("backend/core/api/app/routes/settings.py", "revoke_api_key_device"),
        "invalidate_recovery_leases_for_device",
        "revoke_api_key_device(device_id)",
    )
    _assert_call_precedes(
        _function_source("backend/core/api/app/routes/settings.py", "delete_api_key"),
        "invalidate_recovery_leases_for_device",
        "delete_api_key(key_id)",
    )
    _assert_call_precedes(
        _function_source("backend/core/api/app/routes/auth_routes/auth_sessions.py", "revoke_session"),
        "invalidate_recovery_leases_for_device",
        'delete(f"session:{target_hash}")',
    )
    _assert_call_precedes(
        _function_source("backend/core/api/app/routes/auth_routes/auth_logout.py", "logout"),
        "invalidate_recovery_leases_for_device",
        "delete(cache_key)",
    )


def test_cleanup_preserves_epoch_zero_and_reraises_real_failures() -> None:
    source = _function_source(
        "backend/core/api/app/tasks/persistence_tasks.py",
        "_async_cleanup_expired_chat_recovery_jobs",
    )
    assert "exc.status_code == 404" in source
    assert 'return {"expired_jobs": 0, "expired_tombstones": 0}' in source
    assert "raise" in source


def test_periodic_cleanup_is_registered_on_persistence_queue() -> None:
    source = (REPO_ROOT / "backend/core/api/app/tasks/celery_config.py").read_text(encoding="utf-8")
    assert "'cleanup-expired-chat-recovery-jobs'" in source
    assert "'task': 'app.tasks.persistence_tasks.cleanup_expired_chat_recovery_jobs'" in source
    assert "'options': {'queue': 'persistence'}" in source


def test_legacy_worker_marks_success_and_releases_non_persistable_results() -> None:
    source = _function_source(
        "backend/apps/ai/tasks/ask_skill_task.py",
        "process_ai_skill_ask_task",
    )
    assert "legacy_completion_requires_persistence" in source
    assert "_finalize_legacy_cutover_admission" in source
    assert "legacy_completion_requires_persistence" in source

    helper_source = _function_source(
        "backend/apps/ai/tasks/ask_skill_task.py",
        "_finalize_legacy_cutover_admission",
    )
    assert '"mark_legacy_inference_completed"' in helper_source
    assert '"release_legacy_inference"' in helper_source
    assert "logger.error" in source


def test_encrypted_persistence_acknowledges_legacy_admission_after_directus_write() -> None:
    source = _function_source(
        "backend/core/api/app/tasks/persistence_tasks.py",
        "_async_persist_ai_response_to_directus",
    )
    assert "acknowledge_legacy_persistence" in source
    assert source.index("create_message_in_directus") < source.rindex(
        "acknowledge_legacy_persistence"
    )


def test_epoch_zero_admission_identity_chain_and_acknowledgment_retry_are_wired() -> None:
    ask_skill_source = (
        REPO_ROOT / "backend/apps/ai/skills/ask_skill.py"
    ).read_text(encoding="utf-8")
    stream_source = _function_source(
        "backend/apps/ai/tasks/stream_consumer.py",
        "_create_redis_payload",
    )
    persistence_source = _function_source(
        "backend/core/api/app/tasks/persistence_tasks.py",
        "_async_persist_ai_response_to_directus",
    )
    persistence_wrapper_source = _function_source(
        "backend/core/api/app/tasks/persistence_tasks.py",
        "persist_ai_response_to_directus",
    )

    assert "task_id=request.recovery_task_id or request.legacy_cutover_task_id" in ask_skill_source
    assert '"message_id": task_id' in stream_source
    assert '"acknowledge_legacy_persistence"' in persistence_source
    assert "self.retry" in persistence_wrapper_source


def test_final_chunk_orders_recovery_discovery_before_completion_frames() -> None:
    source = _function_source(
        "backend/core/api/app/routes/websockets.py",
        "listen_for_ai_chat_streams",
    )
    ai_chunk_branch = source[source.index('elif event_type == "ai_message_chunk"'):]
    active_branch = source[
        source.index("if chat_id_from_payload == active_chat_on_device:", source.index('elif event_type == "ai_message_chunk"')):
        source.index('message={"type": "ai_background_response_completed", "payload": background_completion_payload}')
    ]
    background_branch = ai_chunk_branch[
        ai_chunk_branch.index("# Chat is not active on this device."):
        ai_chunk_branch.index('message={"type": "ai_typing_ended", "payload": typing_ended_payload}')
    ]

    assert 'redis_payload.get("is_final_chunk", False)' in ai_chunk_branch
    assert 'redis_payload.get("recovery_protocol_version") == 1' in ai_chunk_branch
    assert 'redis_payload.get("recovery_provisional") is False' in ai_chunk_branch
    assert "send_available_recovery_jobs" in active_branch
    assert "asyncio.create_task(\n                                    send_available_recovery_jobs" not in active_branch
    assert active_branch.index("send_available_recovery_jobs") < active_branch.index(
        'message={"type": "ai_message_update", "payload": redis_payload}'
    )
    assert "send_available_recovery_jobs" in background_branch
    assert background_branch.index("send_available_recovery_jobs") < background_branch.index(
        'message={"type": "ai_background_response_completed", "payload": background_completion_payload}'
    )
