"""Team mail fanout and short-lived, recipient-consented preview envelopes.

Only the authenticated first-party WebSocket stage accepts plaintext. Redis holds
recipient Vault ciphertext for at most five minutes; the committed-message hook
decrypts it transiently for the existing notification queue's recipient envelope.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4
from typing import Any

from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.services.notification_email_preferences import (
    load_notification_user,
    notification_category_enabled,
    preview_enabled,
)

logger = logging.getLogger(__name__)
TEAM_ROLES = {"owner", "admin", "member", "viewer"}
TEAM_EMAIL_CATEGORY = "aiResponses"
MAX_PREVIEW_CHARS = 2000
MAX_TITLE_CHARS = 60
USER_SCAN_PAGE_SIZE = 200
MAX_USER_SCAN_PAGES = 100
PREVIEW_TTL_SECONDS = 300
CAPABILITY_TTL_SECONDS = 60


def _preview_key(team_id: str, chat_id: str, message_id: str, sender_id: str, recipient_id: str) -> str:
    return (f"team:notification:preview:{hash_id(team_id)}:{hash_id(chat_id)}:"
            f"{hash_id(message_id)}:{hash_id(sender_id)}:{hash_id(recipient_id)}")


def _capability_key(capability_id: str) -> str:
    return f"team:notification:capability:{capability_id}"


async def _require_scoped_chat(directus: Any, team_id: str, chat_id: str, actor_id: str) -> None:
    await directus.team.require_team_role(team_id, actor_id, {"owner", "admin", "member"})
    chat = await directus.chat.get_chat_metadata(chat_id)
    if not isinstance(chat, dict) or chat.get("hashed_team_id") != hash_id(team_id):
        raise PermissionError("Team chat scope mismatch")


async def active_team_recipient_ids(
    directus: Any, team_id: str, sender_id: str, *, exclude_sender: bool = True,
) -> tuple[str, ...]:
    """Resolve membership hashes, including accounts without passkeys.

    The indexed passkey lookup handles the common case. A paginated id-only
    Directus scan covers password-only accounts until every member is resolved.
    """
    hashes = await directus.team.list_active_member_hashes(team_id)
    pending = hashes - ({hash_id(sender_id)} if exclude_sender else set())
    recipients: list[str] = []
    for member_hash in tuple(pending):
        member_id = await directus.get_user_id_from_hashed_user_id(member_hash)
        if isinstance(member_id, str) and hash_id(member_id) == member_hash:
            recipients.append(member_id)
            pending.discard(member_hash)
    for page in range(1, MAX_USER_SCAN_PAGES + 1):
        if not pending:
            break
        rows = await directus.get_items(
            "directus_users",
            params={"fields": "id", "page": page, "limit": USER_SCAN_PAGE_SIZE},
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(rows, list):
            raise RuntimeError("Team recipient identity lookup failed")
        for row in rows:
            member_id = row.get("id") if isinstance(row, dict) else None
            if isinstance(member_id, str) and hash_id(member_id) in pending:
                recipients.append(member_id)
                pending.discard(hash_id(member_id))
        if len(rows) < USER_SCAN_PAGE_SIZE:
            break
    if pending:
        logger.warning("Some active Team member identities could not be resolved for notification fanout")
    return tuple(dict.fromkeys(recipients))


async def issue_preview_capability(
    *, directus: Any, cache: Any, team_id: str, chat_id: str, sender_id: str,
) -> dict[str, Any]:
    await _require_scoped_chat(directus, team_id, chat_id, sender_id)
    eligible: list[str] = []
    for recipient_id in await active_team_recipient_ids(directus, team_id, sender_id):
        user = await load_notification_user(directus, recipient_id)
        if notification_category_enabled(user, TEAM_EMAIL_CATEGORY) and preview_enabled(user) and user.get("vault_key_id"):
            eligible.append(recipient_id)
    client = await cache.client
    if not client or not eligible:
        return {"capability_id": None, "recipient_count": 0}
    capability_id = str(uuid4())
    await client.set(
        _capability_key(capability_id),
        json.dumps({"sender_id": sender_id, "team_id": team_id, "chat_id": chat_id, "recipient_ids": eligible}),
        ex=CAPABILITY_TTL_SECONDS,
    )
    return {"capability_id": capability_id, "recipient_count": len(eligible)}


async def stage_team_preview(
    *, directus: Any, cache: Any, encryption: Any, team_id: str, chat_id: str,
    message_id: str, sender_id: str, capability_id: str, preview: str, title: str | None = None,
) -> int:
    if not isinstance(preview, str) or not preview or len(preview) > MAX_PREVIEW_CHARS:
        raise ValueError("Invalid preview length")
    if title is not None and (not isinstance(title, str) or len(title) > MAX_TITLE_CHARS):
        raise ValueError("Invalid title length")
    if not isinstance(message_id, str) or len(message_id) > 255 or not message_id:
        raise ValueError("Invalid message ID")
    await _require_scoped_chat(directus, team_id, chat_id, sender_id)
    client = await cache.client
    if not client:
        return 0
    raw = await client.get(_capability_key(capability_id))
    if not raw:
        raise PermissionError("Preview capability expired")
    capability = json.loads(raw)
    if any(capability.get(key) != value for key, value in (("sender_id", sender_id), ("team_id", team_id), ("chat_id", chat_id))):
        raise PermissionError("Preview capability scope mismatch")
    await client.delete(_capability_key(capability_id))
    active_hashes = await directus.team.list_active_member_hashes(team_id)
    count = 0
    for recipient_id in capability.get("recipient_ids", []):
        if recipient_id == sender_id or hash_id(recipient_id) not in active_hashes:
            continue
        user = await load_notification_user(directus, recipient_id)
        if not (notification_category_enabled(user, TEAM_EMAIL_CATEGORY) and preview_enabled(user)):
            continue
        vault_key_id = user.get("vault_key_id")
        if not vault_key_id:
            continue
        sealed, _ = await encryption.encrypt_with_user_key(
            json.dumps({"preview": preview, "title": title}, ensure_ascii=False), vault_key_id,
        )
        await client.set(
            _preview_key(team_id, chat_id, message_id, sender_id, recipient_id),
            sealed, ex=PREVIEW_TTL_SECONDS,
        )
        count += 1
    return count


async def _consume_team_preview(
    *, cache: Any, encryption: Any, team_id: str, chat_id: str, message_id: str,
    sender_id: str, recipient_id: str, vault_key_id: str,
) -> tuple[str | None, str | None]:
    client = await cache.client
    if not client:
        return None, None
    key = _preview_key(team_id, chat_id, message_id, sender_id, recipient_id)
    sealed = await client.get(key)
    if not sealed:
        return None, None
    await client.delete(key)
    if isinstance(sealed, bytes):
        sealed = sealed.decode("utf-8")
    try:
        envelope = json.loads(await encryption.decrypt_with_user_key(sealed, vault_key_id))
        return envelope.get("preview"), envelope.get("title")
    except Exception:
        return None, None


async def _sender_display_name(directus: Any, encryption: Any, sender_id: str) -> str:
    sender = await directus.get_user_fields_direct(sender_id, ["id", "encrypted_username", "vault_key_id"])
    if not isinstance(sender, dict) or sender.get("id") != sender_id:
        return "A team member"
    if not sender.get("encrypted_username") or not sender.get("vault_key_id"):
        return "A team member"
    try:
        name = await encryption.decrypt_with_user_key(sender["encrypted_username"], sender["vault_key_id"])
        name = " ".join(str(name).split())[:80]
        return name or "A team member"
    except Exception:
        return "A team member"


async def queue_committed_team_message(
    *, directus: Any, cache: Any, encryption: Any, team_id: str, chat_id: str,
    message_id: str, sender_id: str,
) -> int:
    """Queue only after the encrypted user message has committed."""
    await _require_scoped_chat(directus, team_id, chat_id, sender_id)
    from backend.core.api.app.services.chat_email_notification_service import enqueue_chat_email

    sender_name = await _sender_display_name(directus, encryption, sender_id)
    count = 0
    for recipient_id in await active_team_recipient_ids(directus, team_id, sender_id):
        try:
            user = await load_notification_user(directus, recipient_id)
            if not notification_category_enabled(user, TEAM_EMAIL_CATEGORY):
                continue
            preview = title = None
            if preview_enabled(user) and user.get("vault_key_id"):
                preview, title = await _consume_team_preview(
                    cache=cache, encryption=encryption, team_id=team_id,
                    chat_id=chat_id, message_id=message_id, sender_id=sender_id,
                    recipient_id=recipient_id,
                    vault_key_id=user["vault_key_id"],
                )
            queued = await enqueue_chat_email(
                cache_service=cache, directus_service=directus, encryption_service=encryption,
                user_id=recipient_id, chat_id=chat_id, message_id=message_id,
                sender_name=sender_name, source="team", sender_user_id=sender_id,
                preview=preview, title=title, team_id=team_id,
            )
            count += int(bool(queued))
        except Exception:
            logger.exception("Team notification enqueue failed for an eligible recipient")
    return count


async def queue_committed_team_message_by_hash(
    *, directus: Any, cache: Any, encryption: Any, hashed_team_id: str,
    chat_id: str, message_id: str, sender_id: str,
) -> int:
    """Legacy persistence adapter; resolve the exact Team identity server-side."""
    team_id = await _active_team_id_from_hash(directus, hashed_team_id)
    if not team_id:
        return 0
    return await queue_committed_team_message(
        directus=directus, cache=cache, encryption=encryption,
        team_id=team_id, chat_id=chat_id, message_id=message_id, sender_id=sender_id,
    )


async def _active_team_id_from_hash(directus: Any, hashed_team_id: str) -> str | None:
    rows = await directus.get_items(
        "teams",
        params={
            "filter[hashed_team_id][_eq]": hashed_team_id,
            "filter[status][_eq]": "active",
            "fields": "team_id,hashed_team_id",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    row = rows[0] if isinstance(rows, list) and rows else None
    team_id = row.get("team_id") if isinstance(row, dict) else None
    if not isinstance(team_id, str) or hash_id(team_id) != hashed_team_id:
        return None
    return team_id


async def queue_completed_team_mate_response(
    *, directus: Any, cache: Any, encryption: Any, initiating_user_id: str,
    chat_id: str, message_id: str, mate_category: str | None = None,
    preview: str | None = None, title: str | None = None,
) -> bool:
    """Fan out one user-visible completed Mate response to every active Team member.

    The caller first applies the existing completed/user-visible workflow gate.
    True means the chat is Team scoped and private-chat fallback must not run.
    """
    chat = await directus.chat.get_chat_metadata(chat_id, admin_required=True)
    if not isinstance(chat, dict) or not chat.get("hashed_team_id"):
        return False
    if chat.get("deleted"):
        return True
    hashed_team_id = chat["hashed_team_id"]
    team_id = await _active_team_id_from_hash(directus, hashed_team_id)
    if not team_id:
        return True
    try:
        await directus.team.require_team_role(team_id, initiating_user_id, TEAM_ROLES)
    except PermissionError:
        return True
    # Authoritative metadata must continue to match the resolved Team identity.
    if hash_id(team_id) != hashed_team_id:
        return True
    from backend.core.api.app.services.chat_email_notification_service import enqueue_chat_email

    for recipient_id in await active_team_recipient_ids(
        directus, team_id, initiating_user_id, exclude_sender=False,
    ):
        try:
            user = await load_notification_user(directus, recipient_id)
            if not notification_category_enabled(user, TEAM_EMAIL_CATEGORY):
                continue
            await enqueue_chat_email(
                cache_service=cache, directus_service=directus, encryption_service=encryption,
                user_id=recipient_id, chat_id=chat_id, message_id=message_id,
                sender_name="Mate", source="chat", team_id=team_id,
                mate_category=mate_category,
                preview=preview if preview_enabled(user) else None,
                title=title if preview_enabled(user) else None,
            )
        except Exception:
            logger.exception("Team Mate response notification enqueue failed for an eligible recipient")
    return True
