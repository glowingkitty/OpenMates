# backend/core/api/app/routes/connected_accounts.py
#
# Authenticated connected-account encrypted row storage routes.
# Clients remain the source of truth for provider identity and refresh-token
# encryption; the API stores only hash-owned encrypted blobs in Directus.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.connected_accounts_service import (
    ConnectedAccountRow,
    PLAINTEXT_CONNECTED_ACCOUNT_FIELDS,
)
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.models.user import User
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.oauth import exchange_google_refresh_token

router = APIRouter(prefix="/v1/connected-accounts", tags=["Connected Accounts"])


class ConnectedAccountRowResponse(BaseModel):
    id: str
    sync_version: int


class ConnectedAccountListResponse(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class ConnectedAccountImportValidationRequest(BaseModel):
    provider_id: str
    app_id: str
    capabilities: list[str] = Field(default_factory=list)
    refresh_token_envelope: dict[str, Any]


class ConnectedAccountImportValidationResponse(BaseModel):
    valid: bool
    provider_id: str
    app_id: str
    checked_at: int


def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, "directus_service"):
        raise HTTPException(status_code=500, detail="Directus service unavailable")
    return request.app.state.directus_service


def _hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()


def _sync_version() -> int:
    return int(time.time())


def _assert_owner_hash(payload: dict[str, Any], hashed_user_id: str) -> None:
    if payload.get("hashed_user_id") != hashed_user_id:
        raise HTTPException(status_code=403, detail="Connected account owner hash does not match current user")


def _reject_plaintext_fields(payload: dict[str, Any]) -> None:
    plaintext_fields = sorted(key for key in payload if key in PLAINTEXT_CONNECTED_ACCOUNT_FIELDS)
    if plaintext_fields:
        raise HTTPException(
            status_code=400,
            detail="connected account payload contains plaintext provider/account fields: "
            + ", ".join(plaintext_fields),
        )


async def _load_owned_account(
    *,
    directus_service: DirectusService,
    account_id: str,
    hashed_user_id: str,
) -> dict[str, Any]:
    rows = await directus_service.get_items(
        "connected_accounts",
        params={
            "filter[id][_eq]": account_id,
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "limit": 1,
        },
    )
    if not rows:
        raise HTTPException(status_code=403, detail="Connected account not found for current user")
    return rows[0]


@router.get("", response_model=ConnectedAccountListResponse)
async def list_connected_accounts(
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ConnectedAccountListResponse:
    hashed_user_id = _hash_user_id(current_user.id)
    rows = await directus_service.get_items(
        "connected_accounts",
        params={"filter[hashed_user_id][_eq]": hashed_user_id},
    )
    return ConnectedAccountListResponse(rows=rows or [])


@router.post("/validate-import", response_model=ConnectedAccountImportValidationResponse)
async def validate_connected_account_import(
    body: ConnectedAccountImportValidationRequest,
    current_user: User = Depends(get_current_user),
) -> ConnectedAccountImportValidationResponse:
    """Validate an imported refresh-token envelope without persisting it."""

    if body.provider_id != "google_calendar" or body.app_id not in {"calendar", "google_calendar"}:
        raise HTTPException(status_code=400, detail="Unsupported connected account import provider")
    refresh_token = body.refresh_token_envelope.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise HTTPException(status_code=400, detail="Token envelope is malformed")

    try:
        token_response = await exchange_google_refresh_token(
            refresh_token,
            {
                "connected_account_import_validation": True,
                "app_id": "calendar",
                "user_id": current_user.id,
                "capabilities": body.capabilities,
            },
        )
        access_token = token_response.get("access_token")
        if not access_token:
            raise RuntimeError("provider token exchange did not return access_token")
        now = datetime.now(UTC)
        await GoogleCalendarClient(access_token=str(access_token)).list_events(
            calendar_id="primary",
            time_min=now.isoformat().replace("+00:00", "Z"),
            time_max=(now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            max_results=1,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Connected account import validation failed") from exc

    return ConnectedAccountImportValidationResponse(
        valid=True,
        provider_id="google_calendar",
        app_id="calendar",
        checked_at=_sync_version(),
    )


@router.post("", response_model=ConnectedAccountRowResponse)
async def create_connected_account(
    body: dict[str, Any],
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ConnectedAccountRowResponse:
    hashed_user_id = _hash_user_id(current_user.id)
    _assert_owner_hash(body, hashed_user_id)
    try:
        row = ConnectedAccountRow.validate_for_storage(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = row.__dict__ | {"updated_at": _sync_version()}
    result = await directus_service.create_item("connected_accounts", payload)
    if isinstance(result, tuple):
        success, data = result
        if not success:
            raise HTTPException(status_code=502, detail="Failed to store connected account")
        stored = data or payload
    else:
        stored = result or payload
    return ConnectedAccountRowResponse(
        id=str(stored.get("id", row.id)),
        sync_version=int(stored.get("updated_at") or payload["updated_at"]),
    )


@router.patch("/{account_id}", response_model=ConnectedAccountRowResponse)
async def update_connected_account(
    account_id: str,
    body: dict[str, Any],
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ConnectedAccountRowResponse:
    hashed_user_id = _hash_user_id(current_user.id)
    if "hashed_user_id" in body:
        _assert_owner_hash(body, hashed_user_id)
    _reject_plaintext_fields(body)
    await _load_owned_account(
        directus_service=directus_service,
        account_id=account_id,
        hashed_user_id=hashed_user_id,
    )
    payload = {key: value for key, value in body.items() if key not in {"id", "hashed_user_id"}}
    payload["updated_at"] = _sync_version()
    updated = await directus_service.update_item("connected_accounts", account_id, payload)
    if not updated:
        raise HTTPException(status_code=502, detail="Failed to update connected account")
    return ConnectedAccountRowResponse(
        id=account_id,
        sync_version=int(updated.get("updated_at") or payload["updated_at"]),
    )
