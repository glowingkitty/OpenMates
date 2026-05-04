#!/usr/bin/env python3
"""
Send test emails for incomplete-signup account deletion reminders.

This script sends the four transactional email variants through the existing
EmailTemplateService/Brevo path without querying or modifying user accounts.
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.email_delivery_guard import send_email_once
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.frontend_url import get_frontend_base_url

logger = logging.getLogger(__name__)

ANNOUNCEMENT_PATH = "/announcements/introducing-openmates-v09"


@dataclass(frozen=True)
class EmailVariant:
    label: str
    template: str
    subject: str
    context: dict


def _build_reminder_variant(days_remaining: int, base_url: str, username: str, account_id: str) -> EmailVariant:
    reminder_info = ""
    subject = "Complete your OpenMates signup before your account is deleted"
    headline = "Complete your signup before deletion"
    deletion_time_text = f"in {days_remaining} days"
    wait_time_text = f"{days_remaining} days"

    if days_remaining == 14:
        reminder_info = "If you take no action, you will be reminded again 7 days before deletion and 1 day before deletion."
    elif days_remaining == 7:
        reminder_info = "If you take no action, you will receive one final reminder 1 day before deletion."
    elif days_remaining == 1:
        subject = "Final notice: your incomplete OpenMates account will be deleted tomorrow"
        headline = "Final notice"
        deletion_time_text = "tomorrow"
        wait_time_text = "until tomorrow"

    return EmailVariant(
        label=f"{days_remaining}-day reminder",
        template="incomplete-signup-deletion-reminder",
        subject=subject,
        context={
            "darkmode": False,
            "subject": subject,
            "headline": headline,
            "username": username,
            "finish_setup_link": base_url,
            "latest_announcement_link": f"{base_url}{ANNOUNCEMENT_PATH}",
            "direct_delete_account_link": f"{base_url}/#settings/account/delete/{account_id}",
            "deletion_time_text": deletion_time_text,
            "wait_time_text": wait_time_text,
            "reminder_info": reminder_info,
        },
    )


def _build_deleted_variant(base_url: str, username: str) -> EmailVariant:
    subject = "Your incomplete OpenMates account has been deleted"
    return EmailVariant(
        label="account deleted confirmation",
        template="incomplete-signup-account-deleted",
        subject=subject,
        context={
            "darkmode": False,
            "subject": subject,
            "username": username,
            "signup_link": base_url,
        },
    )


async def _send_tests(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    base_url = (args.base_url or get_frontend_base_url()).rstrip("/")
    variants = [
        _build_reminder_variant(14, base_url, args.username, args.account_id),
        _build_reminder_variant(7, base_url, args.username, args.account_id),
        _build_reminder_variant(1, base_url, args.username, args.account_id),
        _build_deleted_variant(base_url, args.username),
    ]

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    directus = DirectusService()
    try:
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        campaign_key = args.campaign_key or f"incomplete_signup_deletion_test_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        sent = 0
        skipped = 0
        for variant in variants:
            logger.info("Sending %s to %s", variant.label, args.to)
            ok, status = await send_email_once(
                directus=directus,
                email_template_service=email_template_service,
                email_type="incomplete_signup_deletion",
                campaign_key=campaign_key,
                recipient_kind="test_email_address",
                recipient_id=args.to.lower().strip(),
                stage=variant.label.replace(" ", "_"),
                template=variant.template,
                recipient_email=args.to,
                recipient_name=args.username,
                context=variant.context,
                subject=f"[TEST] {variant.subject}",
                lang="en",
            )
            if not ok:
                if status == "already_reserved":
                    skipped += 1
                    logger.info("Skipped already-reserved %s", variant.label)
                    continue
                logger.error("Failed to send %s (status=%s)", variant.label, status)
                return 1
            sent += 1

        logger.info("Sent %d test emails to %s; skipped %d", sent, args.to, skipped)
        return 0
    finally:
        await directus.close()
        await secrets_manager.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Send incomplete-signup deletion reminder test emails via Brevo.")
    parser.add_argument("--to", default="testing@openmates.org", help="Recipient email address")
    parser.add_argument("--username", default="there", help="Recipient display name in the email body")
    parser.add_argument("--account-id", default="test-account-id", help="Account ID used in the delete-account deep link")
    parser.add_argument("--base-url", default=None, help="Override frontend base URL")
    parser.add_argument("--campaign-key", default=None, help="Optional deterministic campaign key for idempotency testing")
    return asyncio.run(_send_tests(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
