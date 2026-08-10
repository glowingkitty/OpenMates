#!/usr/bin/env python3
"""
Repair configured Playwright test accounts that predate account_id generation.

This operator-only helper runs inside the API container so it can reuse the
app's Directus and Dragonfly configuration. It accepts redacted account slots
plus emails/user IDs as JSON, writes a missing public billing account_id, and
evicts stale profile cache entries. It never prints raw account identifiers.
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
from backend.shared.python_utils.security_random import (  # noqa: E402
    HUMAN_CODE_ALPHABET,
    generate_random_string,
)


ACCOUNT_ID_LENGTH = 7
MAX_ACCOUNT_ID_ATTEMPTS = 20


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
        user_id = str(item.get("user_id") or "").strip()
        if not email and not user_id:
            continue
        accounts.append({"slot": item.get("slot"), "email": email, "user_id": user_id})
    return accounts


def _dedupe_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_identity: dict[str, dict[str, Any]] = {}
    for account in accounts:
        user_id = account.get("user_id", "").strip()
        normalized_email = account.get("email", "").strip().lower()
        identity = f"user:{user_id}" if user_id else f"email:{normalized_email}"
        existing = by_identity.setdefault(
            identity,
            {"email": account.get("email", ""), "user_id": user_id, "slots": []},
        )
        slot = account.get("slot")
        if slot is not None and slot not in existing["slots"]:
            existing["slots"].append(slot)

    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        slots = item["slots"] or [999]
        normalized_slots = [str(slot) for slot in slots]
        numeric_slots = [int(slot) for slot in normalized_slots if slot.isdigit()]
        return (min(numeric_slots or [999]), min(normalized_slots))

    return sorted(by_identity.values(), key=sort_key)


async def _generate_unique_account_id(directus: DirectusService) -> str:
    for _ in range(MAX_ACCOUNT_ID_ATTEMPTS):
        account_id = generate_random_string(ACCOUNT_ID_LENGTH, HUMAN_CODE_ALPHABET)
        existing_users = await directus.get_items(
            "directus_users",
            {
                "filter[account_id][_eq]": account_id,
                "fields": "id",
                "limit": 1,
            },
        )
        if not existing_users:
            return account_id
    raise RuntimeError("could_not_generate_unique_account_id")


async def _evict_user_caches(cache: CacheService, user_id: str) -> None:
    await cache.delete(f"{cache.USER_KEY_PREFIX}{user_id}")
    await cache.delete(f"user_profile:{user_id}")


async def repair_accounts(args: argparse.Namespace) -> int:
    accounts = _dedupe_accounts(_read_accounts(args.accounts_json))
    if not accounts:
        print("No configured test accounts found to inspect.")
        return 0

    cache = CacheService()
    encryption = EncryptionService()
    directus = DirectusService(cache_service=cache, encryption_service=encryption)

    repaired: list[list[Any]] = []
    refreshed: list[list[Any]] = []
    failed: list[tuple[list[Any], str]] = []

    try:
        for account in accounts:
            slots = account["slots"]
            user_id = account.get("user_id")
            user: dict[str, Any] | None = None

            if user_id:
                user = await directus.get_user_fields_direct(user_id, ["id", "account_id", "is_admin"])
                if not user:
                    failed.append((slots, "user_lookup_failed"))
                    continue
                user["id"] = user_id
            else:
                hashed_email = _hash_email_sha256(account["email"])
                success, user, message = await directus.get_user_by_hashed_email(hashed_email)
                if not success or not user:
                    failed.append((slots, f"user_lookup_failed:{message}"))
                    continue
                user_id = user.get("id")

            if not user_id:
                failed.append((slots, "missing_user_id"))
                continue
            if user.get("is_admin"):
                failed.append((slots, "refusing_admin_user"))
                continue

            account_id = user.get("account_id")
            if account_id:
                await _evict_user_caches(cache, user_id)
                refreshed.append(slots)
                continue

            new_account_id = await _generate_unique_account_id(directus)
            if args.dry_run:
                repaired.append(slots)
                continue

            if not await directus.update_user(user_id, {"account_id": new_account_id}):
                failed.append((slots, "directus_update_failed"))
                continue

            await _evict_user_caches(cache, user_id)
            repaired.append(slots)
    finally:
        await directus.close()
        await cache.close()

    print(f"accounts_checked={len(accounts)}")
    for slots in repaired:
        slot_label = ",".join(str(slot) for slot in slots) or "unknown"
        action = "would_repair" if args.dry_run else "repaired"
        print(f"{action} slots={slot_label} account_id_present=true")
    for slots in refreshed:
        slot_label = ",".join(str(slot) for slot in slots) or "unknown"
        print(f"refreshed slots={slot_label} account_id_present=true")
    for slots, reason in failed:
        slot_label = ",".join(str(slot) for slot in slots) or "unknown"
        print(f"failed slots={slot_label} reason={reason}")

    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair missing account_id on configured E2E test accounts")
    parser.add_argument("--accounts-json", required=True, help="JSON array or '-' to read from stdin")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without updating account IDs")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(repair_accounts(parse_args())))
