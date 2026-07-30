#!/usr/bin/env python3
"""
Audit successful Stripe credit payments that are missing accounting records.

This script is intentionally dry-run by default. With --apply it dispatches the
existing invoice generation task with send_email=False, so backfilled PDFs and
Directus rows are created without notifying users. Run inside the api container
so Vault, Directus, Redis, S3, Stripe, and Celery settings match the target env.

When --check-invoice-ninja is set, the audit also checks whether each order is
present in Invoice Ninja. Directus-present/Invoice-Ninja-missing rows are
reported but not applied because replaying the invoice task would create a
duplicate Directus invoice row.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (str(REPO_ROOT), "/app/backend"):
    if path not in sys.path:
        sys.path.insert(0, path)

import stripe  # noqa: E402

from backend.core.api.app.services.cache import CacheService  # noqa: E402
from backend.core.api.app.services.directus.directus import DirectusService  # noqa: E402
from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService  # noqa: E402
from backend.core.api.app.utils.encryption import EncryptionService  # noqa: E402
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402

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


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    if "T" not in normalized:
        normalized = f"{normalized}T00:00:00+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iter_payment_intents(
    payment_intents: list[str],
    days: int,
    from_date: datetime | None,
    to_date: datetime | None,
):
    if payment_intents:
        for payment_intent_id in payment_intents:
            yield stripe.PaymentIntent.retrieve(payment_intent_id)
        return

    created_filter: dict[str, int] = {}
    created_after = from_date or (datetime.now(timezone.utc) - timedelta(days=days))
    created_filter["gte"] = int(created_after.timestamp())
    if to_date:
        created_filter["lt"] = int(to_date.timestamp())

    for payment_intent in stripe.PaymentIntent.list(
        created=created_filter,
        limit=100,
        expand=["data.latest_charge"],
    ).auto_paging_iter():
        yield payment_intent


async def _invoice_record(directus: DirectusService, payment_intent_id: str) -> dict[str, Any] | None:
    rows = await directus.get_items(
        "invoices",
        params={
            "filter": {
                "_or": [
                    {"order_id": {"_eq": payment_intent_id}},
                    {"provider_order_id": {"_eq": payment_intent_id}},
                ]
            },
            "fields": "id,order_id,provider_order_id,provider,date",
            "limit": 1,
        },
        admin_required=True,
    )
    return rows[0] if rows else None


def _ninja_invoice_matches(row: dict[str, Any], external_order_id: str) -> bool:
    return (
        str(row.get("custom_value2") or "") == external_order_id
        or f"Order ID: {external_order_id}" in str(row.get("private_notes") or "")
    )


async def _ninja_invoice_exists(ninja: InvoiceNinjaService, external_order_id: str) -> bool | None:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    saw_lookup_error = False
    for params in (
        {"custom_value2": external_order_id},
        {"filter": external_order_id, "status": "active"},
        {"filter": external_order_id},
    ):
        response = await ninja.make_api_request("GET", "/invoices", params=params)
        if response is None:
            saw_lookup_error = True
            continue
        for row in (response or {}).get("data") or []:
            row_id = str(row.get("id") or "")
            if row_id and row_id in seen_ids:
                continue
            if row_id:
                seen_ids.add(row_id)
            rows.append(row)
    if any(_ninja_invoice_matches(row, external_order_id) for row in rows):
        return True
    return None if saw_lookup_error else False


def _apply_action_for_stripe_record(
    directus_present: bool,
    invoice_ninja_present: bool | None,
    checked_invoice_ninja: bool,
) -> str:
    if directus_present:
        if checked_invoice_ninja and invoice_ninja_present is False:
            return "none_requires_invoice_ninja_backfill"
        if checked_invoice_ninja and invoice_ninja_present is None:
            return "none_invoice_ninja_unknown"
        return "none_directus_present"
    if checked_invoice_ninja:
        if invoice_ninja_present is True:
            return "none_invoice_ninja_present"
        if invoice_ninja_present is None:
            return "none_invoice_ninja_unknown"
    return "dispatch_no_email_invoice_task"


def _apply_preflight_blockers(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocked = [
        item for item in findings
        if item.get("apply_action") not in ("dispatch_no_email_invoice_task", "none_directus_present")
    ]
    unmapped = [
        item for item in findings
        if item.get("apply_action") == "dispatch_no_email_invoice_task" and not item.get("user_id")
    ]
    return blocked, unmapped


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


async def _iter_bank_transfer_invoice_rows(
    directus: DirectusService,
    from_date: datetime,
    to_date: datetime | None,
) -> list[dict[str, Any]]:
    date_filter: dict[str, str] = {"_gte": from_date.isoformat()}
    if to_date:
        date_filter["_lt"] = to_date.isoformat()
    return await directus.get_items(
        "invoices",
        params={
            "filter": {
                "provider": {"_eq": "bank_transfer"},
                "date": date_filter,
            },
            "fields": "id,order_id,provider_order_id,provider,date",
            "limit": -1,
        },
        admin_required=True,
    ) or []


def _credits_from_metadata(payment_intent: Any) -> int | None:
    raw = (getattr(payment_intent, "metadata", {}) or {}).get("credits_purchased")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def _audit(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    from_date = _parse_datetime(args.from_date)
    to_date = _parse_datetime(args.to_date)
    check_invoice_ninja = args.check_invoice_ninja or args.include_bank_transfers
    if args.apply and not check_invoice_ninja:
        raise SystemExit("--apply requires --check-invoice-ninja to avoid duplicate Invoice Ninja invoices")

    secrets = SecretsManager()
    await secrets.initialize()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    ninja = None

    try:
        stripe.api_key = await _stripe_api_key(secrets)
        if check_invoice_ninja:
            ninja = await InvoiceNinjaService.create(secrets)
        sender = await _sender_details(secrets)
        scanned = missing_directus = missing_invoice_ninja = dispatched = skipped = 0
        findings: list[dict[str, Any]] = []

        for payment_intent in _iter_payment_intents(args.payment_intent, args.days, from_date, to_date):
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

            directus_invoice = await _invoice_record(directus, payment_intent.id)
            directus_present = directus_invoice is not None
            invoice_ninja_present = None
            if ninja:
                invoice_ninja_present = await _ninja_invoice_exists(ninja, payment_intent.id)

            if directus_present and (not check_invoice_ninja or invoice_ninja_present is True):
                continue

            user = await _user_for_customer(directus, getattr(payment_intent, "customer", None))
            apply_action = _apply_action_for_stripe_record(
                directus_present=directus_present,
                invoice_ninja_present=invoice_ninja_present,
                checked_invoice_ninja=check_invoice_ninja,
            )
            record = {
                "source": "stripe_payment_intent",
                "payment_intent_id": payment_intent.id,
                "customer_id": getattr(payment_intent, "customer", None),
                "amount": payment_intent.amount,
                "currency": payment_intent.currency,
                "credits": credits,
                "directus_invoice_id": directus_invoice.get("id") if directus_invoice else None,
                "directus_present": directus_present,
                "invoice_ninja_present": invoice_ninja_present,
                "user_id": user.get("id") if user else None,
                "account_id": user.get("account_id") if user else None,
                "apply_action": apply_action,
            }
            findings.append(record)
            if not directus_present:
                missing_directus += 1
            if invoice_ninja_present is False:
                missing_invoice_ninja += 1

        if args.include_bank_transfers:
            bank_transfer_from_date = from_date or (datetime.now(timezone.utc) - timedelta(days=args.days))
            for invoice in await _iter_bank_transfer_invoice_rows(directus, bank_transfer_from_date, to_date):
                order_id = str(invoice.get("order_id") or invoice.get("provider_order_id") or "")
                if not order_id:
                    continue
                invoice_ninja_present = await _ninja_invoice_exists(ninja, order_id) if ninja else None
                if invoice_ninja_present is not False:
                    continue
                missing_invoice_ninja += 1
                findings.append({
                    "source": "directus_bank_transfer_invoice",
                    "order_id": order_id,
                    "directus_invoice_id": invoice.get("id"),
                    "directus_present": True,
                    "invoice_ninja_present": invoice_ninja_present,
                    "provider": invoice.get("provider"),
                    "date": invoice.get("date"),
                    "apply_action": "none_requires_invoice_ninja_backfill",
                })

        if args.apply:
            blocked, unmapped = _apply_preflight_blockers(findings)
            if blocked or unmapped:
                logger.error(
                    "Invoice backfill apply preflight failed: blocked=%s unmapped=%s. No tasks were dispatched.",
                    len(blocked),
                    len(unmapped),
                )
            else:
                recheck_blocked: list[dict[str, Any]] = []
                for item in findings:
                    if item.get("apply_action") != "dispatch_no_email_invoice_task":
                        continue
                    order_id = item["payment_intent_id"]
                    latest_directus_invoice = await _invoice_record(directus, order_id)
                    latest_invoice_ninja_present = await _ninja_invoice_exists(ninja, order_id) if ninja else None
                    if latest_directus_invoice is not None:
                        item["apply_recheck"] = "directus_present"
                        item["apply_recheck_directus_invoice_id"] = latest_directus_invoice.get("id")
                        recheck_blocked.append(item)
                    elif latest_invoice_ninja_present is not False:
                        item["apply_recheck"] = (
                            "invoice_ninja_present"
                            if latest_invoice_ninja_present is True
                            else "invoice_ninja_unknown"
                        )
                        recheck_blocked.append(item)

                if recheck_blocked:
                    logger.error(
                        "Invoice backfill apply recheck failed for %s item(s). No tasks were dispatched.",
                        len(recheck_blocked),
                    )
                else:
                    from backend.core.api.app.tasks.celery_config import app

                    for item in findings:
                        if item.get("apply_action") != "dispatch_no_email_invoice_task":
                            continue
                        app.send_task(
                            name=INVOICE_TASK,
                            kwargs={
                                "order_id": item["payment_intent_id"],
                                "user_id": item["user_id"],
                                "credits_purchased": item["credits"],
                                "sender_addressline1": sender.get("addressline1") or "",
                                "sender_addressline2": sender.get("addressline2") or "",
                                "sender_addressline3": sender.get("addressline3") or "",
                                "sender_country": sender.get("country") or "",
                                "sender_email": sender.get("email") or "support@openmates.org",
                                "sender_vat": sender.get("vat") or "",
                                "provider": "stripe",
                                "provider_order_id": item["payment_intent_id"],
                                "send_email": False,
                            },
                            queue="email",
                        )
                        dispatched += 1

        print(json.dumps({
            "dry_run": not args.apply,
            "scanned": scanned,
            "skipped": skipped,
            "missing": missing_directus,
            "missing_directus": missing_directus,
            "missing_invoice_ninja": missing_invoice_ninja,
            "dispatched": dispatched,
            "findings": findings,
        }, indent=2, sort_keys=True))
        if args.apply and dispatched == 0 and any(item.get("apply_action") == "dispatch_no_email_invoice_task" for item in findings):
            return 1
        if args.apply and any(item.get("apply_action") not in ("dispatch_no_email_invoice_task", "none_directus_present") for item in findings):
            return 1
        return 0
    finally:
        if ninja:
            await ninja.close()
        await directus.close()
        await secrets.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit/backfill Directus invoices missing for Stripe credit payments.")
    parser.add_argument("--days", type=int, default=180, help="Look back this many days when no --payment-intent is provided")
    parser.add_argument("--from-date", help="Inclusive UTC start date/time, e.g. 2026-07-01 or 2026-07-01T00:00:00Z")
    parser.add_argument("--to-date", help="Exclusive UTC end date/time, e.g. 2026-08-01 or 2026-08-01T00:00:00Z")
    parser.add_argument("--payment-intent", action="append", default=[], help="Specific PaymentIntent ID to inspect; repeatable")
    parser.add_argument("--check-invoice-ninja", action="store_true", help="Also report whether audited orders exist in Invoice Ninja")
    parser.add_argument("--include-bank-transfers", action="store_true", help="Also audit Directus bank-transfer invoices for missing Invoice Ninja rows")
    parser.add_argument("--apply", action="store_true", help="Dispatch no-email invoice backfill tasks for mapped missing invoices")
    parser.add_argument("--verbose", action="store_true", help="Enable INFO logging")
    return asyncio.run(_audit(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
