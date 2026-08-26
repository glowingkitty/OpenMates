"""First-party encrypted cold archive list, read, and promotion routes.

Every request uses current owner or Team authorization and returns only client
ciphertext plus safe routing metadata. Archive bytes are API-proxied without
presigned URLs, and mutations require generation-fenced promotion.
Spec: docs/specs/regional-cold-storage-lifecycle/spec.yml.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.cold_archive_service import (
    ColdArchiveAuthorizationError,
    ColdArchiveConflictError,
    ColdArchiveCursorError,
    ColdArchiveNotFoundError,
    ColdArchiveService,
)
from backend.core.api.app.services.limiter import limiter


router = APIRouter(prefix="/v1/storage", tags=["Storage"])


class ArchivePromotionRequest(BaseModel):
    expected_generation: int = Field(ge=1)
    mutation_intent: str = Field(min_length=1, max_length=64)
    team_id: str | None = None


def _service(request: Request) -> ColdArchiveService:
    return ColdArchiveService(
        directus_service=request.app.state.directus_service,
        s3_service=request.app.state.s3_service,
    )


def _raise_archive_http_error(exc: Exception) -> None:
    if isinstance(exc, ColdArchiveCursorError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, ColdArchiveAuthorizationError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ColdArchiveNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ColdArchiveConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.get("/archive-index/{resource_type}")
@limiter.limit("30/minute")
async def list_archive_index(
    request: Request,
    resource_type: str,
    team_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await _service(request).list_archives(
            user_id=current_user.id,
            resource_type=resource_type,
            team_id=team_id,
            cursor=cursor,
            limit=limit,
        )
    except (ColdArchiveAuthorizationError, ColdArchiveCursorError) as exc:
        _raise_archive_http_error(exc)


@router.get("/archive-items/{archive_id}/parts/{part_id}")
@limiter.limit("30/minute")
async def read_archive_part(
    request: Request,
    archive_id: str,
    part_id: str,
    generation: int = Query(ge=1),
    team_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    service = _service(request)
    try:
        manifest = await service.get_manifest(archive_id)
        await service.authorize_manifest(manifest, user_id=current_user.id, team_id=team_id, mutation=False)
        part = await service.get_part(archive_id, part_id, generation)
        return StreamingResponse(
            service.stream_archive_part(manifest=manifest, part=part),
            media_type="application/gzip",
            headers={"Cache-Control": "private, no-store"},
        )
    except (ColdArchiveAuthorizationError, ColdArchiveConflictError, ColdArchiveNotFoundError) as exc:
        _raise_archive_http_error(exc)


@router.post("/archive-items/{archive_id}/promote")
@limiter.limit("10/minute")
async def promote_archive(
    request: Request,
    archive_id: str,
    body: ArchivePromotionRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await _service(request).promote_archive(
            archive_id,
            user_id=current_user.id,
            team_id=body.team_id,
            expected_generation=body.expected_generation,
            mutation_intent=body.mutation_intent,
        )
    except (ColdArchiveAuthorizationError, ColdArchiveConflictError, ColdArchiveNotFoundError) as exc:
        _raise_archive_http_error(exc)
