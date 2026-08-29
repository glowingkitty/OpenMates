# backend/core/api/app/services/user_plan_service.py
#
# Plans V1 orchestration boundary. Keeps durable plan semantics separate from
# tasks, chat messages, and compression while enforcing completion blockers and
# verification evidence rules.

import time
import uuid
from typing import Any

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
from backend.core.api.app.services.user_work_control_service import is_resolved_assumption


COMPLETION_PASSING_STATUSES = {"passed", "passed_unexpectedly", "waived"}
CRITERION_PASSING_STATUSES = {"satisfied", "waived"}
CRITERION_COVERED_STATUSES = {"covered", "waived"}
ASSUMPTION_RESOLVED_STATUSES = {"confirmed", "corrected", "waived"}
REFERENCE_IMPLEMENTATION_READY_STATUSES = {"inspected", "matched", "waived"}
REFERENCE_COMPLETION_READY_STATUSES = {"matched", "waived"}
ACTIVE_PLAN_STATUSES = {"active", "executing", "running_checks", "blocked"}
FINALIZED_LEARNING_STATUSES = {"proposed", "accepted", "applied"}
MIN_FINALIZED_LEARNINGS = 1
MAX_FINALIZED_LEARNINGS = 5


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

    async def get_plan(self, plan_id: str, user_id: str, team_id: str | None = None) -> dict[str, Any]:
        plan = await self.plan_methods.get_plan(plan_id, user_id, team_id=team_id)
        if not plan:
            raise UserPlanNotFoundError("Plan not found")
        return plan

    async def create_plan(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("status", "draft")
        created = await self.plan_methods.create_plan(user_id, payload)
        if not created:
            raise ValueError("Failed to create plan")
        return created

    async def delete_plan(self, plan_id: str, user_id: str) -> None:
        if not await self.plan_methods.delete_plan(plan_id, user_id):
            raise UserPlanNotFoundError("Plan not found")

    async def update_plan(self, plan_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = await self.plan_methods.get_plan(plan_id, user_id)
        if not existing:
            raise UserPlanNotFoundError("Plan not found")
        update = dict(patch)
        expected_version = update.pop("version", None)
        if expected_version is not None and int(expected_version) != int(existing.get("version") or 1):
            raise UserPlanConflictError("Plan was modified by another client")
        if update.get("status") in ACTIVE_PLAN_STATUSES and not (update.get("primary_chat_id") or existing.get("primary_chat_id")):
            raise ValueError("Active or executable plans require primary_chat_id")
        update["version"] = int(existing.get("version") or 1) + 1
        updated = await self.plan_methods.update_plan(plan_id, user_id, update)
        if not updated:
            raise ValueError("Failed to update plan")
        return updated

    async def activate_plan(self, plan_id: str, user_id: str, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        update = {"status": "active"}
        if patch:
            update.update(patch)
        if not update.get("primary_chat_id"):
            existing = await self.plan_methods.get_plan(plan_id, user_id)
            if not existing or not existing.get("primary_chat_id"):
                raise ValueError("Active plans require primary_chat_id")
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
        assumptions = await self.plan_methods.list_assumptions(plan_id) if hasattr(self.plan_methods, "list_assumptions") else []
        reference_patterns = await self.plan_methods.list_reference_patterns(plan_id) if hasattr(self.plan_methods, "list_reference_patterns") else []
        learnings = await self.plan_methods.list_learnings(plan_id) if hasattr(self.plan_methods, "list_learnings") else []
        blockers: list[dict[str, Any]] = []
        for criterion in criteria:
            if criterion.get("required") is False:
                continue
            coverage_status = criterion.get("coverage_status") or ("covered" if criterion.get("verification_ids") else "uncovered")
            if coverage_status not in CRITERION_COVERED_STATUSES:
                blockers.append({"kind": "criterion_coverage", "id": criterion.get("criterion_id"), "status": coverage_status})
            if criterion.get("status") not in CRITERION_PASSING_STATUSES:
                blockers.append({"kind": "criterion", "id": criterion.get("criterion_id"), "status": criterion.get("status")})
        for verification in verifications:
            if verification.get("required_for_done") is False:
                continue
            if verification.get("status") not in COMPLETION_PASSING_STATUSES:
                blockers.append({"kind": "verification", "id": verification.get("verification_id"), "status": verification.get("status")})
        for assumption in assumptions:
            if assumption.get("required_before") not in {"implementation", "task_execution", "completion"}:
                continue
            if assumption.get("status") not in ASSUMPTION_RESOLVED_STATUSES or not is_resolved_assumption(assumption):
                blockers.append({"kind": "assumption", "id": assumption.get("assumption_id"), "status": assumption.get("status")})
        for pattern in reference_patterns:
            if pattern.get("required_before") not in {"completion", "implementation", "task_execution"}:
                continue
            if pattern.get("required_before") == "completion" and pattern.get("status") not in REFERENCE_COMPLETION_READY_STATUSES:
                blockers.append({"kind": "reference_pattern", "id": pattern.get("pattern_id"), "status": pattern.get("status")})
            elif pattern.get("required_before") in {"implementation", "task_execution"} and pattern.get("status") not in REFERENCE_IMPLEMENTATION_READY_STATUSES:
                blockers.append({"kind": "reference_pattern", "id": pattern.get("pattern_id"), "status": pattern.get("status")})
        finalized_learning_count = sum(1 for learning in learnings if learning.get("status") in FINALIZED_LEARNING_STATUSES)
        if finalized_learning_count < MIN_FINALIZED_LEARNINGS:
            blockers.append({"kind": "missing_learnings", "status": "missing", "count": finalized_learning_count})
        elif finalized_learning_count > MAX_FINALIZED_LEARNINGS:
            blockers.append({"kind": "excess_learnings", "status": "too_many", "count": finalized_learning_count})
        return blockers

    async def implementation_blockers(self, plan_id: str) -> list[dict[str, Any]]:
        assumptions = await self.plan_methods.list_assumptions(plan_id) if hasattr(self.plan_methods, "list_assumptions") else []
        patterns = await self.plan_methods.list_reference_patterns(plan_id) if hasattr(self.plan_methods, "list_reference_patterns") else []
        blockers: list[dict[str, Any]] = []
        for assumption in assumptions:
            if assumption.get("required_before") in {"implementation", "task_execution"} and (
                assumption.get("status") not in ASSUMPTION_RESOLVED_STATUSES or not is_resolved_assumption(assumption)
            ):
                blockers.append({"kind": "assumption", "id": assumption.get("assumption_id"), "status": assumption.get("status")})
        for pattern in patterns:
            if pattern.get("required_before") in {"implementation", "task_execution"} and pattern.get("status") not in REFERENCE_IMPLEMENTATION_READY_STATUSES:
                blockers.append({"kind": "reference_pattern", "id": pattern.get("pattern_id"), "status": pattern.get("status")})
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

    async def delete_criterion(self, plan_id: str, user_id: str, criterion_id: str) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        if not await self.plan_methods.delete_criterion(plan_id, criterion_id):
            raise UserPlanNotFoundError("Plan criterion not found")
        return {"deleted": True, "criterion_id": criterion_id}

    async def create_assumption(self, plan_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        created = await self.plan_methods.create_assumption(plan_id, payload)
        if not created:
            raise ValueError("Failed to create plan assumption")
        return created

    async def update_assumption(self, plan_id: str, user_id: str, assumption_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        updated = await self.plan_methods.update_assumption(plan_id, assumption_id, patch)
        if not updated:
            raise UserPlanNotFoundError("Plan assumption not found")
        return updated

    async def delete_assumption(self, plan_id: str, user_id: str, assumption_id: str) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        if not await self.plan_methods.delete_assumption(plan_id, assumption_id):
            raise UserPlanNotFoundError("Plan assumption not found")
        return {"deleted": True, "assumption_id": assumption_id}

    async def create_reference_pattern(self, plan_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        created = await self.plan_methods.create_reference_pattern(plan_id, payload)
        if not created:
            raise ValueError("Failed to create plan reference pattern")
        return created

    async def update_reference_pattern(self, plan_id: str, user_id: str, pattern_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        updated = await self.plan_methods.update_reference_pattern(plan_id, pattern_id, patch)
        if not updated:
            raise UserPlanNotFoundError("Plan reference pattern not found")
        return updated

    async def delete_reference_pattern(self, plan_id: str, user_id: str, pattern_id: str) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        if not await self.plan_methods.delete_reference_pattern(plan_id, pattern_id):
            raise UserPlanNotFoundError("Plan reference pattern not found")
        return {"deleted": True, "pattern_id": pattern_id}

    async def create_learning(self, plan_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        created = await self.plan_methods.create_learning(plan_id, payload)
        if not created:
            raise ValueError("Failed to create plan learning")
        return created

    async def update_learning(self, plan_id: str, user_id: str, learning_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        updated = await self.plan_methods.update_learning(plan_id, learning_id, patch)
        if not updated:
            raise UserPlanNotFoundError("Plan learning not found")
        return updated

    async def delete_learning(self, plan_id: str, user_id: str, learning_id: str) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        if not await self.plan_methods.delete_learning(plan_id, learning_id):
            raise UserPlanNotFoundError("Plan learning not found")
        return {"deleted": True, "learning_id": learning_id}

    async def create_tasks_from_learnings(self, plan_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.task_service:
            raise ValueError("Task service is required to create tasks from learnings")
        plan = await self.plan_methods.get_plan(plan_id, user_id)
        if not plan:
            raise UserPlanNotFoundError("Plan not found")

        requested_ids = [item for item in payload.get("learning_ids") or [] if isinstance(item, str) and item]
        create_all = payload.get("all") is True
        if not create_all and not requested_ids:
            raise ValueError("Select at least one learning")

        learnings = await self.plan_methods.list_learnings(plan_id)
        learnings_by_id = {str(learning.get("learning_id")): learning for learning in learnings if learning.get("learning_id")}
        selected = learnings if create_all else [learnings_by_id[learning_id] for learning_id in requested_ids if learning_id in learnings_by_id]
        skipped: list[dict[str, Any]] = []
        for missing_id in requested_ids:
            if missing_id not in learnings_by_id:
                skipped.append({"learning_id": missing_id, "reason": "not_found"})

        now = int(payload.get("updated_at") or payload.get("created_at") or time.time())
        tasks: list[dict[str, Any]] = []
        for learning in selected:
            learning_id = str(learning.get("learning_id") or "")
            applied_task_id = learning.get("applied_task_id")
            if learning.get("status") == "applied" or applied_task_id:
                skipped.append({"learning_id": learning_id, "reason": "already_applied", "task_id": applied_task_id})
                continue
            if learning.get("status") not in FINALIZED_LEARNING_STATUSES:
                skipped.append({"learning_id": learning_id, "reason": "not_finalized", "status": learning.get("status")})
                continue
            if not learning.get("encrypted_task_draft"):
                skipped.append({"learning_id": learning_id, "reason": "missing_task_draft"})
                continue
            task_key_wrappers = []
            for wrapper in plan.get("key_wrappers") or []:
                if not isinstance(wrapper, dict) or not wrapper.get("encrypted_plan_key"):
                    continue
                task_key_wrappers.append(
                    {
                        **{key: value for key, value in wrapper.items() if key != "encrypted_plan_key"},
                        "encrypted_task_key": wrapper.get("encrypted_plan_key"),
                    }
                )
            task_payload = {
                "task_id": str(uuid.uuid4()),
                "version": 1,
                "encrypted_task_key": plan.get("encrypted_plan_key"),
                "key_wrappers": task_key_wrappers,
                "encrypted_title": learning.get("encrypted_title"),
                "encrypted_description": learning.get("encrypted_task_draft"),
                "status": "backlog",
                "assignee_type": "user",
                "primary_chat_id": plan.get("primary_chat_id"),
                "linked_project_ids": [],
                "plan_id": plan_id,
                "source_plan_id": plan_id,
                "source_learning_id": learning_id,
                "task_type": "work",
                "created_at": now,
                "updated_at": now,
            }
            task = await self.task_service.create_task(user_id, task_payload)
            tasks.append(task)
            await self.plan_methods.update_learning(
                plan_id,
                learning_id,
                {"status": "applied", "applied_task_id": task.get("task_id"), "updated_at": now},
            )
        return {"tasks": tasks, "skipped": skipped}

    async def create_verification(self, plan_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        payload = dict(payload)
        task = None
        if payload.pop("create_task", False):
            if not self.task_service:
                raise ValueError("Task service is required to create verification tasks")
            task_payload = {
                "task_id": payload.get("task_id"),
                "version": 1,
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

    async def update_verification(self, plan_id: str, user_id: str, verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        updated = await self.plan_methods.update_verification(plan_id, verification_id, payload)
        if not updated:
            raise UserPlanNotFoundError("Plan verification not found")
        return updated

    async def delete_verification(self, plan_id: str, user_id: str, verification_id: str) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        if not await self.plan_methods.delete_verification(plan_id, verification_id):
            raise UserPlanNotFoundError("Plan verification not found")
        return {"deleted": True, "verification_id": verification_id}

    async def add_verification_evidence(self, plan_id: str, user_id: str, verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        updated = await self.plan_methods.update_verification(plan_id, verification_id, payload)
        if not updated:
            raise UserPlanNotFoundError("Plan verification not found")
        if updated.get("required_for_done") is not False and updated.get("status") == "failed":
            await self.plan_methods.update_plan(plan_id, user_id, {"status": "blocked", "continuation_state": "blocked"})
        return updated

    async def create_verification_run(self, plan_id: str, user_id: str, verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        created = await self.plan_methods.create_verification_run(plan_id, verification_id, payload)
        if not created:
            raise ValueError("Failed to create plan verification run")
        return created

    async def get_verification_run(self, plan_id: str, user_id: str, verification_id: str, run_id: str) -> dict[str, Any]:
        await self.ensure_plan_owner(plan_id, user_id)
        run = await self.plan_methods.get_verification_run(plan_id, verification_id, run_id)
        if not run:
            raise UserPlanNotFoundError("Plan verification run not found")
        artifacts = await self.plan_methods.list_verification_artifacts(plan_id, verification_id, run_id)
        return {"run": run, "artifacts": artifacts}

    async def save_execution_context(self, plan_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        plan = await self.plan_methods.get_plan(plan_id, user_id)
        if not plan:
            raise UserPlanNotFoundError("Plan not found")
        if not plan.get("primary_chat_id"):
            raise ValueError("Active plan execution context requires primary_chat_id")
        created = await self.plan_methods.create_execution_context(user_id, plan, payload)
        if not created:
            raise ValueError("Failed to create plan execution context")
        return {"plan_id": plan_id, "expires_at": created.get("expires_at")}

    async def active_context(self, user_id: str, chat_id: str, now: int) -> dict[str, Any]:
        context = await self.plan_methods.get_active_execution_context(user_id, chat_id, now)
        if not context:
            return {
                "active_plan": None,
                "blockers": [{"kind": "execution_context", "status": "missing_or_expired"}],
                "completion_guidance": self.completion_guidance([], has_active_plan=False),
            }
        blockers = await self.completion_blockers(str(context.get("plan_id")))
        return {"active_plan": context, "blockers": blockers, "completion_guidance": self.completion_guidance(blockers, has_active_plan=True)}

    def completion_guidance(self, blockers: list[dict[str, Any]], *, has_active_plan: bool = True) -> dict[str, Any]:
        missing_learnings = any(blocker.get("kind") == "missing_learnings" for blocker in blockers)
        return {
            "can_complete": has_active_plan and not blockers,
            "requires_learning_records": has_active_plan and missing_learnings,
            "final_response_sections": ["Learnings / Suggested Improvements"] if has_active_plan and not missing_learnings else [],
        }

    async def cleanup_expired_plan_data(self, now: int) -> dict[str, int]:
        expired_contexts = await self.plan_methods.delete_expired_execution_contexts(now)
        orphan_key_wrappers = await self.plan_methods.delete_orphan_key_wrappers()
        return {"expired_execution_contexts": expired_contexts, "orphan_key_wrappers": orphan_key_wrappers}

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
