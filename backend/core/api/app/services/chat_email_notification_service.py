"""Completed-message email delivery; queues routing IDs and Vault ciphertext only.

Chat keys are never consulted. A notification preview is a separate, explicitly
consented envelope, expires after a day, and is decrypted only at dispatch.
"""
from __future__ import annotations

import hashlib
import json
import time
from html import escape
from typing import Any
from urllib.parse import quote

from backend.core.api.app.services.notification_email_preferences import (
    load_notification_user, notification_category_enabled, preview_enabled,
    resolve_notification_email,
)
from backend.core.api.app.services.notification_presence import has_active_human, is_message_viewed
from backend.core.api.app.services.direct_chat_access import is_direct_chat, require_direct_chat_access

CANDIDATE_TTL = 86400
RECONNECT_GRACE_SECONDS = 15
CHAT_EMAIL_TASK = "app.tasks.email_tasks.ai_response_notification_email_task.send_ai_response_notification"


def candidate_key(user_id: str, chat_id: str, message_id: str) -> str:
    identity = json.dumps([user_id, chat_id, message_id], separators=(",", ":"))
    return "chat_email_candidate:" + hashlib.sha256(identity.encode()).hexdigest()


def shorten_title(title: str | None) -> str:
    return " ".join((title or "").split())[:60]


def shorten_preview(content: str | None) -> str:
    return "\n".join((content or "").splitlines()[:10])[:2000]


def message_email_content(
    sender: str, chat_id: str, *, title: str = "", preview: str = "", team_id: str | None = None,
    workflow_routing: dict[str, Any] | None = None,
) -> tuple[str, dict]:
    from backend.shared.python_utils.frontend_url import get_frontend_base_url
    sender = " ".join(sender.split())[:120] or "Mate"
    title = shorten_title(title)
    subject = f"{title}: New message from {sender}" if title else f"{sender} messaged you in OpenMates."
    chat_url = f"{get_frontend_base_url()}/#chat-id={quote(chat_id, safe='')}" + (f"&team-id={quote(team_id, safe='')}" if team_id else "")
    if workflow_routing:
        from backend.core.api.app.services.workflow_chat_notification_service import message_url
        chat_url = message_url(workflow_routing)
    return subject, {
        "notification_text": escape(f"{sender} messaged you in OpenMates."),
        "chat_title": escape(title),
        "response_preview": escape(shorten_preview(preview)).replace("\n", "<br/>") if preview else "",
        "chat_url": chat_url,
        "settings_url": f"{get_frontend_base_url()}/#settings/notifications/chat",
    }


async def notification_chat_access(directus: Any, user_id: str, chat_id: str, team_id: str | None = None) -> bool:
    """Revalidate ownership or active Team membership without reading chat content."""
    metadata = await directus.chat.get_chat_metadata(chat_id, admin_required=True)
    if not isinstance(metadata, dict) or metadata.get("deleted"):
        return False
    if is_direct_chat(metadata):
        if not team_id:
            return False
        try:
            await require_direct_chat_access(directus, metadata, user_id, team_id)
            return True
        except (PermissionError, ValueError):
            return False
    if team_id:
        if metadata.get("hashed_team_id") != hashlib.sha256(team_id.encode()).hexdigest():
            return False
        membership = await directus.team.get_membership(team_id, user_id)
        return isinstance(membership, dict) and membership.get("status") == "active"
    return not metadata.get("hashed_team_id") and metadata.get("hashed_user_id") == hashlib.sha256(user_id.encode()).hexdigest()


