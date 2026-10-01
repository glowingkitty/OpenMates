"""Keep the upload service's scoped local Vault token alive without root access."""

import asyncio
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TOKEN_KIND = "periodic_v1"
RENEW_INTERVAL_SECONDS = 12 * 60 * 60
RETRY_INTERVAL_SECONDS = 5 * 60


class TokenRenewalError(RuntimeError):
    """A sanitized Vault token validation or renewal failure."""


async def renew_api_token(
    client: httpx.AsyncClient, vault_url: str, token_path: str
) -> int:
    """Validate and renew the scoped periodic token; return its new TTL in seconds."""
    try:
        token = Path(token_path).read_text().strip()
    except OSError as exc:
        raise TokenRenewalError("Vault API token file unavailable") from exc
    if not token:
        raise TokenRenewalError("Vault API token file empty")

    headers = {"X-Vault-Token": token}
    url = vault_url.rstrip("/")
    try:
        lookup = await client.get(f"{url}/v1/auth/token/lookup-self", headers=headers)
        lookup.raise_for_status()
        data = lookup.json().get("data") or {}
        if (
            data.get("ttl", 0) <= 0
            or not data.get("renewable")
            or "uploads-service" not in data.get("policies", [])
            or (data.get("meta") or {}).get("uploads_token_kind") != TOKEN_KIND
            or data.get("explicit_max_ttl", 0) != 0
        ):
            raise TokenRenewalError(
                "Vault API token is not a renewable scoped periodic token; rerun vault-setup"
            )

        response = await client.post(f"{url}/v1/auth/token/renew-self", headers=headers)
        response.raise_for_status()
        auth = response.json().get("auth") or {}
        ttl = auth.get("lease_duration", 0)
        if not auth.get("renewable") or ttl <= RENEW_INTERVAL_SECONDS:
            raise TokenRenewalError("Vault API token renewal returned insufficient TTL")
        return ttl
    except httpx.HTTPStatusError as exc:
        raise TokenRenewalError(
            f"Vault API token request rejected (HTTP {exc.response.status_code})"
        ) from None
    except (httpx.RequestError, ValueError, TypeError, AttributeError):
        raise TokenRenewalError("Vault API token request failed") from None


async def maintain_api_token(
    vault_url: str, token_path: str
) -> None:
    """Renew twice daily; retry transient failures every five minutes."""
    delay = RENEW_INTERVAL_SECONDS
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            await asyncio.sleep(delay)
            try:
                await renew_api_token(client, vault_url, token_path)
                delay = RENEW_INTERVAL_SECONDS
                logger.info("[Uploads] Local Vault API token renewed")
            except Exception:
                delay = RETRY_INTERVAL_SECONDS
                logger.error("[Uploads] Local Vault API token renewal failed; retrying in 5 minutes")
