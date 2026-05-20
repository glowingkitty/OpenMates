#!/usr/bin/env python3
"""
Reset the test account's 2FA secret to a known value.

Used to sync the server's TOTP secret with the value stored in .env / GH Actions
secrets after a credential-mutating test (e.g., backup-code-login-flow.spec.ts)
has changed it.

Usage:
  docker exec api python /app/backend/scripts/reset_test_2fa.py --from-env
  docker exec api python /app/backend/scripts/reset_test_2fa.py --from-env --slot 10
  docker exec api python /app/backend/scripts/reset_test_2fa.py --from-env --user-id <uuid>
  docker exec api python /app/backend/scripts/reset_test_2fa.py <otp_secret>
  docker exec api python /app/backend/scripts/reset_test_2fa.py <otp_secret> --user-id <uuid>

Flags:
  --from-env     Read OTP key from OPENMATES_TEST_ACCOUNT[_N]_OTP_KEY env var
  --slot N       Use numbered OPENMATES_TEST_ACCOUNT_N_* env vars
  --user-id ID   Target a specific user by Directus UUID (bypasses email lookup)

How it works:
  1. Finds the user by --user-id (preferred) or by hashed_email from env.
  2. Encrypts the given OTP secret with the user's Vault transit key.
  3. Updates encrypted_tfa_secret in Directus and clears the TFA cache.
"""

import asyncio
import argparse
import base64
import hashlib
import os
import sys
import time

sys.path.insert(0, "/app")

def _get_test_account_env(name: str, slot: int | None) -> str | None:
    if slot is not None:
        value = os.environ.get(f"OPENMATES_TEST_ACCOUNT_{slot}_{name}")
        if value:
            return value
    return os.environ.get(f"OPENMATES_TEST_ACCOUNT_{name}") or os.environ.get(
        f"OPENMATES_TEST_ACCOUNT_1_{name}"
    )


def _hash_email(email: str) -> str:
    return base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()


async def main():
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

    parser = argparse.ArgumentParser(description="Reset a test account's 2FA secret")
    parser.add_argument("otp_secret", nargs="?", help="TOTP secret to store")
    parser.add_argument("--from-env", action="store_true", help="Read the TOTP secret from env")
    parser.add_argument("--slot", type=int, help="Use OPENMATES_TEST_ACCOUNT_<slot>_* env vars")
    parser.add_argument("--user-id", help="Target a specific Directus user UUID")
    args = parser.parse_args()

    otp_secret = args.otp_secret
    if args.from_env:
        otp_secret = _get_test_account_env("OTP_KEY", args.slot)
        if not otp_secret:
            slot_hint = f"_{args.slot}" if args.slot is not None else ""
            print(f"ERROR: OPENMATES_TEST_ACCOUNT{slot_hint}_OTP_KEY not set in environment")
            sys.exit(1)

    if not otp_secret:
        print("ERROR: No OTP secret provided. Use --from-env or pass as argument.")
        sys.exit(1)

    # Initialize services
    cache_service = CacheService()
    directus_service = DirectusService(cache_service=cache_service)
    encryption_service = EncryptionService()

    if args.user_id:
        # Direct user lookup by ID
        user_id = args.user_id
        fields = await directus_service.get_user_fields_direct(
            user_id, ["id", "vault_key_id"]
        )
        if not fields:
            print(f"ERROR: User {user_id} not found")
            sys.exit(1)
        vault_key_id = fields.get("vault_key_id")
    else:
        # Lookup by hashed email
        test_email = _get_test_account_env("EMAIL", args.slot)
        if not test_email:
            slot_hint = f"_{args.slot}" if args.slot is not None else ""
            print(f"ERROR: OPENMATES_TEST_ACCOUNT{slot_hint}_EMAIL not set (use --user-id instead)")
            sys.exit(1)

        print(f"Looking up user by email: {test_email}")
        email_hash = _hash_email(test_email)
        success, user, message = await directus_service.get_user_by_hashed_email(email_hash)
        if not success or not user:
            print(f"ERROR: User not found — {message}")
            print("TIP: Use --user-id <uuid> if email lookup finds the wrong user")
            sys.exit(1)
        user_id = user.get("id")
        vault_key_id = user.get("vault_key_id")
    print(f"Found user: {user_id}")
    print(f"Vault key ID: {vault_key_id}")

    if not vault_key_id:
        # Fetch vault_key_id directly if not returned by lookup
        fields = await directus_service.get_user_fields_direct(
            user_id, ["vault_key_id"]
        )
        vault_key_id = fields.get("vault_key_id") if fields else None
        if not vault_key_id:
            print("ERROR: User has no vault_key_id")
            sys.exit(1)
        print(f"Vault key ID (fetched): {vault_key_id}")

    # Encrypt the new secret with the user's vault key
    encrypted_secret, _ = await encryption_service.encrypt_with_user_key(
        otp_secret, vault_key_id
    )
    if not encrypted_secret:
        print("ERROR: Failed to encrypt OTP secret with vault key")
        sys.exit(1)

    # Update Directus
    update_success = await directus_service.update_user(user_id, {
        "encrypted_tfa_secret": encrypted_secret,
        "tfa_last_used": int(time.time()),
    })
    if not update_success:
        print("ERROR: Failed to update user in Directus")
        sys.exit(1)

    # Clear the TFA cache
    client = await cache_service.client
    if client:
        await client.delete(f"user_tfa_data:{user_id}")

    # Verify decrypt round-trip
    decrypted = await encryption_service.decrypt_with_user_key(encrypted_secret, vault_key_id)
    if decrypted == otp_secret:
        print("SUCCESS: 2FA secret reset and decrypt verified")
    else:
        print(f"WARNING: Decrypt mismatch — got '{decrypted}'")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
