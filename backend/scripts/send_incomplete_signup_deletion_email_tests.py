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
from backend.core.api.app.services.translations import TranslationService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.frontend_url import get_frontend_base_url

logger = logging.getLogger(__name__)

ANNOUNCEMENT_CHAT_ID = "announcements-introducing-openmates-v09"
ANNOUNCEMENT_THUMBNAIL_PATH_TEMPLATE = "/newsletter-assets/intro-thumbnail-{lang}.jpg"
SUPPORTED_TEMPLATE_LANGS = {"en", "de"}
TRANSLATION_SERVICE = TranslationService()


@dataclass(frozen=True)
class EmailVariant:
    label: str
    template: str
    subject: str
    context: dict


def _email_text(key: str, lang: str, context: dict | None = None) -> str:
    return TRANSLATION_SERVICE.get_nested_translation(key, lang, context)


def _greeting_name(username: str | None) -> str:
    username = (username or "").strip()
    return f" {username}" if username else ""


def _announcement_url(base_url: str, lang: str) -> str:
    lang_query = "?lang=de" if lang == "de" else ""
    return f"{base_url}/{lang_query}#chat-id={ANNOUNCEMENT_CHAT_ID}&autoplay-video"


def _announcement_thumbnail_url(base_url: str, lang: str) -> str:
    thumbnail_lang = "DE" if lang == "de" else "EN"
    return f"{base_url}{ANNOUNCEMENT_THUMBNAIL_PATH_TEMPLATE.format(lang=thumbnail_lang)}"


def _build_reminder_variant(days_remaining: int, base_url: str, username: str, account_id: str, lang: str) -> EmailVariant:
    key_suffix = f"{days_remaining}d"
    key_prefix = "email.incomplete_signup_deletion_reminder"
    context = {
        "deletion_time_text": _email_text(f"{key_prefix}.deletion_time_{key_suffix}", lang),
        "wait_time_text": _email_text(f"{key_prefix}.wait_time_{key_suffix}", lang),
    }
    subject = _email_text(f"{key_prefix}.subject_{key_suffix}", lang, context)
    context.update({
        "subject": subject,
        "headline": _email_text(f"{key_prefix}.headline_{key_suffix}", lang, context),
        "reminder_info": "" if days_remaining == 1 else _email_text(f"{key_prefix}.reminder_info_{key_suffix}", lang, context),
        "greeting_name": _greeting_name(username),
    })

    return EmailVariant(
        label=f"{lang} {days_remaining}-day reminder",
        template="incomplete-signup-deletion-reminder",
        subject=subject,
        context={
            "darkmode": False,
            "username": username,
            "finish_setup_link": base_url,
            "latest_announcement_video_link": _announcement_url(base_url, lang),
            "announcement_thumbnail_url": _announcement_thumbnail_url(base_url, lang),
            "direct_delete_account_link": f"{base_url}/#settings/account/delete/{account_id}",
            "newsletter_settings_link": f"{base_url}/#settings/newsletter",
            **context,
        },
    )


def _build_deleted_variant(base_url: str, username: str, lang: str) -> EmailVariant:
    subject = _email_text("email.incomplete_signup_account_deleted.subject", lang)
    return EmailVariant(
        label=f"{lang} account deleted confirmation",
        template="incomplete-signup-account-deleted",
        subject=subject,
        context={
            "darkmode": False,
            "subject": subject,
            "username": username,
            "greeting_name": _greeting_name(username),
            "signup_link": base_url,
            "newsletter_settings_link": f"{base_url}/#settings/newsletter",
        },
    )


async def _send_tests(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    base_url = (args.base_url or get_frontend_base_url()).rstrip("/")
    langs = [lang.strip() for lang in args.langs.split(",") if lang.strip()]
    invalid_langs = [lang for lang in langs if lang not in SUPPORTED_TEMPLATE_LANGS]
    if invalid_langs:
        logger.error("Unsupported language(s) for these templates: %s", ", ".join(invalid_langs))
        return 1

    variants_by_lang = {
        lang: [
            _build_reminder_variant(14, base_url, args.username, args.account_id, lang),
            _build_reminder_variant(7, base_url, args.username, args.account_id, lang),
            _build_reminder_variant(1, base_url, args.username, args.account_id, lang),
            _build_deleted_variant(base_url, args.username, lang),
        ]
        for lang in langs
    }

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    directus = DirectusService()
    try:
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        campaign_key = args.campaign_key or f"incomplete_signup_deletion_test_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        sent = 0
        skipped = 0
        for lang, variants in variants_by_lang.items():
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
                    subject=f"[TEST][{lang.upper()}] {variant.subject}",
                    lang=lang,
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
    parser.add_argument("--username", default="", help="Recipient display name in the email body")
    parser.add_argument("--account-id", default="test-account-id", help="Account ID used in the delete-account deep link")
    parser.add_argument("--base-url", default=None, help="Override frontend base URL")
    parser.add_argument("--campaign-key", default=None, help="Optional deterministic campaign key for idempotency testing")
    parser.add_argument("--langs", default="en,de", help="Comma-separated languages to send. Supported: en,de")
    return asyncio.run(_send_tests(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
