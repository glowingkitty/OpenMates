"""Durable, owner-scoped delivery of scheduled Workflow success notifications."""

from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import time
import uuid
from typing import Any
from urllib.parse import quote

from backend.core.api.app.services.email_delivery_guard import send_email_once
from backend.core.api.app.services.notification_email_preferences import (
    NOTIFICATION_USER_FIELDS, notification_category_enabled, preview_enabled,
    resolve_notification_email,
)
from backend.core.api.app.services.notification_event_service import (
    NotificationEvent, NotificationEventService,
)
from backend.core.api.app.services.push_notification_service import push_notification_service
from backend.core.api.app.services.translations import TranslationService
from backend.core.api.app.services.workflow_models import WorkflowNodeRunStatus, WorkflowNodeType, WorkflowRunDetail, WorkflowRunStatus
from backend.core.api.app.services.workflow_service import _hash_owner_id
from backend.shared.python_utils.frontend_url import get_frontend_base_url

logger = logging.getLogger(__name__)
COLLECTION = "workflow_completion_notifications"
NOTIFICATION_TYPE = "workflow.run_completed"
APNS_CATEGORY = "OPENMATES_WORKFLOW_COMPLETED"
_FIELDS = "id,run_id,workflow_id,owner_user_id,notification_id,chat_id,message_id,delivery_id,event_state,push_state,push_target_states,email_state,created_at,updated_at"


async def _load_user_strict(directus: Any, user_id: str, fields: list[str]) -> dict[str, Any] | None:
    """Distinguish confirmed deletion from a transient Directus lookup error."""
    from urllib.parse import quote as url_quote

    requested = list(dict.fromkeys(["id", *fields]))
    url = f"{directus.base_url}/users/{url_quote(user_id, safe='')}?fields={','.join(requested)}&_ts={time.time_ns()}"
    response = await directus._make_api_request("GET", url, headers={"Cache-Control": "no-store"})
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RuntimeError(f"Notification user lookup returned HTTP {response.status_code}")
    data = response.json().get("data")
    if not isinstance(data, dict) or data.get("id") != user_id:
        raise RuntimeError("Notification user lookup identity mismatch")
    return {field: data.get(field) for field in requested}


def notification_id(run_id: str) -> str:
    return "workflow-completed-" + run_id


def completion_url(row: dict[str, Any]) -> str:
    params = [
        ("workflow-id", row["workflow_id"]), ("workflow-tab", "runs"),
        ("run-id", row["run_id"]), ("workflow-completion", "1"),
    ]
    if all(row.get(key) for key in ("chat_id", "message_id", "delivery_id")):
        params.extend((key.replace("_", "-"), row[key]) for key in ("chat_id", "message_id", "delivery_id"))
    return get_frontend_base_url() + "/#" + "&".join(
        f"{key}={quote(str(value), safe='')}" for key, value in params
    )


def _apple_completion_targets(subscription: Any) -> list[dict[str, Any]]:
    targets = subscription.get("targets") if isinstance(subscription, dict) and subscription.get("type") == "multi" else [subscription]
    return [target for target in targets
            if isinstance(target, dict) and target.get("type") == "apns"
            and str(target.get("platform") or "apns").lower() in {"ios", "macos", "apns"}] if isinstance(targets, list) else []


async def load_completion(directus: Any, run_id: str) -> dict[str, Any] | None:
    rows = await directus.get_items(
        COLLECTION, params={"filter": {"run_id": {"_eq": run_id}}, "fields": _FIELDS, "limit": 1},
        admin_required=True, no_cache=True, raise_on_error=True,
    )
    return rows[0] if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) else None


async def owner_run_completion_projection(
    directus: Any, run: WorkflowRunDetail, owner_user_id: str,
) -> dict[str, str] | None:
    """Safe target IDs for an already authorized, non-deleted run detail."""
    if run.status != WorkflowRunStatus.COMPLETED or run.trigger_type != "schedule":
        return None
    row = await load_completion(directus, run.id)
    if not row or (row.get("workflow_id"), row.get("owner_user_id")) != (run.workflow_id, owner_user_id):
        return None
    if row.get("notification_id") != notification_id(run.id):
        return None
    result = {"notification_id": row["notification_id"]}
    if all(isinstance(row.get(key), str) and row[key] for key in ("chat_id", "message_id", "delivery_id")):
        result.update({key: row[key] for key in ("chat_id", "message_id", "delivery_id")})
    return result


