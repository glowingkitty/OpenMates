"""
Purpose: Sends periodic security reminder emails for accounts that still use password login without OTP 2FA.
Architecture: Runs as a Celery beat-triggered email task and evaluates account security state in Directus.
Architecture: See docs/architecture/app-skills.md for async task execution rationale.
Tests: N/A (covered manually via Playwright signup/login flow and task logs)
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

FIRST_REMINDER_DAY = 1
SECOND_REMINDER_DAY = 4
THIRD_REMINDER_DAY = 11
REPEATING_START_DAY = 21
REPEATING_INTERVAL_DAYS = 10
USER_PAGE_SIZE = 200


@app.task(
    name="app.tasks.email_tasks.password_security_reminder_email_task.process_password_security_reminders",
    base=BaseServiceTask,
    bind=True,
)
def process_password_security_reminders(self) -> dict:
    """Run periodic checks and send security reminders for insecure password setups."""
    return asyncio.run(_async_process_password_security_reminders(self))


def _should_send_for_account_age(days_since_signup: int) -> bool:
    if days_since_signup in {FIRST_REMINDER_DAY, SECOND_REMINDER_DAY, THIRD_REMINDER_DAY}:
        return True
    if days_since_signup >= REPEATING_START_DAY:
        return (days_since_signup - REPEATING_START_DAY) % REPEATING_INTERVAL_DAYS == 0
    return False


def _parse_iso_datetime(value: str | None) -> datetime | None:
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
    base_url = os.getenv("FRONTEND_URL", "https://openmates.org").rstrip("/")
    return f"{base_url}/#settings/{path}"


async def _async_process_password_security_reminders(task: BaseServiceTask) -> dict:
    stats = {
        "checked_users": 0,
        "eligible_users": 0,
        "sent": 0,
        "skipped_missing_email": 0,
        "skipped_not_due": 0,
    }

    now_utc = datetime.now(timezone.utc)

    try:
        await task.initialize_services()

        page = 1
        while True:
            users = await task.directus_service.get_items(
                "directus_users",
                params={
                    "fields": "id,date_created,language,darkmode,vault_key_id,encrypted_email_address,encrypted_tfa_secret",
                    "filter": {
                        "status": {"_eq": "active"},
                    },
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

                # Stop if OTP is already configured.
                if user.get("encrypted_tfa_secret"):
                    continue

                created_at = _parse_iso_datetime(user.get("date_created"))
                if not created_at:
                    continue

                days_since_signup = (now_utc - created_at).days
                if days_since_signup < FIRST_REMINDER_DAY or not _should_send_for_account_age(days_since_signup):
                    stats["skipped_not_due"] += 1
                    continue

                hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                password_key = await task.directus_service.get_encryption_key(hashed_user_id, "password")
                if not password_key:
                    # No password login method anymore (for example passkey-only) -> stop reminders.
                    continue

                stats["eligible_users"] += 1

                encrypted_email_address = user.get("encrypted_email_address")
                vault_key_id = user.get("vault_key_id")
                if not encrypted_email_address or not vault_key_id:
                    stats["skipped_missing_email"] += 1
                    continue

                decrypted_email = await task.encryption_service.decrypt_with_user_key(
                    encrypted_email_address,
                    vault_key_id,
                )
                if not decrypted_email:
                    stats["skipped_missing_email"] += 1
                    continue

                context = {
                    "darkmode": bool(user.get("darkmode", False)),
                    "twofa_settings_url": _build_settings_url("account/security/2fa"),
                    "passkeys_settings_url": _build_settings_url("account/security/passkeys"),
                }

                sent = await task.email_template_service.send_email(
                    template="password-security-reminder",
                    recipient_email=decrypted_email,
                    context=context,
                    lang=user.get("language") or "en",
                )

                if sent:
                    stats["sent"] += 1

            if len(users) < USER_PAGE_SIZE:
                break
            page += 1

        logger.info("Password security reminder run completed: %s", stats)
        return stats
    except Exception as exc:
        logger.error("Password security reminder run failed: %s", exc, exc_info=True)
        return stats
    finally:
        await task.cleanup_services()
