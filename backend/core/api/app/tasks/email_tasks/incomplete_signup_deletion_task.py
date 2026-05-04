"""
Purpose: Sends staged deletion reminders for incomplete signups and deletes stale accounts after notice.
Architecture: Daily Celery Beat task; Directus email_deliveries rows provide durable idempotency.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.api.app.services.email_delivery_guard import send_email_once
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils.frontend_url import get_frontend_base_url

logger = logging.getLogger(__name__)

CAMPAIGN_KEY = "incomplete_signup_deletion_v1"
EMAIL_TYPE = "incomplete_signup_deletion"
USER_PAGE_SIZE = 200
INITIAL_NOTICE_AFTER_DAYS = 14
SECOND_NOTICE_AFTER_DAYS = 7
FINAL_NOTICE_AFTER_DAYS = 13
DELETE_AFTER_FINAL_NOTICE_DAYS = 1
ANNOUNCEMENT_CHAT_ID = "announcements-introducing-openmates-v09"
ANNOUNCEMENT_THUMBNAIL_PATH = "/newsletter-assets/intro-thumbnail-EN.jpg"
SEND_DELAY_SECONDS = float(os.getenv("INCOMPLETE_SIGNUP_EMAIL_SEND_DELAY_SECONDS", "0.25"))


@app.task(
    name="app.tasks.email_tasks.incomplete_signup_deletion_task.process_incomplete_signup_deletions",
    base=BaseServiceTask,
    bind=True,
)
def process_incomplete_signup_deletions(
    self: BaseServiceTask,
    dry_run: bool = False,
    max_users: int | None = None,
    max_actions: int | None = None,
    days_ahead: int = 0,
) -> dict:
    """Daily sweep for incomplete signup deletion reminders and due deletions."""
    return asyncio.run(
        _async_process_incomplete_signup_deletions(
            self,
            dry_run=dry_run,
            max_users=max_users,
            max_actions=max_actions,
            days_ahead=days_ahead,
        )
    )


async def process_incomplete_signup_deletions_preview(
    task: BaseServiceTask,
    *,
    max_users: int | None = None,
    max_actions: int | None = None,
    days_ahead: int = 0,
) -> dict:
    """Preview helper for scripts/tests: evaluate due work without sending or deleting."""
    return await _async_process_incomplete_signup_deletions(
        task,
        dry_run=True,
        max_users=max_users,
        max_actions=max_actions,
        days_ahead=days_ahead,
    )


def _actions_count(stats: dict[str, Any]) -> int:
    return int(stats["sent_14d"] + stats["sent_7d"] + stats["sent_1d"] + stats["deleted"])


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _delivery_time(row: dict[str, Any] | None) -> datetime | None:
    if not row:
        return None
    return (
        _parse_datetime(row.get("sent_at"))
        or _parse_datetime(row.get("processing_started_at"))
        or _parse_datetime(row.get("archived_at"))
    )


def _signup_started_at(user: dict[str, Any]) -> datetime | None:
    return (
        _parse_datetime(user.get("signup_started_at"))
        or _parse_datetime(user.get("last_online_timestamp"))
        or _parse_datetime(user.get("last_access"))
    )


async def _get_stage_deliveries(task: BaseServiceTask, user_id: str) -> dict[str, dict[str, Any]]:
    rows = await task.directus_service.get_items(
        "email_deliveries",
        params={
            "fields": "id,stage,status,sent_at,processing_started_at,archived_at",
            "filter": {
                "email_type": {"_eq": EMAIL_TYPE},
                "campaign_key": {"_eq": CAMPAIGN_KEY},
                "recipient_kind": {"_eq": "directus_user"},
                "recipient_id": {"_eq": user_id},
                "status": {"_in": ["processing", "sent", "archived"]},
            },
            "limit": -1,
        },
        admin_required=True,
    )
    return {row.get("stage"): row for row in rows if row.get("stage")}


async def _has_usage_or_invoice(task: BaseServiceTask, user_id: str) -> bool:
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

    usage = await task.directus_service.get_items(
        "usage",
        params={"filter": {"user_id_hash": {"_eq": user_id_hash}}, "fields": "id", "limit": 1},
        admin_required=True,
    )
    if usage:
        return True

    invoices = await task.directus_service.get_items(
        "invoices",
        params={
            "filter": {"user_id_hash": {"_eq": user_id_hash}},
            "fields": "id",
            "limit": 1,
        },
        admin_required=True,
    )
    return bool(invoices)


async def _mark_signup_completed(task: BaseServiceTask, user_id: str, reason: str) -> None:
    updated = await task.directus_service.update_item(
        "directus_users",
        user_id,
        {"signup_completed": True},
        admin_required=True,
    )
    if updated:
        logger.info("Marked incomplete signup user %s complete (%s)", user_id[:8], reason)


async def _decrypt_email_and_username(task: BaseServiceTask, user: dict[str, Any]) -> tuple[str | None, str]:
    contact_rows = await task.directus_service.get_items(
        "account_contact_emails",
        params={
            "fields": "encrypted_email_address",
            "filter": {
                "user_id": {"_eq": user.get("id")},
                "purpose": {"_eq": "account_lifecycle"},
            },
            "limit": 1,
        },
        admin_required=True,
    )
    if contact_rows:
        contact_email = await task.encryption_service.decrypt_account_contact_email(
            contact_rows[0].get("encrypted_email_address")
        )
        if contact_email:
            username = "there"
            encrypted_username = user.get("encrypted_username")
            vault_key_id = user.get("vault_key_id")
            if encrypted_username and vault_key_id:
                try:
                    decrypted_username = await task.encryption_service.decrypt_with_user_key(encrypted_username, vault_key_id)
                    if decrypted_username:
                        username = decrypted_username
                except Exception:
                    logger.debug("Could not decrypt username for incomplete signup user %s", user.get("id", "?")[:8])
            return contact_email, username

    vault_key_id = user.get("vault_key_id")
    encrypted_email = user.get("encrypted_email_address")
    if not vault_key_id or not encrypted_email:
        return None, "there"

    email = await task.encryption_service.decrypt_with_user_key(encrypted_email, vault_key_id)
    username = "there"
    encrypted_username = user.get("encrypted_username")
    if encrypted_username:
        try:
            decrypted_username = await task.encryption_service.decrypt_with_user_key(encrypted_username, vault_key_id)
            if decrypted_username:
                username = decrypted_username
        except Exception:
            logger.debug("Could not decrypt username for incomplete signup user %s", user.get("id", "?")[:8])
    return email, username


def _reminder_context(stage: str, username: str, account_id: str) -> tuple[str, dict[str, Any]]:
    base_url = get_frontend_base_url()
    finish_setup_link = base_url
    latest_announcement_video_link = f"{base_url}/#chat-id={ANNOUNCEMENT_CHAT_ID}&autoplay-video"
    announcement_thumbnail_url = f"{base_url}{ANNOUNCEMENT_THUMBNAIL_PATH}"
    direct_delete_account_link = f"{base_url}/#settings/account/delete/{account_id}"

    if stage == "14d":
        subject = "Complete your OpenMates signup before your account is deleted"
        context = {
            "subject": subject,
            "headline": "Complete your signup before deletion",
            "deletion_time_text": "in 14 days",
            "wait_time_text": "14 days",
            "reminder_info": "If you take no action, you will be reminded again 7 days before deletion and 1 day before deletion.",
        }
    elif stage == "7d":
        subject = "Your incomplete OpenMates account will be deleted in 7 days"
        context = {
            "subject": subject,
            "headline": "Your account will be deleted soon",
            "deletion_time_text": "in 7 days",
            "wait_time_text": "7 days",
            "reminder_info": "If you take no action, you will receive one final reminder 1 day before deletion.",
        }
    else:
        subject = "Final notice: your incomplete OpenMates account will be deleted tomorrow"
        context = {
            "subject": subject,
            "headline": "Final notice",
            "deletion_time_text": "tomorrow",
            "wait_time_text": "until tomorrow",
            "reminder_info": "",
        }

    context.update({
        "username": username,
        "finish_setup_link": finish_setup_link,
        "latest_announcement_video_link": latest_announcement_video_link,
        "announcement_thumbnail_url": announcement_thumbnail_url,
        "direct_delete_account_link": direct_delete_account_link,
    })
    return subject, context


async def _send_reminder(task: BaseServiceTask, user: dict[str, Any], stage: str, email: str, username: str) -> bool:
    account_id = user.get("account_id")
    if not account_id:
        logger.warning("Incomplete signup user %s missing account_id; cannot send delete link", user.get("id", "?")[:8])
        return False

    subject, context = _reminder_context(stage, username, account_id)
    context["darkmode"] = bool(user.get("darkmode", False))
    sent, status = await send_email_once(
        directus=task.directus_service,
        email_template_service=task.email_template_service,
        email_type=EMAIL_TYPE,
        campaign_key=CAMPAIGN_KEY,
        recipient_kind="directus_user",
        recipient_id=user["id"],
        stage=stage,
        template="incomplete-signup-deletion-reminder",
        recipient_email=email,
        recipient_name=username,
        context=context,
        subject=subject,
        lang=user.get("language") or "en",
    )
    if status == "already_reserved":
        logger.info("Incomplete signup %s reminder already reserved for user %s", stage, user["id"][:8])
        return False
    if sent:
        await asyncio.sleep(SEND_DELAY_SECONDS)
    return sent


async def _delete_and_send_confirmation(task: BaseServiceTask, user: dict[str, Any], email: str, username: str) -> bool:
    from backend.core.api.app.tasks.user_cache_tasks import _async_delete_user_account

    user_id = user["id"]
    deleted = await _async_delete_user_account(
        user_id=user_id,
        deletion_type="incomplete_signup_timeout",
        reason="Incomplete signup not completed after staged deletion reminders",
        ip_address=None,
        device_fingerprint=None,
        refund_invoices=False,
        task_id=f"incomplete-signup-deletion-{user_id}",
        email_encryption_key=None,
    )
    if not deleted:
        logger.error("Incomplete signup deletion failed for user %s", user_id[:8])
        return False

    base_url = get_frontend_base_url()
    subject = "Your incomplete OpenMates account has been deleted"
    sent, status = await send_email_once(
        directus=task.directus_service,
        email_template_service=task.email_template_service,
        email_type=EMAIL_TYPE,
        campaign_key=CAMPAIGN_KEY,
        recipient_kind="directus_user",
        recipient_id=user_id,
        stage="deleted",
        template="incomplete-signup-account-deleted",
        recipient_email=email,
        recipient_name=username,
        context={
            "darkmode": bool(user.get("darkmode", False)),
            "subject": subject,
            "username": username,
            "signup_link": base_url,
        },
        subject=subject,
        lang=user.get("language") or "en",
    )
    if status == "already_reserved":
        return True
    if sent:
        await asyncio.sleep(SEND_DELAY_SECONDS)
    return sent


async def _async_process_incomplete_signup_deletions(
    task: BaseServiceTask,
    *,
    dry_run: bool = False,
    max_users: int | None = None,
    max_actions: int | None = None,
    days_ahead: int = 0,
) -> dict:
    stats = {
        "checked": 0,
        "skipped_not_due": 0,
        "skipped_safety_completed": 0,
        "skipped_missing_email": 0,
        "sent_14d": 0,
        "sent_7d": 0,
        "sent_1d": 0,
        "deleted": 0,
        "delete_failed": 0,
        "dry_run": dry_run,
        "days_ahead": days_ahead,
        "max_actions": max_actions,
        "stopped_by_limit": None,
    }
    now = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    cutoff = now - timedelta(days=INITIAL_NOTICE_AFTER_DAYS)

    try:
        await task.initialize_services()
        page = 1
        while True:
            users = await task.directus_service.get_items(
                "directus_users",
                params={
                    "fields": "id,status,is_admin,last_opened,signup_completed,signup_started_at,last_online_timestamp,last_access,account_id,language,darkmode,vault_key_id,encrypted_email_address,encrypted_username",
                    "filter": {
                        "_and": [
                            {"status": {"_eq": "active"}},
                            {"signup_completed": {"_eq": False}},
                        ]
                    },
                    "sort": "id",
                    "page": page,
                    "limit": USER_PAGE_SIZE,
                },
                admin_required=True,
            )
            if not users:
                break

            for user in users:
                if max_users is not None and stats["checked"] >= max_users:
                    logger.info("Incomplete signup deletion run hit max_users=%s", max_users)
                    stats["stopped_by_limit"] = "max_users"
                    return stats

                stats["checked"] += 1
                user_id = user.get("id")
                if not user_id or user.get("is_admin"):
                    continue

                started_at = _signup_started_at(user)
                if not started_at or started_at > cutoff:
                    stats["skipped_not_due"] += 1
                    continue

                last_opened = user.get("last_opened") or ""
                if not last_opened.startswith("/signup/"):
                    if not dry_run:
                        await _mark_signup_completed(task, user_id, "last_opened_not_signup")
                    stats["skipped_safety_completed"] += 1
                    continue

                if await _has_usage_or_invoice(task, user_id):
                    if not dry_run:
                        await _mark_signup_completed(task, user_id, "usage_or_invoice")
                    stats["skipped_safety_completed"] += 1
                    continue

                email, username = await _decrypt_email_and_username(task, user)
                if not email:
                    stats["skipped_missing_email"] += 1
                    continue

                deliveries = await _get_stage_deliveries(task, user_id)
                first_notice_at = _delivery_time(deliveries.get("14d"))
                final_notice_at = _delivery_time(deliveries.get("1d"))

                if not first_notice_at:
                    if dry_run:
                        stats["sent_14d"] += 1
                        if max_actions is not None and _actions_count(stats) >= max_actions:
                            stats["stopped_by_limit"] = "max_actions"
                            return stats
                        continue
                    if await _send_reminder(task, user, "14d", email, username):
                        stats["sent_14d"] += 1
                        if max_actions is not None and _actions_count(stats) >= max_actions:
                            stats["stopped_by_limit"] = "max_actions"
                            return stats
                    continue

                if "7d" not in deliveries and now >= first_notice_at + timedelta(days=SECOND_NOTICE_AFTER_DAYS):
                    if dry_run:
                        stats["sent_7d"] += 1
                        if max_actions is not None and _actions_count(stats) >= max_actions:
                            stats["stopped_by_limit"] = "max_actions"
                            return stats
                        continue
                    if await _send_reminder(task, user, "7d", email, username):
                        stats["sent_7d"] += 1
                        if max_actions is not None and _actions_count(stats) >= max_actions:
                            stats["stopped_by_limit"] = "max_actions"
                            return stats
                    continue

                if not final_notice_at and now >= first_notice_at + timedelta(days=FINAL_NOTICE_AFTER_DAYS):
                    if dry_run:
                        stats["sent_1d"] += 1
                        if max_actions is not None and _actions_count(stats) >= max_actions:
                            stats["stopped_by_limit"] = "max_actions"
                            return stats
                        continue
                    if await _send_reminder(task, user, "1d", email, username):
                        stats["sent_1d"] += 1
                        if max_actions is not None and _actions_count(stats) >= max_actions:
                            stats["stopped_by_limit"] = "max_actions"
                            return stats
                    continue

                if final_notice_at and now >= final_notice_at + timedelta(days=DELETE_AFTER_FINAL_NOTICE_DAYS):
                    if dry_run:
                        stats["deleted"] += 1
                        if max_actions is not None and _actions_count(stats) >= max_actions:
                            stats["stopped_by_limit"] = "max_actions"
                            return stats
                        continue
                    if await _delete_and_send_confirmation(task, user, email, username):
                        stats["deleted"] += 1
                        if max_actions is not None and _actions_count(stats) >= max_actions:
                            stats["stopped_by_limit"] = "max_actions"
                            return stats
                    else:
                        stats["delete_failed"] += 1
                    continue

                stats["skipped_not_due"] += 1

            if len(users) < USER_PAGE_SIZE:
                break
            page += 1

        logger.info("Incomplete signup deletion run completed: %s", stats)
        return stats
    except Exception as exc:
        logger.error("Incomplete signup deletion run failed: %s", exc, exc_info=True)
        stats["error"] = str(exc)
        return stats
    finally:
        await task.cleanup_services()
