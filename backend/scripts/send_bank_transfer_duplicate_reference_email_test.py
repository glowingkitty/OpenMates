#!/usr/bin/env python3
"""
Send Duplicate Bank-Transfer Reference Test Email
================================================

Operator utility for reviewing the user-facing duplicate-reference email design
through the normal EmailTemplateService/Brevo path. It uses a test recipient and
does not look up or mutate user payment records. Keep this script deterministic
so support can resend the same preview safely during copy/design review.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.email_delivery_guard import send_email_once
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager


logger = logging.getLogger(__name__)


async def _send_test(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    directus = DirectusService()
    try:
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        campaign_key = args.campaign_key or f"bank_transfer_duplicate_reference_test_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        context = {
            "darkmode": args.darkmode,
            "credits_amount": args.credits,
            "reference": args.reference,
            "expected_amount_eur": args.expected_amount,
            "received_amount_eur": args.received_amount,
            "total_received_eur": args.total_received,
            "overpaid_amount_eur": args.overpaid_amount,
            "transaction_id": args.transaction_id,
            "support_email": args.support_email,
            "support_mailto": f"mailto:{args.support_email}",
        }
        ok, status = await send_email_once(
            directus=directus,
            email_template_service=email_template_service,
            email_type="bank_transfer_duplicate_reference_test",
            campaign_key=campaign_key,
            recipient_kind="test_email_address",
            recipient_id=args.to.lower().strip(),
            stage="preview",
            template="bank-transfer-duplicate-reference",
            recipient_email=args.to,
            context=context,
            subject="[TEST] Duplicate bank transfer reference received",
            lang=args.lang,
        )
        if ok or status == "already_reserved":
            logger.info("Duplicate-reference test email sent/reserved for %s", args.to)
            return 0
        logger.error("Duplicate-reference test email failed for %s (status=%s)", args.to, status)
        return 1
    finally:
        await directus.close()
        await secrets_manager.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the duplicate bank-transfer reference email preview via Brevo.")
    parser.add_argument("--to", default="testing@openmates.org", help="Recipient email address")
    parser.add_argument("--lang", default="en", help="Template language")
    parser.add_argument("--reference", default="OM-TEST-bt123456", help="Example OM payment reference")
    parser.add_argument("--credits", default="10.000", help="Formatted credits amount")
    parser.add_argument("--expected-amount", default="10.00", help="Original selected pack amount in EUR")
    parser.add_argument("--received-amount", default="10.00", help="Duplicate transfer amount in EUR")
    parser.add_argument("--total-received", default="20.00", help="Total received under the reused reference in EUR")
    parser.add_argument("--overpaid-amount", default="10.00", help="Unresolved amount above selected pack in EUR")
    parser.add_argument("--transaction-id", default="txn_duplicate_reference_test", help="Example Revolut transaction ID")
    parser.add_argument("--support-email", default="support@openmates.org", help="Support email shown in the message")
    parser.add_argument("--campaign-key", default=None, help="Optional deterministic delivery-guard campaign key")
    parser.add_argument("--darkmode", action="store_true", help="Render the dark-mode email variant")
    return asyncio.run(_send_test(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
