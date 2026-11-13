# backend/core/api/app/services/directus/project_commit_methods.py
#
# Directus access helpers for native Project commits. A commit is an
# append-only, client-encrypted pointer set over hosted-file revision history.
# There is intentionally no update or single-row delete: history is never
# rewritten. Rows are removed only with their Project.

import logging
from typing import Any, Dict, List, Optional

from backend.core.api.app.services.directus.project_methods import hash_id, _owner_filter, _owner_params, _owner_record

logger = logging.getLogger(__name__)

COMMIT_FIELDS = (
    "id,commit_id,hashed_project_id,hashed_user_id,hashed_team_id,created_by_user_hash,author_kind,"
    "hashed_chat_id,encrypted_message,encrypted_paths,entries,entry_count,restored_from_commit_id,created_at"
)


class ProjectCommitMethods:
    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def list_commits(
        self,
        project_id: str,
        user_id: str,
        team_id: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return one page of commits, newest first (fetches limit rows)."""
        params: Dict[str, Any] = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "fields": COMMIT_FIELDS,
            "sort": "-created_at,-id",
            "limit": limit,
            "offset": offset,
        }
        params.update(_owner_params(user_id, team_id))
        rows = await self.directus_service.get_items("project_commits", params=params, no_cache=True)
        if not isinstance(rows, list):
            raise RuntimeError("Failed to list Project commits")
        return rows

    async def get_commit(
        self, project_id: str, commit_id: str, user_id: str, team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "filter[commit_id][_eq]": commit_id,
            "fields": COMMIT_FIELDS,
            "limit": 1,
        }
        params.update(_owner_params(user_id, team_id))
        rows = await self.directus_service.get_items("project_commits", params=params, no_cache=True)
        return rows[0] if isinstance(rows, list) and rows else None

    async def find_member_target_hashes(
        self, project_id: str, user_id: str, target_hashes: List[str], team_id: str | None = None,
    ) -> set[str]:
        """Return which target hashes are currently linked embed/upload items of the Project."""
        params: Dict[str, Any] = {
            "filter[hashed_project_id][_eq]": hash_id(project_id),
            "filter[target_id_hash][_in]": ",".join(target_hashes),
            "filter[item_type][_in]": "embed,upload",
            "fields": "target_id_hash",
            "limit": -1,
        }
        params.update(_owner_params(user_id, team_id))
        rows = await self.directus_service.get_items("project_items", params=params, no_cache=True)
        if not isinstance(rows, list):
            raise RuntimeError("Failed to read Project items")
        return {str(row.get("target_id_hash")) for row in rows}

    async def create_commit(
        self, project_id: str, user_id: str, payload: Dict[str, Any], team_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        record = {
            "commit_id": payload["commit_id"],
            "hashed_project_id": hash_id(project_id),
            **_owner_record(user_id, team_id),
            "created_by_user_hash": hash_id(user_id),
            "author_kind": payload["author_kind"],
            "hashed_chat_id": hash_id(payload["chat_id"]) if payload.get("chat_id") else None,
            "encrypted_message": payload["encrypted_message"],
            "encrypted_paths": payload.get("encrypted_paths"),
            "entries": payload["entries"],
            "entry_count": len(payload["entries"]),
            "restored_from_commit_id": payload.get("restored_from_commit_id"),
            "created_at": payload["created_at"],
        }
        success, data = await self.directus_service.create_item("project_commits", record)
        if not success:
            logger.error("Failed to create project commit: %s", data)
            return None
        return data

    async def delete_project_commits_by_project_hash(
        self, hashed_project_id: str, user_id: str, team_id: str | None = None,
    ) -> int:
        return await self.directus_service.delete_items(
            "project_commits",
            {"hashed_project_id": {"_eq": hashed_project_id}, **_owner_filter(user_id, team_id)},
        )
