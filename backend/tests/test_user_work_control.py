"""Focused contract coverage for Plan/Task work-control graph behavior."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend.core.api.app.services.user_work_control_service import DirectusWorkControlRepository, UserWorkControlService, WorkControlValidationError


class MemoryRepository:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.items = {
            "task:open": {"kind": "task", "id": "open", "status": "todo", "hashed_user_id": "owner", "hashed_team_id": None, "linked_project_hashes": ["project"]},
            "task:done": {"kind": "task", "id": "done", "status": "done", "hashed_user_id": "owner", "hashed_team_id": None, "linked_project_hashes": ["project"]},
            "plan:active": {"kind": "plan", "id": "active", "status": "active", "hashed_user_id": "owner", "hashed_team_id": None, "linked_project_hashes": ["project"]},
            "plan:complete": {"kind": "plan", "id": "complete", "status": "completed", "hashed_user_id": "owner", "hashed_team_id": None, "linked_project_hashes": ["project"]},
        }
        self.edges = []
        self.assumptions = {"active": []}
        self.revisions = {"active": []}
        self.plans = {"active": {"approval_state": "draft"}}

    async def get_item(self, ref):
        return self.items.get(ref)

    @asynccontextmanager
    async def graph_lock(self, *_args):
        async with self.lock:
            yield

    async def list_edges(self):
        return list(self.edges)

    async def create_edge(self, edge):
        self.edges.append(edge)
        return edge

    async def delete_edge(self, source_ref, target_ref):
        for edge in self.edges:
            if edge["source_ref"] == source_ref and edge["target_ref"] == target_ref:
                self.edges.remove(edge)
                return True
        return False

    async def list_assumptions(self, plan_id):
        return self.assumptions.get(plan_id, [])

    async def list_revisions(self, plan_id):
        return self.revisions.get(plan_id, [])

    async def create_revision(self, plan_id, revision):
        self.revisions.setdefault(plan_id, []).append({**revision, "plan_id": plan_id})
        return self.revisions[plan_id][-1]

    async def approve_revision(self, plan_id, revision_id, approver_hash, approved_at):
        for revision in self.revisions[plan_id]:
            if revision["revision_id"] == revision_id:
                revision.update({"approval_state": "approved", "approved_at": approved_at, "approved_by_hash": approver_hash})
                return

    async def update_plan(self, plan_id, patch):
        self.plans.setdefault(plan_id, {}).update(patch)
        self.items[f"plan:{plan_id}"].update(patch)
        return self.plans[plan_id]


# contract-test: direct surface=rest_api assertions=plans.dependencies.done-only,tasks.dependencies.done-only
@pytest.mark.asyncio
async def test_mixed_dependencies_are_scoped_acyclic_and_done_only():
    service = UserWorkControlService(MemoryRepository())
    await service.add_dependency("task:open", "plan:complete")
    await service.add_dependency("task:open", "task:done")
    assert await service.dependency_blockers("task:open") == []
    await service.add_dependency("task:open", "plan:active")
    assert await service.dependency_blockers("task:open") == [{"ref": "plan:active", "status": "active"}]
    with pytest.raises(WorkControlValidationError, match="duplicate"):
        await service.add_dependency("task:open", "plan:active")
    with pytest.raises(WorkControlValidationError, match="cycle"):
        await service.add_dependency("plan:active", "task:open")


# contract-test: direct surface=rest_api assertions=plans.assumptions.investigated-before-work,plans.approval.human-web-revision-bound
@pytest.mark.asyncio
async def test_evidence_gates_and_material_edits_invalidate_revision_approval():
    repository = MemoryRepository()
    service = UserWorkControlService(repository)
    repository.assumptions["active"] = [{"assumption_id": "A-1", "required_before": "implementation", "status": "confirmed"}]
    assert await service.execution_blockers("active") == [{"kind": "assumption", "id": "A-1", "status": "missing_investigation"}]
    repository.assumptions["active"][0].update({"linked_sub_chat_id": "opencode:ses-proof", "encrypted_sources": "cipher-sources", "encrypted_evidence_summary": "cipher-summary"})
    assert await service.execution_blockers("active") == []
    revision = await service.submit_revision("active", "fingerprint", "cipher-snapshot", created_at=1)
    await service.approve_revision("active", revision["revision_id"], approver_hash="owner", approved_at=2)
    invalidated = await service.invalidate_for_material_edit("active", updated_at=3)
    assert invalidated["approval_state"] == "changes_required"


# contract-test: direct surface=rest_api assertions=plans.approval.human-web-revision-bound,plans.assumptions.investigated-before-work,tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_hashed_scheduler_plan_gates_use_only_valid_assumption_fields():
    owner_hash = "owner-hash"
    plan = {
        "plan_id": "active",
        "hashed_user_id": owner_hash,
        "hashed_team_id": None,
        "approval_state": "approved",
        "submitted_revision_id": "revision-1",
        "approved_revision_id": "revision-1",
    }
    revision = {
        "revision_id": "revision-1",
        "plan_id": "active",
        "hashed_user_id": owner_hash,
        "hashed_team_id": None,
        "approval_state": "approved",
        "fingerprint": "fingerprint",
        "encrypted_snapshot": "cipher-snapshot",
    }

    class Directus:
        async def get_items(self, collection, *, params, no_cache):
            assert no_cache is True
            if collection == "user_plans":
                return [plan]
            if collection == "user_plan_revisions":
                return [revision]
            if collection == "user_work_dependencies":
                return []
            if collection == "user_plan_assumptions":
                assert set(params) == {"filter[plan_id][_eq]", "fields", "limit"}
                return []
            raise AssertionError(collection)

    repository = DirectusWorkControlRepository(
        user_id="",
        owner_hash=owner_hash,
        plan_methods=None,
        task_methods=None,
        directus_service=Directus(),
        cache_service=None,
    )

    assert await UserWorkControlService(repository).plan_execution_blockers("active") == []
