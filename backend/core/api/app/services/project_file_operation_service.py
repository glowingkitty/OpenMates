"""Bounded client-executed Project file operation coordination.

Only routing/state metadata is durable for the episode. Tool arguments and
results are kept in the existing transient inference cache and are removed on
completion or the 20-minute boundary. No server-side Project key or plaintext
fallback exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import posixpath
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any


PROJECT_FILE_OPERATION_CAPABILITY = "project_file_jobs"
PROJECT_FILE_OPERATION_WAIT_EMAIL_SECONDS = 10 * 60
PROJECT_FILE_OPERATION_PAUSE_SECONDS = 20 * 60
PROJECT_FILE_OPERATION_LEASE_SECONDS = 90
PROJECT_FILE_OPERATION_METADATA_TTL_SECONDS = 24 * 60 * 60
PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS = PROJECT_FILE_OPERATION_PAUSE_SECONDS + 60
PROJECT_FILE_OPERATION_RESULT_MAX_BYTES = 512 * 1024
PROJECT_FILE_OPERATION_ARGUMENT_MAX_BYTES = 512 * 1024
PROJECT_FILE_CONFLICT_RECOVERY_LIMIT = 3
PROJECT_FILE_OPERATIONS = {"list", "search", "read_text", "create_file", "update_file"}
PROJECT_FILE_MUTATIONS = {"create_file", "update_file"}
_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class ProjectFileOperationError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class ProjectFileOperationService:
    """Create, lease, and settle one client-executed file operation."""

    def __init__(self, cache_service: Any) -> None:
        self.cache = cache_service
        lock = getattr(cache_service, "_project_file_operation_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(cache_service, "_project_file_operation_lock", lock)
        self._lock = lock

    async def create_operation(
        self,
        *,
        user_id: str,
        chat_id: str,
        project_focus: dict[str, Any],
        operation: str,
        arguments: dict[str, Any],
        continuation_task_id: str,
        message_id: str | None = None,
        operation_id: str | None = None,
        publish: bool = True,
        now: int | None = None,
    ) -> dict[str, Any]:
        if operation not in PROJECT_FILE_OPERATIONS:
            raise ProjectFileOperationError("unsupported_operation")
        project_id = str(project_focus.get("project_id") or "")
        focus_id = str(project_focus.get("focus_id") or "")
        source_id = project_focus.get("source_id")
        if not project_id or not focus_id:
            raise ProjectFileOperationError("project_focus_required", status_code=403)
        if source_id is not None and (not isinstance(source_id, str) or not source_id or len(source_id) > 128):
            raise ProjectFileOperationError("invalid_project_source")
        self._validate_arguments(operation, arguments)
        created_at = int(time.time()) if now is None else int(now)
        operation_id = operation_id or str(uuid.uuid4())
        owner_hash = _hash(user_id)
        if operation in PROJECT_FILE_MUTATIONS and message_id:
            conflict_count = await self._get_conflict_count(
                owner_hash=owner_hash,
                chat_id=chat_id,
                message_id=message_id,
                project_id=project_id,
                source_id=source_id,
                path=str(arguments["path"]),
            )
            if conflict_count >= PROJECT_FILE_CONFLICT_RECOVERY_LIMIT:
                raise ProjectFileOperationError(
                    "conflict_recovery_budget_exhausted", status_code=409
                )
        episode_key = self._episode_key(
            owner_hash, chat_id, message_id or operation_id
        )
        episode = await self.cache.get(episode_key)
        if not isinstance(episode, dict) or created_at >= int(episode.get("pause_at") or 0):
            episode = {
                "episode_id": str(uuid.uuid4()),
                "wait_started_at": created_at,
                "email_due_at": created_at + PROJECT_FILE_OPERATION_WAIT_EMAIL_SECONDS,
                "pause_at": created_at + PROJECT_FILE_OPERATION_PAUSE_SECONDS,
                "email_sent": False,
            }
            await self.cache.set(
                episode_key,
                episode,
                ttl=PROJECT_FILE_OPERATION_METADATA_TTL_SECONDS,
            )
        episode_id = str(episode["episode_id"])
        job = {
            "protocol_version": 1,
            "operation_id": operation_id,
            "episode_id": episode_id,
            "owner_hash": owner_hash,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "project_id": project_id,
            "focus_id": focus_id,
            "team_id": project_focus.get("team_id"),
            "source_id": source_id,
            "operation": operation,
            "state": "WAITING_FOR_EXECUTOR",
            "created_at": created_at,
            "wait_started_at": int(episode["wait_started_at"]),
            "email_due_at": int(episode["email_due_at"]),
            "pause_at": int(episode["pause_at"]),
            "email_sent": bool(episode.get("email_sent")),
            "lease_generation": 0,
            "continuation_task_id": continuation_task_id,
        }
        await self.cache.set(
            self._job_key(owner_hash, operation_id),
            job,
            ttl=PROJECT_FILE_OPERATION_METADATA_TTL_SECONDS,
        )
        await self.cache.set(
            self._payload_key(owner_hash, operation_id),
            {"episode_id": episode_id, "arguments": arguments},
            ttl=PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS,
        )
        await self._append_index(owner_hash, operation_id)
        if publish:
            await self.publish_available(job)
        return self.public_summary(job)

    async def publish_available(self, job: dict[str, Any]) -> bool:
        if job.get("state") in {"COMPLETED", "PAUSED_REQUIRES_EXPLICIT_RESUME"}:
            return False
        return bool(
            await self.cache.publish_event(
                f"user_updates::{job['owner_hash']}",
                {
                    "event_for_client": "project_file_operation_available",
                    "user_id_uuid": job["user_id"],
                    "payload": self.public_summary(job),
                },
            )
        )

    async def list_available(self, *, user_id: str, chat_id: str, now: int | None = None) -> list[dict[str, Any]]:
        current = int(time.time()) if now is None else int(now)
        owner_hash = _hash(user_id)
        results: list[dict[str, Any]] = []
        for operation_id in list(await self.cache.get(self._index_key(owner_hash)) or []):
            job = await self.cache.get(self._job_key(owner_hash, str(operation_id)))
            if not isinstance(job, dict) or job.get("chat_id") != chat_id:
                continue
            if int(job.get("pause_at") or 0) <= current:
                await self.pause_if_due(user_id=user_id, operation_id=str(operation_id), episode_id=str(job.get("episode_id") or ""), now=current)
                continue
            if job.get("state") in {"WAITING_FOR_EXECUTOR", "LEASED", "AWAITING_APPROVAL"}:
                results.append(self.public_summary(job))
        return results

    async def claim(
        self,
        *,
        user_id: str,
        device_fingerprint_hash: str,
        operation_id: str,
        chat_id: str,
        project_id: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        current = int(time.time()) if now is None else int(now)
        owner_hash = _hash(user_id)
        async with self._state_lock(owner_hash, operation_id):
            job = await self._require_job(owner_hash, operation_id)
            self._require_scope(job, chat_id, project_id)
            if job.get("state") == "COMPLETED":
                raise ProjectFileOperationError("operation_already_completed", status_code=409)
            if current >= int(job["pause_at"]):
                await self._pause_locked(job, current)
                raise ProjectFileOperationError("paused_requires_explicit_resume", status_code=409)
            if job.get("state") == "COMPLETED":
                raise ProjectFileOperationError("operation_already_completed", status_code=409)
            lease_active = job.get("state") in {"LEASED", "AWAITING_APPROVAL"} and int(job.get("lease_expires_at") or 0) > current
            if lease_active and job.get("lease_device_hash") != device_fingerprint_hash:
                raise ProjectFileOperationError("operation_already_claimed", status_code=409)
            if not lease_active:
                job["lease_generation"] = int(job.get("lease_generation") or 0) + 1
                job["lease_token"] = secrets.token_urlsafe(32)
                job["lease_device_hash"] = device_fingerprint_hash
            job["state"] = "LEASED"
            job["lease_expires_at"] = current + PROJECT_FILE_OPERATION_LEASE_SECONDS
            await self._save_job(job)
            payload = await self.cache.get(self._payload_key(owner_hash, operation_id))
            if not isinstance(payload, dict) or payload.get("episode_id") != job.get("episode_id"):
                raise ProjectFileOperationError("operation_payload_expired", status_code=410)
            return {
                **self.public_summary(job),
                "lease_token": job["lease_token"],
                "lease_generation": job["lease_generation"],
                "lease_expires_at": job["lease_expires_at"],
                "arguments": payload.get("arguments") or {},
            }

    async def settle(
        self,
        *,
        user_id: str,
        device_fingerprint_hash: str,
        operation_id: str,
        chat_id: str,
        project_id: str,
        lease_token: str,
        lease_generation: int,
        status: str,
        result: dict[str, Any],
        now: int | None = None,
    ) -> dict[str, Any]:
        current = int(time.time()) if now is None else int(now)
        owner_hash = _hash(user_id)
        if len(str(result).encode("utf-8")) > PROJECT_FILE_OPERATION_RESULT_MAX_BYTES:
            raise ProjectFileOperationError("operation_result_too_large")
        async with self._state_lock(owner_hash, operation_id):
            job = await self._require_job(owner_hash, operation_id)
            self._require_scope(job, chat_id, project_id)
            if status not in {
                "completed",
                "conflict",
                "failed",
                "awaiting_approval",
                "waiting_for_executor",
            }:
                raise ProjectFileOperationError("invalid_operation_result")
            if job.get("operation") in PROJECT_FILE_MUTATIONS and status == "completed":
                commitment = result.get("proposal_commitment")
                if not isinstance(commitment, str) or len(commitment) < 32:
                    raise ProjectFileOperationError("proposal_commitment_required")
                retained_commitment = job.get("proposal_commitment")
                if retained_commitment and commitment != retained_commitment:
                    raise ProjectFileOperationError("proposal_commitment_mismatch", status_code=409)
            if job.get("state") == "COMPLETED":
                replay_matches = (
                    job.get("completed_lease_device_hash") == device_fingerprint_hash
                    and job.get("completed_lease_token_hash") == _hash(lease_token)
                    and int(job.get("completed_lease_generation") or 0) == int(lease_generation)
                    and job.get("result_status") == status
                )
                if not replay_matches:
                    raise ProjectFileOperationError("operation_already_completed", status_code=409)
                return {"terminal": True, "replayed": True, "job": job, "result": result}
            if job.get("state") == "PAUSED_REQUIRES_EXPLICIT_RESUME":
                return await self._record_late_result_locked(
                    job=job,
                    device_fingerprint_hash=device_fingerprint_hash,
                    lease_token=lease_token,
                    lease_generation=lease_generation,
                    status=status,
                    result=result,
                    now=current,
                )
            if current >= int(job["pause_at"]):
                await self._pause_locked(job, current)
                return await self._record_late_result_locked(
                    job=job,
                    device_fingerprint_hash=device_fingerprint_hash,
                    lease_token=lease_token,
                    lease_generation=lease_generation,
                    status=status,
                    result=result,
                    now=current,
                )
            if (
                job.get("lease_device_hash") != device_fingerprint_hash
                or job.get("lease_token") != lease_token
                or int(job.get("lease_generation") or 0) != int(lease_generation)
                or int(job.get("lease_expires_at") or 0) <= current
            ):
                raise ProjectFileOperationError("operation_lease_stale", status_code=409)
            if status == "waiting_for_executor":
                reason = result.get("reason")
                if reason not in {
                    "source_offline",
                    "protocol_timeout",
                    "file_key_unavailable",
                }:
                    raise ProjectFileOperationError("invalid_waiting_reason")
                job["state"] = "WAITING_FOR_EXECUTOR"
                job["last_wait_reason"] = reason
                job["last_wait_at"] = current
                job.pop("lease_token", None)
                job.pop("lease_device_hash", None)
                job.pop("lease_expires_at", None)
                await self._save_job(job)
                return {
                    "terminal": False,
                    "deferred": True,
                    "job": job,
                    "result": {"reason": reason},
                }
            if status == "awaiting_approval":
                if job.get("operation") not in PROJECT_FILE_MUTATIONS:
                    raise ProjectFileOperationError("approval_not_supported_for_read")
                job["state"] = "AWAITING_APPROVAL"
                job["proposal_commitment"] = str(result.get("proposal_commitment") or "")[:256]
                # Approval is client-owned. Release the executor lease; after
                # explicit REST approval the client must claim again, causing a
                # fresh authority/current-chat check before execution.
                job.pop("lease_token", None)
                job.pop("lease_device_hash", None)
                job.pop("lease_expires_at", None)
                await self._save_job(job)
                return {"terminal": False, "job": job, "result": result}
            if status == "conflict" and job.get("operation") in PROJECT_FILE_MUTATIONS:
                payload = await self.cache.get(self._payload_key(owner_hash, operation_id))
                arguments = payload.get("arguments") if isinstance(payload, dict) else None
                path = arguments.get("path") if isinstance(arguments, dict) else None
                if isinstance(path, str) and job.get("message_id"):
                    conflict_count = await self._increment_conflict_count(
                        owner_hash=owner_hash,
                        chat_id=str(job["chat_id"]),
                        message_id=str(job["message_id"]),
                        project_id=str(job["project_id"]),
                        source_id=job.get("source_id"),
                        path=path,
                    )
                    result = {
                        **result,
                        "conflict_recovery_attempt": conflict_count,
                        "conflict_recovery_remaining": max(
                            0, PROJECT_FILE_CONFLICT_RECOVERY_LIMIT - conflict_count
                        ),
                        "conflict_budget_exhausted": (
                            conflict_count >= PROJECT_FILE_CONFLICT_RECOVERY_LIMIT
                        ),
                    }
            job["state"] = "COMPLETED"
            job["completed_at"] = current
            job["result_status"] = status
            job["completed_lease_device_hash"] = device_fingerprint_hash
            job["completed_lease_token_hash"] = _hash(lease_token)
            job["completed_lease_generation"] = int(lease_generation)
            job.pop("lease_token", None)
            await self._save_job(job)
            await self.cache.delete(self._payload_key(owner_hash, operation_id))
            await self._remove_index(owner_hash, operation_id)
            return {"terminal": True, "replayed": False, "job": job, "result": result}

    async def mark_email_sent(self, *, user_id: str, operation_id: str, episode_id: str, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        owner_hash = _hash(user_id)
        async with self._state_lock(owner_hash, operation_id):
            job = await self._require_job(owner_hash, operation_id)
            if job.get("episode_id") != episode_id or job.get("email_sent"):
                return False
            episode_key = self._episode_key(
                owner_hash,
                str(job["chat_id"]),
                str(job.get("message_id") or operation_id),
            )
            episode = await self.cache.get(episode_key)
            if isinstance(episode, dict) and episode.get("email_sent"):
                job["email_sent"] = True
                await self._save_job(job)
                return False
            if job.get("state") == "LEASED" and int(job.get("lease_expires_at") or 0) <= current:
                job["state"] = "WAITING_FOR_EXECUTOR"
                job.pop("lease_token", None)
                job.pop("lease_device_hash", None)
                job.pop("lease_expires_at", None)
            if job.get("state") != "WAITING_FOR_EXECUTOR" or current < int(job.get("email_due_at") or 0) or current >= int(job.get("pause_at") or 0):
                return False
            job["email_sent"] = True
            await self._save_job(job)
            if isinstance(episode, dict):
                episode["email_sent"] = True
                await self.cache.set(
                    episode_key,
                    episode,
                    ttl=PROJECT_FILE_OPERATION_METADATA_TTL_SECONDS,
                )
            return True

    async def reject_approval(
        self,
        *,
        user_id: str,
        operation_id: str,
        chat_id: str,
        project_id: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        """Finish an always-ask operation immediately after explicit rejection."""
        current = int(time.time()) if now is None else int(now)
        owner_hash = _hash(user_id)
        async with self._state_lock(owner_hash, operation_id):
            job = await self._require_job(owner_hash, operation_id)
            self._require_scope(job, chat_id, project_id)
            if job.get("state") == "COMPLETED" and job.get("result_status") == "user_declined":
                return {"job": job, "replayed": True}
            if current >= int(job["pause_at"]):
                await self._pause_locked(job, current)
                raise ProjectFileOperationError("paused_requires_explicit_resume", status_code=409)
            if job.get("state") != "AWAITING_APPROVAL":
                raise ProjectFileOperationError("operation_not_awaiting_approval", status_code=409)
            job["state"] = "COMPLETED"
            job["completed_at"] = current
            job["result_status"] = "user_declined"
            await self._save_job(job)
            await self.cache.delete(self._payload_key(owner_hash, operation_id))
            await self._remove_index(owner_hash, operation_id)
            return {"job": job, "replayed": False}

    async def pause_if_due(self, *, user_id: str, operation_id: str, episode_id: str, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        owner_hash = _hash(user_id)
        async with self._state_lock(owner_hash, operation_id):
            job = await self._require_job(owner_hash, operation_id)
            if job.get("episode_id") != episode_id or job.get("state") == "COMPLETED":
                return False
            if current < int(job.get("pause_at") or 0):
                return False
            await self._pause_locked(job, current)
            return True

    async def get_job(self, *, user_id: str, operation_id: str) -> dict[str, Any]:
        return await self._require_job(_hash(user_id), operation_id)

    async def republish_for_chat(self, *, user_id: str, chat_id: str, now: int | None = None) -> int:
        """Republish still-live operations after a capable chat reconnect."""
        jobs = await self.list_available(user_id=user_id, chat_id=chat_id, now=now)
        published = 0
        for summary in jobs:
            job = await self._require_job(_hash(user_id), str(summary["operation_id"]))
            if await self.publish_available(job):
                published += 1
        return published

    async def _pause_locked(self, job: dict[str, Any], now: int) -> None:
        lease_token = job.get("lease_token")
        if isinstance(lease_token, str) and lease_token:
            # Retain only enough opaque metadata to authenticate a result that
            # crossed the fixed 20-minute boundary in flight. Never retain its
            # plaintext result, and never resume inference from that callback.
            job["paused_lease_token_hash"] = _hash(lease_token)
            job["paused_lease_device_hash"] = job.get("lease_device_hash")
            job["paused_lease_generation"] = int(job.get("lease_generation") or 0)
        job["state"] = "PAUSED_REQUIRES_EXPLICIT_RESUME"
        job["paused_at"] = now
        job.pop("lease_token", None)
        job.pop("lease_device_hash", None)
        job.pop("lease_expires_at", None)
        await self._save_job(job)
        await self.cache.delete(self._payload_key(job["owner_hash"], job["operation_id"]))
        await self._remove_index(job["owner_hash"], job["operation_id"])
        await self.cache.publish_event(
            f"user_updates::{job['owner_hash']}",
            {
                "event_for_client": "project_file_operation_paused",
                "user_id_uuid": job["user_id"],
                "payload": {**self.public_summary(job), "reason": "paused_requires_explicit_resume"},
            },
        )

    async def _record_late_result_locked(
        self,
        *,
        job: dict[str, Any],
        device_fingerprint_hash: str,
        lease_token: str,
        lease_generation: int,
        status: str,
        result: dict[str, Any],
        now: int,
    ) -> dict[str, Any]:
        if status in {"awaiting_approval", "waiting_for_executor"}:
            raise ProjectFileOperationError("paused_requires_explicit_resume", status_code=409)
        matches_paused_lease = (
            job.get("paused_lease_device_hash") == device_fingerprint_hash
            and job.get("paused_lease_token_hash") == _hash(lease_token)
            and int(job.get("paused_lease_generation") or 0) == int(lease_generation)
        )
        if not matches_paused_lease:
            raise ProjectFileOperationError("operation_lease_stale", status_code=409)
        prior_status = job.get("late_result_status")
        if prior_status is not None and prior_status != status:
            raise ProjectFileOperationError("operation_result_conflict", status_code=409)
        job["late_result_status"] = status
        job["late_result_recorded_at"] = int(job.get("late_result_recorded_at") or now)
        await self._save_job(job)
        return {
            "terminal": True,
            "late_after_pause": True,
            "replayed": prior_status == status,
            "job": job,
            "result": result,
        }

    async def _require_job(self, owner_hash: str, operation_id: str) -> dict[str, Any]:
        job = await self.cache.get(self._job_key(owner_hash, operation_id))
        if not isinstance(job, dict) or job.get("owner_hash") != owner_hash:
            raise ProjectFileOperationError("operation_not_found", status_code=404)
        return job

    @staticmethod
    def _require_scope(job: dict[str, Any], chat_id: str, project_id: str) -> None:
        if job.get("chat_id") != chat_id or job.get("project_id") != project_id:
            raise ProjectFileOperationError("operation_scope_mismatch", status_code=403)

    @staticmethod
    def _validate_arguments(operation: str, arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ProjectFileOperationError("invalid_operation_arguments")
        if len(str(arguments).encode("utf-8")) > PROJECT_FILE_OPERATION_ARGUMENT_MAX_BYTES:
            raise ProjectFileOperationError("operation_arguments_too_large")
        path = arguments.get("path")
        if path is not None:
            if not isinstance(path, str) or not path or len(path) > 2048:
                raise ProjectFileOperationError("invalid_project_path")
            normalized = path.replace("\\", "/")
            if normalized.startswith("/") or "\x00" in path or ".." in normalized.split("/"):
                raise ProjectFileOperationError("invalid_project_path")
        if operation == "list" and path is not None and not isinstance(path, str):
            raise ProjectFileOperationError("invalid_list_arguments")
        if operation == "search":
            query = arguments.get("query")
            target = arguments.get("target", "content")
            mode = arguments.get("mode", "literal")
            glob = arguments.get("glob")
            max_results = arguments.get("max_results", 20)
            if (
                not isinstance(query, str)
                or not query.strip()
                or len(query) > 2000
                or any(ord(ch) < 32 for ch in query)
                or target not in {"files", "content"}
                or mode not in {"literal", "regex"}
                or not isinstance(max_results, int)
                or isinstance(max_results, bool)
                or not 1 <= max_results <= 100
            ):
                raise ProjectFileOperationError("invalid_search_arguments")
            if glob is not None:
                normalized_glob = glob.replace("\\", "/") if isinstance(glob, str) else ""
                if (
                    not isinstance(glob, str)
                    or not glob
                    or len(glob) > 512
                    or glob.startswith("!")
                    or glob.startswith("/")
                    or "\\" in glob
                    or any(ord(ch) < 32 for ch in glob)
                    or ".." in normalized_glob.split("/")
                ):
                    raise ProjectFileOperationError("invalid_search_arguments")
        if operation == "read_text" and not isinstance(path, str):
            raise ProjectFileOperationError("invalid_read_text_arguments")
        if operation == "create_file" and (
            arguments.get("expected_base", object()) is not None
            or not isinstance(arguments.get("path"), str)
            or not isinstance(arguments.get("content"), str)
        ):
            raise ProjectFileOperationError("invalid_create_file_arguments")
        if operation == "update_file":
            expected = arguments.get("expected_base")
            if (
                not isinstance(arguments.get("path"), str)
                or not isinstance(arguments.get("patch"), str)
                or not isinstance(expected, str)
                or len(expected) != 64
                or any(ch not in "0123456789abcdef" for ch in expected)
            ):
                raise ProjectFileOperationError("invalid_update_file_arguments")

    def public_summary(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "operation_id": job["operation_id"],
            "chat_id": job["chat_id"],
            "message_id": job.get("message_id"),
            "project_id": job["project_id"],
            "source_id": job.get("source_id"),
            "operation": job["operation"],
            "state": str(job["state"]).lower(),
            "expires_at": job["pause_at"],
        }

    async def _save_job(self, job: dict[str, Any]) -> None:
        await self.cache.set(
            self._job_key(job["owner_hash"], job["operation_id"]),
            job,
            ttl=PROJECT_FILE_OPERATION_METADATA_TTL_SECONDS,
        )

    async def _append_index(self, owner_hash: str, operation_id: str) -> None:
        key = self._index_key(owner_hash)
        values = list(await self.cache.get(key) or [])
        if operation_id not in values:
            values.append(operation_id)
        await self.cache.set(key, values, ttl=PROJECT_FILE_OPERATION_METADATA_TTL_SECONDS)

    async def _remove_index(self, owner_hash: str, operation_id: str) -> None:
        key = self._index_key(owner_hash)
        values = [value for value in list(await self.cache.get(key) or []) if value != operation_id]
        if values:
            await self.cache.set(key, values, ttl=PROJECT_FILE_OPERATION_METADATA_TTL_SECONDS)
        else:
            await self.cache.delete(key)

    @asynccontextmanager
    async def _state_lock(self, owner_hash: str, operation_id: str):
        async with self._lock:
            try:
                client = await self.cache.client
            except (AttributeError, TypeError):
                client = None
            if client is None:
                yield
                return
            key = f"project_file_operation:lock:{owner_hash}:{operation_id}"
            token = secrets.token_urlsafe(24)
            acquired = bool(await client.set(key, token, nx=True, ex=10))
            if not acquired:
                raise ProjectFileOperationError("operation_busy", status_code=503)
            try:
                yield
            finally:
                await client.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)

    @staticmethod
    def _job_key(owner_hash: str, operation_id: str) -> str:
        return f"project_file_operation:job:{owner_hash}:{operation_id}"

    @staticmethod
    def _payload_key(owner_hash: str, operation_id: str) -> str:
        return f"project_file_operation:payload:{owner_hash}:{operation_id}"

    @staticmethod
    def _episode_key(owner_hash: str, chat_id: str, message_id: str) -> str:
        scope = _hash(f"{chat_id}:{message_id}")
        return f"project_file_operation:episode:{owner_hash}:{scope}"

    @staticmethod
    def _conflict_budget_key(
        owner_hash: str,
        chat_id: str,
        message_id: str,
        project_id: str,
        source_id: Any,
        path: str,
    ) -> str:
        normalized_path = posixpath.normpath(path.replace("\\", "/"))
        scope = _hash(
            f"{chat_id}:{message_id}:{project_id}:{source_id or 'hosted'}:{normalized_path}"
        )
        return f"project_file_operation:conflict_budget:{owner_hash}:{scope}"

    async def _get_conflict_count(self, **scope: Any) -> int:
        value = await self.cache.get(self._conflict_budget_key(**scope))
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0

    async def _increment_conflict_count(self, **scope: Any) -> int:
        key = self._conflict_budget_key(**scope)
        count = await self._get_conflict_count(**scope) + 1
        await self.cache.set(
            key,
            count,
            ttl=PROJECT_FILE_OPERATION_METADATA_TTL_SECONDS,
        )
        return count

    @staticmethod
    def _index_key(owner_hash: str) -> str:
        return f"project_file_operation:index:{owner_hash}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
