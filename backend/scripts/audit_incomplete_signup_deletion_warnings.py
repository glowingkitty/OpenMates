#!/usr/bin/env python3
"""
Purpose: Audit incomplete-signup deletion warnings against completed credit sources.
Scope: Read-only; never sends email, creates invoices, or mutates users.
Usage: Run inside the api container so Directus, Vault, and Stripe config match.
Output: User IDs/account IDs only; no plaintext email addresses are printed.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from typing import Any

sys.path.insert(0, "/app/backend")

import stripe

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger("audit_incomplete_signup_deletion_warnings")

CAMPAIGN_KEY = "incomplete_signup_deletion_v1"
EMAIL_TYPE = "incomplete_signup_deletion"
STRIPE_SECRET_PATH = "kv/data/providers/stripe"
WARNING_STATUSES = ["processing", "sent", "archived"]


def _is_production() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "development").lower() == "production"


async def _stripe_api_key(secrets: SecretsManager) -> str:
    key_name = "production_secret_key" if _is_production() else "sandbox_secret_key"
    api_key = await secrets.get_secret(STRIPE_SECRET_PATH, key_name)
    if not api_key:
        raise RuntimeError(f"Missing Stripe secret {key_name}")
    return api_key


async def _warning_deliveries(directus: DirectusService) -> dict[str, list[dict[str, Any]]]:
    deliveries = await directus.get_items(
        "email_deliveries",
        params={
            "filter": {
                "email_type": {"_eq": EMAIL_TYPE},
                "campaign_key": {"_eq": CAMPAIGN_KEY},
                "status": {"_in": WARNING_STATUSES},
            },
            "fields": "recipient_id,stage,status,sent_at,processing_started_at,archived_at",
            "limit": -1,
        },
        admin_required=True,
    )
    by_user: dict[str, list[dict[str, Any]]] = {}
    for delivery in deliveries:
        recipient_id = delivery.get("recipient_id")
        if recipient_id:
            by_user.setdefault(recipient_id, []).append(delivery)
    return by_user


async def _user(directus: DirectusService, user_id: str) -> dict[str, Any]:
    users = await directus.get_items(
        "users",
        params={
            "filter": {"id": {"_eq": user_id}},
            "fields": "id,status,signup_completed,last_opened,signup_started_at,last_access,account_id,language,stripe_customer_id",
            "limit": 1,
        },
        admin_required=True,
    )
    return users[0] if users else {}


async def _local_credit_sources(directus: DirectusService, user_id: str) -> dict[str, int]:
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    invoices = await directus.get_items(
        "invoices",
        params={"filter": {"user_id_hash": {"_eq": user_id_hash}}, "fields": "id", "limit": -1},
        admin_required=True,
    )
    redeemed_gift_cards = await directus.get_items(
        "redeemed_gift_cards",
        params={"filter": {"user_id_hash": {"_eq": user_id_hash}}, "fields": "id", "limit": -1},
        admin_required=True,
    )
    return {"invoice_count": len(invoices), "redeemed_gift_card_count": len(redeemed_gift_cards)}


def _stripe_successes(customer_id: str | None) -> list[dict[str, Any]]:
    if not customer_id:
        return []
    successes: list[dict[str, Any]] = []
    for payment_intent in stripe.PaymentIntent.list(customer=customer_id, limit=100).auto_paging_iter():
        metadata = getattr(payment_intent, "metadata", {}) or {}
        if payment_intent.status == "succeeded" and metadata.get("purchase_type") == "credits":
            successes.append({
                "id": payment_intent.id,
                "created": payment_intent.created,
                "amount": payment_intent.amount,
                "currency": payment_intent.currency,
            })
    return successes


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    secrets = SecretsManager()
    await secrets.initialize()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    try:
        stripe.api_key = await _stripe_api_key(secrets)
        deliveries_by_user = await _warning_deliveries(directus)
        findings: list[dict[str, Any]] = []
        for user_id, deliveries in sorted(deliveries_by_user.items()):
            user = await _user(directus, user_id)
            local_sources = await _local_credit_sources(directus, user_id)
            stripe_successes = _stripe_successes(user.get("stripe_customer_id"))
            has_credit_source = bool(
                local_sources["invoice_count"]
                or local_sources["redeemed_gift_card_count"]
                or stripe_successes
            )
            if not args.all and not has_credit_source:
                continue
            findings.append({
                "user_id": user_id,
                "account_id": user.get("account_id"),
                "signup_completed": user.get("signup_completed"),
                "last_opened": user.get("last_opened"),
                "language": user.get("language"),
                **local_sources,
                "stripe_success_count": len(stripe_successes),
                "stripe_successes": stripe_successes[: args.max_stripe_payments],
                "deliveries": deliveries,
            })
        print(json.dumps({
            "warning_recipient_count": len(deliveries_by_user),
            "matched_recipient_count": len(findings),
            "only_credit_source_recipients": not args.all,
            "findings": findings,
        }, indent=2, sort_keys=True))
        return 0
    finally:
        await directus.close()
        await secrets.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit deletion-warning recipients against completed credit sources.")
    parser.add_argument("--all", action="store_true", help="Include every warning recipient, not only users with completed credit sources")
    parser.add_argument("--max-stripe-payments", type=int, default=3, help="Maximum successful Stripe payments to include per user")
    parser.add_argument("--verbose", action="store_true", help="Enable INFO logging")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
