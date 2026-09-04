#!/usr/bin/env python3
# test-file: scripts/tests/test_sessions_presence_store.py
"""Concurrency-safe ephemeral presence storage for local OpenCode sessions.

The store contains only allowlisted identifiers, states, timestamps, and safe
repository-relative paths. It is intentionally independent from sessions.json,
worktree metadata, edit leases, and deploy locks. See the executable contract in
docs/specs/agent-presence-coordination/spec.yml.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


STORE_VERSION = 1
LIVE_TIMEOUT_SECONDS = 120
DEFAULT_TERMINAL_RETENTION_SECONDS = 24 * 60 * 60
EXECUTION_STATES = {"busy", "retrying", "idle", "stopped", "error", "closed", "unknown"}
ATTENTION_STATES = {"none", "optional", "required_question", "required_permission", "required_both"}
TURN_STATES = {"none", "streaming", "completed", "aborted", "failed"}
CHILD_ROLES = {"unknown", "read_only", "reviewer", "writable"}
QUESTION_CAPABILITIES = {"supported", "unsupported", "unknown"}
CLAIM_ROLES = {"implementation", "reviewer", "read_only"}
IDENTIFIER_FIELDS = {
    "session_id",
    "top_level_session_id",
    "parent_id",
    "repository_session_id",
    "turn_id",
    "user_turn_id",
    "source_id",
}
TIMESTAMP_FIELDS = {"updated_at", "heartbeat_at"}


class PresenceStoreError(RuntimeError):
    """Visible ephemeral-store failure that must not weaken durable guards."""


class TaskClaimConflict(PresenceStoreError):
    """Raised when a second live implementation owner claims the same task."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso_after(value: str, seconds: int) -> str:
    return (_parse_timestamp(value) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_identifier(value: object, *, maximum: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or len(candidate) > maximum or any(ord(char) < 32 for char in candidate):
        return ""
    return candidate


def _safe_id_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({_safe_identifier(item) for item in value if _safe_identifier(item)})[:100]


def normalize_presence_path(raw_path: object, project_root: Path) -> str | None:
    """Return a traversal-safe repository-relative path within project_root."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    try:
        root = project_root.resolve()
        candidate = Path(raw_path)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    return relative.as_posix()


def sanitize_presence_record(raw: object, project_root: Path) -> dict:
    """Build one strict presence record without copying unknown input fields."""
    if not isinstance(raw, dict):
        raise PresenceStoreError("Presence update must be a JSON object")
    session_id = _safe_identifier(raw.get("session_id"))
    source_id = _safe_identifier(raw.get("source_id"))
    if not session_id or not source_id:
        raise PresenceStoreError("Presence update requires safe session_id and source_id values")

    try:
        generation = int(raw.get("generation", 0))
        sequence = int(raw.get("sequence", 0))
    except (TypeError, ValueError) as error:
        raise PresenceStoreError("Presence generation and sequence must be integers") from error
    if generation < 0 or sequence < 0:
        raise PresenceStoreError("Presence generation and sequence must be non-negative")

    execution = raw.get("execution") if raw.get("execution") in EXECUTION_STATES else "unknown"
    attention = raw.get("attention") if raw.get("attention") in ATTENTION_STATES else "none"
    turn = raw.get("turn") if raw.get("turn") in TURN_STATES else "none"
    child_role = raw.get("child_role") if raw.get("child_role") in CHILD_ROLES else "unknown"
    updated_at = _safe_identifier(raw.get("updated_at")) or _utc_now()
    try:
        _parse_timestamp(updated_at)
    except (TypeError, ValueError) as error:
        raise PresenceStoreError("Presence updated_at must be an ISO timestamp") from error

    record = {
        "session_id": session_id,
        "source_id": source_id,
        "generation": generation,
        "sequence": sequence,
        "execution": execution,
        "attention": attention,
        "turn": turn,
        "child_role": child_role,
        "updated_at": updated_at,
        "pending_permission_ids": _safe_id_list(raw.get("pending_permission_ids")),
        "pending_question_ids": _safe_id_list(raw.get("pending_question_ids")),
        "paths": sorted(
            {
                normalized
                for path in raw.get("paths", []) if isinstance(raw.get("paths"), list)
                if (normalized := normalize_presence_path(path, project_root))
            }
        )[:100],
    }
    for field in IDENTIFIER_FIELDS - {"session_id", "source_id"}:
        value = _safe_identifier(raw.get(field))
        if value:
            record[field] = value
    hook_runtime_hash = _safe_identifier(raw.get("hook_runtime_hash"))
    if re.fullmatch(r"[a-f0-9]{64}", hook_runtime_hash):
        record["hook_runtime_hash"] = hook_runtime_hash
    heartbeat = _safe_identifier(raw.get("heartbeat_at"))
    if heartbeat:
        try:
            _parse_timestamp(heartbeat)
        except (TypeError, ValueError) as error:
            raise PresenceStoreError("Presence heartbeat_at must be an ISO timestamp") from error
        record["heartbeat_at"] = heartbeat
    capabilities = raw.get("capabilities")
    question = capabilities.get("question") if isinstance(capabilities, dict) else "unknown"
    record["capabilities"] = {"question": question if question in QUESTION_CAPABILITIES else "unknown"}
    return record


class PresenceStore:
    """Locked atomic store for ephemeral session state and renewable task claims."""

    def __init__(
        self,
        path: str | Path,
        *,
        project_root: str | Path,
        lock_path: str | Path | None = None,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self.path = Path(path)
        self.lock_path = Path(lock_path) if lock_path else self.path.with_suffix(".lock")
        self.project_root = Path(project_root).resolve()
        self.now = now

    def _empty(self, diagnostics: list[dict] | None = None) -> dict:
        return {
            "version": STORE_VERSION,
            "project_root": str(self.project_root),
            "sessions": {},
            "task_claims": {},
            "child_roles": {},
            "diagnostics": diagnostics or [],
        }

    def _load_unlocked(self) -> dict:
        if not self.path.exists():
            return self._empty()
        if self.path.is_symlink():
            return self._empty([{"code": "unsafe_store", "message": "presence store symlinks are rejected"}])
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self._empty([{"code": "corrupt_store", "message": "presence store is unreadable or invalid JSON"}])
        if not isinstance(data, dict) or data.get("version") != STORE_VERSION:
            return self._empty([{"code": "unsupported_store", "message": "presence store version is unsupported"}])
        if data.get("project_root") != str(self.project_root):
            return self._empty([{"code": "project_mismatch", "message": "presence belongs to another canonical project"}])
        if not isinstance(data.get("sessions"), dict) or not isinstance(data.get("task_claims"), dict):
            return self._empty([{"code": "corrupt_store", "message": "presence store schema is invalid"}])
        sanitized = self._empty()
        invalid_records = 0
        for session_id, record in data["sessions"].items():
            try:
                clean = sanitize_presence_record(record, self.project_root)
            except PresenceStoreError:
                invalid_records += 1
                continue
            if clean["session_id"] == session_id:
                sanitized["sessions"][session_id] = clean
            else:
                invalid_records += 1
        for claims in data["task_claims"].values():
            if not isinstance(claims, list):
                invalid_records += 1
                continue
            for claim in claims:
                if not isinstance(claim, dict):
                    invalid_records += 1
                    continue
                spec_path = normalize_presence_path(claim.get("spec_path"), self.project_root)
                task_id = _safe_identifier(claim.get("task_id"))
                owner = _safe_identifier(claim.get("owner_session_id"))
                role = claim.get("role")
                claimed_at = _safe_identifier(claim.get("claimed_at"))
                expires_at = _safe_identifier(claim.get("expires_at"))
                try:
                    _parse_timestamp(claimed_at)
                    _parse_timestamp(expires_at)
                except (TypeError, ValueError):
                    invalid_records += 1
                    continue
                if not spec_path or not task_id or not owner or role not in CLAIM_ROLES:
                    invalid_records += 1
                    continue
                key = f"{spec_path}::{task_id}"
                sanitized["task_claims"].setdefault(key, []).append({
                    "spec_path": spec_path,
                    "task_id": task_id,
                    "owner_session_id": owner,
                    "role": role,
                    "claimed_at": claimed_at,
                    "expires_at": expires_at,
                })
        child_roles = data.get("child_roles", {})
        if isinstance(child_roles, dict):
            for child_id, marker in child_roles.items():
                if not isinstance(marker, dict):
                    invalid_records += 1
                    continue
                child = _safe_identifier(marker.get("session_id"))
                parent = _safe_identifier(marker.get("parent_id"))
                role = marker.get("role")
                updated_at = _safe_identifier(marker.get("updated_at"))
                if child != child_id or not parent or role not in CHILD_ROLES - {"unknown"}:
                    invalid_records += 1
                    continue
                sanitized["child_roles"][child] = {"session_id": child, "parent_id": parent, "role": role, "updated_at": updated_at}
        if invalid_records:
            sanitized["diagnostics"] = [{"code": "invalid_records_removed", "message": f"removed {invalid_records} invalid presence record(s)"}]
        return sanitized

    def _write_unlocked(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.parent.is_symlink() or self.path.is_symlink():
                raise PresenceStoreError("Presence storage path must not be a symlink")
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                    json.dump(data, temporary, sort_keys=True, separators=(",", ":"))
                    temporary.write("\n")
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_name, self.path)
                os.chmod(self.path, 0o600)
            except BaseException:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
                raise
        except PresenceStoreError:
            raise
        except OSError as error:
            raise PresenceStoreError(f"Presence store write failed: {error}") from error

    def _transaction(self, mutator):
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            if self.lock_path.is_symlink():
                raise PresenceStoreError("Presence lock path must not be a symlink")
            with self.lock_path.open("a+", encoding="utf-8") as lock_handle:
                os.chmod(self.lock_path, 0o600)
                fcntl.flock(lock_handle, fcntl.LOCK_EX)
                try:
                    data = self._load_unlocked()
                    result = mutator(data)
                    self._write_unlocked(data)
                    return result
                finally:
                    fcntl.flock(lock_handle, fcntl.LOCK_UN)
        except PresenceStoreError:
            raise
        except OSError as error:
            raise PresenceStoreError(f"Presence store lock failed: {error}") from error

    def _expire(self, data: dict) -> dict:
        """Prune ephemeral state in place before it is persisted again."""
        now_value = self.now()
        now = _parse_timestamp(now_value)
        for session_id, record in list(data["sessions"].items()):
            updated_at = record.get("updated_at")
            try:
                age = (now - _parse_timestamp(updated_at)).total_seconds()
            except (TypeError, ValueError):
                age = DEFAULT_TERMINAL_RETENTION_SECONDS + 1
            if record.get("execution") in {"busy", "retrying"}:
                heartbeat = record.get("heartbeat_at") or updated_at
                try:
                    stale = (now - _parse_timestamp(heartbeat)).total_seconds() > LIVE_TIMEOUT_SECONDS
                except (TypeError, ValueError):
                    stale = True
                if stale and age > DEFAULT_TERMINAL_RETENTION_SECONDS:
                    del data["sessions"][session_id]
                elif stale:
                    record["execution"] = "unknown"
            elif age > DEFAULT_TERMINAL_RETENTION_SECONDS:
                del data["sessions"][session_id]
        for key, claims in list(data["task_claims"].items()):
            active = [claim for claim in claims if claim.get("expires_at", "") > now_value]
            if active:
                data["task_claims"][key] = active
            else:
                del data["task_claims"][key]
        for child_id, marker in list(data["child_roles"].items()):
            try:
                stale = (now - _parse_timestamp(marker.get("updated_at", ""))).total_seconds() > DEFAULT_TERMINAL_RETENTION_SECONDS
            except (TypeError, ValueError):
                stale = True
            if stale:
                del data["child_roles"][child_id]
        return data

    def update(self, raw: object) -> dict:
        record = sanitize_presence_record(raw, self.project_root)

        def apply(data: dict) -> dict:
            self._expire(data)
            existing = data["sessions"].get(record["session_id"], {})
            same_source = existing.get("source_id") == record["source_id"]
            existing_order = (int(existing.get("generation", -1)), int(existing.get("sequence", -1)))
            incoming_order = (record["generation"], record["sequence"])
            if same_source and incoming_order <= existing_order:
                return {"accepted": False, "record": existing}
            data["sessions"][record["session_id"]] = record
            data["diagnostics"] = []
            return {"accepted": True, "record": record}

        return self._transaction(apply)

    def set_child_role(self, session_id: str, parent_id: str, role: str, *, if_unset: bool = False) -> dict:
        if role not in CHILD_ROLES - {"unknown"}:
            raise PresenceStoreError(f"Unsupported child role: {role}")
        child = _safe_identifier(session_id)
        parent = _safe_identifier(parent_id)
        if not child or not parent:
            raise PresenceStoreError("Child role requires safe child and parent session IDs")

        def apply(data: dict) -> dict:
            self._expire(data)
            existing = data["child_roles"].get(child)
            if if_unset and isinstance(existing, dict):
                return existing
            marker = {"session_id": child, "parent_id": parent, "role": role, "updated_at": self.now()}
            data["child_roles"][child] = marker
            return marker

        return self._transaction(apply)

    def snapshot(self, *, expire: bool = True) -> dict:
        data = self._load_unlocked()
        if data.get("project_root") != str(self.project_root):
            return self._empty(data.get("diagnostics"))
        if not expire:
            return data
        return self._expire(data)

    def _claim_key(self, spec_path: str, task_id: str) -> str:
        normalized = normalize_presence_path(spec_path, self.project_root)
        task = _safe_identifier(task_id)
        if not normalized or not task:
            raise PresenceStoreError("Task claim requires a safe repository-relative spec path and task ID")
        return f"{normalized}::{task}"

    def claim_task(self, spec_path: str, task_id: str, owner_session_id: str, *, role: str, ttl_seconds: int) -> dict:
        key = self._claim_key(spec_path, task_id)
        owner = _safe_identifier(owner_session_id)
        if not owner or role not in CLAIM_ROLES or ttl_seconds <= 0:
            raise PresenceStoreError("Task claim owner, role, or TTL is invalid")

        def apply(data: dict) -> dict:
            now = self.now()
            claims = data["task_claims"].setdefault(key, [])
            active = [claim for claim in claims if claim.get("expires_at", "") > now]
            if role == "implementation":
                conflict = next((claim for claim in active if claim.get("role") == "implementation" and claim.get("owner_session_id") != owner), None)
                if conflict:
                    raise TaskClaimConflict(
                        f"Task {task_id} in {spec_path} is already claimed by {conflict['owner_session_id']} until {conflict['expires_at']}"
                    )
                active = [claim for claim in active if not (claim.get("role") == "implementation" and claim.get("owner_session_id") == owner)]
            else:
                active = [claim for claim in active if not (claim.get("role") == role and claim.get("owner_session_id") == owner)]
            claim = {
                "spec_path": key.split("::", 1)[0],
                "task_id": key.split("::", 1)[1],
                "owner_session_id": owner,
                "role": role,
                "claimed_at": now,
                "expires_at": _iso_after(now, ttl_seconds),
            }
            active.append(claim)
            data["task_claims"][key] = active
            return claim

        return self._transaction(apply)

    def renew_task(self, spec_path: str, task_id: str, owner_session_id: str, *, ttl_seconds: int) -> dict:
        key = self._claim_key(spec_path, task_id)
        owner = _safe_identifier(owner_session_id)

        def apply(data: dict) -> dict:
            now = self.now()
            for claim in data["task_claims"].get(key, []):
                if claim.get("owner_session_id") == owner and claim.get("role") == "implementation" and claim.get("expires_at", "") > now:
                    claim["expires_at"] = _iso_after(now, ttl_seconds)
                    return claim
            raise PresenceStoreError(f"No live implementation claim for {owner} on {task_id}")

        return self._transaction(apply)

    def release_task(self, spec_path: str, task_id: str, owner_session_id: str) -> dict:
        key = self._claim_key(spec_path, task_id)
        owner = _safe_identifier(owner_session_id)

        def apply(data: dict) -> dict:
            before = data["task_claims"].get(key, [])
            after = [claim for claim in before if claim.get("owner_session_id") != owner]
            if after:
                data["task_claims"][key] = after
            else:
                data["task_claims"].pop(key, None)
            return {"released": len(before) - len(after), "owner_session_id": owner}

        return self._transaction(apply)
