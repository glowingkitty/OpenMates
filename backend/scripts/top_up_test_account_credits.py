#!/usr/bin/env python3
"""
Top up configured Playwright test account credits.

This operator-only script runs inside the API container so it can reuse the app's
Directus, Redis cache, and Vault encryption services. It accepts account emails
over stdin as JSON and never prints those emails back to logs.

Usage:
    docker exec -i api python /app/backend/scripts/top_up_test_account_credits.py \
      --accounts-json - --minimum 20000 --target 50000
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


try:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
except IndexError:
    PROJECT_ROOT = Path("/app")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if "/app" not in sys.path:
    sys.path.insert(0, "/app")
if "/app/backend" not in sys.path:
    sys.path.insert(0, "/app/backend")


from backend.core.api.app.services.cache import CacheService  # noqa: E402
from backend.core.api.app.services.directus.directus import DirectusService  # noqa: E402
from backend.core.api.app.utils.encryption import EncryptionService  # noqa: E402


def _hash_email_sha256(email: str) -> str:
    email_bytes = email.strip().lower().encode("utf-8")
    return base64.b64encode(hashlib.sha256(email_bytes).digest()).decode("utf-8")


def _read_accounts(raw_value: str) -> list[dict[str, Any]]:
    raw_json = sys.stdin.read() if raw_value == "-" else raw_value
    data = json.loads(raw_json)
    if not isinstance(data, list):
        raise ValueError("accounts JSON must be a list")
    accounts: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each account entry must be an object")
        email = str(item.get("email") or "").strip()
        if not email:
            continue
        slot = item.get("slot")
        accounts.append({"slot": slot, "email": email})
    return accounts


def _dedupe_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_email: dict[str, dict[str, Any]] = {}
    for account in accounts:
        normalized_email = account["email"].strip().lower()
        existing = by_email.setdefault(
            normalized_email,
            {"email": account["email"], "slots": []},
        )
        slot = account.get("slot")
        if slot is not None and slot not in existing["slots"]:
            existing["slots"].append(slot)
    return sorted(
        by_email.values(),
        key=lambda item: min(item["slots"] or [999]),
    )


async def top_up(args: argparse.Namespace) -> int:
    accounts = _dedupe_accounts(_read_accounts(args.accounts_json))
    if not accounts:
        print("No configured test accounts found to inspect.")
        return 0

    cache = CacheService()
    encryption = EncryptionService()
    directus = DirectusService(cache_service=cache, encryption_service=encryption)

    updated: list[tuple[list[Any], int, int]] = []
    already_ok: list[tuple[list[Any], int]] = []
    failed: list[tuple[list[Any], str]] = []

    try:
        for account in accounts:
            slots = account["slots"]
            hashed_email = _hash_email_sha256(account["email"])
            success, user, message = await directus.get_user_by_hashed_email(hashed_email)
            if not success or not user:
                failed.append((slots, f"user_lookup_failed:{message}"))
                continue

            user_id = user.get("id")
            success, profile, message = await directus.get_user_profile(user_id)
            if not success or not profile:
                failed.append((slots, f"profile_failed:{message}"))
                continue

            current_credits = profile.get("credits")
            vault_key_id = profile.get("vault_key_id")
            if not vault_key_id or not isinstance(current_credits, int):
                failed.append((slots, "missing_vault_key_or_integer_credits"))
                continue

            if current_credits >= args.minimum:
                already_ok.append((slots, current_credits))
                continue

            new_total = max(args.target, current_credits)
            if args.dry_run:
                updated.append((slots, current_credits, new_total))
                continue

            encrypted_credits, _ = await encryption.encrypt_with_user_key(str(new_total), vault_key_id)
            if not await directus.update_user(user_id, {"encrypted_credit_balance": encrypted_credits}):
                failed.append((slots, "directus_update_failed"))
                continue

            profile["credits"] = new_total
            await cache.set_user(profile, user_id=user_id)
            updated.append((slots, current_credits, new_total))
    finally:
        await directus.close()
        await cache.close()

    print(f"accounts_checked={len(accounts)}")
    for slots, before, after in updated:
        slot_label = ",".join(str(slot) for slot in slots) or "unknown"
        action = "would_update" if args.dry_run else "updated"
        print(f"{action} slots={slot_label} before={before} after={after}")
    for slots, credits in already_ok:
        slot_label = ",".join(str(slot) for slot in slots) or "unknown"
        print(f"ok slots={slot_label} credits={credits}")
    for slots, reason in failed:
        slot_label = ",".join(str(slot) for slot in slots) or "unknown"
        print(f"failed slots={slot_label} reason={reason}")

    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Top up configured E2E test account credits")
    parser.add_argument("--accounts-json", required=True, help="JSON array or '-' to read from stdin")
    parser.add_argument("--minimum", type=int, default=20_000, help="Top up accounts below this balance")
    parser.add_argument("--target", type=int, default=50_000, help="Target balance for low accounts")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without updating balances")
    args = parser.parse_args()
    if args.minimum < 0:
        parser.error("--minimum must be >= 0")
    if args.target < args.minimum:
        parser.error("--target must be >= --minimum")
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(top_up(parse_args())))