async def reserve_completion(directus: Any, *, run_id: str, workflow_id: str, owner_user_id: str) -> None:
    """Create the recovery record before executing the accepted run's effects."""
    existing = await load_completion(directus, run_id)
    if existing:
        if (existing.get("workflow_id"), existing.get("owner_user_id")) != (workflow_id, owner_user_id):
            raise RuntimeError("Workflow completion identity collision")
        return
    now = int(time.time())
    row = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:workflow-completion:{run_id}")),
        "run_id": run_id, "workflow_id": workflow_id, "owner_user_id": owner_user_id,
        "notification_id": notification_id(run_id),
        "event_state": "pending", "push_state": "pending", "email_state": "pending",
        "created_at": now, "updated_at": now,
    }
    created, _ = await directus.create_item(
        COLLECTION, row, admin_required=True, expected_unique_conflict_field="run_id",
    )
    if not created:
        existing = await load_completion(directus, run_id)
        if not existing or (existing.get("workflow_id"), existing.get("owner_user_id")) != (workflow_id, owner_user_id):
            raise RuntimeError("Workflow completion outbox reservation failed")


async def record_first_chat_target(directus: Any, run: WorkflowRunDetail, owner_user_id: str) -> None:
    """Pin the first actually executed Send message before retention can remove content."""
    if run.status.value != "completed" or run.trigger_type != "schedule":
        return
    row = await load_completion(directus, run.id)
    if not row or row.get("owner_user_id") != owner_user_id or row.get("workflow_id") != run.workflow_id:
        raise RuntimeError("Workflow completion outbox missing or mismatched")
    if row.get("chat_id"):
        return
    owner_hash = hashlib.sha256(owner_user_id.encode()).hexdigest()
    for node in run.node_runs:
        if node.node_type != WorkflowNodeType.SEND_CHAT_MESSAGE or node.status != WorkflowNodeRunStatus.COMPLETED:
            continue
        output = node.output_summary
        # node_statuses retain execution order and stable iteration node IDs
        # after encrypted output retention prunes each node's output_summary.
        # Send message chooses this same deterministic UUID before persisting
        # the owner-scoped delivery, so it recovers the exact first effect.
        delivery_id = output.get("delivery_id") or str(uuid.uuid5(
            uuid.NAMESPACE_URL, f"openmates:workflow:{run.id}:{node.node_id}:delivery",
        ))
        deliveries = await directus.get_items(
            "workflow_chat_deliveries",
            params={"filter": {"_and": [
                {"delivery_id": {"_eq": delivery_id}}, {"run_id": {"_eq": run.id}},
                {"workflow_id": {"_eq": run.workflow_id}}, {"hashed_user_id": {"_eq": owner_hash}},
            ]}, "fields": "delivery_id,chat_id,message_id,status", "limit": 1},
            admin_required=True, no_cache=True, raise_on_error=True,
        )
        delivery = deliveries[0] if isinstance(deliveries, list) and len(deliveries) == 1 else None
        if not isinstance(delivery, dict) or delivery.get("status") not in {"delivery_pending", "claimed", "acknowledged", "expired"}:
            continue
        if not all(isinstance(delivery.get(key), str) and delivery[key] for key in ("chat_id", "message_id", "delivery_id")):
            continue
        persisted = await directus.update_item(COLLECTION, row["id"], {
            "chat_id": delivery["chat_id"], "message_id": delivery["message_id"],
            "delivery_id": delivery["delivery_id"], "updated_at": int(time.time()),
        }, admin_required=True)
        if not persisted:
            raise RuntimeError("Workflow completion chat target was not persisted")
        return


