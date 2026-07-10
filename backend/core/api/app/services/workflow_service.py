# backend/core/api/app/services/workflow_service.py
#
# Workflow persistence, graph validation, ownership, and capability service.
# The in-memory repository keeps focused tests and local dev usable before the
# Directus collection bootstrap has been applied; route callers still go through
# this service so Directus-backed storage can replace the repository cleanly.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import time
import uuid
from copy import deepcopy
from typing import Any, Protocol

import httpx

from backend.core.api.app.services.feature_availability_service import (
    FeatureAvailabilityService,
    FeatureDefinition,
)
from backend.core.api.app.services.workflow_models import (
    SUPPORTED_WORKFLOW_APP_SKILLS,
    WorkflowCapability,
    WorkflowDetail,
    WorkflowGraph,
    WorkflowLifecycle,
    WorkflowMissingInputError,
    WorkflowRunDetail,
    WorkflowRunContentRetention,
    WorkflowRunContentStorage,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowSummary,
    WorkflowValidationError,
)
from backend.core.api.app.utils.encryption import EncryptionService


WORKFLOW_PLATFORM_FEATURE = "platform:workflows"
WORKFLOW_EPHEMERAL_RUN_CONTENT_TTL_SECONDS = 7 * 24 * 60 * 60
WORKFLOW_DURABLE_RUN_CONTENT_LIMIT = 5
WORKFLOW_TEMPORARY_TTL_SECONDS = 7 * 24 * 60 * 60

logger = logging.getLogger(__name__)


def _hash_owner_id(user_id: str) -> str:
    return "user_sha256:" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _workflow_list_sort_key(record: dict[str, Any]) -> tuple[int, int, int]:
    """Put due scheduled workflows first without obscuring recent manual/draft work."""
    next_run_at = record.get("next_run_at")
    if record.get("enabled") and isinstance(next_run_at, int):
        return (0, next_run_at, 0)
    return (1, 0, -int(record.get("updated_at") or 0))


class WorkflowPayloadCipher(Protocol):
    requires_vault_key_id: bool

    def encrypt_json(self, payload: Any, vault_key_id: str | None) -> dict[str, str]:
        """Encrypt a JSON payload and return persisted blob fields."""

    def decrypt_json(self, blob: dict[str, Any], vault_key_id: str | None) -> Any:
        """Decrypt persisted blob fields into a JSON payload."""


class VaultWorkflowPayloadCipher:
    """Vault Transit backed workflow payload encryption."""

    requires_vault_key_id = True

    def __init__(self, encryption_service: EncryptionService | None = None) -> None:
        self.encryption_service = encryption_service or EncryptionService()

    def encrypt_json(self, payload: Any, vault_key_id: str | None) -> dict[str, str]:
        if not vault_key_id:
            raise RuntimeError("Workflow payload encryption requires a user Vault key id")
        plaintext = _stable_json(payload)
        checksum = "sha256:" + hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        ciphertext, key_version = _run_async_blocking(self.encryption_service.encrypt_with_user_key(plaintext, vault_key_id))
        return {
            "ciphertext": ciphertext,
            "checksum": checksum,
            "vault_key_ref": vault_key_id,
            "key_version": key_version,
        }

    def decrypt_json(self, blob: dict[str, Any], vault_key_id: str | None) -> Any:
        key_ref = blob.get("vault_key_ref") or vault_key_id
        if not key_ref:
            raise RuntimeError("Workflow payload decryption requires a user Vault key id")
        plaintext = _run_async_blocking(self.encryption_service.decrypt_with_user_key(blob["ciphertext"], str(key_ref)))
        if plaintext is None:
            raise RuntimeError("Vault returned no plaintext for workflow payload")
        checksum = "sha256:" + hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        if blob.get("checksum") and blob["checksum"] != checksum:
            raise RuntimeError("Workflow payload checksum mismatch")
        return json.loads(plaintext)


