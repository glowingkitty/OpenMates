# backend/shared/providers/google_calendar/oauth.py
#
# Google OAuth token exchange helper for connected Calendar accounts.
# This module exchanges refresh tokens only when the permission/token brokers have
# authorized an exact active-turn account/action scope.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import os
from typing import Any

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager

GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKEN_EXCHANGE_TIMEOUT_SECONDS = 15.0
GOOGLE_OAUTH_CLIENT_ID_ENV_VARS = (
    "SECRET__GOOGLE__OAUTH_CLIENT_ID",
    "GOOGLE_CALENDAR_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_ID",
    "SECRET__GOOGLE_CALENDAR__OAUTH_CLIENT_ID",
)
GOOGLE_OAUTH_CLIENT_SECRET_ENV_VARS = (
    "SECRET__GOOGLE__OAUTH_CLIENT_SECRET",
    "GOOGLE_CALENDAR_CLIENT_SECRET",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "SECRET__GOOGLE_CALENDAR__OAUTH_CLIENT_SECRET",
)
GOOGLE_OAUTH_SECRET_PATHS = ("kv/data/providers/google", "kv/data/providers/google_calendar")
GOOGLE_OAUTH_CLIENT_ID_SECRET_KEYS = ("oauth_client_id", "client_id")
GOOGLE_OAUTH_CLIENT_SECRET_SECRET_KEYS = ("oauth_client_secret", "client_secret")


def _first_env_value(env_var_names: tuple[str, ...]) -> str | None:
    for env_var_name in env_var_names:
        value = os.getenv(env_var_name)
        if value and value.strip():
            return value.strip()
    return None


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
    """Resolve Google OAuth client credentials from env or Vault."""

    client_id = _first_env_value(GOOGLE_OAUTH_CLIENT_ID_ENV_VARS)
    client_secret = _first_env_value(GOOGLE_OAUTH_CLIENT_SECRET_ENV_VARS)
    if client_id and client_secret:
        return client_id, client_secret

    manager = secrets_manager or SecretsManager()
    client_id = client_id or await _first_vault_value(manager, GOOGLE_OAUTH_CLIENT_ID_SECRET_KEYS)
    client_secret = client_secret or await _first_vault_value(manager, GOOGLE_OAUTH_CLIENT_SECRET_SECRET_KEYS)
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
        response.raise_for_status()
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
        response.raise_for_status()
        return response.json()
