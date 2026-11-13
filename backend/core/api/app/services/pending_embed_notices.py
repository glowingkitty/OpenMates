"""Content-free pending "embed updated" notices of a chat.

Specification: feature.embed-user-edits (event.project-edit-reaches-chat).
Plan: docs/plans/embed-user-edit-versions.

A user revision commit of an embed that has a chat writes one row in
``pending_embed_notices`` (hashed chat id, embed id, version, action) in the
same transaction. Only the client core holds the chat key, so a device of the
chat reads the pending rows, writes the chat-key encrypted system message with
the deterministic id ``embed-updated-<embed_id>-v<version>`` and the server
deletes the row when that message is stored. A second device writing the same
id is a duplicate the persistence task skips, and it clears the row again.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

NOTICES_COLLECTION = "pending_embed_notices"
NOTICE_PAGE_LIMIT = 100
# The embed id may contain hyphens; the version is the digits after the last "-v".
_EVENT_MESSAGE_ID = re.compile(r"^embed-updated-(?P<embed_id>[A-Za-z0-9._:-]{1,128})-v(?P<version>[1-9][0-9]{0,9})$")


def embed_updated_message_id(embed_id: str, version: int) -> str:
    """Deterministic id of the system message that announces one user version."""
    return f"embed-updated-{embed_id}-v{version}"


def parse_embed_updated_message_id(message_id: object) -> tuple[str, int] | None:
    """Return ``(embed_id, version)`` for an embed-updated event id, else ``None``."""
    if not isinstance(message_id, str):
        return None
    match = _EVENT_MESSAGE_ID.fullmatch(message_id)
    if match is None:
        return None
    version = int(match.group("version"))
    if version > 2_147_483_647:
        return None
    return match.group("embed_id"), version


async def clear_pending_embed_notice(directus_service: Any, *, chat_id: str, message_id: str) -> int:
    """Delete the notice a just-stored system message answers; 0 when none matches."""
    parsed = parse_embed_updated_message_id(message_id)
    if parsed is None:
        return 0
    embed_id, version = parsed
    deleted = await directus_service.delete_items(
        NOTICES_COLLECTION,
        {
            "hashed_chat_id": {"_eq": hashlib.sha256(chat_id.encode()).hexdigest()},
            "embed_id": {"_eq": embed_id},
            "version": {"_eq": version},
        },
        admin_required=True,
    )
    if deleted:
        logger.info("Cleared pending embed notice for embed %s version %s", embed_id[:8], version)
    return int(deleted or 0)


async def list_pending_embed_notices(directus_service: Any, *, chat_id: str) -> list[dict[str, Any]]:
    """Oldest-first pending notices of one chat (authorization is the caller's)."""
    rows = await directus_service.get_items(
        NOTICES_COLLECTION,
        params={
            "filter[hashed_chat_id][_eq]": hashlib.sha256(chat_id.encode()).hexdigest(),
            "fields": "embed_id,version,action,surface,restored_from,created_at",
            "sort": "created_at,version",
            "limit": NOTICE_PAGE_LIMIT,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Pending embed notice lookup failed")
    notices = []
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("embed_id"), str)
                or type(row.get("version")) is not int or not isinstance(row.get("action"), str)
                or row.get("surface") not in ("chat", "project")
                or (row["action"] == "restore") != (type(row.get("restored_from")) is int)):
            raise RuntimeError("Pending embed notice row is malformed")
        notice = {
            "embed_id": row["embed_id"],
            "version": row["version"],
            "action": row["action"],
            "surface": row["surface"],
            "created_at": row.get("created_at"),
            "message_id": embed_updated_message_id(row["embed_id"], row["version"]),
        }
        if row["action"] == "restore":
            notice["restored_from"] = row["restored_from"]
        notices.append(notice)
    return notices
