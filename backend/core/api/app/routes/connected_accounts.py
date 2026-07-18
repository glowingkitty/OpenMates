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
from uuid import uuid4
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.core.api.app.services.connected_accounts_service import (
    ConnectedAccountRow,
    complete_pending_local_connector_request,
    find_plaintext_connected_account_fields,
)
from backend.core.api.app.models.user import User
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.oauth import exchange_google_refresh_token

if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService

router = APIRouter(prefix="/v1/connected-accounts", tags=["Connected Accounts"])
TEAM_CONNECTED_ACCOUNTS_DISABLED = "TEAM_CONNECTED_ACCOUNTS_DISABLED"


async def get_current_user(request: Request, response: Response) -> User:
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user as get_authenticated_user

    return await get_authenticated_user(
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
        response=response,
        request=request,
    )


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


class LocalConnectorRegistrationResponse(BaseModel):
    connected_account_id: str
    connector_session_id: str
    heartbeat_interval_ms: int
    status: str


class LocalConnectorHeartbeatRequest(BaseModel):
    connected_account_id: str
    status: str
    capabilities: list[str] = Field(default_factory=list)
    health_summary: dict[str, Any] = Field(default_factory=dict)


class LocalConnectorHeartbeatResponse(BaseModel):
    accepted: bool
    status: str
    next_heartbeat_deadline_at: int


class LocalConnectorCompleteRequest(BaseModel):
    connected_account_id: str
    request_id: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class LocalConnectorCompleteResponse(BaseModel):
    accepted: bool
    request_id: str
    status: str


def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, "directus_service"):
        raise HTTPException(status_code=500, detail="Directus service unavailable")
    return request.app.state.directus_service


def _hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()


def _hash_team_id(team_id: str) -> str:
    return hashlib.sha256(team_id.encode()).hexdigest()


def _sync_version() -> int:
    return int(time.time())


def _assert_owner_hash(payload: dict[str, Any], hashed_user_id: str) -> None:
    if payload.get("hashed_user_id") != hashed_user_id:
        raise HTTPException(status_code=403, detail="Connected account owner hash does not match current user")


async def _require_team_role(directus_service: DirectusService, team_id: str | None, user_id: str, roles: set[str]) -> None:
    del directus_service, user_id, roles
    if not team_id:
        return
    raise HTTPException(status_code=501, detail=TEAM_CONNECTED_ACCOUNTS_DISABLED)


def _context_filter(hashed_user_id: str, team_id: str | None) -> dict[str, Any]:
    if team_id:
        return {"filter[hashed_team_id][_eq]": _hash_team_id(team_id)}
    return {"filter[hashed_user_id][_eq]": hashed_user_id, "filter[hashed_team_id][_null]": True}


def _apply_storage_context(payload: dict[str, Any], hashed_user_id: str, team_id: str | None) -> dict[str, Any]:
    if team_id:
        expected_team_hash = _hash_team_id(team_id)
        if payload.get("hashed_team_id") not in (None, expected_team_hash):
            raise HTTPException(status_code=403, detail="Connected account team hash does not match requested team")
        return {**payload, "hashed_user_id": hashed_user_id, "hashed_team_id": expected_team_hash}
    if payload.get("hashed_team_id"):
        raise HTTPException(status_code=403, detail="team_id is required for team connected account rows")
    _assert_owner_hash(payload, hashed_user_id)
    return {**payload, "hashed_team_id": None}


def _reject_plaintext_fields(payload: dict[str, Any]) -> None:
    plaintext_fields = find_plaintext_connected_account_fields(payload)
    if plaintext_fields:
        raise HTTPException(
            status_code=400,
            detail="connected account payload contains plaintext provider/account fields: "
            + ", ".join(plaintext_fields),
        )


def _local_connector_session_id() -> str:
    return f"lcs_{uuid4().hex}"


def _local_connector_heartbeat_deadline(now: int) -> int:
    return now + 60


