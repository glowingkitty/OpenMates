"""Ordinary chat alerts for each durable Workflow Send-message output.

The outbox is admitted atomically with pending Vault ciphertext. Delivery becomes
eligible after normal client ciphertext is committed, or a successful run confirms
a still-valid pending output. Execution status itself never produces an alert.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any
from urllib.parse import quote

from backend.core.api.app.services.notification_event_service import NotificationEvent, NotificationEventService
from backend.core.api.app.services.notification_presence import has_active_human, is_message_viewed
from backend.core.api.app.services.notification_email_preferences import NOTIFICATION_USER_FIELDS, preview_enabled
from backend.core.api.app.services.push_notification_service import push_notification_service
from backend.core.api.app.services.push_subscription_targets import normalize_push_subscription_targets, push_target_id
from backend.shared.python_utils.frontend_url import get_frontend_base_url

logger = logging.getLogger(__name__)
COLLECTION = "workflow_chat_notifications"
ROUTING_FIELDS = ("chat_id", "message_id", "delivery_id", "workflow_id", "run_id")


def message_notification_id(user_id: str, chat_id: str, message_id: str) -> str:
    """Stable identity shared by retries and client persistence/ACK replay."""
    return "chat-message-" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:chat-notification:{user_id}:{chat_id}:{message_id}"))


def message_url(row: dict[str, Any]) -> str:
    """Route to the exact actual message, including authenticated pending recovery."""
    fields = ROUTING_FIELDS if row.get("workflow_delivery_pending", True) else ("chat_id", "message_id")
    params = [(key.replace("_", "-"), row[key]) for key in fields]
    if "delivery_id" in fields:
        params.append(("workflow-tab", "runs"))
    return get_frontend_base_url() + "/#" + "&".join(f"{key}={quote(str(value), safe='')}" for key, value in params)


def enqueue_delivery_notification(delivery_id: str) -> None:
    """Wake the dispatcher; the durable outbox recovers an uncertain broker call."""
    try:
        from backend.core.api.app.tasks.celery_config import app
        app.send_task("workflows.dispatch_chat_notification", args=[delivery_id], queue="workflow")
    except Exception:
        logger.exception("Workflow chat notification enqueue failed; outbox will recover")


async def load_workflow_notification_user(directus: Any, user_id: str, fields: list[str] | None = None) -> dict[str, Any] | None:
    """Only a confirmed 404 is deletion; transient storage failures must retry."""
    requested = list(dict.fromkeys(["id", *(fields or NOTIFICATION_USER_FIELDS)]))
    url = f"{directus.base_url}/users/{quote(user_id, safe='')}?fields={','.join(requested)}&_ts={time.time_ns()}"
    response = await directus._make_api_request("GET", url, headers={"Cache-Control": "no-store"})
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RuntimeError(f"Workflow chat notification user lookup returned HTTP {response.status_code}")
    user = response.json().get("data")
    if not isinstance(user, dict) or user.get("id") != user_id:
        raise RuntimeError("Workflow chat notification user lookup identity mismatch")
    return {key: user.get(key) for key in requested}


async def load_delivery_notification(directus: Any, delivery_id: str) -> dict[str, Any] | None:
    rows = await directus.get_items(COLLECTION, params={"filter": {"delivery_id": {"_eq": delivery_id}}, "limit": 1},
                                   admin_required=True, no_cache=True, raise_on_error=True)
    return rows[0] if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) else None


async def delivery_authority(
    directus: Any, *, user_id: str, chat_id: str, message_id: str, delivery_id: str,
) -> tuple[str, dict[str, Any] | None]:
    """Verify exact owner/message admission without accepting or reading chat keys."""
    row = await load_delivery_notification(directus, delivery_id)
    if not row or any(row.get(key) != value for key, value in {
        "owner_user_id": user_id, "chat_id": chat_id, "message_id": message_id,
        "notification_id": message_notification_id(user_id, chat_id, message_id),
    }.items()):
        return "unauthorized", None
    rows = await directus.get_items("workflow_chat_deliveries", params={"filter": {"_and": [
        {"delivery_id": {"_eq": delivery_id}}, {"hashed_user_id": {"_eq": hashlib.sha256(user_id.encode()).hexdigest()}},
        *[{key: {"_eq": row[key]}} for key in ("chat_id", "message_id", "workflow_id", "run_id")],
    ]}, "limit": 1}, admin_required=True, no_cache=True, raise_on_error=True)
    delivery = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
    if not isinstance(delivery, dict):
        return "unauthorized", None
    # A missing pending chat is expected, but a failed read is not proof of
    # absence. Use strict storage reads rather than metadata helpers that swallow
    # transport errors into None, including at the final email/push gates.
    chats = await directus.get_items("chats", params={"filter": {"id": {"_eq": chat_id}},
        "fields": "id,hashed_user_id,hashed_team_id,chat_visibility,participant_user_hashes,participant_key_envelopes", "limit": 1},
        admin_required=True, no_cache=True, raise_on_error=True)
    metadata = chats[0] if chats else None
    from backend.core.api.app.services.direct_chat_access import is_direct_chat
    if isinstance(metadata, dict) and is_direct_chat(metadata):
        return "unauthorized", None
    if metadata is not None and (not isinstance(metadata, dict) or metadata.get("hashed_team_id")
            or metadata.get("hashed_user_id") != hashlib.sha256(user_id.encode()).hexdigest()):
        return "unauthorized", None
    if delivery.get("client_persisted_at"):
        if metadata is None:
            return "unauthorized", None
        messages = await directus.get_items("messages", params={"filter": {"client_message_id": {"_eq": message_id},
            "chat_id": {"_eq": chat_id}, "hashed_user_id": {"_eq": hashlib.sha256(user_id.encode()).hexdigest()}},
            "fields": "id", "limit": 1}, admin_required=True, no_cache=True, raise_on_error=True)
        if not messages:
            return "unauthorized", None
        from backend.core.api.app.services.push_reply_context import reply_workspace
        # Only committed canonical metadata can create normal inline-Reply
        # context. Pending Vault output has no chat-owned reply authority.
        return "eligible", {**delivery, "_notification_reply_workspace": reply_workspace(metadata, user_id, chat_id)}
    if delivery.get("status") not in {"delivery_pending", "claimed"} or not delivery.get("encrypted_payload"):
        return "skipped", None
    if not isinstance(delivery.get("expires_at"), (int, float)) or delivery["expires_at"] <= time.time():
        return "expired", None
    runs = await directus.get_items("workflow_runs", params={"filter": {"run_id": {"_eq": row["run_id"]},
        "workflow_id": {"_eq": row["workflow_id"]}, "hashed_user_id": {"_eq": "user_sha256:" + hashlib.sha256(user_id.encode()).hexdigest()}},
        "fields": "status", "limit": 1}, admin_required=True, no_cache=True, raise_on_error=True)
    if not runs:
        return "unauthorized", None
    status = runs[0].get("status")
    if status == "completed":
        return "eligible", delivery
    return ("skipped", None) if status in {"failed", "cancelled", "deleted", "skipped_by_user"} else ("pending", delivery)


def _routing(row: dict[str, Any], delivery: dict[str, Any]) -> dict[str, Any]:
    fields = ("chat_id", "message_id") if delivery.get("client_persisted_at") else ROUTING_FIELDS
    return {key: row[key] for key in fields}


async def _update(directus: Any, row: dict[str, Any], **changes: Any) -> None:
    if not await directus.update_item(COLLECTION, row["id"], {**changes, "updated_at": int(time.time())}, admin_required=True):
        raise RuntimeError("Workflow chat notification state was not persisted")
    row.update(changes)


async def _visible(task: Any, row: dict[str, Any]) -> bool:
    return await has_active_human(task.cache_service, row["owner_user_id"], row["chat_id"]) or await is_message_viewed(
        task.cache_service, row["owner_user_id"], row["chat_id"], row["message_id"])


async def _push(task: Any, row: dict[str, Any]) -> str:
    user_id = row["owner_user_id"]
    fields = ["id", "status", "language", "push_notification_enabled", "push_notification_preferences", "push_notification_subscription"]
    user = await load_workflow_notification_user(task.directus_service, user_id, fields)
    prefs = user.get("push_notification_preferences") or {} if isinstance(user, dict) else {}
    if isinstance(prefs, str):
        prefs = json.loads(prefs)
    if not isinstance(user, dict) or user.get("id") != user_id or user.get("status") != "active" or user.get("push_notification_enabled") is not True or not isinstance(prefs, dict) or prefs.get("aiResponses", True) is not True:
        return "disabled"
    targets = normalize_push_subscription_targets(user.get("push_notification_subscription"))
    if not targets:
        return "unavailable"
    await push_notification_service.initialize(task.secrets_manager)
    states = row.get("push_target_states") or {}
    if isinstance(states, str):
        states = json.loads(states)
    states = dict(states)
    for target in targets:
        key = push_target_id(target)
        if not key or key in states:
            continue
        is_apns = target.get("type") == "apns"
        if not (push_notification_service.is_apns_ready() if is_apns else push_notification_service.is_ready()):
            continue
        # Revalidate fresh ownership, consent, target registration and foreground
        # state immediately before each external send.
        authority, current_delivery = await delivery_authority(task.directus_service, user_id=user_id, chat_id=row["chat_id"],
                                                message_id=row["message_id"], delivery_id=row["delivery_id"])
        fresh = await load_workflow_notification_user(task.directus_service, user_id, fields)
        fresh_prefs = fresh.get("push_notification_preferences") or {} if isinstance(fresh, dict) else {}
        if isinstance(fresh_prefs, str):
            fresh_prefs = json.loads(fresh_prefs)
        if authority != "eligible" or not isinstance(fresh, dict) or fresh.get("status") != "active" or fresh.get("push_notification_enabled") is not True or not isinstance(fresh_prefs, dict) or fresh_prefs.get("aiResponses", True) is not True:
            return "disabled"
        registered = {push_target_id(t): t for t in normalize_push_subscription_targets(fresh.get("push_notification_subscription"))}
        if key not in registered:
            continue
        target = registered[key]
        if await _visible(task, row):
            return "suppressed"
        states[key] = "attempting"
        await _update(task.directus_service, row, push_target_states=states)
        result: list[str] = []
        accepted = await asyncio.to_thread(push_notification_service.send_push_notification,
            subscription_json=json.dumps(target), title="OpenMates", body="You received a new message.",
            url=message_url({**row, "workflow_delivery_pending": not bool(current_delivery.get("client_persisted_at"))}), tag=row["notification_id"], chat_id=row["chat_id"], message_id=row["message_id"],
            category="OPENMATES_CHAT_MESSAGE", recipient_account_id=user_id,
            workspace=current_delivery.get("_notification_reply_workspace") if current_delivery.get("client_persisted_at") else None,
            workflow_routing=_routing(row, current_delivery), on_apns_result=result.append)
        if accepted:
            states[key] = "accepted"
        elif result == ["retryable_reject"]:
            states.pop(key)
        elif result == ["permanent_reject"]:
            states[key] = "failed"
        # An uncertain response retains the attempt marker: providers cannot
        # transactionally commit with our database and must not get a duplicate.
        await _update(task.directus_service, row, push_target_states=states)
    if any(push_target_id(target) not in states for target in targets):
        return "pending"
    return "accepted" if "accepted" in states.values() else "uncertain" if "attempting" in states.values() else "failed"


async def _email(task: Any, row: dict[str, Any], delivery: dict[str, Any]) -> str:
    from backend.core.api.app.services.chat_email_notification_service import candidate_key, dispatch_chat_email, enqueue_chat_email
    user_id = row["owner_user_id"]
    client = await task.cache_service.client
    if not await client.get(candidate_key(user_id, row["chat_id"], row["message_id"])):
        user = await load_workflow_notification_user(task.directus_service, user_id)
        title = preview = None
        if preview_enabled(user) and delivery.get("encrypted_payload") and user.get("vault_key_id"):
            try:
                envelope = json.loads(delivery["encrypted_payload"])
                # Always use the freshly authorized user's Vault key, never an
                # envelope-controlled key or any normal chat key.
                plaintext = await task.encryption_service.decrypt_with_user_key(envelope["ciphertext"], user["vault_key_id"])
                content = json.loads(plaintext)
                title, preview = content.get("title"), content.get("message")
            except Exception:
                logger.warning("Optional workflow chat notification preview unavailable", exc_info=True)
        accepted = await enqueue_chat_email(cache_service=task.cache_service, directus_service=task.directus_service,
            encryption_service=task.encryption_service, user_id=user_id, chat_id=row["chat_id"], message_id=row["message_id"],
            source="workflow_delivery", workflow_delivery_id=row["delivery_id"], title=title, preview=preview, queue_dispatch=False,
            completed_at=delivery.get("client_persisted_at") or delivery.get("created_at"))
        if not accepted:
            return "suppressed"
    result = await dispatch_chat_email(task, user_id=user_id, chat_id=row["chat_id"], message_id=row["message_id"])
    if result in {"grace", "failed", "retry_locked", "retry_unavailable", "provider_receipt_missing"}:
        return "pending"
    if result in {"already_reserved", "retry_unsafe_transport"}:
        from backend.core.api.app.services.email_delivery_guard import build_delivery_key, build_delivery_id
        identity = build_delivery_id(build_delivery_key(email_type="chat_response", campaign_key=row["message_id"],
            recipient_kind="directus_user", recipient_id=user_id, stage=row["chat_id"]))
        receipts = await task.directus_service.get_items("email_deliveries", params={"filter": {"id": {"_eq": identity}},
            "fields": "status", "limit": 1}, admin_required=True, no_cache=True, raise_on_error=True)
        if receipts and receipts[0].get("status") == "sent":
            return "sent"
    return result


async def dispatch_chat_notification(task: Any, delivery_id: str) -> dict[str, str]:
    """Each ordinary channel progresses independently from Workflow status."""
    row = await load_delivery_notification(task.directus_service, delivery_id)
    if not row:
        return {"status": "missing"}
    authority, delivery = await delivery_authority(task.directus_service, user_id=row["owner_user_id"],
        chat_id=row["chat_id"], message_id=row["message_id"], delivery_id=delivery_id)
    if authority != "eligible":
        if authority != "pending":
            for field in ("event_state", "push_state", "email_state"):
                if row.get(field) == "pending":
                    await _update(task.directus_service, row, **{field: authority})
        return {"status": authority}
    result = {"status": "eligible"}
    for channel in ("event", "push", "email"):
        field = channel + "_state"
        if row.get(field) != "pending":
            result[channel] = str(row.get(field))
            continue
        try:
            if await _visible(task, row):
                state = "suppressed"
            elif channel == "event":
                event = NotificationEvent(id=row["notification_id"], user_id=row["owner_user_id"],
                    type="chat.assistant_message_received", safe_title_key="apps.openmates",
                    safe_body_key="notifications.chat_message.new_message_received",
                    routing=_routing(row, delivery))
                await NotificationEventService(task.cache_service).store_and_publish_once(event)
                state = "published"
            elif channel == "push":
                state = await _push(task, row)
            else:
                state = await _email(task, row, delivery)
            await _update(task.directus_service, row, **{field: state})
            result[channel] = state
        except Exception:
            logger.exception("Workflow actual-message %s notification pending for delivery %s", channel, delivery_id)
            result[channel] = "pending"
    return result


async def enqueue_run_notifications(directus: Any, run_id: str) -> int:
    """Wake every actual output after success, without selecting only the first."""
    rows = await directus.get_items(COLLECTION, params={"filter": {"run_id": {"_eq": run_id}}, "fields": "delivery_id", "limit": -1},
                                   admin_required=True, no_cache=True, raise_on_error=True)
    for row in rows:
        enqueue_delivery_notification(row["delivery_id"])
    return len(rows)
