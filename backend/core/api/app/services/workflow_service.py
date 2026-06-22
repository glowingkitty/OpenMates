# backend/core/api/app/services/workflow_service.py
#
# Workflow persistence, graph validation, ownership, and capability service.
# The in-memory repository keeps focused tests and local dev usable before the
# Directus collection bootstrap has been applied; route callers still go through
# this service so Directus-backed storage can replace the repository cleanly.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from copy import deepcopy
from typing import Any

from backend.core.api.app.services.feature_availability_service import (
    FeatureAvailabilityService,
    FeatureDefinition,
)
from backend.core.api.app.services.workflow_models import (
    SUPPORTED_WORKFLOW_APP_SKILLS,
    WorkflowCapability,
    WorkflowDetail,
    WorkflowGraph,
    WorkflowRunDetail,
    WorkflowRunContentRetention,
    WorkflowRunContentStorage,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowSummary,
    WorkflowValidationError,
)


WORKFLOW_PLATFORM_FEATURE = "platform:workflows"
WORKFLOW_EPHEMERAL_RUN_CONTENT_TTL_SECONDS = 7 * 24 * 60 * 60
WORKFLOW_DURABLE_RUN_CONTENT_LIMIT = 5


def _hash_owner_id(user_id: str) -> str:
    return "user_sha256:" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _encrypt_payload(payload: Any) -> tuple[str, str]:
    plaintext = _stable_json(payload).encode("utf-8")
    checksum = "sha256:" + hashlib.sha256(plaintext).hexdigest()
    key = hashlib.sha256(b"openmates-workflows-dev-vault-v1").digest()
    ciphertext = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(plaintext))
    return base64.b64encode(ciphertext).decode("ascii"), checksum


def _decrypt_payload(ciphertext: str) -> Any:
    encrypted = base64.b64decode(ciphertext.encode("ascii"))
    key = hashlib.sha256(b"openmates-workflows-dev-vault-v1").digest()
    plaintext = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(encrypted))
    return json.loads(plaintext.decode("utf-8"))


class WorkflowNotFoundError(KeyError):
    """Raised when a workflow or run does not exist for the current owner."""


class WorkflowFeatureDisabledError(PermissionError):
    """Raised when platform:workflows is disabled."""


class InMemoryWorkflowRepository:
    """Small repository used by tests and as a dev fallback before Directus setup."""

    def __init__(self) -> None:
        self.workflows: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.encrypted_blobs: dict[str, dict[str, Any]] = {}

    def save_workflow(self, record: dict[str, Any]) -> dict[str, Any]:
        self.workflows[record["id"]] = deepcopy(record)
        return deepcopy(record)

    def list_workflows(self, user_id: str) -> list[dict[str, Any]]:
        owner_hash = _hash_owner_id(user_id)
        return [
            deepcopy(record)
            for record in self.workflows.values()
            if record["owner_hash"] == owner_hash and record["status"] != WorkflowStatus.DELETED.value
        ]

    def get_workflow(self, workflow_id: str, user_id: str) -> dict[str, Any] | None:
        record = self.workflows.get(workflow_id)
        if not record or record["owner_hash"] != _hash_owner_id(user_id) or record["status"] == WorkflowStatus.DELETED.value:
            return None
        return deepcopy(record)

    def save_run(self, record: dict[str, Any]) -> dict[str, Any]:
        self.runs[record["id"]] = deepcopy(record)
        return deepcopy(record)

    def list_runs(self, workflow_id: str, user_id: str) -> list[dict[str, Any]]:
        owner_hash = _hash_owner_id(user_id)
        return [
            deepcopy(record)
            for record in self.runs.values()
            if record["workflow_id"] == workflow_id and record["owner_hash"] == owner_hash
        ]

    def get_run(self, workflow_id: str, run_id: str, user_id: str) -> dict[str, Any] | None:
        record = self.runs.get(run_id)
        if not record or record["workflow_id"] != workflow_id or record["owner_hash"] != _hash_owner_id(user_id):
            return None
        return deepcopy(record)

    def save_encrypted_blob(self, blob: dict[str, Any]) -> dict[str, Any]:
        self.encrypted_blobs[blob["ref"]] = deepcopy(blob)
        return deepcopy(blob)

    def get_encrypted_blob(self, ref: str) -> dict[str, Any] | None:
        blob = self.encrypted_blobs.get(ref)
        return deepcopy(blob) if blob else None

    def delete_encrypted_blob(self, ref: str) -> None:
        self.encrypted_blobs.pop(ref, None)