async def _confirmed_run(directus: Any, row: dict[str, Any]) -> bool:
    return await _finished_at(directus, row) is not None


async def _run_status(directus: Any, row: dict[str, Any]) -> str | None:
    rows = await directus.get_items(
        "workflow_runs", params={"filter": {"_and": [
            {"run_id": {"_eq": row["run_id"]}},
            {"workflow_id": {"_eq": row["workflow_id"]}},
            {"hashed_user_id": {"_eq": _hash_owner_id(row["owner_user_id"])}},
            {"trigger_type": {"_eq": "schedule"}},
        ]}, "fields": "status", "limit": 1},
        admin_required=True, no_cache=True, raise_on_error=True,
    )
    return rows[0].get("status") if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) else None


async def _finished_at(directus: Any, row: dict[str, Any]) -> int | None:
    rows = await directus.get_items(
        "workflow_runs", params={"filter": {"_and": [
            {"run_id": {"_eq": row["run_id"]}},
            {"workflow_id": {"_eq": row["workflow_id"]}},
            {"hashed_user_id": {"_eq": _hash_owner_id(row["owner_user_id"])}},
            {"trigger_type": {"_eq": "schedule"}}, {"status": {"_eq": "completed"}},
        ]}, "fields": "run_id,finished_at", "limit": 1},
        admin_required=True, no_cache=True, raise_on_error=True,
    )
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0].get("finished_at"), int):
        return rows[0]["finished_at"]
    return None


async def _update(directus: Any, row: dict[str, Any], field: str, state: str) -> None:
    persisted = await directus.update_item(COLLECTION, row["id"], {field: state, "updated_at": int(time.time())}, admin_required=True)
    if not persisted:
        raise RuntimeError("Workflow completion delivery state was not persisted")
    row[field] = state


async def dispatch_completion(task: Any, run_id: str, workflow_service: Any) -> dict[str, str]:
    """Reload all authorization and preferences; channels proceed independently."""
    directus = task.directus_service
    row = await load_completion(directus, run_id)
    if not row or row.get("notification_id") != notification_id(run_id):
        return {"status": "missing"}
    if not await _confirmed_run(directus, row):
        if await _run_status(directus, row) in {"failed", "cancelled", "skipped_by_user", "deleted"}:
            for channel in ("event_state", "push_state", "email_state"):
                if row.get(channel) == "pending":
                    await _update(directus, row, channel, "skipped")
        return {"status": "not_completed"}
    if not row.get("chat_id"):
        try:
            vault_key_id = await asyncio.to_thread(workflow_service.resolve_user_vault_key_id, row["owner_user_id"])
            run = await asyncio.to_thread(
                workflow_service.get_run, row["workflow_id"], row["run_id"],
                row["owner_user_id"], vault_key_id,
            )
            await record_first_chat_target(directus, run, row["owner_user_id"])
            refreshed = await load_completion(directus, run_id)
            if not refreshed:
                raise RuntimeError("Workflow completion outbox disappeared during target projection")
            row = refreshed
        except Exception:
            # A read or pin failure is not proof that Send message never ran.
            # Keep every channel pending until a retry can recover the exact
            # owner-scoped chat target from retained node execution identities.
            logger.exception("Workflow completion target projection pending for run %s", run_id)
            return {"status": "target_pending"}
    user_id = row["owner_user_id"]
    results: dict[str, str] = {"status": "completed"}
    if row.get("event_state") == "pending":
        try:
            event = NotificationEvent(
                id=row["notification_id"], user_id=user_id, type=NOTIFICATION_TYPE,
                safe_title_key="apps.openmates", safe_body_key="notifications.workflow_run.completed",
                routing={key: row[key] for key in ("workflow_id", "run_id", "chat_id", "message_id", "delivery_id") if row.get(key)},
            )
            await NotificationEventService(task.cache_service).store_and_publish_once(event)
            await _update(directus, row, "event_state", "published")
            results["event"] = "published"
        except Exception:
            logger.exception("Workflow completion event publish failed for run %s", run_id)
            results["event"] = "failed"
    for channel, dispatch in (("push", _dispatch_push), ("email", _dispatch_email)):
        try:
            results[channel] = await dispatch(task, row, workflow_service)
        except Exception:
            logger.exception("Workflow completion %s dispatch failed for run %s", channel, run_id)
            results[channel] = "failed"
    return results


