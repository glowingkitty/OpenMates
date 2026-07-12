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
