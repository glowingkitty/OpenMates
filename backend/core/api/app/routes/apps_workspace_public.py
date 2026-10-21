"""Unauthenticated read-only public Apps inspiration. No paid work on request."""
from typing import Any, Literal

from fastapi import APIRouter, Path, Request, Response

from backend.core.api.app.services.apps_workspace_public_service import AppsWorkspacePublicService
from backend.core.api.app.services.limiter import limiter

router = APIRouter(prefix="/v1/apps/workspace/public", tags=["Apps Workspace"])


@router.get("/{app_id}")
@limiter.limit("60/minute")
async def public_library(request: Request, response: Response,
                         app_id: str = Path(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
                         language: Literal["en", "de"] = "en") -> dict[str, Any]:
    # No CDN/browser result may outlive the24h server gate. Anonymous reads
    # never dispatch jobs, spend credits, inspect cookies or load a user profile.
    response.headers["Cache-Control"] = "no-store"
    return await AppsWorkspacePublicService().library(app_id, language)
