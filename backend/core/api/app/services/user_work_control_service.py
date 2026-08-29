# backend/core/api/app/services/user_work_control_service.py
#
# Safe work-control semantics for encrypted Plans and Tasks. This service only
# receives routing metadata, statuses, encrypted revision snapshots, and hashes;
# it never decrypts or derives private Plan or Task content.
#
# Spec: docs/specs/opencode-openmates-work-control/spec.yml

import re
import secrets
import time
import uuid
import asyncio
from contextlib import asynccontextmanager
from inspect import isawaitable
from typing import Any, AsyncIterator, Protocol


ITEM_REF_RE = re.compile(r"^(plan|task):([^:]+)$")
OPENCODE_SUB_CHAT_RE = re.compile(r"^opencode:[^:\s]+$")
RESOLVED_ASSUMPTION_STATUSES = {"confirmed", "corrected"}
GRAPH_LOCK_TTL_SECONDS = 30
_RENEW_GRAPH_LOCK_SCRIPT = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
_RELEASE_GRAPH_LOCK_SCRIPT = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


class WorkControlValidationError(ValueError):
    """Raised when a dependency or work gate is invalid."""


class WorkControlPermissionError(PermissionError):
    """Raised when an approval does not originate from a web user session."""


class GraphLockLostError(RuntimeError):
    """Raised before a graph mutation when its fenced Redis lease is lost."""


class GraphMutationLease:
    """Exposes an explicit fail-closed checkpoint before a guarded mutation."""

    def __init__(self) -> None:
        self.lost = False

    async def assert_held(self) -> None:
        if self.lost:
            raise GraphLockLostError("Dependency graph lock was lost before mutation")


def validate_browser_approval(auth_source: str | None, origin: str | None, allowed_origins: set[str]) -> None:
    if auth_source != "session":
        raise WorkControlPermissionError("Plan approval requires an authenticated web user session")
    if not origin or origin not in allowed_origins:
        raise WorkControlPermissionError("Plan approval requires a trusted browser Origin")


def has_required_assumption_evidence(assumption: dict[str, Any]) -> bool:
    """Check required opaque ciphertext fields without inspecting their contents."""
    return bool(assumption.get("encrypted_sources")) and bool(assumption.get("encrypted_evidence_summary"))


def is_resolved_assumption(assumption: dict[str, Any]) -> bool:
    """Resolved statuses remain valid only while their required ciphertext exists."""
    status = str(assumption.get("status") or "unchecked")
    if status == "confirmed":
        return has_required_assumption_evidence(assumption)
    if status == "corrected":
        return has_required_assumption_evidence(assumption) and bool(assumption.get("encrypted_corrected_text"))
    return status == "waived"


def validate_assumption_resolution_evidence(assumption: dict[str, Any]) -> None:
    """Require opaque evidence before recording an assumption as resolved."""
    status = str(assumption.get("status") or "unchecked")
    if status == "confirmed" and not has_required_assumption_evidence(assumption):
        raise WorkControlValidationError("Confirmed assumptions require encrypted_sources and encrypted_evidence_summary")
    if status == "corrected" and not is_resolved_assumption(assumption):
        raise WorkControlValidationError("Corrected assumptions require encrypted_sources, encrypted_evidence_summary, and encrypted_corrected_text")


class WorkControlRepository(Protocol):
    async def get_item(self, ref: str) -> dict[str, Any] | None: ...
    async def list_edges(self) -> list[dict[str, Any]]: ...
    async def create_edge(self, edge: dict[str, Any]) -> dict[str, Any]: ...
    async def delete_edge(self, source_ref: str, target_ref: str) -> bool: ...
    async def list_assumptions(self, plan_id: str) -> list[dict[str, Any]]: ...
    async def list_revisions(self, plan_id: str) -> list[dict[str, Any]]: ...
    async def create_revision(self, plan_id: str, revision: dict[str, Any]) -> dict[str, Any]: ...
    async def approve_revision(self, plan_id: str, revision_id: str, approver_hash: str, approved_at: int) -> None: ...
    async def update_plan(self, plan_id: str, patch: dict[str, Any]) -> dict[str, Any]: ...


