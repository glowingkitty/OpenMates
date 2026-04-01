#!/usr/bin/env python3
"""
Reset the test account's 2FA secret to a known value.

Used to sync the server's TOTP secret with the value stored in .env / GH Actions
secrets after a credential-mutating test (e.g., backup-code-login-flow.spec.ts)
has changed it.

Usage:
  docker exec api python /app/backend/scripts/reset_test_2fa.py <otp_secret>
  docker exec api python /app/backend/scripts/reset_test_2fa.py --from-env

The --from-env flag reads OPENMATES_TEST_ACCOUNT_OTP_KEY from the environment.
"""

import asyncio
import os
import sys
import hashlib

# Add project root to path
sys.path.insert(0, "/app")

from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService


async def main():
    if len(sys.argv) < 2:
        print("Usage: reset_test_2fa.py <otp_secret> | --from-env")
        sys.exit(1)

    if sys.argv[1] == "--from-env":
        otp_secret = os.environ.get("OPENMATES_TEST_ACCOUNT_OTP_KEY")
        if not otp_secret:
            print("ERROR: OPENMATES_TEST_ACCOUNT_OTP_KEY not set in environment")
            sys.exit(1)
    else:
        otp_secret = sys.argv[1]

    test_email = os.environ.get(
        "OPENMATES_TEST_ACCOUNT_EMAIL",
        os.environ.get("OPENMATES_TEST_ACCOUNT_1_EMAIL")
    )
    if not test_email:
        print("ERROR: OPENMATES_TEST_ACCOUNT_EMAIL not set in environment")
        sys.exit(1)

    print(f"Resetting 2FA for test account: {test_email}")
    print(f"New OTP secret: {otp_secret}")

    # Initialize services
    cache_service = CacheService()
    directus_service = DirectusService(cache_service=cache_service)
    encryption_service = EncryptionService()

    # Find the test user by hashed email (base64-encoded SHA-256, matching frontend hashEmail())
    import base64
    email_hash_bytes = hashlib.sha256(test_email.encode()).digest()
    hashed_email = base64.b64encode(email_hash_bytes).decode()
    success, user, message = await directus_service.get_user_by_hashed_email(hashed_email)
    if not success or not user:
        print(f"ERROR: User not found for email hash {hashed_email[:16]}... — {message}")
        sys.exit(1)

    user_id = user.get("id")
    vault_key_id = user.get("vault_key_id")
    print(f"Found user: {user_id}")
    print(f"Vault key ID: {vault_key_id}")

    if not vault_key_id:
        print("ERROR: User has no vault_key_id")
        sys.exit(1)

    # Encrypt the new secret with the user's vault key
    encrypted_secret, key_version = await encryption_service.encrypt_with_user_key(
        otp_secret, vault_key_id
    )
    if not encrypted_secret:
        print("ERROR: Failed to encrypt OTP secret with vault key")
        sys.exit(1)

    print(f"Encrypted secret (first 20 chars): {encrypted_secret[:20]}...")

    # Update Directus with the new encrypted secret
    import time
    success = await directus_service.update_user(user_id, {
        "encrypted_tfa_secret": encrypted_secret,
        "tfa_last_used": int(time.time()),
    })

    if not success:
        print("ERROR: Failed to update user in Directus")
        sys.exit(1)

    # Also clear the cache so the new secret is picked up
    await cache_service.update_user(user_id, {"tfa_enabled": True})

    print("SUCCESS: 2FA secret reset and synced")
    print(f"OTP key to use in tests: {otp_secret}")

    # Verify by decrypting
    decrypted = await encryption_service.decrypt_with_user_key(encrypted_secret, vault_key_id)
    if decrypted == otp_secret:
        print("VERIFIED: Decrypt round-trip succeeded")
    else:
        print(f"WARNING: Decrypt returned '{decrypted}' instead of '{otp_secret}'")

    await cache_service.close()


if __name__ == "__main__":
    asyncio.run(main())
