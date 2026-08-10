# backend/core/api/app/services/user_task_update_job_service.py
#
# Tasks V1 client-encrypted update job protocol. Jobs lease a vault-encrypted
# working copy to one authenticated device and accept only client-encrypted
# terminal payloads. This first implementation is intentionally repository-free
# so unit tests can prove claim, lease, conflict, and idempotency semantics.

from __future__ import annotations

import secrets
import time
import uuid
from copy import deepcopy
from typing import Any, Callable


DEFAULT_TASK_UPDATE_JOB_TTL_SECONDS = 15 * 60
DEFAULT_TASK_UPDATE_JOB_LEASE_TTL_SECONDS = 60
TASK_UPDATE_JOB_PENDING = "PENDING"
TASK_UPDATE_JOB_LEASED = "LEASED"
TASK_UPDATE_JOB_TERMINAL = "TERMINAL"
ALLOWED_CLIENT_PAYLOAD_SAFE_KEYS = {
    "ai_execution_state",
    "assignee_hash",
    "assignee_type",
    "blocked_reason_code",
    "created_at",
    "due_at",
    "key_wrappers",
    "label_hashes",
    "linked_project_ids",
    "parent_task_id",
    "plan_id",
    "plan_step_id",
    "position",
    "primary_chat_id",
    "priority",
    "queue_state",
    "status",
    "task_id",
    "task_type",
    "updated_at",
    "verification_id",
    "version",
}


class TaskUpdateJobConflictError(ValueError):
    """Raised when a task update job lease or commit conflicts."""


class TaskUpdateJobNotFoundError(ValueError):
    """Raised when a task update job is not visible to the caller."""


