# backend/core/api/app/services/directus/project_methods.py
#
# Directus access helpers for Projects V1. Projects are client-encrypted
# workspaces: the backend only sees hashed ids and opaque encrypted metadata.

import hashlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


PROJECT_FIELDS = (
    "id,project_id,hashed_user_id,encrypted_project_key,encrypted_name,"
    "encrypted_description,encrypted_icon,encrypted_color,pinned,archived,"
    "is_private,is_shared,created_at,updated_at,last_opened_at,item_count"
)
FOLDER_FIELDS = (
    "id,folder_id,hashed_project_id,hashed_parent_folder_id,hashed_user_id,"
    "encrypted_name,encrypted_sort_key,created_at,updated_at,position"
)
ITEM_FIELDS = (
    "id,project_item_id,hashed_project_id,hashed_folder_id,hashed_user_id,"
    "item_type,target_id_hash,target_id_encrypted,encrypted_display_name,"
    "encrypted_note,encrypted_metadata,deleted_target_state,created_at,updated_at,position"
)


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ProjectMethods:
    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def list_projects(self, user_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
        hashed_user_id = hash_id(user_id)
        params: Dict[str, Any] = {
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "fields": PROJECT_FIELDS,
            "sort": "-pinned,-last_opened_at,-updated_at",
            "limit": -1,
        }
        if not include_archived:
            params["filter[archived][_neq]"] = True

        response = await self.directus_service.get_items("projects", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def get_project(self, project_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        hashed_user_id = hash_id(user_id)
        params = {
            "filter[project_id][_eq]": project_id,
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "fields": PROJECT_FIELDS,
            "limit": 1,
        }
        response = await self.directus_service.get_items("projects", params=params, no_cache=True)
        if response and isinstance(response, list):
            return response[0]
        return None

    async def create_project(self, user_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        now = payload.get("created_at") or payload.get("updated_at")
        record = {
            **payload,
            "hashed_user_id": hash_id(user_id),
            "pinned": payload.get("pinned", False),
            "archived": payload.get("archived", False),
            "is_private": payload.get("is_private", True),
            "is_shared": payload.get("is_shared", False),
            "created_at": now,
            "updated_at": payload.get("updated_at", now),
            "last_opened_at": payload.get("last_opened_at", now),
            "item_count": payload.get("item_count", 0),
        }
        success, data = await self.directus_service.create_item("projects", record)
        if not success:
            logger.error("Failed to create project: %s", data)
            return None
        return data

    async def update_project(self, project_id: str, user_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        existing = await self.get_project(project_id, user_id)
        if not existing:
            return None
        return await self.directus_service.update_item("projects", existing["id"], patch)

    async def delete_project(self, project_id: str, user_id: str) -> bool:
        existing = await self.get_project(project_id, user_id)
        if not existing:
            return False

        hashed_project_id = hash_id(project_id)
        await self.delete_project_items_by_project_hash(hashed_project_id, user_id)
        await self.delete_project_folders_by_project_hash(hashed_project_id, user_id)
        return await self.directus_service.delete_item("projects", existing["id"])

    async def list_folders(self, project_id: str, user_id: str) -> List[Dict[str, Any]]:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": FOLDER_FIELDS,
            "sort": "position,created_at",
            "limit": -1,
        }
        response = await self.directus_service.get_items("project_folders", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def create_folder(self, user_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        record = {
            **payload,
            "hashed_user_id": hash_id(user_id),
        }
        success, data = await self.directus_service.create_item("project_folders", record)
        if not success:
            logger.error("Failed to create project folder: %s", data)
            return None
        return data

    async def folder_exists(self, project_id: str, folder_id: str, user_id: str) -> bool:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "filter[folder_id][_eq]": folder_id,
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": "id",
            "limit": 1,
        }
        response = await self.directus_service.get_items("project_folders", params=params, no_cache=True)
        return bool(response and isinstance(response, list))

    async def delete_project_folders_by_project_hash(self, hashed_project_id: str, user_id: str) -> int:
        return await self.directus_service.delete_items(
            "project_folders",
            {
                "hashed_project_id": {"_eq": hashed_project_id},
                "hashed_user_id": {"_eq": hash_id(user_id)},
            },
        )

    async def list_items(self, project_id: str, user_id: str) -> List[Dict[str, Any]]:
        params = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": ITEM_FIELDS,
            "sort": "position,created_at",
            "limit": -1,
        }
        response = await self.directus_service.get_items("project_items", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def create_item(self, user_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        record = {
            **payload,
            "hashed_user_id": hash_id(user_id),
        }
        success, data = await self.directus_service.create_item("project_items", record)
        if not success:
            logger.error("Failed to create project item: %s", data)
            return None
        await self.increment_project_item_count(payload.get("hashed_project_id"), 1)
        return data

    async def delete_project_items_by_project_hash(self, hashed_project_id: str, user_id: str) -> int:
        return await self.directus_service.delete_items(
            "project_items",
            {
                "hashed_project_id": {"_eq": hashed_project_id},
                "hashed_user_id": {"_eq": hash_id(user_id)},
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
        }
        params = {
            "filter[target_id_hash][_in]": ",".join(target_hashes),
            "filter[item_type][_eq]": item_type,
            "filter[hashed_user_id][_eq]": hashed_user_id,
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

    async def increment_project_item_count(self, hashed_project_id: Optional[str], delta: int) -> None:
        if not hashed_project_id:
            return
        params = {
            "filter[hashed_project_id][_eq]": hashed_project_id,
            "fields": "id,item_count",
            "limit": 1,
        }
        rows = await self.directus_service.get_items("projects", params=params, no_cache=True)
        if not rows or not isinstance(rows, list):
            return
        project = rows[0]
        count = max(0, int(project.get("item_count") or 0) + delta)
        await self.directus_service.update_item("projects", project["id"], {"item_count": count})
