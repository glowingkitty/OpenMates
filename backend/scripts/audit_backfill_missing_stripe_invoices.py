#!/usr/bin/env python3
"""
Audit successful Stripe credit payments that are missing Directus invoice rows.

This script is intentionally dry-run by default. With --apply it dispatches the
existing invoice generation task with send_email=False, so backfilled PDFs and
Directus rows are created without notifying users. Run inside the api container
so Vault, Directus, Redis, S3, Stripe, and Celery settings match the target env.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, "/app/backend")

import stripe

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger("audit_backfill_missing_stripe_invoices")

INVOICE_TASK = "app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email"
STRIPE_SECRET_PATH = "kv/data/providers/stripe"
INVOICE_SENDER_SECRET_PATH = "kv/data/providers/invoice_sender"


def _is_production() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "development").lower() == "production"


async def _stripe_api_key(secrets: SecretsManager) -> str:
    key_name = "production_secret_key" if _is_production() else "sandbox_secret_key"
    api_key = await secrets.get_secret(STRIPE_SECRET_PATH, key_name)
    if not api_key:
        raise RuntimeError(f"Missing Stripe secret {key_name}")
    return api_key


async def _sender_details(secrets: SecretsManager) -> dict[str, str]:
    keys = ["addressline1", "addressline2", "addressline3", "country", "email", "vat"]
    values = {
        key: await secrets.get_secret(INVOICE_SENDER_SECRET_PATH, key)
        for key in keys
    }
    values["email"] = values.get("email") or "support@openmates.org"
    return values


def _iter_payment_intents(payment_intents: list[str], days: int):
    if payment_intents:
        for payment_intent_id in payment_intents:
            yield stripe.PaymentIntent.retrieve(payment_intent_id)
        return

    created_after = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    for payment_intent in stripe.PaymentIntent.list(
        created={"gte": created_after},
        limit=100,
        expand=["data.latest_charge"],
    ).auto_paging_iter():
        yield payment_intent


async def _invoice_exists(directus: DirectusService, payment_intent_id: str) -> bool:
    rows = await directus.get_items(
        "invoices",
        params={
            "filter": {
                "_or": [
                    {"order_id": {"_eq": payment_intent_id}},
                    {"provider_order_id": {"_eq": payment_intent_id}},
                ]
            },
            "fields": "id,order_id,provider_order_id",
            "limit": 1,
        },
        admin_required=True,
    )
    return bool(rows)


async def _user_for_customer(directus: DirectusService, customer_id: str | None) -> dict[str, Any] | None:
    if not customer_id:
        return None
    users = await directus.get_items(
        "users",
        params={
            "filter": {"stripe_customer_id": {"_eq": customer_id}},
            "fields": "id,account_id,stripe_customer_id",
            "limit": 2,
        },
        admin_required=True,
    )
    if len(users) != 1:
        return None
    return users[0]


def _credits_from_metadata(payment_intent: Any) -> int | None:
    raw = (getattr(payment_intent, "metadata", {}) or {}).get("credits_purchased")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def _audit(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    secrets = SecretsManager()
    await secrets.initialize()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)

    try:
        stripe.api_key = await _stripe_api_key(secrets)
        sender = await _sender_details(secrets)
        scanned = missing = dispatched = skipped = 0
        findings: list[dict[str, Any]] = []

        for payment_intent in _iter_payment_intents(args.payment_intent, args.days):
            scanned += 1
            if payment_intent.status != "succeeded":
                skipped += 1
                continue
            metadata = getattr(payment_intent, "metadata", {}) or {}
            if metadata.get("purchase_type") != "credits":
                skipped += 1
                continue
            credits = _credits_from_metadata(payment_intent)
            if not credits:
                skipped += 1
                continue
            if await _invoice_exists(directus, payment_intent.id):
                continue

            user = await _user_for_customer(directus, getattr(payment_intent, "customer", None))
            record = {
                "payment_intent_id": payment_intent.id,
                "customer_id": getattr(payment_intent, "customer", None),
                "amount": payment_intent.amount,
                "currency": payment_intent.currency,
                "credits": credits,
                "user_id": user.get("id") if user else None,
                "account_id": user.get("account_id") if user else None,
            }
            findings.append(record)
            missing += 1

            if args.apply and user:
                from backend.core.api.app.tasks.celery_config import app

                app.send_task(
                    name=INVOICE_TASK,
                    kwargs={
                        "order_id": payment_intent.id,
                        "user_id": user["id"],
                        "credits_purchased": credits,
                        "sender_addressline1": sender.get("addressline1") or "",
                        "sender_addressline2": sender.get("addressline2") or "",
                        "sender_addressline3": sender.get("addressline3") or "",
                        "sender_country": sender.get("country") or "",
                        "sender_email": sender.get("email") or "support@openmates.org",
                        "sender_vat": sender.get("vat") or "",
                        "provider": "stripe",
                        "provider_order_id": payment_intent.id,
                        "send_email": False,
                    },
                    queue="email",
                )
                dispatched += 1

        print(json.dumps({
            "dry_run": not args.apply,
            "scanned": scanned,
            "skipped": skipped,
            "missing": missing,
            "dispatched": dispatched,
            "findings": findings,
        }, indent=2, sort_keys=True))
        if args.apply and any(item["user_id"] is None for item in findings):
            logger.error("Some missing invoices could not be mapped to exactly one user; no task was dispatched for them.")
            return 1
        return 0
    finally:
        await directus.close()
        await secrets.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit/backfill Directus invoices missing for Stripe credit payments.")
    parser.add_argument("--days", type=int, default=180, help="Look back this many days when no --payment-intent is provided")
    parser.add_argument("--payment-intent", action="append", default=[], help="Specific PaymentIntent ID to inspect; repeatable")
    parser.add_argument("--apply", action="store_true", help="Dispatch no-email invoice backfill tasks for mapped missing invoices")
    parser.add_argument("--verbose", action="store_true", help="Enable INFO logging")
    return asyncio.run(_audit(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
