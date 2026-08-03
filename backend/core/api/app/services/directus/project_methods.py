# backend/core/api/app/services/directus/project_methods.py
#
# Directus access helpers for Projects V1. Projects are client-encrypted
# workspaces: the backend only sees hashed ids and opaque encrypted metadata.

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
PROJECT_KEY_WRAPPER_TYPES = {"master", "chat", "project", "plan", "team"}


PROJECT_FIELDS = (
    "id,project_id,hashed_user_id,hashed_team_id,created_by_user_hash,encrypted_project_key,encrypted_name,"
    "encrypted_description,encrypted_icon,encrypted_color,pinned,archived,"
    "is_private,is_shared,version,created_at,updated_at,last_opened_at,item_count"
)
FOLDER_FIELDS = (
    "id,folder_id,hashed_project_id,hashed_parent_folder_id,hashed_user_id,hashed_team_id,created_by_user_hash,"
    "encrypted_name,encrypted_sort_key,created_at,updated_at,position"
)
ITEM_FIELDS = (
    "id,project_item_id,hashed_project_id,hashed_folder_id,hashed_user_id,hashed_team_id,attached_by_user_hash,"
    "item_type,target_id_hash,target_id_encrypted,encrypted_display_name,"
    "encrypted_note,encrypted_metadata,deleted_target_state,created_at,updated_at,position"
)
SOURCE_FIELDS = (
    "id,source_id,hashed_project_id,hashed_user_id,hashed_team_id,attached_by_user_hash,source_type,"
    "encrypted_display_name,encrypted_metadata,capabilities,status,"
    "created_at,updated_at,last_indexed_at"
)
PROJECT_SETTINGS_FIELDS = (
    "id,hashed_project_id,hashed_user_id,hashed_team_id,updated_by_user_hash,write_mode,encrypted_settings,updated_at"
)
PROJECT_KEY_WRAPPER_FIELDS = (
    "id,hashed_project_id,hashed_user_id,key_type,hashed_chat_id,hashed_plan_id,"
    "hashed_team_id,team_key_epoch,encrypted_project_key,wrapper_version,created_at,expires_at"
)


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _is_sha256_hex(value: str | None) -> bool:
    return bool(value and SHA256_HEX_RE.fullmatch(value))


def _validate_project_key_wrapper(wrapper: dict[str, Any]) -> bool:
    key_type = wrapper.get("key_type")
    if key_type not in PROJECT_KEY_WRAPPER_TYPES:
        logger.error("Rejected project key wrapper with invalid key_type")
        return False
    if not wrapper.get("encrypted_project_key"):
        logger.error("Rejected project key wrapper without encrypted key material")
        return False

    hashed_chat_id = wrapper.get("hashed_chat_id")
    hashed_plan_id = wrapper.get("hashed_plan_id")
    hashed_team_id = wrapper.get("hashed_team_id")
    team_key_epoch = wrapper.get("team_key_epoch")
    if hashed_chat_id is not None and not _is_sha256_hex(hashed_chat_id):
        return False
    if hashed_plan_id is not None and not _is_sha256_hex(hashed_plan_id):
        return False
    if hashed_team_id is not None and not _is_sha256_hex(hashed_team_id):
        return False
    if key_type in {"master", "project"} and any(value is not None for value in (hashed_chat_id, hashed_plan_id, hashed_team_id)):
        return False
    if key_type == "chat" and (hashed_chat_id is None or hashed_plan_id is not None or hashed_team_id is not None):
        return False
    if key_type == "plan" and (hashed_plan_id is None or hashed_chat_id is not None or hashed_team_id is not None):
        return False
    if key_type == "team":
        if hashed_team_id is None or hashed_chat_id is not None or hashed_plan_id is not None:
            return False
        if not isinstance(team_key_epoch, int) or team_key_epoch < 1:
            return False
    return True


