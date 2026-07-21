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
from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.services.token_broker import TokenBrokerService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.shared.providers.google_calendar.oauth import exchange_google_refresh_token
from backend.shared.providers.revolut_business.oauth import exchange_revolut_business_refresh_token
from backend.core.api.app.models.user import User
from backend.shared.python_utils.connected_account_registry import is_connected_account_action_allowed

router = APIRouter(prefix="/v1/token-broker", tags=["Token Broker"])
TEAM_CONNECTED_ACCOUNTS_DISABLED = "TEAM_CONNECTED_ACCOUNTS_DISABLED"


class CreateTurnTokenRefItem(BaseModel):
    """Client-submitted connected-account refresh-token envelope."""

    connected_account_id: str
    app_id: str
    provider_id: str | None = None
    allowed_actions: list[str] = Field(min_length=1)
    refresh_token_envelope: dict[str, Any]
    action_scope: dict[str, Any] | None = None


class CreateTurnTokenRefsRequest(BaseModel):
    """Create turn-token refs for one active chat message."""

    chat_id: str
    message_id: str
    refs: list[CreateTurnTokenRefItem] = Field(min_length=1)
    team_id: str | None = None


class TurnTokenRefResponse(BaseModel):
    """Opaque turn-token ref returned to the client send pipeline."""

    connected_account_id: str
    app_id: str
    provider_id: str | None = None
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
    provider_id: str | None = None
    action: str
    action_scope: dict[str, Any] | None = None
    team_id: str | None = None


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


def get_directus_service(request: Request) -> Any:
    if not hasattr(request.app.state, "directus_service"):
        raise HTTPException(status_code=500, detail="Directus service unavailable")
    return request.app.state.directus_service


def _require_vault_key_id(current_user: User) -> str:
    vault_key_id = getattr(current_user, "vault_key_id", None)
    if not vault_key_id:
        raise HTTPException(status_code=403, detail="User vault key is required for connected-account token brokerage")
    return str(vault_key_id)


def _build_token_broker(
    cache_service: CacheService,
    encryption_service: EncryptionService,
    *,
    provider_id: str | None = None,
) -> TokenBrokerService:
    exchange_refresh_token = (
        exchange_revolut_business_refresh_token
        if _normalize_provider_id(provider_id) == "revolut_business"
        else exchange_google_refresh_token
    )
    return TokenBrokerService(
        cache_service=cache_service,
        encryption_service=encryption_service,
        exchange_refresh_token=exchange_refresh_token,
    )


def _normalize_provider_id(value: str | None) -> str:
    if value in {"calendar", "google_calendar"}:
        return "google"
    if value == "finance":
        return "revolut_business"
    return str(value or "google")


async def _assert_connected_account_context(
    *,
    directus_service: Any,
    account_id: str,
    user_id: str,
    team_id: str | None,
    app_id: str,
    provider_id: str | None,
    allowed_actions: list[str],
) -> None:
    if team_id:
        raise HTTPException(status_code=501, detail=TEAM_CONNECTED_ACCOUNTS_DISABLED)
    params = {
        "filter[id][_eq]": account_id,
        "filter[hashed_user_id][_eq]": hash_id(user_id),
        "filter[hashed_team_id][_null]": True,
        "limit": 1,
    }
    rows = await directus_service.get_items("connected_accounts", params=params)
    if not rows:
        raise HTTPException(status_code=403, detail="Connected account not found for current context")
    normalized_provider = _normalize_provider_id(provider_id or app_id)
    provider_hash = rows[0].get("provider_type_hash")
    acceptable_provider_hashes = {
        hash_id(normalized_provider),
        hash_id(str(provider_id or "")),
        hash_id(app_id),
    }
    if provider_hash and provider_hash not in acceptable_provider_hashes:
        raise HTTPException(status_code=403, detail="Connected account provider mismatch")
    invalid_actions = [
        action
        for action in sorted(set(allowed_actions))
        if not is_connected_account_action_allowed(app_id, normalized_provider, action)
    ]
    if invalid_actions:
        raise HTTPException(status_code=400, detail="Connected account action is not supported for this app/provider")


@router.post("/turn-token-refs", response_model=CreateTurnTokenRefsResponse)
async def create_turn_token_refs(
    body: CreateTurnTokenRefsRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    directus_service: Any = Depends(get_directus_service),
) -> CreateTurnTokenRefsResponse:
    """Create opaque active-turn refs without exchanging refresh tokens."""

    vault_key_id = _require_vault_key_id(current_user)
    broker = _build_token_broker(cache_service, encryption_service)
    created: list[TurnTokenRefResponse] = []
    for item in body.refs:
        await _assert_connected_account_context(
            directus_service=directus_service,
            account_id=item.connected_account_id,
            user_id=current_user.id,
            team_id=body.team_id,
            app_id=item.app_id,
            provider_id=item.provider_id,
            allowed_actions=item.allowed_actions,
        )
        try:
            ref = await broker.create_turn_token_ref(
                user_id=current_user.id,
                user_vault_key_id=vault_key_id,
                connected_account_id=item.connected_account_id,
                team_id=body.team_id,
                chat_id=body.chat_id,
                message_id=body.message_id,
                app_id=item.app_id,
                allowed_actions=item.allowed_actions,
                refresh_token_envelope=item.refresh_token_envelope,
                provider_id=item.provider_id,
                action_scope=item.action_scope,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        created.append(
            TurnTokenRefResponse(
                connected_account_id=item.connected_account_id,
                app_id=item.app_id,
                provider_id=ref.provider_id,
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
    directus_service: Any = Depends(get_directus_service),
) -> ExchangeTurnTokenRefResponse:
    """Exchange an already-authorized turn-token ref for an access-token handle."""

    vault_key_id = _require_vault_key_id(current_user)
    if body.team_id:
        raise HTTPException(status_code=501, detail=TEAM_CONNECTED_ACCOUNTS_DISABLED)
    broker = _build_token_broker(cache_service, encryption_service, provider_id=body.provider_id or body.app_id)
    try:
        handle = await broker.exchange_turn_token_ref(
            turn_token_ref=body.turn_token_ref,
            user_id=current_user.id,
            user_vault_key_id=vault_key_id,
            team_id=body.team_id,
            chat_id=body.chat_id,
            message_id=body.message_id,
            app_id=body.app_id,
            action=body.action,
            provider_id=body.provider_id,
            action_scope=body.action_scope,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ExchangeTurnTokenRefResponse(
        access_token_handle=handle.access_token_handle,
        expires_at=handle.expires_at,
        rotated_refresh_token_bundle=handle.rotated_refresh_token_bundle,
    )
