# backend/core/api/app/services/directus/user_plan_methods.py
#
# Directus access helpers for Plans V1. Plan content, criteria, verification
# prompts, and evidence are client-encrypted; the backend stores only minimal
# metadata needed for ownership, filtering, status, and orchestration.

import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_WRAPPER_TYPES = {"master", "chat", "project", "plan", "team"}


USER_PLAN_FIELDS = (
    "id,plan_id,hashed_user_id,hashed_team_id,status,primary_chat_id,hashed_primary_chat_id,"
    "linked_project_hashes,current_phase_id,current_step_id,current_task_id,"
    "planner_focus_id,version,created_at,updated_at,completed_at,"
    "encrypted_plan_key,encrypted_title,encrypted_summary,encrypted_goal,"
    "encrypted_scope_in,encrypted_scope_out,encrypted_linked_project_ids,encrypted_assumptions,"
    "encrypted_open_questions,encrypted_constraints,encrypted_decisions,encrypted_risks"
)

USER_PLAN_KEY_WRAPPER_FIELDS = (
    "id,hashed_plan_id,hashed_user_id,key_type,hashed_chat_id,hashed_project_id,"
    "hashed_context_plan_id,hashed_team_id,team_key_epoch,encrypted_plan_key,created_at,expires_at,wrapper_version"
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


def is_sha256_hex(value: str | None) -> bool:
    return bool(value and SHA256_HEX_RE.fullmatch(value))


def _coerce_hashes(value: Any) -> set[str]:
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    if isinstance(value, str):
        return {value}
    return set()


def _validate_wrapper_shape(wrapper: dict[str, Any], encrypted_key_field: str) -> bool:
    key_type = wrapper.get("key_type")
    if key_type not in KEY_WRAPPER_TYPES:
        logger.error("Rejected user plan key wrapper with invalid key_type")
        return False
    if not wrapper.get(encrypted_key_field):
        logger.error("Rejected user plan key wrapper without encrypted key material")
        return False

    hashed_chat_id = wrapper.get("hashed_chat_id")
    hashed_project_id = wrapper.get("hashed_project_id")
    hashed_context_plan_id = wrapper.get("hashed_plan_id")
    hashed_team_id = wrapper.get("hashed_team_id")
    team_key_epoch = wrapper.get("team_key_epoch")
    if hashed_chat_id is not None and not is_sha256_hex(hashed_chat_id):
        logger.error("Rejected user plan key wrapper with invalid hashed_chat_id")
        return False
    if hashed_project_id is not None and not is_sha256_hex(hashed_project_id):
        logger.error("Rejected user plan key wrapper with invalid hashed_project_id")
        return False
    if hashed_context_plan_id is not None and not is_sha256_hex(hashed_context_plan_id):
        logger.error("Rejected user plan key wrapper with invalid hashed_plan_id")
        return False
    if hashed_team_id is not None and not is_sha256_hex(hashed_team_id):
        logger.error("Rejected user plan key wrapper with invalid hashed_team_id")
        return False
    if key_type == "master" and any(value is not None for value in (hashed_chat_id, hashed_project_id, hashed_context_plan_id, hashed_team_id)):
        logger.error("Rejected user plan master wrapper with scoped hash")
        return False
    if key_type == "chat" and (hashed_chat_id is None or any(value is not None for value in (hashed_project_id, hashed_context_plan_id, hashed_team_id))):
        logger.error("Rejected user plan chat wrapper with invalid scope")
        return False
    if key_type == "project" and (hashed_project_id is None or any(value is not None for value in (hashed_chat_id, hashed_context_plan_id, hashed_team_id))):
        logger.error("Rejected user plan project wrapper with invalid scope")
        return False
    if key_type == "plan" and (hashed_context_plan_id is None or any(value is not None for value in (hashed_chat_id, hashed_project_id, hashed_team_id))):
        logger.error("Rejected user plan plan wrapper with invalid scope")
        return False
    if key_type == "team":
        if hashed_team_id is None or any(value is not None for value in (hashed_chat_id, hashed_project_id, hashed_context_plan_id)):
            logger.error("Rejected user plan team wrapper with invalid scope")
            return False
        if not isinstance(team_key_epoch, int) or team_key_epoch < 1:
            logger.error("Rejected user plan team wrapper without valid team_key_epoch")
            return False
    return True


def _validate_wrapper_set(
    wrappers: list[dict[str, Any]],
    *,
    primary_chat_hash: str | None,
    project_hashes: set[str],
) -> bool:
    if not wrappers:
        logger.error("Rejected empty user plan key wrapper set")
        return False
    master_count = 0
    chat_hashes: set[str] = set()
    wrapper_project_hashes: set[str] = set()
    for wrapper in wrappers:
        if not _validate_wrapper_shape(wrapper, "encrypted_plan_key"):
            return False
        key_type = wrapper.get("key_type")
        if key_type == "master":
            master_count += 1
        elif key_type == "chat":
            hashed_chat_id = wrapper.get("hashed_chat_id")
            if hashed_chat_id != primary_chat_hash:
                logger.error("Rejected user plan chat wrapper that does not match primary chat metadata")
                return False
            chat_hashes.add(hashed_chat_id)
        elif key_type == "project":
            hashed_project_id = wrapper.get("hashed_project_id")
            if hashed_project_id not in project_hashes:
                logger.error("Rejected user plan project wrapper that does not match linked project metadata")
                return False
            wrapper_project_hashes.add(hashed_project_id)
    if master_count != 1:
        logger.error("Rejected user plan key wrapper set without exactly one master wrapper")
        return False
    if primary_chat_hash and primary_chat_hash not in chat_hashes:
        logger.error("Rejected user plan key wrapper set missing primary chat wrapper")
        return False
    if not project_hashes.issubset(wrapper_project_hashes):
        logger.error("Rejected user plan key wrapper set missing linked project wrappers")
        return False
    return True


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
        team_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "fields": USER_PLAN_FIELDS,
            "sort": "-updated_at",
            "limit": max(1, min(limit, 500)),
        }
        if team_id:
            params["filter[hashed_team_id][_eq]"] = hash_id(team_id)
        else:
            params["filter[hashed_user_id][_eq]"] = hash_id(user_id)
            params["filter[hashed_team_id][_null]"] = True
        if status:
            params["filter[status][_eq]"] = status
        if active_only:
            params["filter[status][_in]"] = ["active", "executing", "blocked"]
        if chat_id:
            params["filter[hashed_primary_chat_id][_eq]"] = hash_id(chat_id)
        if project_id:
            params["filter[linked_project_hashes][_contains]"] = hash_id(project_id)
        response = await self.directus_service.get_items("user_plans", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def get_plan(self, plan_id: str, user_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        params = {
            "filter[plan_id][_eq]": plan_id,
            "fields": USER_PLAN_FIELDS,
            "limit": 1,
        }
        if team_id:
            params["filter[hashed_team_id][_eq]"] = hash_id(team_id)
        else:
            params["filter[hashed_user_id][_eq]"] = hash_id(user_id)
            params["filter[hashed_team_id][_null]"] = True
        response = await self.directus_service.get_items("user_plans", params=params, no_cache=True)
        if response and isinstance(response, list):
            return response[0]
        return None

    async def create_plan(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        key_wrappers = payload.pop("key_wrappers", []) or []
        linked_project_ids = payload.pop("linked_project_ids", []) or []
        now = payload.get("created_at") or payload.get("updated_at")
        primary_chat_id = payload.get("primary_chat_id")
        record = {
            **payload,
            "hashed_user_id": hash_id(user_id),
            "status": payload.get("status") or "draft",
            "linked_project_hashes": [hash_id(project_id) for project_id in linked_project_ids if project_id],
            "hashed_primary_chat_id": hash_id(primary_chat_id) if primary_chat_id else None,
            "version": payload.get("version", 1),
            "created_at": now,
            "updated_at": payload.get("updated_at", now),
        }
        if key_wrappers and not _validate_wrapper_set(
            key_wrappers,
            primary_chat_hash=record.get("hashed_primary_chat_id"),
            project_hashes=_coerce_hashes(record.get("linked_project_hashes")),
        ):
            return None
        success, data = await self.directus_service.create_item("user_plans", record)
        if not success:
            logger.error("Failed to create user plan: %s", data)
            return None
        created_wrappers: list[dict[str, Any]] = []
        for wrapper in key_wrappers:
            created_wrapper = await self.create_plan_key_wrapper(user_id, payload["plan_id"], wrapper)
            if not created_wrapper:
                await self._delete_created_plan_with_wrappers(data, created_wrappers)
                return None
            created_wrappers.append(created_wrapper)
        return data

    async def _delete_created_plan_with_wrappers(self, plan_row: dict[str, Any], wrappers: list[dict[str, Any]]) -> None:
        for wrapper in wrappers:
            wrapper_id = wrapper.get("id")
            if wrapper_id:
                await self.directus_service.delete_item("user_plan_key_wrappers", wrapper_id)
        row_id = plan_row.get("id")
        if row_id:
            await self.directus_service.delete_item("user_plans", row_id)

    async def create_plan_key_wrapper(self, user_id: str, plan_id: str, wrapper: dict[str, Any]) -> dict[str, Any] | None:
        hashed_chat_id = wrapper.get("hashed_chat_id")
        hashed_project_id = wrapper.get("hashed_project_id")
        hashed_context_plan_id = wrapper.get("hashed_plan_id")
        hashed_team_id = wrapper.get("hashed_team_id")
        if not _validate_wrapper_shape(wrapper, "encrypted_plan_key"):
            return None
        record = {
            "hashed_plan_id": hash_id(plan_id),
            "hashed_user_id": hash_id(user_id),
            "key_type": wrapper.get("key_type"),
            "hashed_chat_id": hashed_chat_id,
            "hashed_project_id": hashed_project_id,
            "hashed_context_plan_id": hashed_context_plan_id,
            "hashed_team_id": hashed_team_id,
            "team_key_epoch": wrapper.get("team_key_epoch"),
            "encrypted_plan_key": wrapper.get("encrypted_plan_key"),
            "created_at": wrapper.get("created_at"),
            "expires_at": wrapper.get("expires_at"),
            "wrapper_version": wrapper.get("wrapper_version", 1),
        }
        success, data = await self.directus_service.create_item("user_plan_key_wrappers", record)
        if not success:
            logger.error("Failed to create user plan key wrapper: %s", data)
            return None
        return data

    async def replace_plan_key_wrappers(self, user_id: str, plan_id: str, wrappers: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        plan = await self.get_plan(plan_id, user_id)
        if not plan:
            return None
        if not _validate_wrapper_set(
            wrappers,
            primary_chat_hash=plan.get("hashed_primary_chat_id"),
            project_hashes=_coerce_hashes(plan.get("linked_project_hashes")),
        ):
            return None
        existing_wrappers = await self.list_plan_key_wrappers(user_id, plan_id)
        created_wrappers: list[dict[str, Any]] = []
        for wrapper in wrappers:
            created_wrapper = await self.create_plan_key_wrapper(user_id, plan_id, wrapper)
            if not created_wrapper:
                for created in created_wrappers:
                    created_id = created.get("id")
                    if created_id:
                        await self.directus_service.delete_item("user_plan_key_wrappers", created_id)
                return None
            created_wrappers.append(created_wrapper)
        if not await self._delete_key_wrappers(existing_wrappers):
            await self._delete_key_wrappers(created_wrappers)
            raise RuntimeError("Failed to delete old user plan key wrappers")
        return created_wrappers

    async def list_plan_key_wrappers(self, user_id: str, plan_id: str) -> list[dict[str, Any]]:
        params = {
            "filter[hashed_plan_id][_eq]": hash_id(plan_id),
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": USER_PLAN_KEY_WRAPPER_FIELDS,
            "limit": 50,
        }
        response = await self.directus_service.get_items("user_plan_key_wrappers", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def update_plan(self, plan_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        existing = await self.get_plan(plan_id, user_id)
        if not existing:
            return None
        update = dict(patch)
        key_wrappers = update.pop("key_wrappers", None)
        existing_wrappers: list[dict[str, Any]] = []
        created_wrappers: list[dict[str, Any]] = []
        existing_chat_hash = existing.get("hashed_primary_chat_id")
        if existing_chat_hash is None and existing.get("primary_chat_id"):
            existing_chat_hash = hash_id(existing["primary_chat_id"])
        existing_project_hashes = _coerce_hashes(existing.get("linked_project_hashes"))
        if not existing_project_hashes and isinstance(existing.get("linked_project_ids"), list):
            existing_project_hashes = {hash_id(project_id) for project_id in existing["linked_project_ids"] if project_id}

        next_chat_hash = existing_chat_hash
        if "primary_chat_id" in update:
            primary_chat_id = update.get("primary_chat_id")
            next_chat_hash = hash_id(primary_chat_id) if primary_chat_id else None
        next_project_hashes = existing_project_hashes
        if "linked_project_ids" in update:
            linked_project_ids = update.get("linked_project_ids") or []
            next_project_hashes = {hash_id(project_id) for project_id in linked_project_ids if project_id}

        relinks_context = next_chat_hash != existing_chat_hash or next_project_hashes != existing_project_hashes
        if relinks_context and not key_wrappers:
            logger.error("Rejected user plan relink without replacement key wrappers")
            return None
        if next_project_hashes != existing_project_hashes and ("encrypted_linked_project_ids" not in update or update.get("encrypted_linked_project_ids") is None):
            logger.error("Rejected user plan project relink without encrypted linked project ids")
            return None
        update.pop("plan_id", None)
        update.pop("hashed_user_id", None)
        if "primary_chat_id" in update:
            primary_chat_id = update.get("primary_chat_id")
            update["hashed_primary_chat_id"] = hash_id(primary_chat_id) if primary_chat_id else None
        if "linked_project_ids" in update:
            linked_project_ids = update.pop("linked_project_ids") or []
            update["linked_project_hashes"] = [hash_id(project_id) for project_id in linked_project_ids if project_id]
        if key_wrappers is not None and not _validate_wrapper_set(
            key_wrappers,
            primary_chat_hash=next_chat_hash,
            project_hashes=next_project_hashes,
        ):
            return None
        if key_wrappers is not None:
            existing_wrappers = await self.list_plan_key_wrappers(user_id, plan_id)
            for wrapper in key_wrappers:
                created_wrapper = await self.create_plan_key_wrapper(user_id, plan_id, wrapper)
                if not created_wrapper:
                    await self._delete_key_wrappers(created_wrappers)
                    return None
                created_wrappers.append(created_wrapper)
        update["version"] = int(existing.get("version") or 1) + 1
        updated = await self.directus_service.update_item("user_plans", existing["id"], update)
        if not updated:
            await self._delete_key_wrappers(created_wrappers)
            return None
        if not await self._delete_key_wrappers(existing_wrappers):
            raise RuntimeError("Failed to delete old user plan key wrappers")
        return updated

    async def _delete_key_wrappers(self, wrappers: list[dict[str, Any]]) -> bool:
        all_deleted = True
        for wrapper in wrappers:
            wrapper_id = wrapper.get("id")
            if wrapper_id:
                deleted = await self.directus_service.delete_item("user_plan_key_wrappers", wrapper_id)
                if deleted is False:
                    logger.error("Failed to delete old user plan key wrapper")
                    all_deleted = False
        return all_deleted

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
