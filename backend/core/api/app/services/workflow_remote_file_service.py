"""Portable Workflow writes through the authorized Project source-write boundary.

Bindings are client/Workflow encrypted state. Contents and paths must never be
stored in unencrypted job metadata. External edits require explicit reconciliation.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable

import yaml

from backend.core.api.app.services.workflow_file_service import WorkflowFileService


@dataclass(frozen=True)
class WorkflowRemoteFileBinding:
    project_id: str
    source_id: str
    folder_path: str
    file_path: str | None = None
    base_hash: str | None = None
    saved_content: str | None = None
    workflow_version_id: str | None = None


class WorkflowRemoteFileService:
    def __init__(self, workflow_service: Any, execute_source_operation: Callable[..., Awaitable[dict[str, Any]]]) -> None:
        self.workflows = workflow_service
        self.execute = execute_source_operation

    async def persist(self, *, user_id: str, workflow_id: str, expected_workflow_version_id: str,
                      binding: WorkflowRemoteFileBinding, source_write_context: dict[str, Any],
                      vault_key_id: str | None = None) -> dict[str, Any]:
        """Only confirmed source-write completion means saved, never queued/proposed.

        The callback must freshly authorize Project access/write policy and use
        the existing client source-write executor. An update uses the last
        confirmed content/hash; it never reads and overwrites an external edit.
        """
        if (source_write_context.get("project_id") != binding.project_id
                or source_write_context.get("source_id") != binding.source_id
                or not source_write_context.get("chat_id")):
            raise ValueError("workflow_file_source_scope_mismatch")
        workflow = self.workflows.get_workflow(workflow_id, user_id, vault_key_id)
        if workflow.current_version_id != expected_workflow_version_id:
            return {"status": "conflict", "error": "workflow_version_changed", "binding": binding}
        folder = _relative_folder(binding.folder_path)
        stem = unicodedata.normalize("NFKC", workflow.title)
        stem = re.sub(r'[\x00-\x1f/\\<>:"|?*]', "-", stem)
        stem = re.sub(r"\.workflow\.ya?ml$", "", stem, flags=re.I)
        stem = re.sub(r"^\.+|[. ]+$", "", stem).strip().lower()
        stem = re.sub(r"\s+", "_", stem)[:100] or "workflow"
        path = binding.file_path or (f"{folder}/" if folder else "") + stem + ".workflow.yml"
        if (_relative_folder(path) != path or not path.endswith(".workflow.yml")
                or (path.rsplit("/", 1)[0] if "/" in path else "") != folder):
            raise ValueError("workflow_file_path_outside_selected_folder")
        content = yaml.safe_dump(WorkflowFileService(self.workflows).export_document(workflow).model_dump(mode="json"),
                                 sort_keys=False, allow_unicode=True)
        proposed_binding = replace(binding, file_path=path, base_hash=hashlib.sha256(content.encode()).hexdigest(),
                                   saved_content=content, workflow_version_id=expected_workflow_version_id)
        if binding.base_hash is None:
            if binding.saved_content is not None:
                raise ValueError("workflow_file_binding_incomplete")
            operation, arguments = "create_file", {"path": path, "expected_base": None, "content": content}
        else:
            if binding.saved_content is None or hashlib.sha256(binding.saved_content.encode()).hexdigest() != binding.base_hash:
                raise ValueError("workflow_file_binding_hash_mismatch")
            operation, arguments = "update_file", {"path": path, "expected_base": binding.base_hash,
                "patch": _replacement_patch(path, binding.saved_content, content)}
        try:
            # Stage the encrypted/transient binding before the adapter publishes
            # a job: a fast connected executor may settle during this await.
            result = await self.execute(operation, arguments, {**source_write_context, "_proposed_binding": proposed_binding})
        except Exception as exc:
            code = getattr(exc, "code", "workflow_file_write_failed")
            return {"status": "pending" if code in {"source_offline", "protocol_timeout"} else "failed",
                    "error": code, "binding": binding}
        status = result.get("status")
        if status != "completed":
            return {"status": "conflict" if status == "conflict" else "failed" if status == "failed" else "pending",
                    "error": result.get("error") or result.get("reason"), "binding": binding,
                    "operation_id": result.get("operation_id"), "proposed_binding": proposed_binding,
                    "workflow_version_id": expected_workflow_version_id}
        confirmed = proposed_binding
        current = self.workflows.get_workflow(workflow_id, user_id, vault_key_id)
        return {"status": "saved" if current.current_version_id == expected_workflow_version_id else "conflict",
                "error": None if current.current_version_id == expected_workflow_version_id else "workflow_version_changed",
                "binding": confirmed, "workflow_version_id": expected_workflow_version_id}


def _relative_folder(value: str) -> str:
    if value in {"", ".", "/"}:
        return ""
    if (not isinstance(value, str) or len(value) > 2048 or value.startswith("/") or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError("invalid_workflow_folder")
    return value


def _replacement_patch(path: str, old: str, new: str) -> str:
    def rows(content: str, marker: str) -> list[str]:
        return [part for line in content.splitlines(keepends=True)
                for part in ([marker + line.rstrip("\n"), "\\ No newline at end of file"] if not line.endswith("\n") else [marker + line[:-1]])]
    return "\n".join([f"--- a/{path}", f"+++ b/{path}",
        f"@@ -{1 if old else 0},{len(old.splitlines())} +{1 if new else 0},{len(new.splitlines())} @@",
        *rows(old, "-"), *rows(new, "+")]) + "\n"
