#!/usr/bin/env python3
"""
Reset the test account's 2FA secret to a known value.

Used to sync the server's TOTP secret with the value stored in .env / GH Actions
secrets after a credential-mutating test (e.g., backup-code-login-flow.spec.ts)
has changed it.

Usage:
  docker exec api python /app/backend/scripts/reset_test_2fa.py --from-env
  docker exec api python /app/backend/scripts/reset_test_2fa.py --from-env --user-id <uuid>
  docker exec api python /app/backend/scripts/reset_test_2fa.py <otp_secret>
  docker exec api python /app/backend/scripts/reset_test_2fa.py <otp_secret> --user-id <uuid>

Flags:
  --from-env     Read OTP key from OPENMATES_TEST_ACCOUNT_OTP_KEY env var
  --user-id ID   Target a specific user by Directus UUID (bypasses email lookup)

How it works:
  1. Finds the user by --user-id (preferred) or by hashed_email from env.
  2. Encrypts the given OTP secret with the user's Vault transit key.
  3. Updates encrypted_tfa_secret in Directus and clears the TFA cache.
"""

import asyncio
import base64
import hashlib
import os
import sys
import time

sys.path.insert(0, "/app")

from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService


async def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: reset_test_2fa.py <otp_secret> | --from-env [--user-id <uuid>]")
        sys.exit(1)

    # Parse flags
    otp_secret = None
    explicit_user_id = None
    i = 0
    while i < len(args):
        if args[i] == "--from-env":
            otp_secret = os.environ.get("OPENMATES_TEST_ACCOUNT_OTP_KEY")
            if not otp_secret:
                print("ERROR: OPENMATES_TEST_ACCOUNT_OTP_KEY not set in environment")
                sys.exit(1)
        elif args[i] == "--user-id" and i + 1 < len(args):
            explicit_user_id = args[i + 1]
            i += 1
        elif not otp_secret and not args[i].startswith("--"):
            otp_secret = args[i]
        i += 1

    if not otp_secret:
        print("ERROR: No OTP secret provided. Use --from-env or pass as argument.")
        sys.exit(1)

    # Initialize services
    cache_service = CacheService()
    directus_service = DirectusService(cache_service=cache_service)
    encryption_service = EncryptionService()

    if explicit_user_id:
        # Direct user lookup by ID
        user_id = explicit_user_id
        fields = await directus_service.get_user_fields_direct(
            user_id, ["id", "vault_key_id"]
        )
        if not fields:
            print(f"ERROR: User {user_id} not found")
            sys.exit(1)
        vault_key_id = fields.get("vault_key_id")
    else:
        # Lookup by hashed email
        test_email = os.environ.get(
            "OPENMATES_TEST_ACCOUNT_EMAIL",
            os.environ.get("OPENMATES_TEST_ACCOUNT_1_EMAIL")
        )
        if not test_email:
            print("ERROR: OPENMATES_TEST_ACCOUNT_EMAIL not set (use --user-id instead)")
            sys.exit(1)

        print(f"Looking up user by email: {test_email}")
        email_hash = base64.b64encode(hashlib.sha256(test_email.encode()).digest()).decode()
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
