"""Validate minimal client-decrypted Focus metadata for one owned Project.

The server can verify encrypted item identity and revision before consent. It
cannot read the Focus document until the first-party client supplies it after
Project activation.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from backend.core.api.app.services.project_recommendation_service import project_item_revision

MAX_FOCUSES_PER_PROJECT = 20
REVISION_PATTERN = re.compile(r"[a-f0-9]{64}\Z")


def _bounded_text(value: Any, limit: int, *, required: bool = False) -> str | None:
    if not isinstance(value, str):
        return None if required else ""
    text = " ".join(value.split())[:limit]
    return text if text or not required else None


async def validated_focus_candidates_for_project(
    candidate: dict[str, Any], *, directus_service: Any, user_id: str,
    team_id: str | None,
) -> list[dict[str, str]]:
    """Return current Focus identities and text only, scoped by Project owner/team.

    ``candidate`` must already be an eligible Project from
    ``validated_project_candidates``. A stale, deleted, foreign, or forged item
    is omitted. This function never reads an item target or decrypted body.
    """
    project_id = candidate.get("project_id")
    supplied = candidate.get("focuses")
    if not isinstance(project_id, str) or not isinstance(supplied, list) or not supplied:
        return []
    try:
        UUID(project_id)
    except (TypeError, ValueError, AttributeError):
        return []
    rows = await directus_service.project.list_items(project_id, user_id, team_id=team_id)
    current = {row.get("project_item_id"): row for row in rows
               if row.get("item_type") in {"embed", "upload"}
               and row.get("target_id_hash") and not row.get("deleted_target_state")}
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for offered in supplied[:MAX_FOCUSES_PER_PROJECT]:
        if not isinstance(offered, dict):
            continue
        item_id, revision = offered.get("item_id"), offered.get("revision")
        if not isinstance(item_id, str) or not isinstance(revision, str) or item_id in seen:
            continue
        try:
            UUID(item_id)
        except (TypeError, ValueError, AttributeError):
            continue
        if not REVISION_PATTERN.fullmatch(revision):
            continue
        row = current.get(item_id)
        if not row or project_item_revision(row) != revision:
            continue
        title = _bounded_text(offered.get("title"), 180, required=True)
        description = _bounded_text(offered.get("description"), 640, required=True)
        when_to_use = _bounded_text(offered.get("when_to_use"), 640)
        if title is None or description is None:
            continue
        seen.add(item_id)
        result.append({"focus_id": f"project-focus:{project_id}:{item_id}",
                       "item_id": item_id, "revision": revision,
                       "title": title, "description": description,
                       "when_to_use": when_to_use or ""})
    return result
