"""Account Export V1 API routes.

Purpose: expose a resumable personal export job contract for CLI, SDKs, web,
and later Apple parity.
Architecture: docs/specs/account-export-v1/spec.yml.
Security: authenticates by session or API key and scopes every job to one user.
Privacy: partial and failed exports are explicit and never update last_export_at.
Access: first-party/session or approved API-key REST; no AI credits consumed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_current_user_or_api_key,
    get_directus_service,
)
from backend.core.api.app.services.account_export_service import (
    AccountExportAuthorizationError,
    AccountExportError,
    AccountExportFilterError,
    AccountExportNotFoundError,
    AccountExportService,
)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter


router = APIRouter(prefix="/v1/account-exports", tags=["Account Exports"])
logger = logging.getLogger(__name__)


class AccountExportStartRequest(BaseModel):
    domains: list[str] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    format: Literal["zip", "directory"] = "zip"
    include_advanced_metadata: bool = False
    team_id: str | None = None
    defer_build: bool = False


async def _build_deferred_account_export(
    service: AccountExportService,
    *,
    user_id: str,
    export_id: str,
    team_id: str | None,
) -> None:
    try:
        await service.build_export(user_id=user_id, export_id=export_id, team_id=team_id)
    except Exception:
        logger.exception("Deferred account export build failed", extra={"export_id": export_id})


def _schedule_deferred_account_export(
    request: Request,
    service: AccountExportService,
    *,
    user_id: str,
    export_id: str,
    team_id: str | None,
) -> None:
    task = asyncio.create_task(
        _build_deferred_account_export(
            service,
            user_id=user_id,
            export_id=export_id,
            team_id=team_id,
        )
    )
    tasks = getattr(request.app.state, "account_export_build_tasks", None)
    if not isinstance(tasks, set):
        tasks = set()
        request.app.state.account_export_build_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


class AccountExportFailureRequest(BaseModel):
    domain: str
    item_id: str
    reason: str


class AccountExportJobResponse(BaseModel):
    export: dict[str, Any]


class AccountExportManifestResponse(BaseModel):
    manifest: dict[str, Any]


class AccountExportChunksResponse(BaseModel):
    chunks: list[dict[str, Any]]


class AccountExportChunkResponse(BaseModel):
    chunk: dict[str, Any]


def get_account_export_service(
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
) -> AccountExportService:
    if not hasattr(request.app.state, "account_export_jobs"):
        request.app.state.account_export_jobs = {}
    return AccountExportService(
        directus_service=directus_service,
        jobs=request.app.state.account_export_jobs,
    )


@router.post("", response_model=AccountExportJobResponse)
@limiter.limit("5/hour")
async def start_account_export(
    payload: AccountExportStartRequest,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportJobResponse:
    try:
        export = await service.start_export(
            user_id=current_user.id,
            domains=payload.domains,
            filters=payload.filters,
            include_advanced_metadata=payload.include_advanced_metadata,
            output_format=payload.format,
            team_id=payload.team_id,
            build_immediately=not payload.defer_build,
        )
        if payload.defer_build:
            export_id = str(export.get("export_id") or "")
            if export_id:
                _schedule_deferred_account_export(
                    request,
                    service,
                    user_id=current_user.id,
                    export_id=export_id,
                    team_id=payload.team_id,
                )
        return AccountExportJobResponse(export=export)
    except AccountExportFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{export_id}", response_model=AccountExportJobResponse)
@limiter.limit("60/minute")
async def get_account_export(
    export_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportJobResponse:
    del request
    try:
        return AccountExportJobResponse(export=await service.get_job(user_id=current_user.id, export_id=export_id, team_id=team_id))
    except AccountExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{export_id}/manifest", response_model=AccountExportManifestResponse)
@limiter.limit("60/minute")
async def get_account_export_manifest(
    export_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportManifestResponse:
    del request
    try:
        return AccountExportManifestResponse(manifest=await service.get_manifest(user_id=current_user.id, export_id=export_id, team_id=team_id))
    except AccountExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{export_id}/chunks", response_model=AccountExportChunksResponse)
@limiter.limit("60/minute")
async def list_account_export_chunks(
    export_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportChunksResponse:
    del request
    try:
        return AccountExportChunksResponse(chunks=await service.list_chunks(user_id=current_user.id, export_id=export_id, team_id=team_id))
    except AccountExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{export_id}/chunks/{chunk_id}", response_model=AccountExportChunkResponse)
@limiter.limit("60/minute")
async def get_account_export_chunk(
    export_id: str,
    chunk_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportChunkResponse:
    del request
    try:
        chunk = await service.get_chunk(user_id=current_user.id, export_id=export_id, chunk_id=chunk_id, team_id=team_id)
        return AccountExportChunkResponse(chunk=chunk)
    except AccountExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{export_id}/failures", response_model=AccountExportJobResponse)
@limiter.limit("20/minute")
async def record_account_export_failure(
    export_id: str,
    payload: AccountExportFailureRequest,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportJobResponse:
    del request
    try:
        export = await service.record_domain_failure(
            user_id=current_user.id,
            export_id=export_id,
            domain=payload.domain,
            item_id=payload.item_id,
            reason=payload.reason,
            team_id=team_id,
        )
        return AccountExportJobResponse(export=export)
    except AccountExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{export_id}/complete", response_model=AccountExportJobResponse)
@limiter.limit("20/minute")
async def complete_account_export(
    export_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportJobResponse:
    del request
    try:
        return AccountExportJobResponse(export=await service.mark_complete(user_id=current_user.id, export_id=export_id, team_id=team_id))
    except AccountExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{export_id}/accept-partial", response_model=AccountExportJobResponse)
@limiter.limit("20/minute")
async def accept_partial_account_export(
    export_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportJobResponse:
    del request
    try:
        return AccountExportJobResponse(export=await service.accept_partial(user_id=current_user.id, export_id=export_id, team_id=team_id))
    except AccountExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{export_id}/cancel", response_model=AccountExportJobResponse)
@limiter.limit("20/minute")
async def cancel_account_export(
    export_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    service: AccountExportService = Depends(get_account_export_service),
) -> AccountExportJobResponse:
    del request
    try:
        return AccountExportJobResponse(export=await service.cancel_export(user_id=current_user.id, export_id=export_id, team_id=team_id))
    except AccountExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountExportAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
