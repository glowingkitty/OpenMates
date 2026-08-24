#!/usr/bin/env python3
# contract-test-file: infrastructure
"""
Exercise personal billing settlement through the real internal dev API.

The script runs inside the API container, receives a test account through JSON,
and verifies concurrent distinct charges, exact replay, durable identities/raw
usage, and idempotent refunds. It never prints account identifiers or secrets.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
for import_path in (str(PROJECT_ROOT), "/app", "/app/backend"):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from backend.core.api.app.services.cache import CacheService  # noqa: E402
from backend.core.api.app.services.directus.directus import DirectusService  # noqa: E402
from backend.core.api.app.utils.encryption import EncryptionService  # noqa: E402


def _read_account(raw_value: str | None) -> dict[str, str]:
    if raw_value is None:
        for key in ("OPENMATES_TEST_ACCOUNT_1_EMAIL", "OPENMATES_TEST_ACCOUNT_EMAIL"):
            email = os.getenv(key, "").strip()
            if email:
                return {"email": email, "user_id": ""}
        raise ValueError("accounts JSON or a configured test-account email is required")
    raw_json = sys.stdin.read() if raw_value == "-" else raw_value
    accounts = json.loads(raw_json)
    if not isinstance(accounts, list) or not accounts or not isinstance(accounts[0], dict):
        raise ValueError("accounts JSON must contain at least one account object")
    account = accounts[0]
    email = str(account.get("email") or "").strip()
    user_id = str(account.get("user_id") or "").strip()
    if not email and not user_id:
        raise ValueError("the first account requires email or user_id")
    return {"email": email, "user_id": user_id}


def _hashed_email(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).digest()
    return base64.b64encode(digest).decode("utf-8")


async def _authoritative_balance(
    directus: DirectusService,
    encryption: EncryptionService,
    user_id: str,
) -> int:
    rows = await directus.get_items(
        "directus_users",
        params={
            "filter": {"id": {"_eq": user_id}},
            "fields": "id,vault_key_id,encrypted_credit_balance",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not rows:
        raise RuntimeError("billing test account profile was not found")
    plaintext = await encryption.decrypt_with_user_key(
        rows[0]["encrypted_credit_balance"],
        rows[0]["vault_key_id"],
    )
    if plaintext is None:
        raise RuntimeError("billing test account balance could not be decrypted")
    return int(plaintext)


async def run(args: argparse.Namespace) -> int:
    internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not internal_token:
        raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required")

    account = _read_account(args.accounts_json)
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    try:
        user_id = account["user_id"]
        if not user_id:
            found, user, message = await directus.get_user_by_hashed_email(_hashed_email(account["email"]))
            if not found or not user:
                raise RuntimeError(f"billing test account lookup failed: {message}")
            user_id = str(user["id"])

        user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        balance_before = await _authoritative_balance(directus, encryption, user_id)
        run_id = uuid.uuid4().hex
        charge_ids = [f"billing-contract:{run_id}:{index}" for index in range(args.concurrency)]
        charge_payloads = [
            {
                "user_id": user_id,
                "user_id_hash": user_id_hash,
                "credits": 1,
                "app_id": "system",
                "skill_id": "billing_contract",
                "idempotency_key": charge_id,
                "usage_details": {"source": "billing_contract"},
            }
            for charge_id in charge_ids
        ]
        headers = {"X-Internal-Service-Token": internal_token}
        charge_url = f"{args.api_url.rstrip('/')}/internal/billing/charge"
        refund_url = f"{args.api_url.rstrip('/')}/internal/billing/refund"
        # The API container inherits outbound proxy variables that cannot
        # hairpin the local dev domain; bypass them while still exercising the
        # public HTTPS route through Caddy.
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            responses = await asyncio.gather(
                *(client.post(charge_url, json=payload, headers=headers) for payload in charge_payloads)
            )
            for response in responses:
                response.raise_for_status()
                body = response.json()
                if body.get("status") != "success" or body.get("idempotent"):
                    raise RuntimeError("a distinct concurrent charge did not commit exactly once")

            replay_responses = await asyncio.gather(
                *(client.post(charge_url, json=payload, headers=headers) for payload in charge_payloads)
            )
            for response in replay_responses:
                response.raise_for_status()
                if not response.json().get("idempotent"):
                    raise RuntimeError("charge replay was not reported as idempotent")

            identity_rows = await directus.get_items(
                "billing_charge_identities",
                params={"filter": {"charge_id": {"_in": charge_ids}}, "fields": "charge_id", "limit": -1},
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            usage_rows = await directus.get_items(
                "usage",
                params={"filter": {"charge_id": {"_in": charge_ids}}, "fields": "charge_id", "limit": -1},
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            if len(identity_rows) != len(charge_ids) or len(usage_rows) != len(charge_ids):
                raise RuntimeError("durable charge identity or raw usage count did not match")

            refund_payloads = [
                {
                    "user_id": user_id,
                    "user_id_hash": user_id_hash,
                    "credits": 1,
                    "app_id": "system",
                    "skill_id": "billing_contract",
                    "idempotency_key": f"{charge_id}:refund",
                    "reason": "Billing settlement contract cleanup",
                }
                for charge_id in charge_ids
            ]
            for payload in refund_payloads:
                response = await client.post(refund_url, json=payload, headers=headers)
                response.raise_for_status()
                replay = await client.post(refund_url, json=payload, headers=headers)
                replay.raise_for_status()

        balance_after = await _authoritative_balance(directus, encryption, user_id)
        if balance_after != balance_before:
            raise RuntimeError("idempotent cleanup refunds did not restore the starting balance")
        print(
            f"billing_settlement_contract=passed concurrent_charges={len(charge_ids)} "
            f"identities={len(identity_rows)} usage_rows={len(usage_rows)} balance_restored=true"
        )
        return 0
    finally:
        await directus.close()
        await cache.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify real dev billing settlement behavior")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--accounts-json", help="JSON list or '-' for stdin; defaults to configured test account")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    if args.concurrency < 2 or args.concurrency > 10:
        parser.error("--concurrency must be between 2 and 10")
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
