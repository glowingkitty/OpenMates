# backend/shared/providers/figma/oauth.py
#
# Figma OAuth adapter for connected accounts: confidential code exchange with
# PKCE, refresh-token exchange, and the /v1/me account hint lookup. Tokens and
# codes are never logged. Figma documents no revoke endpoint, so disconnect only
# deletes the stored refresh token on the client side.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml
# Docs: https://developers.figma.com/docs/rest-api/oauth-apps/

from __future__ import annotations

import logging
from typing import Any, Iterable

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.connected_account_errors import ConnectedAccountTokenExchangeError

FIGMA_AUTHORIZE_URL = "https://www.figma.com/oauth"
FIGMA_TOKEN_URL = "https://api.figma.com/v1/oauth/token"
FIGMA_REFRESH_URL = "https://api.figma.com/v1/oauth/refresh"
FIGMA_ME_URL = "https://api.figma.com/v1/me"
FIGMA_OAUTH_SECRET_PATH = "kv/data/providers/figma"
FIGMA_OAUTH_CLIENT_ID_SECRET_KEY = "oauth_client_id"
FIGMA_OAUTH_CLIENT_SECRET_SECRET_KEY = "oauth_client_secret"
TOKEN_EXCHANGE_TIMEOUT_SECONDS = 15.0
MAX_PROVIDER_ERROR_DESCRIPTION_LENGTH = 240

BASE_SCOPES = ("file_content:read", "current_user:read")
VARIABLES_SCOPE = "file_variables:read"
SUPPORTED_CAPABILITIES = frozenset({"read", "variables"})

logger = logging.getLogger(__name__)


class FigmaOAuthNotConfiguredError(RuntimeError):
    """Figma OAuth client credentials are missing from Vault."""


class FigmaOAuthTokenExchangeError(ConnectedAccountTokenExchangeError):
    """Sanitized Figma OAuth token exchange failure."""

    def __init__(
        self,
        *,
        operation: str,
        status_code: int,
        provider_error: str | None,
        provider_error_description: str | None,
    ) -> None:
        self.operation = operation
        self.provider_error_description = provider_error_description
        message = f"Figma OAuth {operation} failed with HTTP {status_code}"
        if provider_error:
            message += f": {provider_error}"
        if provider_error_description:
            message += f" ({provider_error_description})"
        super().__init__(
            message, provider_id="figma", status_code=status_code, provider_error=provider_error,
        )


def scopes_for_capabilities(capabilities: Iterable[str]) -> list[str]:
    """Map requested capabilities to the minimal Figma scopes."""

    requested = list(dict.fromkeys(capabilities))
    unsupported = [item for item in requested if item not in SUPPORTED_CAPABILITIES]
    if unsupported:
        raise ValueError(f"Unsupported Figma capabilities: {', '.join(sorted(unsupported))}")
    if "read" not in requested:
        raise ValueError("Figma connection requires the read capability")
    scopes = list(BASE_SCOPES)
    if "variables" in requested:
        scopes.append(VARIABLES_SCOPE)
    return scopes


def _sanitize(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    sanitized = " ".join(value.split()).strip()
    return sanitized[:MAX_PROVIDER_ERROR_DESCRIPTION_LENGTH] or None


def _provider_error(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        payload = response.json()
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    error = payload.get("error")
    description = payload.get("error_description") or payload.get("message")
    if isinstance(error, bool) or isinstance(error, (int, float)):
        error = None
    return _sanitize(error), _sanitize(description)


def _raise_for_figma_error(response: httpx.Response, *, operation: str) -> None:
    if not response.is_error:
        return
    provider_error, description = _provider_error(response)
    logger.warning(
        "Figma OAuth %s failed: status=%s provider_error=%s",
        operation, response.status_code, provider_error or "unknown",
    )
    raise FigmaOAuthTokenExchangeError(
        operation=operation,
        status_code=response.status_code,
        provider_error=provider_error,
        provider_error_description=description,
    )


async def _vault_value(secrets_manager: SecretsManager, secret_key: str) -> str | None:
    if not secrets_manager.vault_token or not secrets_manager.vault_url:
        await secrets_manager.initialize()
    if not secrets_manager.vault_token or not secrets_manager.vault_url:
        return None
    value = await secrets_manager.get_secret(FIGMA_OAUTH_SECRET_PATH, secret_key, log_missing=False)
    return value.strip() if value and value.strip() else None


async def get_figma_oauth_credentials(
    secrets_manager: SecretsManager | None = None,
) -> tuple[str, str]:
    """Resolve Figma OAuth client credentials from Vault only."""

    manager = secrets_manager or SecretsManager()
    client_id = await _vault_value(manager, FIGMA_OAUTH_CLIENT_ID_SECRET_KEY)
    client_secret = await _vault_value(manager, FIGMA_OAUTH_CLIENT_SECRET_SECRET_KEY)
    if not client_id or not client_secret:
        raise FigmaOAuthNotConfiguredError("Figma OAuth client credentials are not configured")
    return client_id, client_secret


async def exchange_figma_authorization_code(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Exchange a Figma authorization code (valid 30 s) using PKCE and Basic auth."""

    client_id, client_secret = await get_figma_oauth_credentials()
    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.post(
            FIGMA_TOKEN_URL,
            auth=(client_id, client_secret),
            data={
                "redirect_uri": redirect_uri,
                "code": code,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
        _raise_for_figma_error(response, operation="authorization code exchange")
        return response.json()


async def exchange_figma_refresh_token(
    refresh_token: str,
    scope_context: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Exchange a Figma refresh token for a short-lived access token.

    Figma does not rotate refresh tokens; a refresh invalidates the previous
    access token, so callers must not share one access token across requests.
    """

    client_id, client_secret = await get_figma_oauth_credentials()
    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.post(
            FIGMA_REFRESH_URL,
            auth=(client_id, client_secret),
            data={"refresh_token": refresh_token},
        )
        _raise_for_figma_error(response, operation="refresh token exchange")
        payload = response.json()

    result: dict[str, Any] = {"access_token": payload.get("access_token")}
    if payload.get("expires_in") is not None:
        result["expires_in"] = payload["expires_in"]
    return result


async def fetch_figma_current_user(
    access_token: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch id, handle, email and avatar of the connected Figma account."""

    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.get(FIGMA_ME_URL, headers={"Authorization": f"Bearer {access_token}"})
        _raise_for_figma_error(response, operation="current user lookup")
        payload = response.json()
    return payload if isinstance(payload, dict) else {}