async def _email_user(directus: Any, user_id: str, candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Workflow outbox retries must distinguish deletion from an unavailable read."""
    if candidate.get("source") == "workflow_delivery":
        from backend.core.api.app.services.workflow_chat_notification_service import load_workflow_notification_user
        return await load_workflow_notification_user(directus, user_id)
    return await load_notification_user(directus, user_id)


async def _email_access(directus: Any, user_id: str, chat_id: str, message_id: str, candidate: dict[str, Any]) -> bool:
    """The workflow fallback is exact-message admission, never general chat access."""
    if candidate.get("source") == "workflow_delivery":
        if candidate.get("team_id") or not candidate.get("workflow_delivery_id"):
            return False
        from backend.core.api.app.services.workflow_chat_notification_service import delivery_authority
        status, _ = await delivery_authority(directus, user_id=user_id, chat_id=chat_id, message_id=message_id,
                                             delivery_id=candidate["workflow_delivery_id"])
        return status == "eligible"
    return await notification_chat_access(directus, user_id, chat_id, candidate.get("team_id"))


async def enqueue_chat_email(
    *, cache_service: Any, directus_service: Any, encryption_service: Any,
    user_id: str, chat_id: str, message_id: str, sender_name: str = "Mate",
    source: str = "chat", sender_user_id: str | None = None, preview: str | None = None,
    title: str | None = None, team_id: str | None = None, completed_at: float | None = None,
    mate_category: str | None = None, workflow_delivery_id: str | None = None,
    queue_dispatch: bool = True,
) -> bool:
    """Accept a real completed message; tentative workflow outputs are excluded."""
    if source not in {"chat", "team", "workflow_delivery"} or not all((user_id, chat_id, message_id)) or sender_user_id == user_id:
        return False
    if not await _email_access(directus_service, user_id, chat_id, message_id, {"source": source, "team_id": team_id, "workflow_delivery_id": workflow_delivery_id}):
        return False
    # Suppress at completion as well as dispatch: closing the app after reading
    # a response must not turn that completed response into a delayed email.
    if await has_active_human(cache_service, user_id, chat_id):
        return False
    user = await _email_user(directus_service, user_id, {"source": source})
    if not user or user.get("status") != "active" or not notification_category_enabled(user, "aiResponses"):
        return False
    if source == "chat" and mate_category:
        from backend.core.api.app.services.translations import TranslationService
        mate_name = TranslationService().get_nested_translation(f"mates.{mate_category}", str(user.get("language") or "en"))
        if isinstance(mate_name, str) and mate_name and not mate_name.startswith("mates."):
            sender_name = mate_name
    now = time.time()
    candidate: dict[str, Any] = {
        "user_id": user_id, "chat_id": chat_id, "message_id": message_id,
        "sender_name": "A team member" if source == "team" else " ".join(sender_name.split())[:120], "source": source,
        "sender_user_id": sender_user_id, "team_id": team_id,
        "workflow_delivery_id": workflow_delivery_id,
        "completed_at": completed_at if completed_at is not None else now,
        "not_before": now + RECONNECT_GRACE_SECONDS,
    }
    if source == "team" and user.get("vault_key_id"):
        try:
            encrypted_sender_name, _ = await encryption_service.encrypt_with_user_key(
                " ".join(sender_name.split())[:120], user["vault_key_id"],
            )
            if encrypted_sender_name:
                candidate["encrypted_sender_name"] = encrypted_sender_name
        except Exception:
            pass  # Optional identity envelope; retain the generic sender fallback.
    if preview_enabled(user) and (preview or title) and user.get("vault_key_id"):
        plaintext = json.dumps({"title": shorten_title(title), "preview": shorten_preview(preview)})
        try:
            ciphertext, _ = await encryption_service.encrypt_with_user_key(plaintext, user["vault_key_id"])
            if ciphertext:
                candidate["encrypted_preview"] = ciphertext
        except Exception:
            pass  # Optional content must never prevent the content-free email.
    client = await cache_service.client
    key = candidate_key(user_id, chat_id, message_id)
    if await has_active_human(cache_service, user_id, chat_id):
        return False
    accepted = await client.set(key, json.dumps(candidate), nx=True, ex=CANDIDATE_TTL)
    if not accepted:
        return False
    if not queue_dispatch:
        return True
    from backend.core.api.app.tasks.celery_config import app as celery_app
    try:
        celery_app.send_task(CHAT_EMAIL_TASK, kwargs={"user_id": user_id, "chat_id": chat_id, "message_id": message_id},
                             countdown=RECONNECT_GRACE_SECONDS, queue="email")
    except Exception:
        await client.delete(key)
        raise
    return True


async def dispatch_chat_email(task: Any, *, user_id: str, chat_id: str, message_id: str) -> str:
    """Resolve consent, human activity, viewed state and verified recipient at send time."""
    from backend.core.api.app.services.email_delivery_guard import send_email_once
    client = await task.cache_service.client
    raw = await client.get(candidate_key(user_id, chat_id, message_id))
    if not raw:
        return "expired"
    candidate = json.loads(raw)
    if candidate.get("source") not in {"chat", "team", "workflow_delivery"} or candidate.get("sender_user_id") == user_id:
        return "excluded"
    if candidate.get("not_before", 0) > time.time():
        return "grace"
    user = await _email_user(task.directus_service, user_id, candidate)
    if not user or user.get("status") != "active" or not notification_category_enabled(user, "aiResponses"):
        return "disabled"
    if not await _email_access(task.directus_service, user_id, chat_id, message_id, candidate):
        return "unauthorized"
    recipient = await resolve_notification_email(task.directus_service, task.encryption_service, user)
    if not recipient:
        return "no_verified_address"
    if await has_active_human(task.cache_service, user_id, chat_id):
        return "active"
    if await is_message_viewed(task.cache_service, user_id, chat_id, message_id):
        return "viewed"
    sender = candidate.get("sender_name") or ("A team member" if candidate.get("source") == "team" else "Mate")
    if candidate.get("encrypted_sender_name") and user.get("vault_key_id"):
        try:
            sender = await task.encryption_service.decrypt_with_user_key(candidate["encrypted_sender_name"], user["vault_key_id"]) or sender
        except Exception:
            pass
    workflow_routing = None
    if candidate.get("source") == "workflow_delivery":
        from backend.core.api.app.services.workflow_chat_notification_service import load_delivery_notification, delivery_authority
        workflow_routing = await load_delivery_notification(task.directus_service, candidate["workflow_delivery_id"])
        authority, delivery = await delivery_authority(task.directus_service, user_id=user_id, chat_id=chat_id,
            message_id=message_id, delivery_id=candidate["workflow_delivery_id"])
        if authority != "eligible":
            return "unauthorized"
        workflow_routing = {**workflow_routing, "workflow_delivery_pending": not bool(delivery.get("client_persisted_at"))}
    subject, private_context = message_email_content(sender, chat_id, team_id=candidate.get("team_id"), workflow_routing=workflow_routing)
    context = dict(private_context)
    send_options = {"subject": subject}

    async def check_before_send() -> bool:
        # The transport gate may run again after awaiting provider credentials.
        # Never retain a preview from an earlier consent check.
        context.update(private_context)
        send_options["subject"] = subject
        # Reservation/database/crypto work may have allowed an opt-out, reconnect,
        # read receipt or membership revocation to arrive in the meantime.
        fresh = await _email_user(task.directus_service, user_id, candidate)
        if not fresh or fresh.get("status") != "active" or not notification_category_enabled(fresh, "aiResponses"):
            return False
        if not await _email_access(task.directus_service, user_id, chat_id, message_id, candidate):
            return False
        if await resolve_notification_email(task.directus_service, task.encryption_service, fresh) != recipient:
            return False
        if await has_active_human(task.cache_service, user_id, chat_id) or await is_message_viewed(task.cache_service, user_id, chat_id, message_id):
            return False
        if preview_enabled(fresh) and candidate.get("encrypted_preview") and fresh.get("vault_key_id"):
            try:
                plaintext = await task.encryption_service.decrypt_with_user_key(candidate["encrypted_preview"], fresh["vault_key_id"])
                if plaintext:
                    envelope = json.loads(plaintext)
                    preview_subject, preview_context = message_email_content(
                        sender, chat_id, title=envelope.get("title", ""), preview=envelope.get("preview", ""),
                        team_id=candidate.get("team_id"), workflow_routing=workflow_routing,
                    )
                    context.update(preview_context)
                    send_options["subject"] = preview_subject
            except Exception:
                pass
        # Decrypting an optional envelope is awaited work. Recheck after it so
        # a foreground return, read receipt or opt-out during crypto wins.
        current = await _email_user(task.directus_service, user_id, candidate)
        if not current or current.get("status") != "active" or not notification_category_enabled(current, "aiResponses"):
            return False
        if not preview_enabled(current):
            context.update(private_context)
            send_options["subject"] = subject
        if not await _email_access(task.directus_service, user_id, chat_id, message_id, candidate):
            return False
        if await resolve_notification_email(task.directus_service, task.encryption_service, current) != recipient:
            return False
        if await has_active_human(task.cache_service, user_id, chat_id) or await is_message_viewed(task.cache_service, user_id, chat_id, message_id):
            return False
        return True

    async def before_send() -> bool:
        try:
            return await check_before_send()
        except Exception as exc:
            if candidate.get("source") != "workflow_delivery":
                raise
            from backend.core.api.app.services.email_template import EmailSendDeferred
            raise EmailSendDeferred("Workflow message eligibility read unavailable") from exc

    sent, status = await send_email_once(
        directus=task.directus_service, email_template_service=task.email_template_service,
        email_type="chat_response", campaign_key=message_id, recipient_kind="directus_user",
        recipient_id=user_id, stage=chat_id, recipient_email=recipient, template="chat-message-notification",
        context=context, lang=str(user.get("language") or "en"),
        before_send=before_send, send_options=send_options, retry_cache=task.cache_service,
    )
    return "sent" if sent else status
