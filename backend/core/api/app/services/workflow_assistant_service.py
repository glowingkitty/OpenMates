# backend/core/api/app/services/workflow_assistant_service.py
#
# Durable assistant workflow operations. Assistant tool calls may only create
# owner-scoped drafts or cancellable run countdowns; the service is the sole
# execution boundary for a saved draft or elapsed run countdown.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from copy import deepcopy
from typing import Any

import httpx

from backend.core.api.app.services.workflow_models import (
    WorkflowAssistantProposal,
    WorkflowAssistantProposalAction,
    WorkflowAssistantProposalStatus,
    WorkflowDetail,
    WorkflowLifecycle,
    WorkflowNodeType,
)
from backend.core.api.app.services.workflow_service import WorkflowService


WORKFLOW_ASSISTANT_PROPOSAL_TTL_SECONDS = 15 * 60
WORKFLOW_ASSISTANT_RUN_COUNTDOWN_SECONDS = 6
logger = logging.getLogger(__name__)


class WorkflowAssistantProposalNotPendingError(ValueError):
    """Raised when a proposal was already resolved by a competing action."""


class WorkflowAssistantProposalExpiredError(ValueError):
    """Raised when a proposal reaches its deadline before it is saved."""


class WorkflowAssistantDeleteConfirmationRequiredError(ValueError):
    """Raised when a destructive assistant proposal has not been confirmed."""


