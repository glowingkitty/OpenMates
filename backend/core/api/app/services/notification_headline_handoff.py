"""Short-lived, Vault-sealed hand-off of the notification type and summary.

The post-processing step finishes after the answer stream. The API listener for
`post_processing_completed` seals `{type, summary}` with the user's Vault key
and parks it in Redis under a hash of (user, chat, task) for a few minutes. The
push path (and the email dispatch, behind its content consent) reads it back.
The summary derives from the plaintext answer the AI pipeline already handles
transiently; at rest in Redis it is ciphertext and expires on its own.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Optional

from backend.apps.ai.processing.notification_summary import NOTIFICATION_TYPES, notification_headline

logger = logging.getLogger(__name__)

HEADLINE_TTL_SECONDS = 600
POLL_INTERVAL_SECONDS = 0.5


def headline_key(user_id: str, chat_id: str, task_id: str) -> str:
    identity = json.dumps([user_id, chat_id, task_id], separators=(",", ":"))
    return "notification_headline:" + hashlib.sha256(identity.encode()).hexdigest()


async def lookup_vault_key_id(cache_service: Any, directus_service: Any, user_id: str) -> Optional[str]:
    cached = await cache_service.get_user_by_id(user_id)
    if isinstance(cached, dict) and cached.get("vault_key_id"):
        return str(cached["vault_key_id"])
    fields = await directus_service.get_user_fields_direct(user_id, ["vault_key_id"])
    return str(fields["vault_key_id"]) if isinstance(fields, dict) and fields.get("vault_key_id") else None


async def stage_headline(
    *, cache_service: Any, directus_service: Any, encryption_service: Any,
    user_id: str, chat_id: str, task_id: str,
    notification_type: Optional[str], summary: Optional[str],
) -> bool:
    """Seal and park a valid type/summary pair; anything else stores nothing."""
    if notification_type not in NOTIFICATION_TYPES or not summary:
        return False
    vault_key_id = await lookup_vault_key_id(cache_service, directus_service, user_id)
    if not vault_key_id:
        return False
    plaintext = json.dumps({"type": notification_type, "summary": summary}, ensure_ascii=False)
    ciphertext, _ = await encryption_service.encrypt_with_user_key(plaintext, vault_key_id)
    if not ciphertext:
        return False
    client = await cache_service.client
    await client.set(headline_key(user_id, chat_id, task_id), ciphertext, ex=HEADLINE_TTL_SECONDS)
    return True


async def read_headline(
    *, cache_service: Any, encryption_service: Any, vault_key_id: Optional[str],
    user_id: str, chat_id: str, task_id: Optional[str], wait_seconds: float = 0.0,
) -> Optional[str]:
    """Return "<icon> <summary>", polling up to `wait_seconds` for a late post-processing result."""
    if not task_id or not vault_key_id:
        return None
    client = await cache_service.client
    key = headline_key(user_id, chat_id, task_id)
    waited = 0.0
    sealed = await client.get(key)
    while not sealed and waited < wait_seconds:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS
        sealed = await client.get(key)
    if not sealed:
        return None
    plaintext = await encryption_service.decrypt_with_user_key(
        sealed.decode() if isinstance(sealed, bytes) else sealed, vault_key_id,
    )
    try:
        value = json.loads(plaintext) if plaintext else {}
        return notification_headline(value["type"], value["summary"])
    except (ValueError, KeyError, TypeError):
        logger.warning("Sealed notification headline was unreadable; using generic text")
        return None
