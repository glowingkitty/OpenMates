"""Private staging boundary for atomic workflow authoring.

WorkflowService prepares and encrypts against this overlay. Nothing becomes
visible until the Directus authoring transaction accepts the complete batch.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class StagedWorkflowRepository:
    def __init__(self, base: Any, *, owner_hash: str | None = None) -> None:
        self.base = base
        self.owner_hash = owner_hash
        self.workflows: dict[str, dict[str, Any]] = {}
        self.triggers: dict[str, dict[str, Any] | None] = {}
        self.blobs: dict[str, dict[str, Any]] = {}
        self.deleted_blob_refs: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def get_workflow(self, workflow_id: str, user_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        if workflow_id in self.workflows:
            record = self.workflows[workflow_id]
            if record.get("status") == "deleted":
                return None
            return deepcopy(record)
        return self.base.get_workflow(workflow_id, user_id, team_id)

    def get_workflow_including_deleted(self, workflow_id: str, user_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        if workflow_id in self.workflows:
            return deepcopy(self.workflows[workflow_id])
        return self.base.get_workflow_including_deleted(workflow_id, user_id, team_id)

    def save_workflow(self, record: dict[str, Any]) -> dict[str, Any]:
        from backend.shared.python_utils.encrypted_slug_metadata import validate_encrypted_slug_metadata

        validate_encrypted_slug_metadata(record, record_label="Workflow")
        self.workflows[record["id"]] = deepcopy(record)
        return deepcopy(record)

    def get_trigger_for_workflow(self, workflow_id: str, user_id: str) -> dict[str, Any] | None:
        if workflow_id in self.triggers:
            trigger = self.triggers[workflow_id]
            return deepcopy(trigger) if trigger else None
        if self.owner_hash and hasattr(self.base, "get_trigger_for_workflow_owner_hash"):
            return self.base.get_trigger_for_workflow_owner_hash(workflow_id, self.owner_hash)
        return self.base.get_trigger_for_workflow(workflow_id, user_id)

    def save_trigger(self, record: dict[str, Any]) -> dict[str, Any]:
        if self.owner_hash:
            record = {**record, "owner_hash": self.owner_hash}
        self.triggers[record["workflow_id"]] = deepcopy(record)
        return deepcopy(record)

    def delete_trigger_for_workflow(self, workflow_id: str, user_id: str) -> dict[str, Any] | None:
        from backend.core.api.app.services.workflow_service import _hash_owner_id

        return self.delete_trigger_for_workflow_owner_hash(workflow_id, _hash_owner_id(user_id))

    def delete_trigger_for_workflow_owner_hash(self, workflow_id: str, owner_hash: str) -> dict[str, Any] | None:
        if workflow_id in self.triggers:
            existing = self.triggers[workflow_id]
        else:
            # Service callers supply a user id through the ordinary path. The
            # base repository's owner-hash deletion would mutate live state.
            existing = self.base.get_trigger_for_workflow_owner_hash(workflow_id, owner_hash)
        self.triggers[workflow_id] = None
        return deepcopy(existing) if existing else None

    def save_encrypted_blob(self, blob: dict[str, Any]) -> dict[str, Any]:
        if self.owner_hash:
            blob = {**blob, "owner_hash": self.owner_hash}
        self.blobs[blob["ref"]] = deepcopy(blob)
        return deepcopy(blob)

    def create_encrypted_blob(self, blob: dict[str, Any]) -> dict[str, Any]:
        return self.save_encrypted_blob(blob)

    def create_encrypted_blobs(self, blobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for blob in blobs:
            self.save_encrypted_blob(blob)
        return deepcopy(blobs)

    def get_encrypted_blob(self, ref: str) -> dict[str, Any] | None:
        if ref in self.blobs:
            return deepcopy(self.blobs[ref])
        return self.base.get_encrypted_blob(ref)

    def delete_encrypted_blob(self, ref: str) -> None:
        # Old refs remain usable for undo and active runs. Cleanup is separate
        # from publishing a new head, and never precedes the commit.
        if ref in self.blobs:
            self.blobs.pop(ref)
        else:
            self.deleted_blob_refs.add(ref)