async def _workflow_title(service: Any, row: dict[str, Any]) -> str | None:
    try:
        workflow = await asyncio.to_thread(service.get_workflow, row["workflow_id"], row["owner_user_id"])
        return workflow.title if isinstance(workflow.title, str) and workflow.title.strip() else None
    except Exception:
        return None


async def _dispatch_push(task: Any, row: dict[str, Any], service: Any) -> str:
    if row.get("push_state") != "pending":
        return str(row.get("push_state"))
    user = await _load_user_strict(
        task.directus_service,
        row["owner_user_id"],
        ["id", "status", "language", "push_notification_enabled", "push_notification_preferences", "push_notification_subscription"],
    )
    if not isinstance(user, dict) or user.get("id") != row["owner_user_id"] or user.get("status") != "active" or user.get("push_notification_enabled") is not True:
        await _update(task.directus_service, row, "push_state", "disabled")
        return "disabled"
    prefs = user.get("push_notification_preferences") or {}
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except ValueError:
            prefs = {}
    if not isinstance(prefs, dict) or prefs.get("workflowRuns", True) is False:
        await _update(task.directus_service, row, "push_state", "disabled")
        return "disabled"
    subscription = user.get("push_notification_subscription")
    try:
        subscription = json.loads(subscription) if isinstance(subscription, str) else subscription
    except ValueError:
        subscription = None
    targets = _apple_completion_targets(subscription)
    if not targets:
        await _update(task.directus_service, row, "push_state", "unavailable")
        return "unavailable"
    title = await _workflow_title(service, row)
    body = TranslationService().get_nested_translation(
        "notifications.workflow_run.completed", user.get("language") or "en",
    )
    if body == "notifications.workflow_run.completed":
        body = "Your scheduled Workflow completed"
    routing = {key: row[key] for key in ("workflow_id", "run_id", "notification_id", "chat_id", "message_id", "delivery_id") if row.get(key)}
    await push_notification_service.initialize(task.secrets_manager)
    if not push_notification_service.is_apns_ready():
        return "provider_unavailable"
    states = row.get("push_target_states") or {}
    if isinstance(states, str):
        try:
            states = json.loads(states)
        except ValueError:
            states = {}
    if not isinstance(states, dict):
        states = {}
    attempted_this_batch = 0
    for target in targets:
        token = target.get("token")
        if not isinstance(token, str) or not token:
            continue
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if key in states:
            continue
        if attempted_this_batch >= 10:
            break
        # APNs offers no transactional idempotency key. Persist each target's
        # external boundary before crossing it; an uncertain response stays
        # attempting and is never sent again.
        states[key] = "attempting"
        persisted = await task.directus_service.update_item(
            COLLECTION, row["id"], {"push_target_states": states, "updated_at": int(time.time())},
            admin_required=True,
        )
        if not persisted:
            raise RuntimeError("Workflow push attempt reservation was not persisted")
        attempted_this_batch += 1
        provider_result: list[str] = []
        accepted = await asyncio.to_thread(
            push_notification_service.send_push_notification,
            subscription_json=json.dumps(target), title="OpenMates",
            body=body, chat_id=row.get("chat_id"),
            category=APNS_CATEGORY, tag=row["notification_id"],
            workflow_routing=routing, encrypted_title=title,
            on_apns_result=provider_result.append,
        )
        if accepted:
            states[key] = "accepted"
        elif provider_result == ["retryable_reject"]:
            # APNs returned a definite non-acceptance. It is safe to retry.
            states.pop(key)
        elif provider_result == ["permanent_reject"]:
            states[key] = "failed"
        else:
            # No response, or transport failure after an uncertain send.
            # Retain the pre-send marker so replay cannot duplicate it.
            states[key] = "attempting"
        persisted = await task.directus_service.update_item(
            COLLECTION, row["id"], {"push_target_states": states, "updated_at": int(time.time())},
            admin_required=True,
        )
        if not persisted:
            raise RuntimeError("Workflow push provider result was not persisted")
    still_pending = any(
        isinstance(target.get("token"), str)
        and hashlib.sha256(target["token"].encode("utf-8")).hexdigest() not in states
        for target in targets
    )
    final = "pending" if still_pending else "accepted" if "accepted" in states.values() else "uncertain" if "attempting" in states.values() else "failed"
    await _update(task.directus_service, row, "push_state", final)
    return final


