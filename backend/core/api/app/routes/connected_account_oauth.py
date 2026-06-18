# backend/core/api/app/routes/connected_account_oauth.py
#
# Authenticated browser routes for connected-account OAuth bootstrap handoffs.
# Provider-specific adapters create handoffs after confidential code exchange;
# the browser claims them once and immediately stores a client-encrypted row.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.connected_account_oauth_handoff import (
    ConnectedAccountOAuthHandoffService,
)

router = APIRouter(prefix="/v1/connected-account-oauth", tags=["Connected Account OAuth"])


class ClaimOAuthHandoffResponse(BaseModel):
    provider_id: str
    refresh_token_bundle: dict[str, Any]
    account_hint: dict[str, Any]
    expires_at: int


def get_cache_service(request: Request) -> Any:
    if not hasattr(request.app.state, "cache_service"):
        raise HTTPException(status_code=500, detail="Cache service unavailable")
    return request.app.state.cache_service


def get_encryption_service(request: Request) -> Any:
    if not hasattr(request.app.state, "encryption_service"):
        raise HTTPException(status_code=500, detail="Encryption service unavailable")
    return request.app.state.encryption_service


def _require_vault_key_id(current_user: User) -> str:
    vault_key_id = getattr(current_user, "vault_key_id", None)
    if not vault_key_id:
        raise HTTPException(status_code=403, detail="User vault key is required for connected-account OAuth handoff")
    return str(vault_key_id)


def build_oauth_handoff_service(
    cache_service: Any,
    encryption_service: Any,
) -> ConnectedAccountOAuthHandoffService:
    return ConnectedAccountOAuthHandoffService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )


@router.post("/handoffs/{handoff_id}/claim", response_model=ClaimOAuthHandoffResponse)
async def claim_oauth_handoff(
    handoff_id: str,
    current_user: User = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> ClaimOAuthHandoffResponse:
    """Claim one OAuth refresh-token handoff for immediate browser encryption."""

    vault_key_id = _require_vault_key_id(current_user)
    service = build_oauth_handoff_service(cache_service, encryption_service)
    try:
        handoff = await service.claim_handoff(
            handoff_id=handoff_id,
            user_id=current_user.id,
            user_vault_key_id=vault_key_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ClaimOAuthHandoffResponse(
        provider_id=handoff.provider_id,
        refresh_token_bundle=handoff.refresh_token_bundle,
        account_hint=handoff.account_hint,
        expires_at=handoff.expires_at,
    )