def _local_connector_registered_capabilities(row: dict[str, Any]) -> set[str]:
    public_metadata = row.get("connector_public_metadata") or {}
    if not isinstance(public_metadata, dict):
        return set()
    capabilities = public_metadata.get("capabilities") or []
    if not isinstance(capabilities, list):
        return set()
    return {str(capability) for capability in capabilities}


async def _load_owned_account(
    *,
    directus_service: DirectusService,
    account_id: str,
    hashed_user_id: str,
    team_id: str | None = None,
) -> dict[str, Any]:
    rows = await directus_service.get_items(
        "connected_accounts",
        params={
            "filter[id][_eq]": account_id,
            **_context_filter(hashed_user_id, team_id),
            "limit": 1,
        },
    )
    if not rows:
        raise HTTPException(status_code=403, detail="Connected account not found for current user")
    return rows[0]


@router.get("", response_model=ConnectedAccountListResponse)
async def list_connected_accounts(
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ConnectedAccountListResponse:
    hashed_user_id = _hash_user_id(current_user.id)
    await _require_team_role(directus_service, team_id, current_user.id, {"owner", "admin", "member", "viewer"})
    rows = await directus_service.get_items(
        "connected_accounts",
        params=_context_filter(hashed_user_id, team_id),
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
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ConnectedAccountRowResponse:
    hashed_user_id = _hash_user_id(current_user.id)
    team_id = team_id or body.get("team_id")
    await _require_team_role(directus_service, team_id, current_user.id, {"owner", "admin", "member"})
    body = _apply_storage_context({key: value for key, value in body.items() if key != "team_id"}, hashed_user_id, team_id)
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


@router.post("/local-connectors", response_model=LocalConnectorRegistrationResponse)
async def register_local_connected_account_connector(
    body: dict[str, Any],
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> LocalConnectorRegistrationResponse:
    hashed_user_id = _hash_user_id(current_user.id)
    team_id = team_id or body.get("team_id")
    await _require_team_role(directus_service, team_id, current_user.id, {"owner", "admin", "member"})
    body = _apply_storage_context({key: value for key, value in body.items() if key != "team_id"}, hashed_user_id, team_id)
    session_id = _local_connector_session_id()
    now = _sync_version()
    payload = body | {
        "execution_mode": "local_connector",
        "encrypted_refresh_token_bundle": None,
        "connector_status": "online",
        "local_connector_session_id": session_id,
        "local_connector_last_heartbeat_at": now,
        "local_connector_deadline_at": _local_connector_heartbeat_deadline(now),
        "updated_at": now,
    }
    try:
        row = ConnectedAccountRow.validate_for_storage(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stored_payload = row.__dict__ | {
        "created_at": now,
        "updated_at": now,
    }
    result = await directus_service.create_item("connected_accounts", stored_payload)
    if isinstance(result, tuple):
        success, data = result
        if not success:
            raise HTTPException(status_code=502, detail="Failed to store local connected account")
        stored = data or stored_payload
    else:
        stored = result or stored_payload
    return LocalConnectorRegistrationResponse(
        connected_account_id=str(stored.get("id", row.id)),
        connector_session_id=session_id,
        heartbeat_interval_ms=25_000,
        status="online",
    )


@router.post("/local-connectors/{connector_session_id}/heartbeat", response_model=LocalConnectorHeartbeatResponse)
async def local_connected_account_connector_heartbeat(
    connector_session_id: str,
    body: LocalConnectorHeartbeatRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> LocalConnectorHeartbeatResponse:
    _reject_plaintext_fields(body.model_dump())
    hashed_user_id = _hash_user_id(current_user.id)
    await _require_team_role(directus_service, team_id, current_user.id, {"owner", "admin", "member"})
    row = await _load_owned_account(
        directus_service=directus_service,
        account_id=body.connected_account_id,
        hashed_user_id=hashed_user_id,
        team_id=team_id,
    )
    if row.get("execution_mode") != "local_connector" or row.get("local_connector_session_id") != connector_session_id:
        raise HTTPException(status_code=403, detail="Local connector session does not belong to this account")
    if row.get("connector_status") == "revoked":
        raise HTTPException(status_code=409, detail="Local connector account was revoked")
    if body.status not in {"online", "offline"}:
        raise HTTPException(status_code=400, detail="Local connector heartbeat status is invalid")
    registered_capabilities = _local_connector_registered_capabilities(row)
    heartbeat_capabilities = {str(capability) for capability in body.capabilities}
    if not heartbeat_capabilities.issubset(registered_capabilities):
        raise HTTPException(status_code=400, detail="Local connector heartbeat capabilities exceed registration")
    now = _sync_version()
    deadline = _local_connector_heartbeat_deadline(now)
    await directus_service.update_item(
        "connected_accounts",
        body.connected_account_id,
        {
            "connector_status": body.status,
            "local_connector_last_heartbeat_at": now,
            "local_connector_deadline_at": deadline,
            "connector_public_metadata": (row.get("connector_public_metadata") or {}) | {
                "health_summary": body.health_summary,
                "capabilities": body.capabilities,
            },
            "updated_at": now,
        },
    )
    return LocalConnectorHeartbeatResponse(
        accepted=True,
        status=body.status,
        next_heartbeat_deadline_at=deadline,
    )


@router.post("/local-connectors/{connector_session_id}/complete-request", response_model=LocalConnectorCompleteResponse)
async def complete_local_connected_account_connector_request(
    connector_session_id: str,
    body: LocalConnectorCompleteRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> LocalConnectorCompleteResponse:
    _reject_plaintext_fields(body.model_dump())
    hashed_user_id = _hash_user_id(current_user.id)
    await _require_team_role(directus_service, team_id, current_user.id, {"owner", "admin", "member"})
    row = await _load_owned_account(
        directus_service=directus_service,
        account_id=body.connected_account_id,
        hashed_user_id=hashed_user_id,
        team_id=team_id,
    )
    if row.get("execution_mode") != "local_connector" or row.get("local_connector_session_id") != connector_session_id:
        raise HTTPException(status_code=403, detail="Local connector session does not belong to this account")
    if row.get("connector_status") == "revoked":
        raise HTTPException(status_code=409, detail="Local connector account was revoked")
    if body.status not in {"ok", "error", "cancelled"}:
        raise HTTPException(status_code=400, detail="Local connector request status is invalid")
    try:
        completed = await complete_pending_local_connector_request(
            connector_session_id=connector_session_id,
            request_id=body.request_id,
            status=body.status,
            result=body.result,
            error_code=body.error_code,
            error_message=body.error_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not completed:
        raise HTTPException(status_code=404, detail="Local connector request was not found or expired")
    return LocalConnectorCompleteResponse(
        accepted=True,
        request_id=body.request_id,
        status=body.status,
    )


@router.patch("/{account_id}", response_model=ConnectedAccountRowResponse)
async def update_connected_account(
    account_id: str,
    body: dict[str, Any],
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ConnectedAccountRowResponse:
    hashed_user_id = _hash_user_id(current_user.id)
    team_id = team_id or body.get("team_id")
    await _require_team_role(directus_service, team_id, current_user.id, {"owner", "admin", "member"})
    if not team_id and "hashed_user_id" in body:
        _assert_owner_hash(body, hashed_user_id)
    _reject_plaintext_fields(body)
    await _load_owned_account(
        directus_service=directus_service,
        account_id=account_id,
        hashed_user_id=hashed_user_id,
        team_id=team_id,
    )
    payload = {key: value for key, value in body.items() if key not in {"id", "hashed_user_id", "hashed_team_id", "team_id"}}
    payload["updated_at"] = _sync_version()
    updated = await directus_service.update_item("connected_accounts", account_id, payload)
    if not updated:
        raise HTTPException(status_code=502, detail="Failed to update connected account")
    return ConnectedAccountRowResponse(
        id=account_id,
        sync_version=int(updated.get("updated_at") or payload["updated_at"]),
    )
