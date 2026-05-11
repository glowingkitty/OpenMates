"""
Vault api.token handoff validation.

The API startup script uses this module to reject stale Vault token files before
starting the web server. Vault can be unsealed and healthy while the api.token
on the shared volume is expired, revoked, or missing required policies. In that
state, login/encryption fails later at runtime, so startup must fail fast.

This module is intentionally small and has no app-state dependencies so it can
run from ``wait-for-vault.sh`` and from unit tests with a mocked Vault client.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass, field

import httpx


DEFAULT_REQUIRED_POLICIES = ("api-service", "api-encryption")
MIN_TOKEN_TTL_SECONDS = 3600


@dataclass
class VaultTokenValidationResult:
    """Structured result for validating a Vault token file."""

    valid: bool
    reason: str
    ttl_seconds: int = 0
    policies: list[str] = field(default_factory=list)
    missing_policies: list[str] = field(default_factory=list)
    status_code: int | None = None
    detail: str = ""


def _read_token(token_path: str) -> str | None:
    if not os.path.exists(token_path):
        return None
    with open(token_path, "r", encoding="utf-8") as token_file:
        token = token_file.read().strip()
    return token or None


async def validate_token_file(
    vault_url: str,
    token_path: str,
    *,
    required_policies: tuple[str, ...] = DEFAULT_REQUIRED_POLICIES,
    min_ttl_seconds: int = MIN_TOKEN_TTL_SECONDS,
    client: httpx.AsyncClient | None = None,
) -> VaultTokenValidationResult:
    """Validate a Vault api.token file using auth/token/lookup-self."""

    token = _read_token(token_path)
    if not token:
        return VaultTokenValidationResult(valid=False, reason="missing_token_file")

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        response = await client.get(
            f"{vault_url}/v1/auth/token/lookup-self",
            headers={"X-Vault-Token": token},
        )
    except Exception as exc:
        return VaultTokenValidationResult(
            valid=False,
            reason="vault_request_failed",
            detail=str(exc),
        )
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code != 200:
        return VaultTokenValidationResult(
            valid=False,
            reason="invalid_token",
            status_code=response.status_code,
            detail=response.text,
        )

    data = response.json().get("data", {})
    ttl_seconds = int(data.get("ttl") or 0)
    policies = list(data.get("policies") or [])
    policy_set = set(policies)
    policy_set.discard("default")
    missing_policies = [policy for policy in required_policies if policy not in policy_set]

    if missing_policies:
        return VaultTokenValidationResult(
            valid=False,
            reason="missing_policies",
            ttl_seconds=ttl_seconds,
            policies=policies,
            missing_policies=missing_policies,
        )

    if ttl_seconds < min_ttl_seconds:
        return VaultTokenValidationResult(
            valid=False,
            reason="ttl_too_low",
            ttl_seconds=ttl_seconds,
            policies=policies,
        )

    return VaultTokenValidationResult(
        valid=True,
        reason="valid",
        ttl_seconds=ttl_seconds,
        policies=policies,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Vault api.token handoff file")
    parser.add_argument("--vault-url", default=os.getenv("VAULT_ADDR") or os.getenv("VAULT_URL") or "http://vault:8200")
    parser.add_argument("--token-file", default="/vault-data/api.token")
    args = parser.parse_args()

    result = await validate_token_file(args.vault_url, args.token_file)
    if result.valid:
        print(f"Vault api.token is valid (ttl={result.ttl_seconds}s, policies={','.join(result.policies)})")
        return 0

    detail = f" detail={result.detail}" if result.detail else ""
    missing = f" missing_policies={','.join(result.missing_policies)}" if result.missing_policies else ""
    print(f"Vault api.token is invalid: reason={result.reason} status={result.status_code}{missing}{detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
