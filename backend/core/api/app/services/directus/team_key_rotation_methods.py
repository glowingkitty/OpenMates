"""Team key rotation storage (Teams, live collaboration).

A member removal deletes the removed member's Team key wrappers and sets
`teams.rotation_pending`. A remaining owner/admin client then generates a fresh
Team key, seals it for every current member, re-wraps every Project key and
uploads the whole set here in one request. The server validates the set, never
sees a plaintext key, and publishes the complete set in one Directus
transaction.
"""

from __future__ import annotations

import os
from typing import Any

from backend.core.api.app.services.directus.team_methods import (
    ACTIVE_STATUS,
    TeamMethods,
    TeamPermissionError,
    hash_id,
)

ROTATION_ROLES = {"owner", "admin"}
TEAM_PROFILE_FIELDS = ("encrypted_name", "encrypted_description", "encrypted_profile_image_metadata")


class TeamKeyRotationError(ValueError):
    """The uploaded rotation set is stale, incomplete or inconsistent."""


class TeamKeyRotationMethods:
    def __init__(self, team: TeamMethods) -> None:
        self.team = team
        self.directus = team.directus_service

    async def _team_row(self, team_id: str, *, include_profile: bool = False) -> dict[str, Any]:
        fields = ("id", "team_key_epoch", "rotation_pending")
        if include_profile:
            fields += TEAM_PROFILE_FIELDS
        rows = await self.directus.get_items(
            "teams",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": ",".join(fields),
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(rows, list) or not rows:
            raise TeamPermissionError("Team permission denied")
        return rows[0]

    async def allows_legacy_project_sandbox(self, team_id: str) -> bool:
        """Whether a sandbox with only a Project key can read and seal Team revisions."""
        row = await self._team_row(team_id)
        return not row.get("rotation_pending") and row.get("team_key_epoch") in (None, 1)

    async def _project_wrappers(self, team_id: str) -> list[dict[str, Any]]:
        rows = await self.directus.get_items(
            "project_key_wrappers",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[key_type][_eq]": "team",
                "fields": "id,hashed_project_id,team_key_epoch,encrypted_project_key",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(rows, list):
            raise RuntimeError("Failed to list Team Project key wrappers")
        return rows

    async def context(self, team_id: str, actor_user_id: str) -> dict[str, Any]:
        """Opaque Team profile and key wrappers that the admin device must rotate."""
        await self.team.require_team_role(team_id, actor_user_id, ROTATION_ROLES)
        team = await self._team_row(team_id, include_profile=True)
        members = sorted(await self.team.list_active_member_hashes(team_id))
        return {
            "team_key_epoch": int(team.get("team_key_epoch") or 1),
            "rotation_pending": bool(team.get("rotation_pending")),
            "member_hashes": members,
            "profile": {field: team[field] for field in TEAM_PROFILE_FIELDS if team.get(field)},
            "project_key_wrappers": [
                {
                    "hashed_project_id": row["hashed_project_id"],
                    "team_key_epoch": row.get("team_key_epoch"),
                    "encrypted_project_key": row.get("encrypted_project_key"),
                }
                for row in await self._project_wrappers(team_id)
            ],
        }

    async def apply(self, team_id: str, actor_user_id: str, upload: dict[str, Any]) -> int:
        """Validate and store one rotated key set; returns the new epoch."""
        await self.team.require_team_role(team_id, actor_user_id, ROTATION_ROLES)
        team = await self._team_row(team_id)
        if not team.get("rotation_pending"):
            raise TeamKeyRotationError("Team key rotation is not pending")
        current = int(team.get("team_key_epoch") or 1)
        if upload.get("team_key_epoch") != current + 1:
            raise TeamKeyRotationError("Team key epoch must be the current epoch plus one")
        members = await self.team.list_active_member_hashes(team_id)
        wrappers = upload.get("wrappers")
        if not isinstance(wrappers, list):
            raise TeamKeyRotationError("wrappers are required")
        by_user: dict[str, str] = {}
        for item in wrappers:
            user_hash = item.get("hashed_user_id") if isinstance(item, dict) else None
            cipher = item.get("encrypted_team_key") if isinstance(item, dict) else None
            if not isinstance(user_hash, str) or not isinstance(cipher, str) or not cipher or user_hash in by_user:
                raise TeamKeyRotationError("Invalid or duplicate Team key wrapper")
            by_user[user_hash] = cipher
        if set(by_user) != members:
            raise TeamKeyRotationError("Wrappers must cover exactly the current active members")
        existing_projects = await self._project_wrappers(team_id)
        project_uploads = upload.get("project_key_wrappers")
        if not isinstance(project_uploads, list):
            raise TeamKeyRotationError("project_key_wrappers are required")
        by_project: dict[str, str] = {}
        for item in project_uploads:
            project_hash = item.get("hashed_project_id") if isinstance(item, dict) else None
            cipher = item.get("encrypted_project_key") if isinstance(item, dict) else None
            if not isinstance(project_hash, str) or not isinstance(cipher, str) or not cipher or project_hash in by_project:
                raise TeamKeyRotationError("Invalid or duplicate Project key wrapper")
            by_project[project_hash] = cipher
        if set(by_project) != {row["hashed_project_id"] for row in existing_projects}:
            raise TeamKeyRotationError("Project key wrappers must cover exactly the Team's Projects")
        previous = upload.get("encrypted_previous_team_keys")
        if not isinstance(previous, str) or not previous:
            raise TeamKeyRotationError("encrypted_previous_team_keys is required")

        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for Team key rotation")
        response = await self.directus._make_api_request(
            "POST",
            f"{self.directus.base_url.rstrip('/')}/embed-version-transaction/team-key-rotation",
            headers={"X-Internal-Service-Token": token},
            json={
                **upload,
                "team_hash": hash_id(team_id),
                "actor_user_hash": hash_id(actor_user_id),
            },
        )
        if response.status_code == 403:
            raise TeamPermissionError("Team permission denied")
        if response.status_code in {400, 409}:
            raise TeamKeyRotationError("Team state or key wrappers changed during rotation")
        if response.status_code != 200:
            raise RuntimeError("Team key rotation transaction failed")
        result = response.json()
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict) or data.get("team_key_epoch") != current + 1:
            raise RuntimeError("Team key rotation transaction returned an invalid epoch")
        return current + 1

    async def claim(self, team_id: str, user_id: str, epoch: int, encrypted_team_key: str) -> None:
        """Replace the member's own sealed (`OMTK1.`) wrapper with their master-key wrapper."""
        await self.team.require_team_role(team_id, user_id, {"owner", "admin", "member", "viewer"})
        team = await self._team_row(team_id)
        if epoch != int(team.get("team_key_epoch") or 1):
            raise TeamKeyRotationError("Team key epoch is not current")
        rows = await self.directus.get_items(
            "team_key_wrappers",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[hashed_user_id][_eq]": hash_id(user_id),
                "filter[team_key_epoch][_eq]": epoch,
                "fields": "id,encrypted_team_key",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(rows, list) or not rows:
            raise TeamPermissionError("Team permission denied")
        if not str(rows[0].get("encrypted_team_key") or "").startswith("OMTK1."):
            raise TeamKeyRotationError("Team key wrapper is not a sealed rotation wrapper")
        if encrypted_team_key.startswith("OMTK1."):
            raise TeamKeyRotationError("Claimed wrapper must be master-key wrapped")
        if not await self.directus.update_item(
            "team_key_wrappers", rows[0]["id"], {"encrypted_team_key": encrypted_team_key}, admin_required=True
        ):
            raise RuntimeError("Failed to store claimed Team key wrapper")
