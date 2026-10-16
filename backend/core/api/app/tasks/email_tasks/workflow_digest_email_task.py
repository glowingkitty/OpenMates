"""Send one private daily email for accepted scheduled Workflow runs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.api.app.services.email_delivery_guard import RETRY_WINDOW_SECONDS, send_email_once
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.email_tasks.ai_response_notification_email_task import initialize_notification_email_services
from backend.core.api.app.services.notification_email_preferences import (
    load_notification_user,
    notification_category_enabled,
    preview_enabled,
    resolve_notification_email,
)
from backend.core.api.app.services.workflow_digest_service import (
    collect_workflow_digest,
    load_workflow_message_previews,
    load_workflow_title_previews,
)
from backend.shared.python_utils.frontend_url import get_frontend_base_url


logger = logging.getLogger(__name__)
RETRY_DELAYS_SECONDS = (30, 90, 180)


def _utc_time(value: int | None) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if value is not None else None


async def send_user_workflow_digest(
    task: Any, user_id: str, cutoff_utc: datetime, *, require_current_cutoff: bool = False,
) -> str:
    """Return sent, empty, disabled, unavailable, failed, or already_reserved.

    The run query is metadata-only. Consent and the verified address are read
    afresh immediately before the external email send, after aggregation.
    """
    cutoff_epoch = int(cutoff_utc.timestamp())
    if require_current_cutoff and not _is_current_digest_cutoff(cutoff_epoch):
        return "expired_digest"
    digest = await collect_workflow_digest(task.directus_service, user_id, cutoff_utc)
    if digest is None:
        return "empty"

    user = await load_notification_user(task.directus_service, user_id)
    if not user or user.get("status") != "active" or not notification_category_enabled(user, "workflowRuns"):
        return "disabled"
    rows = [dict(row) for row in digest["rows"]]
    if preview_enabled(user):
        try:
            titles = await load_workflow_title_previews(
                task.directus_service, task.encryption_service, user_id=user_id,
                vault_key_id=user.get("vault_key_id"), rows=rows,
            )
            for row in rows:
                if row["workflow_id"] in titles:
                    row["title"] = titles[row["workflow_id"]]
        except Exception:
            logger.warning("Workflow digest title preview unavailable for user %s", user_id[:8])
        try:
            messages = await load_workflow_message_previews(
                task.directus_service, task.encryption_service, user_id=user_id,
                vault_key_id=user.get("vault_key_id"), rows=rows,
            )
            for row in rows:
                if row["run_id"] in messages:
                    row["output_preview"] = messages[row["run_id"]]
        except Exception:
            # A preview failure cannot force content into a private email.
            logger.warning("Workflow digest message preview unavailable for user %s", user_id[:8])

    # A Vault lookup or a queued task can outlive a settings change. Confirm
    # consent again at the final send boundary, and drop an optional preview if
    # content permission was withdrawn while it was being prepared.
    latest_user = await load_notification_user(task.directus_service, user_id)
    if not latest_user or latest_user.get("status") != "active" or not notification_category_enabled(latest_user, "workflowRuns"):
        return "disabled"
    if not preview_enabled(latest_user):
        for row in rows:
            row.pop("title", None)
            row.pop("output_preview", None)
    email = await resolve_notification_email(task.directus_service, task.encryption_service, latest_user)
    if not email:
        return "unavailable"

    for row in rows:
        row["accepted_time"] = _utc_time(row["accepted_at"])
        row["started_time"] = _utc_time(row["started_at"])
        row["finished_time"] = _utc_time(row["finished_at"])
    context = {
        "darkmode": bool(latest_user.get("darkmode", False)),
        "window_start": _utc_time(digest["window_start"]),
        "window_end": _utc_time(digest["window_end"]),
        "run_count": digest["run_count"],
        "status_counts": digest["status_counts"],
        "delivery_pending_count": digest["delivery_pending_count"],
        "delivery_acknowledged_count": digest["delivery_acknowledged_count"],
        "delivery_cancelled_count": digest["delivery_cancelled_count"],
        "delivery_expired_count": digest["delivery_expired_count"],
        "delivery_failed_count": digest["delivery_failed_count"],
        "rows": rows,
        "omitted_count": digest["omitted_count"],
        "settings_url": f"{get_frontend_base_url()}/#settings/notifications/chat",
    }

    async def before_send() -> bool:
        # This callback runs after the idempotency reservation, directly before
        # EmailTemplateService crosses the external transport boundary.
        if require_current_cutoff and not _is_current_digest_cutoff(cutoff_epoch):
            return False
        current = await load_notification_user(task.directus_service, user_id)
        if not current or current.get("status") != "active" or not notification_category_enabled(current, "workflowRuns"):
            return False
        current_email = await resolve_notification_email(task.directus_service, task.encryption_service, current)
        if not current_email or current_email.casefold() != email.casefold():
            return False
        if not preview_enabled(current):
            for row in context["rows"]:
                row.pop("title", None)
                row.pop("output_preview", None)
        # The consent and verified-address reads can themselves cross 09:00 UTC.
        return not require_current_cutoff or _is_current_digest_cutoff(cutoff_epoch)

    sent, status = await send_email_once(
        directus=task.directus_service,
        email_template_service=task.email_template_service,
        email_type="daily_notification",
        campaign_key="workflowRuns",
        recipient_kind="directus_user",
        recipient_id=user_id,
        stage=cutoff_utc.astimezone(timezone.utc).date().isoformat(),
        template="workflow-run-digest",
        subject=task.email_template_service.translation_service.get_nested_translation(
            "email.workflow_digest.subject", latest_user.get("language") or "en", context,
        ),
        recipient_email=email,
        context=context,
        lang=latest_user.get("language") or "en",
        before_send=before_send,
        retry_cache=getattr(task, "cache_service", None),
    )
    return "sent" if sent else status


def _is_current_digest_cutoff(cutoff_epoch: int) -> bool:
    now = datetime.now(timezone.utc)
    latest = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now < latest:
        latest -= timedelta(days=1)
    return cutoff_epoch == int(latest.timestamp())


def queue_workflow_digest_retry(user_id: str, cutoff_epoch: int, attempt: int) -> bool:
    """Queue a content-free retry retaining the original daily cutoff."""
    if not isinstance(user_id, str) or not user_id or not isinstance(cutoff_epoch, int):
        return False
    if not 1 <= attempt <= len(RETRY_DELAYS_SECONDS) or not _is_current_digest_cutoff(cutoff_epoch):
        return False
    retry_workflow_digest.apply_async(
        args=[user_id, cutoff_epoch, attempt],
        countdown=RETRY_DELAYS_SECONDS[attempt - 1],
        expires=RETRY_WINDOW_SECONDS,
    )
    return True


@app.task(
    name="app.tasks.email_tasks.workflow_digest_email_task.retry_workflow_digest",
    base=BaseServiceTask,
    bind=True,
)
def retry_workflow_digest(self: BaseServiceTask, user_id: str, cutoff_epoch: int, attempt: int) -> str:
    """Retry a failed digest without putting an address or message content in Celery."""
    return asyncio.run(_async_retry_workflow_digest(self, user_id, cutoff_epoch, attempt))


async def _async_retry_workflow_digest(task: BaseServiceTask, user_id: str, cutoff_epoch: int, attempt: int) -> str:
    if not isinstance(user_id, str) or not user_id or not isinstance(cutoff_epoch, int) or not 1 <= attempt <= len(RETRY_DELAYS_SECONDS):
        return "invalid_retry"
    cutoff = datetime.fromtimestamp(cutoff_epoch, timezone.utc)
    # A broker backlog must not deliver yesterday's retry alongside the next
    # daily window. This also covers failures before a delivery row existed.
    if not _is_current_digest_cutoff(cutoff_epoch):
        return "expired_retry"
    try:
        await initialize_notification_email_services(task)
        if not _is_current_digest_cutoff(cutoff_epoch):
            return "expired_retry"
        result = await send_user_workflow_digest(task, user_id, cutoff, require_current_cutoff=True)
    except Exception:
        logger.exception("Workflow digest retry %s failed for user %s", attempt, user_id[:8])
        result = "failed"
    finally:
        try:
            await task.cleanup_services()
        except Exception:
            logger.exception("Workflow digest retry cleanup failed for user %s", user_id[:8])
    if result in {"failed", "retry_locked", "retry_unavailable"}:
        queue_workflow_digest_retry(user_id, cutoff_epoch, attempt + 1)
    return result