class UserWorkControlService:
    """Validates dependency, assumption, and revision metadata without plaintext."""

    def __init__(self, repository: WorkControlRepository):
        self.repository = repository

    async def add_dependency(self, source_ref: str, target_ref: str) -> dict[str, Any]:
        source = await self._require_item(source_ref)
        async with self._graph_lock(source) as lease:
            await lease.assert_held()
            return await self._add_dependency(source_ref, target_ref)

    async def _add_dependency(self, source_ref: str, target_ref: str) -> dict[str, Any]:
        source_kind, source_id = self._parse_ref(source_ref)
        target_kind, target_id = self._parse_ref(target_ref)
        if source_ref == target_ref:
            raise WorkControlValidationError("dependency cannot reference itself")
        source = await self._require_item(source_ref)
        target = await self._require_item(target_ref)
        dependency_project_hash = self._validate_shared_scope(source, target)
        edges = await self.repository.list_edges()
        if any(edge.get("source_ref") == source_ref and edge.get("target_ref") == target_ref for edge in edges):
            raise WorkControlValidationError("duplicate dependency")
        if self._would_cycle(edges, source_ref, target_ref):
            raise WorkControlValidationError("dependency would create a cycle")
        return await self.repository.create_edge({
            "edge_id": str(uuid.uuid4()),
            "source_ref": source_ref,
            "source_kind": source_kind,
            "source_id": source_id,
            "target_ref": target_ref,
            "target_kind": target_kind,
            "target_id": target_id,
            "hashed_user_id": source.get("hashed_user_id"),
            "hashed_team_id": source.get("hashed_team_id"),
            "dependency_project_hash": dependency_project_hash,
        })

    async def remove_dependency(self, source_ref: str, target_ref: str) -> None:
        source = await self._require_item(source_ref)
        async with self._graph_lock(source) as lease:
            await lease.assert_held()
            if not await self.repository.delete_edge(source_ref, target_ref):
                raise WorkControlValidationError("Dependency not found")

    async def dependency_blockers(self, source_ref: str) -> list[dict[str, str]]:
        blockers: list[dict[str, str]] = []
        for edge in await self.repository.list_edges():
            if edge.get("source_ref") != source_ref:
                continue
            target_ref = str(edge.get("target_ref"))
            target = await self._require_item(target_ref)
            if not self._is_satisfied(target):
                blockers.append({"ref": target_ref, "status": str(target.get("status") or "unknown")})
        return blockers

    async def dependency_read_model(self, source_ref: str) -> dict[str, Any]:
        """Return dependency routing metadata without encrypted record fields."""
        await self._require_item(source_ref)
        dependencies: list[dict[str, Any]] = []
        for edge in await self.repository.list_edges():
            if edge.get("source_ref") != source_ref:
                continue
            target_ref = str(edge.get("target_ref"))
            target = await self._require_item(target_ref)
            dependencies.append({
                "edge_id": edge.get("edge_id"),
                "source_ref": source_ref,
                "target_ref": target_ref,
                "target_kind": target.get("kind"),
                "target_id": target.get("id"),
                "target_status": target.get("status"),
                "satisfied": self._is_satisfied(target),
            })
        return {"dependencies": dependencies, "blockers": await self.dependency_blockers(source_ref)}

    async def approval_read_model(self, plan_id: str) -> dict[str, Any]:
        """Expose only approval metadata required by first-party review clients."""
        plan = await self._require_item(f"plan:{plan_id}")
        return {
            "plan_id": plan_id,
            "approval_state": plan.get("approval_state") or "unapproved",
            "submitted_revision_id": plan.get("submitted_revision_id"),
            "approved_revision_id": plan.get("approved_revision_id"),
            "approved_at": plan.get("approved_at"),
        }

    async def ensure_deletable(self, target_ref: str) -> None:
        linked = [
            edge for edge in await self.repository.list_edges()
            if edge.get("source_ref") == target_ref or edge.get("target_ref") == target_ref
        ]
        if linked:
            references = ", ".join(
                str(edge.get("source_ref") if edge.get("target_ref") == target_ref else edge.get("target_ref"))
                for edge in linked
            )
            raise WorkControlValidationError(f"Cannot delete item with dependencies: {references}")

    @asynccontextmanager
    async def delete_guard(self, target_ref: str) -> AsyncIterator[GraphMutationLease]:
        """Hold the owner graph lock from dependency validation through deletion."""
        target = await self._require_item(target_ref)
        async with self._graph_lock(target) as lease:
            await self.ensure_deletable(target_ref)
            await lease.assert_held()
            yield lease

    @asynccontextmanager
    async def restore_delete_guard(self, history_service: Any, *, user_id: str, object_type: str, object_id: str, entry_id: str, state: str) -> AsyncIterator[GraphMutationLease]:
        """Guard a history restore only when its selected state deletes the item."""
        if object_type not in {"plan", "task"}:
            yield GraphMutationLease()
            return
        entry = await history_service.get_object_entry(user_id, object_type=object_type, object_id=object_id, entry_id=entry_id)
        if not entry:
            raise ValueError("Workspace history entry not found")
        if history_service.snapshot_for_entry_state(entry, state) is not None:
            yield GraphMutationLease()
            return
        async with self.delete_guard(f"{object_type}:{object_id}") as lease:
            yield lease

    async def ensure_unlinked(self, ref: str) -> None:
        if any(edge.get("source_ref") == ref or edge.get("target_ref") == ref for edge in await self.repository.list_edges()):
            raise WorkControlValidationError("Cannot move item while it has dependencies")

    async def ensure_restore_deletable(
        self,
        history_service: Any,
        *,
        user_id: str,
        object_type: str,
        object_id: str,
        entry_id: str,
        state: str,
    ) -> None:
        """Reject history restores that would delete a still-linked Plan or Task."""
        if object_type not in {"plan", "task"}:
            return
        entry = await history_service.get_object_entry(
            user_id, object_type=object_type, object_id=object_id, entry_id=entry_id
        )
        if not entry:
            raise ValueError("Workspace history entry not found")
        if history_service.snapshot_for_entry_state(entry, state) is None:
            await self.ensure_deletable(f"{object_type}:{object_id}")

    async def invalidate_for_task_membership_change(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        *,
        updated_at: int,
    ) -> None:
        plan_ids = {
            str(item.get("plan_id"))
            for item in (before, after)
            if item and item.get("plan_id")
        }
        for plan_id in plan_ids:
            await self.invalidate_for_material_edit(plan_id, updated_at=updated_at)

    @asynccontextmanager
    async def _graph_lock(self, source: dict[str, Any]) -> AsyncIterator[GraphMutationLease]:
        lock = getattr(self.repository, "graph_lock", None)
        if lock is None:
            yield GraphMutationLease()
            return
        async with lock(str(source.get("hashed_user_id") or ""), source.get("hashed_team_id")) as lease:
            yield lease if isinstance(lease, GraphMutationLease) else GraphMutationLease()

    def validate_linked_sub_chat_id(self, linked_sub_chat_id: str) -> str:
        if OPENCODE_SUB_CHAT_RE.fullmatch(linked_sub_chat_id):
            return linked_sub_chat_id
        try:
            return str(uuid.UUID(linked_sub_chat_id))
        except (ValueError, AttributeError) as exc:
            raise WorkControlValidationError("linked_sub_chat_id must be a native UUID or opencode:<opaque-id>") from exc

    async def execution_blockers(self, plan_id: str, *, phase: str = "task_execution") -> list[dict[str, str]]:
        required_before = {"completion"} if phase == "completion" else {"implementation", "task_execution"}
        blockers: list[dict[str, str]] = []
        for assumption in await self.repository.list_assumptions(plan_id):
            if assumption.get("required_before") not in required_before:
                continue
            linked_sub_chat_id = assumption.get("linked_sub_chat_id")
            if not linked_sub_chat_id:
                blockers.append({"kind": "assumption", "id": str(assumption.get("assumption_id")), "status": "missing_investigation"})
                continue
            self.validate_linked_sub_chat_id(str(linked_sub_chat_id))
            status = str(assumption.get("status") or "unchecked")
            if not self._has_required_assumption_evidence(assumption, status):
                blockers.append({"kind": "assumption", "id": str(assumption.get("assumption_id")), "status": status})
        return blockers

    async def plan_execution_blockers(self, plan_id: str) -> list[dict[str, str]]:
        plan = await self._require_item(f"plan:{plan_id}")
        blockers: list[dict[str, str]] = []
        if plan.get("approval_state") != "approved" or not plan.get("approved_revision_id"):
            blockers.append({"kind": "approval", "id": plan_id, "status": str(plan.get("approval_state") or "unapproved")})
        else:
            revisions = await self.repository.list_revisions(plan_id)
            approved_revision_id = str(plan["approved_revision_id"])
            revision = next((item for item in revisions if item.get("revision_id") == approved_revision_id), None)
            if not self._is_current_approved_revision({**plan, "plan_id": plan_id}, revision):
                blockers.append({"kind": "approval", "id": plan_id, "status": "invalid_revision"})
        blockers.extend(await self.dependency_blockers(f"plan:{plan_id}"))
        blockers.extend(await self.execution_blockers(plan_id))
        return blockers

    async def submit_revision(self, plan_id: str, fingerprint: str, encrypted_snapshot: str, *, created_at: int) -> dict[str, Any]:
        if not fingerprint or not encrypted_snapshot:
            raise WorkControlValidationError("Revision requires fingerprint and encrypted snapshot")
        plan = await self._require_item(f"plan:{plan_id}")
        if plan.get("hashed_team_id"):
            raise WorkControlValidationError("Team work-control revisions are not supported in this slice")
        async with self._revision_lock(plan):
            revisions = await self.repository.list_revisions(plan_id)
            if any(revision.get("fingerprint") == fingerprint for revision in revisions):
                raise WorkControlValidationError("Revisions are immutable and fingerprint already exists")
            revision = {
                "revision_id": str(uuid.uuid4()),
                "revision_number": len(revisions) + 1,
                "fingerprint": fingerprint,
                "encrypted_snapshot": encrypted_snapshot,
                "created_at": created_at,
                "approval_state": "submitted",
                "hashed_user_id": plan.get("hashed_user_id"),
                "hashed_team_id": plan.get("hashed_team_id"),
                "linked_project_hashes": list(plan.get("linked_project_hashes") or []),
            }
            created = await self.repository.create_revision(plan_id, revision)
            await self.repository.update_plan(plan_id, {
                "approval_state": "awaiting_review", "submitted_revision_id": created["revision_id"],
                "approved_revision_id": None, "approved_at": None, "approved_by_hash": None,
            })
            return created

    async def approve_revision(self, plan_id: str, revision_id: str, *, approver_hash: str, approved_at: int | None = None) -> dict[str, Any]:
        plan = await self._require_item(f"plan:{plan_id}")
        async with self._revision_lock(plan):
            plan = await self._require_item(f"plan:{plan_id}")
            revisions = await self.repository.list_revisions(plan_id)
            revision = next((item for item in revisions if item.get("revision_id") == revision_id), None)
            if self._is_current_approved_revision({**plan, "plan_id": plan_id}, revision):
                return plan
            if self._is_repairable_approved_revision({**plan, "plan_id": plan_id}, revision):
                await self.repository.approve_revision(plan_id, revision_id, approver_hash, int(plan["approved_at"]))
                return plan
            if plan.get("approval_state") != "awaiting_review" or plan.get("submitted_revision_id") != revision_id:
                raise WorkControlValidationError("Plan revision is not the current submitted revision")
            if not self._is_submitted_revision({**plan, "plan_id": plan_id}, revision):
                raise WorkControlValidationError("Plan revision is not the current immutable submitted revision")
            approval_time = int(time.time()) if approved_at is None else approved_at
            # Commit the optimistic Plan state first so a conflict cannot leave an approved revision row behind.
            updated_plan = await self.repository.update_plan(plan_id, {
                "approval_state": "approved",
                "approved_revision_id": revision_id,
                "approved_at": approval_time,
                "approved_by_hash": approver_hash,
            })
            await self.repository.approve_revision(plan_id, revision_id, approver_hash, approval_time)
            return updated_plan

    async def invalidate_for_material_edit(self, plan_id: str, *, updated_at: int) -> dict[str, Any]:
        return await self.repository.update_plan(plan_id, {
            "approval_state": "changes_required",
            "approved_revision_id": None,
            "approved_at": None,
            "submitted_revision_id": None,
            "updated_at": updated_at,
        })

    @asynccontextmanager
    async def _revision_lock(self, plan: dict[str, Any]) -> AsyncIterator[None]:
        lock = getattr(self.repository, "revision_lock", None)
        if lock is None:
            yield
            return
        async with lock(str(plan.get("hashed_user_id") or ""), str(plan.get("plan_id") or plan.get("id") or "")):
            yield

    @staticmethod
    def _is_submitted_revision(plan: dict[str, Any], revision: dict[str, Any] | None) -> bool:
        return bool(
            revision
            and revision.get("plan_id") == plan.get("plan_id")
            and revision.get("hashed_user_id") == plan.get("hashed_user_id")
            and revision.get("hashed_team_id") == plan.get("hashed_team_id")
            and revision.get("approval_state") == "submitted"
            and revision.get("fingerprint")
            and revision.get("encrypted_snapshot")
        )

    @classmethod
    def _is_current_approved_revision(cls, plan: dict[str, Any], revision: dict[str, Any] | None) -> bool:
        return bool(
            plan.get("submitted_revision_id") == plan.get("approved_revision_id")
            and revision
            and revision.get("plan_id") == plan.get("plan_id")
            and revision.get("hashed_user_id") == plan.get("hashed_user_id")
            and revision.get("hashed_team_id") == plan.get("hashed_team_id")
            and revision.get("approval_state") == "approved"
            and revision.get("fingerprint")
            and revision.get("encrypted_snapshot")
        )

    @classmethod
    def _is_repairable_approved_revision(cls, plan: dict[str, Any], revision: dict[str, Any] | None) -> bool:
        return bool(
            plan.get("approval_state") == "approved"
            and plan.get("submitted_revision_id") == plan.get("approved_revision_id")
            and plan.get("approved_revision_id") == (revision or {}).get("revision_id")
            and plan.get("approved_at") is not None
            and cls._is_submitted_revision(plan, revision)
        )

    async def _require_item(self, ref: str) -> dict[str, Any]:
        item = await self.repository.get_item(ref)
        if item is None:
            raise WorkControlValidationError(f"Dependency item not found: {ref}")
        return item

    @staticmethod
    def _parse_ref(ref: str) -> tuple[str, str]:
        match = ITEM_REF_RE.fullmatch(ref)
        if not match:
            raise WorkControlValidationError("Dependency references must use plan:<id> or task:<id>")
        return match.group(1), match.group(2)

    @staticmethod
    def _validate_shared_scope(source: dict[str, Any], target: dict[str, Any]) -> str:
        if source.get("hashed_user_id") != target.get("hashed_user_id") or source.get("hashed_team_id") != target.get("hashed_team_id"):
            raise WorkControlValidationError("Dependencies must share the same owner/workspace")
        if source.get("hashed_team_id"):
            raise WorkControlValidationError("Team dependencies are not supported in this slice")
        source_projects = set(source.get("linked_project_hashes") or [])
        target_projects = set(target.get("linked_project_hashes") or [])
        if not source_projects or not target_projects or source_projects.isdisjoint(target_projects):
            raise WorkControlValidationError("Dependencies must share the same Project")
        return sorted(source_projects & target_projects)[0]

    @staticmethod
    def _would_cycle(edges: list[dict[str, Any]], source_ref: str, target_ref: str) -> bool:
        adjacency: dict[str, set[str]] = {}
        for edge in edges:
            source = edge.get("source_ref")
            target = edge.get("target_ref")
            if isinstance(source, str) and isinstance(target, str):
                adjacency.setdefault(source, set()).add(target)
        stack = [target_ref]
        visited: set[str] = set()
        while stack:
            current = stack.pop()
            if current == source_ref:
                return True
            if current in visited:
                continue
            visited.add(current)
            stack.extend(adjacency.get(current, ()))
        return False

    @staticmethod
    def _is_satisfied(item: dict[str, Any]) -> bool:
        return (item.get("kind") == "task" and item.get("status") == "done") or (
            item.get("kind") == "plan" and item.get("status") == "completed"
        )

    @staticmethod
    def _has_required_assumption_evidence(assumption: dict[str, Any], status: str) -> bool:
        return is_resolved_assumption({**assumption, "status": status})


