#!/usr/bin/env python3
"""
Audit successful Stripe credit payments that are missing accounting records.

This script is intentionally dry-run by default. With --apply it dispatches the
existing invoice generation task with send_email=False, so backfilled PDFs and
Directus rows are created without notifying users. Run inside the api container
so Vault, Directus, Redis, S3, Stripe, and Celery settings match the target env.

When --check-invoice-ninja is set, the audit also checks whether each order is
present in Invoice Ninja. Directus-present/Invoice-Ninja-missing bank-transfer
rows can be created with --apply-invoice-ninja-backfill, which uses the existing
encrypted Directus invoice/PDF as the source of truth and does not email users.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (str(REPO_ROOT), "/app/backend"):
    if path not in sys.path:
        sys.path.insert(0, path)

import stripe  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

from backend.core.api.app.services.cache import CacheService  # noqa: E402
from backend.core.api.app.services.directus.directus import DirectusService  # noqa: E402
from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService  # noqa: E402
from backend.core.api.app.services.pdf.invoice import InvoiceTemplateService  # noqa: E402
from backend.core.api.app.services.s3 import S3UploadService  # noqa: E402
from backend.core.api.app.services.s3.config import get_bucket_name  # noqa: E402
from backend.core.api.app.utils.encryption import EncryptionService  # noqa: E402
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402

logger = logging.getLogger("audit_backfill_missing_stripe_invoices")

INVOICE_TASK = "app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email"
STRIPE_SECRET_PATH = "kv/data/providers/stripe"
INVOICE_SENDER_SECRET_PATH = "kv/data/providers/invoice_sender"
BACKFILLED_INVOICE_FILENAME_RE = re.compile(r"^openmates_invoice_\d{4}_\d{2}_\d{2}_(?P<number>.+)\.pdf$")
ZERO_DECIMAL_CURRENCIES = {
    "bif",
    "clp",
    "djf",
    "gnf",
    "jpy",
    "kmf",
    "krw",
    "mga",
    "pyg",
    "rwf",
    "ugx",
    "vnd",
    "vuv",
    "xaf",
    "xof",
    "xpf",
}
INCOMPLETE_REPLACEMENT_CLEANUP_ORDER = (
    ("bank_transactions", "bank_transaction_id", "incomplete replacement bank transaction"),
    ("payments", "payment_id", "incomplete replacement payment"),
    ("invoices", "invoice_id", "incomplete replacement invoice"),
)


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


def _stripe_invoice_datetime(payment_intent: Any) -> datetime:
    latest_charge = getattr(payment_intent, "latest_charge", None)
    charge_created = getattr(latest_charge, "created", None) if latest_charge and not isinstance(latest_charge, str) else None
    created = charge_created or getattr(payment_intent, "created", None)
    if not created:
        raise RuntimeError(f"PaymentIntent {payment_intent.id} has no created timestamp")
    return datetime.fromtimestamp(int(created), tz=timezone.utc)


def _invoice_filename_for_date(invoice_number: str, invoice_date: str) -> str:
    return f"openmates_invoice_{invoice_date.replace('-', '_')}_{invoice_number}.pdf"


def _invoice_s3_object_key_for_date(invoice_date: str) -> str:
    return f"{invoice_date.replace('-', '_')}_{uuid.uuid4().hex}.pdf"


def _invoice_number_from_filename(filename: str) -> str | None:
    match = BACKFILLED_INVOICE_FILENAME_RE.match(filename)
    return match.group("number") if match else None


def _account_id_from_invoice_number(invoice_number: str) -> str | None:
    account_id, separator, counter = invoice_number.rpartition("-")
    return account_id if separator and account_id and counter.isdigit() else None


def _stripe_amount_to_display_units(amount: int, currency_code: str) -> float:
    if currency_code.lower() in ZERO_DECIMAL_CURRENCIES:
        return float(amount)
    return float(amount) / 100


def _card_details_from_payment_intent(payment_intent: Any) -> dict[str, str | None]:
    latest_charge = getattr(payment_intent, "latest_charge", None)
    payment_method_details = getattr(latest_charge, "payment_method_details", None)
    card = getattr(payment_method_details, "card", None) if payment_method_details else None
    billing_details = getattr(latest_charge, "billing_details", None) if latest_charge else None
    return {
        "card_brand": getattr(card, "brand", None) if card else None,
        "card_last_four": getattr(card, "last4", None) if card else None,
        "cardholder_name": getattr(billing_details, "name", None) if billing_details else None,
    }


def _iter_payment_intents(
    payment_intents: list[str],
    days: int,
    from_date: datetime | None,
    to_date: datetime | None,
):
    if payment_intents:
        for payment_intent_id in payment_intents:
            yield stripe.PaymentIntent.retrieve(payment_intent_id, expand=["latest_charge"])
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
            "fields": (
                "id,order_id,provider_order_id,provider,date,user_id_hash,"
                "encrypted_amount,encrypted_credits_purchased,encrypted_currency,"
                "encrypted_s3_object_key,encrypted_aes_key,aes_nonce,encrypted_filename,is_gift_card"
            ),
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


def _is_active_ninja_row(row: dict[str, Any]) -> bool:
    archived_at = row.get("archived_at")
    deleted_at = row.get("deleted_at")
    return archived_at in (None, 0, "0") and deleted_at in (None, 0, "0")


async def _ninja_invoice_rows(ninja: InvoiceNinjaService, external_order_id: str) -> tuple[list[dict[str, Any]], bool]:
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
    return [row for row in rows if _is_active_ninja_row(row) and _ninja_invoice_matches(row, external_order_id)], saw_lookup_error


async def _ninja_invoice_exists(ninja: InvoiceNinjaService, external_order_id: str) -> bool | None:
    rows, saw_lookup_error = await _ninja_invoice_rows(ninja, external_order_id)
    if rows:
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
            "fields": "id,account_id,stripe_customer_id,vault_key_id,language,darkmode",
            "limit": 2,
        },
        admin_required=True,
    )
    if len(users) != 1:
        return None
    return users[0]


async def _directus_users_by_hash(
    directus: DirectusService,
    wanted_hashes: set[str],
) -> dict[str, dict[str, Any]]:
    if not wanted_hashes:
        return {}
    users_by_hash: dict[str, dict[str, Any]] = {}
    offset = 0
    limit = 500
    for collection in ("users", "directus_users"):
        offset = 0
        while True:
            users = await directus.get_items(
                collection,
                params={
                    "fields": "id,account_id,vault_key_id",
                    "limit": limit,
                    "offset": offset,
                },
                admin_required=True,
            ) or []
            if not users:
                break
            for user in users:
                user_id = str(user.get("id") or "")
                if not user_id:
                    continue
                user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
                if user_hash in wanted_hashes:
                    users_by_hash[user_hash] = user
            if len(users_by_hash) == len(wanted_hashes):
                return users_by_hash
            offset += limit
    return users_by_hash


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
            "fields": (
                "id,order_id,provider_order_id,provider,date,user_id_hash,"
                "encrypted_amount,encrypted_credits_purchased,encrypted_currency,"
                "encrypted_s3_object_key,encrypted_aes_key,aes_nonce,encrypted_filename,is_gift_card"
            ),
            "limit": -1,
        },
        admin_required=True,
    ) or []


async def _iter_stripe_invoices_created_on(
    directus: DirectusService,
    created_on: datetime,
) -> list[dict[str, Any]]:
    start = created_on.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return await directus.get_items(
        "invoices",
        params={
            "filter": {
                "provider": {"_eq": "stripe"},
                "date": {"_gte": start.isoformat(), "_lt": end.isoformat()},
            },
            "fields": (
                "id,order_id,provider_order_id,provider,date,user_id_hash,"
                "encrypted_s3_object_key,encrypted_aes_key,aes_nonce,encrypted_filename,"
                "encrypted_credits_purchased,is_gift_card"
            ),
            "limit": -1,
        },
        admin_required=True,
    ) or []


async def _stripe_invoice_rows_for_payment_intents(
    directus: DirectusService,
    payment_intent_ids: set[str],
) -> list[dict[str, Any]]:
    if not payment_intent_ids:
        return []
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for payment_intent_id in sorted(payment_intent_ids):
        matches = await directus.get_items(
            "invoices",
            params={
                "filter": {
                    "_or": [
                        {"order_id": {"_eq": payment_intent_id}},
                        {"provider_order_id": {"_eq": payment_intent_id}},
                    ],
                    "provider": {"_eq": "stripe"},
                },
                "fields": (
                    "id,order_id,provider_order_id,provider,date,user_id_hash,"
                    "encrypted_s3_object_key,encrypted_aes_key,aes_nonce,encrypted_filename,"
                    "encrypted_credits_purchased,is_gift_card"
                ),
                "limit": 1,
            },
            admin_required=True,
        ) or []
        for row in matches:
            row_id = str(row.get("id") or "")
            if row_id and row_id not in seen_ids:
                seen_ids.add(row_id)
                rows.append(row)
    return rows


async def _ninja_bank_transaction_rows(
    ninja: InvoiceNinjaService,
    external_order_id: str,
    invoice_number: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for params in ({"filter": external_order_id}, {"filter": invoice_number}):
        response = await ninja.make_api_request("GET", "/bank_transactions", params=params)
        for row in (response or {}).get("data") or []:
            row_id = str(row.get("id") or "")
            if row_id and row_id in seen_ids:
                continue
            description = str(row.get("description") or "")
            if not _is_active_ninja_row(row):
                continue
            if external_order_id not in description and invoice_number not in description:
                continue
            if row_id:
                seen_ids.add(row_id)
            rows.append(row)
    return rows


async def _ninja_payment_rows(ninja: InvoiceNinjaService, external_order_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for params in (
        {"filter": external_order_id, "include": "invoices"},
        {"transaction_reference": external_order_id, "include": "invoices"},
    ):
        response = await ninja.make_api_request("GET", "/payments", params=params)
        for row in (response or {}).get("data") or []:
            row_id = str(row.get("id") or "")
            if row_id and row_id in seen_ids:
                continue
            if not _is_active_ninja_row(row):
                continue
            transaction_reference = str(row.get("transaction_reference") or "")
            if transaction_reference != external_order_id:
                continue
            if row_id:
                seen_ids.add(row_id)
            rows.append(row)
    return rows


async def _cleanup_incomplete_invoice_ninja_replacement(
    ninja: InvoiceNinjaService,
    replacement: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for endpoint, id_key, label in INCOMPLETE_REPLACEMENT_CLEANUP_ORDER:
        row_id = replacement.get(id_key)
        if not row_id:
            continue
        response = await ninja.make_api_request("DELETE", f"/{endpoint}/{row_id}")
        if response is None:
            errors.append(f"failed to delete {label} {row_id}")
    return errors


def _missing_invoice_ninja_replacement_parts(replacement: dict[str, Any] | None) -> list[str]:
    if not replacement:
        return ["replacement transaction"]
    required_parts = (
        ("invoice_id", "replacement invoice"),
        ("payment_id", "replacement payment"),
        ("bank_transaction_id", "replacement bank transaction"),
        ("pdf_upload_success", "replacement PDF upload"),
        ("transaction_match_success", "replacement bank transaction match"),
    )
    return [label for key, label in required_parts if not replacement.get(key)]


async def _decrypt_required_invoice_value(
    encryption: EncryptionService,
    invoice: dict[str, Any],
    field: str,
    vault_key_id: str,
) -> str:
    encrypted_value = invoice.get(field)
    if not encrypted_value:
        raise RuntimeError(f"Directus invoice is missing {field}")
    value = await encryption.decrypt_with_user_key(encrypted_value, vault_key_id)
    if value in (None, ""):
        raise RuntimeError(f"failed to decrypt Directus invoice {field}")
    return str(value)


async def _decrypt_directus_invoice_pdf(
    *,
    s3: S3UploadService,
    encryption: EncryptionService,
    invoice: dict[str, Any],
    vault_key_id: str,
) -> bytes:
    s3_object_key = await _decrypt_required_invoice_value(encryption, invoice, "encrypted_s3_object_key", vault_key_id)
    aes_key_b64 = await _decrypt_required_invoice_value(encryption, invoice, "encrypted_aes_key", vault_key_id)
    nonce_b64 = invoice.get("aes_nonce")
    if not nonce_b64:
        raise RuntimeError("Directus invoice is missing aes_nonce")
    encrypted_pdf_payload = await s3.get_file(get_bucket_name("invoices", s3.environment), s3_object_key)
    if not encrypted_pdf_payload:
        raise RuntimeError("failed to download encrypted invoice PDF from S3")
    try:
        aes_key = base64.b64decode(aes_key_b64)
        nonce = base64.b64decode(str(nonce_b64))
        return AESGCM(aes_key).decrypt(nonce, encrypted_pdf_payload, None)
    except Exception as exc:  # noqa: BLE001 - keep this operational script fail-closed.
        raise RuntimeError("failed to decrypt stored invoice PDF") from exc


async def _backfill_invoice_ninja_from_directus_invoice(
    *,
    ninja: InvoiceNinjaService,
    s3: S3UploadService | None,
    encryption: EncryptionService,
    invoice: dict[str, Any],
    user: dict[str, Any] | None,
    apply: bool,
) -> dict[str, Any]:
    external_order_id = str(invoice.get("order_id") or invoice.get("provider_order_id") or "")
    result: dict[str, Any] = {
        "directus_invoice_id": invoice.get("id"),
        "order_id": external_order_id,
        "apply": apply,
        "status": "pending",
        "errors": [],
    }
    if invoice.get("provider") != "bank_transfer":
        result["status"] = "blocked"
        result["errors"].append("Invoice Ninja-only backfill currently supports bank_transfer invoices only")
        return result
    if not external_order_id:
        result["status"] = "blocked"
        result["errors"].append("Directus invoice is missing order_id/provider_order_id")
        return result

    latest_invoice_ninja_present = await _ninja_invoice_exists(ninja, external_order_id)
    if latest_invoice_ninja_present is True:
        result["status"] = "already_present"
        return result
    if latest_invoice_ninja_present is None:
        result["status"] = "blocked"
        result["errors"].append("Invoice Ninja lookup failed")
        return result

    user_hash = str(invoice.get("user_id_hash") or "")
    vault_key_id = str((user or {}).get("vault_key_id") or "")
    if not user_hash or not user or not vault_key_id:
        result["status"] = "blocked"
        result["errors"].append("missing Directus user mapping with vault key")
        return result

    try:
        invoice_date = _parse_datetime(str(invoice.get("date") or ""))
        if not invoice_date:
            raise RuntimeError("Directus invoice is missing date")
        filename = await _decrypt_required_invoice_value(encryption, invoice, "encrypted_filename", vault_key_id)
        invoice_number = _invoice_number_from_filename(filename)
        if not invoice_number:
            raise RuntimeError("failed to parse invoice number from encrypted filename")
        amount_paid = int(await _decrypt_required_invoice_value(encryption, invoice, "encrypted_amount", vault_key_id))
        credits = int(await _decrypt_required_invoice_value(encryption, invoice, "encrypted_credits_purchased", vault_key_id))
        currency_code = "eur"
        if invoice.get("encrypted_currency"):
            currency_code = (await _decrypt_required_invoice_value(encryption, invoice, "encrypted_currency", vault_key_id)).lower()
        customer_account_id = str(user.get("account_id") or _account_id_from_invoice_number(invoice_number) or "")
        if not customer_account_id:
            raise RuntimeError("missing account_id for Invoice Ninja client")
    except (RuntimeError, TypeError, ValueError) as exc:
        result["status"] = "blocked"
        result["errors"].append(str(exc))
        return result

    result.update({
        "invoice_number": invoice_number,
        "invoice_date": invoice_date.date().isoformat(),
        "amount": amount_paid,
        "credits": credits,
        "currency": currency_code,
        "customer_account_id": customer_account_id,
    })
    if not apply:
        result["status"] = "would_create"
        return result
    if s3 is None:
        result["status"] = "blocked"
        result["errors"].append("S3 service unavailable for Invoice Ninja PDF backfill")
        return result

    try:
        pdf_bytes = await _decrypt_directus_invoice_pdf(
            s3=s3,
            encryption=encryption,
            invoice=invoice,
            vault_key_id=vault_key_id,
        )
        replacement = await ninja.process_income_transaction(
            user_hash=user_hash,
            external_order_id=external_order_id,
            customer_firstname="",
            customer_lastname="",
            customer_account_id=customer_account_id,
            customer_country_code="",
            credits_value=credits,
            currency_code=currency_code,
            purchase_price_value=_stripe_amount_to_display_units(amount_paid, currency_code),
            invoice_date=invoice_date.date().isoformat(),
            due_date=invoice_date.date().isoformat(),
            payment_processor="bank_transfer",
            card_brand_lower="",
            custom_invoice_number=invoice_number,
            custom_pdf_data=pdf_bytes,
            is_gift_card=bool(invoice.get("is_gift_card")),
        )
    except Exception as exc:  # noqa: BLE001 - operational script returns structured blockers.
        result["status"] = "blocked"
        result["errors"].append(str(exc))
        return result

    result["invoice_ninja"] = replacement
    missing_parts = _missing_invoice_ninja_replacement_parts(replacement)
    if missing_parts:
        result["status"] = "blocked"
        result["errors"].append(f"failed to create complete Invoice Ninja rows: {', '.join(missing_parts)}")
        if replacement:
            result["cleanup_errors"] = await _cleanup_incomplete_invoice_ninja_replacement(ninja, replacement)
            result["errors"].extend(result["cleanup_errors"])
        return result

    result["status"] = "created"
    return result


async def _encrypt_repair_pdf_payload(
    encryption: EncryptionService,
    vault_key_id: str,
    pdf_bytes: bytes,
) -> tuple[bytes, str, str]:
    aes_key = os.urandom(32)
    nonce = os.urandom(12)
    encrypted_payload = AESGCM(aes_key).encrypt(nonce, pdf_bytes, None)
    aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
    encrypted_aes_key, _ = await encryption.encrypt_with_user_key(aes_key_b64, vault_key_id)
    if not encrypted_aes_key:
        raise RuntimeError("failed to wrap repaired invoice PDF AES key")
    return encrypted_payload, encrypted_aes_key, base64.b64encode(nonce).decode("utf-8")


def _build_repair_invoice_data(
    *,
    invoice_number: str,
    invoice_date: str,
    user: dict[str, Any],
    credits: int,
    amount_paid: int,
    currency_code: str,
    card_details: dict[str, str | None],
    sender: dict[str, str],
    refund_link: str,
    is_gift_card: bool,
) -> dict[str, Any]:
    card_brand = card_details.get("card_brand") or ""
    formatted_card_brand = card_brand
    if card_brand:
        card_brand_lower = card_brand.lower()
        if card_brand_lower == "visa":
            formatted_card_brand = "VISA"
        elif card_brand_lower == "mastercard":
            formatted_card_brand = "MasterCard"
        elif card_brand_lower == "american_express":
            formatted_card_brand = "American Express"

    return {
        "invoice_number": invoice_number,
        "date_of_issue": invoice_date,
        "date_due": invoice_date,
        "receiver_name": "",
        "receiver_account_id": user.get("account_id"),
        "credits": credits,
        "actual_amount_paid": _stripe_amount_to_display_units(amount_paid, currency_code),
        "card_name": formatted_card_brand,
        "card_last4": card_details.get("card_last_four"),
        "sender_addressline1": sender.get("addressline1") or "",
        "sender_addressline2": sender.get("addressline2") or "",
        "sender_addressline3": sender.get("addressline3") or "",
        "sender_country": sender.get("country") or "",
        "sender_email": sender.get("email") or "support@openmates.org",
        "sender_vat": sender.get("vat") or "",
        "is_gift_card": is_gift_card,
        "refund_link": refund_link,
    }


async def _patch_invoice_ninja_date_surfaces(
    *,
    ninja: InvoiceNinjaService,
    external_order_id: str,
    invoice_rows: list[dict[str, Any]],
    invoice_number: str,
    invoice_date: str,
    pdf_bytes: bytes,
    apply: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "invoice_ids": [row.get("id") for row in invoice_rows],
        "payment_ids": [],
        "bank_transaction_ids": [],
        "updated": False,
        "errors": [],
    }
    payments = await _ninja_payment_rows(ninja, external_order_id)
    bank_transactions = await _ninja_bank_transaction_rows(ninja, external_order_id, invoice_number)
    result["payment_ids"] = [row.get("id") for row in payments]
    result["bank_transaction_ids"] = [row.get("id") for row in bank_transactions]

    if not apply:
        return result

    for row in invoice_rows:
        invoice_id = row.get("id")
        if not invoice_id:
            result["errors"].append("invoice row missing id")
            continue
        response = await ninja.make_api_request(
            "PUT",
            f"/invoices/{invoice_id}",
            data={"date": invoice_date, "due_date": invoice_date},
        )
        if response is None:
            result["errors"].append(f"failed to update invoice {invoice_id} date")
            continue
        if not await ninja.upload_invoice_document(invoice_id, pdf_bytes, f"{external_order_id}_invoice.pdf"):
            result["errors"].append(f"failed to upload corrected PDF for invoice {invoice_id}")

    for payment in payments:
        payment_id = payment.get("id")
        if not payment_id:
            continue
        response = await ninja.make_api_request("PUT", f"/payments/{payment_id}", data={"date": invoice_date})
        if response is None:
            result["errors"].append(f"failed to update payment {payment_id} date")

    for row in bank_transactions:
        transaction_id = row.get("id")
        if not transaction_id:
            continue
        response = await ninja.make_api_request(
            "PUT",
            f"/bank_transactions/{transaction_id}",
            data={"date": invoice_date},
        )
        if response is None:
            result["errors"].append(f"failed to update bank transaction {transaction_id} date")

    result["updated"] = not result["errors"]
    return result


async def _recreate_locked_invoice_ninja_surfaces(
    *,
    ninja: InvoiceNinjaService,
    external_order_id: str,
    invoice_rows: list[dict[str, Any]],
    invoice_number: str,
    invoice_date: str,
    pdf_bytes: bytes,
    user_hash: str,
    user: dict[str, Any],
    credits: int,
    amount_paid: int,
    currency_code: str,
    card_details: dict[str, str | None],
    is_gift_card: bool,
    apply: bool,
) -> dict[str, Any]:
    payments = await _ninja_payment_rows(ninja, external_order_id)
    bank_transactions = await _ninja_bank_transaction_rows(ninja, external_order_id, invoice_number)
    result: dict[str, Any] = {
        "mode": "delete_recreate",
        "old_invoice_ids": [row.get("id") for row in invoice_rows],
        "old_invoice_dates": [row.get("date") for row in invoice_rows],
        "old_invoice_due_dates": [row.get("due_date") for row in invoice_rows],
        "old_invoice_statuses": [row.get("status") or row.get("status_id") for row in invoice_rows],
        "old_invoice_archived_at": [row.get("archived_at") for row in invoice_rows],
        "old_invoice_deleted_at": [row.get("deleted_at") for row in invoice_rows],
        "old_payment_ids": [row.get("id") for row in payments],
        "old_payment_dates": [row.get("date") for row in payments],
        "old_payment_archived_at": [row.get("archived_at") for row in payments],
        "old_payment_deleted_at": [row.get("deleted_at") for row in payments],
        "old_bank_transaction_ids": [row.get("id") for row in bank_transactions],
        "old_bank_transaction_dates": [row.get("date") for row in bank_transactions],
        "old_bank_transaction_archived_at": [row.get("archived_at") for row in bank_transactions],
        "old_bank_transaction_deleted_at": [row.get("deleted_at") for row in bank_transactions],
        "recreated": False,
        "errors": [],
    }

    async def delete_rows(endpoint: str, rows: list[dict[str, Any]], label: str, *, stop_on_error: bool = False) -> bool:
        deleted_all = True
        for row in rows:
            row_id = row.get("id")
            if not row_id:
                continue
            response = await ninja.make_api_request("DELETE", f"/{endpoint}/{row_id}")
            if response is None:
                result["errors"].append(f"failed to delete {label} {row_id}")
                deleted_all = False
                if stop_on_error:
                    return False
        return deleted_all

    if not apply:
        return result

    cardholder_name = card_details.get("cardholder_name") or ""
    customer_firstname = ""
    customer_lastname = ""
    if cardholder_name:
        if " " in cardholder_name:
            customer_firstname, customer_lastname = cardholder_name.split(" ", 1)
        else:
            customer_firstname = cardholder_name

    replacement = await ninja.process_income_transaction(
        user_hash=user_hash,
        external_order_id=external_order_id,
        customer_firstname=customer_firstname,
        customer_lastname=customer_lastname,
        customer_account_id=str(user.get("account_id") or ""),
        customer_country_code="",
        credits_value=credits,
        currency_code=currency_code,
        purchase_price_value=_stripe_amount_to_display_units(amount_paid, currency_code),
        invoice_date=invoice_date,
        due_date=invoice_date,
        payment_processor="stripe",
        card_brand_lower=(card_details.get("card_brand") or "").lower(),
        custom_invoice_number=invoice_number,
        custom_pdf_data=pdf_bytes,
        is_gift_card=is_gift_card,
    )
    result["new_invoice_id"] = replacement.get("invoice_id") if replacement else None
    result["new_payment_id"] = replacement.get("payment_id") if replacement else None
    result["new_bank_transaction_id"] = replacement.get("bank_transaction_id") if replacement else None

    missing_replacement_parts = []
    if not replacement:
        missing_replacement_parts.append("replacement transaction")
    elif not replacement.get("invoice_id"):
        missing_replacement_parts.append("replacement invoice")
    elif not replacement.get("payment_id"):
        missing_replacement_parts.append("replacement payment")
    elif not replacement.get("bank_transaction_id"):
        missing_replacement_parts.append("replacement bank transaction")
    elif not replacement.get("pdf_upload_success"):
        missing_replacement_parts.append("replacement PDF upload")
    elif not replacement.get("transaction_match_success"):
        missing_replacement_parts.append("replacement bank transaction match")

    if missing_replacement_parts:
        result["errors"].append(f"failed to create complete replacement: {', '.join(missing_replacement_parts)}")
        if replacement:
            await delete_rows("bank_transactions", [{"id": replacement.get("bank_transaction_id")}], "incomplete replacement bank transaction")
            await delete_rows("payments", [{"id": replacement.get("payment_id")}], "incomplete replacement payment")
            await delete_rows("invoices", [{"id": replacement.get("invoice_id")}], "incomplete replacement invoice")
        return result

    result["replacement_created"] = True
    if not await delete_rows("bank_transactions", bank_transactions, "old bank transaction", stop_on_error=True):
        result["recreated"] = False
        return result
    if not await delete_rows("payments", payments, "old payment", stop_on_error=True):
        result["recreated"] = False
        return result
    if not await delete_rows("invoices", invoice_rows, "old invoice", stop_on_error=True):
        result["recreated"] = False
        return result
    result["recreated"] = not result["errors"]
    return result


async def _repair_backfilled_invoice_dates(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    created_on = _parse_datetime(args.repair_created_on)
    if not created_on:
        raise SystemExit("--repair-created-on must be a date or ISO timestamp")

    secrets = SecretsManager()
    await secrets.initialize()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    ninja = None
    s3 = None

    try:
        stripe.api_key = await _stripe_api_key(secrets)
        sender = await _sender_details(secrets)
        ninja = await InvoiceNinjaService.create(secrets)
        if args.apply_date_repair:
            s3 = S3UploadService(secrets)
            await s3.initialize()
        invoice_template = await InvoiceTemplateService.create(secrets)
        findings: list[dict[str, Any]] = []
        repaired = 0
        blocked = 0
        selected_payment_intents = set(args.payment_intent or [])
        directus_rows = await _iter_stripe_invoices_created_on(directus, created_on)
        if selected_payment_intents:
            rows_by_id = {str(row.get("id")): row for row in directus_rows if row.get("id")}
            for row in await _stripe_invoice_rows_for_payment_intents(directus, selected_payment_intents):
                row_id = str(row.get("id") or "")
                if row_id:
                    rows_by_id[row_id] = row
            directus_rows = list(rows_by_id.values())

        for invoice in directus_rows:
            external_order_id = str(invoice.get("provider_order_id") or invoice.get("order_id") or "")
            if not external_order_id.startswith("pi_"):
                continue
            if selected_payment_intents and external_order_id not in selected_payment_intents:
                continue
            exact_rows = await _stripe_invoice_rows_for_payment_intents(directus, {external_order_id})
            if exact_rows:
                invoice = exact_rows[0]

            payment_intent = stripe.PaymentIntent.retrieve(external_order_id, expand=["latest_charge"])
            original_datetime = _stripe_invoice_datetime(payment_intent)
            original_date = original_datetime.date().isoformat()
            current_date = _parse_datetime(str(invoice.get("date") or ""))
            directus_date_matches = bool(current_date and current_date.date() == original_datetime.date())
            if (
                directus_date_matches
                and not args.recreate_locked_invoice_ninja
                and not selected_payment_intents
            ):
                continue

            record: dict[str, Any] = {
                "directus_invoice_id": invoice.get("id"),
                "payment_intent_id": external_order_id,
                "current_directus_date": invoice.get("date"),
                "original_invoice_datetime": original_datetime.isoformat(),
                "original_invoice_date": original_date,
                "apply_date_repair": bool(args.apply_date_repair),
                "status": "pending",
                "errors": [],
            }

            user = await _user_for_customer(directus, getattr(payment_intent, "customer", None))
            if not user or not user.get("vault_key_id") or not user.get("account_id"):
                record["status"] = "blocked"
                record["errors"].append("missing unique Directus user mapping with vault/account data")
                findings.append(record)
                blocked += 1
                continue

            vault_key_id = user["vault_key_id"]
            encrypted_filename = invoice.get("encrypted_filename")
            encrypted_s3_object_key = invoice.get("encrypted_s3_object_key")
            if not encrypted_filename or not encrypted_s3_object_key:
                record["status"] = "blocked"
                record["errors"].append("Directus invoice is missing encrypted PDF metadata")
                findings.append(record)
                blocked += 1
                continue

            current_filename = await encryption.decrypt_with_user_key(encrypted_filename, vault_key_id)
            s3_object_key = await encryption.decrypt_with_user_key(encrypted_s3_object_key, vault_key_id)
            invoice_number = _invoice_number_from_filename(current_filename or "")
            if not current_filename or not s3_object_key or not invoice_number:
                record["status"] = "blocked"
                record["errors"].append("failed to decrypt current filename, S3 key, or invoice number")
                findings.append(record)
                blocked += 1
                continue

            credits = _credits_from_metadata(payment_intent)
            if not credits:
                record["status"] = "blocked"
                record["errors"].append("Stripe metadata does not contain credits_purchased")
                findings.append(record)
                blocked += 1
                continue

            refund_link = f"{os.getenv('WEBAPP_URL', 'https://openmates.org')}#settings/billing/invoices/{invoice['id']}/refund"
            currency_code = str(getattr(payment_intent, "currency", "eur")).lower()
            invoice_data = _build_repair_invoice_data(
                invoice_number=invoice_number,
                invoice_date=original_date,
                user=user,
                credits=credits,
                amount_paid=int(getattr(payment_intent, "amount", 0) or 0),
                currency_code=currency_code,
                card_details=_card_details_from_payment_intent(payment_intent),
                sender=sender,
                refund_link=refund_link,
                is_gift_card=bool(invoice.get("is_gift_card")),
            )
            pdf_buffer = invoice_template.generate_invoice(
                invoice_data,
                lang="en",
                currency=currency_code,
                document_type="invoice",
            )
            pdf_bytes = pdf_buffer.getvalue()
            pdf_buffer.close()
            corrected_filename = _invoice_filename_for_date(invoice_number, original_date)
            record.update({
                "current_filename": current_filename,
                "corrected_filename": corrected_filename,
                "old_s3_object_key_preserved": s3_object_key,
            })

            ninja_rows, ninja_lookup_error = await _ninja_invoice_rows(ninja, external_order_id)
            if not ninja_rows:
                record["status"] = "blocked"
                record["errors"].append("matching Invoice Ninja invoice not found" if not ninja_lookup_error else "Invoice Ninja lookup failed")
                findings.append(record)
                blocked += 1
                continue

            async def apply_invoice_ninja_repair(apply: bool) -> dict[str, Any]:
                if args.recreate_locked_invoice_ninja:
                    return await _recreate_locked_invoice_ninja_surfaces(
                        ninja=ninja,
                        external_order_id=external_order_id,
                        invoice_rows=ninja_rows,
                        invoice_number=invoice_number,
                        invoice_date=original_date,
                        pdf_bytes=pdf_bytes,
                        user_hash=str(invoice.get("user_id_hash") or ""),
                        user=user,
                        credits=credits,
                        amount_paid=int(getattr(payment_intent, "amount", 0) or 0),
                        currency_code=currency_code,
                        card_details=_card_details_from_payment_intent(payment_intent),
                        is_gift_card=bool(invoice.get("is_gift_card")),
                        apply=apply,
                    )
                return await _patch_invoice_ninja_date_surfaces(
                    ninja=ninja,
                    external_order_id=external_order_id,
                    invoice_rows=ninja_rows,
                    invoice_number=invoice_number,
                    invoice_date=original_date,
                    pdf_bytes=pdf_bytes,
                    apply=apply,
                )

            if args.apply_date_repair:
                if s3 is None:
                    record["status"] = "blocked"
                    record["errors"].append("S3 service unavailable for apply")
                    findings.append(record)
                    blocked += 1
                    continue
                if directus_date_matches:
                    record["directus_already_repaired"] = True
                else:
                    try:
                        encrypted_pdf_payload, encrypted_aes_key, aes_nonce_b64 = await _encrypt_repair_pdf_payload(
                            encryption,
                            vault_key_id,
                            pdf_bytes,
                        )
                    except RuntimeError as exc:
                        record["status"] = "blocked"
                        record["errors"].append(str(exc))
                        findings.append(record)
                        blocked += 1
                        continue
                    new_s3_object_key = _invoice_s3_object_key_for_date(original_date)
                    encrypted_new_s3_object_key, _ = await encryption.encrypt_with_user_key(new_s3_object_key, vault_key_id)
                    encrypted_corrected_filename, _ = await encryption.encrypt_with_user_key(corrected_filename, vault_key_id)
                    if not encrypted_new_s3_object_key or not encrypted_corrected_filename:
                        record["status"] = "blocked"
                        record["errors"].append("failed to encrypt repaired S3 key or filename")
                        findings.append(record)
                        blocked += 1
                        continue
                    upload_result = await s3.upload_file(
                        bucket_key="invoices",
                        file_key=new_s3_object_key,
                        content=encrypted_pdf_payload,
                        content_type="application/octet-stream",
                    )
                    if not upload_result.get("url"):
                        record["status"] = "blocked"
                        record["errors"].append("failed to upload repaired encrypted S3 PDF")
                        findings.append(record)
                        blocked += 1
                        continue

                    update_result = await directus.update_item(
                        "invoices",
                        str(invoice["id"]),
                        {
                            "date": original_datetime.isoformat(),
                            "encrypted_filename": encrypted_corrected_filename,
                            "encrypted_s3_object_key": encrypted_new_s3_object_key,
                            "encrypted_aes_key": encrypted_aes_key,
                            "aes_nonce": aes_nonce_b64,
                        },
                        admin_required=True,
                    )
                    if not update_result:
                        record["status"] = "blocked"
                        record["errors"].append("failed to update Directus invoice date/filename")
                        findings.append(record)
                        blocked += 1
                        continue
                    record["rotated_pdf_encryption"] = True
                    record["new_s3_object_key"] = new_s3_object_key
                record["invoice_ninja"] = await apply_invoice_ninja_repair(apply=True)
                if record["invoice_ninja"].get("errors"):
                    record["status"] = "partial"
                    blocked += 1
                else:
                    record["status"] = "repaired"
                    repaired += 1
            else:
                record["invoice_ninja"] = await apply_invoice_ninja_repair(apply=False)
                record["status"] = "would_repair"
            findings.append(record)

        print(json.dumps({
            "dry_run": not args.apply_date_repair,
            "repair_created_on": created_on.date().isoformat(),
            "scanned_directus_invoices": len(directus_rows),
            "would_repair": sum(1 for item in findings if item.get("status") == "would_repair"),
            "repaired": repaired,
            "blocked": blocked,
            "findings": findings,
        }, indent=2, sort_keys=True))
        return 1 if blocked else 0
    finally:
        if ninja:
            await ninja.close()
        await directus.close()
        await secrets.aclose()


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
    s3 = None

    try:
        stripe.api_key = await _stripe_api_key(secrets)
        if check_invoice_ninja:
            ninja = await InvoiceNinjaService.create(secrets)
        if args.apply_invoice_ninja_backfill:
            s3 = S3UploadService(secrets)
            await s3.initialize()
        sender = await _sender_details(secrets)
        scanned = missing_directus = missing_invoice_ninja = dispatched = skipped = 0
        invoice_ninja_backfilled = invoice_ninja_backfill_blocked = 0
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
            invoice_datetime = _stripe_invoice_datetime(payment_intent)
            invoice_date = invoice_datetime.date().isoformat()

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
                "invoice_date": invoice_date,
                "invoice_datetime": invoice_datetime.isoformat(),
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
            selected_order_ids = set(args.order_id or [])
            bank_transfer_from_date = from_date or (datetime.now(timezone.utc) - timedelta(days=args.days))
            missing_bank_transfer_invoices: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for invoice in await _iter_bank_transfer_invoice_rows(directus, bank_transfer_from_date, to_date):
                order_id = str(invoice.get("order_id") or invoice.get("provider_order_id") or "")
                if not order_id:
                    continue
                if selected_order_ids and order_id not in selected_order_ids:
                    continue
                invoice_ninja_present = await _ninja_invoice_exists(ninja, order_id) if ninja else None
                if invoice_ninja_present is not False:
                    continue
                missing_invoice_ninja += 1
                record = {
                    "source": "directus_bank_transfer_invoice",
                    "order_id": order_id,
                    "directus_invoice_id": invoice.get("id"),
                    "directus_present": True,
                    "invoice_ninja_present": invoice_ninja_present,
                    "provider": invoice.get("provider"),
                    "date": invoice.get("date"),
                    "apply_action": (
                        "create_invoice_ninja_rows"
                        if args.apply_invoice_ninja_backfill
                        else "none_requires_invoice_ninja_backfill"
                    ),
                }
                findings.append(record)
                missing_bank_transfer_invoices.append((invoice, record))

            if missing_bank_transfer_invoices:
                users_by_hash = await _directus_users_by_hash(
                    directus,
                    {str(invoice.get("user_id_hash") or "") for invoice, _ in missing_bank_transfer_invoices},
                )
                for invoice, record in missing_bank_transfer_invoices:
                    user_hash = str(invoice.get("user_id_hash") or "")
                    backfill_result = await _backfill_invoice_ninja_from_directus_invoice(
                        ninja=ninja,
                        s3=s3,
                        encryption=encryption,
                        invoice=invoice,
                        user=users_by_hash.get(user_hash),
                        apply=args.apply_invoice_ninja_backfill,
                    )
                    record["invoice_ninja_backfill"] = backfill_result
                    if backfill_result.get("status") == "created":
                        invoice_ninja_backfilled += 1
                    elif backfill_result.get("status") == "blocked":
                        invoice_ninja_backfill_blocked += 1

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
                                "invoice_date": item["invoice_datetime"],
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
            "invoice_ninja_backfilled": invoice_ninja_backfilled,
            "invoice_ninja_backfill_blocked": invoice_ninja_backfill_blocked,
            "findings": findings,
        }, indent=2, sort_keys=True))
        if args.apply and dispatched == 0 and any(item.get("apply_action") == "dispatch_no_email_invoice_task" for item in findings):
            return 1
        if args.apply and any(item.get("apply_action") not in ("dispatch_no_email_invoice_task", "none_directus_present") for item in findings):
            return 1
        if args.apply_invoice_ninja_backfill and invoice_ninja_backfill_blocked:
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
    parser.add_argument("--order-id", action="append", default=[], help="Specific Directus order_id/provider_order_id to inspect for Invoice Ninja-only backfill; repeatable")
    parser.add_argument("--check-invoice-ninja", action="store_true", help="Also report whether audited orders exist in Invoice Ninja")
    parser.add_argument("--include-bank-transfers", action="store_true", help="Also audit Directus bank-transfer invoices for missing Invoice Ninja rows")
    parser.add_argument("--apply", action="store_true", help="Dispatch no-email invoice backfill tasks for mapped missing invoices")
    parser.add_argument("--apply-invoice-ninja-backfill", action="store_true", help="Create missing Invoice Ninja rows for Directus-present bank-transfer invoices")
    parser.add_argument("--repair-created-on", help="Repair historical invoice dates for direct-Stripe invoices created on this bad processing date")
    parser.add_argument("--apply-date-repair", action="store_true", help="Apply --repair-created-on date/PDF/metadata repairs; dry-run by default")
    parser.add_argument(
        "--recreate-locked-invoice-ninja",
        action="store_true",
        help="For locked Invoice Ninja invoices, delete matched old invoice/payment/bank rows and recreate them with original dates",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable INFO logging")
    args = parser.parse_args()
    if args.repair_created_on:
        if args.apply:
            raise SystemExit("--repair-created-on cannot be combined with --apply")
        return asyncio.run(_repair_backfilled_invoice_dates(args))
    if args.apply_date_repair:
        raise SystemExit("--apply-date-repair requires --repair-created-on")
    if args.recreate_locked_invoice_ninja:
        raise SystemExit("--recreate-locked-invoice-ninja requires --repair-created-on")
    if args.apply and args.apply_invoice_ninja_backfill:
        raise SystemExit("--apply-invoice-ninja-backfill cannot be combined with --apply")
    if args.apply_invoice_ninja_backfill and not args.include_bank_transfers:
        raise SystemExit("--apply-invoice-ninja-backfill requires --include-bank-transfers")
    if args.order_id and not args.include_bank_transfers:
        raise SystemExit("--order-id requires --include-bank-transfers")
    return asyncio.run(_audit(args))


if __name__ == "__main__":
    raise SystemExit(main())