async def _dispatch_email(task: Any, row: dict[str, Any], service: Any) -> str:
    if row.get("email_state") in {"sent", "disabled", "unavailable"}:
        return str(row["email_state"])
    user = await _load_user_strict(task.directus_service, row["owner_user_id"], NOTIFICATION_USER_FIELDS)
    if not user or user.get("status") != "active" or not notification_category_enabled(user, "workflowRuns"):
        await _update(task.directus_service, row, "email_state", "disabled")
        return "disabled"
    address = await resolve_notification_email(task.directus_service, task.encryption_service, user)
    if not address:
        await _update(task.directus_service, row, "email_state", "unavailable")
        return "unavailable"
    title = await _workflow_title(service, row) if preview_enabled(user) else None
    finished_at = await _finished_at(task.directus_service, row)
    if finished_at is None:
        return "not_completed"
    context = {
        "darkmode": bool(user.get("darkmode")), "workflow_title": title,
        "run_id": row["run_id"], "completed_time": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(finished_at)),
        "url": completion_url(row),
    }

    async def before_send() -> bool:
        current = await _load_user_strict(task.directus_service, row["owner_user_id"], NOTIFICATION_USER_FIELDS)
        if not current or current.get("status") != "active" or not notification_category_enabled(current, "workflowRuns"):
            return False
        current_address = await resolve_notification_email(task.directus_service, task.encryption_service, current)
        if not current_address or current_address.casefold() != address.casefold():
            return False
        if not preview_enabled(current):
            context["workflow_title"] = None
        return await _confirmed_run(task.directus_service, row)

    sent, state = await send_email_once(
        directus=task.directus_service, email_template_service=task.email_template_service,
        email_type="workflow-completed", campaign_key="workflowRuns", recipient_kind="directus_user",
        recipient_id=row["owner_user_id"], stage=row["run_id"], template="workflow-run-completed",
        subject=task.email_template_service.translation_service.get_nested_translation(
            "email.workflow_completion.subject", user.get("language") or "en", context,
        ), recipient_email=address,
        context=context, lang=user.get("language") or "en", before_send=before_send,
        retry_cache=task.cache_service,
    )
    if sent:
        await _update(task.directus_service, row, "email_state", "sent")
        return "sent"
    if state == "already_reserved":
        # A completed guard row is already dispatched; other reservations are
        # uncertain and must not be labelled sent.
        from backend.core.api.app.services.email_delivery_guard import build_delivery_id, build_delivery_key
        delivery_id = build_delivery_id(build_delivery_key(
            email_type="workflow-completed", campaign_key="workflowRuns", recipient_kind="directus_user",
            recipient_id=row["owner_user_id"], stage=row["run_id"],
        ))
        existing = await task.directus_service.get_items(
            "email_deliveries", params={"filter": {"id": {"_eq": delivery_id}},
                                         "fields": "id,status", "limit": 1},
            admin_required=True, no_cache=True, raise_on_error=True,
        )
        if isinstance(existing, list) and len(existing) == 1 and existing[0].get("status") == "sent":
            await _update(task.directus_service, row, "email_state", "sent")
            return "sent"
    if state in {"ineligible_at_dispatch", "retry_unsafe_transport"}:
        await _update(task.directus_service, row, "email_state", "disabled" if state == "ineligible_at_dispatch" else "uncertain")
    elif state in {"retry_window_closed", "already_reserved"}:
        await _update(task.directus_service, row, "email_state", "uncertain")
    return state
