# backend/core/api/app/routes/provider_oauth_figma.py
#
# Figma OAuth adapter for connected accounts (PKCE + confidential code exchange).
# The refresh-token bundle lives only in the generic one-time OAuth handoff; the
# browser is redirected with an opaque handoff id for client-side encryption.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.provider_oauth_google_calendar import (
    _append_handoff_query,
    _webapp_url,
    get_cache_service,
    get_encryption_service,
)
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.connected_account_oauth_handoff import (
    ConnectedAccountOAuthHandoffService,
)
from backend.shared.providers.figma.oauth import (
    FIGMA_AUTHORIZE_URL,
    FigmaOAuthNotConfiguredError,
    exchange_figma_authorization_code,
    fetch_figma_current_user,
    get_figma_oauth_credentials,
    scopes_for_capabilities,
)
from backend.shared.python_utils.connected_account_errors import ConnectedAccountTokenExchangeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/provider-oauth/figma", tags=["Figma OAuth"])

FIGMA_STATE_PREFIX = "connected_account:oauth_state:figma:"
FIGMA_STATE_TTL_SECONDS = 10 * 60
DEFAULT_RETURN_PATH = "/#settings/apps/design"


class FigmaOAuthStartRequest(BaseModel):
    capabilities: list[str] = Field(min_length=1)
    return_path: str | None = None


class FigmaOAuthStartResponse(BaseModel):
    authorization_url: str
    state_expires_at: int
    scopes: list[str]


def _state_key(state: str) -> str:
    return f"{FIGMA_STATE_PREFIX}{state}"


def _redirect_uri(request: Request) -> str:
    return os.getenv("FIGMA_OAUTH_REDIRECT_URI") or str(request.url_for("figma_oauth_callback"))


def _sanitize_return_path(return_path: str | None) -> str:
    if not return_path or not return_path.startswith("/#settings/"):
        return DEFAULT_RETURN_PATH
    if "\n" in return_path or "\r" in return_path:
        return DEFAULT_RETURN_PATH
    if return_path.startswith("/#settings/app_store"):
        return "/#settings/apps" + return_path.removeprefix("/#settings/app_store")
    return return_path


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@router.post("/start", response_model=FigmaOAuthStartResponse)
@limiter.limit("20/minute")
async def figma_oauth_start(
    body: FigmaOAuthStartRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
) -> FigmaOAuthStartResponse:
    """Create single-use state + PKCE verifier and return the Figma consent URL."""

    try:
        scopes = scopes_for_capabilities(body.capabilities)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        client_id, _client_secret = await get_figma_oauth_credentials()
    except FigmaOAuthNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="figma_oauth_not_configured") from exc

    state = f"figma_{secrets.token_urlsafe(24)}"
    code_verifier = secrets.token_urlsafe(64)
    expires_at = int(time.time()) + FIGMA_STATE_TTL_SECONDS
    redirect_uri = _redirect_uri(request)
    ok = await cache_service.set(
        _state_key(state),
        {
            "user_id": current_user.id,
            "capabilities": list(dict.fromkeys(body.capabilities)),
            "scopes": scopes,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "return_path": _sanitize_return_path(body.return_path),
            "webapp_url": _webapp_url(request),
            "expires_at": expires_at,
        },
        ttl=FIGMA_STATE_TTL_SECONDS,
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to store OAuth state")

    authorization_url = FIGMA_AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "state": state,
            "response_type": "code",
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return FigmaOAuthStartResponse(
        authorization_url=authorization_url, state_expires_at=expires_at, scopes=scopes,
    )


@router.get("/callback", name="figma_oauth_callback")
@limiter.limit("30/minute")
async def figma_oauth_callback(
    request: Request,
    code: str,
    state: str,
    current_user: User = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> RedirectResponse:
    """Exchange the Figma code and redirect with only an opaque handoff id."""

    state_payload = await cache_service.get(_state_key(state))
    if not state_payload:
        raise HTTPException(status_code=400, detail="OAuth state expired or not found")
    if state_payload.get("user_id") != current_user.id:
        raise HTTPException(status_code=403, detail="OAuth state owner mismatch")

    # Single use: delete before the exchange so a replayed callback is rejected.
    await cache_service.delete(_state_key(state))
    try:
        token_response = await exchange_figma_authorization_code(
            code=code,
            code_verifier=str(state_payload["code_verifier"]),
            redirect_uri=str(state_payload["redirect_uri"]),
        )
    except FigmaOAuthNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="figma_oauth_not_configured") from exc
    except (ConnectedAccountTokenExchangeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail="Figma OAuth token exchange failed") from exc

    refresh_token = token_response.get("refresh_token")
    access_token = token_response.get("access_token")
    if not refresh_token or not access_token:
        raise HTTPException(status_code=502, detail="Figma OAuth did not return tokens")

    try:
        me = await fetch_figma_current_user(str(access_token))
    except (ConnectedAccountTokenExchangeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail="Figma account lookup failed") from exc

    vault_key_id = getattr(current_user, "vault_key_id", None)
    if not vault_key_id:
        raise HTTPException(status_code=403, detail="User vault key is required for OAuth handoff")

    scopes = list(state_payload.get("scopes") or [])
    capabilities = list(state_payload.get("capabilities") or [])
    handoff_service = ConnectedAccountOAuthHandoffService(
        cache_service=cache_service, encryption_service=encryption_service,
    )
    handoff = await handoff_service.create_handoff(
        user_id=current_user.id,
        user_vault_key_id=str(vault_key_id),
        provider_id="figma",
        refresh_token_bundle={
            "provider": "figma",
            "refresh_token": refresh_token,
            "scope_context": {"scopes": scopes, "capabilities": capabilities},
        },
        account_hint={
            "provider_id": "figma",
            "handle": me.get("handle"),
            "email": me.get("email"),
            "id": me.get("id") or token_response.get("user_id_string"),
            "capabilities": capabilities,
            "scopes": scopes,
        },
    )

    return RedirectResponse(
        url=_append_handoff_query(
            str(state_payload.get("webapp_url") or _webapp_url(request)),
            str(state_payload.get("return_path") or DEFAULT_RETURN_PATH),
            handoff.handoff_id,
        ),
        status_code=303,
    )
