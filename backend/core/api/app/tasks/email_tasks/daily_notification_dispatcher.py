"""
Purpose: Unified daily notification dispatcher — scans all active users once per day and
         dispatches whichever notification emails are due for each user.

Architecture: Uses a handler registry pattern so new notification types (e.g. Tips & Tricks)
              can be added by implementing NotificationHandler and adding to HANDLERS.
              A single paginated sweep avoids N separate full-table Directus scans.

              Eligibility gate shared by all handlers:
                - email_notifications_enabled must be True
                - last_access within the past ACTIVITY_WINDOW_DAYS (14 days) — avoids
                  spamming dormant accounts

              Per-handler opt-out: checked via email_notification_preferences JSON column.
              The handler defines its key and default_opt_in. No DB schema change required
              when adding new notification types — just add a new key to the JSON.

Architecture reference: docs/architecture/account-backup.md
Tests: N/A (covered by integration tests via celery beat + email delivery logs)
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_PAGE_SIZE = 200
# Users inactive for longer than this are skipped — no point reminding dormant accounts.
ACTIVITY_WINDOW_DAYS = 14

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string to a UTC-aware datetime. Returns None on failure."""
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _build_settings_url(path: str) -> str:
    """Build a deep-link URL into the frontend settings panel.

    Uses the /#settings/{path} hash routing convention.
    See docs/architecture/web-app.md for deep-link handling details.
    """
    from backend.shared.python_utils.frontend_url import get_frontend_base_url
    return f"{get_frontend_base_url()}/#settings/{path}"


# ---------------------------------------------------------------------------
# Handler protocol
# ---------------------------------------------------------------------------


class NotificationHandler(ABC):
    """
    Abstract base for a single daily notification type.

    To add a new notification type:
      1. Subclass NotificationHandler
      2. Set notification_key to a new key in email_notification_preferences JSON
      3. Implement should_send() and send()
      4. Append an instance to HANDLERS below

    No DB schema migration is required because email_notification_preferences is a
    freeform JSON column — new keys are silently defaulted to `default_opt_in`.
    """

    # Unique key used in email_notification_preferences JSON (e.g. "backupReminder").
    notification_key: str

    # Whether new users are opted in by default.
    default_opt_in: bool = True

    def is_opted_in(self, user: dict[str, Any]) -> bool:
        """Check whether this user has opted into this notification type."""
        prefs = user.get("email_notification_preferences") or {}
        # JSON column may arrive as a dict (Directus) or a string — normalise.
        if isinstance(prefs, str):
            import json
            try:
                prefs = json.loads(prefs)
            except Exception:
                prefs = {}
        return bool(prefs.get(self.notification_key, self.default_opt_in))

    @abstractmethod
    def should_send(self, user: dict[str, Any], now_utc: datetime) -> bool:
        """Return True if this user should receive this notification today."""

    @abstractmethod
    async def send(
        self,
        task: BaseServiceTask,
        user: dict[str, Any],
        decrypted_email: str,
    ) -> bool:
        """Send the notification email. Return True on success."""


# ---------------------------------------------------------------------------
# BackupReminderHandler
# ---------------------------------------------------------------------------


class BackupReminderHandler(NotificationHandler):
    """
    Sends a periodic data-backup reminder email.

    Schedule:
      - First reminder: 3 days after account creation (if user has never exported)
      - Subsequent: every `backup_reminder_interval_days` days (default 30) after either
        the last successful export OR the last time the user dismissed a reminder,
        whichever is more recent.
    """

    notification_key = "backupReminder"
    default_opt_in = True

    # Days after account creation before the very first reminder.
    FIRST_REMINDER_DAYS = 3

    def should_send(self, user: dict[str, Any], now_utc: datetime) -> bool:
        created_at = _parse_iso_datetime(user.get("date_created"))
        if not created_at:
            return False

        days_since_created = (now_utc - created_at).days

        # Too new — don't send until FIRST_REMINDER_DAYS have passed.
        if days_since_created < self.FIRST_REMINDER_DAYS:
            return False

        last_export_at = _parse_iso_datetime(user.get("last_export_at"))
        dismissed_at = _parse_iso_datetime(user.get("backup_reminder_dismissed_at"))
        interval = int(user.get("backup_reminder_interval_days") or 30)

        # If user has never exported and never dismissed, fire the first reminder.
        if last_export_at is None and dismissed_at is None:
            # Only fire exactly on the first-reminder day — avoids re-firing every day thereafter.
            return days_since_created == self.FIRST_REMINDER_DAYS

        # Otherwise, use the most recent "reset" event (export or dismissal) as the baseline.
        candidates = [t for t in (last_export_at, dismissed_at) if t is not None]
        most_recent_reset = max(candidates)
        days_since_reset = (now_utc - most_recent_reset).days

        return days_since_reset >= interval

    async def send(
        self,
        task: BaseServiceTask,
        user: dict[str, Any],
        decrypted_email: str,
    ) -> bool:
        notifications_settings_url = _build_settings_url("notifications/backup")
        export_url = _build_settings_url("account/export")

        last_export_at = user.get("last_export_at")
        context = {
            "darkmode": bool(user.get("darkmode", False)),
            "export_url": export_url,
            "notifications_settings_url": notifications_settings_url,
            "last_export_at": last_export_at,  # ISO string or None; rendered in template
        }

        sent = await task.email_template_service.send_email(
            template="backup-reminder",
            recipient_email=decrypted_email,
            context=context,
            lang=user.get("language") or "en",
        )

        if sent:
            # Mark that we sent a reminder today so the interval resets.
            # We update backup_reminder_dismissed_at as a "last reminder sent" timestamp
            # to prevent duplicate sends if the task runs multiple times on the same day.
            # (A real user-initiated dismiss from the app will also write this field.)
            try:
                await task.directus_service.update_item(
                    "directus_users",
                    user["id"],
                    {"backup_reminder_dismissed_at": datetime.now(timezone.utc).isoformat()},
                    admin_required=True,
                )
            except Exception as exc:
                logger.warning(
                    "BackupReminderHandler: could not update backup_reminder_dismissed_at "
                    "for user %s: %s",
                    user.get("id", "?"),
                    exc,
                )

        return sent


