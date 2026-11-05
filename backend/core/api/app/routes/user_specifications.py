"""First-party encrypted Specifications in an authorized Project.

Session and approved paired-device callers use the existing Project scopes.
These routes are excluded from public API documentation/allowlists. No inference,
paid work, plaintext content or decryption keys are accepted by this surface.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.user_specification_service import SpecificationError, UserSpecificationService

router = APIRouter(prefix="/v1/projects/{project_id}/specifications", tags=["Project Specifications"],
                   dependencies=[Depends(ensure_projects_enabled)])
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Cipher = Annotated[str, Field(min_length=1, max_length=4 * 1024 * 1024)]


class SpecificationKeyWrapper(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_type: Literal["master", "project", "team"]
    encrypted_specification_key: str = Field(min_length=1, max_length=16384)
    hashed_project_id: Hash | None = None
    hashed_team_id: Hash | None = None
    team_key_epoch: int | None = Field(default=None, ge=1)


class SpecificationRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: UUID
    content_hash: Hash
    project_surface_catalog_revision_id: str = Field(min_length=1, max_length=255)
    encrypted_title: str = Field(min_length=1, max_length=16384)
    encrypted_summary: str = Field(min_length=1, max_length=16384)
    encrypted_specification_document: Cipher


class SpecificationCreateInput(SpecificationRevisionInput):
    specification_id: UUID
    key_wrappers: list[SpecificationKeyWrapper] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_wrappers(self):
        contexts = [(wrapper.key_type, wrapper.hashed_project_id, wrapper.hashed_team_id) for wrapper in self.key_wrappers]
        if len(contexts) != len(set(contexts)):
            raise ValueError("Key wrapper contexts must be unique")
        return self


class SpecificationReviseInput(SpecificationRevisionInput):
    base_revision_id: UUID


class SpecificationApproveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: UUID
    content_hash: Hash


async def _service(request: Request, user: User, team_id: str | None, *, write: bool = False):
    directus = request.app.state.directus_service
    if team_id:
        try:
            await directus.team.require_team_role(team_id, user.id,
                                                  {"owner", "admin", "member"} if write else {"owner", "admin", "member", "viewer"})
        except TeamPermissionError as exc:
            raise HTTPException(status_code=403, detail={"error": "team_permission_denied"}) from exc
    return UserSpecificationService(directus)


def _error(exc: SpecificationError):
    return HTTPException(status_code=exc.status_code, detail={"error": exc.code})


@router.get("")
@limiter.limit("60/minute")
async def list_specifications(request: Request, project_id: UUID, team_id: str | None = None,
                              limit: int = Query(50, ge=1, le=100), after: UUID | None = None,
                              user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id)
    try:
        return await service.list_specifications(str(project_id), user.id, team_id=team_id, limit=limit,
                                                 after=str(after) if after else None)
    except SpecificationError as exc:
        raise _error(exc) from exc


@router.post("", status_code=201)
@limiter.limit("30/minute")
async def create_specification(request: Request, project_id: UUID, body: SpecificationCreateInput,
                               team_id: str | None = None, user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.mutate("create", str(project_id), str(body.specification_id), user.id,
                                    body.model_dump(mode="json", exclude_none=True), team_id=team_id)
    except SpecificationError as exc:
        raise _error(exc) from exc


@router.get("/{specification_id}")
@limiter.limit("60/minute")
async def get_specification(request: Request, project_id: UUID, specification_id: UUID,
                            revision_id: UUID | None = None, team_id: str | None = None,
                            user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id)
    try:
        return await service.detail(str(project_id), str(specification_id), user.id, team_id=team_id,
                                     revision_id=str(revision_id) if revision_id else None)
    except SpecificationError as exc:
        raise _error(exc) from exc


@router.get("/{specification_id}/revisions")
@limiter.limit("60/minute")
async def list_specification_revisions(request: Request, project_id: UUID, specification_id: UUID,
                                       team_id: str | None = None, limit: int = Query(50, ge=1, le=100),
                                       before: int | None = Query(None, ge=1),
                                       user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id)
    try:
        return await service.revisions(str(project_id), str(specification_id), user.id,
                                        team_id=team_id, limit=limit, before=before)
    except SpecificationError as exc:
        raise _error(exc) from exc


@router.post("/{specification_id}/revisions")
@limiter.limit("30/minute")
async def revise_specification(request: Request, project_id: UUID, specification_id: UUID,
                               body: SpecificationReviseInput, team_id: str | None = None,
                               user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.mutate("revise", str(project_id), str(specification_id), user.id,
                                    body.model_dump(mode="json"), team_id=team_id)
    except SpecificationError as exc:
        raise _error(exc) from exc


@router.post("/{specification_id}/approve")
@limiter.limit("20/minute")
async def approve_specification(request: Request, project_id: UUID, specification_id: UUID,
                                body: SpecificationApproveInput, team_id: str | None = None,
                                user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.mutate("approve", str(project_id), str(specification_id), user.id,
                                    body.model_dump(mode="json"), team_id=team_id)
    except SpecificationError as exc:
        raise _error(exc) from exc
