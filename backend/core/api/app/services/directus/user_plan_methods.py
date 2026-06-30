# backend/core/api/app/services/directus/user_plan_methods.py
#
# Directus access helpers for Plans V1. Plan content, criteria, verification
# prompts, and evidence are client-encrypted; the backend stores only minimal
# metadata needed for ownership, filtering, status, and orchestration.

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


USER_PLAN_FIELDS = (
    "id,plan_id,hashed_user_id,status,primary_chat_id,hashed_primary_chat_id,"
    "linked_project_ids,current_phase_id,current_step_id,current_task_id,"
    "planner_focus_id,version,created_at,updated_at,completed_at,"
    "encrypted_plan_key,encrypted_title,encrypted_summary,encrypted_goal,"
    "encrypted_scope_in,encrypted_scope_out,encrypted_assumptions,"
    "encrypted_open_questions,encrypted_constraints,encrypted_decisions,encrypted_risks"
)

CRITERION_FIELDS = (
    "id,plan_id,criterion_id,type,status,required,linked_step_ids,linked_task_ids,"
    "verification_ids,version,created_at,updated_at,encrypted_text,encrypted_evidence,"
    "encrypted_waiver_reason"
)

VERIFICATION_FIELDS = (
    "id,plan_id,verification_id,kind,phase,status,required_for_done,covers,"
    "threshold,score,confidence,linked_task_id,run_id,created_at,updated_at,"
    "encrypted_command,encrypted_evaluation_prompt,encrypted_expected_result,"
    "encrypted_result_summary,encrypted_required_fixes"
)


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class UserPlanMethods:
    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def list_plans(
        self,
        user_id: str,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": USER_PLAN_FIELDS,
            "sort": "-updated_at",
            "limit": max(1, min(limit, 500)),
        }
        if status:
            params["filter[status][_eq]"] = status
        if active_only:
            params["filter[status][_in]"] = ["active", "executing", "blocked"]
        if chat_id:
            params["filter[hashed_primary_chat_id][_eq]"] = hash_id(chat_id)
        if project_id:
            params["filter[linked_project_ids][_contains]"] = hash_id(project_id)
        response = await self.directus_service.get_items("user_plans", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def get_plan(self, plan_id: str, user_id: str) -> dict[str, Any] | None:
        params = {
            "filter[plan_id][_eq]": plan_id,
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": USER_PLAN_FIELDS,
            "limit": 1,
        }
        response = await self.directus_service.get_items("user_plans", params=params, no_cache=True)
        if response and isinstance(response, list):
            return response[0]
        return None

    async def create_plan(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        now = payload.get("created_at") or payload.get("updated_at")
        primary_chat_id = payload.get("primary_chat_id")
        linked_project_ids = payload.get("linked_project_ids") or []
        record = {
            **payload,
            "hashed_user_id": hash_id(user_id),
            "status": payload.get("status") or "draft",
            "linked_project_ids": [hash_id(project_id) for project_id in linked_project_ids if project_id],
            "hashed_primary_chat_id": hash_id(primary_chat_id) if primary_chat_id else None,
            "version": payload.get("version", 1),
            "created_at": now,
            "updated_at": payload.get("updated_at", now),
        }
        success, data = await self.directus_service.create_item("user_plans", record)
        if not success:
            logger.error("Failed to create user plan: %s", data)
            return None
        return data

    async def update_plan(self, plan_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        existing = await self.get_plan(plan_id, user_id)
        if not existing:
            return None
        update = dict(patch)
        update.pop("plan_id", None)
        update.pop("hashed_user_id", None)
        if "primary_chat_id" in update:
            primary_chat_id = update.get("primary_chat_id")
            update["hashed_primary_chat_id"] = hash_id(primary_chat_id) if primary_chat_id else None
        if "linked_project_ids" in update:
            update["linked_project_ids"] = [hash_id(project_id) for project_id in (update.get("linked_project_ids") or []) if project_id]
        update["version"] = int(existing.get("version") or 1) + 1
        return await self.directus_service.update_item("user_plans", existing["id"], update)

    async def create_criterion(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        record = {**payload, "plan_id": plan_id, "status": payload.get("status") or "pending", "version": payload.get("version", 1)}
        success, data = await self.directus_service.create_item("user_plan_acceptance_criteria", record)
        if not success:
            logger.error("Failed to create plan criterion: %s", data)
            return None
        return data

    async def list_criteria(self, plan_id: str) -> list[dict[str, Any]]:
        params = {"filter[plan_id][_eq]": plan_id, "fields": CRITERION_FIELDS, "sort": "created_at"}
        response = await self.directus_service.get_items("user_plan_acceptance_criteria", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def update_criterion(self, plan_id: str, criterion_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        params = {
            "filter[plan_id][_eq]": plan_id,
            "filter[criterion_id][_eq]": criterion_id,
            "fields": CRITERION_FIELDS,
            "limit": 1,
        }
        existing_rows = await self.directus_service.get_items("user_plan_acceptance_criteria", params=params, no_cache=True)
        if not existing_rows:
            return None
        existing = existing_rows[0]
        update = dict(patch)
        update["version"] = int(existing.get("version") or 1) + 1
        return await self.directus_service.update_item("user_plan_acceptance_criteria", existing["id"], update)

    async def create_verification(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        record = {**payload, "plan_id": plan_id, "status": payload.get("status") or "pending"}
        success, data = await self.directus_service.create_item("user_plan_verifications", record)
        if not success:
            logger.error("Failed to create plan verification: %s", data)
            return None
        return data

    async def list_verifications(self, plan_id: str) -> list[dict[str, Any]]:
        params = {"filter[plan_id][_eq]": plan_id, "fields": VERIFICATION_FIELDS, "sort": "created_at"}
        response = await self.directus_service.get_items("user_plan_verifications", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def update_verification(self, plan_id: str, verification_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        params = {
            "filter[plan_id][_eq]": plan_id,
            "filter[verification_id][_eq]": verification_id,
            "fields": VERIFICATION_FIELDS,
            "limit": 1,
        }
        existing_rows = await self.directus_service.get_items("user_plan_verifications", params=params, no_cache=True)
        if not existing_rows:
            return None
        return await self.directus_service.update_item("user_plan_verifications", existing_rows[0]["id"], patch)
