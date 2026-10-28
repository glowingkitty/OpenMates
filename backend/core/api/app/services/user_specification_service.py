"""Owner/Project-scoped ciphertext reads and atomic Specification mutations."""

# test-file: backend/tests/test_user_specifications.py

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
HEAD_FIELDS = (
    "specification_id,hashed_user_id,hashed_team_id,home_project_hash,linked_project_hashes,"
    "current_revision_id,current_revision_number,version,status,encrypted_title,encrypted_summary,"
    "key_wrappers,created_at,updated_at"
)
REVISION_FIELDS = (
    "revision_id,specification_id,revision_number,supersedes_revision_id,content_hash,"
    "project_surface_catalog_revision_id,encrypted_title,encrypted_summary,"
    "encrypted_specification_document,approval_state,approved_by_hash,approved_at,created_at"
)


def hash_id(value: str) -> str:
    """Hash routing identities without placing raw private identifiers in storage."""
    return hashlib.sha256(value.encode()).hexdigest()


class SpecificationError(ValueError):
    """A safe protocol error, suitable for first-party client presentation."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class UserSpecificationService:
    """Keep authorization and storage operations independent of any UI adapter."""

    def __init__(self, directus: Any) -> None:
        self.directus = directus

    async def _scope(self, project_id: str, user_id: str, team_id: str | None) -> dict[str, Any]:
        project = await self.directus.project.get_project(project_id, user_id, team_id=team_id)
        if not project:
            raise SpecificationError("project_not_found", 404)
        return {
            "hashed_user_id": None if team_id else hash_id(user_id),
            "hashed_team_id": hash_id(team_id) if team_id else None,
            "home_project_hash": hash_id(project_id),
        }

    @staticmethod
    def _filters(scope: dict[str, Any]) -> dict[str, Any]:
        return {f"filter[{name}][{'_null' if value is None else '_eq'}]": True if value is None else value
                for name, value in scope.items()}

    @staticmethod
    def _head(row: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in row.items() if key != "id"}
        for name in ("key_wrappers", "linked_project_hashes"):
            if isinstance(result.get(name), str):
                result[name] = json.loads(result[name])
        return result

    async def _get_head(self, specification_id: str, scope: dict[str, Any]) -> dict[str, Any]:
        rows = await self.directus.get_items("user_specifications", params={
            **self._filters(scope), "filter[specification_id][_eq]": specification_id,
            "fields": HEAD_FIELDS, "limit": 1,
        }, no_cache=True, raise_on_error=True)
        if not isinstance(rows, list) or not rows:
            raise SpecificationError("specification_not_found", 404)
        return self._head(rows[0])

    async def list_specifications(
        self, project_id: str, user_id: str, *, team_id: str | None = None,
        limit: int = 50, after: str | None = None,
    ) -> dict[str, Any]:
        """Read one bounded page from an authorized owning Project."""
        scope = await self._scope(project_id, user_id, team_id)
        params = {**self._filters(scope), "fields": HEAD_FIELDS, "sort": "specification_id", "limit": limit + 1}
        if after:
            params["filter[specification_id][_gt]"] = after
        rows = await self.directus.get_items("user_specifications", params=params, no_cache=True, raise_on_error=True)
        if not isinstance(rows, list):
            raise SpecificationError("specification_storage_unavailable", 503)
        items = [self._head(row) for row in rows[:limit]]
        return {"specifications": items, "next_cursor": items[-1]["specification_id"] if len(rows) > limit else None}

    async def detail(
        self, project_id: str, specification_id: str, user_id: str, *,
        team_id: str | None = None, revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Read a saved head plus an exact immutable revision without decryption."""
        scope = await self._scope(project_id, user_id, team_id)
        head = await self._get_head(specification_id, scope)
        rows = await self.directus.get_items("user_specification_revisions", params={
            "filter[specification_id][_eq]": specification_id,
            "filter[revision_id][_eq]": revision_id or head["current_revision_id"],
            "fields": REVISION_FIELDS, "limit": 1,
        }, no_cache=True, raise_on_error=True)
        if not isinstance(rows, list) or not rows:
            raise SpecificationError("revision_not_found", 404)
        return {"specification": head, "revision": rows[0]}

    async def revisions(
        self, project_id: str, specification_id: str, user_id: str, *,
        team_id: str | None = None, limit: int = 50, before: int | None = None,
    ) -> dict[str, Any]:
        """Read bounded immutable history after authorizing its parent record."""
        scope = await self._scope(project_id, user_id, team_id)
        await self._get_head(specification_id, scope)
        params = {"filter[specification_id][_eq]": specification_id, "fields": REVISION_FIELDS,
                  "sort": "-revision_number", "limit": limit + 1}
        if before is not None:
            params["filter[revision_number][_lt]"] = before
        rows = await self.directus.get_items("user_specification_revisions", params=params, no_cache=True, raise_on_error=True)
        if not isinstance(rows, list):
            raise SpecificationError("specification_storage_unavailable", 503)
        items = rows[:limit]
        return {"revisions": items, "next_cursor": items[-1]["revision_number"] if len(rows) > limit else None}

    async def mutate(
        self, operation: str, project_id: str, specification_id: str, user_id: str,
        payload: dict[str, Any], *, team_id: str | None = None,
    ) -> dict[str, Any]:
        """Authorize the Project, then atomically publish content or exact approval."""
        scope = await self._scope(project_id, user_id, team_id)
        token = os.environ.get("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise SpecificationError("specification_storage_unavailable", 503)
        response = await self.directus._make_api_request(
            "POST", f"{self.directus.base_url.rstrip('/')}/specification-transaction",
            headers={"X-Internal-Service-Token": token},
            json={**payload, **scope, "operation": operation, "specification_id": specification_id,
                  "project_id": project_id, "actor_hash": hash_id(user_id)},
        )
        if response is None:
            raise SpecificationError("specification_storage_unavailable", 503)
        if response.status_code in {400, 404, 409}:
            error = response.json().get("error", {}).get("code")
            # Only known protocol errors cross the internal boundary.
            allowed = {"revision_conflict", "revision_identity_conflict", "specification_exists",
                       "specification_not_found", "project_not_found", "invalid_key_wrappers", "missing_project_key_wrapper"}
            raise SpecificationError(error if error in allowed else "invalid_specification_operation", response.status_code)
        if response.status_code != 200:
            logger.error("Specification storage failed with HTTP %s", response.status_code)
            raise SpecificationError("specification_storage_unavailable", 503)
        result = response.json().get("data")
        if not isinstance(result, dict) or not isinstance(result.get("specification"), dict) or not isinstance(result.get("revision"), dict):
            raise SpecificationError("specification_storage_unavailable", 503)
        return {**result, "specification": self._head(result["specification"]),
                "revision": {k: v for k, v in result["revision"].items() if k != "id"}}
