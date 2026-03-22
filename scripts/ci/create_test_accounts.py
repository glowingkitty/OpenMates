#!/usr/bin/env python3
"""
scripts/ci/create_test_accounts.py

Creates test accounts for E2E Playwright tests.
Must be run inside the API Docker container (docker exec api python ...).

Usage:
    docker exec api python /app/scripts/ci/create_test_accounts.py --start 5 --end 10

    # Also set GitHub secrets and append to .env
    docker exec api python /app/scripts/ci/create_test_accounts.py --start 5 --end 10 --json \
      | python3 scripts/ci/set_test_account_secrets.py
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
import time
import pyotp


async def create_account(slot: int) -> dict:
    """Create a test account using internal services."""
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.utils.encryption import EncryptionService

    cache = CacheService()
    ds = DirectusService(cache_service=cache)
    enc = EncryptionService()

    email = f"testacct{slot}@test.openmates.org"
    username = f"Test Account {slot}"
    password = f"TestAcct!2026pw{slot}"

    # Hash email for lookup
    hashed_email = base64.b64encode(
        hashlib.sha256(email.lower().strip().encode("utf-8")).digest()
    ).decode("utf-8")

    # Generate 2FA secret
    otp_secret = pyotp.random_base32()

    print(f"Creating account {slot}: {email}", file=sys.stderr)

    # Create user via DirectusService
    success, user_data, msg = await ds.create_user(
        username=username,
        hashed_email=hashed_email,
        language="en",
        darkmode=False,
    )

    if not success:
        raise RuntimeError(f"Failed to create user: {msg}")

    user_id = user_data["id"]
    print(f"  Created user {user_id}", file=sys.stderr)

    # Set password hash directly in Directus
    import argon2
    ph = argon2.PasswordHasher()
    password_hash = ph.hash(password)

    await ds.update_user(user_id, {
        "password_hash": password_hash,
        "signup_completed": True,
        "tfa_enabled": True,
        "tfa_secret": otp_secret,
    })

    print(f"  Password and 2FA configured", file=sys.stderr)

    return {
        "slot": slot,
        "email": email,
        "password": password,
        "otp_key": otp_secret,
        "user_id": user_id,
    }


async def main_async(start: int, end: int) -> list:
    accounts = []
    for slot in range(start, end + 1):
        try:
            acct = await create_account(slot)
            accounts.append(acct)
        except Exception as e:
            print(f"  Failed account {slot}: {e}", file=sys.stderr)
    return accounts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    accounts = asyncio.run(main_async(args.start, args.end))

    if args.json:
        print(json.dumps(accounts, indent=2))
    else:
        for acct in accounts:
            s = acct["slot"]
            print(f"\nAccount {s}:")
            print(f"  Email:    {acct['email']}")
            print(f"  Password: {acct['password']}")
            print(f"  OTP Key:  {acct['otp_key']}")
            print(f"  User ID:  {acct['user_id']}")

        print(f"\nTo set GitHub secrets:")
        for acct in accounts:
            s = acct["slot"]
            print(f'gh secret set OPENMATES_TEST_ACCOUNT_{s}_EMAIL --body "{acct["email"]}"')
            print(f'gh secret set OPENMATES_TEST_ACCOUNT_{s}_PASSWORD --body "{acct["password"]}"')
            print(f'gh secret set OPENMATES_TEST_ACCOUNT_{s}_OTP_KEY --body "{acct["otp_key"]}"')


if __name__ == "__main__":
    main()
