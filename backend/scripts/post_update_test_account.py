#!/usr/bin/env python3
"""Server side of the temporary accounts used by post-update checks (chat and voice call).

Runs inside the api container. The host wrapper scripts/post_update_test_account.py
sends this file on stdin, so it works before it is deployed:

    docker exec -i api python - <command> [options] < backend/scripts/post_update_test_account.py

Commands (each prints one JSON line; no secret, e-mail or code is logged):
  prepare                 create a single-use 0-credit invite code for the signup
  code --email E          read the pending e-mail verification code of E (the
                          signup mail goes to a mailbox nobody reads)
  mark --email E          label E as test account (users.is_test_account), set a
                          small credit balance and take it out of the daily
                          registration counter
  delete --email E        delete E and all its data through delete_user_account.py,
                          the path of the product's account deletion
  exists --email E        {exists: bool}

Every command except ``prepare`` refuses an e-mail that is not a recognised test
account address (``omtestuser-<16 hex>@<domain>``, the AI test-user marker).
"""
import argparse
import asyncio
import base64
import hashlib
import json
import re
import secrets
import subprocess
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/backend")

LOCAL_PART = re.compile(r"^omtestuser-[0-9a-f]{16}$")
CREDITS = 300  # two short chats and one short voice call
DELETE_SCRIPT = "/app/backend/scripts/delete_user_account.py"
DELETE_REASON = "Temporary post-update check account"


class RefusedError(ValueError):
    """The e-mail is not a test-account address, or a service call failed."""


def require_test_email(email: str) -> str:
    """Return the normalised e-mail or refuse when it lacks the test marker."""
    normalised = email.strip().lower()
    local, _, domain = normalised.rpartition("@")
    if not domain or not LOCAL_PART.match(local):
        raise RefusedError("email_is_not_a_test_account_address")
    return normalised


def hash_email(email: str) -> str:
    """SHA-256 (base64) of the e-mail, the way signup and account deletion hash it."""
    return base64.b64encode(hashlib.sha256(email.encode("utf-8")).digest()).decode("utf-8")


def user_id_hash(user_id: str) -> str:
    """Hash of the user id as stored in usage and invoice rows."""
    return hashlib.sha256(user_id.encode()).hexdigest()


async def _services():
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    return secrets_manager, cache, encryption, directus


async def prepare(directus) -> dict:
    """Create a single-use invite code with no gifted credits."""
    code = secrets.token_hex(9)
    created = await directus.create_item(
        "invite_codes", {"code": code, "remaining_uses": 1, "is_admin": False, "gifted_credits": 0},
        admin_required=True)
    if not created:
        raise RefusedError("invite_code_not_created")
    return {"invite_code": code}


async def verification_code(cache, email: str) -> dict:
    """The pending signup e-mail code of the account, or null when none is stored yet."""
    stored = await cache.get(f"email_verification:{email}")
    return {"code": str(stored) if stored else None}


async def _find_user(directus, email: str):
    success, user, _ = await directus.get_user_by_hashed_email(hash_email(email))
    return user if success and user else None


async def mark(cache, encryption, directus, email: str) -> dict:
    """Label the account as test account, set its credits and undo its registration count."""
    user = await _find_user(directus, email)
    if not user:
        raise RefusedError("user_not_found")
    user_id = user["id"]
    success, profile, _ = await directus.get_user_profile(user_id)
    vault_key_id = (profile or {}).get("vault_key_id")
    if not success or not vault_key_id:
        raise RefusedError("profile_without_vault_key")
    encrypted_credits, _ = await encryption.encrypt_with_user_key(str(CREDITS), vault_key_id)
    update = {"is_test_account": True, "encrypted_credit_balance": encrypted_credits}
    if not await directus.update_user(user_id, update):
        raise RefusedError("user_update_failed")
    profile["credits"] = CREDITS
    profile["is_test_account"] = True
    await cache.set_user(profile, user_id=user_id)
    from backend.core.api.app.services.stats_account_label import remember_test_account
    await remember_test_account(cache, user_id, True)
    await cache.increment_stat("new_users_registered", -1)
    return {"marked": True, "credits": CREDITS, "user_id_hash": user_id_hash(user_id)}


def delete(email: str) -> dict:
    """Run the product's account deletion; "absent" when no user exists any more."""
    run = subprocess.run(
        [sys.executable, DELETE_SCRIPT, "--email", email, "--yes", "--reason", DELETE_REASON],
        capture_output=True, text=True, timeout=300, check=False)
    output = run.stdout + run.stderr
    if run.returncode and "No user found" not in output:
        raise RefusedError(f"account_deletion_failed_exit_{run.returncode}")
    return {"deleted": True, "absent": bool(run.returncode)}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["prepare", "code", "mark", "delete", "exists"])
    parser.add_argument("--email", default="")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            email = ""
        else:
            email = require_test_email(args.email)
        if args.command == "delete":
            deletion_status = delete(email)
            print(json.dumps(deletion_status))
            return 0
        secrets_manager, cache, encryption, directus = await _services()
        try:
            if args.command == "prepare":
                result = await prepare(directus)
            elif args.command == "code":
                result = await verification_code(cache, email)
            elif args.command == "mark":
                result = await mark(cache, encryption, directus, email)
            else:
                result = {"exists": await _find_user(directus, email) is not None}
        finally:
            await secrets_manager.aclose()
            await directus.close()
        print(json.dumps(result))
        return 0
    except RefusedError as error:
        print(json.dumps({"error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
