"""First-party Project authoring: session or approved SDK/device auth only.

These encrypted-workspace routes are not added to Caddy's public allowlist.
Project/chat membership, current owner/team write roles and target revisions are
rechecked on assessment, click and save. Paid inference uses existing metering;
no endpoint grants Workflow execution or creates a regular chat.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.routes.workflows import get_workflow_input_service, get_workflow_service
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.project_authoring_service import (
    LegacyProjectFocusDocument, ProjectAuthoringService, ProjectFocusAuthor, ProjectFocusDocument,
    normalize_saved_project_focus_document, validate_history,
)
from backend.core.api.app.services.project_recommendation_service import (
    ProjectAuthoringAccess, ProjectCatalogEntry, ProjectRecommendationService,
)
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationError
from backend.core.api.app.services.workflow_authoring_billing import MeteredJevClient, WorkflowAuthoringBilling
from backend.core.api.app.services.workflow_remote_file_service import WorkflowRemoteFileBinding, WorkflowRemoteFileService
from backend.shared.providers.typesafe.client import JevDecisionClient

class _PrivateAuthoringRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def private_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's union errors include complete private phase/history
                # input. Replace them before shared logging or response encoding.
                raise HTTPException(status_code=422, detail="PROJECT_AUTHORING_INVALID_REQUEST") from None

        return private_handler


router = APIRouter(prefix="/v1/projects/{project_id}/authoring", tags=["Project authoring"],
                   route_class=_PrivateAuthoringRoute, dependencies=[Depends(ensure_projects_enabled)])


class _PrivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HistoryMessage(_PrivateRequest):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)


class RecommendRequest(_PrivateRequest):
    chat_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    catalog: list[ProjectCatalogEntry] = Field(max_length=40)
    history: list[HistoryMessage] = Field(min_length=1, max_length=60)


class InspectRequest(_PrivateRequest):
    assessment_id: str = Field(min_length=36, max_length=36)
    history: list[HistoryMessage] = Field(min_length=1, max_length=60)
    document: ProjectFocusDocument | LegacyProjectFocusDocument


class RemoteBindingRequest(_PrivateRequest):
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    folder_path: str = Field(max_length=2_048)
    file_path: str | None = Field(default=None, max_length=2_048)
    base_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    saved_content: str | None = Field(default=None, max_length=1_048_576)
    workflow_version_id: str | None = Field(default=None, max_length=128)


class StartRequest(_PrivateRequest):
    recommendation_id: str = Field(min_length=36, max_length=36)
    expected_revision: str | None = Field(default=None, max_length=128)
    history: list[HistoryMessage] = Field(min_length=1, max_length=60)
    target: ProjectFocusDocument | LegacyProjectFocusDocument | None = None
    remote_binding: RemoteBindingRequest | None = None
    timezone: str | None = Field(default=None, max_length=80)


class FocusSaveRequest(_PrivateRequest):
    save_operation_id: str = Field(min_length=1, max_length=128)
    project_item_id: str = Field(min_length=1, max_length=128)
    embed_id: str = Field(min_length=1, max_length=128)
    saved_revision: str = Field(min_length=1, max_length=128)
    expected_revision: str | None = Field(default=None, max_length=128)


class WorkflowBindingSaveRequest(_PrivateRequest):
    project_item_id: str = Field(min_length=1, max_length=128)
    saved_item_revision: str = Field(min_length=1, max_length=128)
    workflow_version_id: str = Field(min_length=1, max_length=128)


def get_access(request: Request) -> ProjectAuthoringAccess:
    return ProjectAuthoringAccess(request.app.state.directus_service, request.app.state.cache_service,
                                  get_workflow_service(request))


def get_recommendations(request: Request, current_user: User = Depends(get_current_user_or_api_key)) -> ProjectRecommendationService:
    injected = getattr(request.app.state, "project_recommendation_service", None)
    if injected is not None:
        return injected
    billing = WorkflowAuthoringBilling(user_id=current_user.id, session_id=str(uuid.uuid4()),
                                      app_id="ai", skill_id="project-recommendation")
    return ProjectRecommendationService(access=get_access(request), cache=request.app.state.cache_service,
        jev=MeteredJevClient(JevDecisionClient(secrets_manager=request.app.state.secrets_manager), billing))


def get_authoring(request: Request) -> ProjectAuthoringService:
    service = getattr(request.app.state, "project_authoring_service", None)
    if service is None:
        service = ProjectAuthoringService(access=get_access(request), cache=request.app.state.cache_service,
            workflow_input=get_workflow_input_service(request), focus_author=ProjectFocusAuthor(request.app.state.secrets_manager, request.app.state.directus_service),
            remote_files=getattr(request.app.state, "workflow_remote_file_service", None))
        request.app.state.project_authoring_service = service
        if service.remote_files is None:
            service.remote_files = WorkflowRemoteFileService(get_workflow_service(request), service.execute_source_operation)
    return service


def _history(rows: list[HistoryMessage]) -> list[dict[str, str]]:
    return validate_history([row.model_dump() for row in rows])


def _denial(exc: Exception) -> None:
    if isinstance(exc, ProjectWriteAuthorizationError):
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from None
    # Do not expose provider failures, private drafts or validation input.
    raise HTTPException(status_code=503, detail="PROJECT_AUTHORING_UNAVAILABLE") from None


@router.post("/recommend")
@limiter.limit("10/minute")
async def recommend(request: Request, project_id: str, body: RecommendRequest,
                    current_user: User = Depends(get_current_user_or_api_key),
                    service: ProjectRecommendationService = Depends(get_recommendations)) -> dict[str, Any]:
    try:
        return {"recommendations": await service.assess(user_id=current_user.id, chat_id=body.chat_id,
            project_id=project_id, team_id=body.team_id, catalog=body.catalog, history=_history(body.history),
            vault_key_id=current_user.vault_key_id, message_id=body.message_id)}
    except Exception as exc:
        _denial(exc)


@router.post("/inspect")
@limiter.limit("20/minute")
async def inspect(request: Request, project_id: str, body: InspectRequest,
                  current_user: User = Depends(get_current_user_or_api_key),
                  service: ProjectRecommendationService = Depends(get_recommendations)) -> dict[str, Any]:
    try:
        proposal = await service.inspect_focus(user_id=current_user.id, project_id=project_id,
            assessment_id=body.assessment_id, history=_history(body.history),
            document=normalize_saved_project_focus_document(body.document).model_dump())
        return {"recommendation": proposal}
    except Exception as exc:
        _denial(exc)


@router.post("/jobs", status_code=202)
@limiter.limit("10/minute")
async def start_authoring(request: Request, project_id: str, body: StartRequest,
                          current_user: User = Depends(get_current_user_or_api_key),
                          service: ProjectAuthoringService = Depends(get_authoring)) -> dict[str, Any]:
    try:
        binding = WorkflowRemoteFileBinding(**body.remote_binding.model_dump()) if body.remote_binding else None
        # The binding is transient encrypted-client data; neither YAML nor
        # source paths are retained in the public job metadata.
        return {"job": await service.start(user_id=current_user.id, project_id=project_id,
            recommendation_id=body.recommendation_id, expected_revision=body.expected_revision, history=_history(body.history),
            target=body.target.model_dump() if body.target else None, vault_key_id=current_user.vault_key_id,
            remote_binding=binding, source_write_context={"project_id": project_id,
                "source_id": binding.source_id if binding else None}, timezone=body.timezone)}
    except Exception as exc:
        _denial(exc)


@router.get("/jobs/{job_id}")
@limiter.limit("60/minute")
async def get_job(request: Request, project_id: str, job_id: str,
                  current_user: User = Depends(get_current_user_or_api_key),
                  service: ProjectAuthoringService = Depends(get_authoring)) -> dict[str, Any]:
    try:
        return {"job": await service.get(user_id=current_user.id, project_id=project_id, job_id=job_id)}
    except Exception as exc:
        _denial(exc)


@router.post("/jobs/{job_id}/saved")
@limiter.limit("20/minute")
async def acknowledge_saved(request: Request, project_id: str, job_id: str, body: FocusSaveRequest,
                            current_user: User = Depends(get_current_user_or_api_key),
                            service: ProjectAuthoringService = Depends(get_authoring)) -> dict[str, Any]:
    try:
        return {"job": await service.acknowledge_focus_save(user_id=current_user.id, project_id=project_id,
            job_id=job_id, project_item_id=body.project_item_id, embed_id=body.embed_id,
            saved_revision=body.saved_revision, expected_revision=body.expected_revision,
            save_operation_id=body.save_operation_id)}
    except Exception as exc:
        _denial(exc)


@router.post("/jobs/{job_id}/workflow-saved")
@limiter.limit("20/minute")
async def acknowledge_workflow_saved(request: Request, project_id: str, job_id: str, body: WorkflowBindingSaveRequest,
                                     current_user: User = Depends(get_current_user_or_api_key),
                                     service: ProjectAuthoringService = Depends(get_authoring)) -> dict[str, Any]:
    try:
        return {"job": await service.acknowledge_workflow_binding(user_id=current_user.id, project_id=project_id,
            job_id=job_id, project_item_id=body.project_item_id, saved_item_revision=body.saved_item_revision,
            workflow_version_id=body.workflow_version_id, vault_key_id=current_user.vault_key_id)}
    except Exception as exc:
        _denial(exc)
