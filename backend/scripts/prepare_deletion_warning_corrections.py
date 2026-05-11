#!/usr/bin/env python3
"""
Prepare correction emails for paid users who received deletion warnings.

Default mode only prints affected user IDs from the email delivery ledger. The
script creates a fresh 500-credit gift card and sends a draft only when
--send-test is passed. Real-user sending requires both --send-real and
--confirm-real, and should only run after explicit operator approval.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import string
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, "/app/backend")

import stripe

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.translations import TranslationService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.frontend_url import get_frontend_base_url

logger = logging.getLogger("prepare_deletion_warning_corrections")

CAMPAIGN_KEY = "incomplete_signup_deletion_v1"
EMAIL_TYPE = "incomplete_signup_deletion"
CORRECTION_CREDITS = 500
STRIPE_SECRET_PATH = "kv/data/providers/stripe"
GIFT_CARD_CHARSET = (
    string.ascii_uppercase.replace("O", "").replace("I", "")
    + string.digits.replace("0", "").replace("1", "")
)
TRANSLATION_SERVICE = TranslationService()


def _generate_gift_card_code() -> str:
    return "-".join("".join(random.choices(GIFT_CARD_CHARSET, k=4)) for _ in range(3))


def _is_production() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "development").lower() == "production"


async def _stripe_api_key(secrets: SecretsManager) -> str:
    key_name = "production_secret_key" if _is_production() else "sandbox_secret_key"
    api_key = await secrets.get_secret(STRIPE_SECRET_PATH, key_name)
    if not api_key:
        raise RuntimeError(f"Missing Stripe secret {key_name}")
    return api_key


async def _create_gift_card(directus: DirectusService, notes: str) -> str:
    for _ in range(5):
        code = _generate_gift_card_code()
        if await directus.get_gift_card_by_code(code) is None:
            created = await directus.create_gift_card(code=code, credits_value=CORRECTION_CREDITS)
            if not created:
                raise RuntimeError("Directus refused to create correction gift card")
            await directus.update_item("gift_cards", created["id"], {"notes": notes}, admin_required=True)
            return code
    raise RuntimeError("Could not generate a unique gift card code")


def _translated_subject(lang: str) -> str:
    subject = TRANSLATION_SERVICE.get_nested_translation(
        "email.account_deletion_warning_correction.subject",
        lang,
        {},
    )
    return subject if subject != "email.account_deletion_warning_correction.subject" else "Correction: your OpenMates account will not be deleted"


async def _send_email(secrets: SecretsManager, to_email: str, code: str, name: str = "", lang: str = "en") -> bool:
    subject = _translated_subject(lang)
    base_url = get_frontend_base_url().rstrip("/")
    email_template_service = EmailTemplateService(secrets_manager=secrets)
    return await email_template_service.send_email(
        template="account-deletion-warning-correction",
        recipient_email=to_email,
        context={
            "darkmode": False,
            "subject": subject,
            "gift_card_code": code,
            "redeem_link": f"{base_url}/#settings/billing",
            "greeting_name": f" {name}" if name else "",
            "credits": CORRECTION_CREDITS,
        },
        subject=subject,
        lang=lang,
    )


async def _user_has_successful_stripe_credit_payment(customer_id: str | None) -> bool:
    if not customer_id:
        return False
    for payment_intent in stripe.PaymentIntent.list(customer=customer_id, limit=100).auto_paging_iter():
        metadata = getattr(payment_intent, "metadata", {}) or {}
        if payment_intent.status == "succeeded" and metadata.get("purchase_type") == "credits":
            return True
    return False


async def _paid_warning_recipients(directus: DirectusService) -> list[dict[str, Any]]:
    deliveries = await directus.get_items(
        "email_deliveries",
        params={
            "filter": {
                "email_type": {"_eq": EMAIL_TYPE},
                "campaign_key": {"_eq": CAMPAIGN_KEY},
                "stage": {"_eq": "14d"},
                "status": {"_eq": "sent"},
            },
            "fields": "recipient_id,sent_at",
            "limit": -1,
        },
        admin_required=True,
    )
    recipients: list[dict[str, Any]] = []
    for delivery in deliveries:
        user_id = delivery.get("recipient_id")
        if not user_id:
            continue
        users = await directus.get_items(
            "users",
            params={
                "filter": {"id": {"_eq": user_id}},
                "fields": "id,stripe_customer_id,language",
                "limit": 1,
            },
            admin_required=True,
        )
        user = users[0] if users else {}
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()
        invoices = await directus.get_items(
            "invoices",
            params={"filter": {"user_id_hash": {"_eq": user_hash}}, "fields": "id", "limit": 1},
            admin_required=True,
        )
        gifts = await directus.get_items(
            "redeemed_gift_cards",
            params={"filter": {"user_id_hash": {"_eq": user_hash}}, "fields": "id", "limit": 1},
            admin_required=True,
        )
        if invoices or gifts:
            recipients.append({
                "user_id": user_id,
                "sent_at": delivery.get("sent_at"),
                "paid_source": "directus",
                "lang": user.get("language") or "en",
            })
            continue

        customer_id = user.get("stripe_customer_id")
        if await _user_has_successful_stripe_credit_payment(customer_id):
            recipients.append({
                "user_id": user_id,
                "sent_at": delivery.get("sent_at"),
                "paid_source": "stripe",
                "lang": user.get("language") or "en",
            })
    return recipients


async def _decrypt_contact_email(
    directus: DirectusService,
    encryption: EncryptionService,
    user_id: str,
) -> str | None:
    rows = await directus.get_items(
        "account_contact_emails",
        params={
            "filter": {"user_id": {"_eq": user_id}, "purpose": {"_eq": "account_lifecycle"}},
            "fields": "encrypted_email_address",
            "limit": 1,
        },
        admin_required=True,
    )
    if not rows:
        return None
    return await encryption.decrypt_account_contact_email(rows[0].get("encrypted_email_address"))


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    secrets = SecretsManager()
    await secrets.initialize()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    try:
        stripe.api_key = await _stripe_api_key(secrets)
        if args.send_test:
            code = await _create_gift_card(
                directus,
                f"Deletion-warning correction test draft for {args.test_to} at {datetime.now(timezone.utc).isoformat()}",
            )
            ok = await _send_email(secrets, args.test_to, code, "OpenMates test", args.lang)
            print(json.dumps({"sent_test": ok, "test_to": args.test_to, "gift_card_code": code}, indent=2))
            return 0 if ok else 1

        recipients = await _paid_warning_recipients(directus)
        print(json.dumps({"dry_run": not args.send_real, "paid_warning_recipients": recipients, "count": len(recipients)}, indent=2))
        if not args.send_real:
            return 0
        if not args.confirm_real:
            raise SystemExit("Refusing real sends without --confirm-real")

        sent = 0
        for recipient in recipients:
            email = await _decrypt_contact_email(directus, encryption, recipient["user_id"])
            if not email:
                logger.error("Skipping %s: no decryptable contact email", recipient["user_id"])
                continue
            code = await _create_gift_card(
                directus,
                f"Deletion-warning correction for user {recipient['user_id']} at {datetime.now(timezone.utc).isoformat()}",
            )
            if await _send_email(secrets, email, code, lang=recipient.get("lang") or "en"):
                sent += 1
        print(json.dumps({"sent_real": sent, "eligible": len(recipients)}, indent=2))
        return 0
    finally:
        await directus.close()
        await secrets.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare correction emails for mistaken deletion-warning recipients.")
    parser.add_argument("--send-test", action="store_true", help="Create one real 500-credit gift card and send draft to --test-to")
    parser.add_argument("--test-to", default="testing@openmates.org", help="Recipient for test draft")
    parser.add_argument("--lang", default="en", help="Language for --send-test draft (for example: en or de)")
    parser.add_argument("--send-real", action="store_true", help="Send correction emails to real eligible users")
    parser.add_argument("--confirm-real", action="store_true", help="Required with --send-real")
    parser.add_argument("--verbose", action="store_true", help="Enable INFO logging")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
