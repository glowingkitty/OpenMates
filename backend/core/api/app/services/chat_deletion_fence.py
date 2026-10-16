"""Require durable deletion authority before removing a saved chat's data."""

from __future__ import annotations

import re
from typing import Any

from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)


_OWNER_HASH = re.compile(r"[a-f0-9]{64}")


async def require_chat_deletion_fence(
    directus_service: Any,
    chat_id: str,
    *,
    hashed_user_id: str | None = None,
) -> dict[str, Any]:
    """Persist the fence, with a receipt that distinguishes the upgraded API.

    Authenticated callers supply the deletion actor. Older internal personal-chat
    callers can obtain its owner from current metadata. Team deletion always
    requires the explicit actor; the transaction rechecks its authority.
    """
    actor_hash = hashed_user_id
    if actor_hash is None:
        rows = await directus_service.get_items(
            "chats",
            params={
                "filter[id][_eq]": chat_id,
                "fields": "id,hashed_user_id,hashed_team_id",
                "limit": 1,
            },
            no_cache=True,
        )
        if not isinstance(rows, list) or len(rows) != 1 \
                or not isinstance(rows[0], dict) or rows[0].get("id") != chat_id:
            raise ChatRecoveryProtocolError(404, "chat_not_found")
        if rows[0].get("hashed_team_id"):
            raise ChatRecoveryProtocolError(403, "team_delete_actor_required")
        actor_hash = rows[0].get("hashed_user_id")
    if not isinstance(actor_hash, str) or not _OWNER_HASH.fullmatch(actor_hash):
        raise ValueError("Chat deletion requires an authoritative actor hash")

    receipt = await ChatRecoveryService(directus_service).execute(
        "invalidate_deletion",
        {
            "protocol_version": 1,
            "hashed_user_id": actor_hash,
            "scope": "chat",
            "chat_id": chat_id,
        },
    )
    if not isinstance(receipt, dict) \
            or receipt.get("chat_deletion_fenced") is not True \
            or receipt.get("chat_id") != chat_id:
        raise RuntimeError("Chat deletion did not confirm its durable fence")
    return receipt
