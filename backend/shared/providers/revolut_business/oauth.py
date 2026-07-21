# backend/shared/providers/revolut_business/oauth.py
#
# Revolut Business OAuth-like token exchange helpers.
# Revolut uses a certificate/JWT client assertion flow; this module keeps the
# exchange logic provider-local and avoids importing any Finance app code.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

try:
    import jwt
except ImportError:
    class _MissingJwt:
        @staticmethod
        def encode(*_args: Any, **_kwargs: Any) -> str:
            raise RevolutBusinessTokenExchangeError("PyJWT is required for Revolut Business token exchange")

    jwt = _MissingJwt()

REVOLUT_TOKEN_URL = "https://b2b.revolut.com/api/1.0/auth/token"
REVOLUT_SANDBOX_TOKEN_URL = "https://sandbox-b2b.revolut.com/api/1.0/auth/token"
TOKEN_EXCHANGE_TIMEOUT_SECONDS = 15.0
REVOLUT_AUDIENCE = "https://revolut.com"
REVOLUT_CLIENT_ASSERTION_TTL_SECONDS = 60 * 60
REVOLUT_CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
REVOLUT_ISSUERS = {
    "sandbox": "api.dev.openmates.org",
    "production": "api.openmates.org",
}

logger = logging.getLogger(__name__)


class RevolutBusinessTokenExchangeError(RuntimeError):
    """Sanitized Revolut token exchange failure."""


async def exchange_revolut_business_refresh_token(
    refresh_token: str,
    scope_context: dict[str, Any],
) -> dict[str, Any]:
    """Exchange a Revolut Business refresh token for an access token.

    The decrypted connected-account envelope is expected in scope_context when
    live exchange is used because Revolut requires client_id and a JWT client
    assertion signed with the user's certificate private key.
    """

    envelope = scope_context.get("refresh_token_envelope") if isinstance(scope_context, dict) else None
    if not isinstance(envelope, dict):
        envelope = {}
    client_id = str(envelope.get("client_id") or "").strip()
    environment = _normalize_environment(envelope.get("environment"))
    client_assertion = _client_assertion_for_envelope(client_id=client_id, envelope=envelope, environment=environment)
    token_url = REVOLUT_SANDBOX_TOKEN_URL if environment == "sandbox" else REVOLUT_TOKEN_URL
    if not client_id or not client_assertion:
        raise RevolutBusinessTokenExchangeError("Revolut Business client credentials are not configured")

    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS) as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_assertion_type": REVOLUT_CLIENT_ASSERTION_TYPE,
                "client_assertion": client_assertion,
            },
        )
    if response.is_error:
        logger.warning("Revolut Business token exchange failed: status=%s", response.status_code)
        raise RevolutBusinessTokenExchangeError(f"Revolut Business token exchange failed with HTTP {response.status_code}")
    payload = response.json()
    result: dict[str, Any] = {"access_token": payload.get("access_token")}
    if payload.get("expires_in") is not None:
        result["expires_in"] = payload["expires_in"]
    if payload.get("refresh_token"):
        result["rotated_refresh_token_bundle"] = {
            **envelope,
            "refresh_token": payload["refresh_token"],
            "provider": "revolut_business",
        }
    return result


async def exchange_revolut_business_authorization_code(
    *,
    client_id: str,
    code_or_redirect_url: str,
    private_key_pem: str,
    environment: str = "production",
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    """Exchange a Revolut Business authorization code for token material."""

    normalized_environment = _normalize_environment(environment)
    code = extract_revolut_business_authorization_code(code_or_redirect_url)
    if not client_id.strip() or not code or not private_key_pem.strip():
        raise RevolutBusinessTokenExchangeError("Revolut Business setup credentials are incomplete")
    token_url = REVOLUT_SANDBOX_TOKEN_URL if normalized_environment == "sandbox" else REVOLUT_TOKEN_URL
    client_assertion = generate_revolut_business_client_assertion(
        client_id=client_id,
        private_key_pem=private_key_pem,
        environment=normalized_environment,
        issuer=_issuer_from_redirect_uri(redirect_uri) if redirect_uri else None,
    )
    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS) as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_assertion_type": REVOLUT_CLIENT_ASSERTION_TYPE,
                "client_assertion": client_assertion,
            },
        )
    if response.is_error:
        logger.warning("Revolut Business authorization-code exchange failed: status=%s", response.status_code)
        raise RevolutBusinessTokenExchangeError(
            f"Revolut Business authorization-code exchange failed with HTTP {response.status_code}"
        )
    payload = response.json()
    if not payload.get("refresh_token"):
        raise RevolutBusinessTokenExchangeError("Revolut Business authorization-code exchange did not return a refresh token")
    return payload


def generate_revolut_business_client_assertion(
    *,
    client_id: str,
    private_key_pem: str,
    environment: str = "production",
    issuer: str | None = None,
) -> str:
    """Sign a short-lived Revolut Business client assertion JWT."""

    normalized_environment = _normalize_environment(environment)
    now = int(time.time())
    payload = {
        "iss": issuer or REVOLUT_ISSUERS[normalized_environment],
        "sub": client_id,
        "aud": REVOLUT_AUDIENCE,
        "exp": now + REVOLUT_CLIENT_ASSERTION_TTL_SECONDS,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def extract_revolut_business_authorization_code(value: str) -> str:
    trimmed = str(value or "").strip()
    if not trimmed:
        return ""
    if not trimmed.startswith(("http://", "https://")):
        return trimmed
    try:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(trimmed)
        return (parse_qs(parsed.query).get("code") or [""])[0].strip()
    except ValueError:
        return ""


def _issuer_from_redirect_uri(redirect_uri: str | None) -> str | None:
    if not redirect_uri:
        return None
    try:
        from urllib.parse import urlparse

        hostname = urlparse(redirect_uri).netloc.strip()
    except ValueError:
        return None
    return hostname or None


def _client_assertion_for_envelope(
    *,
    client_id: str,
    envelope: dict[str, Any],
    environment: str,
) -> str:
    manual_assertion = str(envelope.get("client_assertion") or "").strip()
    if manual_assertion:
        return manual_assertion
    private_key = str(envelope.get("private_key_pem") or envelope.get("private_key") or "").strip()
    if not client_id or not private_key:
        return ""
    return generate_revolut_business_client_assertion(
        client_id=client_id,
        private_key_pem=private_key,
        environment=environment,
    )


def _normalize_environment(value: Any) -> str:
    return "sandbox" if str(value or "").strip().lower() == "sandbox" else "production"
