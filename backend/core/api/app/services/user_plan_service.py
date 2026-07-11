# backend/core/api/app/services/user_plan_service.py
#
# Plans V1 orchestration boundary. Keeps durable plan semantics separate from
# tasks, chat messages, and compression while enforcing completion blockers and
# verification evidence rules.

from typing import Any

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods


COMPLETION_PASSING_STATUSES = {"passed", "passed_unexpectedly", "waived"}
CRITERION_PASSING_STATUSES = {"satisfied", "waived"}


class UserPlanConflictError(ValueError):
    """Raised when a plan update is based on a stale client version."""


class UserPlanNotFoundError(ValueError):
    """Raised when a plan does not exist or belongs to another user."""


class UserPlanService:
    def __init__(self, plan_methods: UserPlanMethods, task_service: Any | None = None):
        self.plan_methods = plan_methods
        self.task_service = task_service

    async def list_plans(self, user_id: str, **filters: Any) -> list[dict[str, Any]]:
        return await self.plan_methods.list_plans(user_id, **filters)

    async def create_plan(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("status", "draft")
        created = await self.plan_methods.create_plan(user_id, payload)
        if not created:
            raise ValueError("Failed to create plan")
        return created

    async def update_plan(self, plan_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = await self.plan_methods.get_plan(plan_id, user_id)
        if not existing:
            raise UserPlanNotFoundError("Plan not found")
        update = dict(patch)
        update["version"] = int(existing.get("version") or 1) + 1
        updated = await self.plan_methods.update_plan(plan_id, user_id, update)
        if not updated:
            raise ValueError("Failed to update plan")
        return updated

    async def activate_plan(self, plan_id: str, user_id: str, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        update = {"status": "active"}
        if patch:
            update.update(patch)
        return await self.update_plan(plan_id, user_id, update)

    async def complete_plan(self, plan_id: str, user_id: str, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        existing = await self.plan_methods.get_plan(plan_id, user_id)
        if not existing:
            raise UserPlanNotFoundError("Plan not found")
        patch = dict(patch or {})
        expected_version = patch.get("version")
        if expected_version is not None and int(expected_version) != int(existing.get("version") or 1):
            raise UserPlanConflictError("Plan was modified by another client")

        blockers = await self.completion_blockers(plan_id)
        if blockers:
            return {"plan": None, "blocked_by": blockers}

        update = {"status": "completed", "completed_at": patch.get("updated_at"), "updated_at": patch.get("updated_at")}
        updated = await self.plan_methods.update_plan(plan_id, user_id, update)
        if not updated:
            raise UserPlanNotFoundError("Plan not found")
        return {"plan": updated, "blocked_by": []}

    async def completion_blockers(self, plan_id: str) -> list[dict[str, Any]]:
        criteria = await self.plan_methods.list_criteria(plan_id)
        verifications = await self.plan_methods.list_verifications(plan_id)
        blockers: list[dict[str, Any]] = []
        for criterion in criteria:
            if criterion.get("required") is False:
                continue
            if criterion.get("status") not in CRITERION_PASSING_STATUSES:
                blockers.append({"kind": "criterion", "id": criterion.get("criterion_id"), "status": criterion.get("status")})
        for verification in verifications:
            if verification.get("required_for_done") is False:
                continue
            if verification.get("status") not in COMPLETION_PASSING_STATUSES:
                blockers.append({"kind": "verification", "id": verification.get("verification_id"), "status": verification.get("status")})
        return blockers

    async def ensure_plan_owner(self, plan_id: str, user_id: str) -> None:
        if not await self.plan_methods.get_plan(plan_id, user_id):
            raise UserPlanNotFoundError("Plan not found")

    async def create_criterion(self, plan_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        created = await self.plan_methods.create_criterion(plan_id, payload)
        if not created:
            raise ValueError("Failed to create plan criterion")
        return created

    async def update_criterion(self, plan_id: str, user_id: str, criterion_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        updated = await self.plan_methods.update_criterion(plan_id, criterion_id, patch)
        if not updated:
            raise UserPlanNotFoundError("Plan criterion not found")
        return updated

    async def create_verification(self, plan_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        payload = dict(payload)
        task = None
        if payload.pop("create_task", False):
            if not self.task_service:
                raise ValueError("Task service is required to create verification tasks")
            task_payload = {
                "task_id": payload.get("task_id"),
                "encrypted_task_key": payload.get("encrypted_task_key"),
                "key_wrappers": payload.get("task_key_wrappers", []),
                "encrypted_title": payload.get("encrypted_title"),
                "encrypted_description": payload.get("encrypted_expected_result"),
                "encrypted_linked_project_ids": payload.get("encrypted_linked_project_ids"),
                "status": "todo",
                "assignee_type": payload.get("assignee_type", "user"),
                "primary_chat_id": payload.get("primary_chat_id"),
                "linked_project_ids": payload.get("linked_project_ids", []),
                "plan_id": plan_id,
                "plan_step_id": payload.get("plan_step_id"),
                "task_type": "verification",
                "verification_id": payload.get("verification_id"),
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
            }
            task = await self.task_service.create_task(user_id, task_payload)
            payload["linked_task_id"] = task.get("task_id")
        for task_only_field in (
            "task_id",
            "encrypted_task_key",
            "task_key_wrappers",
            "encrypted_linked_project_ids",
            "encrypted_title",
            "primary_chat_id",
            "linked_project_ids",
            "plan_step_id",
            "assignee_type",
            "assigned_to",
        ):
            payload.pop(task_only_field, None)
        created = await self.plan_methods.create_verification(plan_id, payload)
        if not created:
            raise ValueError("Failed to create plan verification")
        return {"verification": created, "task": task}

    async def add_verification_evidence(self, plan_id: str, user_id: str, verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        updated = await self.plan_methods.update_verification(plan_id, verification_id, payload)
        if not updated:
            raise UserPlanNotFoundError("Plan verification not found")
        return updated

    def drift_decision(self, drift_score: int) -> dict[str, Any]:
        score = max(0, min(int(drift_score), 100))
        if score < 40:
            return {"drift_score": score, "status": "on_track", "recommended_action": "continue"}
        if score < 70:
            return {"drift_score": score, "status": "slightly_drifting", "recommended_action": "steer_back"}
        if score < 90:
            return {"drift_score": score, "status": "off_track", "recommended_action": "ask_user"}
        return {"drift_score": score, "status": "blocked_or_scope_change", "recommended_action": "stop"}

    def build_correction_message(self, plan_id: str, drift_score: int, message: str, task_id: str | None = None) -> dict[str, Any]:
        decision = self.drift_decision(drift_score)
        return {
            **decision,
            "plan_id": plan_id,
            "task_id": task_id,
            "content": message,
            "origin": "system_generated",
            "display_role": "system",
            "llm_role": "user",
        }

    def build_ai_evaluation_correction(
        self,
        *,
        plan_id: str,
        task_id: str | None,
        score: int,
        threshold: int,
        required_fixes: list[str],
    ) -> dict[str, Any]:
        fixes = "; ".join(required_fixes) if required_fixes else "Address the failed evaluation criteria."
        content = (
            f"Quality check failed: score {score}/{threshold}. "
            f"Keep working on the active plan before marking it done. Required fixes: {fixes}"
        )
        return {
            "plan_id": plan_id,
            "task_id": task_id,
            "score": score,
            "threshold": threshold,
            "plan_status": "active",
            "content": content,
            "origin": "system_generated",
            "display_role": "system",
            "llm_role": "user",
            "recommended_action": "steer_back",
        }
