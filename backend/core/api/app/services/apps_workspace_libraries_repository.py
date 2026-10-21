"""Backed-up durable Apps configuration; never stores recommendation batches."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

COLLECTION = "apps_workspace_libraries"


class AppsLibrariesRepository:
    def __init__(self, directus: Any) -> None:
        self.directus = directus

    async def get(self, scope: str) -> dict[str, Any] | None:
        rows = await self.directus.get_items(COLLECTION, params={"filter[scope_hash][_eq]": scope,
            "fields": "*", "limit": 1}, no_cache=True, admin_required=True, raise_on_error=True)
        if not isinstance(rows, list):
            raise RuntimeError("Apps durable library read failed")
        return rows[0] if rows else None

    async def activity(self, user_id: str) -> dict[str, Any]:
        """Read general auth/session activity freshly, outside profile caches.

        The existing auth login/session producers own last_online_timestamp;
        scheduling must not equate an Apps visit with all account activity.
        """
        rows = await self.directus.get_items("users", params={"filter[id][_eq]": user_id,
            "fields": "id,last_online_timestamp,last_access", "limit": 1},
            no_cache=True, admin_required=True, raise_on_error=True)
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("Apps scheduler account activity unavailable")
        return rows[0]

    async def scopes(self) -> list[dict[str, Any]]:
        # Enumerate the authoritative DB, including after an empty-volume restore.
        rows = await self.directus.get_items(COLLECTION, params={"fields": "scope_hash,last_attempt_at",
            "sort": "last_attempt_at", "limit": -1}, no_cache=True, admin_required=True, raise_on_error=True)
        if not isinstance(rows, list):
            raise RuntimeError("Apps durable library enumeration failed")
        return rows

    async def put(self, scope: str, previous: dict[str, Any] | None, data: dict[str, Any]) -> dict[str, Any]:
        if previous:
            version = int(previous["version"])
            updated = await self.directus.update_item_if_version(COLLECTION, previous["id"],
                {**data, "version": version + 1}, version, extra_filters={"scope_hash": scope}, admin_required=True)
            if not updated:
                raise RuntimeError("Apps durable library update conflict")
            return updated
        record = {"id": str(uuid4()), "scope_hash": scope, "version": 1, **data}
        ok, created = await self.directus.create_item(COLLECTION, record, admin_required=True)
        if not ok or not isinstance(created, dict):
            raise RuntimeError("Apps durable library creation failed")
        return created
