"""Authorize per-user draft mutations without confusing Team and Personal chats."""

from typing import Any

from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.services.direct_chat_access import is_direct_chat, require_direct_chat_access


TEAM_DRAFT_WRITE_ROLES = {"owner", "admin", "member"}


async def draft_change_allowed(
    directus_service: Any, user_id: str, chat_id: str, team_id: Any,
) -> bool:
    """A Team draft requires a committed Team chat and an active write member.

    A new, uncommitted Team chat keeps its draft locally. Personal draft-only
    chats retain their existing behavior; a Team chat cannot use that fallback.
    """
    if team_id is not None and (not isinstance(team_id, str) or not team_id.strip()):
        return False
    try:
        metadata = await directus_service.chat.get_chat_metadata(chat_id)
        if is_direct_chat(metadata):
            if not team_id:
                return False
            await require_direct_chat_access(directus_service, metadata, user_id, team_id)
            return True  # Active direct-chat viewers may write human turns/drafts.
        if team_id:
            if not metadata or metadata.get("hashed_team_id") != hash_id(team_id):
                return False
            await directus_service.team.require_team_role(
                team_id, user_id, TEAM_DRAFT_WRITE_ROLES,
            )
            return True
        if metadata and metadata.get("hashed_team_id"):
            return False
        if not metadata:
            return True  # Personal draft-only chat, not yet persisted.
        return bool(await directus_service.chat.check_chat_ownership(chat_id, user_id))
    except Exception:
        return False
