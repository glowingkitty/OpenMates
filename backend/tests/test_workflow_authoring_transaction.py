"""Atomic workflow authoring guards and encrypted undo ledger."""

from copy import deepcopy

import pytest

from backend.core.api.app.services.workflow_service import (
    InMemoryWorkflowRepository,
    WORKFLOW_AUTHORING_MUTATION_TTL_SECONDS,
    WorkflowAuthoringConflictError,
    _hash_owner_id,
)
from backend.tests.test_workflows_models import rain_graph
from backend.tests.workflow_test_utils import workflow_service


def _create(workflow_id: str, title: str) -> dict:
    return {"type": "create", "workflow_id": workflow_id,
            "initial_version_id": f"version-{workflow_id}", "title": title,
            "graph": rain_graph()}


# contract-test: direct surface=rest_api assertions=teams.context.full-switch-local
def test_team_member_edit_keeps_creator_storage_owner_and_uses_member_vault_key() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    created = service.apply_authoring_batch(
        "alice", [{**_create("team-flow", "Shared"), "team_id": "team-a"}],
        "team-create", team_id="team-a",
    )[0]
    assert created is not None
    updated = service.apply_authoring_batch(
        "bob", [{"type": "update", "workflow_id": created.id,
                 "expected_record_version": created.version, "new_version_id": "team-v2",
                 "title": "Edited by Bob", "team_id": "team-a"}],
        "team-edit", team_id="team-a",
    )[0]
    assert updated is not None and updated.title == "Edited by Bob"
    assert repository.workflows[created.id]["owner_hash"] == _hash_owner_id("alice")
    assert repository.authoring_receipts["team-edit"]["owner_hash"] == _hash_owner_id("alice")
    assert {blob["owner_hash"] for blob in repository.encrypted_blobs.values()} == {_hash_owner_id("alice")}
    assert service.get_workflow(created.id, "bob", team_id="team-a").title == "Edited by Bob"
    with pytest.raises(KeyError):
        service.get_workflow(created.id, "bob")
    with pytest.raises(KeyError):
        service.get_workflow(created.id, "bob", team_id="team-b")


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_mixed_authoring_batch_is_idempotent_and_undoes_every_target() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    first = service.apply_authoring_batch("alice", [_create("first", "First"), _create("second", "Second")], "create-both")
    assert [item.title for item in first if item] == ["First", "Second"]
    assert len(repository.authoring_mutations["create-both"]) == 2
    assert all("First" not in str(row) for row in repository.authoring_mutations["create-both"])

    repeated = service.apply_authoring_batch("alice", [_create("first", "First"), _create("second", "Second")], "create-both")
    assert [item.current_version_id for item in repeated if item] == [item.current_version_id for item in first if item]
    assert len(repository.authoring_receipts) == 1

    results = service.apply_authoring_batch("alice", [
        {"type": "update", "workflow_id": "first", "expected_record_version": 1,
         "new_version_id": "first-updated", "title": "Changed"},
        {"type": "delete", "workflow_id": "second", "expected_record_version": 1},
        _create("third", "Third"),
    ], "mixed-edit")
    assert [item.title if item else None for item in results] == ["Changed", None, "Third"]
    assert service.get_workflow("first", "alice").version == 2
    assert repository.get_workflow("second", "alice") is None
    assert len(repository.authoring_mutations["mixed-edit"]) == 3

    undone = service.undo_authoring_batch("alice", "mixed-edit")
    assert [item.title if item else None for item in undone] == ["First", "Second", None]
    assert service.get_workflow("first", "alice").title == "First"
    assert service.get_workflow("second", "alice").title == "Second"
    assert repository.get_workflow("third", "alice") is None
    assert all(item["undone_at"] for item in repository.authoring_mutations["mixed-edit"])
    repeated_undo = service.undo_authoring_batch("alice", "mixed-edit")
    assert [item.current_version_id if item else None for item in repeated_undo] == [
        item.current_version_id if item else None for item in undone
    ]


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_one_stale_version_rejects_entire_batch_without_publishing_blobs() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    service.apply_authoring_batch("alice", [_create("first", "First"), _create("second", "Second")], "setup")
    before = deepcopy(repository.workflows)
    blob_count = len(repository.encrypted_blobs)
    with pytest.raises(WorkflowAuthoringConflictError):
        service.apply_authoring_batch("alice", [
            {"type": "update", "workflow_id": "first", "expected_record_version": 1,
             "new_version_id": "first-v2", "title": "Would change"},
            {"type": "update", "workflow_id": "second", "expected_record_version": 2,
             "new_version_id": "second-v2", "title": "Stale"},
        ], "conflict")
    assert repository.workflows == before
    assert len(repository.encrypted_blobs) == blob_count
    assert "conflict" not in repository.authoring_receipts


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_undo_conflict_keeps_every_target_and_ledger_untouched() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    service.apply_authoring_batch("alice", [_create("first", "First"), _create("second", "Second")], "setup")
    service.apply_authoring_batch("alice", [
        {"type": "update", "workflow_id": "first", "expected_record_version": 1,
         "new_version_id": "first-v2", "title": "First edit"},
        {"type": "update", "workflow_id": "second", "expected_record_version": 1,
         "new_version_id": "second-v2", "title": "Second edit"},
    ], "edit-both")
    service.apply_authoring_batch("alice", [{"type": "update", "workflow_id": "second",
        "expected_record_version": 2, "new_version_id": "second-v3", "title": "Later edit"}], "later")
    with pytest.raises(WorkflowAuthoringConflictError):
        service.undo_authoring_batch("alice", "edit-both")
    assert service.get_workflow("first", "alice").title == "First edit"
    assert service.get_workflow("second", "alice").title == "Later edit"
    assert all(item["undone_at"] is None for item in repository.authoring_mutations["edit-both"])


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
def test_authoring_snapshots_expire_after_seven_days_but_receipt_blocks_replay() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    operation = _create("first", "First")
    service.apply_authoring_batch("alice", [operation], "retained-id")
    mutation = repository.authoring_mutations["retained-id"][0]
    snapshot_ref = mutation["encrypted_after_ref"]
    created_at = mutation["created_at"]
    assert repository.encrypted_blobs[snapshot_ref]["expires_at"] >= created_at + WORKFLOW_AUTHORING_MUTATION_TTL_SECONDS
    service.cleanup_expired_temporary_workflows(now=created_at + WORKFLOW_AUTHORING_MUTATION_TTL_SECONDS - 1)
    assert snapshot_ref in repository.encrypted_blobs
    service.cleanup_expired_temporary_workflows(now=created_at + WORKFLOW_AUTHORING_MUTATION_TTL_SECONDS)
    assert snapshot_ref not in repository.encrypted_blobs
    assert "retained-id" not in repository.authoring_mutations
    assert repository.authoring_receipts["retained-id"]["outcomes"][0]["expired"] is True
    with pytest.raises(WorkflowAuthoringConflictError, match="expired"):
        service.apply_authoring_batch("alice", [operation], "retained-id")
