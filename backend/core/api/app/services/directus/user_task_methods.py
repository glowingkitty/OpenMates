# backend/core/api/app/services/directus/user_task_methods.py
#
# Directus access helpers for Tasks V1. User task title, description, tags, and
# activity text are client-encrypted; the backend stores only minimal metadata
# needed for ownership, filtering, scheduling, ordering, and execution.
# test-file: backend/tests/test_user_task_activity_api.py

import hashlib
import logging
import re
import secrets
from typing import Any

from backend.shared.python_utils.encrypted_slug_metadata import (
    DuplicateObjectSlugError,
    is_slug_unique_violation,
    validate_encrypted_slug_metadata,
)

logger = logging.getLogger(__name__)
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_WRAPPER_TYPES = {"master", "chat", "project", "plan", "team"}
EXTERNAL_CHAT_PROVIDERS = {"opencode"}
TASK_ASSIGNEE_IDENTITIES = {"openmates": "openmates", "external_ai": "opencode"}
TASK_ASSIGNEE_TYPES = {"user", "openmates", "external_ai", "unassigned"}


class TaskLockBusyError(RuntimeError):
    """Raised when another task lifecycle transition owns the short write lease."""


USER_TASK_FIELDS = (
    "id,task_id,hashed_user_id,hashed_team_id,status,assignee_type,assignee_identity,assignee_hash,"
    "primary_chat_id,hashed_primary_chat_id,external_chat_provider,external_chat_lookup_hash,linked_project_hashes,label_hashes,parent_task_id,"
    "plan_id,task_type,verification_id,source_plan_id,source_learning_id,"
    "due_at,priority,position,version,created_at,updated_at,started_at,"
    "completed_at,blocked_reason_code,queue_state,ai_execution_state,encrypted_title,"
    "encrypted_slug,slug_lookup_hash,encrypted_task_key,encrypted_description,encrypted_labels,encrypted_tags,encrypted_linked_project_ids,"
    "encrypted_activity_summary,encrypted_latest_instruction,encrypted_external_chat_id,encrypted_external_chat_title,encrypted_blocked_reason"
)

USER_TASK_METADATA_FIELDS = "task_id,status,updated_at,version"
USER_TASK_ADMISSION_FIELDS = (
    "id,task_id,hashed_user_id,hashed_team_id,status,assignee_type,assignee_identity,primary_chat_id,"
    "plan_id,due_at,priority,position,version,created_at,updated_at,"
    "started_at,blocked_reason_code,queue_state,ai_execution_state"
)

USER_TASK_KEY_WRAPPER_FIELDS = (
    "id,hashed_task_id,hashed_user_id,key_type,hashed_chat_id,hashed_project_id,"
    "hashed_plan_id,hashed_team_id,team_key_epoch,encrypted_task_key,created_at,expires_at,wrapper_version"
)

USER_TASK_EXECUTION_CONTEXT_FIELDS = "id,hashed_user_id,hashed_task_id,hashed_chat_id,encrypted_context,created_at,expires_at"
USER_TASK_ACTIVITY_FIELDS = (
    "id,entry_id,task_id,hashed_task_id,hashed_user_id,hashed_team_id,kind,actor_type,actor_hash,"
    "actor_display_name,actor_profile_image_url,actor_identity,"
    "event_type,source_surface,previous_status,next_status,created_at,encrypted_message,"
    "encrypted_embed_key_material,embed_refs,encrypted_snapshot,deleted_at,deleted_by_hash,deleted_by_display_name"
)
TASK_ACTIVITY_IDEMPOTENT_FIELDS = {
    "encrypted_message",
    "encrypted_embed_key_material",
    "embed_refs",
    "created_at",
}


def _validate_task_assignment(record: dict[str, Any], *, user_id: str | None = None) -> None:
    assignee_type = record.get("assignee_type") or "user"
    if assignee_type not in TASK_ASSIGNEE_TYPES:
        raise ValueError("Task assignee type is not allowed")
    expected_identity = TASK_ASSIGNEE_IDENTITIES.get(assignee_type)
    identity = record.get("assignee_identity")
    if expected_identity is not None and identity != expected_identity:
        raise ValueError(f"Task {assignee_type} assignment requires identity {expected_identity}")
    if expected_identity is None and identity is not None:
        raise ValueError(f"Task {assignee_type} assignment cannot have an AI identity")
    if assignee_type == "user":
        if not record.get("assignee_hash") and user_id:
            record["assignee_hash"] = hash_id(user_id)
    else:
        record["assignee_hash"] = None


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def derive_task_short_id(task: dict[str, Any]) -> str:
    prefix = str(task.get("short_id_prefix") or "TASK")
    source = str(task.get("task_id") or f"{task.get('created_at') or ''}-{task.get('position') or ''}")
    digest = hashlib.sha256(source.encode()).hexdigest()[:4].upper()
    return f"{prefix}-{int(digest, 16) % 10_000}"


def _with_short_id(task: dict[str, Any]) -> dict[str, Any]:
    return {**task, "short_id": task.get("short_id") or derive_task_short_id(task)}


def is_sha256_hex(value: str | None) -> bool:
    return bool(value and SHA256_HEX_RE.fullmatch(value))


def _coerce_hashes(value: Any) -> set[str]:
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    if isinstance(value, str):
        return {value}
    return set()


def _coerce_blind_hashes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    hashes: list[str] = []
    for item in value:
        if not isinstance(item, str) or not is_sha256_hex(item):
            raise ValueError("Task label hashes must be lowercase SHA-256 hex strings")
        hashes.append(item)
    return hashes


def _coerce_priority(value: Any) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Task priority must be an integer from 0 to 4") from exc
    if priority < 0 or priority > 4:
        raise ValueError("Task priority must be an integer from 0 to 4")
    return priority


def _validate_external_chat_context(record: dict[str, Any]) -> None:
    provider = record.get("external_chat_provider")
    lookup_hash = record.get("external_chat_lookup_hash")
    encrypted_id = record.get("encrypted_external_chat_id")
    encrypted_title = record.get("encrypted_external_chat_title")
    has_external_field = any(value is not None for value in (provider, lookup_hash, encrypted_id, encrypted_title))
    if not has_external_field:
        return
    if provider not in EXTERNAL_CHAT_PROVIDERS:
        raise ValueError("Task external chat provider is not allowed")
    if not is_sha256_hex(lookup_hash):
        raise ValueError("Task external chat lookup hash must be a lowercase SHA-256 hex string")
    if not isinstance(encrypted_id, str) or not encrypted_id:
        raise ValueError("Task external chat requires an encrypted external id")
    if record.get("primary_chat_id") is not None:
        raise ValueError("Task must use either a native or external chat context, not both")


def _slug_lookup_filter(user_id: str, slug_lookup_hash: str, exclude_row_id: str | None = None) -> dict[str, Any]:
    terms: list[dict[str, Any]] = [
        {"slug_lookup_hash": {"_eq": slug_lookup_hash}},
        {"hashed_user_id": {"_eq": hash_id(user_id)}},
        {"hashed_team_id": {"_null": True}},
    ]
    if exclude_row_id:
        terms.append({"id": {"_neq": exclude_row_id}})
    return {"_and": terms}