class UserTaskUpdateJobService:
    def __init__(
        self,
        *,
        clock: Callable[[], int] | None = None,
        lease_ttl_seconds: int = DEFAULT_TASK_UPDATE_JOB_LEASE_TTL_SECONDS,
        job_ttl_seconds: int = DEFAULT_TASK_UPDATE_JOB_TTL_SECONDS,
    ):
        self.clock = clock or (lambda: int(time.time()))
        self.lease_ttl_seconds = lease_ttl_seconds
        self.job_ttl_seconds = job_ttl_seconds
        self._jobs: dict[str, dict[str, Any]] = {}

    def create_job(
        self,
        *,
        owner_id: str,
        task_id: str,
        chat_id: str | None,
        working_copy_ref: str,
        expected_task_version: int,
        task_key_version: int,
    ) -> dict[str, Any]:
        now = int(self.clock())
        job_id = f"task-update-job-{uuid.uuid4()}"
        job = {
            "job_id": job_id,
            "owner_id": owner_id,
            "task_id": task_id,
            "chat_id": chat_id,
            "working_copy_ref": working_copy_ref,
            "expected_task_version": int(expected_task_version),
            "task_key_version": int(task_key_version),
            "state": TASK_UPDATE_JOB_PENDING,
            "lease_token": None,
            "lease_generation": 0,
            "lease_device_hash": None,
            "lease_expires_at": None,
            "client_encrypted_payload": None,
            "encrypted_task_event_message": None,
            "created_at": now,
            "expires_at": now + self.job_ttl_seconds,
        }
        self._jobs[job_id] = job
        return deepcopy(job)

    def get_job(self, *, job_id: str, owner_id: str) -> dict[str, Any]:
        job = self._get_visible_job(job_id, owner_id)
        return deepcopy(job)

    def claim_job(self, *, job_id: str, owner_id: str, device_hash: str) -> dict[str, Any]:
        now = int(self.clock())
        job = self._get_visible_job(job_id, owner_id)
        self._raise_if_expired(job, now)
        if job["state"] == TASK_UPDATE_JOB_TERMINAL:
            raise TaskUpdateJobConflictError("Task update job is already terminal")
        if job["state"] == TASK_UPDATE_JOB_LEASED and job.get("lease_expires_at", 0) > now:
            if job.get("lease_device_hash") != device_hash:
                raise TaskUpdateJobConflictError("Task update job is leased by another device")
            return self._claim_response(job)

        job["state"] = TASK_UPDATE_JOB_LEASED
        job["lease_token"] = secrets.token_urlsafe(24)
        job["lease_generation"] = int(job.get("lease_generation") or 0) + 1
        job["lease_device_hash"] = device_hash
        job["lease_expires_at"] = now + self.lease_ttl_seconds
        return self._claim_response(job)

    def persist_job(
        self,
        *,
        job_id: str,
        owner_id: str,
        device_hash: str,
        lease_token: str,
        lease_generation: int,
        expected_task_version: int,
        encrypted_task_payload: dict[str, Any],
        encrypted_task_event_message: str | None,
    ) -> dict[str, Any]:
        now = int(self.clock())
        job = self._get_visible_job(job_id, owner_id)
        if job["state"] == TASK_UPDATE_JOB_TERMINAL:
            return self._terminal_idempotent_response(job, encrypted_task_payload, encrypted_task_event_message)
        self._raise_if_expired(job, now)
        self._validate_payload_is_client_encrypted(encrypted_task_payload)
        if job["state"] != TASK_UPDATE_JOB_LEASED:
            raise TaskUpdateJobConflictError("Task update job has no active lease")
        if job.get("lease_device_hash") != device_hash:
            raise TaskUpdateJobConflictError("Task update job lease belongs to another device")
        if job.get("lease_token") != lease_token or int(job.get("lease_generation") or 0) != int(lease_generation):
            raise TaskUpdateJobConflictError("Task update job lease is stale")
        if int(expected_task_version) != int(job["expected_task_version"]):
            raise TaskUpdateJobConflictError("Task update job expected task version is stale")
        committed_task_version = encrypted_task_payload.get("version")
        if committed_task_version is None:
            raise TaskUpdateJobConflictError("Task update job committed task version is required")

        job["state"] = TASK_UPDATE_JOB_TERMINAL
        job["client_encrypted_payload"] = deepcopy(encrypted_task_payload)
        job["encrypted_task_event_message"] = encrypted_task_event_message
        job["committed_task_version"] = int(committed_task_version)
        job["committed_at"] = now
        return self._terminal_response(job)

    def _get_visible_job(self, job_id: str, owner_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job or job.get("owner_id") != owner_id:
            raise TaskUpdateJobNotFoundError("Task update job not found")
        return job

    @staticmethod
    def _raise_if_expired(job: dict[str, Any], now: int) -> None:
        if int(job.get("expires_at") or 0) <= now:
            raise TaskUpdateJobNotFoundError("Task update job expired")

    @staticmethod
    def _validate_payload_is_client_encrypted(payload: dict[str, Any]) -> None:
        for key in payload:
            if key in ALLOWED_CLIENT_PAYLOAD_SAFE_KEYS or key.startswith("encrypted_"):
                continue
            raise ValueError("Task update job payload contains plaintext or unsupported field")

    @staticmethod
    def _claim_response(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": job["job_id"],
            "task_id": job["task_id"],
            "chat_id": job.get("chat_id"),
            "state": job["state"],
            "lease_token": job["lease_token"],
            "lease_generation": job["lease_generation"],
            "lease_expires_at": job["lease_expires_at"],
            "working_copy_ref": job["working_copy_ref"],
            "expected_task_version": job["expected_task_version"],
            "task_key_version": job["task_key_version"],
        }

    def _terminal_idempotent_response(
        self,
        job: dict[str, Any],
        encrypted_task_payload: dict[str, Any],
        encrypted_task_event_message: str | None,
    ) -> dict[str, Any]:
        if job.get("client_encrypted_payload") != encrypted_task_payload:
            raise TaskUpdateJobConflictError("Task update job already committed different encrypted payload")
        if job.get("encrypted_task_event_message") != encrypted_task_event_message:
            raise TaskUpdateJobConflictError("Task update job already committed different event message")
        return self._terminal_response(job)

    @staticmethod
    def _terminal_response(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": job["job_id"],
            "task_id": job["task_id"],
            "state": TASK_UPDATE_JOB_TERMINAL,
            "committed_task_version": job["committed_task_version"],
        }
