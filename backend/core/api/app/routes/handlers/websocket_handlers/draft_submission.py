"""Keep independent composer drafts separate from public question submissions.

Ordinary sends tombstone the draft and notify the user's other devices.
Incognito and explicit separate submissions preserve it.
Uses the existing versioned cache and broadcast protocol.
Failure remains non-critical, matching the normal send behavior.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def clear_sent_message_draft(
    *,
    cache_service: Any,
    manager: Any,
    user_id: str,
    chat_id: str,
    message_id: str,
    device_hash: str,
    is_incognito: bool,
    preserve_draft: Any = False,
) -> None:
    if is_incognito or preserve_draft is True:
        return
    try:
        version = await cache_service.increment_and_tombstone_user_draft(
            user_id, chat_id
        )
        if version is not None:
            await manager.broadcast_to_user(
                message={
                    "type": "draft_deleted",
                    "payload": {"chat_id": chat_id, "draft_v": version},
                },
                user_id=user_id,
                exclude_device_hash=device_hash,
            )
        else:
            logger.warning("Could not tombstone draft after message submission")
    except Exception as exc:
        # Reconnect reconciliation and future draft updates remain the fallback.
        logger.warning(
            "Draft cleanup after submission unavailable: %s", type(exc).__name__
        )