# ---------------------------------------------------------------------------
# Handler registry — add new handlers here to extend the dispatcher
# ---------------------------------------------------------------------------

HANDLERS: list[NotificationHandler] = [
    BackupReminderHandler(),
    # Future: TipsAndTricksHandler(),
    # Future: WeeklyDigestHandler(),
]

# Fields fetched per user in the paginated sweep.
# Extend this list if a new handler needs additional fields.
_USER_FIELDS = (
    "id,date_created,last_access,language,darkmode,"
    "vault_key_id,encrypted_email_address,"
    "email_notifications_enabled,email_notification_preferences,"
    # Backup reminder fields
    "last_export_at,backup_reminder_dismissed_at,backup_reminder_interval_days"
)

# ---------------------------------------------------------------------------
# Celery task entrypoint
# ---------------------------------------------------------------------------


@app.task(
    name="app.tasks.email_tasks.daily_notification_dispatcher.run_daily_notifications",
    base=BaseServiceTask,
    bind=True,
)
def run_daily_notifications(self) -> dict:
    """Daily sweep: send whichever notification emails are due for each active user."""
    return asyncio.run(_async_run_daily_notifications(self))


async def _async_run_daily_notifications(task: BaseServiceTask) -> dict:
    stats: dict[str, Any] = {
        "checked_users": 0,
        "skipped_inactive": 0,
        "skipped_email_disabled": 0,
        "skipped_missing_email": 0,
        # Per-handler sent counts are added dynamically, e.g. "sent_backupReminder"
    }
    for handler in HANDLERS:
        stats[f"sent_{handler.notification_key}"] = 0

    now_utc = datetime.now(timezone.utc)

    try:
        await task.initialize_services()

        page = 1
        while True:
            users = await task.directus_service.get_items(
                "directus_users",
                params={
                    "fields": _USER_FIELDS,
                    "filter": {"status": {"_eq": "active"}},
                    "sort": "date_created",
                    "page": page,
                    "limit": USER_PAGE_SIZE,
                },
                admin_required=True,
            )

            if not users:
                break

            for user in users:
                stats["checked_users"] += 1
                user_id = user.get("id")
                if not user_id:
                    continue

                # --- Shared eligibility: email notifications must be enabled ---
                if not user.get("email_notifications_enabled", False):
                    stats["skipped_email_disabled"] += 1
                    continue

                # --- Shared eligibility: user must have been active recently ---
                last_access = _parse_iso_datetime(user.get("last_access"))
                if last_access is None or (now_utc - last_access).days > ACTIVITY_WINDOW_DAYS:
                    stats["skipped_inactive"] += 1
                    continue

                # --- Decrypt email once (shared across all handlers for this user) ---
                encrypted_email = user.get("encrypted_email_address")
                vault_key_id = user.get("vault_key_id")
                if not encrypted_email or not vault_key_id:
                    stats["skipped_missing_email"] += 1
                    continue

                decrypted_email = await task.encryption_service.decrypt_with_user_key(
                    encrypted_email, vault_key_id
                )
                if not decrypted_email:
                    stats["skipped_missing_email"] += 1
                    continue

                # --- Run each handler ---
                for handler in HANDLERS:
                    if not handler.is_opted_in(user):
                        continue
                    if not handler.should_send(user, now_utc):
                        continue

                    try:
                        sent = await handler.send(task, user, decrypted_email)
                        if sent:
                            stats[f"sent_{handler.notification_key}"] += 1
                            logger.info(
                                "daily_notification_dispatcher: sent %s to user %s",
                                handler.notification_key,
                                user_id[:8],
                            )
                    except Exception as exc:
                        logger.error(
                            "daily_notification_dispatcher: handler %s failed for user %s: %s",
                            handler.notification_key,
                            user_id[:8],
                            exc,
                            exc_info=True,
                        )

            if len(users) < USER_PAGE_SIZE:
                break
            page += 1

        logger.info("daily_notification_dispatcher completed: %s", stats)
        return stats

    except Exception as exc:
        logger.error("daily_notification_dispatcher failed: %s", exc, exc_info=True)
        return stats
    finally:
        await task.cleanup_services()
