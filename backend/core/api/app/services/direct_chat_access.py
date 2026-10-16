"""Authoritative participant access and per-recipient projection for Team direct chats.

These checks deliberately use Directus membership rows, never the Team chat
cache or the creator's ownership. A removed member loses access immediately.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.core.api.app.services.directus.team_methods import hash_id


_HASH = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ENVELOPE = re.compile(r"^OMDM1\.[A-Za-z0-9._-]{16,16378}$")
DIRECT_FIELDS = frozenset({"chat_visibility", "participant_user_hashes", "participant_key_envelopes"})


def is_personal_retention_chat(metadata: dict[str, Any] | None, owner_hash: str) -> bool:
    """Personal retention must not delete shared Team or malformed private rows."""
    return (
        isinstance(metadata, dict)
        and metadata.get("hashed_user_id") == owner_hash
        and metadata.get("hashed_team_id") is None
        and not is_direct_chat(metadata)
    )


class _DirectProjection(dict):
    """In-process marker; never serialized as a key in an outbound payload."""

    def __init__(self, metadata: dict[str, Any], user_hash: str):
        super().__init__(metadata)
        self.user_hash = user_hash


def is_direct_chat(metadata: dict[str, Any] | None) -> bool:
    return isinstance(metadata, dict) and (
        metadata.get("chat_visibility") not in (None, "team")
        or metadata.get("participant_user_hashes") is not None
        or metadata.get("participant_key_envelopes") is not None
    )


def _json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Malformed direct chat metadata") from exc
    return value


def validate_direct_chat_metadata(metadata: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, str]]]:
    """Fail closed if either participant or envelope is missing or malformed."""
    if metadata.get("chat_visibility") != "direct":
        raise ValueError("Not a direct chat")
    members = _json_field(metadata.get("participant_user_hashes"))
    envelopes = _json_field(metadata.get("participant_key_envelopes"))
    if (
        not isinstance(members, list)
        or len(members) != 2
        or any(not isinstance(item, str) or not _HASH.fullmatch(item) for item in members)
        or len(set(members)) != 2
        or not isinstance(envelopes, dict)
        or set(envelopes) != set(members)
        or not isinstance(metadata.get("hashed_team_id"), str)
        or not _HASH.fullmatch(metadata["hashed_team_id"])
        or metadata.get("encrypted_chat_key") not in (None, "")
    ):
        raise ValueError("Malformed direct chat metadata")
    for envelope in envelopes.values():
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"key_id", "encrypted_chat_key"}
            or not isinstance(envelope["key_id"], str)
            or not _KEY_ID.fullmatch(envelope["key_id"])
            or not isinstance(envelope["encrypted_chat_key"], str)
            or not _ENVELOPE.fullmatch(envelope["encrypted_chat_key"])
        ):
            raise ValueError("Malformed direct chat metadata")
    return members, envelopes


def project_direct_chat_metadata(metadata: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Return only the caller's wrapper in the legacy outbound key field."""
    user_hash = hash_id(user_id)
    if isinstance(metadata, _DirectProjection):
        if metadata.user_hash != user_hash:
            raise PermissionError("Direct chat access denied")
        return metadata
    members, envelopes = validate_direct_chat_metadata(metadata)
    if user_hash not in members:
        raise PermissionError("Direct chat access denied")
    projected = dict(metadata)
    projected["participant_user_hashes"] = members
    projected.pop("participant_key_envelopes", None)
    projected["encrypted_chat_key"] = envelopes[user_hash]["encrypted_chat_key"]
    return _DirectProjection(projected, user_hash)


async def require_direct_chat_access(
    directus_service: Any,
    metadata: dict[str, Any] | None,
    user_id: str,
    team_id: str | None = None,
) -> dict[str, Any]:
    """Check active Team and participant rows, then return caller-safe metadata."""
    if not is_direct_chat(metadata):
        raise ValueError("Not a direct chat")
    projected = project_direct_chat_metadata(metadata, user_id)
    team_hash = metadata["hashed_team_id"]
    if team_id is not None and hash_id(team_id) != team_hash:
        raise PermissionError("Direct chat access denied")
    params = {
        "filter[hashed_team_id][_eq]": team_hash,
        "filter[hashed_user_id][_eq]": hash_id(user_id),
        "filter[status][_eq]": "active",
        "fields": "id",
        "limit": 1,
    }
    rows = await directus_service.get_items(
        "team_memberships", params=params, no_cache=True, admin_required=True,
    )
    teams = await directus_service.get_items(
        "teams",
        params={
            "filter[hashed_team_id][_eq]": team_hash,
            "filter[status][_eq]": "active",
            "fields": "id",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    if not isinstance(rows, list) or not rows or not isinstance(teams, list) or not teams:
        raise PermissionError("Direct chat access denied")
    return projected


async def filter_direct_chat_metadata(
    directus_service: Any,
    rows: list[dict[str, Any]],
    user_id: str,
    team_id: str | None = None,
) -> list[dict[str, Any]]:
    """Filter and project mixed Team list/sync rows without exposing peer wrappers."""
    result = []
    for row in rows:
        if is_direct_chat(row):
            try:
                result.append(await require_direct_chat_access(directus_service, row, user_id, team_id))
            except (PermissionError, ValueError):
                continue
        else:
            result.append(row)
    return result
