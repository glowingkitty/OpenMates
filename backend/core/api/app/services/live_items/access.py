"""Live item access: role from ownership or Team membership.
Projects have no member records of their own: a Project item is a Team item, so the Team
role (team_memberships) is the only access source besides personal ownership.

An item is an embed. The owner of a Personal item gets `edit`. A Team (or Team
Project) item gives the member the role the membership allows; `viewer` gets `view`.
Share links are view-only and anonymous visitors get no live subscription, so this
module only ever resolves authenticated users. Anyone without access gets None, which
the relay reports as `not_found` (never leaks that the item exists).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

EDIT_ROLES = frozenset({"owner", "admin", "member"})
VIEW_ROLES = frozenset({"viewer"})
ACTIVE_STATUS = "active"


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class LiveAccess:
    role: str  # "view" | "edit"
    team_hash: str | None


def live_role_for(team_role: str | None) -> str | None:
    """Map a Team role to the live item role ("edit" | "view"), None for no access."""
    if team_role in EDIT_ROLES:
        return "edit"
    if team_role in VIEW_ROLES:
        return "view"
    return None


async def _team_role(directus: Any, team_hash: str, user_id: str) -> str | None:
    rows = await directus.get_items(
        "team_memberships",
        params={
            "filter[hashed_team_id][_eq]": team_hash,
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "filter[status][_eq]": ACTIVE_STATUS,
            "fields": "id,role",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    if not rows or not isinstance(rows, list):
        return None
    return live_role_for(rows[0].get("role"))


# Wire kinds of `live_item_subscribe` (build contract: doc, sheet, deck, code). All
# four are stored as embeds; "embed" stays accepted for older clients.
LIVE_EMBED_KINDS = frozenset({"doc", "sheet", "deck", "code", "embed"})


async def _project_team_hash(directus: Any, item_id: str) -> str | None:
    """Team of the Team Project that holds this file, if any.

    Project files are stored as embeds owned by their creator (no hashed_team_id);
    the Team link lives on the project_items row that targets the embed, so Team
    members are authorized through it (same membership source as the Project routes).
    """
    rows = await directus.get_items(
        "project_items",
        params={
            "filter[target_id_hash][_eq]": hash_id(item_id),
            "filter[hashed_team_id][_nnull]": "true",
            "fields": "hashed_team_id",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    if not rows or not isinstance(rows, list):
        return None
    team_hash = rows[0].get("hashed_team_id")
    return team_hash if isinstance(team_hash, str) and team_hash else None


async def resolve_access(
    directus: Any, user_id: str, item_id: str, kind: str
) -> LiveAccess | None:
    """Return the caller's role for the item, or None when it does not exist for them."""
    if kind not in LIVE_EMBED_KINDS:
        return None
    rows = await directus.get_items(
        "embeds",
        params={
            "filter[hashed_embed_id][_eq]": hash_id(item_id),
            "fields": "hashed_user_id,hashed_team_id",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    if not rows or not isinstance(rows, list):
        return None
    row = rows[0]
    team_hash = row.get("hashed_team_id") or await _project_team_hash(directus, item_id)
    if team_hash:
        role = await _team_role(directus, team_hash, user_id)
        return LiveAccess(role, team_hash) if role else None
    if row.get("hashed_user_id") == hash_id(user_id):
        return LiveAccess("edit", None)
    return None
