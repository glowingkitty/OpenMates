# backend/core/api/app/services/token_broker.py
#
# Active-turn token broker for connected-account provider actions.
# The broker accepts client-submitted refresh-token envelopes, stores them
# Vault-encrypted under short-lived refs, and lazily exchanges selected refs only
# after permission-broker authorization.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


DEFAULT_TURN_TOKEN_REF_TTL_SECONDS = 5 * 60
DEFAULT_ACCESS_TOKEN_HANDLE_TTL_SECONDS = 5 * 60
TURN_TOKEN_REF_PREFIX = "connected_account:turn_token_ref:"
ACCESS_TOKEN_HANDLE_PREFIX = "connected_account:access_token_handle:"


@dataclass(frozen=True)
class TurnTokenRef:
    """Opaque active-turn ref to a Vault-encrypted refresh-token envelope."""

    turn_token_ref: str
    expires_at: int


@dataclass(frozen=True)
class AccessTokenHandle:
    """Opaque active-turn handle to a Vault-encrypted access token."""

    access_token_handle: str
    expires_at: int
    rotated_refresh_token_bundle: dict[str, Any] | None = None


ExchangeRefreshToken = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class TokenBrokerService:
    """Store token refs and exchange selected refs after exact authorization."""

    def __init__(
        self,
        *,
        cache_service: Any,
        encryption_service: Any,
        exchange_refresh_token: ExchangeRefreshToken,
        turn_token_ref_ttl_seconds: int = DEFAULT_TURN_TOKEN_REF_TTL_SECONDS,
        access_token_handle_ttl_seconds: int = DEFAULT_ACCESS_TOKEN_HANDLE_TTL_SECONDS,
    ) -> None:
        self.cache = cache_service
        self.encryption = encryption_service
        self.exchange_refresh_token = exchange_refresh_token
        self.turn_token_ref_ttl_seconds = turn_token_ref_ttl_seconds
        self.access_token_handle_ttl_seconds = access_token_handle_ttl_seconds

    async def create_turn_token_ref(
        self,
        *,
        user_id: str,
        user_vault_key_id: str,
        connected_account_id: str,
        chat_id: str,
        message_id: str,
        app_id: str,
        allowed_actions: list[str],
        refresh_token_envelope: dict[str, Any],
        action_scope: dict[str, Any] | None = None,
    ) -> TurnTokenRef:
        """Create a short-lived ref without exchanging the refresh token."""

        if not refresh_token_envelope.get("refresh_token"):
            raise ValueError("refresh_token_envelope.refresh_token is required")
        if not allowed_actions:
            raise ValueError("allowed_actions is required")

        token_ref = f"tref_{secrets.token_urlsafe(24)}"
        expires_at = int(time.time()) + self.turn_token_ref_ttl_seconds
        encrypted_envelope, _ = await self.encryption.encrypt_with_user_key(
            json.dumps(refresh_token_envelope),
            user_vault_key_id,
        )
        payload = {
            "user_id": user_id,
            "connected_account_id": connected_account_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "app_id": app_id,
            "allowed_actions": sorted(set(allowed_actions)),
            "action_scope": action_scope or {},
            "encrypted_refresh_token_envelope": encrypted_envelope,
            "expires_at": expires_at,
        }
        ok = await self.cache.set(
            self._turn_token_key(token_ref),
            payload,
            ttl=self.turn_token_ref_ttl_seconds,
        )
        if not ok:
            raise RuntimeError("token broker failed to store turn token ref")
        return TurnTokenRef(turn_token_ref=token_ref, expires_at=expires_at)

    async def exchange_turn_token_ref(
        self,
        *,
        turn_token_ref: str,
        user_id: str,
        user_vault_key_id: str,
        chat_id: str,
        message_id: str,
        app_id: str,
        action: str,
        action_scope: dict[str, Any] | None = None,
    ) -> AccessTokenHandle:
        """Lazily exchange a matching turn-token ref for an access-token handle."""

        payload = await self.cache.get(self._turn_token_key(turn_token_ref))
        if not payload:
            raise PermissionError("turn token ref expired or not found")

        self._assert_scope_matches(
            payload,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            app_id=app_id,
            action=action,
        )
        requested_scope = action_scope or {}
        stored_scope = payload.get("action_scope") or {}
        if stored_scope and requested_scope and stored_scope != requested_scope:
            raise PermissionError("turn token ref action scope mismatch")

        encrypted_envelope = payload.get("encrypted_refresh_token_envelope")
        if not encrypted_envelope:
            raise PermissionError("turn token ref missing encrypted token envelope")

        plaintext_envelope = await self.encryption.decrypt_with_user_key(
            encrypted_envelope,
            user_vault_key_id,
        )
        envelope = json.loads(plaintext_envelope)
        refresh_token = envelope.get("refresh_token")
        if not refresh_token:
            raise PermissionError("turn token ref missing refresh token")

        token_response = await self.exchange_refresh_token(
            str(refresh_token),
            {
                "connected_account_id": payload["connected_account_id"],
                "app_id": app_id,
                "action": action,
                "action_scope": requested_scope or stored_scope,
            },
        )
        access_token = token_response.get("access_token")
        if not access_token:
            raise RuntimeError("provider token exchange did not return access_token")

        handle = f"ath_{secrets.token_urlsafe(24)}"
        expires_at = int(time.time()) + self.access_token_handle_ttl_seconds
        encrypted_access_token, _ = await self.encryption.encrypt_with_user_key(
            str(access_token),
            user_vault_key_id,
        )
        handle_payload = {
            "user_id": user_id,
            "connected_account_id": payload["connected_account_id"],
            "chat_id": chat_id,
            "message_id": message_id,
            "app_id": app_id,
            "action": action,
            "action_scope": requested_scope or stored_scope,
            "encrypted_access_token": encrypted_access_token,
            "expires_at": expires_at,
        }
        ok = await self.cache.set(
            self._access_token_key(handle),
            handle_payload,
            ttl=self.access_token_handle_ttl_seconds,
        )
        if not ok:
            raise RuntimeError("token broker failed to store access token handle")

        rotated = token_response.get("rotated_refresh_token_bundle")
        return AccessTokenHandle(
            access_token_handle=handle,
            expires_at=expires_at,
            rotated_refresh_token_bundle=rotated if isinstance(rotated, dict) else None,
        )

    async def delete_turn_artifacts(
        self,
        turn_token_ref: str | None = None,
        access_token_handle: str | None = None,
    ) -> None:
        """Delete active-turn refs/handles on completion, error, or cancel."""

        if turn_token_ref:
            await self.cache.delete(self._turn_token_key(turn_token_ref))
        if access_token_handle:
            await self.cache.delete(self._access_token_key(access_token_handle))

    async def resolve_access_token_handle(
        self,
        *,
        access_token_handle: str,
        user_id: str,
        user_vault_key_id: str,
        chat_id: str,
        message_id: str,
        app_id: str,
        action: str,
        action_scope: dict[str, Any] | None = None,
    ) -> str:
        """Decrypt a matching short-lived access-token handle for provider calls."""

        payload = await self.cache.get(self._access_token_key(access_token_handle))
        if not payload:
            raise PermissionError("access token handle expired or not found")
        self._assert_access_handle_matches(
            payload,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            app_id=app_id,
            action=action,
        )
        requested_scope = action_scope or {}
        stored_scope = payload.get("action_scope") or {}
        if stored_scope and requested_scope and stored_scope != requested_scope:
            raise PermissionError("access token handle action scope mismatch")
        encrypted_access_token = payload.get("encrypted_access_token")
        if not encrypted_access_token:
            raise PermissionError("access token handle missing encrypted token")
        return await self.encryption.decrypt_with_user_key(
            encrypted_access_token,
            user_vault_key_id,
        )

    def _assert_scope_matches(
        self,
        payload: dict[str, Any],
        *,
        user_id: str,
        chat_id: str,
        message_id: str,
        app_id: str,
        action: str,
    ) -> None:
        if payload.get("user_id") != user_id:
            raise PermissionError("turn token ref owner mismatch")
        if payload.get("chat_id") != chat_id:
            raise PermissionError("turn token ref chat mismatch")
        if payload.get("message_id") != message_id:
            raise PermissionError("turn token ref message mismatch")
        if payload.get("app_id") != app_id:
            raise PermissionError("turn token ref app mismatch")
        if action not in set(payload.get("allowed_actions") or []):
            raise PermissionError("turn token ref action mismatch")

    def _assert_access_handle_matches(
        self,
        payload: dict[str, Any],
        *,
        user_id: str,
        chat_id: str,
        message_id: str,
        app_id: str,
        action: str,
    ) -> None:
        if payload.get("user_id") != user_id:
            raise PermissionError("access token handle owner mismatch")
        if payload.get("chat_id") != chat_id:
            raise PermissionError("access token handle chat mismatch")
        if payload.get("message_id") != message_id:
            raise PermissionError("access token handle message mismatch")
        if payload.get("app_id") != app_id:
            raise PermissionError("access token handle app mismatch")
        if payload.get("action") != action:
            raise PermissionError("access token handle action mismatch")

    @staticmethod
    def _turn_token_key(token_ref: str) -> str:
        return f"{TURN_TOKEN_REF_PREFIX}{token_ref}"

    @staticmethod
    def _access_token_key(handle: str) -> str:
        return f"{ACCESS_TOKEN_HANDLE_PREFIX}{handle}"
