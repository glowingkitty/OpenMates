#!/usr/bin/env python3
"""
Manual bank transfer approval for OpenMates credit purchases.

This is an operator-only script for the current non-automated SEPA flow: an
admin confirms that money arrived, then this script grants the credits for the
matching pending OpenMates order. It deliberately does not call Revolut and does
not simulate a Revolut webhook, so no Revolut webhook secret is required.

Run inside the API container:
    docker exec api python /app/backend/scripts/approve_bank_transfer.py \
      --reference OM-2026-ABCD1234 --received-cents 5000 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if "/app" not in sys.path:
    sys.path.insert(0, "/app")
if "/app/backend" not in sys.path:
    sys.path.insert(0, "/app/backend")


from backend.core.api.app.services.cache import CacheService  # noqa: E402
from backend.core.api.app.services.compliance import ComplianceService  # noqa: E402
from backend.core.api.app.services.directus.directus import DirectusService  # noqa: E402
from backend.core.api.app.utils.encryption import EncryptionService  # noqa: E402
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402


logger = logging.getLogger("approve_bank_transfer")

AMOUNT_TOLERANCE_CENTS = 50
PAID_SIGNUP_COMPLETION_LAST_OPENED = "/chat/new"
PENDING_BANK_TRANSFERS_COLLECTION = "pending_bank_transfers"
INVOICE_SENDER_SECRET_PATH = "kv/data/providers/invoice_sender"
PURCHASE_CONFIRMATION_TASK = (
    "app.tasks.email_tasks.purchase_confirmation_email_task."
    "process_invoice_and_send_email"
)


class ApprovalError(Exception):
    """Expected operator-facing failure while approving a bank transfer."""


def _paid_signup_completion_update_payload(**extra_fields: Any) -> dict[str, Any]:
    return {
        **extra_fields,
        "last_opened": PAID_SIGNUP_COMPLETION_LAST_OPENED,
        "signup_completed": True,
    }


async def _fetch_order(directus: DirectusService, reference: str) -> dict[str, Any]:
    rows = await directus.get_items(
        PENDING_BANK_TRANSFERS_COLLECTION,
        params={
            "filter[reference][_eq]": reference,
            "limit": 1,
        },
        no_cache=True,
    )
    if not rows:
        raise ApprovalError(f"No bank transfer order found for reference '{reference}'.")
    return rows[0]


async def _update_order(
    directus: DirectusService,
    item_id: str,
    data: dict[str, Any],
) -> None:
    updated = await directus.update_item(PENDING_BANK_TRANSFERS_COLLECTION, item_id, data)
    if not updated:
        raise ApprovalError(f"Failed to update bank transfer Directus item {item_id}.")


async def _get_user_profile(
    directus: DirectusService,
    cache: CacheService,
    user_id: str,
) -> dict[str, Any]:
    cached_user = await cache.get_user_by_id(user_id)
    if (
        isinstance(cached_user, dict)
        and cached_user.get("vault_key_id")
        and isinstance(cached_user.get("credits"), int)
    ):
        return cached_user

    success, profile, message = await directus.get_user_profile(user_id)
    if not success or not profile:
        raise ApprovalError(f"Could not load user profile {user_id}: {message}")
    if not profile.get("vault_key_id"):
        raise ApprovalError(f"User {user_id} has no vault_key_id.")
    if not isinstance(profile.get("credits"), int):
        raise ApprovalError(f"User {user_id} has no integer credit balance.")
    return profile


async def _sender_details(secrets: SecretsManager) -> dict[str, str]:
    async def get(key: str) -> str:
        value = await secrets.get_secret(
            secret_path=INVOICE_SENDER_SECRET_PATH,
            secret_key=key,
        )
        return value or ""

    return {
        "sender_addressline1": await get("addressline1"),
        "sender_addressline2": await get("addressline2"),
        "sender_addressline3": await get("addressline3"),
        "sender_country": await get("country"),
        "sender_email": await get("email") or "support@openmates.org",
        "sender_vat": await get("vat"),
    }


def _print_order(order: dict[str, Any], received_cents: int) -> None:
    print("\nBank transfer order")
    print(f"  Directus ID: {order.get('id')}")
    print(f"  Order ID:    {order.get('order_id')}")
    print(f"  Reference:   {order.get('reference')}")
    print(f"  Status:      {order.get('status')}")
    print(f"  Type:        {order.get('order_type', 'credit_purchase')}")
    print(f"  User ID:     {order.get('user_id')}")
    print(f"  Expected:    €{int(order.get('amount_expected_cents') or 0) / 100:.2f}")
    print(f"  Received:    €{received_cents / 100:.2f}")
    print(f"  Credits:     {order.get('credits_amount')}")


async def approve(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    secrets = SecretsManager()
    await secrets.initialize()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)

    try:
        order = await _fetch_order(directus, args.reference)
        _print_order(order, args.received_cents)

        item_id = order.get("id")
        order_id = order.get("order_id")
        reference = order.get("reference")
        status = order.get("status")
        user_id = order.get("user_id")
        order_type = order.get("order_type", "credit_purchase")
        expected_cents = int(order.get("amount_expected_cents") or 0)
        credits_amount = int(order.get("credits_amount") or 0)

        if not item_id or not order_id or not reference:
            raise ApprovalError("Bank transfer order is missing id/order_id/reference.")
        if order_type != "credit_purchase":
            raise ApprovalError(
                f"Order {order_id} is '{order_type}', not a credit purchase. "
                "This script only grants user credits."
            )
        if status == "completed":
            print("\nAlready completed. No credits granted.")
            return 0
        if status != "pending":
            raise ApprovalError(f"Order {order_id} has status '{status}', expected 'pending'.")
        if not user_id:
            raise ApprovalError(f"Order {order_id} has no user_id.")
        if credits_amount <= 0:
            raise ApprovalError(f"Order {order_id} has invalid credits_amount={credits_amount}.")

        diff = args.received_cents - expected_cents
        if abs(diff) > AMOUNT_TOLERANCE_CENTS and not args.allow_amount_mismatch:
            raise ApprovalError(
                "Amount mismatch exceeds ±€0.50 tolerance: "
                f"expected €{expected_cents / 100:.2f}, "
                f"received €{args.received_cents / 100:.2f}. "
                "Use --allow-amount-mismatch only after manual review."
            )

        user_profile = await _get_user_profile(directus, cache, user_id)
        current_credits = int(user_profile["credits"])
        vault_key_id = user_profile["vault_key_id"]
        new_total_credits = current_credits + credits_amount

        print("\nCredit change")
        print(f"  Current:     {current_credits}")
        print(f"  Add:         {credits_amount}")
        print(f"  New total:   {new_total_credits}")

        if not args.apply:
            print("\nDry run only. Re-run with --apply to approve and grant credits.")
            return 0

        completed_at = datetime.now(timezone.utc).isoformat()
        encrypted_credits, _ = await encryption.encrypt_with_user_key(
            str(new_total_credits),
            vault_key_id,
        )

        user_update = _paid_signup_completion_update_payload(
            encrypted_credit_balance=encrypted_credits,
        )
        if not await directus.update_user(user_id, user_update):
            raise ApprovalError(f"Failed to update encrypted credits for user {user_id}.")

        order_update = {
            "status": "completed",
            "completed_at": completed_at,
            "received_amount_cents": args.received_cents,
            "admin_note": "Manually approved via approve_bank_transfer.py",
        }
        if args.bank_transaction_id:
            order_update["revolut_transaction_id"] = args.bank_transaction_id
        await _update_order(directus, item_id, order_update)

        await cache.update_bank_transfer_status(
            order_id=order_id,
            reference=reference,
            status="completed",
            extra_fields={
                "completed_at": completed_at,
                "received_amount_cents": args.received_cents,
            },
        )

        user_profile["credits"] = new_total_credits
        user_profile["last_opened"] = PAID_SIGNUP_COMPLETION_LAST_OPENED
        user_profile["signup_completed"] = True
        user_profile.pop("payment_in_progress_timestamp", None)
        user_profile["payment_in_progress"] = False
        if user_profile.get("pending_order_id") == order_id:
            user_profile.pop("pending_order_id", None)
        await cache.set_user(user_profile, user_id=user_id)

        await cache.increment_stat("income_eur_cents", args.received_cents)
        await cache.increment_stat("credits_sold", credits_amount)
        await cache.update_liability(credits_amount)
        await cache.increment_stat("purchase_count")
        await cache.increment_json_stat("purchases_by_provider", "bank_transfer_manual")

        if not args.no_email:
            from backend.core.api.app.tasks.celery_config import app as celery_app

            sender = await _sender_details(secrets)
            celery_app.send_task(
                name=PURCHASE_CONFIRMATION_TASK,
                kwargs={
                    "order_id": order_id,
                    "user_id": user_id,
                    "credits_purchased": credits_amount,
                    **sender,
                    "email_encryption_key": order.get("email_encryption_key"),
                    "is_gift_card": False,
                    "is_auto_topup": False,
                    "provider": "bank_transfer",
                },
                queue="email",
            )

        ComplianceService.log_financial_transaction(
            user_id=user_id,
            transaction_type="credit_purchase",
            amount=credits_amount,
            currency="eur",
            status="success",
            details={
                "order_id": order_id,
                "provider": "bank_transfer_manual",
                "previous_credits": current_credits,
                "new_credits": new_total_credits,
                "received_amount_cents": args.received_cents,
                "bank_transaction_id": args.bank_transaction_id,
            },
        )

        print("\nApproved. Credits granted and bank transfer marked completed.")
        if args.no_email:
            print("Confirmation email skipped because --no-email was provided.")
        else:
            print("Confirmation email task queued.")
        return 0

    except ApprovalError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    finally:
        await directus.close()
        await cache.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually approve a pending bank transfer credit purchase.",
    )
    parser.add_argument("--reference", required=True, help="Payment reference, e.g. OM-2026-ABCD1234")
    parser.add_argument("--received-cents", required=True, type=int, help="Amount received in cents, e.g. 5000 for €50.00")
    parser.add_argument("--bank-transaction-id", help="Optional bank/Revolut transaction ID for audit trail")
    parser.add_argument("--allow-amount-mismatch", action="store_true", help="Approve even when outside the ±€0.50 tolerance")
    parser.add_argument("--no-email", action="store_true", help="Do not queue the purchase confirmation email")
    parser.add_argument("--apply", action="store_true", help="Actually grant credits and complete the order")
    parser.add_argument("--verbose", action="store_true", help="Enable info logging")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(approve(parse_args())))