class DirectusWorkControlRepository:
    """Persists only safe work-control metadata beside encrypted records."""

    def __init__(self, *, user_id: str, plan_methods: Any, task_methods: Any, directus_service: Any, cache_service: Any, owner_hash: str | None = None):
        self.user_id = user_id
        self.owner_hash = owner_hash
        self.plan_methods = plan_methods
        self.task_methods = task_methods
        self.directus_service = directus_service
        self.cache_service = cache_service

    @asynccontextmanager
    async def graph_lock(self, owner_hash: str, team_hash: str | None) -> AsyncIterator[GraphMutationLease]:
        async with self.owner_graph_lock_for_hash(self.cache_service, owner_hash, team_hash):
            yield

    @staticmethod
    @asynccontextmanager
    async def owner_graph_lock_for_hash(cache_service: Any, owner_hash: str, team_hash: str | None = None) -> AsyncIterator[GraphMutationLease]:
        """Serialize all mutations of one personal owner's dependency graph."""
        if team_hash:
            raise WorkControlValidationError("Team dependencies are not supported in this slice")
        if not owner_hash:
            raise RuntimeError("Dependency graph owner is required")
        client_ref = getattr(cache_service, "client", None)
        if client_ref is None:
            raise RuntimeError("Dependency graph lock backend is unavailable")
        client = await client_ref if isawaitable(client_ref) else client_ref
        if not client:
            raise RuntimeError("Dependency graph lock backend is unavailable")
        key = f"user_work_dependency_graph_lock:{owner_hash}"
        token = secrets.token_urlsafe(16)
        if not await client.set(key, token, nx=True, ex=GRAPH_LOCK_TTL_SECONDS):
            raise RuntimeError("Dependency graph is being updated; retry the mutation")
        lease = GraphMutationLease()
        stop_renewal = asyncio.Event()

        async def renew() -> None:
            while not stop_renewal.is_set():
                try:
                    await asyncio.wait_for(stop_renewal.wait(), timeout=GRAPH_LOCK_TTL_SECONDS / 3)
                    return
                except TimeoutError:
                    renewed = await client.eval(_RENEW_GRAPH_LOCK_SCRIPT, 1, key, token, GRAPH_LOCK_TTL_SECONDS)
                    if not renewed:
                        lease.lost = True
                        return

        renewal_task = asyncio.create_task(renew())
        try:
            yield lease
        finally:
            stop_renewal.set()
            renewal_error: BaseException | None = None
            try:
                await renewal_task
            except BaseException as exc:
                lease.lost = True
                renewal_error = exc
            try:
                released = await client.eval(_RELEASE_GRAPH_LOCK_SCRIPT, 1, key, token)
                if not released:
                    lease.lost = True
            except BaseException as exc:
                lease.lost = True
                if renewal_error is None:
                    renewal_error = exc
            if renewal_error is not None:
                raise RuntimeError("Dependency graph lock renewal or cleanup failed") from renewal_error

    @asynccontextmanager
    async def revision_lock(self, owner_hash: str, plan_id: str) -> AsyncIterator[None]:
        if not owner_hash or not plan_id:
            raise RuntimeError("Plan revision lock scope is required")
        client_ref = getattr(self.cache_service, "client", None)
        if client_ref is None:
            raise RuntimeError("Plan revision lock backend is unavailable")
        client = await client_ref if isawaitable(client_ref) else client_ref
        if not client:
            raise RuntimeError("Plan revision lock backend is unavailable")
        key = f"user_plan_revision_lock:{owner_hash}:{plan_id}"
        token = secrets.token_urlsafe(16)
        if not await client.set(key, token, nx=True, ex=30):
            raise RuntimeError("Plan revision is being updated; retry the mutation")
        try:
            yield
        finally:
            current = await client.get(key)
            if isinstance(current, bytes):
                current = current.decode("utf-8")
            if current == token:
                await client.delete(key)

    async def get_item(self, ref: str) -> dict[str, Any] | None:
        kind, item_id = UserWorkControlService._parse_ref(ref)
        if self.owner_hash:
            collection = "user_plans" if kind == "plan" else "user_tasks"
            id_field = "plan_id" if kind == "plan" else "task_id"
            rows = await self.directus_service.get_items(
                collection,
                params={
                    f"filter[{id_field}][_eq]": item_id,
                    "filter[hashed_user_id][_eq]": self.owner_hash,
                    "filter[hashed_team_id][_null]": True,
                    "fields": "*",
                    "limit": 1,
                },
                no_cache=True,
            )
            item = rows[0] if isinstance(rows, list) and rows else None
            return {**item, "kind": kind, "id": item_id} if item else None
        item = (
            await self.plan_methods.get_plan(item_id, self.user_id)
            if kind == "plan"
            else await self.task_methods.get_task(item_id, self.user_id)
        )
        return {**item, "kind": kind, "id": item_id} if item else None

    async def list_edges(self) -> list[dict[str, Any]]:
        rows = await self.directus_service.get_items(
            "user_work_dependencies",
            params={"filter[hashed_user_id][_eq]": self._owner_hash(), "filter[hashed_team_id][_null]": True, "fields": "*", "limit": -1},
            no_cache=True,
        )
        return rows if isinstance(rows, list) else []

    async def create_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        success, created = await self.directus_service.create_item("user_work_dependencies", edge)
        if not success:
            raise RuntimeError("Failed to create dependency")
        return created

    async def delete_edge(self, source_ref: str, target_ref: str) -> bool:
        rows = await self.directus_service.get_items(
            "user_work_dependencies",
            params={
                "filter[source_ref][_eq]": source_ref,
                "filter[target_ref][_eq]": target_ref,
                "filter[hashed_user_id][_eq]": self._owner_hash(),
                "filter[hashed_team_id][_null]": True,
                "fields": "id",
                "limit": 1,
            },
            no_cache=True,
        )
        return bool(rows and await self.directus_service.delete_item("user_work_dependencies", rows[0]["id"]))

    async def list_assumptions(self, plan_id: str) -> list[dict[str, Any]]:
        if self.owner_hash:
            rows = await self.directus_service.get_items(
                "user_plan_assumptions",
                params={
                    "filter[plan_id][_eq]": plan_id,
                    "fields": "*",
                    "limit": -1,
                },
                no_cache=True,
            )
            return rows if isinstance(rows, list) else []
        return await self.plan_methods.list_assumptions(plan_id)

    async def list_revisions(self, plan_id: str) -> list[dict[str, Any]]:
        rows = await self.directus_service.get_items(
            "user_plan_revisions",
            params={"filter[plan_id][_eq]": plan_id, "filter[hashed_user_id][_eq]": self._owner_hash(), "filter[hashed_team_id][_null]": True, "fields": "*", "sort": "revision_number", "limit": -1},
            no_cache=True,
        )
        return rows if isinstance(rows, list) else []

    async def create_revision(self, plan_id: str, revision: dict[str, Any]) -> dict[str, Any]:
        plan = await self.plan_methods.get_plan(plan_id, self.user_id)
        if not plan:
            raise WorkControlValidationError("Plan not found")
        success, created = await self.directus_service.create_item("user_plan_revisions", {**revision, "plan_id": plan_id})
        if not success:
            raise RuntimeError("Failed to create plan revision")
        return created

    async def approve_revision(self, plan_id: str, revision_id: str, approver_hash: str, approved_at: int) -> None:
        rows = await self.directus_service.get_items(
            "user_plan_revisions",
            params={
                "filter[plan_id][_eq]": plan_id,
                "filter[revision_id][_eq]": revision_id,
                "filter[hashed_user_id][_eq]": self._owner_hash(),
                "filter[hashed_team_id][_null]": True,
                "fields": "id",
                "limit": 1,
            },
            no_cache=True,
        )
        if not rows:
            raise WorkControlValidationError("Plan revision not found")
        updated = await self.directus_service.update_item(
            "user_plan_revisions",
            rows[0]["id"],
            {"approval_state": "approved", "approved_at": approved_at, "approved_by_hash": approver_hash},
        )
        if not updated:
            raise RuntimeError("Failed to record revision approval")

    async def update_plan(self, plan_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        plan = await self.plan_methods.get_plan(plan_id, self.user_id)
        if not plan:
            raise WorkControlValidationError("Plan not found")
        version = plan.get("version")
        if version is None:
            raise WorkControlValidationError("Plan version is required for work-control mutation")
        updated = await self.directus_service.update_item_if_version(
            "user_plans",
            plan["id"],
            {**patch, "version": int(version) + 1},
            int(version),
            owner_hash_field="hashed_user_id",
            owner_hash=self._owner_hash(),
        )
        if not updated:
            raise WorkControlValidationError("Plan was modified by another client")
        return updated

    def _owner_hash(self) -> str:
        if self.owner_hash:
            return self.owner_hash
        from backend.core.api.app.services.directus.user_plan_methods import hash_id

        return hash_id(self.user_id)
