"""Small HTTP helper shared by the company register wrappers.

Retries 429 and 5xx responses with short backoff and maps status codes to the
typed ``RegisterProviderError`` codes the Business app understands.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Protocol

import httpx

from backend.shared.providers.company_registers.models import RegisterProviderError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
USER_AGENT = "OpenMates company register reader (https://openmates.org)"


class SecretSource(Protocol):
    async def get_secret(self, secret_path: str, secret_key: str, log_missing: bool = True) -> str | None: ...


async def provider_api_key(provider_id: str, secrets_manager: SecretSource | None) -> str | None:
    """Read ``api_key`` from Vault ``kv/data/providers/<id>``, then the env fallback."""
    if secrets_manager is not None:
        value = await secrets_manager.get_secret(f"kv/data/providers/{provider_id}", "api_key", log_missing=False)
        if value and value.strip().strip("'\""):
            return value.strip().strip("'\"")
    env_name = f"SECRET__{provider_id.upper().replace('_', '__')}__API_KEY"
    value = os.getenv(env_name, "").strip().strip("'\"")
    return value or None


class _Borrowed:
    """Async context wrapper that does not close an injected client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: Any) -> None:
        return None


def borrowed_or_new(client: httpx.AsyncClient | None, timeout: float) -> Any:
    """Use an injected client without closing it, or open a fresh one."""
    return _Borrowed(client) if client is not None else httpx.AsyncClient(timeout=timeout)


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    not_found_ok: bool = False,
    **kwargs: Any,
) -> Any:
    """Send one request with retry; return parsed JSON or None for an allowed 404."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **kwargs.pop("headers", {})}
    last_status = 0
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("%s request failed (attempt %s): %s", provider, attempt + 1, exc)
            if attempt + 1 == MAX_ATTEMPTS:
                raise RegisterProviderError("provider_error", f"{provider} could not be reached") from exc
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        last_status = response.status_code
        if response.status_code == 429 or response.status_code >= 500:
            if attempt + 1 < MAX_ATTEMPTS:
                await asyncio.sleep(float(response.headers.get("Retry-After") or 0.5 * (attempt + 1)))
                continue
            break
        if response.status_code == 404 and not_found_ok:
            return None
        if response.status_code == 404:
            raise RegisterProviderError("not_found", f"{provider} has no matching entry")
        if response.status_code in (401, 403):
            raise RegisterProviderError("provider_not_configured", f"{provider} rejected the configured credentials")
        if response.status_code == 402:
            raise RegisterProviderError("rate_limited", f"{provider} monthly allowance is used up")
        if response.status_code >= 400:
            raise RegisterProviderError("provider_error", f"{provider} rejected the request (HTTP {response.status_code})")
        try:
            return response.json()
        except ValueError as exc:
            raise RegisterProviderError("provider_error", f"{provider} returned an unreadable response") from exc
    if last_status == 429:
        raise RegisterProviderError("rate_limited", f"{provider} rate limit reached; try again later")
    raise RegisterProviderError("provider_error", f"{provider} is temporarily unavailable (HTTP {last_status})")
