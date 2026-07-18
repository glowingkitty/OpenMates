"""Team-scoped export/import service for Teams V1.

Exports are authorization-checked owner/admin artifacts containing only selected
team rows. Imports are allowed only into a destination team where the actor is
owner/admin and must be explicitly marked as rewrapped for the destination team
before persistence.

Spec: docs/specs/teams-v1/spec.yml
"""

from __future__ import annotations

import hashlib
import time
from typing import Any
from uuid import uuid4

from backend.core.api.app.services.directus.team_methods import hash_id


TEAM_SCOPED_COLLECTIONS = (
    "team_memberships",
    "team_invites",
    "team_credit_accounts",
    "team_credit_events",
    "team_usage_events",
    "user_app_settings_and_memories",
    "connected_accounts",
    "team_connected_account_grants",
)

SECRET_FIELDS = {
    "encrypted_team_key",
    "encrypted_refresh_token_bundle",
    "encrypted_server_access_ref",
    "one_time_token_hash",
}


class TeamDataPortabilityError(ValueError):
    """Raised when an export/import artifact violates team isolation rules."""


class TeamDataPortabilityService:
    def __init__(self, directus_service: Any) -> None:
        self.directus_service = directus_service

    async def export_team_data(self, team_id: str, actor_user_id: str, *, export_id: str | None = None, created_at: int | None = None) -> dict[str, Any]:
        await self.directus_service.team.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        now = int(created_at or time.time())
        team_hash = hash_id(team_id)
        artifact: dict[str, Any] = {
            "schema": "openmates.team_export.v1",
            "export_id": export_id or str(uuid4()),
            "hashed_team_id": team_hash,
            "created_at": now,
            "collections": {},
        }
        collections = artifact["collections"]
        team_rows = await self.directus_service.get_items(
            "teams",
            params={"filter[hashed_team_id][_eq]": team_hash, "limit": -1},
            no_cache=True,
            admin_required=True,
        )
        collections["teams"] = [self._redact_row(row) for row in team_rows if isinstance(row, dict)] if isinstance(team_rows, list) else []
        for collection in TEAM_SCOPED_COLLECTIONS:
            rows = await self.directus_service.get_items(
                collection,
                params={"filter[hashed_team_id][_eq]": team_hash, "limit": -1},
                no_cache=True,
                admin_required=True,
            )
            collections[collection] = [self._redact_row(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        artifact_hash = hashlib.sha256(repr(artifact).encode()).hexdigest()
        await self.directus_service.create_item(
            "team_data_exports",
            {
                "export_id": artifact["export_id"],
                "hashed_team_id": team_hash,
                "actor_user_hash": hash_id(actor_user_id),
                "artifact_hash": artifact_hash,
                "encrypted_manifest": "redacted-team-export-manifest",
                "status": "ready",
                "created_at": now,
                "expires_at": None,
            },
            admin_required=True,
        )
        return {"artifact": artifact, "artifact_hash": artifact_hash}

    async def get_team_export(self, team_id: str, actor_user_id: str, export_id: str) -> dict[str, Any]:
        await self.directus_service.team.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        rows = await self.directus_service.get_items(
            "team_data_exports",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[export_id][_eq]": export_id,
                "filter[status][_eq]": "ready",
                "fields": "export_id,artifact_hash,encrypted_manifest,status,created_at,expires_at",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not rows or not isinstance(rows, list):
            raise TeamDataPortabilityError("Team export not found")
        return {"export": rows[0]}

    async def import_team_data(self, destination_team_id: str, actor_user_id: str, artifact: dict[str, Any], *, imported_at: int | None = None) -> dict[str, Any]:
        await self.directus_service.team.require_team_role(destination_team_id, actor_user_id, {"owner", "admin"})
        if artifact.get("schema") != "openmates.team_export.v1":
            raise TeamDataPortabilityError("Invalid team export schema")
        if artifact.get("rewrapped_with_destination_team_key") is not True:
            raise TeamDataPortabilityError("Team export must be rewrapped with destination team key before import")
        collections = artifact.get("collections")
        if not isinstance(collections, dict):
            raise TeamDataPortabilityError("Team export collections are missing")
        destination_hash = hash_id(destination_team_id)
        now = int(imported_at or time.time())
        imported_count = 0
        for collection, rows in collections.items():
            if collection == "teams" or collection not in TEAM_SCOPED_COLLECTIONS:
                continue
            if not isinstance(rows, list):
                raise TeamDataPortabilityError(f"Invalid rows for {collection}")
            for row in rows:
                if not isinstance(row, dict):
                    raise TeamDataPortabilityError(f"Invalid row for {collection}")
                if row.get("owner_context") == "personal" or row.get("hashed_user_id") and not row.get("hashed_team_id"):
                    raise TeamDataPortabilityError("Personal-context rows cannot be imported into a team")
                clean = {key: value for key, value in row.items() if key not in {"id", *SECRET_FIELDS}}
                clean["hashed_team_id"] = destination_hash
                if collection in {"user_app_settings_and_memories", "connected_accounts"}:
                    clean["owner_context"] = "team"
                    clean["updated_at"] = now
                await self.directus_service.create_item(collection, clean, admin_required=True)
                imported_count += 1
        return {"success": True, "imported_rows": imported_count, "hashed_team_id": destination_hash}

    def _redact_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: ("<redacted>" if key in SECRET_FIELDS else value) for key, value in row.items()}