class WorkflowService:
    def __init__(
        self,
        repository: InMemoryWorkflowRepository | None = None,
        feature_availability: FeatureAvailabilityService | None = None,
    ) -> None:
        self.repository = repository or InMemoryWorkflowRepository()
        self.feature_availability = feature_availability or FeatureAvailabilityService(
            definitions=[FeatureDefinition(id=WORKFLOW_PLATFORM_FEATURE, kind="platform", default_enabled=False)],
            config={"feature_overrides": {"enabled": [WORKFLOW_PLATFORM_FEATURE], "disabled": []}},
        )

    def ensure_enabled(self) -> None:
        if not self.feature_availability.is_enabled(WORKFLOW_PLATFORM_FEATURE):
            raise WorkflowFeatureDisabledError("FEATURE_DISABLED")

    def list_workflows(self, user_id: str) -> list[WorkflowSummary]:
        self.ensure_enabled()
        records = sorted(self.repository.list_workflows(user_id), key=lambda item: item["updated_at"], reverse=True)
        return [self._summary_from_record(record) for record in records]

    def get_workflow(self, workflow_id: str, user_id: str) -> WorkflowDetail:
        self.ensure_enabled()
        record = self.repository.get_workflow(workflow_id, user_id)
        if not record:
            raise WorkflowNotFoundError(workflow_id)
        return self._detail_from_record(record)

    def create_workflow(
        self,
        user_id: str,
        title: str,
        graph: dict[str, Any] | WorkflowGraph,
        enabled: bool = False,
        run_content_retention: WorkflowRunContentRetention = WorkflowRunContentRetention.LAST_5,
    ) -> WorkflowDetail:
        self.ensure_enabled()
        workflow_graph = graph if isinstance(graph, WorkflowGraph) else WorkflowGraph.model_validate(graph)
        retention = WorkflowRunContentRetention(run_content_retention)
        now = int(time.time())
        workflow_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        title_blob = self._save_encrypted_blob(user_id, "workflow_title", title)
        graph_payload = workflow_graph.model_dump(mode="json", by_alias=True)
        graph_blob = self._save_encrypted_blob(user_id, "workflow_graph", graph_payload)
        record = {
            "id": workflow_id,
            "owner_hash": _hash_owner_id(user_id),
            "encrypted_title_ref": title_blob["ref"],
            "encrypted_title_checksum": title_blob["checksum"],
            "status": WorkflowStatus.ACTIVE.value if enabled else WorkflowStatus.DISABLED.value,
            "enabled": enabled,
            "trigger_summary": self._trigger_summary(workflow_graph),
            "next_run_at": None,
            "last_run_status": None,
            "run_content_retention": retention.value,
            "current_version_id": version_id,
            "encrypted_graph_ref": graph_blob["ref"],
            "encrypted_graph_checksum": graph_blob["checksum"],
            "versions": [
                {
                    "id": version_id,
                    "version_number": 1,
                    "encrypted_graph_ref": graph_blob["ref"],
                    "encrypted_graph_checksum": graph_blob["checksum"],
                }
            ],
            "created_at": now,
            "updated_at": now,
        }
        return self._detail_from_record(self.repository.save_workflow(record))

    def update_workflow(
        self,
        workflow_id: str,
        user_id: str,
        *,
        title: str | None = None,
        graph: dict[str, Any] | WorkflowGraph | None = None,
        enabled: bool | None = None,
        run_content_retention: WorkflowRunContentRetention | None = None,
    ) -> WorkflowDetail:
        self.ensure_enabled()
        record = self.repository.get_workflow(workflow_id, user_id)
        if not record:
            raise WorkflowNotFoundError(workflow_id)

        if title is not None:
            title_blob = self._save_encrypted_blob(user_id, "workflow_title", title)
            self.repository.delete_encrypted_blob(record["encrypted_title_ref"])
            record["encrypted_title_ref"] = title_blob["ref"]
            record["encrypted_title_checksum"] = title_blob["checksum"]
        if graph is not None:
            workflow_graph = graph if isinstance(graph, WorkflowGraph) else WorkflowGraph.model_validate(graph)
            version_id = str(uuid.uuid4())
            graph_payload = workflow_graph.model_dump(mode="json", by_alias=True)
            graph_blob = self._save_encrypted_blob(user_id, "workflow_graph", graph_payload)
            versions = list(record.get("versions") or [])
            versions.append(
                {
                    "id": version_id,
                    "version_number": len(versions) + 1,
                    "encrypted_graph_ref": graph_blob["ref"],
                    "encrypted_graph_checksum": graph_blob["checksum"],
                }
            )
            record["encrypted_graph_ref"] = graph_blob["ref"]
            record["encrypted_graph_checksum"] = graph_blob["checksum"]
            record["current_version_id"] = version_id
            record["versions"] = versions
            record["trigger_summary"] = self._trigger_summary(workflow_graph)
        if enabled is not None:
            record["enabled"] = enabled
            record["status"] = WorkflowStatus.ACTIVE.value if enabled else WorkflowStatus.DISABLED.value
        if run_content_retention is not None:
            record["run_content_retention"] = WorkflowRunContentRetention(run_content_retention).value
        record["updated_at"] = int(time.time())
        return self._detail_from_record(self.repository.save_workflow(record))

    def delete_workflow(self, workflow_id: str, user_id: str) -> bool:
        self.ensure_enabled()
        record = self.repository.get_workflow(workflow_id, user_id)
        if not record:
            raise WorkflowNotFoundError(workflow_id)
        record["status"] = WorkflowStatus.DELETED.value
        record["enabled"] = False
        record["updated_at"] = int(time.time())
        self.repository.save_workflow(record)
        return True

    def save_run(self, user_id: str, run: WorkflowRunDetail) -> WorkflowRunDetail:
        workflow = self.repository.get_workflow(run.workflow_id, user_id)
        if not workflow:
            raise WorkflowNotFoundError(run.workflow_id)

        retention = WorkflowRunContentRetention(workflow.get("run_content_retention") or WorkflowRunContentRetention.LAST_5.value)
        record = run.model_dump(mode="json", exclude={"node_runs", "output_summary"})
        record["owner_hash"] = _hash_owner_id(user_id)
        record["content_retention_mode"] = retention.value
        record["saved_at"] = time.time_ns()

        run_content = {
            "node_runs": [node.model_dump(mode="json") for node in run.node_runs],
            "output_summary": run.output_summary,
        }
        now = int(time.time())
        if retention == WorkflowRunContentRetention.NONE:
            self._delete_existing_ephemeral_run_content(run.workflow_id, user_id)
            blob = self._save_encrypted_blob(
                user_id,
                "workflow_run_content_ephemeral",
                run_content,
                expires_at=now + WORKFLOW_EPHEMERAL_RUN_CONTENT_TTL_SECONDS,
            )
            record["content_available"] = True
            record["content_storage"] = WorkflowRunContentStorage.EPHEMERAL.value
            record["content_expires_at"] = blob["expires_at"]
            record["encrypted_content_ref"] = blob["ref"]
            record["encrypted_content_checksum"] = blob["checksum"]
        else:
            blob = self._save_encrypted_blob(user_id, "workflow_run_content", run_content)
            record["content_available"] = True
            record["content_storage"] = WorkflowRunContentStorage.DURABLE.value
            record["content_expires_at"] = None
            record["encrypted_content_ref"] = blob["ref"]
            record["encrypted_content_checksum"] = blob["checksum"]

        self.repository.save_run(record)
        self._apply_run_content_retention(run.workflow_id, user_id)

        workflow["last_run_status"] = run.status.value
        workflow["updated_at"] = now
        self.repository.save_workflow(workflow)
        return self.get_run(run.workflow_id, run.id, user_id)

    def list_runs(self, workflow_id: str, user_id: str) -> list[WorkflowRunDetail]:
        self.ensure_enabled()
        if not self.repository.get_workflow(workflow_id, user_id):
            raise WorkflowNotFoundError(workflow_id)
        records = sorted(self.repository.list_runs(workflow_id, user_id), key=lambda item: item.get("started_at") or 0, reverse=True)
        return [self._run_detail_from_record(record) for record in records]

    def get_run(self, workflow_id: str, run_id: str, user_id: str) -> WorkflowRunDetail:
        self.ensure_enabled()
        record = self.repository.get_run(workflow_id, run_id, user_id)
        if not record:
            raise WorkflowNotFoundError(run_id)
        return self._run_detail_from_record(record)

    def capabilities(self) -> list[WorkflowCapability]:
        node_capabilities = [
            WorkflowCapability(type="node", id="schedule_trigger", title="Schedule", metadata={"category": "trigger"}),
            WorkflowCapability(type="node", id="manual_trigger", title="Manual run", metadata={"category": "trigger"}),
            WorkflowCapability(type="node", id="app_skill_action", title="App skill", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="decision", title="Decision", metadata={"category": "decision"}),
            WorkflowCapability(type="node", id="repeat", title="Repeat", metadata={"category": "repeat"}),
            WorkflowCapability(type="node", id="create_chat_report", title="Create chat report", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="send_notification", title="Send push notification", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="send_email_notification", title="Send email notification", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="custom_code", title="Run custom code", enabled=False, reason="Custom code nodes are planned for a later E2B-gated slice"),
        ]
        app_skill_capabilities = [
            WorkflowCapability(type="app_skill", id="weather:forecast", title="Weather forecast", metadata={"app_id": "weather", "skill_id": "forecast"}),
            WorkflowCapability(type="app_skill", id="news:search", title="News search", metadata={"app_id": "news", "skill_id": "search"}),
        ]
        return node_capabilities + app_skill_capabilities

    def _summary_from_record(self, record: dict[str, Any]) -> WorkflowSummary:
        return WorkflowSummary(
            id=record["id"],
            title=str(self._load_encrypted_blob(record["encrypted_title_ref"])),
            status=WorkflowStatus(record["status"]),
            enabled=bool(record["enabled"]),
            trigger_summary=record.get("trigger_summary"),
            next_run_at=record.get("next_run_at"),
            last_run_status=WorkflowRunStatus(record["last_run_status"]) if record.get("last_run_status") else None,
            run_content_retention=WorkflowRunContentRetention(record.get("run_content_retention") or WorkflowRunContentRetention.LAST_5.value),
            current_version_id=record["current_version_id"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )

    def _detail_from_record(self, record: dict[str, Any]) -> WorkflowDetail:
        graph_payload = self._load_encrypted_blob(record["encrypted_graph_ref"])
        return WorkflowDetail(**self._summary_from_record(record).model_dump(), graph=WorkflowGraph.model_validate(graph_payload))

    def _run_detail_from_record(self, record: dict[str, Any]) -> WorkflowRunDetail:
        hydrated = deepcopy(record)
        hydrated["node_runs"] = []
        hydrated["output_summary"] = {}
        if hydrated.get("content_available") and hydrated.get("encrypted_content_ref"):
            blob = self.repository.get_encrypted_blob(hydrated["encrypted_content_ref"])
            if blob and (blob.get("expires_at") is None or blob["expires_at"] > int(time.time())):
                content = _decrypt_payload(blob["ciphertext"])
                hydrated["node_runs"] = content.get("node_runs") or []
                hydrated["output_summary"] = content.get("output_summary") or {}
            else:
                hydrated["content_available"] = False
                hydrated["content_storage"] = WorkflowRunContentStorage.DELETED.value
                hydrated["encrypted_content_ref"] = None
                hydrated["encrypted_content_checksum"] = None
        return WorkflowRunDetail.model_validate(hydrated)

    def _save_encrypted_blob(self, user_id: str, kind: str, payload: Any, expires_at: int | None = None) -> dict[str, Any]:
        ciphertext, checksum = _encrypt_payload(payload)
        return self.repository.save_encrypted_blob(
            {
                "ref": f"vault://workflows/{kind}/{uuid.uuid4()}",
                "owner_hash": _hash_owner_id(user_id),
                "kind": kind,
                "ciphertext": ciphertext,
                "checksum": checksum,
                "expires_at": expires_at,
                "created_at": int(time.time()),
            }
        )

    def _load_encrypted_blob(self, ref: str) -> Any:
        blob = self.repository.get_encrypted_blob(ref)
        if not blob:
            raise WorkflowNotFoundError(ref)
        if blob.get("expires_at") is not None and blob["expires_at"] <= int(time.time()):
            raise WorkflowNotFoundError(ref)
        return _decrypt_payload(blob["ciphertext"])

    def _delete_existing_ephemeral_run_content(self, workflow_id: str, user_id: str) -> None:
        for run_record in self.repository.list_runs(workflow_id, user_id):
            if run_record.get("content_storage") != WorkflowRunContentStorage.EPHEMERAL.value:
                continue
            ref = run_record.get("encrypted_content_ref")
            if ref:
                self.repository.delete_encrypted_blob(ref)
            run_record["content_available"] = False
            run_record["content_storage"] = WorkflowRunContentStorage.DELETED.value
            run_record["encrypted_content_ref"] = None
            run_record["encrypted_content_checksum"] = None
            self.repository.save_run(run_record)

    def _apply_run_content_retention(self, workflow_id: str, user_id: str) -> None:
        durable_runs = [
            record
            for record in self.repository.list_runs(workflow_id, user_id)
            if record.get("content_storage") == WorkflowRunContentStorage.DURABLE.value and record.get("encrypted_content_ref")
        ]
        durable_runs.sort(key=lambda item: (item.get("saved_at") or 0, item.get("started_at") or 0, item["id"]), reverse=True)
        for stale_run in durable_runs[WORKFLOW_DURABLE_RUN_CONTENT_LIMIT:]:
            self.repository.delete_encrypted_blob(stale_run["encrypted_content_ref"])
            stale_run["content_available"] = False
            stale_run["content_storage"] = WorkflowRunContentStorage.DELETED.value
            stale_run["encrypted_content_ref"] = None
            stale_run["encrypted_content_checksum"] = None
            self.repository.save_run(stale_run)

    def _trigger_summary(self, graph: WorkflowGraph) -> str:
        trigger = next(node for node in graph.nodes if node.id == graph.trigger_node_id)
        if trigger.type.value == "schedule_trigger":
            schedule = trigger.config.get("schedule") or {}
            schedule_type = schedule.get("type") or "schedule"
            time_value = schedule.get("time")
            if time_value:
                return f"{schedule_type} at {time_value}"
            return str(schedule_type)
        return trigger.type.value


def validate_app_skill_available(app_id: str, skill_id: str) -> None:
    if (app_id, skill_id) not in SUPPORTED_WORKFLOW_APP_SKILLS:
        raise WorkflowValidationError(f"Workflow app-skill action is not enabled for {app_id}:{skill_id} in V1")
