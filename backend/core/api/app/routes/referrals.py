"""
Referral program API routes for authenticated web users.

The browser may capture a public #ref code from the URL fragment, but the server
stores attribution durably and only payment webhooks can grant promotional
credits. These endpoints expose status, referral link data, and code capture.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.referral_service import ReferralService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/referrals", tags=["Referrals"])


def get_directus_service(request: Request) -> DirectusService:
    return request.app.state.directus_service


def get_cache_service(request: Request) -> CacheService:
    return request.app.state.cache_service


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def get_referral_service(
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> ReferralService:
    return ReferralService(directus_service, cache_service, encryption_service)


class ReferralStatusResponse(BaseModel):
    available: bool
    referral_code: Optional[str] = None
    successful_referrals_count: int
    max_successful_referrals: int
    credits_per_referrer: int
    credits_per_referred_user: int
    min_purchase_amount_cents: int
    attribution_expires_days: int


class CaptureReferralRequest(BaseModel):
    referral_code: str


class CaptureReferralResponse(BaseModel):
    accepted: bool
    reason: str


@router.get("/status", response_model=ReferralStatusResponse)
async def get_referral_status(
    current_user: User = Depends(get_current_user),
    referral_service: ReferralService = Depends(get_referral_service),
):
    try:
        return ReferralStatusResponse(**await referral_service.get_status(current_user.id))
    except Exception as exc:
        logger.error("Failed to load referral status for user %s: %s", current_user.id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load referral status")


@router.post("/capture", response_model=CaptureReferralResponse)
async def capture_referral(
    payload: CaptureReferralRequest,
    current_user: User = Depends(get_current_user),
    referral_service: ReferralService = Depends(get_referral_service),
):
    try:
        result = await referral_service.capture_referral(current_user.id, payload.referral_code)
        return CaptureReferralResponse(**result)
    except Exception as exc:
        logger.error("Failed to capture referral for user %s: %s", current_user.id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to capture referral")
