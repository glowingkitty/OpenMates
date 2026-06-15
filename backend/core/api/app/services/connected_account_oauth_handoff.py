# backend/core/api/app/services/connected_account_oauth_handoff.py
#
# Provider-neutral OAuth refresh-token handoff for connected accounts.
# Confidential OAuth adapters exchange provider authorization codes server-side,
# then place refresh-token bundles in this one-time encrypted handoff for the
# browser to claim and immediately encrypt with the user's master key.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_OAUTH_HANDOFF_TTL_SECONDS = 2 * 60
OAUTH_HANDOFF_PREFIX = "connected_account:oauth_handoff:"


@dataclass(frozen=True)
class OAuthRefreshTokenHandoff:
    """Opaque one-time handoff for browser-side connected-account encryption."""

    handoff_id: str
    expires_at: int


@dataclass(frozen=True)
class ClaimedOAuthRefreshTokenHandoff:
    """Plaintext payload returned once to the owning browser session."""

    provider_id: str
    refresh_token_bundle: dict[str, Any]
    account_hint: dict[str, Any]
    expires_at: int


class ConnectedAccountOAuthHandoffService:
    """Create and claim encrypted OAuth handoffs for any connected-account provider."""

    def __init__(
        self,
        *,
        cache_service: Any,
        encryption_service: Any,
        ttl_seconds: int = DEFAULT_OAUTH_HANDOFF_TTL_SECONDS,
    ) -> None:
        self.cache = cache_service
        self.encryption = encryption_service
        self.ttl_seconds = ttl_seconds

    async def create_handoff(
        self,
        *,
        user_id: str,
        user_vault_key_id: str,
        provider_id: str,
        refresh_token_bundle: dict[str, Any],
        account_hint: dict[str, Any] | None = None,
    ) -> OAuthRefreshTokenHandoff:
        """Store a provider refresh-token bundle in an encrypted one-time handoff."""

        if not refresh_token_bundle.get("refresh_token"):
            raise ValueError("refresh_token_bundle.refresh_token is required")
        if not provider_id:
            raise ValueError("provider_id is required")

        handoff_id = f"oauth_handoff_{secrets.token_urlsafe(24)}"
        expires_at = int(time.time()) + self.ttl_seconds
        encrypted_payload, _ = await self.encryption.encrypt_with_user_key(
            json.dumps(
                {
                    "provider_id": provider_id,
                    "refresh_token_bundle": refresh_token_bundle,
                    "account_hint": account_hint or {},
                    "expires_at": expires_at,
                }
            ),
            user_vault_key_id,
        )
        payload = {
            "user_id": user_id,
            "encrypted_handoff_payload": encrypted_payload,
            "expires_at": expires_at,
        }
        ok = await self.cache.set(self._handoff_key(handoff_id), payload, ttl=self.ttl_seconds)
        if not ok:
            raise RuntimeError("failed to store OAuth connected-account handoff")
        return OAuthRefreshTokenHandoff(handoff_id=handoff_id, expires_at=expires_at)

    async def claim_handoff(
        self,
        *,
        handoff_id: str,
        user_id: str,
        user_vault_key_id: str,
    ) -> ClaimedOAuthRefreshTokenHandoff:
        """Return the decrypted handoff payload once to the owning user, then delete it."""

        cache_key = self._handoff_key(handoff_id)
        payload = await self.cache.get(cache_key)
        if not payload:
            raise PermissionError("OAuth handoff expired or not found")
        if payload.get("user_id") != user_id:
            raise PermissionError("OAuth handoff owner mismatch")

        encrypted_payload = payload.get("encrypted_handoff_payload")
        if not encrypted_payload:
            raise PermissionError("OAuth handoff payload missing")
        plaintext_payload = await self.encryption.decrypt_with_user_key(
            encrypted_payload,
            user_vault_key_id,
        )
        await self.cache.delete(cache_key)
        handoff = json.loads(plaintext_payload)
        refresh_token_bundle = handoff.get("refresh_token_bundle")
        if not isinstance(refresh_token_bundle, dict) or not refresh_token_bundle.get("refresh_token"):
            raise PermissionError("OAuth handoff refresh-token bundle missing")
        account_hint = handoff.get("account_hint") if isinstance(handoff.get("account_hint"), dict) else {}
        return ClaimedOAuthRefreshTokenHandoff(
            provider_id=str(handoff.get("provider_id") or ""),
            refresh_token_bundle=refresh_token_bundle,
            account_hint=account_hint,
            expires_at=int(handoff.get("expires_at") or payload.get("expires_at") or 0),
        )

    @staticmethod
    def _handoff_key(handoff_id: str) -> str:
        return f"{OAUTH_HANDOFF_PREFIX}{handoff_id}"
