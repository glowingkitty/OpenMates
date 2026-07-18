"""Team workspace context and move authorization helpers.

Teams V1 uses one team-wide workspace per team. Records remain encrypted with
their object keys; moving into a team changes the server-visible workspace owner
and relies on team key wrappers for future client decryption.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from backend.core.api.app.services.directus.team_methods import hash_id


WorkspaceContext = Literal["personal", "team"]
TEAM_WORKSPACE_WRITE_ROLES = {"owner", "admin", "member"}


class TeamWorkspaceMoveError(ValueError):
    """Raised when a workspace record cannot be moved into a team."""


WORKSPACE_COLLECTIONS: dict[str, tuple[str, str]] = {
    "chat": ("chats", "id"),
    "project": ("projects", "project_id"),
    "task": ("user_tasks", "task_id"),
    "plan": ("user_plans", "plan_id"),
    "workflow": ("workflows", "workflow_id"),
}


def workspace_context_filters(*, user_id: str, team_id: str | None = None) -> dict[str, Any]:
    if team_id:
        return {"filter[hashed_team_id][_eq]": hash_id(team_id)}
    return {"filter[hashed_user_id][_eq]": hash_id(user_id), "filter[hashed_team_id][_null]": "true"}


async def authorize_personal_to_team_move(
    *,
    directus_service: Any,
    actor_user_id: str,
    team_id: str,
    record: dict[str, Any],
    moved_at: int | None = None,
) -> dict[str, Any]:
    await directus_service.team.require_team_role(team_id, actor_user_id, TEAM_WORKSPACE_WRITE_ROLES)
    if record.get("hashed_user_id") != hash_id(actor_user_id):
        raise TeamWorkspaceMoveError("Only the personal owner can move a workspace record into a team")
    if record.get("hashed_team_id"):
        raise TeamWorkspaceMoveError("Workspace record is already team-scoped")
    return {"hashed_team_id": hash_id(team_id), "updated_at": int(moved_at or time.time())}


async def move_workspace_record_to_team(
    *,
    directus_service: Any,
    actor_user_id: str,
    team_id: str,
    workspace_type: str,
    object_id: str,
    confirmed: bool,
    moved_at: int | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise TeamWorkspaceMoveError("Move confirmation is required")
    collection_config = WORKSPACE_COLLECTIONS.get(workspace_type)
    if not collection_config:
        raise TeamWorkspaceMoveError("Unsupported workspace type")
    collection, id_field = collection_config
    rows = await directus_service.get_items(
        collection,
        params={
            f"filter[{id_field}][_eq]": object_id,
            "filter[hashed_user_id][_eq]": hash_id(actor_user_id),
            "filter[hashed_team_id][_null]": True,
            "fields": "id,hashed_user_id,hashed_team_id,updated_at",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    if not rows or not isinstance(rows, list):
        raise TeamWorkspaceMoveError("Workspace record not found in personal context")
    patch = await authorize_personal_to_team_move(
        directus_service=directus_service,
        actor_user_id=actor_user_id,
        team_id=team_id,
        record=rows[0],
        moved_at=moved_at,
    )
    updated = await directus_service.update_item(collection, rows[0]["id"], patch, admin_required=True)
    if not updated:
        raise RuntimeError("Failed to move workspace record")
    return updated
