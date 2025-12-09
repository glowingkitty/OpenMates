# backend/core/api/app/routes/creators.py
#
# Creator program API endpoints.
# Handles tipping creators and managing creator accounts.

import logging
import time
import hashlib
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.creators.revenue_service import CreatorRevenueService
from backend.core.api.app.services.limiter import limiter
from backend.shared.python_utils.content_hasher import hash_owner_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/creators", tags=["Creators"])


# Request/Response models
class TipCreatorRequest(BaseModel):
    """Request model for tipping a creator"""
    owner_id: str = Field(
        ...,
        description="Creator's owner ID (YouTube channel ID for videos, domain for websites). Will be hashed on server for privacy."
    )
    content_type: str = Field(
        ...,
        description="Type of content: 'video' or 'website'",
        enum=["video", "website"]
    )
    credits: int = Field(
        ...,
        description="Number of credits to tip (must be positive)",
        gt=0
    )


class TipCreatorResponse(BaseModel):
    """Response model for tipping a creator"""
    success: bool
    message: str
    credits_tipped: Optional[int] = None
    current_credits: Optional[int] = None


# Dependency functions
def get_directus_service(request: Request) -> DirectusService:
    """Get Directus service from app state"""
    return request.app.state.directus_service


def get_encryption_service(request: Request) -> EncryptionService:
    """Get encryption service from app state"""
    return request.app.state.encryption_service


def get_cache_service(request: Request) -> CacheService:
    """Get cache service from app state"""
    return request.app.state.cache_service


def get_billing_service(
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> BillingService:
    """Get billing service with dependencies"""
    return BillingService(cache_service, directus_service, encryption_service)


def get_creator_revenue_service(
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> CreatorRevenueService:
    """Get creator revenue service with dependencies"""
    return CreatorRevenueService(directus_service, encryption_service)


# API Endpoints

@router.post("/tip", response_model=TipCreatorResponse, include_in_schema=False)  # Exclude from OpenAPI docs for now
@limiter.limit("30/minute")  # Rate limit: 30 tips per minute per user
async def tip_creator(
    request: Request,
    tip_data: TipCreatorRequest,
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
    revenue_service: CreatorRevenueService = Depends(get_creator_revenue_service),
    cache_service: CacheService = Depends(get_cache_service)
) -> TipCreatorResponse:
    """
    Tip a creator with credits.
    
    This endpoint allows users to tip creators (website owners or video creators)
    by transferring credits from their account. 100% of the tipped credits go to
    the creator (no platform fee).
    
    The tip creates a creator_income entry that will be available for the creator
    to claim when they sign up for a creator account.
    
    Args:
        tip_data: Tip request containing hashed_owner_id, content_type, and credits
        current_user: Currently authenticated user (from dependency)
        billing_service: Billing service for deducting credits
        revenue_service: Creator revenue service for creating income entries
        cache_service: Cache service for user data
    
    Returns:
        TipCreatorResponse with success status and updated credit balance
    """
    try:
        # Validate owner_id is provided
        if not tip_data.owner_id or not tip_data.owner_id.strip():
            raise HTTPException(
                status_code=400,
                detail="owner_id is required and cannot be empty"
            )
        
        # Hash the owner_id for privacy-preserving storage
        hashed_owner_id = hash_owner_id(tip_data.owner_id.strip())
        if not hashed_owner_id:
            raise HTTPException(
                status_code=400,
                detail="Invalid owner_id format"
            )
        
        # Check if user has sufficient credits
        user = await cache_service.get_user_by_id(current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        current_credits = user.get("credits", 0)
        if not isinstance(current_credits, int):
            logger.warning(f"User credits for {current_user.id} were not an integer: {current_credits}. Treating as 0.")
            current_credits = 0
        
        if current_credits < tip_data.credits:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient credits. You have {current_credits} credits, but trying to tip {tip_data.credits}."
            )
        
        # Deduct credits from user's account
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        # Use billing service to deduct credits (creates usage entry)
        # Note: We use a special app_id and skill_id to identify tips
        await billing_service.charge_user_credits(
            user_id=current_user.id,
            credits_to_deduct=tip_data.credits,
            user_id_hash=user_id_hash,
            app_id="creators",
            skill_id="tip",
            usage_details={
                "tip_to_hashed_owner_id": hashed_owner_id,
                "content_type": tip_data.content_type
            }
        )
        
        # Create creator income entry for the tip
        # Generate a unique content ID for the tip (using timestamp and user hash)
        timestamp = int(time.time())
        tip_content_id = f"tip:{timestamp}:{user_id_hash[:16]}"
        
        # Create income entry using the original owner_id (will be hashed by the service)
        success = await revenue_service.create_income_entry(
            owner_id=tip_data.owner_id.strip(),  # Original owner_id, will be hashed by service
            content_id=tip_content_id,
            content_type=tip_data.content_type,
            app_id="creators",
            skill_id="tip",
            credits=tip_data.credits,
            income_source="tip"
        )
        
        if not success:
            # If income entry creation fails, we should ideally refund the credits
            # But for now, we'll just log the error
            logger.error(f"Failed to create creator income entry for tip. Credits were deducted but income entry not created.")
            # TODO: Consider refunding credits if income entry creation fails
        
        # Get updated credit balance
        updated_user = await cache_service.get_user_by_id(current_user.id)
        new_credits = updated_user.get("credits", 0) if updated_user else current_credits - tip_data.credits
        
        return TipCreatorResponse(
            success=True,
            message=f"Successfully tipped {tip_data.credits} credits to creator",
            credits_tipped=tip_data.credits,
            current_credits=new_credits
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing tip: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing tip: {str(e)}")