class InMemoryWorkflowAssistantProposalRepository:
    """Thread-safe durable-process test repository for assistant proposals."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.records[record["proposal_id"]] = deepcopy(record)
            return deepcopy(record)

    def get(self, proposal_id: str, owner_hash: str) -> dict[str, Any] | None:
        with self._lock:
            record = self.records.get(proposal_id)
            if not record or record["owner_hash"] != owner_hash:
                return None
            return deepcopy(record)

    def transition(
        self,
        proposal_id: str,
        owner_hash: str,
        expected_status: WorkflowAssistantProposalStatus,
        next_status: WorkflowAssistantProposalStatus,
        *,
        now: int,
        require_unexpired: bool = False,
        result_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self.records.get(proposal_id)
            if (
                not record
                or record["owner_hash"] != owner_hash
                or record["status"] != expected_status.value
                or (require_unexpired and int(record["expires_at"]) <= now)
            ):
                return None
            record["status"] = next_status.value
            record["updated_at"] = now
            if next_status != WorkflowAssistantProposalStatus.EXECUTING:
                record["resolved_at"] = now
            if result_id is not None:
                record["result_id"] = result_id
            self.records[proposal_id] = deepcopy(record)
            return deepcopy(record)

    def expire_pending(self, now: int) -> int:
        with self._lock:
            expired = 0
            for proposal_id, record in self.records.items():
                if record["status"] == WorkflowAssistantProposalStatus.PENDING.value and int(record["expires_at"]) <= now:
                    record["status"] = WorkflowAssistantProposalStatus.EXPIRED.value
                    record["updated_at"] = now
                    record["resolved_at"] = now
                    self.records[proposal_id] = deepcopy(record)
                    expired += 1
            return expired


class DirectusWorkflowAssistantProposalRepository:
    """Directus proposal persistence with compare-and-set lifecycle transitions."""

    COLLECTION = "workflow_assistant_proposals"

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("CMS_URL") or "http://cms:8055").rstrip("/")
        self.token = token or os.getenv("DIRECTUS_TOKEN")
        self.admin_email = os.getenv("DATABASE_ADMIN_EMAIL")
        self.admin_password = os.getenv("DATABASE_ADMIN_PASSWORD")
        self._admin_token: str | None = None
        self._client = httpx.Client(timeout=5.0)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = self._payload(record)
        existing = self._find_one({"proposal_id": {"_eq": record["proposal_id"]}}, fields="id")
        if existing:
            self._request("PATCH", f"/items/{self.COLLECTION}/{existing['id']}", json=payload)
        else:
            self._request("POST", f"/items/{self.COLLECTION}", json=payload)
        return deepcopy(record)

    def get(self, proposal_id: str, owner_hash: str) -> dict[str, Any] | None:
        item = self._find_one(
            {"_and": [{"proposal_id": {"_eq": proposal_id}}, {"hashed_user_id": {"_eq": owner_hash}}]},
            fields="record_json",
        )
        record = item.get("record_json") if item else None
        return deepcopy(record) if isinstance(record, dict) else None

    def transition(
        self,
        proposal_id: str,
        owner_hash: str,
        expected_status: WorkflowAssistantProposalStatus,
        next_status: WorkflowAssistantProposalStatus,
        *,
        now: int,
        require_unexpired: bool = False,
        result_id: str | None = None,
    ) -> dict[str, Any] | None:
        record = self.get(proposal_id, owner_hash)
        if not record:
            return None
        record["status"] = next_status.value
        record["updated_at"] = now
        if next_status != WorkflowAssistantProposalStatus.EXECUTING:
            record["resolved_at"] = now
        if result_id is not None:
            record["result_id"] = result_id
        conditions: list[dict[str, Any]] = [
            {"proposal_id": {"_eq": proposal_id}},
            {"hashed_user_id": {"_eq": owner_hash}},
            {"status": {"_eq": expected_status.value}},
        ]
        if require_unexpired:
            conditions.append({"expires_at": {"_gt": now}})
        response = self._request(
            "PATCH",
            f"/items/{self.COLLECTION}",
            params={"filter": json.dumps({"_and": conditions}), "fields": "record_json"},
            json=self._payload(record),
        )
        items = response.json().get("data") or []
        if len(items) != 1 or not isinstance(items[0].get("record_json"), dict):
            return None
        return deepcopy(items[0]["record_json"])

    def expire_pending(self, now: int) -> int:
        items = self._get_items(
            {"_and": [{"status": {"_eq": WorkflowAssistantProposalStatus.PENDING.value}}, {"expires_at": {"_lte": now}}]},
            fields="record_json",
        )
        expired = 0
        for item in items:
            record = item.get("record_json")
            if not isinstance(record, dict):
                continue
            if self.transition(
                record["proposal_id"],
                record["owner_hash"],
                WorkflowAssistantProposalStatus.PENDING,
                WorkflowAssistantProposalStatus.EXPIRED,
                now=now,
            ):
                expired += 1
        return expired

    @staticmethod
    def _payload(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "proposal_id": record["proposal_id"],
            "hashed_user_id": record["owner_hash"],
            "action": record["action"],
            "workflow_id": record.get("workflow_id"),
            "status": record["status"],
            "risk_level": record["risk_level"],
            "auto_execute_at": record.get("auto_execute_at"),
            "expires_at": record["expires_at"],
            "resolved_at": record.get("resolved_at"),
            "result_id": record.get("result_id"),
            "encrypted_payload_ref": record["encrypted_payload_ref"],
            "record_json": record,
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

    def _find_one(self, filters: dict[str, Any], fields: str) -> dict[str, Any] | None:
        items = self._get_items(filters, fields=fields, limit=1)
        return items[0] if items else None

    def _get_items(self, filters: dict[str, Any], fields: str = "*", limit: int = -1) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/items/{self.COLLECTION}",
            params={"filter": json.dumps(filters), "fields": fields, "limit": limit},
        )
        return response.json().get("data") or []

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._token()}"}
        response = self._client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def _token(self) -> str:
        if self.token:
            return self.token
        if self._admin_token:
            return self._admin_token
        if not self.admin_email or not self.admin_password:
            raise RuntimeError("Directus workflow proposals require DIRECTUS_TOKEN or admin credentials")
        response = self._client.post(
            f"{self.base_url}/auth/login",
            json={"email": self.admin_email, "password": self.admin_password},
        )
        response.raise_for_status()
        token = response.json().get("data", {}).get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Directus admin login did not return an access token")
        self._admin_token = token
        return token


class WorkflowAssistantService:
    """Owner-scoped drafts and cancellable assistant-triggered workflow runs."""

    def __init__(
        self,
        workflow_service: WorkflowService,
        proposal_repository: Any | None = None,
        enqueue_run_after_countdown: Any | None = None,
    ) -> None:
        self.workflow_service = workflow_service
        self.proposal_repository = proposal_repository or InMemoryWorkflowAssistantProposalRepository()
        self.enqueue_run_after_countdown = enqueue_run_after_countdown or _enqueue_run_after_countdown

    def search(
        self,
        user_id: str,
        query: str,
        include_temporary: bool = False,
        vault_key_id: str | None = None,
    ) -> list[dict[str, Any]]:
        del include_temporary
        normalized = query.strip().lower()
        results: list[dict[str, Any]] = []
        for workflow in self.workflow_service.list_workflows(user_id, vault_key_id):
            if normalized and normalized not in workflow.title.lower():
                continue
            detail = self.workflow_service.get_workflow(workflow.id, user_id, vault_key_id)
            results.append(
                {
                    "workflow_id": workflow.id,
                    "title": workflow.title,
                    "required_input_summary": _required_input_summary(detail.graph.model_dump(mode="json", by_alias=True)),
                }
            )
        return results

    def schedule_once(self, user_id: str, title: str, graph: dict[str, Any], source_chat_id: str | None = None) -> dict[str, Any]:
        if _schedule_type(graph) != "once":
            raise ValueError("schedule_once requires a one-time schedule trigger")
        return self._propose_create(user_id, title, graph, WorkflowLifecycle.TEMPORARY, source_chat_id)

    def schedule_recurring(self, user_id: str, title: str, graph: dict[str, Any], source_chat_id: str | None = None) -> dict[str, Any]:
        if _schedule_type(graph) == "once":
            raise ValueError("schedule_recurring requires a recurring schedule trigger")
        return self._propose_create(user_id, title, graph, WorkflowLifecycle.PERSISTED, source_chat_id)

    def create_or_modify(
        self,
        user_id: str,
        *,
        title: str,
        graph: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        source_chat_id: str | None = None,
    ) -> dict[str, Any]:
        if workflow_id:
            changes: dict[str, Any] = {"title": title}
            if graph is not None:
                changes["graph"] = graph
            return self.propose_update(user_id, workflow_id, changes)
        workflow_graph = graph or {"nodes": []}
        if _schedule_type(workflow_graph) == "once":
            return self.schedule_once(user_id, title, workflow_graph, source_chat_id=source_chat_id)
        return self.schedule_recurring(user_id, title, workflow_graph, source_chat_id=source_chat_id)

    def propose_update(self, user_id: str, workflow_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        workflow = self.workflow_service.get_workflow(workflow_id, user_id)
        allowed = {"title", "description", "graph", "enabled", "run_content_retention"}
        if not changes or any(key not in allowed for key in changes):
            raise ValueError("Workflow update proposal includes unsupported fields")
        if "graph" in changes:
            self.workflow_service.get_workflow(workflow_id, user_id)
        return self._create_proposal(
            user_id,
            WorkflowAssistantProposalAction.UPDATE,
            {"workflow_id": workflow_id, "changes": changes},
            workflow_id=workflow_id,
            title=workflow.title,
            graph=changes.get("graph") or workflow.graph.model_dump(mode="json", by_alias=True),
        )

    def propose_delete(self, user_id: str, workflow_id: str) -> dict[str, Any]:
        workflow = self.workflow_service.get_workflow(workflow_id, user_id)
        return self._create_proposal(
            user_id,
            WorkflowAssistantProposalAction.DELETE,
            {"workflow_id": workflow_id},
            workflow_id=workflow_id,
            title=workflow.title,
            graph=workflow.graph.model_dump(mode="json", by_alias=True),
        )

    def create_pending_run(
        self,
        user_id: str,
        workflow_id: str,
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workflow = self.workflow_service.get_workflow(workflow_id, user_id)
        self.workflow_service.validate_manual_run_input(workflow, input_payload)
        proposal = self._create_proposal(
            user_id,
            WorkflowAssistantProposalAction.RUN,
            {"workflow_id": workflow_id, "input": input_payload or {}},
            workflow_id=workflow_id,
            title=workflow.title,
            graph=workflow.graph.model_dump(mode="json", by_alias=True),
        )
        self.enqueue_run_after_countdown(user_id, proposal["proposal_id"])
        return proposal

    def get_pending(self, user_id: str, proposal_id: str) -> dict[str, Any]:
        record = self.proposal_repository.get(proposal_id, self.workflow_service.repository.workflow_owner_hash(user_id))
        if not record:
            raise WorkflowAssistantProposalNotPendingError("Workflow proposal not found")
        return self._public(record)

    def get_draft_preview(self, user_id: str, proposal_id: str) -> dict[str, Any]:
        """Return a decrypted preview only after the owner-scoped record lookup."""
        record = self.proposal_repository.get(proposal_id, self.workflow_service.repository.workflow_owner_hash(user_id))
        if not record:
            raise WorkflowAssistantProposalNotPendingError("Workflow proposal not found")
        proposal = self._public(record)
        action = WorkflowAssistantProposalAction(record["action"])
        if action not in {WorkflowAssistantProposalAction.CREATE, WorkflowAssistantProposalAction.UPDATE}:
            return proposal
        proposal["preview"] = self._draft_preview(user_id, record)
        return proposal

    def cancel_pending(self, user_id: str, pending_id: str) -> bool:
        return self._resolve_without_execution(user_id, pending_id, WorkflowAssistantProposalStatus.CANCELLED)

    def reject(self, user_id: str, proposal_id: str) -> bool:
        return self._resolve_without_execution(user_id, proposal_id, WorkflowAssistantProposalStatus.REJECTED)

    def expire_pending(self, now: int | None = None) -> int:
        return self.proposal_repository.expire_pending(now if now is not None else int(time.time()))

    async def save(
        self,
        user_id: str,
        proposal_id: str,
        runtime_service: Any | None = None,
        enqueue_accepted_run: Any | None = None,
        *,
        confirm_delete: bool = False,
    ) -> dict[str, Any]:
        record = self.proposal_repository.get(proposal_id, self.workflow_service.repository.workflow_owner_hash(user_id))
        if not record:
            raise WorkflowAssistantProposalNotPendingError("Workflow proposal not found")
        if record["action"] == WorkflowAssistantProposalAction.DELETE.value and not confirm_delete:
            raise WorkflowAssistantDeleteConfirmationRequiredError("Deleting a workflow requires explicit confirmation")
        if record["action"] == WorkflowAssistantProposalAction.RUN.value:
            raise ValueError("Assistant-triggered runs start automatically after the countdown")
        return await self._execute_pending(user_id, proposal_id, runtime_service, enqueue_accepted_run)

    async def confirm_delete(
        self,
        user_id: str,
        proposal_id: str,
        runtime_service: Any | None = None,
        enqueue_accepted_run: Any | None = None,
    ) -> dict[str, Any]:
        return await self.save(
            user_id,
            proposal_id,
            runtime_service,
            enqueue_accepted_run,
            confirm_delete=True,
        )

    async def execute_after_countdown(
        self,
        user_id: str,
        proposal_id: str,
        runtime_service: Any,
        enqueue_accepted_run: Any,
        *,
        now: int | None = None,
    ) -> dict[str, Any]:
        """Run only the durable, still-pending proposal after its task buffer."""
        record = self.proposal_repository.get(proposal_id, self.workflow_service.repository.workflow_owner_hash(user_id))
        if not record:
            raise WorkflowAssistantProposalNotPendingError("Workflow proposal not found")
        if record["action"] != WorkflowAssistantProposalAction.RUN.value:
            raise ValueError("Only assistant-triggered workflow runs use a countdown")
        if int(record.get("auto_execute_at") or 0) > (now if now is not None else int(time.time())):
            raise WorkflowAssistantProposalNotPendingError("Workflow countdown has not finished")
        return await self._execute_pending(user_id, proposal_id, runtime_service, enqueue_accepted_run)

    async def _execute_pending(
        self,
        user_id: str,
        proposal_id: str,
        runtime_service: Any | None,
        enqueue_accepted_run: Any | None,
    ) -> dict[str, Any]:
        now = int(time.time())
        owner_hash = self.workflow_service.repository.workflow_owner_hash(user_id)
        pending = self.proposal_repository.get(proposal_id, owner_hash)
        if not pending:
            raise WorkflowAssistantProposalNotPendingError("Workflow proposal not found")
        if int(pending["expires_at"]) <= now:
            self.proposal_repository.transition(
                proposal_id, owner_hash, WorkflowAssistantProposalStatus.PENDING, WorkflowAssistantProposalStatus.EXPIRED, now=now
            )
            raise WorkflowAssistantProposalExpiredError("Workflow proposal expired")
        claimed = self.proposal_repository.transition(
            proposal_id,
            owner_hash,
            WorkflowAssistantProposalStatus.PENDING,
            WorkflowAssistantProposalStatus.EXECUTING,
            now=now,
            require_unexpired=True,
        )
        if not claimed:
            raise WorkflowAssistantProposalNotPendingError("Workflow proposal is no longer pending")
        try:
            payload = self._load_payload(user_id, claimed["encrypted_payload_ref"])
            result_id = await self._execute_approved(user_id, claimed, payload, runtime_service, enqueue_accepted_run)
            resolved = self.proposal_repository.transition(
                proposal_id,
                owner_hash,
                WorkflowAssistantProposalStatus.EXECUTING,
                WorkflowAssistantProposalStatus.APPROVED,
                now=int(time.time()),
                result_id=result_id,
            )
            if not resolved:
                raise RuntimeError("Workflow proposal save transition was lost")
            self.workflow_service.repository.delete_encrypted_blob(claimed["encrypted_payload_ref"])
            return self._public(resolved)
        except Exception:
            self.proposal_repository.transition(
                proposal_id,
                owner_hash,
                WorkflowAssistantProposalStatus.EXECUTING,
                WorkflowAssistantProposalStatus.FAILED,
                now=int(time.time()),
            )
            self.workflow_service.repository.delete_encrypted_blob(claimed["encrypted_payload_ref"])
            raise

    def keep_temporary(self, user_id: str, workflow_id: str) -> WorkflowDetail:
        return self.workflow_service.keep_temporary_workflow(workflow_id, user_id)

    def _propose_create(
        self,
        user_id: str,
        title: str,
        graph: dict[str, Any],
        lifecycle: WorkflowLifecycle,
        source_chat_id: str | None,
    ) -> dict[str, Any]:
        self.workflow_service.ensure_enabled()
        self.workflow_service.get_workflow  # Keep this facade dependent on the validated core service.
        return self._create_proposal(
            user_id,
            WorkflowAssistantProposalAction.CREATE,
            {
                "title": title,
                "graph": graph,
                "lifecycle": lifecycle.value,
                "source_chat_id": source_chat_id,
            },
            title=title,
            lifecycle=lifecycle,
            graph=graph,
        )

    def _create_proposal(
        self,
        user_id: str,
        action: WorkflowAssistantProposalAction,
        payload: dict[str, Any],
        *,
        workflow_id: str | None = None,
        title: str | None = None,
        lifecycle: WorkflowLifecycle | None = None,
        graph: dict[str, Any],
    ) -> dict[str, Any]:
        graph = self._validate_graph(graph)
        now = int(time.time())
        payload_ref = self._save_payload(user_id, payload)
        record = {
            "proposal_id": str(uuid.uuid4()),
            "owner_hash": self.workflow_service.repository.workflow_owner_hash(user_id),
            "action": action.value,
            "status": WorkflowAssistantProposalStatus.PENDING.value,
            "workflow_id": workflow_id,
            "lifecycle": lifecycle.value if lifecycle else None,
            "title": title,
            "required_input_summary": _required_input_summary(graph),
            "expected_actions": _expected_actions(graph),
            "risk_level": _risk_level(action, graph),
            "encrypted_payload_ref": payload_ref,
            "auto_execute_at": now + WORKFLOW_ASSISTANT_RUN_COUNTDOWN_SECONDS if action == WorkflowAssistantProposalAction.RUN else None,
            "expires_at": now + WORKFLOW_ASSISTANT_PROPOSAL_TTL_SECONDS,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
            "result_id": None,
        }
        return self._public(self.proposal_repository.save(record))

    def _validate_graph(self, graph: dict[str, Any]) -> dict[str, Any]:
        from backend.core.api.app.services.workflow_models import WorkflowGraph

        return WorkflowGraph.model_validate(graph).model_dump(mode="json", by_alias=True)

    def _save_payload(self, user_id: str, payload: dict[str, Any]) -> str:
        vault_key_id = self.workflow_service.resolve_user_vault_key_id(user_id)
        encrypted = self.workflow_service.payload_cipher.encrypt_json(payload, vault_key_id)
        ref = f"vault://workflows/assistant_proposal/{uuid.uuid4()}"
        self.workflow_service.repository.save_encrypted_blob(
            {
                "ref": ref,
                "owner_hash": self.workflow_service.repository.workflow_owner_hash(user_id),
                "kind": "workflow_assistant_proposal",
                "ciphertext": encrypted["ciphertext"],
                "checksum": encrypted["checksum"],
                "vault_key_ref": encrypted.get("vault_key_ref"),
                "key_version": encrypted.get("key_version"),
                "expires_at": None,
                "created_at": int(time.time()),
            }
        )
        return ref

    def _load_payload(self, user_id: str, ref: str) -> dict[str, Any]:
        blob = self.workflow_service.repository.get_encrypted_blob(ref)
        if not blob or blob.get("owner_hash") != self.workflow_service.repository.workflow_owner_hash(user_id):
            raise WorkflowAssistantProposalNotPendingError("Workflow proposal payload not found")
        payload = self.workflow_service.payload_cipher.decrypt_json(blob, self.workflow_service.resolve_user_vault_key_id(user_id))
        if not isinstance(payload, dict):
            raise ValueError("Workflow proposal payload is invalid")
        return payload

    def _draft_preview(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        payload = self._load_payload(user_id, record["encrypted_payload_ref"])
        if record["action"] == WorkflowAssistantProposalAction.CREATE.value:
            return {
                "title": payload["title"],
                "graph": payload["graph"],
                "lifecycle": payload["lifecycle"],
            }
        workflow = self.workflow_service.get_workflow(payload["workflow_id"], user_id)
        preview = workflow.model_dump(mode="json", by_alias=True)
        preview.update(payload["changes"])
        return preview

    async def _execute_approved(
        self,
        user_id: str,
        proposal: dict[str, Any],
        payload: dict[str, Any],
        runtime_service: Any | None,
        enqueue_accepted_run: Any | None,
    ) -> str:
        action = WorkflowAssistantProposalAction(proposal["action"])
        if action == WorkflowAssistantProposalAction.CREATE:
            workflow = self.workflow_service.create_workflow(
                user_id,
                str(payload["title"]),
                payload["graph"],
                enabled=True,
                lifecycle=WorkflowLifecycle(payload["lifecycle"]),
                source="chat",
                source_chat_id=payload.get("source_chat_id"),
                created_by_assistant=True,
            )
            return workflow.id
        if action == WorkflowAssistantProposalAction.UPDATE:
            workflow = self.workflow_service.update_workflow(payload["workflow_id"], user_id, **payload["changes"])
            return workflow.id
        if action == WorkflowAssistantProposalAction.DELETE:
            self.workflow_service.delete_workflow(payload["workflow_id"], user_id)
            return payload["workflow_id"]
        if action == WorkflowAssistantProposalAction.RUN:
            if runtime_service is None or enqueue_accepted_run is None:
                raise RuntimeError("Assistant run execution requires runtime acceptance and dispatch services")
            workflow = self.workflow_service.get_workflow(payload["workflow_id"], user_id)
            self.workflow_service.validate_manual_run_input(workflow, payload.get("input"))
            accepted = await runtime_service.execute(
                "accept_manual_run",
                {
                    "workflow_id": workflow.id,
                    "hashed_user_id": self.workflow_service.repository.workflow_owner_hash(user_id),
                    "trigger_type": "manual",
                    "idempotency_key": proposal["proposal_id"],
                },
            )
            run_id = accepted.get("run_id")
            version_id = accepted.get("version_id")
            if not isinstance(run_id, str) or not run_id or not isinstance(version_id, str) or not version_id:
                raise RuntimeError("Workflow runtime acceptance returned invalid run metadata")
            if accepted.get("status") == "queued":
                enqueue_accepted_run(workflow.id, user_id, run_id, version_id, "manual", payload.get("input") or {})
            return run_id
        raise ValueError("Unsupported workflow proposal action")

    def _resolve_without_execution(self, user_id: str, proposal_id: str, status: WorkflowAssistantProposalStatus) -> bool:
        owner_hash = self.workflow_service.repository.workflow_owner_hash(user_id)
        record = self.proposal_repository.transition(
            proposal_id,
            owner_hash,
            WorkflowAssistantProposalStatus.PENDING,
            status,
            now=int(time.time()),
        )
        if not record:
            return False
        self.workflow_service.repository.delete_encrypted_blob(record["encrypted_payload_ref"])
        return True

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        public = WorkflowAssistantProposal(
            proposal_id=record["proposal_id"],
            action=record["action"],
            status=record["status"],
            workflow_id=record.get("workflow_id"),
            lifecycle=record.get("lifecycle"),
            title=record.get("title"),
            required_input_summary=record.get("required_input_summary") or [],
            expected_actions=record.get("expected_actions") or [],
            risk_level=record["risk_level"],
            requires_approval=False,
            created_at=record["created_at"],
            expires_at=record["expires_at"],
            resolved_at=record.get("resolved_at"),
            result_id=record.get("result_id"),
        ).model_dump(mode="json")
        if record.get("auto_execute_at") is not None:
            public["countdown_ends_at"] = record["auto_execute_at"]
        return public


def _enqueue_run_after_countdown(user_id: str, proposal_id: str) -> None:
    """Schedule the worker buffer separately from the four-second visible countdown."""
    from backend.core.api.app.tasks.workflow_assistant_tasks import execute_workflow_assistant_countdown_task

    execute_workflow_assistant_countdown_task.apply_async(
        args=(user_id, proposal_id),
        countdown=WORKFLOW_ASSISTANT_RUN_COUNTDOWN_SECONDS,
    )


def _schedule_type(graph: dict[str, Any]) -> str | None:
    trigger_id = graph.get("trigger_node_id")
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or node.get("id") != trigger_id:
            continue
        schedule = (node.get("config") or {}).get("schedule") or {}
        if isinstance(schedule, dict):
            return schedule.get("type")
    return None


def _required_input_summary(graph: dict[str, Any]) -> list[str]:
    trigger_id = graph.get("trigger_node_id")
    trigger = next((node for node in graph.get("nodes") or [] if isinstance(node, dict) and node.get("id") == trigger_id), {})
    schema = (trigger.get("config") or {}).get("required_start_input_schema") if isinstance(trigger, dict) else None
    required = schema.get("required") if isinstance(schema, dict) else None
    return [str(field) for field in required] if isinstance(required, list) else []


def _expected_actions(graph: dict[str, Any]) -> list[str]:
    return [
        str(node["type"])
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and node.get("type") not in {"schedule_trigger", "manual_trigger", "event_trigger"}
    ]


def _risk_level(action: WorkflowAssistantProposalAction, graph: dict[str, Any]) -> str:
    node_types = {str(node.get("type")) for node in graph.get("nodes") or [] if isinstance(node, dict)}
    if action == WorkflowAssistantProposalAction.DELETE or WorkflowNodeType.SEND_EMAIL_NOTIFICATION.value in node_types:
        return "high"
    if action in {WorkflowAssistantProposalAction.CREATE, WorkflowAssistantProposalAction.UPDATE, WorkflowAssistantProposalAction.RUN} and node_types - {
        WorkflowNodeType.MANUAL_TRIGGER.value,
        WorkflowNodeType.SCHEDULE_TRIGGER.value,
        WorkflowNodeType.EVENT_TRIGGER.value,
    }:
        return "elevated"
    return "low"