def _validate_wrapper_shape(wrapper: dict[str, Any], encrypted_key_field: str) -> bool:
    key_type = wrapper.get("key_type")
    if key_type not in KEY_WRAPPER_TYPES:
        logger.error("Rejected user task key wrapper with invalid key_type")
        return False
    if not wrapper.get(encrypted_key_field):
        logger.error("Rejected user task key wrapper without encrypted key material")
        return False

    hashed_chat_id = wrapper.get("hashed_chat_id")
    hashed_project_id = wrapper.get("hashed_project_id")
    hashed_plan_id = wrapper.get("hashed_plan_id")
    hashed_team_id = wrapper.get("hashed_team_id")
    team_key_epoch = wrapper.get("team_key_epoch")
    if hashed_chat_id is not None and not is_sha256_hex(hashed_chat_id):
        logger.error("Rejected user task key wrapper with invalid hashed_chat_id")
        return False
    if hashed_project_id is not None and not is_sha256_hex(hashed_project_id):
        logger.error("Rejected user task key wrapper with invalid hashed_project_id")
        return False
    if hashed_plan_id is not None and not is_sha256_hex(hashed_plan_id):
        logger.error("Rejected user task key wrapper with invalid hashed_plan_id")
        return False
    if hashed_team_id is not None and not is_sha256_hex(hashed_team_id):
        logger.error("Rejected user task key wrapper with invalid hashed_team_id")
        return False
    if key_type == "master" and any(value is not None for value in (hashed_chat_id, hashed_project_id, hashed_plan_id, hashed_team_id)):
        logger.error("Rejected user task master wrapper with scoped hash")
        return False
    if key_type == "chat" and (hashed_chat_id is None or any(value is not None for value in (hashed_project_id, hashed_plan_id, hashed_team_id))):
        logger.error("Rejected user task chat wrapper with invalid scope")
        return False
    if key_type == "project" and (hashed_project_id is None or any(value is not None for value in (hashed_chat_id, hashed_plan_id, hashed_team_id))):
        logger.error("Rejected user task project wrapper with invalid scope")
        return False
    if key_type == "plan" and (hashed_plan_id is None or any(value is not None for value in (hashed_chat_id, hashed_project_id, hashed_team_id))):
        logger.error("Rejected user task plan wrapper with invalid scope")
        return False
    if key_type == "team":
        if hashed_team_id is None or any(value is not None for value in (hashed_chat_id, hashed_project_id, hashed_plan_id)):
            logger.error("Rejected user task team wrapper with invalid scope")
            return False
        if not isinstance(team_key_epoch, int) or team_key_epoch < 1:
            logger.error("Rejected user task team wrapper without valid team_key_epoch")
            return False
    return True


def _validate_wrapper_set(
    wrappers: list[dict[str, Any]],
    *,
    primary_chat_hash: str | None,
    project_hashes: set[str],
    plan_hash: str | None = None,
    has_external_chat_context: bool = False,
) -> bool:
    if not wrappers:
        logger.error("Rejected empty user task key wrapper set")
        return False
    master_count = 0
    chat_hashes: set[str] = set()
    wrapper_project_hashes: set[str] = set()
    plan_hashes: set[str] = set()
    for wrapper in wrappers:
        if not _validate_wrapper_shape(wrapper, "encrypted_task_key"):
            return False
        key_type = wrapper.get("key_type")
        if key_type == "master":
            master_count += 1
        elif key_type == "chat":
            if has_external_chat_context:
                logger.error("Rejected user task chat wrapper for external chat context")
                return False
            hashed_chat_id = wrapper.get("hashed_chat_id")
            if hashed_chat_id != primary_chat_hash:
                logger.error("Rejected user task chat wrapper that does not match primary chat metadata")
                return False
            chat_hashes.add(hashed_chat_id)
        elif key_type == "project":
            hashed_project_id = wrapper.get("hashed_project_id")
            if hashed_project_id not in project_hashes:
                logger.error("Rejected user task project wrapper that does not match linked project metadata")
                return False
            wrapper_project_hashes.add(hashed_project_id)
        elif key_type == "plan":
            hashed_plan_id = wrapper.get("hashed_plan_id")
            if hashed_plan_id != plan_hash:
                logger.error("Rejected user task plan wrapper that does not match plan metadata")
                return False
            plan_hashes.add(hashed_plan_id)
    if master_count != 1:
        logger.error("Rejected user task key wrapper set without exactly one master wrapper")
        return False
    if primary_chat_hash and primary_chat_hash not in chat_hashes:
        logger.error("Rejected user task key wrapper set missing primary chat wrapper")
        return False
    if not project_hashes.issubset(wrapper_project_hashes):
        logger.error("Rejected user task key wrapper set missing linked project wrappers")
        return False
    if plan_hash and plan_hash not in plan_hashes:
        logger.error("Rejected user task key wrapper set missing linked plan wrapper")
        return False
    return True


