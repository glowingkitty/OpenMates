# backend/core/api/app/routes/provider_oauth_google_calendar.py
#
# Google Calendar OAuth adapter for connected accounts.
# It performs confidential-server code exchange, stores the refresh-token bundle
# only in the generic one-time OAuth handoff, and redirects the browser with an
# opaque handoff id for client-side encryption.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.connected_account_oauth_handoff import (
    ConnectedAccountOAuthHandoffService,
)
from backend.shared.providers.google_calendar.oauth import (
    exchange_google_authorization_code,
    get_google_oauth_credentials,
)

router = APIRouter(prefix="/v1/provider-oauth/google/calendar", tags=["Google Calendar OAuth"])

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_CALENDAR_STATE_PREFIX = "connected_account:oauth_state:google_calendar:"
GOOGLE_CALENDAR_STATE_TTL_SECONDS = 10 * 60
CALENDAR_READ_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleCalendarOAuthStartRequest(BaseModel):
    capabilities: list[str] = Field(min_length=1)
    return_path: str | None = None


class GoogleCalendarOAuthStartResponse(BaseModel):
    authorization_url: str
    state_expires_at: int
    scopes: list[str]


def get_cache_service(request: Request) -> Any:
    if not hasattr(request.app.state, "cache_service"):
        raise HTTPException(status_code=500, detail="Cache service unavailable")
    return request.app.state.cache_service


def get_encryption_service(request: Request) -> Any:
    if not hasattr(request.app.state, "encryption_service"):
        raise HTTPException(status_code=500, detail="Encryption service unavailable")
    return request.app.state.encryption_service


def _redirect_uri(request: Request) -> str:
    return os.getenv("GOOGLE_CALENDAR_OAUTH_REDIRECT_URI") or str(
        request.url_for("google_calendar_oauth_callback")
    )


def _webapp_url() -> str:
    configured = os.getenv("WEBAPP_URL") or os.getenv("PRODUCTION_URL")
    if configured:
        return configured.rstrip("/")
    frontend_urls = os.getenv("FRONTEND_URLS", "").split(",")
    for url in frontend_urls:
        clean = url.strip()
        if clean.startswith("https://") or clean.startswith("http://"):
            return clean.rstrip("/")
    return "https://app.dev.openmates.org"


def _sanitize_return_path(return_path: str | None) -> str:
    if not return_path or not return_path.startswith("/#settings/"):
        return "/#settings/apps/calendar"
    if "\n" in return_path or "\r" in return_path:
        return "/#settings/apps/calendar"
    if return_path.startswith("/#settings/app_store"):
        return "/#settings/apps" + return_path.removeprefix("/#settings/app_store")
    return return_path


def _append_handoff_query(base_url: str, return_path: str, handoff_id: str) -> str:
    target = base_url + return_path
    parsed = urlsplit(target)
    query = urlencode({"oauth_handoff_id": handoff_id})
    if parsed.query:
        query = f"{parsed.query}&{query}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def google_calendar_scopes_for_capabilities(capabilities: list[str]) -> list[str]:
    normalized = {capability.strip().lower() for capability in capabilities}
    unsupported = normalized - {"read", "write", "delete"}
    if unsupported:
        raise ValueError("unsupported Google Calendar capability: " + ", ".join(sorted(unsupported)))
    if "write" in normalized or "delete" in normalized:
        return [CALENDAR_EVENTS_SCOPE]
    if "read" in normalized:
        return [CALENDAR_READ_SCOPE]
    raise ValueError("at least one Calendar capability is required")


@router.post("/start", response_model=GoogleCalendarOAuthStartResponse)
async def start_google_calendar_oauth(
    body: GoogleCalendarOAuthStartRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
) -> GoogleCalendarOAuthStartResponse:
    """Create an owner-bound OAuth state and return Google consent URL."""

    try:
        scopes = google_calendar_scopes_for_capabilities(body.capabilities)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        client_id, _client_secret = await get_google_oauth_credentials()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Google OAuth client credentials are not configured") from exc

    state = f"gcal_{secrets.token_urlsafe(24)}"
    expires_at = int(time.time()) + GOOGLE_CALENDAR_STATE_TTL_SECONDS
    redirect_uri = _redirect_uri(request)
    state_payload = {
        "user_id": current_user.id,
        "capabilities": body.capabilities,
        "scopes": scopes,
        "redirect_uri": redirect_uri,
        "return_path": _sanitize_return_path(body.return_path),
        "expires_at": expires_at,
    }
    ok = await cache_service.set(
        _state_key(state),
        state_payload,
        ttl=GOOGLE_CALENDAR_STATE_TTL_SECONDS,
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to store OAuth state")

    authorization_url = GOOGLE_AUTHORIZATION_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    return GoogleCalendarOAuthStartResponse(
        authorization_url=authorization_url,
        state_expires_at=expires_at,
        scopes=scopes,
    )


@router.get("/callback", name="google_calendar_oauth_callback")
async def google_calendar_oauth_callback(
    request: Request,
    code: str,
    state: str,
    current_user: User = Depends(get_current_user),
    cache_service: Any = Depends(get_cache_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> RedirectResponse:
    """Exchange Google code and redirect browser with only an opaque handoff id."""

    state_payload = await cache_service.get(_state_key(state))
    if not state_payload:
        raise HTTPException(status_code=400, detail="OAuth state expired or not found")
    if state_payload.get("user_id") != current_user.id:
        raise HTTPException(status_code=403, detail="OAuth state owner mismatch")

    await cache_service.delete(_state_key(state))
    try:
        token_response = await exchange_google_authorization_code(
            code=code,
            redirect_uri=str(state_payload["redirect_uri"]),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Google OAuth token exchange failed") from exc

    refresh_token = token_response.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=502, detail="Google OAuth did not return a refresh token")

    vault_key_id = getattr(current_user, "vault_key_id", None)
    if not vault_key_id:
        raise HTTPException(status_code=403, detail="User vault key is required for OAuth handoff")

    handoff_service = ConnectedAccountOAuthHandoffService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )
    handoff = await handoff_service.create_handoff(
        user_id=current_user.id,
        user_vault_key_id=str(vault_key_id),
        provider_id="google_calendar",
        refresh_token_bundle={
            "provider": "google_calendar",
            "refresh_token": refresh_token,
            "scopes": state_payload.get("scopes") or [],
            "token_type": token_response.get("token_type"),
        },
        account_hint={
            "provider_id": "google_calendar",
            "capabilities": state_payload.get("capabilities") or [],
            "scopes": state_payload.get("scopes") or [],
        },
    )

    return RedirectResponse(
        url=_append_handoff_query(
            _webapp_url(),
            str(state_payload.get("return_path") or "/#settings/apps/calendar"),
            handoff.handoff_id,
        ),
        status_code=303,
    )


def _state_key(state: str) -> str:
    return f"{GOOGLE_CALENDAR_STATE_PREFIX}{state}"
