"""Settings endpoints for the one-time E2B upload consent decision.

Access classification: first-party client surface only (session auth through
get_current_user, owner-scoped, never developer API keys). The client-encrypted
data stays first-party; the SDK sends its consent per request instead.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_current_user,
    get_directus_service,
)
from backend.core.api.app.services import e2b_upload_consent as consent
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter

router = APIRouter(prefix="/v1", tags=["Settings"])


class E2bUploadConsentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allowed", "declined"]


@router.get("/settings/e2b-upload-consent", include_in_schema=False)
@limiter.limit("30/minute")
async def get_e2b_upload_consent(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus: DirectusService = Depends(get_directus_service),
) -> dict[str, Any]:
    return await consent.get_decision(current_user.id, directus)


@router.put("/settings/e2b-upload-consent", include_in_schema=False)
@limiter.limit("10/minute")
async def put_e2b_upload_consent(
    request: Request,
    body: E2bUploadConsentBody,
    current_user: User = Depends(get_current_user),
    directus: DirectusService = Depends(get_directus_service),
) -> dict[str, Any]:
    return await consent.record_decision(current_user.id, body.decision, directus)
