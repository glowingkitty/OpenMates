"""Cold workspace archive adapter contract tests.

Projects, Tasks, Plans, Workflow definitions, and Workflow runs keep their own
client-encrypted schemas and lifecycle states. This adapter decides which rows
are eligible to move cold and builds safe manifest payloads without duplicating
referenced encrypted files. Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import hashlib

from backend.core.api.app.services.cold_workspace_archive_service import (
    build_workspace_archive_manifest,
    workspace_file_references,
    workspace_resource_is_archive_eligible,
)


NOW = 40 * 86_400
OLD = 1
RECENT = NOW - 60


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
def test_completed_tasks_and_plans_use_terminal_inactive_rules() -> None:
    assert workspace_resource_is_archive_eligible(
        "task",
        {"task_id": "task-1", "status": "done", "completed_at": OLD, "queue_state": "none"},
        now_timestamp=NOW,
    )
    assert workspace_resource_is_archive_eligible(
        "plan",
        {"plan_id": "plan-1", "status": "completed", "completed_at": OLD, "continuation_state": "idle"},
        now_timestamp=NOW,
    )
    assert not workspace_resource_is_archive_eligible(
        "task",
        {"task_id": "task-active", "status": "in_progress", "updated_at": OLD},
        now_timestamp=NOW,
    )
    assert not workspace_resource_is_archive_eligible(
        "plan",
        {"plan_id": "plan-active", "status": "executing", "updated_at": OLD},
        now_timestamp=NOW,
    )


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
def test_workflow_runs_and_definitions_block_active_or_scheduled_rows() -> None:
    assert workspace_resource_is_archive_eligible(
        "workflow_run",
        {"run_id": "run-1", "status": "completed", "finished_at": OLD, "content_storage": "durable"},
        now_timestamp=NOW,
    )
    assert workspace_resource_is_archive_eligible(
        "workflow",
        {"workflow_id": "workflow-1", "status": "disabled", "enabled": False, "updated_at": OLD, "next_run_at": None},
        now_timestamp=NOW,
    )
    assert not workspace_resource_is_archive_eligible(
        "workflow_run",
        {"run_id": "run-active", "status": "running", "finished_at": None},
        now_timestamp=NOW,
    )
    assert not workspace_resource_is_archive_eligible(
        "workflow",
        {"workflow_id": "workflow-scheduled", "status": "active", "enabled": True, "updated_at": OLD, "next_run_at": NOW + 60},
        now_timestamp=NOW,
    )


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
def test_inactive_projects_are_blocked_by_sharing_pinning_and_dependencies() -> None:
    base = {"project_id": "project-1", "updated_at": OLD, "last_opened_at": OLD, "pinned": False, "is_shared": False}

    assert workspace_resource_is_archive_eligible("project", base, now_timestamp=NOW)
    assert not workspace_resource_is_archive_eligible("project", {**base, "updated_at": RECENT}, now_timestamp=NOW)
    assert not workspace_resource_is_archive_eligible("project", {**base, "pinned": True}, now_timestamp=NOW)
    assert not workspace_resource_is_archive_eligible("project", {**base, "is_shared": True}, now_timestamp=NOW)
    assert not workspace_resource_is_archive_eligible("project", base, now_timestamp=NOW, has_active_dependency=True)


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.privacy.ciphertext-boundary
def test_manifest_preserves_personal_and_team_scope_without_plaintext_metadata() -> None:
    row = {
        "project_id": "project-1",
        "hashed_user_id": "owner-hash",
        "hashed_team_id": "team-hash",
        "name": "plaintext must stay out",
        "encrypted_name": "cipher-name",
        "encrypted_description": "cipher-description",
        "slug_lookup_hash": "slug-hash",
        "updated_at": OLD,
    }

    manifest = build_workspace_archive_manifest(
        "project",
        row,
        archive_id="archive-1",
        generation=1,
        part_count=2,
        graph_checksum="checksum",
        file_references=[],
        now_timestamp=NOW,
    )

    assert manifest["resource_type"] == "project"
    assert manifest["resource_id"] == "project-1"
    assert manifest["hashed_resource_id"] == hashlib.sha256(b"project-1").hexdigest()
    assert manifest["hashed_user_id"] == "owner-hash"
    assert manifest["hashed_team_id"] == "team-hash"
    assert manifest["encrypted_listing_metadata"] == {
        "encrypted_name": "cipher-name",
        "encrypted_description": "cipher-description",
        "slug_lookup_hash": "slug-hash",
        "updated_at": OLD,
    }
    assert "name" not in manifest["encrypted_listing_metadata"]


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy
def test_workspace_file_references_are_deduped_without_binary_duplication() -> None:
    references = workspace_file_references(
        {
            "embeds": [
                {"id": "embed-1", "s3_file_keys": [{"bucket": "chatfiles", "key": "files/shared.enc"}]},
                {"id": "embed-2", "s3_file_keys": [{"logical_bucket": "chatfiles", "object_key": "files/shared.enc"}]},
            ],
            "upload_files": [
                {"id": "upload-1", "files_metadata": {"original": {"s3_key": "files/upload.enc"}}}
            ],
        }
    )

    assert references == [
        {"logical_bucket": "chatfiles", "object_key": "files/shared.enc"},
        {"logical_bucket": "chatfiles", "object_key": "files/upload.enc"},
    ]
