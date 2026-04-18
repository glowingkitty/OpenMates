#!/usr/bin/env python3
"""
Apply Bank Transfer — Manual trigger for incoming SEPA transfer processing.

Looks up a pending bank transfer by reference in Directus, then simulates the
Revolut Business TransactionCreated webhook event by posting a signed payload
to the local API. This triggers the exact same code path as a real Revolut
webhook: credits are applied and a confirmation email is sent.

Usage:
    python3 scripts/apply_bank_transfer.py --reference OM-2024-ABCD1234

    # Dry run — show the payload without sending
    python3 scripts/apply_bank_transfer.py --reference OM-2024-ABCD1234 --dry-run

Prerequisites:
    - Run on the production server (posts to localhost:8000).
    - The pending_bank_transfers record for this reference must exist in Directus.
    - DIRECTUS_TOKEN and SECRET__REVOLUT_BUSINESS__PRODUCTION_WEBHOOK_SECRET
      must be set in .env.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: requests\nInstall with: pip install requests")
    sys.exit(1)


# ────────────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────────────

WEBHOOK_URL = "http://localhost:8000/v1/payments/webhook"
DIRECTUS_URL = "http://localhost:8055"
WEBHOOK_SECRET_ENV_KEY = "SECRET__REVOLUT_BUSINESS__PRODUCTION_WEBHOOK_SECRET"


# ────────────────────────────────────────────────────────────────────
# .env loader (minimal — avoids requiring python-dotenv)
# ────────────────────────────────────────────────────────────────────

def load_env_file() -> dict:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return {}
    result = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


# ────────────────────────────────────────────────────────────────────
# Directus lookup
# ────────────────────────────────────────────────────────────────────

def fetch_pending_order(reference: str, directus_token: str) -> dict:
    """Look up a pending bank transfer by reference from Directus."""
    response = requests.get(
        f"{DIRECTUS_URL}/items/pending_bank_transfers",
        params={
            "filter[reference][_eq]": reference,
            "filter[status][_eq]": "pending",
            "limit": 1,
        },
        headers={"Authorization": f"Bearer {directus_token}"},
        timeout=10,
    )
    if response.status_code != 200:
        print(f"\n  Error: Directus query failed ({response.status_code}): {response.text}")
        sys.exit(1)

    items = response.json().get("data", [])
    if not items:
        print(f"\n  Error: No pending bank transfer found for reference '{reference}'.")
        print("  Check that the user completed checkout and selected bank transfer as payment method.")
        sys.exit(1)

    return items[0]


# ────────────────────────────────────────────────────────────────────
# Signature
# ────────────────────────────────────────────────────────────────────

def sign_payload(raw_body: str, timestamp_ms: int, secret: str) -> str:
    """
    Compute Revolut Business webhook HMAC-SHA256 signature.

    Algorithm (matches RevolutBusinessService.verify_and_parse_webhook):
        payload_to_sign = f"v1.{timestamp_ms}.{raw_body}"
        signature = "v1=" + hmac_sha256(secret, payload_to_sign).hexdigest()
    """
    payload_to_sign = f"v1.{timestamp_ms}.{raw_body}"
    digest = hmac.new(
        secret.encode("utf-8"),
        payload_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"v1={digest}"


# ────────────────────────────────────────────────────────────────────
# Payload builder
# ────────────────────────────────────────────────────────────────────

def build_payload(reference: str, amount_cents: int) -> dict:
    """
    Build a Revolut Business TransactionCreated event payload.

    parse_incoming_transfer() expects:
      - event: "TransactionCreated"
      - data.reference: the payment reference
      - data.legs[0].amount: positive float in EUR (incoming money)
      - data.legs[0].currency: "EUR"
    """
    amount_eur = amount_cents / 100
    return {
        "event": "TransactionCreated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "id": str(uuid.uuid4()),
            "state": "completed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "reference": reference,
            "type": "transfer",
            "legs": [
                {
                    "id": str(uuid.uuid4()),
                    "amount": amount_eur,
                    "currency": "EUR",
                    "description": reference,
                    "counterparty": {
                        "name": "Manual bank transfer trigger",
                        "account_type": "external",
                    },
                }
            ],
        },
    }


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manually trigger bank transfer processing (credits + confirmation email)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--reference", required=True,
        help="Payment reference (e.g. OM-2024-ABCD1234)",
    )
    parser.add_argument(
        "--received-cents", type=int, required=True,
        help="Amount actually received in cents as shown in Revolut (e.g. 5000 for €50.00)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the payload and headers without sending the request",
    )
    args = parser.parse_args()

    env_vars = load_env_file()

    # Load webhook secret
    webhook_secret = env_vars.get(WEBHOOK_SECRET_ENV_KEY) or os.environ.get(WEBHOOK_SECRET_ENV_KEY)
    if not webhook_secret:
        print(f"\n  Error: {WEBHOOK_SECRET_ENV_KEY} not set in .env.")
        print("  Run: python3 scripts/revolut_business_setup.py --env production --write-env")
        sys.exit(1)

    # Load Directus token
    directus_token = env_vars.get("DIRECTUS_TOKEN") or os.environ.get("DIRECTUS_TOKEN")
    if not directus_token:
        print("\n  Error: DIRECTUS_TOKEN not set in .env.")
        sys.exit(1)

    # Fetch the pending order
    print(f"\n  Looking up reference '{args.reference}' in Directus...")
    order = fetch_pending_order(args.reference, directus_token)

    order_id = order.get("order_id", order.get("id", "?"))
    amount_cents = order.get("amount_expected_cents", 0)
    credits = order.get("credits_amount", "?")
    order_type = order.get("order_type", "credit_purchase")

    print(f"  ✓ Found order {order_id}")
    print(f"    Expected: €{amount_cents / 100:.2f}")
    print(f"    Received: €{args.received_cents / 100:.2f}")
    print(f"    Credits:  {credits}")
    print(f"    Type:     {order_type}")

    # Amount check — same ±€0.50 tolerance as the webhook handler
    TOLERANCE_CENTS = 50
    if abs(args.received_cents - amount_cents) > TOLERANCE_CENTS:
        diff = (args.received_cents - amount_cents) / 100
        print("\n  ✗ Amount mismatch:")
        print(f"      Expected: €{amount_cents / 100:.2f}")
        print(f"      Received: €{args.received_cents / 100:.2f}")
        print(f"      Diff:     {'+' if diff > 0 else ''}{diff:.2f} EUR")
        print("\n  Did the user send the wrong amount? Check your Revolut app and retry.")
        sys.exit(1)

    # Build and sign payload using the actually received amount
    payload = build_payload(args.reference, args.received_cents)
    raw_body = json.dumps(payload, separators=(",", ":"))
    timestamp_ms = int(time.time() * 1000)
    signature = sign_payload(raw_body, timestamp_ms, webhook_secret)

    headers = {
        "Content-Type": "application/json",
        "Revolut-Request-Timestamp": str(timestamp_ms),
        "Revolut-Signature": signature,
    }

    if args.dry_run:
        print("\n── Payload ──────────────────────────────────────────────────────────")
        print(json.dumps(payload, indent=2))
        print("\n── Headers ──────────────────────────────────────────────────────────")
        for k, v in headers.items():
            print(f"  {k}: {v}")
        print("\n  (not sent — remove --dry-run to send)")
        return

    print(f"\n  Sending to {WEBHOOK_URL}...")
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=raw_body,
            headers=headers,
            timeout=30,
        )
    except requests.ConnectionError:
        print(f"\n  Error: could not connect to {WEBHOOK_URL}")
        print("  Is the API running? Try: docker compose ps api")
        sys.exit(1)

    print(f"  Status: {response.status_code}")

    try:
        body = response.json()
        status = body.get("status", "")
        print(f"  Response: {json.dumps(body)}")
    except Exception:
        status = ""
        print(f"  Response: {response.text}")

    if response.status_code == 200:
        if status == "completed":
            print("\n  ✓ Done — credits applied and confirmation email sent.")
        elif status == "already_completed":
            print("\n  ⚠  Order already completed — no duplicate credits granted.")
        elif status == "amount_mismatch_flagged":
            print("\n  ⚠  Amount mismatch flagged — check admin email.")
        elif status == "unmatched_transfer_flagged":
            print("\n  ⚠  Reference not matched — check admin email.")
        else:
            print(f"\n  Status: {status}")
    else:
        print(f"\n  ✗ Request failed ({response.status_code})")
        sys.exit(1)


if __name__ == "__main__":
    main()