def _run_async_blocking(coro: Any) -> Any:
    """Run an async Vault call from sync workflow service code without reusing event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


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

    def list_all_workflow_records(self, user_id: str | None = None) -> list[dict[str, Any]]:
        owner_hash = _hash_owner_id(user_id) if user_id else None
        return [
            deepcopy(record)
            for record in self.workflows.values()
            if (owner_hash is None or record["owner_hash"] == owner_hash) and record["status"] != WorkflowStatus.DELETED.value
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

    def list_run_records_for_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return [deepcopy(record) for record in self.runs.values() if record["workflow_id"] == workflow_id]

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

    def delete_workflow_record(self, workflow_id: str) -> None:
        self.workflows.pop(workflow_id, None)

    def delete_run_record(self, run_id: str) -> None:
        self.runs.pop(run_id, None)

    def get_user_vault_key_id(self, user_id: str) -> str | None:
        del user_id
        return None


class DirectusWorkflowRepository:
    """Durable workflow repository backed by Directus custom collections."""

    WORKFLOWS = "workflows"
    RUNS = "workflow_runs"
    BLOBS = "workflow_encrypted_blobs"

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("CMS_URL") or "http://cms:8055").rstrip("/")
        self.token = token or os.getenv("DIRECTUS_TOKEN")
        self.admin_email = os.getenv("DATABASE_ADMIN_EMAIL")
        self.admin_password = os.getenv("DATABASE_ADMIN_PASSWORD")
        self._admin_token: str | None = None
        self._client = httpx.Client(timeout=5.0)

    def save_workflow(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": record["id"],
            "workflow_id": record["id"],
            "hashed_user_id": record["owner_hash"],
            "encrypted_title": record["encrypted_title_ref"],
            "status": record["status"],
            "enabled": record["enabled"],
            "lifecycle": record.get("lifecycle", WorkflowLifecycle.PERSISTED.value),
            "source": record.get("source") or "manual",
            "source_chat_id": record.get("source_chat_id"),
            "created_by_assistant": bool(record.get("created_by_assistant")),
            "auto_delete_at": record.get("auto_delete_at"),
            "kept_at": record.get("kept_at"),
            "current_version_id": record["current_version_id"],
            "trigger_type": record.get("trigger_type") or record.get("trigger_summary"),
            "trigger_summary": record.get("trigger_summary"),
            "next_run_at": record.get("next_run_at"),
            "last_run_id": record.get("last_run_id"),
            "last_run_status": record.get("last_run_status"),
            "run_content_retention": record.get("run_content_retention"),
            "deleted_at": record.get("updated_at") if record.get("status") == WorkflowStatus.DELETED.value else None,
            "record_json": record,
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }
        existing = self._find_one(self.WORKFLOWS, {"id": {"_eq": record["id"]}}, fields="id")
        if existing:
            self._patch_item(self.WORKFLOWS, existing["id"], payload)
        else:
            self._create_item(self.WORKFLOWS, payload)
        return deepcopy(record)

    def list_workflows(self, user_id: str) -> list[dict[str, Any]]:
        return self.list_all_workflow_records(user_id=user_id)

    def list_all_workflow_records(self, user_id: str | None = None) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"status": {"_neq": WorkflowStatus.DELETED.value}}
        if user_id is not None:
            filters["hashed_user_id"] = {"_eq": _hash_owner_id(user_id)}
        items = self._get_items(self.WORKFLOWS, filters, sort="-updated_at", limit=-1)
        return [deepcopy(item["record_json"]) for item in items if isinstance(item.get("record_json"), dict)]

    def get_workflow(self, workflow_id: str, user_id: str) -> dict[str, Any] | None:
        item = self._find_one(
            self.WORKFLOWS,
            {"_and": [{"id": {"_eq": workflow_id}}, {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}}]},
        )
        if not item or not isinstance(item.get("record_json"), dict):
            return None
        record = item["record_json"]
        if record.get("status") == WorkflowStatus.DELETED.value:
            return None
        return deepcopy(record)

    def save_run(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": record["id"],
            "run_id": record["id"],
            "workflow_id": record["workflow_id"],
            "version_id": record["version_id"],
            "hashed_user_id": record["owner_hash"],
            "trigger_id": record.get("trigger_id"),
            "trigger_type": record.get("trigger_type"),
            "status": record.get("status"),
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
            "cost_summary": record.get("cost_summary"),
            "error_summary": record.get("error_summary"),
            "encrypted_input": None,
            "encrypted_output_summary": record.get("encrypted_content_ref"),
            "content_retention_mode": record.get("content_retention_mode"),
            "content_available": record.get("content_available"),
            "content_storage": record.get("content_storage"),
            "content_expires_at": record.get("content_expires_at"),
            "record_json": record,
        }
        existing = self._find_one(self.RUNS, {"id": {"_eq": record["id"]}}, fields="id")
        if existing:
            self._patch_item(self.RUNS, existing["id"], payload)
        else:
            self._create_item(self.RUNS, payload)
        return deepcopy(record)

    def list_runs(self, workflow_id: str, user_id: str) -> list[dict[str, Any]]:
        items = self._get_items(
            self.RUNS,
            {"_and": [{"workflow_id": {"_eq": workflow_id}}, {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}}]},
            sort="-started_at",
            limit=-1,
        )
        return [deepcopy(item["record_json"]) for item in items if isinstance(item.get("record_json"), dict)]

    def list_run_records_for_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        items = self._get_items(self.RUNS, {"workflow_id": {"_eq": workflow_id}}, sort="-started_at", limit=-1)
        return [deepcopy(item["record_json"]) for item in items if isinstance(item.get("record_json"), dict)]

    def get_run(self, workflow_id: str, run_id: str, user_id: str) -> dict[str, Any] | None:
        item = self._find_one(
            self.RUNS,
            {
                "_and": [
                    {"id": {"_eq": run_id}},
                    {"workflow_id": {"_eq": workflow_id}},
                    {"hashed_user_id": {"_eq": _hash_owner_id(user_id)}},
                ]
            },
        )
        if not item or not isinstance(item.get("record_json"), dict):
            return None
        return deepcopy(item["record_json"])

    def save_encrypted_blob(self, blob: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "ref": blob["ref"],
            "hashed_user_id": blob["owner_hash"],
            "kind": blob["kind"],
            "ciphertext": blob["ciphertext"],
            "checksum": blob["checksum"],
            "vault_key_ref": blob.get("vault_key_ref"),
            "key_version": blob.get("key_version"),
            "expires_at": blob.get("expires_at"),
            "created_at": blob["created_at"],
        }
        existing = self._find_one(self.BLOBS, {"ref": {"_eq": blob["ref"]}}, fields="id")
        if existing:
            self._patch_item(self.BLOBS, existing["id"], payload)
        else:
            self._create_item(self.BLOBS, payload)
        return deepcopy(blob)

    def get_encrypted_blob(self, ref: str) -> dict[str, Any] | None:
        item = self._find_one(self.BLOBS, {"ref": {"_eq": ref}})
        if not item:
            return None
        return {
            "ref": item["ref"],
            "owner_hash": item["hashed_user_id"],
            "kind": item["kind"],
            "ciphertext": item["ciphertext"],
            "checksum": item["checksum"],
            "vault_key_ref": item.get("vault_key_ref"),
            "key_version": item.get("key_version"),
            "expires_at": item.get("expires_at"),
            "created_at": item["created_at"],
        }

    def delete_encrypted_blob(self, ref: str) -> None:
        item = self._find_one(self.BLOBS, {"ref": {"_eq": ref}}, fields="id")
        if item:
            self._delete_item(self.BLOBS, item["id"])

    def delete_workflow_record(self, workflow_id: str) -> None:
        item = self._find_one(self.WORKFLOWS, {"id": {"_eq": workflow_id}}, fields="id")
        if item:
            self._delete_item(self.WORKFLOWS, item["id"])

    def delete_run_record(self, run_id: str) -> None:
        item = self._find_one(self.RUNS, {"id": {"_eq": run_id}}, fields="id")
        if item:
            self._delete_item(self.RUNS, item["id"])

    def get_user_vault_key_id(self, user_id: str) -> str | None:
        response = self._request("GET", f"/users/{user_id}", params={"fields": "vault_key_id"})
        vault_key_id = response.json().get("data", {}).get("vault_key_id")
        return str(vault_key_id) if vault_key_id else None

    def _find_one(self, collection: str, filters: dict[str, Any], fields: str = "*") -> dict[str, Any] | None:
        items = self._get_items(collection, filters, fields=fields, limit=1)
        return items[0] if items else None

    def _get_items(
        self,
        collection: str,
        filters: dict[str, Any],
        *,
        fields: str = "*",
        sort: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"filter": json.dumps(filters), "fields": fields, "limit": limit, "_ts": str(time.time_ns())}
        if sort:
            params["sort"] = sort
        response = self._request("GET", f"/items/{collection}", params=params)
        data = response.json().get("data")
        if not isinstance(data, list):
            raise RuntimeError(f"Directus returned invalid list response for {collection}")
        return data

    def _create_item(self, collection: str, payload: dict[str, Any]) -> None:
        self._request("POST", f"/items/{collection}", json=payload)

    def _patch_item(self, collection: str, item_id: str, payload: dict[str, Any]) -> None:
        patch_payload = {key: value for key, value in payload.items() if key != "id"}
        self._request("PATCH", f"/items/{collection}/{item_id}", json=patch_payload)

    def _delete_item(self, collection: str, item_id: str) -> None:
        self._request("DELETE", f"/items/{collection}/{item_id}")

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Authorization", f"Bearer {self._token()}")
        response = self._client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        if 200 <= response.status_code < 300:
            return response
        if response.status_code == 401:
            self._admin_token = None
            self.token = None
            headers["Authorization"] = f"Bearer {self._admin_login_token()}"
            response = self._client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
            if 200 <= response.status_code < 300:
                return response
        logger.error("Directus workflow request failed: %s %s -> %s %s", method, path, response.status_code, response.text[:500])
        response.raise_for_status()
        return response

    def _token(self) -> str:
        if self.token:
            return self.token
        return self._admin_login_token()

    def _admin_login_token(self) -> str:
        if self._admin_token:
            return self._admin_token
        if not self.admin_email or not self.admin_password:
            raise RuntimeError("Directus workflow repository requires DIRECTUS_TOKEN or admin credentials")
        response = self._client.post(
            f"{self.base_url}/auth/login",
            json={"email": self.admin_email, "password": self.admin_password},
        )
        if not (200 <= response.status_code < 300):
            raise RuntimeError(f"Directus admin login failed for workflow repository: {response.status_code}")
        token = response.json().get("data", {}).get("access_token")
        if not token:
            raise RuntimeError("Directus admin login did not return an access token")
        self._admin_token = str(token)
        return self._admin_token


class WorkflowService:
    def __init__(
        self,
        repository: Any | None = None,
        feature_availability: FeatureAvailabilityService | None = None,
        payload_cipher: WorkflowPayloadCipher | None = None,
    ) -> None:
        self.repository = repository or InMemoryWorkflowRepository()
        self.payload_cipher = payload_cipher or VaultWorkflowPayloadCipher()
        self.feature_availability = feature_availability or FeatureAvailabilityService(
            definitions=[FeatureDefinition(id=WORKFLOW_PLATFORM_FEATURE, kind="platform", default_enabled=False)],
            config={"feature_overrides": {"enabled": [WORKFLOW_PLATFORM_FEATURE], "disabled": []}},
        )

    def ensure_enabled(self) -> None:
        if not self.feature_availability.is_enabled(WORKFLOW_PLATFORM_FEATURE):
            raise WorkflowFeatureDisabledError("FEATURE_DISABLED")

    def resolve_user_vault_key_id(self, user_id: str, vault_key_id: str | None = None) -> str | None:
        """Return the Vault Transit key id required for workflow blob encryption."""
        return self._vault_key_id_for_user(user_id, vault_key_id)

    def list_workflows(self, user_id: str, vault_key_id: str | None = None) -> list[WorkflowSummary]:
        self.ensure_enabled()
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
        records = [
            record
            for record in self.repository.list_workflows(user_id)
            if record.get("lifecycle", WorkflowLifecycle.PERSISTED.value) == WorkflowLifecycle.PERSISTED.value
        ]
        records = sorted(records, key=_workflow_list_sort_key)
        return [self._summary_from_record(record, vault_key_id) for record in records]

    def list_temporary_workflows(self, user_id: str, vault_key_id: str | None = None) -> list[WorkflowSummary]:
        self.ensure_enabled()
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
        records = [
            record
            for record in self.repository.list_workflows(user_id)
            if record.get("lifecycle") == WorkflowLifecycle.TEMPORARY.value
        ]
        records = sorted(records, key=_workflow_list_sort_key)
        return [self._summary_from_record(record, vault_key_id) for record in records]

    def get_workflow(self, workflow_id: str, user_id: str, vault_key_id: str | None = None) -> WorkflowDetail:
        self.ensure_enabled()
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
        record = self.repository.get_workflow(workflow_id, user_id)
        if not record:
            raise WorkflowNotFoundError(workflow_id)
        return self._detail_from_record(record, vault_key_id)

    def create_workflow(
        self,
        user_id: str,
        title: str,
        graph: dict[str, Any] | WorkflowGraph,
        enabled: bool = False,
        run_content_retention: WorkflowRunContentRetention = WorkflowRunContentRetention.LAST_5,
        lifecycle: WorkflowLifecycle | str = WorkflowLifecycle.PERSISTED,
        source: str = "manual",
        source_chat_id: str | None = None,
        created_by_assistant: bool = False,
        auto_delete_at: int | None = None,
        vault_key_id: str | None = None,
    ) -> WorkflowDetail:
        self.ensure_enabled()
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
        workflow_graph = graph if isinstance(graph, WorkflowGraph) else WorkflowGraph.model_validate(graph)
        retention = WorkflowRunContentRetention(run_content_retention)
        workflow_lifecycle = WorkflowLifecycle(lifecycle)
        now = int(time.time())
        if workflow_lifecycle == WorkflowLifecycle.TEMPORARY:
            minimum_auto_delete_at = now + WORKFLOW_TEMPORARY_TTL_SECONDS
            if auto_delete_at is None:
                auto_delete_at = minimum_auto_delete_at
            elif auto_delete_at < minimum_auto_delete_at:
                raise ValueError("temporary workflows must auto-delete no sooner than seven days after creation")
        if workflow_lifecycle == WorkflowLifecycle.PERSISTED and auto_delete_at is not None:
            raise ValueError("auto_delete_at is only valid for temporary workflows")
        workflow_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        title_blob = self._save_encrypted_blob(user_id, "workflow_title", title, vault_key_id=vault_key_id)
        graph_payload = workflow_graph.model_dump(mode="json", by_alias=True)
        graph_blob = self._save_encrypted_blob(user_id, "workflow_graph", graph_payload, vault_key_id=vault_key_id)
        record = {
            "id": workflow_id,
            "owner_hash": _hash_owner_id(user_id),
            "encrypted_title_ref": title_blob["ref"],
            "encrypted_title_checksum": title_blob["checksum"],
            "status": WorkflowStatus.ACTIVE.value if enabled else WorkflowStatus.DISABLED.value,
            "enabled": enabled,
            "lifecycle": workflow_lifecycle.value,
            "source": source,
            "source_chat_id": source_chat_id,
            "created_by_assistant": created_by_assistant,
            "auto_delete_at": auto_delete_at,
            "kept_at": None,
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
        return self._detail_from_record(self.repository.save_workflow(record), vault_key_id)

    def update_workflow(
        self,
        workflow_id: str,
        user_id: str,
        *,
        title: str | None = None,
        graph: dict[str, Any] | WorkflowGraph | None = None,
        enabled: bool | None = None,
        run_content_retention: WorkflowRunContentRetention | None = None,
        vault_key_id: str | None = None,
    ) -> WorkflowDetail:
        self.ensure_enabled()
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
        record = self.repository.get_workflow(workflow_id, user_id)
        if not record:
            raise WorkflowNotFoundError(workflow_id)

        if title is not None:
            title_blob = self._save_encrypted_blob(user_id, "workflow_title", title, vault_key_id=vault_key_id)
            self.repository.delete_encrypted_blob(record["encrypted_title_ref"])
            record["encrypted_title_ref"] = title_blob["ref"]
            record["encrypted_title_checksum"] = title_blob["checksum"]
        if graph is not None:
            workflow_graph = graph if isinstance(graph, WorkflowGraph) else WorkflowGraph.model_validate(graph)
            version_id = str(uuid.uuid4())
            graph_payload = workflow_graph.model_dump(mode="json", by_alias=True)
            graph_blob = self._save_encrypted_blob(user_id, "workflow_graph", graph_payload, vault_key_id=vault_key_id)
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
        return self._detail_from_record(self.repository.save_workflow(record), vault_key_id)

    def keep_temporary_workflow(self, workflow_id: str, user_id: str, vault_key_id: str | None = None) -> WorkflowDetail:
        self.ensure_enabled()
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
        record = self.repository.get_workflow(workflow_id, user_id)
        if not record:
            raise WorkflowNotFoundError(workflow_id)
        if record.get("lifecycle") != WorkflowLifecycle.TEMPORARY.value:
            raise ValueError("Only temporary workflows can be kept")
        now = int(time.time())
        record["lifecycle"] = WorkflowLifecycle.PERSISTED.value
        record["auto_delete_at"] = None
        record["kept_at"] = now
        record["updated_at"] = now
        return self._detail_from_record(self.repository.save_workflow(record), vault_key_id)

    def cleanup_expired_temporary_workflows(self, user_id: str | None = None, now: int | None = None) -> int:
        self.ensure_enabled()
        cutoff = now if now is not None else int(time.time())
        deleted = 0
        records = self.repository.list_all_workflow_records(user_id=user_id)
        for record in records:
            if user_id is not None and record.get("owner_hash") != _hash_owner_id(user_id):
                continue
            if record.get("lifecycle") != WorkflowLifecycle.TEMPORARY.value:
                continue
            auto_delete_at = record.get("auto_delete_at")
            if not isinstance(auto_delete_at, int) or auto_delete_at > cutoff:
                continue
            workflow_id = record["id"]
            for ref_key in ("encrypted_title_ref", "encrypted_graph_ref"):
                ref = record.get(ref_key)
                if ref:
                    self.repository.delete_encrypted_blob(ref)
            for run_record in self.repository.list_run_records_for_workflow(workflow_id):
                if run_record.get("workflow_id") != workflow_id:
                    continue
                ref = run_record.get("encrypted_content_ref")
                if ref:
                    self.repository.delete_encrypted_blob(ref)
                self.repository.delete_run_record(run_record["id"])
            self.repository.delete_workflow_record(workflow_id)
            deleted += 1
        return deleted

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

    def save_run(self, user_id: str, run: WorkflowRunDetail, vault_key_id: str | None = None) -> WorkflowRunDetail:
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
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
                vault_key_id=vault_key_id,
            )
            record["content_available"] = True
            record["content_storage"] = WorkflowRunContentStorage.EPHEMERAL.value
            record["content_expires_at"] = blob["expires_at"]
            record["encrypted_content_ref"] = blob["ref"]
            record["encrypted_content_checksum"] = blob["checksum"]
        else:
            blob = self._save_encrypted_blob(user_id, "workflow_run_content", run_content, vault_key_id=vault_key_id)
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
        return self.get_run(run.workflow_id, run.id, user_id, vault_key_id=vault_key_id)

    def list_runs(self, workflow_id: str, user_id: str, vault_key_id: str | None = None) -> list[WorkflowRunDetail]:
        self.ensure_enabled()
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
        if not self.repository.get_workflow(workflow_id, user_id):
            raise WorkflowNotFoundError(workflow_id)
        records = sorted(self.repository.list_runs(workflow_id, user_id), key=lambda item: item.get("started_at") or 0, reverse=True)
        return [self._run_detail_from_record(record, vault_key_id) for record in records]

    def get_run(self, workflow_id: str, run_id: str, user_id: str, vault_key_id: str | None = None) -> WorkflowRunDetail:
        self.ensure_enabled()
        vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
        record = self.repository.get_run(workflow_id, run_id, user_id)
        if not record:
            raise WorkflowNotFoundError(run_id)
        return self._run_detail_from_record(record, vault_key_id)

    def validate_manual_run_input(self, workflow: WorkflowDetail, input_payload: dict[str, Any] | None) -> None:
        from backend.core.api.app.services.workflow_models import validate_manual_run_input

        try:
            validate_manual_run_input(workflow.graph, input_payload)
        except WorkflowMissingInputError:
            raise

    def capabilities(self, user_id: str | None = None, vault_key_id: str | None = None) -> list[WorkflowCapability]:
        node_capabilities = [
            WorkflowCapability(type="node", id="schedule_trigger", title="Schedule", metadata={"category": "trigger"}),
            WorkflowCapability(type="node", id="manual_trigger", title="Manual run", metadata={"category": "trigger"}),
            WorkflowCapability(type="node", id="app_skill_action", title="App skill", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="decision", title="Decision", metadata={"category": "decision"}),
            WorkflowCapability(type="node", id="repeat", title="Repeat", metadata={"category": "repeat"}),
            WorkflowCapability(type="node", id="create_chat_report", title="Create chat report", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="start_new_chat", title="Start new chat", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="send_notification", title="Send push notification", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="send_email_notification", title="Send email notification", metadata={"category": "action"}),
            WorkflowCapability(type="node", id="event_trigger", title="Event trigger", enabled=False, reason="Event triggers require scoped event matching before execution"),
            WorkflowCapability(type="node", id="custom_code", title="Run custom code", enabled=False, reason="Custom code nodes are planned for a later E2B-gated slice"),
        ]
        app_skill_capabilities = [
            WorkflowCapability(type="app_skill", id="weather:forecast", title="Weather forecast", metadata={"app_id": "weather", "skill_id": "forecast"}),
            WorkflowCapability(type="app_skill", id="news:search", title="News search", metadata={"app_id": "news", "skill_id": "search"}),
        ]
        workflow_capabilities: list[WorkflowCapability] = []
        if user_id is not None:
            vault_key_id = self._vault_key_id_for_user(user_id, vault_key_id)
            workflow_capabilities = [
                WorkflowCapability(
                    type="workflow",
                    id=f"workflow:{record['id']}",
                    title=str(self._load_encrypted_blob(record["encrypted_title_ref"], vault_key_id)),
                    metadata={
                        "workflow_id": record["id"],
                        "lifecycle": record.get("lifecycle", WorkflowLifecycle.PERSISTED.value),
                        "trigger_type": record.get("trigger_type") or self._trigger_type_from_record(record, vault_key_id),
                        "requires_input": self._workflow_requires_start_input(record, vault_key_id),
                    },
                )
                for record in self.repository.list_workflows(user_id)
                if record.get("lifecycle", WorkflowLifecycle.PERSISTED.value) == WorkflowLifecycle.PERSISTED.value
            ]
        return node_capabilities + app_skill_capabilities + workflow_capabilities

    def _summary_from_record(self, record: dict[str, Any], vault_key_id: str | None) -> WorkflowSummary:
        return WorkflowSummary(
            id=record["id"],
            title=str(self._load_encrypted_blob(record["encrypted_title_ref"], vault_key_id)),
            status=WorkflowStatus(record["status"]),
            enabled=bool(record["enabled"]),
            lifecycle=WorkflowLifecycle(record.get("lifecycle", WorkflowLifecycle.PERSISTED.value)),
            source=record.get("source") or "manual",
            source_chat_id=record.get("source_chat_id"),
            created_by_assistant=bool(record.get("created_by_assistant")),
            auto_delete_at=record.get("auto_delete_at"),
            kept_at=record.get("kept_at"),
            trigger_summary=record.get("trigger_summary"),
            next_run_at=record.get("next_run_at"),
            last_run_status=WorkflowRunStatus(record["last_run_status"]) if record.get("last_run_status") else None,
            run_content_retention=WorkflowRunContentRetention(record.get("run_content_retention") or WorkflowRunContentRetention.LAST_5.value),
            current_version_id=record["current_version_id"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )

    def _detail_from_record(self, record: dict[str, Any], vault_key_id: str | None) -> WorkflowDetail:
        graph_payload = self._load_encrypted_blob(record["encrypted_graph_ref"], vault_key_id)
        return WorkflowDetail(**self._summary_from_record(record, vault_key_id).model_dump(), graph=WorkflowGraph.model_validate(graph_payload))

    def _run_detail_from_record(self, record: dict[str, Any], vault_key_id: str | None) -> WorkflowRunDetail:
        hydrated = deepcopy(record)
        hydrated["node_runs"] = []
        hydrated["output_summary"] = {}
        if hydrated.get("content_available") and hydrated.get("encrypted_content_ref"):
            blob = self.repository.get_encrypted_blob(hydrated["encrypted_content_ref"])
            if blob and (blob.get("expires_at") is None or blob["expires_at"] > int(time.time())):
                content = self.payload_cipher.decrypt_json(blob, vault_key_id)
                hydrated["node_runs"] = content.get("node_runs") or []
                hydrated["output_summary"] = content.get("output_summary") or {}
            else:
                hydrated["content_available"] = False
                hydrated["content_storage"] = WorkflowRunContentStorage.DELETED.value
                hydrated["encrypted_content_ref"] = None
                hydrated["encrypted_content_checksum"] = None
        return WorkflowRunDetail.model_validate(hydrated)

    def _save_encrypted_blob(self, user_id: str, kind: str, payload: Any, expires_at: int | None = None, vault_key_id: str | None = None) -> dict[str, Any]:
        encrypted = self.payload_cipher.encrypt_json(payload, vault_key_id)
        return self.repository.save_encrypted_blob(
            {
                "ref": f"vault://workflows/{kind}/{uuid.uuid4()}",
                "owner_hash": _hash_owner_id(user_id),
                "kind": kind,
                "ciphertext": encrypted["ciphertext"],
                "checksum": encrypted["checksum"],
                "vault_key_ref": encrypted.get("vault_key_ref"),
                "key_version": encrypted.get("key_version"),
                "expires_at": expires_at,
                "created_at": int(time.time()),
            }
        )

    def _load_encrypted_blob(self, ref: str, vault_key_id: str | None) -> Any:
        blob = self.repository.get_encrypted_blob(ref)
        if not blob:
            raise WorkflowNotFoundError(ref)
        if blob.get("expires_at") is not None and blob["expires_at"] <= int(time.time()):
            raise WorkflowNotFoundError(ref)
        return self.payload_cipher.decrypt_json(blob, vault_key_id)

    def _vault_key_id_for_user(self, user_id: str, vault_key_id: str | None = None) -> str | None:
        if not self.payload_cipher.requires_vault_key_id:
            return vault_key_id
        resolved = vault_key_id
        if not resolved and hasattr(self.repository, "get_user_vault_key_id"):
            resolved = self.repository.get_user_vault_key_id(user_id)
        if not resolved:
            raise RuntimeError("Workflow encryption requires the user's Vault key id")
        return resolved

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

    def _trigger_type_from_record(self, record: dict[str, Any], vault_key_id: str | None) -> str:
        try:
            graph = WorkflowGraph.model_validate(self._load_encrypted_blob(record["encrypted_graph_ref"], vault_key_id))
            return next(node.type.value for node in graph.nodes if node.id == graph.trigger_node_id)
        except Exception:
            return "unknown"

    def _workflow_requires_start_input(self, record: dict[str, Any], vault_key_id: str | None) -> bool:
        try:
            graph = WorkflowGraph.model_validate(self._load_encrypted_blob(record["encrypted_graph_ref"], vault_key_id))
            trigger = next(node for node in graph.nodes if node.id == graph.trigger_node_id)
            schema = trigger.config.get("required_start_input_schema") or {}
            return bool(schema.get("required"))
        except Exception:
            return False


def validate_app_skill_available(app_id: str, skill_id: str) -> None:
    if (app_id, skill_id) not in SUPPORTED_WORKFLOW_APP_SKILLS:
        raise WorkflowValidationError(f"Workflow app-skill action is not enabled for {app_id}:{skill_id} in V1")
