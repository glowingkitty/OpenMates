"""First-party session-only private Apps library (never public/API-key REST).

Owner and Team role checks occur on every read/write; no paid work starts from
these endpoints. Background work has its own durable claims and credit cap.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.apps_workspace import _session_rate_key
from backend.core.api.app.services.apps_workspace_recommendations_service import (
    AppsLibraryUnavailable, AppsWorkspaceRecommendationsService,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.limiter import limiter
from backend.shared.python_utils.private_inference_logging import private_inference_logging

def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(prefix="/v1/apps/workspace/library", tags=["Apps Workspace"],
                   dependencies=[Depends(_no_store)])


class SaveSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_user_id: UUID
    team_id: UUID | None = None
    skill_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=10_000)
    parameters: dict[str, Any]


class LibrarySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_user_id: UUID
    team_id: UUID | None = None
    daily_searches_enabled: bool


def _service(request: Request) -> AppsWorkspaceRecommendationsService:
    # get_current_user also supports developer keys; explicitly close that path.
    if getattr(request.state, "auth_source", None) != "session":
        raise HTTPException(403, "APPS_LIBRARY_SESSION_REQUIRED")
    return AppsWorkspaceRecommendationsService(request.app.state.directus_service,
        request.app.state.encryption_service, registry=getattr(request.app.state, "skill_registry", None))


async def _call(operation: Any) -> dict[str, Any]:
    try:
        with private_inference_logging():
            return await operation
    except TeamPermissionError as exc:
        raise HTTPException(403, "TEAM_PERMISSION_DENIED") from exc
    except AppsLibraryUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{app_id}")
@limiter.limit("60/minute", key_func=_session_rate_key)
async def library(request: Request, app_id: str = Path(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
                  team_id: UUID | None = None, user: User = Depends(get_current_user)) -> dict[str, Any]:
    return await _call(_service(request).library(user.id, app_id, str(team_id) if team_id else None))


@router.post("/{app_id}/saved-searches")
@limiter.limit("20/minute", key_func=_session_rate_key)
async def save_search(body: SaveSearch, request: Request, app_id: str = Path(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
                      user: User = Depends(get_current_user)) -> dict[str, Any]:
    if str(body.expected_user_id) != user.id:
        raise HTTPException(409, "APPS_LIBRARY_ACCOUNT_CHANGED")
    return await _call(_service(request).save_search(user.id, app_id, body.model_dump(mode="json")))


@router.patch("/{app_id}/settings")
@limiter.limit("20/minute", key_func=_session_rate_key)
async def settings(body: LibrarySettings, request: Request, app_id: str = Path(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
                   user: User = Depends(get_current_user)) -> dict[str, Any]:
    if str(body.expected_user_id) != user.id:
        raise HTTPException(409, "APPS_LIBRARY_ACCOUNT_CHANGED")
    return await _call(_service(request).settings(user.id, app_id, body.daily_searches_enabled,
                                                str(body.team_id) if body.team_id else None))


@router.get("/{app_id}/recommendations/{batch_id}")
@limiter.limit("60/minute", key_func=_session_rate_key)
async def recommendation(batch_id: UUID, request: Request, app_id: str = Path(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
                         team_id: UUID | None = None, user: User = Depends(get_current_user)) -> dict[str, Any]:
    result = await _call(_service(request).detail(user.id, app_id, str(batch_id), str(team_id) if team_id else None))
    if result is None:
        raise HTTPException(404, "APPS_RECOMMENDATION_NOT_FOUND")
    return result
