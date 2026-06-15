# backend/core/api/app/routes/token_broker.py
#
# Active-turn connected-account token broker routes.
# Clients submit refresh-token envelopes for selected connected accounts; the
# broker stores opaque short-lived refs and exchanges only authorized refs later.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.token_broker import TokenBrokerService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.shared.providers.google_calendar.oauth import exchange_google_refresh_token
from backend.shared.python_schemas.user import User

router = APIRouter(prefix="/v1/token-broker", tags=["Token Broker"])


class CreateTurnTokenRefItem(BaseModel):
    """Client-submitted connected-account refresh-token envelope."""

    connected_account_id: str
    app_id: str
    allowed_actions: list[str] = Field(min_length=1)
    refresh_token_envelope: dict[str, Any]
    action_scope: dict[str, Any] | None = None


class CreateTurnTokenRefsRequest(BaseModel):
    """Create turn-token refs for one active chat message."""

    chat_id: str
    message_id: str
    refs: list[CreateTurnTokenRefItem] = Field(min_length=1)


class TurnTokenRefResponse(BaseModel):
    """Opaque turn-token ref returned to the client send pipeline."""

    connected_account_id: str
    app_id: str
    turn_token_ref: str
    expires_at: int


class CreateTurnTokenRefsResponse(BaseModel):
    """Response for created turn-token refs."""

    refs: list[TurnTokenRefResponse]


class ExchangeTurnTokenRefRequest(BaseModel):
    """Exchange one authorized turn-token ref for an access-token handle."""

    turn_token_ref: str
    chat_id: str
    message_id: str
    app_id: str
    action: str
    action_scope: dict[str, Any] | None = None


class ExchangeTurnTokenRefResponse(BaseModel):
    """Opaque access-token handle for provider skill execution."""

    access_token_handle: str
    expires_at: int
    rotated_refresh_token_bundle: dict[str, Any] | None = None


def get_cache_service(request: Request) -> CacheService:
    if not hasattr(request.app.state, "cache_service"):
        raise HTTPException(status_code=500, detail="Cache service unavailable")
    return request.app.state.cache_service


def get_encryption_service(request: Request) -> EncryptionService:
    if not hasattr(request.app.state, "encryption_service"):
        raise HTTPException(status_code=500, detail="Encryption service unavailable")
    return request.app.state.encryption_service


def _require_vault_key_id(current_user: User) -> str:
    vault_key_id = getattr(current_user, "vault_key_id", None)
    if not vault_key_id:
        raise HTTPException(status_code=403, detail="User vault key is required for connected-account token brokerage")
    return str(vault_key_id)


def _build_token_broker(cache_service: CacheService, encryption_service: EncryptionService) -> TokenBrokerService:
    return TokenBrokerService(
        cache_service=cache_service,
        encryption_service=encryption_service,
        exchange_refresh_token=exchange_google_refresh_token,
    )


@router.post("/turn-token-refs", response_model=CreateTurnTokenRefsResponse)
async def create_turn_token_refs(
    body: CreateTurnTokenRefsRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> CreateTurnTokenRefsResponse:
    """Create opaque active-turn refs without exchanging refresh tokens."""

    vault_key_id = _require_vault_key_id(current_user)
    broker = _build_token_broker(cache_service, encryption_service)
    created: list[TurnTokenRefResponse] = []
    for item in body.refs:
        try:
            ref = await broker.create_turn_token_ref(
                user_id=current_user.id,
                user_vault_key_id=vault_key_id,
                connected_account_id=item.connected_account_id,
                chat_id=body.chat_id,
                message_id=body.message_id,
                app_id=item.app_id,
                allowed_actions=item.allowed_actions,
                refresh_token_envelope=item.refresh_token_envelope,
                action_scope=item.action_scope,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        created.append(
            TurnTokenRefResponse(
                connected_account_id=item.connected_account_id,
                app_id=item.app_id,
                turn_token_ref=ref.turn_token_ref,
                expires_at=ref.expires_at,
            )
        )
    return CreateTurnTokenRefsResponse(refs=created)


@router.post("/exchange", response_model=ExchangeTurnTokenRefResponse)
async def exchange_turn_token_ref(
    body: ExchangeTurnTokenRefRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> ExchangeTurnTokenRefResponse:
    """Exchange an already-authorized turn-token ref for an access-token handle."""

    vault_key_id = _require_vault_key_id(current_user)
    broker = _build_token_broker(cache_service, encryption_service)
    try:
        handle = await broker.exchange_turn_token_ref(
            turn_token_ref=body.turn_token_ref,
            user_id=current_user.id,
            user_vault_key_id=vault_key_id,
            chat_id=body.chat_id,
            message_id=body.message_id,
            app_id=body.app_id,
            action=body.action,
            action_scope=body.action_scope,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ExchangeTurnTokenRefResponse(
        access_token_handle=handle.access_token_handle,
        expires_at=handle.expires_at,
        rotated_refresh_token_bundle=handle.rotated_refresh_token_bundle,
    )
