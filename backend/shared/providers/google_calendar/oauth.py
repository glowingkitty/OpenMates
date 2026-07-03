# backend/shared/providers/google_calendar/oauth.py
#
# Google OAuth token exchange helper for connected Calendar accounts.
# This module exchanges refresh tokens only when the permission/token brokers have
# authorized an exact active-turn account/action scope.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager

GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKEN_EXCHANGE_TIMEOUT_SECONDS = 15.0
GOOGLE_OAUTH_SECRET_PATHS = ("kv/data/providers/google", "kv/data/providers/google_calendar")
GOOGLE_OAUTH_CLIENT_ID_SECRET_KEYS = ("oauth_client_id", "client_id")
GOOGLE_OAUTH_CLIENT_SECRET_SECRET_KEYS = ("oauth_client_secret", "client_secret")
MAX_PROVIDER_ERROR_DESCRIPTION_LENGTH = 240

logger = logging.getLogger(__name__)


class GoogleOAuthTokenExchangeError(RuntimeError):
    """Sanitized Google OAuth token exchange failure."""

    def __init__(
        self,
        *,
        operation: str,
        status_code: int,
        provider_error: str | None,
        provider_error_description: str | None,
    ) -> None:
        self.operation = operation
        self.status_code = status_code
        self.provider_error = provider_error
        self.provider_error_description = provider_error_description
        message = f"Google OAuth {operation} failed with HTTP {status_code}"
        if provider_error:
            message += f": {provider_error}"
        if provider_error_description:
            message += f" ({provider_error_description})"
        super().__init__(message)


def _sanitize_provider_error_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    sanitized = " ".join(value.split()).strip()
    if not sanitized:
        return None
    return sanitized[:MAX_PROVIDER_ERROR_DESCRIPTION_LENGTH]


def _provider_token_error(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        payload = response.json()
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    return (
        _sanitize_provider_error_value(payload.get("error")),
        _sanitize_provider_error_value(payload.get("error_description")),
    )


def _raise_for_google_token_error(response: httpx.Response, *, operation: str) -> None:
    if not response.is_error:
        response.raise_for_status()
        return

    provider_error, provider_error_description = _provider_token_error(response)
    logger.warning(
        "Google OAuth %s failed: status=%s provider_error=%s provider_error_description=%s",
        operation,
        response.status_code,
        provider_error or "unknown",
        provider_error_description or "unknown",
    )
    raise GoogleOAuthTokenExchangeError(
        operation=operation,
        status_code=response.status_code,
        provider_error=provider_error,
        provider_error_description=provider_error_description,
    )


async def _first_vault_value(
    secrets_manager: SecretsManager,
    secret_keys: tuple[str, ...],
) -> str | None:
    if not secrets_manager.vault_token or not secrets_manager.vault_url:
        await secrets_manager.initialize()
    if not secrets_manager.vault_token or not secrets_manager.vault_url:
        return None

    for secret_path in GOOGLE_OAUTH_SECRET_PATHS:
        for secret_key in secret_keys:
            value = await secrets_manager.get_secret(secret_path, secret_key, log_missing=False)
            if value and value.strip():
                return value.strip()
    return None


async def get_google_oauth_credentials(
    secrets_manager: SecretsManager | None = None,
) -> tuple[str, str]:
    """Resolve Google OAuth client credentials from Vault only."""

    manager = secrets_manager or SecretsManager()
    client_id = await _first_vault_value(manager, GOOGLE_OAUTH_CLIENT_ID_SECRET_KEYS)
    client_secret = await _first_vault_value(manager, GOOGLE_OAUTH_CLIENT_SECRET_SECRET_KEYS)
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth client credentials are not configured")
    return client_id, client_secret


async def exchange_google_refresh_token(
    refresh_token: str,
    scope_context: dict[str, Any],
) -> dict[str, Any]:
    """Exchange a Google refresh token for a short-lived access token."""

    client_id, client_secret = await get_google_oauth_credentials()

    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS) as client:
        response = await client.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        _raise_for_google_token_error(response, operation="refresh token exchange")
        payload = response.json()

    result: dict[str, Any] = {"access_token": payload.get("access_token")}
    if payload.get("expires_in") is not None:
        result["expires_in"] = payload["expires_in"]
    if payload.get("refresh_token"):
        result["rotated_refresh_token_bundle"] = {
            "provider": "google",
            "refresh_token": payload["refresh_token"],
            "scope_context": scope_context,
        }
    return result


async def exchange_google_authorization_code(
    *,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange a Google OAuth authorization code for token response data."""

    client_id, client_secret = await get_google_oauth_credentials()

    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS) as client:
        response = await client.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        _raise_for_google_token_error(response, operation="authorization code exchange")
        return response.json()
