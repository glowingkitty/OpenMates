"""
WebSocket authentication token utilities.

Generates and verifies short-lived HMAC tokens for WebSocket authentication.
These replace the previous approach of returning the raw refresh token as ws_token,
which defeated the HttpOnly cookie protection.

The ws_token format is: "<token_hash>:<expiry_unix_ts>:<hmac_hex>"
  - token_hash: SHA-256 of the refresh token (same key used in the session cache)
  - expiry: Unix timestamp when the token expires
  - hmac: HMAC-SHA256(token_hash + ":" + expiry, INTERNAL_API_SHARED_TOKEN)

The frontend stores this in sessionStorage and passes it as a query parameter
during WebSocket connection — Safari iOS doesn't send HttpOnly cookies on
WebSocket upgrade requests, so this provides a secure fallback.

Security properties:
  - Token is NOT the refresh token — a leaked ws_token cannot be used to
    refresh the session or call any REST API endpoint.
  - The token_hash inside is the same hash already stored server-side in the
    session cache — it is not secret (it's a hash, not the token itself).
  - Short TTL (5 min) limits the window of exposure.
  - HMAC binding prevents forgery or tampering with the token_hash/expiry.

Architecture: docs/architecture/security.md
"""

import hashlib
import hmac
import logging
import os
import time

logger = logging.getLogger(__name__)

# Short TTL — the frontend refreshes the ws_token on every /auth/session call
WS_TOKEN_TTL_SECONDS = 300  # 5 minutes

# Signing key — reuse the internal API shared token as the HMAC key.
# This secret is available to the API server but never exposed to browsers.
_WS_TOKEN_SECRET = os.getenv("INTERNAL_API_SHARED_TOKEN", "")


def create_ws_token(refresh_token: str) -> str:
    """Create a short-lived HMAC token for WebSocket authentication.

    Format: "<token_hash>:<expiry>:<hmac_sig>"

    Args:
        refresh_token: The raw Directus refresh token (from the login/session flow).

    Returns:
        A ws_token string the frontend can pass as a WebSocket query parameter.
    """
    if not _WS_TOKEN_SECRET:
        logger.warning("INTERNAL_API_SHARED_TOKEN not set — ws_token will be empty")
        return ""

    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    expiry = int(time.time()) + WS_TOKEN_TTL_SECONDS
    payload = f"{token_hash}:{expiry}"

    sig = hmac.new(
        _WS_TOKEN_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    return f"{token_hash}:{expiry}:{sig}"


def verify_ws_token(ws_token: str) -> str | None:
    """Verify a ws_token and extract the session token_hash.

    Args:
        ws_token: The token string received from the WebSocket query parameter.

    Returns:
        The token_hash (str) if valid and not expired, or None on failure.
    """
    if not _WS_TOKEN_SECRET or not ws_token:
        return None

    try:
        parts = ws_token.split(":", 2)
        if len(parts) != 3:
            logger.debug("ws_token format invalid — expected '<token_hash>:<expiry>:<sig>'")
            return None

        token_hash, expiry_str, sig_received = parts
        expiry = int(expiry_str)

        # Check expiry
        if time.time() > expiry:
            logger.debug("ws_token expired")
            return None

        # Re-derive the expected HMAC
        payload = f"{token_hash}:{expiry_str}"
        sig_expected = hmac.new(
            _WS_TOKEN_SECRET.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(sig_received, sig_expected):
            logger.debug("ws_token HMAC mismatch")
            return None

        return token_hash

    except (ValueError, TypeError) as e:
        logger.debug(f"ws_token verification error: {e}")
        return None