class UserTaskMethods:
    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def list_tasks(
        self,
        user_id: str,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        assignee_hash: str | None = None,
        label_hashes: list[str] | None = None,
        external_chat_provider: str | None = None,
        external_chat_lookup_hash: str | None = None,
        priority: int | None = None,
        due_before: int | None = None,
        team_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        requested_limit = max(1, min(limit, 500))
        if team_id:
            filter_terms: list[dict[str, Any]] = [{"hashed_team_id": {"_eq": hash_id(team_id)}}]
        else:
            filter_terms = [{"hashed_user_id": {"_eq": hash_id(user_id)}}, {"hashed_team_id": {"_null": True}}]
        valid_label_hashes = _coerce_blind_hashes(label_hashes or [])
        if (external_chat_provider is None) != (external_chat_lookup_hash is None):
            raise ValueError("Task external chat filters require both provider and lookup hash")
        if external_chat_provider is not None:
            if external_chat_provider not in EXTERNAL_CHAT_PROVIDERS:
                raise ValueError("Task external chat provider is not allowed")
            if not is_sha256_hex(external_chat_lookup_hash):
                raise ValueError("Task external chat lookup hash must be a lowercase SHA-256 hex string")
        params: dict[str, Any] = {
            "fields": USER_TASK_FIELDS,
            "sort": "position,created_at",
            "limit": -1 if project_id else requested_limit,
        }
        if status:
            filter_terms.append({"status": {"_eq": status}})
        if chat_id:
            filter_terms.append({"hashed_primary_chat_id": {"_eq": hash_id(chat_id)}})
        if assignee_hash:
            filter_terms.append({"assignee_hash": {"_eq": assignee_hash}})
        if external_chat_provider:
            filter_terms.append({"external_chat_provider": {"_eq": external_chat_provider}})
            filter_terms.append({"external_chat_lookup_hash": {"_eq": external_chat_lookup_hash}})
        if priority is not None:
            filter_terms.append({"priority": {"_eq": _coerce_priority(priority)}})
        for label_hash in valid_label_hashes:
            filter_terms.append({"label_hashes": {"_contains": label_hash}})
        if due_before is not None:
            filter_terms.append({"due_at": {"_lte": due_before}})
        params["filter"] = {"_and": filter_terms} if len(filter_terms) > 1 else filter_terms[0]

        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        tasks = response if isinstance(response, list) else []
        if project_id:
            project_hash = hash_id(project_id)
            tasks = [task for task in tasks if project_hash in _coerce_hashes(task.get("linked_project_hashes"))]
            tasks = tasks[:requested_limit]
        return [_with_short_id(task) for task in tasks]

    async def summarize_task_metadata(self, user_id: str, team_id: str | None = None) -> dict[str, Any]:
        if team_id:
            filter_terms: list[dict[str, Any]] = [{"hashed_team_id": {"_eq": hash_id(team_id)}}]
        else:
            filter_terms = [{"hashed_user_id": {"_eq": hash_id(user_id)}}, {"hashed_team_id": {"_null": True}}]
        response = await self.directus_service.get_items(
            "user_tasks",
            params={
                "fields": "status",
                "filter": {"_and": filter_terms} if len(filter_terms) > 1 else filter_terms[0],
                "limit": -1,
            },
            no_cache=True,
        )
        tasks = response if isinstance(response, list) else []
        by_status: dict[str, int] = {}
        for task in tasks:
            status = str(task.get("status") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        return {"total": len(tasks), "by_status": by_status}

    async def get_task_metadata(self, task_id: str, user_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        params = {
            "filter[task_id][_eq]": task_id,
            "fields": USER_TASK_METADATA_FIELDS,
            "limit": 1,
        }
        if team_id:
            params["filter[hashed_team_id][_eq]"] = hash_id(team_id)
        else:
            params["filter[hashed_user_id][_eq]"] = hash_id(user_id)
            params["filter[hashed_team_id][_null]"] = True
        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        if response and isinstance(response, list):
            task = response[0]
            return {
                "task_id": task.get("task_id"),
                "status": task.get("status"),
                "updated_at": task.get("updated_at"),
                "version": task.get("version"),
            }
        return None

    async def get_task(self, task_id: str, user_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        params = {
            "filter[task_id][_eq]": task_id,
            "fields": USER_TASK_FIELDS,
            "limit": 1,
        }
        if team_id:
            params["filter[hashed_team_id][_eq]"] = hash_id(team_id)
        else:
            params["filter[hashed_user_id][_eq]"] = hash_id(user_id)
            params["filter[hashed_team_id][_null]"] = True
        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        if response and isinstance(response, list):
            return _with_short_id(response[0])
        return None

    def _activity_filter(self, user_id: str, task_id: str, team_id: str | None = None) -> dict[str, Any]:
        terms: list[dict[str, Any]] = [{"hashed_task_id": {"_eq": hash_id(task_id)}}]
        if team_id:
            terms.append({"hashed_team_id": {"_eq": hash_id(team_id)}})
        else:
            terms.extend(
                [
                    {"hashed_user_id": {"_eq": hash_id(user_id)}},
                    {"hashed_team_id": {"_null": True}},
                ]
            )
        return {"_and": terms}

    async def list_task_activity(
        self,
        user_id: str,
        task_id: str,
        *,
        team_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        newest_first: bool = False,
    ) -> list[dict[str, Any]]:
        comparison = "_lt" if newest_first else "_gt"
        bounded_limit = max(1, min(limit, 201))
        params: dict[str, Any] = {
            "fields": USER_TASK_ACTIVITY_FIELDS,
            "filter[hashed_task_id][_eq]": hash_id(task_id),
            "sort": "-created_at,-entry_id" if newest_first else "created_at,entry_id",
            "limit": bounded_limit,
        }
        if team_id:
            params["filter[hashed_team_id][_eq]"] = hash_id(team_id)
        else:
            params["filter[hashed_user_id][_eq]"] = hash_id(user_id)
            params["filter[hashed_team_id][_null]"] = True
        if cursor:
            created_at_text, separator, entry_id = cursor.partition(":")
            if not separator or not created_at_text.isdigit() or not entry_id:
                raise ValueError("Invalid Task Activity cursor")
            created_at = int(created_at_text)
            same_timestamp_params = {
                **params,
                "filter[created_at][_eq]": created_at,
                f"filter[entry_id][{comparison}]": entry_id,
                "sort": "-entry_id" if newest_first else "entry_id",
            }
            same_timestamp = await self.directus_service.get_items(
                "user_task_activity",
                params=same_timestamp_params,
                no_cache=True,
            )
            entries = same_timestamp if isinstance(same_timestamp, list) else []
            if len(entries) >= bounded_limit:
                return entries
            later_params = {
                **params,
                f"filter[created_at][{comparison}]": created_at,
                "limit": bounded_limit - len(entries),
            }
            later = await self.directus_service.get_items(
                "user_task_activity",
                params=later_params,
                no_cache=True,
            )
            return entries + (later if isinstance(later, list) else [])
        response = await self.directus_service.get_items(
            "user_task_activity",
            params=params,
            no_cache=True,
        )
        return response if isinstance(response, list) else []

    async def create_task_activity(
        self,
        user_id: str,
        task_id: str,
        payload: dict[str, Any],
        *,
        team_id: str | None = None,
        source_surface: str,
        actor_type: str = "user",
        actor_hash: str | None = None,
        actor_display_name: str | None = None,
        actor_profile_image_url: str | None = None,
    ) -> dict[str, Any] | None:
        entry_id = str(payload.get("entry_id") or "")
        existing = await self.directus_service.get_items(
            "user_task_activity",
            params={
                "fields": USER_TASK_ACTIVITY_FIELDS,
                "filter": {"_and": [self._activity_filter(user_id, task_id, team_id), {"entry_id": {"_eq": entry_id}}]},
                "limit": 1,
            },
            no_cache=True,
        )
        if isinstance(existing, list) and existing:
            current = existing[0]
            if any(current.get(field) != payload.get(field) for field in TASK_ACTIVITY_IDEMPOTENT_FIELDS):
                raise ValueError("Task Activity entry id conflicts with different content")
            return current

        record = {
            "entry_id": entry_id,
            "task_id": task_id,
            "hashed_task_id": hash_id(task_id),
            "hashed_user_id": hash_id(user_id),
            "hashed_team_id": hash_id(team_id) if team_id else None,
            "kind": "comment",
            "actor_type": actor_type,
            "actor_hash": hash_id(user_id) if actor_hash is None and actor_type == "user" else actor_hash,
            "actor_display_name": actor_display_name,
            "actor_profile_image_url": actor_profile_image_url,
            "actor_identity": payload.get("actor_identity"),
            "event_type": "comment_added",
            "source_surface": source_surface,
            "created_at": payload["created_at"],
            "encrypted_message": payload["encrypted_message"],
            "encrypted_embed_key_material": payload.get("encrypted_embed_key_material"),
            "embed_refs": payload.get("embed_refs") or [],
            "encrypted_snapshot": None,
            "deleted_at": None,
            "deleted_by_hash": None,
        }
        success, created = await self.directus_service.create_item("user_task_activity", record)
        if success and isinstance(created, dict):
            return created
        raced = await self.directus_service.get_items(
            "user_task_activity",
            params={
                "fields": USER_TASK_ACTIVITY_FIELDS,
                "filter": {"_and": [self._activity_filter(user_id, task_id, team_id), {"entry_id": {"_eq": entry_id}}]},
                "limit": 1,
            },
            no_cache=True,
        )
        if isinstance(raced, list) and raced:
            current = raced[0]
            if any(current.get(field) != payload.get(field) for field in TASK_ACTIVITY_IDEMPOTENT_FIELDS):
                raise ValueError("Task Activity entry id conflicts with different content")
            return current
        return None

    async def delete_task_activity(
        self,
        user_id: str,
        task_id: str,
        entry_id: str,
        *,
        team_id: str | None = None,
        deleted_at: int,
        allow_task_mutation: bool = False,
        deleted_by_display_name: str | None = None,
    ) -> dict[str, Any]:
        response = await self.directus_service.get_items(
            "user_task_activity",
            params={
                "fields": USER_TASK_ACTIVITY_FIELDS,
                "filter": {"_and": [self._activity_filter(user_id, task_id, team_id), {"entry_id": {"_eq": entry_id}}]},
                "limit": 1,
            },
            no_cache=True,
        )
        if not isinstance(response, list) or not response:
            raise PermissionError("Task Activity entry not found in the authorized scope")
        entry = response[0]
        if entry.get("kind") == "tombstone":
            raise ValueError("TASK_ACTIVITY_ALREADY_DELETED")
        actor_hash = str(entry.get("actor_hash") or "")
        if actor_hash != hash_id(user_id) and not allow_task_mutation:
            raise PermissionError("Task Activity deletion is not authorized")
        patch = {
            "kind": "tombstone",
            "event_type": "comment_deleted",
            "deleted_at": deleted_at,
            "deleted_by_hash": hash_id(user_id),
            "deleted_by_display_name": deleted_by_display_name,
            "encrypted_message": None,
            "encrypted_embed_key_material": None,
            "embed_refs": [],
            "encrypted_snapshot": None,
        }
        updated = await self.directus_service.update_item("user_task_activity", entry["id"], patch)
        if not updated:
            raise ValueError("Failed to delete Task Activity entry")
        return {**entry, **patch, "author_hash": actor_hash}

    async def admission_blockers(self, task: dict[str, Any], user_id: str, *, owner_hash: str | None = None) -> list[dict[str, str]]:
        from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
        from backend.core.api.app.services.user_work_control_service import DirectusWorkControlRepository, UserWorkControlService

        repository = DirectusWorkControlRepository(
            user_id=user_id,
            plan_methods=UserPlanMethods(self.directus_service),
            task_methods=self,
            directus_service=self.directus_service,
            cache_service=None,
            owner_hash=owner_hash,
        )
        service = UserWorkControlService(repository)
        task_id = str(task.get("task_id") or "")
        blockers = await service.dependency_blockers(f"task:{task_id}")
        plan_id = str(task.get("plan_id") or "")
        if plan_id:
            blockers.extend(await service.plan_execution_blockers(plan_id))
        return blockers

    async def get_task_by_short_id(self, short_id: str, user_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for task in await self.list_tasks(user_id, team_id=team_id, limit=500):
            if task.get("short_id") == short_id:
                matches.append(task)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.error("Ambiguous task short ID %s for user hash %s", short_id, hash_id(user_id))
        return None

    async def list_due_ai_tasks(self, due_before: int, *, limit: int = 100) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[assignee_type][_eq]": "openmates",
            "filter[due_at][_lte]": due_before,
            "filter[status][_eq]": "todo",
            "fields": USER_TASK_FIELDS,
            "sort": "due_at,position,created_at",
            "limit": max(1, min(limit, 500)),
        }
        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def list_waiting_ai_task_scopes_for_reconciliation(self, *, limit: int = 100) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[assignee_type][_eq]": "openmates",
            "filter[status][_eq]": "todo",
            "fields": ["hashed_user_id", "hashed_team_id"],
            "groupBy": ["hashed_user_id", "hashed_team_id"],
            "sort": "hashed_team_id,hashed_user_id",
        }
        return await self._list_all_admission_rows(params, page_size=limit)

    async def list_stale_queued_ai_tasks(self, started_before: int, *, limit: int = 100) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[assignee_type][_eq]": "openmates",
            "filter[status][_eq]": "in_progress",
            "filter[queue_state][_eq]": "active",
            "filter[ai_execution_state][_eq]": "queued",
            "filter[started_at][_lte]": started_before,
            "fields": USER_TASK_ADMISSION_FIELDS,
            "sort": "started_at,task_id",
            "limit": max(1, min(limit, 500)),
        }
        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def list_active_ai_tasks_for_chat(
        self,
        user_id: str,
        chat_id: str,
        *,
        exclude_task_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "filter[hashed_primary_chat_id][_eq]": hash_id(chat_id),
            "filter[assignee_type][_eq]": "openmates",
            "filter[status][_eq]": "in_progress",
            "fields": USER_TASK_FIELDS,
            "sort": "started_at,position,created_at",
            "limit": max(1, min(limit, 50)),
        }
        if exclude_task_id:
            params["filter[task_id][_neq]"] = exclude_task_id
        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def list_open_tasks_for_admission(
        self,
        user_id: str,
        *,
        team_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[status][_in]": ["todo", "in_progress", "blocked"],
            "fields": USER_TASK_ADMISSION_FIELDS,
            "sort": "task_id",
        }
        if team_id:
            params["filter[hashed_team_id][_eq]"] = hash_id(team_id)
        else:
            params["filter[hashed_user_id][_eq]"] = hash_id(user_id)
            params["filter[hashed_team_id][_null]"] = True
        return await self._list_all_admission_rows(params, page_size=limit)

    async def list_open_tasks_for_hashed_admission(self, scope: str, owner_hash: str, *, limit: int = 500) -> list[dict[str, Any]]:
        owner_field = "hashed_team_id" if scope == "team" else "hashed_user_id"
        params: dict[str, Any] = {
            f"filter[{owner_field}][_eq]": owner_hash,
            "filter[status][_in]": ["todo", "in_progress", "blocked"],
            "fields": USER_TASK_ADMISSION_FIELDS,
            "sort": "task_id",
        }
        if scope == "personal":
            params["filter[hashed_team_id][_null]"] = True
        return await self._list_all_admission_rows(params, page_size=limit)

    async def _list_all_admission_rows(self, params: dict[str, Any], *, page_size: int) -> list[dict[str, Any]]:
        bounded_page_size = max(1, min(page_size, 500))
        rows: list[dict[str, Any]] = []
        offset = 0
        task_id_cursor: str | None = None
        grouped_query = bool(params.get("groupBy"))
        while True:
            page_params = {**params, "limit": bounded_page_size}
            if grouped_query:
                page_params["offset"] = offset
            elif task_id_cursor:
                page_params["filter[task_id][_gt]"] = task_id_cursor
            response = await self.directus_service.get_items(
                "user_tasks",
                params=page_params,
                no_cache=True,
            )
            page = response if isinstance(response, list) else []
            rows.extend(page)
            if len(page) < bounded_page_size:
                return rows
            if grouped_query:
                offset += bounded_page_size
                continue
            next_cursor = str(page[-1].get("task_id") or "")
            if not next_cursor or next_cursor == task_id_cursor:
                raise RuntimeError("User Task admission pagination did not advance")
            task_id_cursor = next_cursor

    async def create_task(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        key_wrappers = payload.pop("key_wrappers", []) or []
        linked_project_ids = payload.pop("linked_project_ids", []) or []
        validate_encrypted_slug_metadata(payload, record_label="Task")
        now = payload.get("created_at") or payload.get("updated_at")
        primary_chat_id = payload.get("primary_chat_id")
        version = payload.get("version")
        if version is None:
            raise ValueError("Task create requires version")
        record = {
            **payload,
            "hashed_user_id": hash_id(user_id),
            "status": payload.get("status") or "todo",
            "assignee_type": payload.get("assignee_type") or "user",
            "linked_project_hashes": [hash_id(project_id) for project_id in linked_project_ids if project_id],
            "label_hashes": _coerce_blind_hashes(payload.get("label_hashes") or []),
            "priority": _coerce_priority(payload.get("priority") or 0),
            "hashed_primary_chat_id": hash_id(primary_chat_id) if primary_chat_id else None,
            "version": int(version),
            "created_at": now,
            "updated_at": payload.get("updated_at", now),
        }
        _validate_task_assignment(record, user_id=user_id)
        _validate_external_chat_context(record)
        if key_wrappers and not _validate_wrapper_set(
            key_wrappers,
            primary_chat_hash=record.get("hashed_primary_chat_id"),
            project_hashes=_coerce_hashes(record.get("linked_project_hashes")),
            plan_hash=hash_id(record["plan_id"]) if record.get("plan_id") else None,
            has_external_chat_context=record.get("external_chat_provider") is not None,
        ):
            return None
        await self._ensure_slug_lookup_available(record.get("slug_lookup_hash"), user_id)
        success, data = await self.directus_service.create_item("user_tasks", record)
        if not success:
            if is_slug_unique_violation(data):
                raise DuplicateObjectSlugError("Task slug already exists in this workspace")
            logger.error("Failed to create user task: %s", data)
            return None
        created_wrappers: list[dict[str, Any]] = []
        for wrapper in key_wrappers:
            created_wrapper = await self.create_task_key_wrapper(user_id, payload["task_id"], wrapper)
            if not created_wrapper:
                await self._delete_created_task_with_wrappers(data, created_wrappers)
                return None
            created_wrappers.append(created_wrapper)
        return data

    async def _delete_created_task_with_wrappers(self, task_row: dict[str, Any], wrappers: list[dict[str, Any]]) -> None:
        for wrapper in wrappers:
            wrapper_id = wrapper.get("id")
            if wrapper_id:
                await self.directus_service.delete_item("user_task_key_wrappers", wrapper_id, admin_required=True)
        row_id = task_row.get("id")
        if row_id:
            await self.directus_service.delete_item("user_tasks", row_id)

    async def create_task_key_wrapper(self, user_id: str, task_id: str, wrapper: dict[str, Any]) -> dict[str, Any] | None:
        hashed_chat_id = wrapper.get("hashed_chat_id")
        hashed_project_id = wrapper.get("hashed_project_id")
        hashed_plan_id = wrapper.get("hashed_plan_id")
        hashed_team_id = wrapper.get("hashed_team_id")
        if not _validate_wrapper_shape(wrapper, "encrypted_task_key"):
            return None
        record = {
            "hashed_task_id": hash_id(task_id),
            "hashed_user_id": hash_id(user_id),
            "key_type": wrapper.get("key_type"),
            "hashed_chat_id": hashed_chat_id,
            "hashed_project_id": hashed_project_id,
            "hashed_plan_id": hashed_plan_id,
            "hashed_team_id": hashed_team_id,
            "team_key_epoch": wrapper.get("team_key_epoch"),
            "encrypted_task_key": wrapper.get("encrypted_task_key"),
            "created_at": wrapper.get("created_at"),
            "expires_at": wrapper.get("expires_at"),
            "wrapper_version": wrapper.get("wrapper_version", 1),
        }
        success, data = await self.directus_service.create_item("user_task_key_wrappers", record, admin_required=True)
        if not success:
            logger.error("Failed to create user task key wrapper: %s", data)
            return None
        return data

    async def replace_task_key_wrappers(self, user_id: str, task_id: str, wrappers: list[dict[str, Any]], expected_version: int) -> list[dict[str, Any]] | None:
        lock_key = self._task_lock_key(user_id, task_id)
        lock_token = await self._acquire_task_lock(lock_key)
        try:
            task = await self.get_task(task_id, user_id)
            if not task:
                return None
            task_version = task.get("version")
            if task_version is None:
                return None
            if int(task_version) != int(expected_version):
                return None
            replacement = await self._replace_task_key_wrappers_unlocked(user_id, task_id, wrappers, task=task)
            if replacement is None:
                return None
            created_wrappers, previous_wrappers = replacement
            version_touch = await self.directus_service.update_item_if_version(
                "user_tasks",
                task["id"],
                {"version": int(expected_version) + 1},
                int(expected_version),
                owner_hash_field="hashed_user_id",
                owner_hash=hash_id(user_id),
            )
            if not version_touch:
                if not await self._delete_key_wrappers(created_wrappers):
                    raise RuntimeError("Failed to clean up new user task key wrappers")
                await self._restore_task_key_wrappers(user_id, task_id, previous_wrappers)
                raise RuntimeError("Failed to advance task version after key wrapper replacement")
            return created_wrappers
        finally:
            await self._release_task_lock(lock_key, lock_token)

    async def _replace_task_key_wrappers_unlocked(self, user_id: str, task_id: str, wrappers: list[dict[str, Any]], *, task: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        task = task or await self.get_task(task_id, user_id)
        if not task:
            return None
        if not _validate_wrapper_set(
            wrappers,
            primary_chat_hash=task.get("hashed_primary_chat_id"),
            project_hashes=_coerce_hashes(task.get("linked_project_hashes")),
            plan_hash=hash_id(task["plan_id"]) if task.get("plan_id") else None,
            has_external_chat_context=task.get("external_chat_provider") is not None,
        ):
            return None
        existing_wrappers = await self.list_task_key_wrappers(user_id, task_id)
        created_wrappers: list[dict[str, Any]] = []
        for wrapper in wrappers:
            created_wrapper = await self.create_task_key_wrapper(user_id, task_id, wrapper)
            if not created_wrapper:
                for created in created_wrappers:
                    created_id = created.get("id")
                    if created_id:
                        await self.directus_service.delete_item("user_task_key_wrappers", created_id, admin_required=True)
                return None
            created_wrappers.append(created_wrapper)
        deleted_existing, deleted_existing_wrappers = await self._delete_key_wrappers_tracking(existing_wrappers)
        if not deleted_existing:
            if not await self._delete_key_wrappers(created_wrappers):
                raise RuntimeError("Failed to clean up new user task key wrappers")
            await self._restore_task_key_wrappers(user_id, task_id, deleted_existing_wrappers)
            raise RuntimeError("Failed to delete old user task key wrappers")
        return created_wrappers, existing_wrappers

    async def list_task_key_wrappers(self, user_id: str, task_id: str) -> list[dict[str, Any]]:
        params = {
            "filter[hashed_task_id][_eq]": hash_id(task_id),
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": USER_TASK_KEY_WRAPPER_FIELDS,
            "limit": 50,
        }
        response = await self.directus_service.get_items("user_task_key_wrappers", params=params, no_cache=True, admin_required=True)
        return response if isinstance(response, list) else []

    async def create_task_execution_context(
        self,
        *,
        user_id: str,
        task_id: str,
        chat_id: str,
        encrypted_context: str,
        created_at: int,
        expires_at: int,
    ) -> dict[str, Any] | None:
        if expires_at <= created_at:
            raise ValueError("Task execution context must expire after creation")
        record = {
            "hashed_user_id": hash_id(user_id),
            "hashed_task_id": hash_id(task_id),
            "hashed_chat_id": hash_id(chat_id),
            "encrypted_context": encrypted_context,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        success, data = await self.directus_service.create_item("user_task_execution_contexts", record, admin_required=True)
        if not success:
            logger.error("Failed to create user task execution context: %s", data)
            return None
        return data

    async def get_task_execution_context(self, *, user_id: str, task_id: str, chat_id: str, now: int) -> dict[str, Any] | None:
        params = {
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "filter[hashed_task_id][_eq]": hash_id(task_id),
            "filter[hashed_chat_id][_eq]": hash_id(chat_id),
            "filter[expires_at][_gt]": now,
            "fields": USER_TASK_EXECUTION_CONTEXT_FIELDS,
            "sort": "-created_at",
            "limit": 1,
        }
        response = await self.directus_service.get_items("user_task_execution_contexts", params=params, no_cache=True, admin_required=True)
        if response and isinstance(response, list):
            return response[0]
        return None

    async def get_task_execution_context_for_admission(self, task: dict[str, Any], *, now: int) -> dict[str, Any] | None:
        params = {
            "filter[hashed_task_id][_eq]": hash_id(str(task.get("task_id") or "")),
            "filter[hashed_chat_id][_eq]": hash_id(str(task.get("primary_chat_id") or "")),
            "filter[expires_at][_gt]": now,
            "fields": USER_TASK_EXECUTION_CONTEXT_FIELDS,
            "sort": "-created_at",
            "limit": 1,
        }
        response = await self.directus_service.get_items("user_task_execution_contexts", params=params, no_cache=True, admin_required=True)
        return response[0] if response and isinstance(response, list) else None

    async def delete_expired_task_execution_contexts(self, now: int, *, limit: int = 100) -> int:
        response = await self.directus_service.get_items(
            "user_task_execution_contexts",
            params={
                "filter[expires_at][_lte]": now,
                "fields": "id",
                "limit": max(1, min(limit, 500)),
            },
            no_cache=True,
            admin_required=True,
        )
        contexts = response if isinstance(response, list) else []
        deleted = 0
        for context in contexts:
            context_id = context.get("id")
            if context_id and await self.directus_service.delete_item("user_task_execution_contexts", context_id, admin_required=True) is not False:
                deleted += 1
        return deleted

    async def update_task(self, task_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        lock_key = self._task_lock_key(user_id, task_id)
        lock_token = await self._acquire_task_lock(lock_key)
        try:
            if patch.get("version") is None:
                raise ValueError("Task update requires expected version")
            existing = await self.get_task(task_id, user_id)
            if not existing:
                return None
            existing_version = existing.get("version")
            if existing_version is None:
                return None
            if int(existing_version) != int(patch.get("version") or 0):
                return None
            return await self._update_task_unlocked(task_id, user_id, patch, existing=existing)
        finally:
            await self._release_task_lock(lock_key, lock_token)

    async def update_task_if_version(
        self,
        task_id: str,
        user_id: str,
        patch: dict[str, Any],
        expected_version: int,
        *,
        team_id: str | None = None,
    ) -> dict[str, Any] | None:
        lock_key = self._task_lock_key(team_id or user_id, task_id)
        lock_token = await self._acquire_task_lock(lock_key)
        try:
            existing = await self.get_task(task_id, user_id, team_id)
            if not existing:
                return None
            existing_version = existing.get("version")
            if existing_version is None:
                return None
            if int(existing_version) != int(expected_version):
                return None
            patch_version = patch.get("version")
            committed_version = int(patch_version) if patch_version is not None and int(patch_version) != int(expected_version) else None
            return await self._update_task_unlocked(
                task_id,
                user_id,
                patch,
                existing=existing,
                committed_version=committed_version,
                team_id=team_id,
            )
        finally:
            await self._release_task_lock(lock_key, lock_token)

    async def _update_task_unlocked(
        self,
        task_id: str,
        user_id: str,
        patch: dict[str, Any],
        *,
        existing: dict[str, Any] | None = None,
        committed_version: int | None = None,
        team_id: str | None = None,
    ) -> dict[str, Any] | None:
        existing = existing or await self.get_task(task_id, user_id, team_id)
        if not existing:
            return None
        update = dict(patch)
        validate_encrypted_slug_metadata(update, record_label="Task")
        await self._ensure_slug_lookup_available(update.get("slug_lookup_hash"), user_id, exclude_row_id=existing.get("id"))
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
        next_plan_hash = hash_id(update["plan_id"]) if update.get("plan_id") else (hash_id(existing["plan_id"]) if existing.get("plan_id") else None)

        effective_context = {
            field: update[field] if field in update else existing.get(field)
            for field in (
                "primary_chat_id",
                "external_chat_provider",
                "external_chat_lookup_hash",
                "encrypted_external_chat_id",
                "encrypted_external_chat_title",
            )
        }
        _validate_external_chat_context(effective_context)
        effective_assignment = {
            field: update[field] if field in update else existing.get(field)
            for field in ("assignee_type", "assignee_identity", "assignee_hash")
        }
        _validate_task_assignment(effective_assignment, user_id=user_id)
        if any(field in update for field in ("assignee_type", "assignee_identity", "assignee_hash")):
            update.update(effective_assignment)

        relinks_context = next_chat_hash != existing_chat_hash or next_project_hashes != existing_project_hashes
        if relinks_context and not key_wrappers:
            logger.error("Rejected user task relink without replacement key wrappers")
            return None
        if next_project_hashes != existing_project_hashes and ("encrypted_linked_project_ids" not in update or update.get("encrypted_linked_project_ids") is None):
            logger.error("Rejected user task project relink without encrypted linked project ids")
            return None
        update.pop("task_id", None)
        update.pop("hashed_user_id", None)
        update.pop("version", None)
        if "label_hashes" in update:
            update["label_hashes"] = _coerce_blind_hashes(update.get("label_hashes") or [])
        if "priority" in update:
            update["priority"] = _coerce_priority(update.get("priority") or 0)
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
            plan_hash=next_plan_hash,
            has_external_chat_context=effective_context.get("external_chat_provider") is not None,
        ):
            return None
        if key_wrappers is not None:
            existing_wrappers = await self.list_task_key_wrappers(user_id, task_id)
            for wrapper in key_wrappers:
                created_wrapper = await self.create_task_key_wrapper(user_id, task_id, wrapper)
                if not created_wrapper:
                    await self._delete_key_wrappers(created_wrappers)
                    return None
                created_wrappers.append(created_wrapper)
        existing_version = existing.get("version")
        if existing_version is None:
            return None
        next_version = int(committed_version) if committed_version is not None else int(existing_version) + 1
        if next_version <= int(existing_version):
            return None
        if key_wrappers is not None:
            deleted_existing, deleted_existing_wrappers = await self._delete_key_wrappers_tracking(existing_wrappers)
            if not deleted_existing:
                if not await self._delete_key_wrappers(created_wrappers):
                    raise RuntimeError("Failed to clean up new user task key wrappers")
                await self._restore_task_key_wrappers(user_id, task_id, deleted_existing_wrappers)
                raise RuntimeError("Failed to delete old user task key wrappers")
            final_update = dict(update)
            final_update["version"] = next_version
            updated = await self.directus_service.update_item_if_version(
                "user_tasks",
                existing["id"],
                final_update,
                int(existing_version),
                owner_hash_field="hashed_team_id" if team_id else "hashed_user_id",
                owner_hash=hash_id(team_id or user_id),
            )
            if not updated:
                updated = await self._committed_task_after_empty_update(
                    task_id,
                    user_id,
                    next_version,
                    team_id=team_id,
                )
            if not updated:
                if is_slug_unique_violation(getattr(self.directus_service, "last_update_error", None)):
                    raise DuplicateObjectSlugError("Task slug already exists in this workspace")
                if not await self._delete_key_wrappers(created_wrappers):
                    raise RuntimeError("Failed to clean up new user task key wrappers")
                await self._restore_task_key_wrappers(user_id, task_id, existing_wrappers)
                return None
            return updated

        update["version"] = next_version
        updated = await self.directus_service.update_item_if_version(
            "user_tasks",
            existing["id"],
            update,
            int(existing_version),
            owner_hash_field="hashed_team_id" if team_id else "hashed_user_id",
            owner_hash=hash_id(team_id or user_id),
        )
        if not updated and is_slug_unique_violation(getattr(self.directus_service, "last_update_error", None)):
            raise DuplicateObjectSlugError("Task slug already exists in this workspace")
        return updated or await self._committed_task_after_empty_update(task_id, user_id, next_version, team_id=team_id)

    async def _ensure_slug_lookup_available(self, slug_lookup_hash: str | None, user_id: str, *, exclude_row_id: str | None = None) -> None:
        if not slug_lookup_hash:
            return
        params = {
            "filter": _slug_lookup_filter(user_id, slug_lookup_hash, exclude_row_id=exclude_row_id),
            "fields": "id",
            "limit": 1,
        }
        rows = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        if rows and isinstance(rows, list):
            raise DuplicateObjectSlugError("Task slug already exists in this workspace")

    async def _committed_task_after_empty_update(
        self,
        task_id: str,
        user_id: str,
        expected_version: int,
        *,
        team_id: str | None = None,
    ) -> dict[str, Any] | None:
        current = await self.get_task(task_id, user_id, team_id)
        if current and int(current.get("version") or 0) == int(expected_version):
            return current
        return None

    def _task_lock_key(self, user_id: str, task_id: str) -> str:
        return f"user_task_write_lock:{hash_id(user_id)}:{hash_id(task_id)}"

    async def _acquire_task_lock(self, key: str) -> str | None:
        cache = getattr(self.directus_service, "cache", None)
        if cache is None:
            raise RuntimeError("Task lock backend is unavailable")
        client_ref = getattr(cache, "client", None)
        if client_ref is None:
            raise RuntimeError("Task lock backend is unavailable")
        client = await client_ref
        if not client:
            raise RuntimeError("Task lock backend is unavailable")
        token = secrets.token_urlsafe(16)
        acquired = await client.set(key, token, nx=True, ex=30)
        if not acquired:
            raise TaskLockBusyError("Task is already being updated")
        return token

    async def _release_task_lock(self, key: str, token: str | None) -> None:
        if token is None:
            return
        cache = getattr(self.directus_service, "cache", None)
        if cache is None:
            return
        client_ref = getattr(cache, "client", None)
        if client_ref is None:
            return
        client = await client_ref
        if not client:
            return
        current = await client.get(key)
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current == token:
            await client.delete(key)

    async def _delete_key_wrappers(self, wrappers: list[dict[str, Any]]) -> bool:
        all_deleted, _deleted_wrappers = await self._delete_key_wrappers_tracking(wrappers)
        return all_deleted

    async def _delete_key_wrappers_tracking(self, wrappers: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
        all_deleted = True
        deleted_wrappers: list[dict[str, Any]] = []
        for wrapper in wrappers:
            wrapper_id = wrapper.get("id")
            if wrapper_id:
                deleted = await self.directus_service.delete_item("user_task_key_wrappers", wrapper_id, admin_required=True)
                if deleted is False:
                    logger.error("Failed to delete old user task key wrapper")
                    all_deleted = False
                else:
                    deleted_wrappers.append(wrapper)
        return all_deleted, deleted_wrappers

    async def _restore_task_key_wrappers(self, user_id: str, task_id: str, wrappers: list[dict[str, Any]]) -> None:
        restored: list[dict[str, Any]] = []
        for wrapper in wrappers:
            created = await self.create_task_key_wrapper(user_id, task_id, wrapper)
            if not created:
                await self._delete_key_wrappers(restored)
                raise RuntimeError("Failed to restore old user task key wrappers")
            restored.append(created)

    async def start_due_ai_task(self, task: dict[str, Any], now: int) -> dict[str, Any] | None:
        row_id = task.get("id")
        if not row_id:
            return None
        task_id = str(task.get("task_id") or "")
        owner_hash = str(task.get("hashed_user_id") or "")
        if not task_id or not owner_hash:
            return None
        lock_key = f"user_task_write_lock:{owner_hash}:{hash_id(task_id)}"
        lock_token = await self._acquire_task_lock(lock_key)
        update = {
            "status": "in_progress",
            "ai_execution_state": "queued",
            "started_at": now,
            "updated_at": now,
            "version": int(task["version"]) + 1,
        }
        try:
            return await self.directus_service.update_item_if_version(
                "user_tasks",
                row_id,
                update,
                int(task["version"]),
                owner_hash_field="hashed_user_id",
                owner_hash=owner_hash,
            )
        finally:
            await self._release_task_lock(lock_key, lock_token)

    async def claim_ai_task(self, task: dict[str, Any], now: int) -> dict[str, Any] | None:
        row_id = task.get("id")
        task_id = str(task.get("task_id") or "")
        version = task.get("version")
        team_hash = str(task.get("hashed_team_id") or "")
        user_hash = str(task.get("hashed_user_id") or "")
        owner_hash_field = "hashed_team_id" if team_hash else "hashed_user_id"
        owner_hash = team_hash or user_hash
        if not row_id or not task_id or version is None or not owner_hash:
            return None
        lock_key = f"user_task_write_lock:{owner_hash}:{hash_id(task_id)}"
        lock_token = await self._acquire_task_lock(lock_key)
        try:
            return await self.directus_service.update_item_if_version(
                "user_tasks",
                row_id,
                {
                    "status": "in_progress",
                    "queue_state": "active",
                    "ai_execution_state": "queued",
                    "started_at": task.get("started_at") or now,
                    "updated_at": now,
                    "version": int(version) + 1,
                },
                int(version),
                owner_hash_field=owner_hash_field,
                owner_hash=owner_hash,
            )
        finally:
            await self._release_task_lock(lock_key, lock_token)

    async def set_ai_task_waiting(self, task: dict[str, Any], state: str, now: int) -> dict[str, Any] | None:
        row_id = task.get("id")
        task_id = str(task.get("task_id") or "")
        version = task.get("version")
        team_hash = str(task.get("hashed_team_id") or "")
        user_hash = str(task.get("hashed_user_id") or "")
        owner_hash_field = "hashed_team_id" if team_hash else "hashed_user_id"
        owner_hash = team_hash or user_hash
        if not row_id or not task_id or version is None or not owner_hash:
            return None
        lock_key = f"user_task_write_lock:{owner_hash}:{hash_id(task_id)}"
        lock_token = await self._acquire_task_lock(lock_key)
        try:
            return await self.directus_service.update_item_if_version(
                "user_tasks",
                row_id,
                {
                    "status": "todo",
                    "queue_state": "waiting",
                    "ai_execution_state": state,
                    "updated_at": now,
                    "version": int(version) + 1,
                },
                int(version),
                owner_hash_field=owner_hash_field,
                owner_hash=owner_hash,
            )
        finally:
            await self._release_task_lock(lock_key, lock_token)

    async def fail_stale_queued_ai_task(self, task: dict[str, Any], now: int) -> dict[str, Any] | None:
        row_id = task.get("id")
        task_id = str(task.get("task_id") or "")
        version = task.get("version")
        team_hash = str(task.get("hashed_team_id") or "")
        user_hash = str(task.get("hashed_user_id") or "")
        owner_hash_field = "hashed_team_id" if team_hash else "hashed_user_id"
        owner_hash = team_hash or user_hash
        if not row_id or not task_id or version is None or not owner_hash:
            return None
        lock_key = f"user_task_write_lock:{owner_hash}:{hash_id(task_id)}"
        lock_token = await self._acquire_task_lock(lock_key)
        try:
            return await self.directus_service.update_item_if_version(
                "user_tasks",
                row_id,
                {
                    "status": "blocked",
                    "queue_state": "waiting_for_user",
                    "ai_execution_state": "failed",
                    "blocked_reason_code": "ai_dispatch_timeout",
                    "updated_at": now,
                    "version": int(version) + 1,
                },
                int(version),
                owner_hash_field=owner_hash_field,
                owner_hash=owner_hash,
            )
        finally:
            await self._release_task_lock(lock_key, lock_token)

    async def claim_queued_ai_task_execution(
        self,
        task_id: str,
        user_id: str,
        *,
        team_id: str | None = None,
        now: int,
    ) -> dict[str, Any] | None:
        lock_key = self._task_lock_key(team_id or user_id, task_id)
        lock_token = await self._acquire_task_lock(lock_key)
        try:
            existing = await self.get_task(task_id, user_id, team_id)
            if (
                not existing
                or existing.get("status") != "in_progress"
                or existing.get("queue_state") != "active"
                or existing.get("ai_execution_state") != "queued"
            ):
                return None
            return await self._update_task_unlocked(
                task_id,
                user_id,
                {
                    "status": "in_progress",
                    "queue_state": "active",
                    "ai_execution_state": "running",
                    "updated_at": now,
                },
                existing=existing,
                team_id=team_id,
            )
        finally:
            await self._release_task_lock(lock_key, lock_token)

    async def fail_claimed_ai_task(self, task: dict[str, Any], reason: str, now: int) -> dict[str, Any] | None:
        row_id = task.get("id")
        version = task.get("version")
        team_hash = str(task.get("hashed_team_id") or "")
        user_hash = str(task.get("hashed_user_id") or "")
        owner_hash_field = "hashed_team_id" if team_hash else "hashed_user_id"
        owner_hash = team_hash or user_hash
        if not row_id or version is None or not owner_hash:
            return None
        return await self.directus_service.update_item_if_version(
            "user_tasks",
            row_id,
            {
                "status": "blocked",
                "queue_state": "waiting_for_user",
                "ai_execution_state": "failed",
                "blocked_reason_code": reason,
                "updated_at": now,
                "version": int(version) + 1,
            },
            int(version),
            owner_hash_field=owner_hash_field,
            owner_hash=owner_hash,
        )

    async def acquire_admission_lock(self, scope: str, scope_id: str) -> str | None:
        return await self._acquire_task_lock(f"user_task_admission_lock:{scope}:{hash_id(scope_id)}")

    async def release_admission_lock(self, scope: str, scope_id: str, token: str | None) -> None:
        await self._release_task_lock(f"user_task_admission_lock:{scope}:{hash_id(scope_id)}", token)

    async def acquire_hashed_admission_lock(self, scope: str, owner_hash: str) -> str | None:
        return await self._acquire_task_lock(f"user_task_admission_lock:{scope}:{owner_hash}")

    async def release_hashed_admission_lock(self, scope: str, owner_hash: str, token: str | None) -> None:
        await self._release_task_lock(f"user_task_admission_lock:{scope}:{owner_hash}", token)

    async def delete_task(self, task_id: str, user_id: str, expected_version: int, *, team_id: str | None = None) -> bool:
        lock_key = self._task_lock_key(team_id or user_id, task_id)
        lock_token = await self._acquire_task_lock(lock_key)
        try:
            existing = await self.get_task(task_id, user_id, team_id)
            if not existing:
                return False
            existing_version = existing.get("version")
            if existing_version is None:
                return False
            if int(existing_version) != int(expected_version):
                return False
            return await self.directus_service.delete_item("user_tasks", existing["id"])
        finally:
            await self._release_task_lock(lock_key, lock_token)
