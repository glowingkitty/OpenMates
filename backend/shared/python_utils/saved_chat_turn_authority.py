"""Server admission for a new user turn in an existing descendant chat.

The turn owns a fresh ordinary inference admission, not the completed delegated
job. Its physical ancestry remains immutable for attribution and spawn limits.
Every worker resolves this context from owned database rows, including queued
turns and resumed tasks. It is never accepted as serialized client authority.
"""
from __future__ import annotations

import hashlib

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SavedChatAncestry:
    parent_id: str
    root_chat_id: str
    depth: int


async def resolve_saved_chat_ancestry(
    directus: Any, *, chat_id: str, owner_hash: str, team_hash: str | None,
) -> SavedChatAncestry | None:
    """Walk owned canonical rows, preferring immutable orchestration lineage.

    Looking up lineage even when editable chat metadata says 'root' prevents a
    reparented descendant from resetting its depth. Legacy saved children use
    their canonical parent rows, with the same bounded ownership/cycle checks.
    """
    seen: set[str] = set()
    current = chat_id
    parent_id = None
    expected_depth = None
    orchestration_id = None
    root_id = None
    for depth in range(3):
        if current in seen:
            raise ValueError("saved_chat_ancestry_cycle")
        seen.add(current)
        row = await directus.chat.get_chat_metadata(current, admin_required=True)
        if (not row or row.get("id") != current
                or row.get("hashed_team_id") != team_hash
                or (team_hash is None and row.get("hashed_user_id") != owner_hash)):
            raise ValueError("saved_chat_ancestry_forbidden")
        links = await directus.get_items(
            "sub_chat_orchestration_children", params={
                "filter[child_chat_id][_eq]": current,
                "fields": "orchestration_id,parent_chat_id,depth", "limit": 2,
            }, admin_required=True, raise_on_error=True, no_cache=True,
        ) or []
        if len(links) > 1:
            raise ValueError("saved_chat_ancestry_ambiguous")
        if links:
            link = links[0]
            if type(link.get("depth")) is not int or link["depth"] not in (1, 2):
                raise ValueError("saved_chat_ancestry_depth")
            if orchestration_id is None:
                orchestration_id = link["orchestration_id"]
                roots = await directus.get_items(
                    "sub_chat_orchestrations", params={
                        "filter[id][_eq]": orchestration_id,
                        "fields": "id,root_chat_id,hashed_user_id,hashed_team_id", "limit": 1,
                    }, admin_required=True, raise_on_error=True, no_cache=True,
                ) or []
                if (not roots or roots[0].get("hashed_team_id") != team_hash
                        or (team_hash is None and roots[0].get("hashed_user_id") != owner_hash)):
                    raise ValueError("saved_chat_ancestry_forbidden")
                root_id = roots[0]["root_chat_id"]
                expected_depth = depth + link["depth"]
            if (link["orchestration_id"] != orchestration_id
                    or depth + link["depth"] != expected_depth):
                raise ValueError("saved_chat_ancestry_mismatch")
            parent = link.get("parent_chat_id")
        else:
            parent = row.get("parent_id")
            if row.get("is_sub_chat") and not parent:
                raise ValueError("saved_chat_ancestry_missing")
        if not parent:
            if expected_depth is not None and (depth != expected_depth or current != root_id):
                raise ValueError("saved_chat_ancestry_mismatch")
            return SavedChatAncestry(parent_id, current, depth) if depth else None
        if depth == 0:
            parent_id = parent
        current = parent
    raise ValueError("saved_chat_ancestry_depth")



@dataclass(frozen=True)
class _VerifiedSavedTurn:
    owner_id: str
    owner_hash: str
    team_hash: str | None
    chat_id: str
    ancestry: SavedChatAncestry


async def prepare_saved_chat_turn(request: Any, directus: Any) -> None:
    """Resolve canonical ancestry before admission; never reuse a child claim.

    The request's existing durable ordinary admission still authenticates the
    actual chat/message/task. This private in-memory proof only separates that
    admission identity from immutable billing ancestry. Rebuild it after every
    transport or checkpoint restoration rather than trusting serialized depth.
    """
    if any(getattr(request, key, False) for key in (
        "is_sub_chat", "is_anonymous", "is_external", "is_incognito",
    )):
        return
    if request.user_id_hash != hashlib.sha256(request.user_id.encode()).hexdigest():
        raise ValueError("saved_chat_ancestry_forbidden")
    ancestry = await resolve_saved_chat_ancestry(
        directus, chat_id=request.chat_id, owner_hash=request.user_id_hash,
        team_hash=request.team_id_hash,
    )
    if ancestry is None:
        if getattr(request, "sub_chat_depth", 0):
            raise ValueError("saved_chat_ancestry_mismatch")
        return
    if request.orchestration_id or request.orchestration_dispatch_token:
        raise ValueError("saved_chat_turn_cannot_reuse_delegated_job")
    request.parent_id = ancestry.parent_id
    request.root_chat_id = ancestry.root_chat_id
    request.sub_chat_depth = ancestry.depth
    object.__setattr__(request, "_verified_saved_chat_turn", _VerifiedSavedTurn(
        request.user_id, request.user_id_hash, request.team_id_hash, request.chat_id, ancestry,
    ))


def saved_chat_turn(request: Any) -> bool:
    proof = getattr(request, "_verified_saved_chat_turn", None)
    if not isinstance(proof, _VerifiedSavedTurn):
        return False
    if (proof.owner_id != request.user_id or proof.owner_hash != request.user_id_hash
            or proof.team_hash != request.team_id_hash or proof.chat_id != request.chat_id
            or proof.ancestry != SavedChatAncestry(request.parent_id, request.root_chat_id, request.sub_chat_depth)
            or request.is_sub_chat or request.orchestration_id or request.orchestration_dispatch_token):
        raise ValueError("saved_chat_turn_identity_mismatch")
    return True


def admission_chat_id(request: Any) -> str:
    return request.chat_id if saved_chat_turn(request) else request.root_chat_id or request.chat_id


def admission_message_id(request: Any) -> str:
    return request.message_id if saved_chat_turn(request) else request.root_user_message_id or request.message_id
