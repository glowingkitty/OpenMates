"""Fresh, owner-scoped Personal Project routing metadata for one send socket."""

from __future__ import annotations

from typing import Any

from backend.core.api.app.services.directus.project_methods import _owner_params, hash_id
from backend.core.api.app.services.project_focus_request_service import project_focus_activation_policy

PROJECT_CANDIDATE_LIMIT = 40
_PROJECT_FIELDS = (
    "project_id,hashed_user_id,hashed_team_id,archived,"
    "encrypted_project_key,encrypted_name,encrypted_description"
)


async def fresh_personal_project_candidates(directus: Any, user_id: str) -> list[dict[str, Any]]:
    """Read only current Personal routing rows; never expose disabled Projects."""
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Personal owner required")
    params: dict[str, Any] = {
        "fields": _PROJECT_FIELDS,
        "sort": "-pinned,-last_opened_at,-updated_at",
        "limit": PROJECT_CANDIDATE_LIMIT,
        "filter[archived][_neq]": True,
    }
    params.update(_owner_params(user_id, None))
    rows = await directus.get_items("projects", params=params, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list) or len(rows) > PROJECT_CANDIDATE_LIMIT:
        raise RuntimeError("Personal Project directory unavailable")
    owner_hash = hash_id(user_id)
    seen: set[str] = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("hashed_user_id") != owner_hash
                or row.get("hashed_team_id") is not None or row.get("archived") is True
                or not isinstance(row.get("project_id"), str) or not row["project_id"]
                or row["project_id"] in seen
                or not isinstance(row.get("encrypted_project_key"), str)
                or not row["encrypted_project_key"]
                or not isinstance(row.get("encrypted_name"), str)
                or not row["encrypted_name"]
                or row.get("encrypted_description") is not None
                and not isinstance(row["encrypted_description"], str)):
            raise RuntimeError("Personal Project directory invalid")
        seen.add(row["project_id"])
    settings = await directus.project.get_project_settings_for_projects(
        [row["project_id"] for row in rows], user_id, team_id=None,
    )
    if not isinstance(settings, dict):
        raise RuntimeError("Personal Project settings unavailable")
    return [
        {
            "project_id": row["project_id"],
            "encrypted_project_key": row["encrypted_project_key"],
            "encrypted_name": row["encrypted_name"],
            "encrypted_description": row.get("encrypted_description"),
            "auto_selection": True,
            "focus_activation_policy": project_focus_activation_policy(settings.get(row["project_id"])),
        }
        for row in rows
        if not isinstance(settings.get(row["project_id"]), dict)
        or settings[row["project_id"]].get("auto_selection") is not False
    ]
