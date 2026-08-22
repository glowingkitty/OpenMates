"""Team workspace context and move authorization helpers.

Teams V1 uses one team-wide workspace per team. Records remain encrypted with
their object keys; moving into a team changes the server-visible workspace owner
and relies on team key wrappers for future client decryption.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from backend.core.api.app.services.directus.team_methods import hash_id
from backend.shared.python_utils.encrypted_slug_metadata import (
    DuplicateObjectSlugError,
    is_slug_unique_violation,
    validate_encrypted_slug_metadata,
)


WorkspaceContext = Literal["personal", "team"]
TEAM_WORKSPACE_WRITE_ROLES = {"owner", "admin", "member"}


class TeamWorkspaceMoveError(ValueError):
    """Raised when a workspace record cannot be moved into a team."""


WORKSPACE_COLLECTIONS: dict[str, tuple[str, str]] = {
    "chat": ("chats", "id"),
    "task": ("user_tasks", "task_id"),
    "plan": ("user_plans", "plan_id"),
    "workflow": ("workflows", "workflow_id"),
}


def _workspace_user_hash(workspace_type: str, user_id: str) -> str:
    if workspace_type == "workflow":
        return f"user_sha256:{hash_id(user_id)}"
    return hash_id(user_id)


def workspace_context_filters(*, user_id: str, team_id: str | None = None) -> dict[str, Any]:
    if team_id:
        return {"filter[hashed_team_id][_eq]": hash_id(team_id)}
    return {"filter[hashed_user_id][_eq]": hash_id(user_id), "filter[hashed_team_id][_null]": "true"}


async def authorize_personal_to_team_move(
    *,
    directus_service: Any,
    actor_user_id: str,
    team_id: str,
    workspace_type: str,
    record: dict[str, Any],
    encrypted_slug: str | None = None,
    slug_lookup_hash: str | None = None,
    moved_at: int | None = None,
) -> dict[str, Any]:
    await directus_service.team.require_team_role(team_id, actor_user_id, TEAM_WORKSPACE_WRITE_ROLES)
    if record.get("hashed_user_id") != _workspace_user_hash(workspace_type, actor_user_id):
        raise TeamWorkspaceMoveError("Only the personal owner can move a workspace record into a team")
    if record.get("hashed_team_id"):
        raise TeamWorkspaceMoveError("Workspace record is already team-scoped")
    patch = {"hashed_user_id": None, "hashed_team_id": hash_id(team_id), "updated_at": int(moved_at or time.time())}
    if record.get("encrypted_slug") or record.get("slug_lookup_hash"):
        validate_encrypted_slug_metadata(
            {"encrypted_slug": encrypted_slug, "slug_lookup_hash": slug_lookup_hash},
            record_label="Workspace move",
        )
        if not encrypted_slug or not slug_lookup_hash:
            raise TeamWorkspaceMoveError("Moving a slugged workspace record requires team-scoped encrypted slug metadata")
        patch["encrypted_slug"] = encrypted_slug
        patch["slug_lookup_hash"] = slug_lookup_hash
    return patch


async def _ensure_team_slug_lookup_available(
    *,
    directus_service: Any,
    collection: str,
    team_id: str,
    slug_lookup_hash: str | None,
) -> None:
    if not slug_lookup_hash:
        return
    rows = await directus_service.get_items(
        collection,
        params={
            "filter": {
                "_and": [
                    {"slug_lookup_hash": {"_eq": slug_lookup_hash}},
                    {"hashed_team_id": {"_eq": hash_id(team_id)}},
                ]
            },
            "fields": "id",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    if rows and isinstance(rows, list):
        raise DuplicateObjectSlugError("Workspace slug already exists in this team")


async def move_workspace_record_to_team(
    *,
    directus_service: Any,
    actor_user_id: str,
    team_id: str,
    workspace_type: str,
    object_id: str,
    confirmed: bool,
    encrypted_slug: str | None = None,
    slug_lookup_hash: str | None = None,
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
            "filter[hashed_user_id][_eq]": _workspace_user_hash(workspace_type, actor_user_id),
            "filter[hashed_team_id][_null]": True,
            "fields": "id,hashed_user_id,hashed_team_id,encrypted_slug,slug_lookup_hash,updated_at,record_json",
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
        workspace_type=workspace_type,
        record=rows[0],
        encrypted_slug=encrypted_slug,
        slug_lookup_hash=slug_lookup_hash,
        moved_at=moved_at,
    )
    await _ensure_team_slug_lookup_available(
        directus_service=directus_service,
        collection=collection,
        team_id=team_id,
        slug_lookup_hash=patch.get("slug_lookup_hash"),
    )
    update_patch = dict(patch)
    if workspace_type == "workflow" and isinstance(rows[0].get("record_json"), dict):
        record_json = {**rows[0]["record_json"], **patch, "owner_hash": _workspace_user_hash(workspace_type, actor_user_id)}
        update_patch["record_json"] = record_json
    try:
        updated = await directus_service.update_item(collection, rows[0]["id"], update_patch, admin_required=True)
    except DuplicateObjectSlugError:
        raise
    except Exception as exc:
        if is_slug_unique_violation(exc):
            raise DuplicateObjectSlugError("Workspace slug already exists in this team") from exc
        raise
    if not updated:
        error_details = getattr(directus_service, "last_update_error", None)
        if is_slug_unique_violation(error_details):
            raise DuplicateObjectSlugError("Workspace slug already exists in this team")
        raise RuntimeError("Failed to move workspace record")
    return updated
