"""One-use client-held email verification proof for account creation."""

import base64
import hashlib
import secrets
import time


async def verify_signup_transaction(
    cache_service,
    *,
    hashed_email: str,
    username: str,
    invite_code: str,
    transaction_token: str | None,
    consume: bool = False,
) -> dict | None:
    if not transaction_token or len(transaction_token) > 256:
        return None
    data = await cache_service.get(f"email_verified:{hashed_email}")
    if not isinstance(data, dict):
        return None
    actual_email_hash = base64.b64encode(hashlib.sha256(data.get("email", "").encode("utf-8")).digest()).decode("utf-8")
    token_hash = hashlib.sha256(transaction_token.encode("utf-8")).hexdigest()
    valid = (
        secrets.compare_digest(actual_email_hash, hashed_email)
        and secrets.compare_digest(str(data.get("transaction_token_hash", "")), token_hash)
        and data.get("username") == username
        and (data.get("invite_code") or "") == (invite_code or "")
        and time.time() - int(data.get("verified_at", 0)) <= 1800
    )
    if not valid:
        return None
    if consume:
        consumed = await cache_service.get_and_delete(f"signup_transaction:{hashed_email}:{token_hash}")
        if str(consumed) != "1":
            return None
    return data
