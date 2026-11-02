"""Live owner/Team visibility fence for startup and background sync reads.

Every sync phase re-checks that a chat is still in the caller's scope right
before encrypted content is read or sent. Rows the caller already read through
an owner/Team-filtered query can be passed as ``known_metadata``; every other
id is resolved with one batched Directus read instead of one GET per chat.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from backend.core.api.app.services.direct_chat_access import (
    is_direct_chat, require_direct_chat_access,
)

if TYPE_CHECKING:
    from backend.core.api.app.services.directus import DirectusService


def _sync_metadata_in_scope(
    metadata: Any, user_id: str, team_id: Optional[str],
) -> bool:
    """Owner/Team predicate shared by every live sync visibility fence."""
    if not isinstance(metadata, dict):
        return False
    if team_id:
        return metadata.get("hashed_team_id") == hashlib.sha256(team_id.encode()).hexdigest()
    return (
        not metadata.get("hashed_team_id")
        and metadata.get("hashed_user_id") == hashlib.sha256(user_id.encode()).hexdigest()
    )


async def _live_visible_sync_chat_metadata(
    directus_service: DirectusService, chat_ids: List[str], user_id: str,
    team_id: Optional[str],
    known_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return caller-safe metadata for visible chats, in input order.

    ``known_metadata`` holds rows the caller read moments earlier through an
    owner/Team-filtered query; only ids missing from it are read, with one
    batched Directus call. Missing or out-of-scope chats are skipped, and
    direct chats always re-check live membership (fail closed).
    """
    ordered_ids = list(dict.fromkeys(str(chat_id) for chat_id in chat_ids if chat_id))
    known = known_metadata or {}
    unknown_ids = [chat_id for chat_id in ordered_ids if chat_id not in known]
    fetched: Dict[str, Dict[str, Any]] = {}
    if unknown_ids:
        fetched = await directus_service.chat.get_chats_metadata_batch(
            unknown_ids, admin_required=True,
        ) or {}
    visible: Dict[str, Dict[str, Any]] = {}
    for chat_id in ordered_ids:
        metadata = known.get(chat_id) if chat_id in known else fetched.get(chat_id)
        if not _sync_metadata_in_scope(metadata, user_id, team_id):
            continue
        if is_direct_chat(metadata):
            try:
                metadata = await require_direct_chat_access(directus_service, metadata, user_id, team_id)
            except (PermissionError, ValueError):
                continue
        visible[chat_id] = metadata
    return visible


async def _live_visible_sync_chat_ids(
    directus_service: DirectusService, chat_ids: List[str], user_id: str,
    team_id: Optional[str],
    known_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Recheck direct-chat access immediately before encrypted content reads."""
    return list((await _live_visible_sync_chat_metadata(
        directus_service, chat_ids, user_id, team_id, known_metadata,
    )).keys())
