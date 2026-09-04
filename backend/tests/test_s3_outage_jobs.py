"""Storage outage contracts for destructive background jobs.

Archive and deletion tasks must explicitly probe storage before destructive
work, preserve authoritative database state on outage, and surface failures to
their bounded Celery retry path. Contract: architecture.storage-resilience.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _async_function_source(relative_path: str, function_name: str) -> str:
    source = (REPOSITORY_ROOT / relative_path).read_text()
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name
    )
    return ast.get_source_segment(source, function) or ""


# contract-test: direct surface=rest_api assertions=storage-resilience.jobs.preserve-and-retry
def test_usage_archive_probes_storage_and_retries_outages() -> None:
    source = _async_function_source(
        "backend/core/api/app/tasks/usage_archive_tasks.py",
        "archive_old_usage_entries",
    )

    assert "initialize_task_storage" in source
    assert "require_storage_available" in source
    assert "self.retry" in source

    service_source = _async_function_source(
        "backend/core/api/app/services/usage_archive_service.py",
        "archive_user_month_usage",
    )
    assert "is_storage_unavailable_error" in service_source


# contract-test: direct surface=rest_api assertions=storage-resilience.jobs.preserve-and-retry
def test_issue_cleanup_does_not_swallow_storage_deletion_failures() -> None:
    source = _async_function_source(
        "backend/core/api/app/tasks/auto_delete_tasks.py",
        "_delete_issue_s3_files",
    )

    assert "require_storage_available" in source
    assert "except" not in source
    assert source.index("if yaml_key_enc or screenshot_key_enc") < source.index("require_storage_available")


# contract-test: direct surface=rest_api assertions=storage-resilience.jobs.preserve-and-retry
def test_storage_billing_does_not_reset_state_after_failed_deletion() -> None:
    source = _async_function_source(
        "backend/core/api/app/tasks/storage_billing_tasks.py",
        "_handle_billing_failure",
    )

    assert "require_storage_available" in source
    assert "except Exception as del_err" not in source
    assert source.index("delete_all_upload_files_for_user") < source.index("storage_billing_failures': 0")

    run_source = _async_function_source(
        "backend/core/api/app/tasks/storage_billing_tasks.py",
        "_async_charge_storage_fees",
    )
    assert "retry_storage_deletion" in run_source
    assert "raise fresult" not in run_source

    deletion_source = _async_function_source(
        "backend/core/api/app/services/directus/embed_methods.py",
        "delete_all_upload_files_for_user",
    )
    assert "_persist_upload_tombstones" in deletion_source
    assert deletion_source.index("_persist_upload_tombstones") < deletion_source.index("bulk_delete_items")