def _owner_params(user_id: str, team_id: str | None) -> dict[str, Any]:
    if team_id:
        return {"filter[hashed_team_id][_eq]": hash_id(team_id)}
    return {
        "filter[hashed_user_id][_eq]": hash_id(user_id),
        "filter[hashed_team_id][_null]": True,
    }


def _owner_filter(user_id: str, team_id: str | None) -> dict[str, Any]:
    if team_id:
        return {"hashed_team_id": {"_eq": hash_id(team_id)}}
    return {
        "hashed_user_id": {"_eq": hash_id(user_id)},
        "hashed_team_id": {"_null": True},
    }


def _owner_record(user_id: str, team_id: str | None) -> dict[str, Any]:
    return {
        "hashed_user_id": None if team_id else hash_id(user_id),
        "hashed_team_id": hash_id(team_id) if team_id else None,
    }


class ProjectMoveError(RuntimeError):
    """Raised when a Personal Project cannot move atomically into a Team."""


class ProjectMethods:
    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def list_projects(self, user_id: str, include_archived: bool = False, team_id: str | None = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "fields": PROJECT_FIELDS,
            "sort": "-pinned,-last_opened_at,-updated_at",
            "limit": -1,
        }
        params.update(_owner_params(user_id, team_id))
        if not include_archived:
            params["filter[archived][_neq]"] = True

        response = await self.directus_service.get_items("projects", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def get_project(self, project_id: str, user_id: str, team_id: str | None = None) -> Optional[Dict[str, Any]]:
        params = {
            "filter[project_id][_eq]": project_id,
            "fields": PROJECT_FIELDS,
            "limit": 1,
        }
        params.update(_owner_params(user_id, team_id))
        response = await self.directus_service.get_items("projects", params=params, no_cache=True)
        if response and isinstance(response, list):
            return response[0]
        return None

    async def create_project(
        self,
        user_id: str,
        payload: Dict[str, Any],
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        key_wrappers = payload.pop("key_wrappers", []) or []
        now = payload.get("created_at") or payload.get("updated_at")
        record = {
            **payload,
            **_owner_record(user_id, team_id),
            "created_by_user_hash": hash_id(user_id),
            "pinned": payload.get("pinned", False),
            "archived": payload.get("archived", False),
            "is_private": payload.get("is_private", True),
            "is_shared": payload.get("is_shared", False),
            "version": 1,
            "created_at": now,
            "updated_at": payload.get("updated_at", now),
            "last_opened_at": payload.get("last_opened_at", now),
            "item_count": payload.get("item_count", 0),
        }
        if key_wrappers and not all(_validate_project_key_wrapper(wrapper) for wrapper in key_wrappers):
            return None
        success, data = await self.directus_service.create_item("projects", record)
        if not success:
            logger.error("Failed to create project: %s", data)
            return None
        created_wrappers: list[dict[str, Any]] = []
        for wrapper in key_wrappers:
            created_wrapper = await self.create_project_key_wrapper(
                user_id,
                payload["project_id"],
                wrapper,
                team_id=team_id,
            )
            if not created_wrapper:
                for created in created_wrappers:
                    wrapper_id = created.get("id")
                    if wrapper_id:
                        await self.directus_service.delete_item("project_key_wrappers", wrapper_id)
                row_id = data.get("id") if isinstance(data, dict) else None
                if row_id:
                    await self.directus_service.delete_item("projects", row_id)
                return None
            created_wrappers.append(created_wrapper)
        return data

    async def create_project_key_wrapper(
        self,
        user_id: str,
        project_id: str,
        wrapper: Dict[str, Any],
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not _validate_project_key_wrapper(wrapper):
            return None
        record = {
            "hashed_project_id": hash_id(project_id),
            "hashed_user_id": None if team_id else hash_id(user_id),
            "key_type": wrapper.get("key_type"),
            "hashed_chat_id": wrapper.get("hashed_chat_id"),
            "hashed_plan_id": wrapper.get("hashed_plan_id"),
            "hashed_team_id": wrapper.get("hashed_team_id"),
            "team_key_epoch": wrapper.get("team_key_epoch"),
            "encrypted_project_key": wrapper.get("encrypted_project_key"),
            "wrapper_version": wrapper.get("wrapper_version", 1),
            "created_at": wrapper.get("created_at"),
            "expires_at": wrapper.get("expires_at"),
        }
        success, data = await self.directus_service.create_item("project_key_wrappers", record)
        if not success:
            logger.error("Failed to create project key wrapper: %s", data)
            return None
        return data

    async def list_project_key_wrappers(
        self,
        user_id: str,
        project_id: str,
        team_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "fields": PROJECT_KEY_WRAPPER_FIELDS,
            "limit": 50,
        }
        params.update(_owner_params(user_id, team_id))
        response = await self.directus_service.get_items("project_key_wrappers", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def update_project(
        self,
        project_id: str,
        user_id: str,
        patch: Dict[str, Any],
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        existing = await self.get_project(project_id, user_id, team_id=team_id)
        if not existing:
            return None
        update = dict(patch)
        update["version"] = int(existing.get("version") or 1) + 1
        return await self.directus_service.update_item("projects", existing["id"], update)

    async def list_sources(
        self,
        project_id: str,
        user_id: str,
        team_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "fields": SOURCE_FIELDS,
            "sort": "created_at",
            "limit": -1,
        }
        params.update(_owner_params(user_id, team_id))
        response = await self.directus_service.get_items("project_sources", params=params, no_cache=True)
        if not isinstance(response, list):
            raise RuntimeError("Failed to list Project sources")
        return response

    async def get_source(
        self,
        project_id: str,
        user_id: str,
        source_id: str,
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "filter[source_id][_eq]": source_id,
            "fields": SOURCE_FIELDS,
            "limit": 1,
        }
        params.update(_owner_params(user_id, team_id))
        rows = await self.directus_service.get_items("project_sources", params=params, no_cache=True)
        return rows[0] if isinstance(rows, list) and rows else None

    async def create_source(
        self,
        project_id: str,
        user_id: str,
        payload: Dict[str, Any],
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        record = {
            "source_id": payload["source_id"],
            "hashed_project_id": hash_id(project_id),
            **_owner_record(user_id, team_id),
            "attached_by_user_hash": hash_id(user_id),
            "source_type": payload["source_type"],
            "encrypted_display_name": payload["encrypted_display_name"],
            "encrypted_metadata": payload["encrypted_metadata"],
            "capabilities": payload.get("capabilities", []),
            "status": payload.get("status", "connected"),
            "created_at": payload["created_at"],
            "updated_at": payload["updated_at"],
            "last_indexed_at": payload.get("last_indexed_at"),
        }
        success, data = await self.directus_service.create_item("project_sources", record)
        if not success:
            logger.error("Failed to create project source: %s", data)
            return None
        return data

    async def delete_source(
        self,
        project_id: str,
        user_id: str,
        source_id: str,
        team_id: str | None = None,
    ) -> bool:
        source = await self.get_source(project_id, user_id, source_id, team_id=team_id)
        if not source:
            return False
        return bool(await self.directus_service.delete_item("project_sources", source["id"]))

    async def get_project_settings(
        self,
        project_id: str,
        user_id: str,
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "fields": PROJECT_SETTINGS_FIELDS,
            "limit": 1,
        }
        params.update(_owner_params(user_id, team_id))
        rows = await self.directus_service.get_items("project_settings", params=params, no_cache=True)
        if rows and isinstance(rows, list):
            return rows[0]
        return None

    async def upsert_project_settings(
        self,
        project_id: str,
        user_id: str,
        payload: Dict[str, Any],
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        record = {
            "hashed_project_id": hash_id(project_id),
            **_owner_record(user_id, team_id),
            "updated_by_user_hash": hash_id(user_id),
            "write_mode": payload["write_mode"],
            "encrypted_settings": payload.get("encrypted_settings"),
            "updated_at": payload["updated_at"],
        }
        existing = await self.get_project_settings(project_id, user_id, team_id=team_id)
        if existing:
            return await self.directus_service.update_item("project_settings", existing["id"], record)

        success, data = await self.directus_service.create_item("project_settings", record)
        if not success:
            logger.error("Failed to create project settings: %s", data)
            return None
        return data

    async def delete_project(
        self,
        project_id: str,
        user_id: str,
        team_id: str | None = None,
    ) -> bool:
        existing = await self.get_project(project_id, user_id, team_id=team_id)
        if not existing:
            return False

        hashed_project_id = hash_id(project_id)
        await self.delete_project_items_by_project_hash(hashed_project_id, user_id, team_id=team_id)
        await self.delete_project_folders_by_project_hash(hashed_project_id, user_id, team_id=team_id)
        owner_filter = {"hashed_project_id": {"_eq": hashed_project_id}, **_owner_filter(user_id, team_id)}
        for collection in ("project_sources", "project_settings"):
            await self.directus_service.delete_items(collection, owner_filter)
        await self.directus_service.delete_items(
            "project_key_wrappers",
            {"hashed_project_id": {"_eq": hashed_project_id}},
        )
        return await self.directus_service.delete_item("projects", existing["id"])

    async def move_project_to_team(
        self,
        project_id: str,
        user_id: str,
        team_id: str,
        wrapper: Dict[str, Any],
        *,
        moved_at: int | None = None,
    ) -> Dict[str, Any]:
        project = await self.get_project(project_id, user_id)
        if not project:
            raise ProjectMoveError("Project not found in Personal context")
        expected_team_hash = hash_id(team_id)
        if (
            not _validate_project_key_wrapper(wrapper)
            or wrapper.get("key_type") != "team"
            or wrapper.get("hashed_team_id") != expected_team_hash
            or wrapper.get("team_key_epoch") != 1
        ):
            raise ProjectMoveError("A matching Team epoch-1 Project key wrapper is required")

        hashed_project_id = hash_id(project_id)
        actor_hash = hash_id(user_id)
        actor_fields = {
            "project_folders": "created_by_user_hash",
            "project_items": "attached_by_user_hash",
            "project_sources": "attached_by_user_hash",
            "project_settings": "updated_by_user_hash",
        }
        child_rows: list[tuple[str, str, dict[str, Any]]] = []
        for collection, actor_field in actor_fields.items():
            rows = await self.directus_service.get_items(
                collection,
                params={
                    "filter[hashed_project_id][_eq]": hashed_project_id,
                    "fields": f"id,hashed_user_id,hashed_team_id,{actor_field}",
                    "limit": -1,
                },
                no_cache=True,
            )
            if not isinstance(rows, list):
                raise ProjectMoveError("Failed to preflight Project child rows")
            if any(
                row.get("hashed_user_id") != actor_hash
                or row.get("hashed_team_id") is not None
                or not row.get(actor_field)
                for row in rows
            ):
                raise ProjectMoveError("Project child ownership does not match Personal context")
            child_rows.extend((collection, actor_field, row) for row in rows)

        created_wrapper = await self.create_project_key_wrapper(
            user_id,
            project_id,
            wrapper,
            team_id=team_id,
        )
        if not created_wrapper or not created_wrapper.get("id"):
            raise ProjectMoveError("Failed to persist Team Project key wrapper")

        moved_children: list[tuple[str, str, dict[str, Any]]] = []
        parent_update_attempted = False
        try:
            for collection, actor_field, row in child_rows:
                moved_children.append((collection, actor_field, row))
                updated = await self.directus_service.update_item(
                    collection,
                    row["id"],
                    {
                        "hashed_user_id": None,
                        "hashed_team_id": expected_team_hash,
                        actor_field: row.get(actor_field) or actor_hash,
                    },
                )
                if not updated:
                    raise ProjectMoveError("Failed to move Project child rows")

            parent_update_attempted = True
            updated_project = await self.directus_service.update_item(
                "projects",
                project["id"],
                {
                    "hashed_user_id": None,
                    "hashed_team_id": expected_team_hash,
                    "created_by_user_hash": project.get("created_by_user_hash") or actor_hash,
                    "updated_at": moved_at if moved_at is not None else project.get("updated_at"),
                },
            )
            if not updated_project:
                raise ProjectMoveError("Failed to move Project owner context")
            return updated_project
        except Exception as exc:
            rollback_failed = False
            if parent_update_attempted:
                restored_project = await self.directus_service.update_item(
                    "projects",
                    project["id"],
                    {
                        "hashed_user_id": project.get("hashed_user_id"),
                        "hashed_team_id": project.get("hashed_team_id"),
                        "created_by_user_hash": project.get("created_by_user_hash"),
                        "updated_at": project.get("updated_at"),
                    },
                )
                rollback_failed = not bool(restored_project)
            for collection, actor_field, row in reversed(moved_children):
                restored = await self.directus_service.update_item(
                    collection,
                    row["id"],
                    {
                        "hashed_user_id": row.get("hashed_user_id"),
                        "hashed_team_id": row.get("hashed_team_id"),
                        actor_field: row.get(actor_field),
                    },
                )
                rollback_failed = rollback_failed or not bool(restored)
            wrapper_deleted = await self.directus_service.delete_item(
                "project_key_wrappers",
                created_wrapper["id"],
            )
            if rollback_failed or not wrapper_deleted:
                raise ProjectMoveError("Project move failed and rollback was incomplete") from exc
            if isinstance(exc, ProjectMoveError):
                raise
            raise ProjectMoveError("Project move failed before parent mutation") from exc

    async def list_folders(self, project_id: str, user_id: str, team_id: str | None = None) -> List[Dict[str, Any]]:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "fields": FOLDER_FIELDS,
            "sort": "position,created_at",
            "limit": -1,
        }
        params.update(_owner_params(user_id, team_id))
        response = await self.directus_service.get_items("project_folders", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def create_folder(
        self,
        user_id: str,
        payload: Dict[str, Any],
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        record = {
            **payload,
            **_owner_record(user_id, team_id),
            "created_by_user_hash": hash_id(user_id),
        }
        success, data = await self.directus_service.create_item("project_folders", record)
        if not success:
            logger.error("Failed to create project folder: %s", data)
            return None
        return data

    async def folder_exists(
        self,
        project_id: str,
        folder_id: str,
        user_id: str,
        team_id: str | None = None,
    ) -> bool:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "filter[folder_id][_eq]": folder_id,
            "fields": "id",
            "limit": 1,
        }
        params.update(_owner_params(user_id, team_id))
        response = await self.directus_service.get_items("project_folders", params=params, no_cache=True)
        return bool(response and isinstance(response, list))

    async def delete_project_folders_by_project_hash(
        self,
        hashed_project_id: str,
        user_id: str,
        team_id: str | None = None,
    ) -> int:
        return await self.directus_service.delete_items(
            "project_folders",
            {"hashed_project_id": {"_eq": hashed_project_id}, **_owner_filter(user_id, team_id)},
        )

    async def list_items(self, project_id: str, user_id: str, team_id: str | None = None) -> List[Dict[str, Any]]:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "fields": ITEM_FIELDS,
            "sort": "position,created_at",
            "limit": -1,
        }
        params.update(_owner_params(user_id, team_id))
        response = await self.directus_service.get_items("project_items", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def create_item(
        self,
        user_id: str,
        payload: Dict[str, Any],
        team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        record = {
            **payload,
            **_owner_record(user_id, team_id),
            "attached_by_user_hash": hash_id(user_id),
        }
        success, data = await self.directus_service.create_item("project_items", record)
        if not success:
            logger.error("Failed to create project item: %s", data)
            return None
        await self.increment_project_item_count(payload.get("hashed_project_id"), 1, user_id, team_id=team_id)
        return data

    async def delete_item_for_project_target(
        self,
        project_id: str,
        item_type: str,
        target_id: str,
        user_id: str,
        team_id: str | None = None,
    ) -> int:
        hashed_project_id = hash_id(project_id)
        deleted = await self.directus_service.delete_items(
            "project_items",
            {
                "hashed_project_id": {"_eq": hashed_project_id},
                "target_id_hash": {"_eq": hash_id(target_id)},
                "item_type": {"_eq": item_type},
                **_owner_filter(user_id, team_id),
            },
        )
        if deleted:
            await self.increment_project_item_count(hashed_project_id, -deleted, user_id, team_id=team_id)
        return deleted

    async def delete_project_items_by_project_hash(
        self,
        hashed_project_id: str,
        user_id: str,
        team_id: str | None = None,
    ) -> int:
        return await self.directus_service.delete_items(
            "project_items",
            {
                "hashed_project_id": {"_eq": hashed_project_id},
                **_owner_filter(user_id, team_id),
            },
        )

    async def remove_items_for_target_hashes(
        self,
        target_hashes: List[str],
        item_type: str,
        user_id: str,
    ) -> int:
        if not target_hashes:
            return 0
        hashed_user_id = hash_id(user_id)
        filters = {
            "target_id_hash": {"_in": target_hashes},
            "item_type": {"_eq": item_type},
            "hashed_user_id": {"_eq": hashed_user_id},
            "hashed_team_id": {"_null": True},
        }
        params = {
            "filter[target_id_hash][_in]": ",".join(target_hashes),
            "filter[item_type][_eq]": item_type,
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "filter[hashed_team_id][_null]": True,
            "fields": "hashed_project_id",
            "limit": -1,
        }
        rows = await self.directus_service.get_items("project_items", params=params, no_cache=True)
        deleted = await self.directus_service.delete_items(
            "project_items",
            filters,
        )
        if deleted and rows and isinstance(rows, list):
            project_counts: Dict[str, int] = {}
            for row in rows:
                hashed_project_id = row.get("hashed_project_id")
                if hashed_project_id:
                    project_counts[hashed_project_id] = (
                        project_counts.get(hashed_project_id, 0) + 1
                    )
            for hashed_project_id, count in project_counts.items():
                await self.increment_project_item_count(hashed_project_id, -count)
        return deleted

    async def get_project_embed_reference_counts(self, embed_ids: List[str], user_id: str) -> Dict[str, int]:
        if not embed_ids:
            return {}
        embed_hashes = {hash_id(embed_id): embed_id for embed_id in embed_ids if embed_id}
        if not embed_hashes:
            return {}

        params = {
            "filter[item_type][_eq]": "embed",
            "filter[target_id_hash][_in]": ",".join(embed_hashes.keys()),
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "filter[hashed_team_id][_null]": True,
            "fields": "target_id_hash,hashed_project_id",
            "limit": -1,
        }
        response = await self.directus_service.get_items("project_items", params=params, no_cache=True)
        counts: Dict[str, set[str]] = {embed_id: set() for embed_id in embed_hashes.values()}
        if response and isinstance(response, list):
            for row in response:
                target_hash = row.get("target_id_hash")
                project_hash = row.get("hashed_project_id")
                embed_id = embed_hashes.get(target_hash)
                if embed_id and project_hash:
                    counts.setdefault(embed_id, set()).add(project_hash)
        return {embed_id: len(project_hashes) for embed_id, project_hashes in counts.items()}

    async def increment_project_item_count(
        self,
        hashed_project_id: Optional[str],
        delta: int,
        user_id: str | None = None,
        team_id: str | None = None,
    ) -> None:
        if not hashed_project_id:
            return
        params = {
            "filter[hashed_project_id][_eq]": hashed_project_id,
            "fields": "id,item_count",
            "limit": 1,
        }
        if user_id is not None:
            params.update(_owner_params(user_id, team_id))
        rows = await self.directus_service.get_items("projects", params=params, no_cache=True)
        if not rows or not isinstance(rows, list):
            return
        project = rows[0]
        count = max(0, int(project.get("item_count") or 0) + delta)
        await self.directus_service.update_item("projects", project["id"], {"item_count": count})
