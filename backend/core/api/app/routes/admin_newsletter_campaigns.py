"""Hidden admin API for newsletter campaign scheduling.

Campaigns are authored externally, uploaded through admin API-key auth, previewed
to the admin address, explicitly approved after design review, and only then can
they be scheduled or sent. The router is excluded from public OpenAPI docs.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.admin_debug import require_admin_api_key
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.newsletter_campaign_service import (
    NewsletterCampaignError,
    NewsletterCampaignService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/newsletter-campaigns", tags=["Admin Newsletter Campaigns"])


class NewsletterCampaignPayload(BaseModel):
    slug: str
    mode: str = "email_only"
    category: str
    kind: Optional[str] = None
    demo_chat_category: Optional[str] = None
    chat_id: Optional[str] = None
    public_page_url: Optional[str] = None
    scheduled_for: Optional[str] = None
    timezone: str = "UTC"
    subject: Dict[str, str]
    title: Dict[str, str]
    subtitle: Dict[str, str] = Field(default_factory=dict)
    cta_text: Dict[str, str] = Field(default_factory=dict)
    cta_url: Optional[str] = None
    body_markdown: Dict[str, str]
    video: Optional[Dict[str, Any]] = None
    hero_image: Optional[Dict[str, Any]] = None
    header_icon: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    admin_email: Optional[EmailStr] = None


class ScheduleRequest(BaseModel):
    scheduled_for: str


class SendNowRequest(BaseModel):
    simulate: bool = False


def _service(directus: DirectusService) -> NewsletterCampaignService:
    return NewsletterCampaignService(directus)


def _handle_error(exc: Exception) -> None:
    if isinstance(exc, NewsletterCampaignError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.error("Newsletter campaign admin API failed: %s", exc, exc_info=True)
    raise HTTPException(status_code=500, detail="Newsletter campaign operation failed") from exc


@router.get("")
@limiter.limit("30/minute")
async def list_campaigns(
    request: Request,
    limit: int = 25,
    admin_user: User = Depends(require_admin_api_key),
    directus: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    try:
        campaigns = await _service(directus).list_campaigns(limit=limit)
        return {"success": True, "campaigns": campaigns, "admin_user_id": admin_user.id}
    except Exception as exc:
        _handle_error(exc)


@router.post("")
@limiter.limit("10/minute")
async def upsert_campaign(
    request: Request,
    payload: NewsletterCampaignPayload,
    admin_user: User = Depends(require_admin_api_key),
    directus: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    try:
        campaign = await _service(directus).upsert_campaign(payload.model_dump(), admin_user.id)
        return {"success": True, "campaign": campaign}
    except Exception as exc:
        _handle_error(exc)


@router.get("/{slug}")
@limiter.limit("30/minute")
async def get_campaign(
    request: Request,
    slug: str,
    admin_user: User = Depends(require_admin_api_key),
    directus: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    try:
        campaign = await _service(directus).get_by_slug(slug)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return {"success": True, "campaign": campaign, "admin_user_id": admin_user.id}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_error(exc)


@router.post("/{slug}/preview")
@limiter.limit("5/minute")
async def send_preview(
    request: Request,
    slug: str,
    body: PreviewRequest,
    admin_user: User = Depends(require_admin_api_key),
    directus: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    try:
        admin_email = str(body.admin_email or os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL") or "")
        if not admin_email:
            raise NewsletterCampaignError("admin_email or SERVER_OWNER_EMAIL/ADMIN_NOTIFY_EMAIL is required")
        result = await _service(directus).send_preview(slug, admin_email)
        logger.warning("[ADMIN_NEWSLETTER_PREVIEW] user=%s slug=%s", admin_user.id, slug)
        return {"success": True, **result}
    except Exception as exc:
        _handle_error(exc)


@router.post("/{slug}/approve")
@limiter.limit("10/minute")
async def approve_campaign(
    request: Request,
    slug: str,
    admin_user: User = Depends(require_admin_api_key),
    directus: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    try:
        campaign = await _service(directus).approve_campaign(slug, admin_user.id)
        logger.warning("[ADMIN_NEWSLETTER_APPROVE] user=%s slug=%s", admin_user.id, slug)
        return {"success": True, "campaign": campaign}
    except Exception as exc:
        _handle_error(exc)


@router.post("/{slug}/schedule")
@limiter.limit("10/minute")
async def schedule_campaign(
    request: Request,
    slug: str,
    body: ScheduleRequest,
    admin_user: User = Depends(require_admin_api_key),
    directus: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    try:
        campaign = await _service(directus).schedule_campaign(slug, body.scheduled_for)
        logger.warning("[ADMIN_NEWSLETTER_SCHEDULE] user=%s slug=%s scheduled_for=%s", admin_user.id, slug, body.scheduled_for)
        return {"success": True, "campaign": campaign}
    except Exception as exc:
        _handle_error(exc)


@router.post("/{slug}/send-now")
@limiter.limit("3/minute")
async def send_now(
    request: Request,
    slug: str,
    body: SendNowRequest,
    admin_user: User = Depends(require_admin_api_key),
    directus: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    try:
        result = await _service(directus).send_campaign_now(slug, simulate=body.simulate)
        logger.warning("[ADMIN_NEWSLETTER_SEND_NOW] user=%s slug=%s simulate=%s", admin_user.id, slug, body.simulate)
        return {"success": True, **result}
    except Exception as exc:
        _handle_error(exc)
