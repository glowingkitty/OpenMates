# backend/core/api/app/routes/project_timeline.py
#
# Project Timeline read API. Access model: first-party client surface only
# (session auth; web, CLI/TUI and Apple through the shared Rust core). Not part
# of the public or developer API-key surface.
#
# Merges four append-only sources newest first: native commits, assistant
# hosted-file revisions, user Project-scope revisions and file link operations
# (adopt/rename/delete). The wire carries hashes only (target_id_hash); embed ids
# and paths never leave the server, the client core joins hashes to its own
# decrypted Project links.

import base64
import binascii
import logging
from typing import Annotated, Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.project_commits import COMMIT_PAGE_MAX, _public_commit, _require_project
from backend.core.api.app.routes.projects import TEAM_READ_ROLES, get_directus_service
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.directus.project_commit_methods import COMMIT_FIELDS
from backend.core.api.app.services.directus.project_methods import _owner_params, hash_id
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects", tags=["Project timeline"], dependencies=[Depends(ensure_projects_enabled)])

# Tie-break order for entries sharing a timestamp (higher sorts first).
KIND_RANK = {"commit": 3, "file_version": 2, "file_operation": 1}
SOURCES = ("commit", "assistant_revision", "user_revision", "operation")
SOURCE_KIND = {
    "commit": "commit",
    "assistant_revision": "file_version",
    "user_revision": "file_version",
    "operation": "file_operation",
}
SOURCE_COLLECTION = {
    "commit": "project_commits",
    "assistant_revision": "embed_version_commits",
    "user_revision": "embed_user_revision_commits",
    "operation": "project_item_operations",
}
SOURCE_FIELDS = {
    "commit": COMMIT_FIELDS,
    "assistant_revision": "id,embed_id,expected_revision,committed_revision,created_at",
    "user_revision": "id,embed_id,revision_action,committed_revision,restored_from,created_at",
    "operation": "id,operation_kind,target_id_hash,created_at",
}

Cursor = Tuple[int, str, str]


def _encode_cursor(entry: Dict[str, Any]) -> str:
    raw = f"{entry['created_at']}|{entry['kind']}|{entry['id']}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(value: str) -> Cursor:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        created_at, kind, row_id = raw.split("|", 2)
        parsed = int(created_at)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="INVALID_TIMELINE_CURSOR") from exc
    if parsed < 0 or kind not in KIND_RANK or not row_id:
        raise HTTPException(status_code=400, detail="INVALID_TIMELINE_CURSOR")
    return parsed, kind, row_id


def _source_params(
    source: str, project_id: str, user_id: str, team_id: str | None, limit: int, cursor: Cursor | None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"fields": SOURCE_FIELDS[source], "sort": "-created_at,-id", "limit": limit}
    if source in ("commit", "operation"):
        params["filter[hashed_project_id][_eq]"] = hash_id(project_id)
        params.update(_owner_params(user_id, team_id))
    elif source == "assistant_revision":
        params["filter[hashed_project_id][_eq]"] = hash_id(project_id)
    else:
        params["filter[scope_kind][_eq]"] = "project"
        params["filter[hashed_scope_id][_eq]"] = hash_id(project_id)
    if source in ("assistant_revision", "user_revision"):
        if team_id:
            params["filter[hashed_team_id][_eq]"] = hash_id(team_id)
        else:
            params["filter[hashed_team_id][_null]"] = True
    if cursor:
        created_at, kind, row_id = cursor
        if SOURCE_KIND[source] == kind:
            params["filter[_or][0][created_at][_lt]"] = created_at
            params["filter[_or][1][_and][0][created_at][_eq]"] = created_at
            params["filter[_or][1][_and][1][id][_lt]"] = row_id
        elif KIND_RANK[SOURCE_KIND[source]] < KIND_RANK[kind]:
            params["filter[created_at][_lte]"] = created_at
        else:
            params["filter[created_at][_lt]"] = created_at
    return params


def _entry(source: str, row: Dict[str, Any]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "kind": SOURCE_KIND[source],
        "id": str(row["id"]),
        "created_at": row.get("created_at"),
        "author_kind": "user",
        "target_id_hash": None,
        "version": None,
        "action": None,
        "restored_from_version": None,
        "commit": None,
    }
    if source == "commit":
        entry["author_kind"] = row.get("author_kind")
        entry["commit"] = _public_commit(row)
    elif source == "assistant_revision":
        entry["author_kind"] = "assistant"
        entry["target_id_hash"] = hash_id(row["embed_id"])
        entry["version"] = row.get("committed_revision")
        entry["action"] = "create" if row.get("expected_revision") == 0 else "update"
    elif source == "user_revision":
        entry["target_id_hash"] = hash_id(row["embed_id"])
        entry["version"] = row.get("committed_revision")
        entry["action"] = row.get("revision_action")
        entry["restored_from_version"] = row.get("restored_from")
    else:
        entry["target_id_hash"] = row.get("target_id_hash")
        entry["action"] = row.get("operation_kind")
    return entry


def _sort_key(entry: Dict[str, Any]) -> Tuple[int, int, str]:
    return entry["created_at"], KIND_RANK[entry["kind"]], entry["id"]


async def _fetch_source(
    directus_service: DirectusService, source: str, project_id: str, user_id: str,
    team_id: str | None, limit: int, cursor: Cursor | None,
) -> List[Dict[str, Any]]:
    params = _source_params(source, project_id, user_id, team_id, limit, cursor)
    rows = await directus_service.get_items(SOURCE_COLLECTION[source], params=params, no_cache=True)
    if not isinstance(rows, list):
        logger.error("Project timeline source %s unreadable for project %s", source, hash_id(project_id)[:12])
        raise HTTPException(status_code=502, detail="Failed to read Project timeline")
    return [_entry(source, row) for row in rows]


@router.get("/{project_id}/timeline")
@limiter.limit("120/minute")
async def get_project_timeline(
    request: Request,
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=COMMIT_PAGE_MAX)] = 50,
    before: Optional[str] = None,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Newest first across commits, file revisions and file operations; hashes only."""
    cursor = _decode_cursor(before) if before else None
    await _require_project(directus_service, project_id, current_user, team_id, TEAM_READ_ROLES)
    merged: List[Dict[str, Any]] = []
    for source in SOURCES:
        merged.extend(await _fetch_source(
            directus_service, source, project_id, current_user.id, team_id, limit + 1, cursor,
        ))
    merged.sort(key=_sort_key, reverse=True)
    page = merged[:limit]
    return {"entries": page, "next_cursor": _encode_cursor(page[-1]) if len(merged) > limit else None}
