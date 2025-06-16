# backend/core/api/app/routes/internal_api.py
#
# This module defines FastAPI routes for internal services (e.g., apps)
# to communicate with the main API. These endpoints are secured by an
# internal service token.

import logging
from fastapi import APIRouter, HTTPException, Request, Depends, Body
from typing import Dict, Any, Optional
from pydantic import BaseModel # Ensure BaseModel is imported for Pydantic models
import os # For os.urandom in simulated transaction ID

from backend.core.api.app.utils.internal_auth import VerifiedInternalRequest
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["Internal Services"],
    dependencies=[VerifiedInternalRequest] # Apply token verification to all routes in this router
)

# --- Dependency to get services from app.state ---
# These are simplified versions. In a larger app, you might have a more robust
# dependency injection system or pass app.state around.

def get_config_manager(request: Request) -> ConfigManager:
    if not hasattr(request.app.state, 'config_manager'):
        logger.error("ConfigManager not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: ConfigManager not available.")
    return request.app.state.config_manager

def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: DirectusService not available.")
    return request.app.state.directus_service

def get_encryption_service(request: Request) -> EncryptionService:
    if not hasattr(request.app.state, 'encryption_service'):
        logger.error("EncryptionService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: EncryptionService not available.")
    return request.app.state.encryption_service

def get_cache_service(request: Request) -> CacheService:
    if not hasattr(request.app.state, 'cache_service'):
        logger.error("CacheService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: CacheService not available.")
    return request.app.state.cache_service

def get_billing_service(
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> BillingService:
    return BillingService(cache_service, directus_service, encryption_service)


# --- Endpoint Implementations ---

@router.get("/config/provider_model_pricing/{provider_id}/{model_id_suffix}")
async def get_provider_model_pricing_route(
    provider_id: str,
    model_id_suffix: str, # Assuming model_id_suffix does not contain slashes
    config_manager: ConfigManager = Depends(get_config_manager)
) -> Dict[str, Any]:
    """
    Provides pricing configuration for a specific provider model.
    Called by app services (e.g., BaseSkill) to determine costs.
    """
    logger.info(f"Internal API: Requesting pricing for provider '{provider_id}', model suffix '{model_id_suffix}'.")
    try:
        provider_config = config_manager.get_provider_config(provider_id)
        if not provider_config:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        # Attempt to get pricing using model_id_suffix directly
        model_pricing = provider_config.get_model_pricing(model_id_suffix)
        
        if not model_pricing:
            # If not found, try constructing full model_id (provider_id/model_id_suffix)
            # This handles cases where model_id_suffix might be just the model name part
            full_model_id_from_suffix = f"{provider_id}/{model_id_suffix}"
            model_pricing = provider_config.get_model_pricing(full_model_id_from_suffix)

        if not model_pricing:
            # Final fallback: iterate through models if get_model_pricing is too strict
            # This is more robust if model IDs in YAML don't always match the exact lookup key.
            for model_conf in provider_config.models:
                if model_conf.id == model_id_suffix or model_conf.id == f"{provider_id}/{model_id_suffix}":
                    model_pricing = model_conf.pricing.model_dump(exclude_none=True) if model_conf.pricing else None
                    break
            if not model_pricing:
                 raise HTTPException(status_code=404, detail=f"Model pricing for '{model_id_suffix}' (provider '{provider_id}') not found after checking multiple forms.")

        return model_pricing
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching pricing for {provider_id}/{model_id_suffix}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error fetching pricing: {str(e)}")

# Pydantic model for usage recording payload (mirroring BaseSkill.record_skill_usage)
class UsageRecordPayload(BaseModel):
    user_id_hash: str
    app_id: str
    skill_id: str
    type: str # e.g., "skill_execution"
    timestamp: int # Unix timestamp
    credits_charged: int
    model_used: Optional[str] = None
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    cost_details: Optional[Dict[str, Any]] = None # Raw, unencrypted data

@router.post("/usage/record")
async def record_usage_route(
    payload: UsageRecordPayload,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service) # Keep if direct encryption needed here
) -> Dict[str, Any]:
    """
    Records skill usage data. Called by app services (e.g., BaseSkill).
    The main API handles encryption and persistence.
    """
    logger.info(f"Internal API: Recording usage for user '{payload.user_id_hash}', app '{payload.app_id}', skill '{payload.skill_id}'.")
    
    try:
        # The directus_service.usage.create_usage_entry should handle the encryption
        # using the user_id_hash to derive the encryption key_id.
        usage_entry_id = await directus_service.usage.create_usage_entry(
            user_id_hash=payload.user_id_hash,
            app_id=payload.app_id,
            skill_id=payload.skill_id,
            usage_type=payload.type,
            timestamp=payload.timestamp,
            credits_charged=payload.credits_charged,
            model_used=payload.model_used,
            chat_id=payload.chat_id,
            message_id=payload.message_id,
            cost_system_prompt_credits=payload.cost_details.get("system_prompt_credits") if payload.cost_details else None,
            cost_history_credits=payload.cost_details.get("history_credits") if payload.cost_details else None,
            cost_response_credits=payload.cost_details.get("response_credits") if payload.cost_details else None,
            actual_input_tokens=payload.cost_details.get("input_tokens") if payload.cost_details else None,
            actual_output_tokens=payload.cost_details.get("output_tokens") if payload.cost_details else None,
        )
        logger.info(f"Usage recorded successfully. Entry ID: {usage_entry_id}")
        return {"status": "success", "usage_entry_id": usage_entry_id}
    except Exception as e:
        logger.error(f"Error recording usage for user {payload.user_id_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error recording usage: {str(e)}")


# Pydantic model for credit charging payload (mirroring BaseApp.charge_user_credits)
class CreditChargePayload(BaseModel):
    user_id: str
    user_id_hash: str
    credits: int
    skill_id: str
    app_id: str
    idempotency_key: Optional[str] = None
    usage_details: Optional[Dict[str, Any]] = None

@router.post("/billing/charge")
async def charge_credits_route(
    payload: CreditChargePayload,
    billing_service: BillingService = Depends(get_billing_service)
) -> Dict[str, Any]:
    """
    Charges credits from a user. Called by app services (e.g., BaseApp).
    """
    logger.info(f"Internal API: Charging {payload.credits} credits for user '{payload.user_id}', app '{payload.app_id}', skill '{payload.skill_id}'.")

    if payload.credits <= 0:
        logger.warning(f"Attempted to charge non-positive credits ({payload.credits}) for user {payload.user_id}. Skipping.")
        return {"status": "skipped", "reason": "Non-positive credits"}

    try:
        await billing_service.charge_user_credits(
            user_id=payload.user_id,
            credits_to_deduct=payload.credits,
            user_id_hash=payload.user_id_hash,
            app_id=payload.app_id,
            skill_id=payload.skill_id,
            usage_details=payload.usage_details
        )
        
        return {
            "status": "success",
            "charged_credits": payload.credits,
        }
    except HTTPException as e:
        # Forward HTTP exceptions from the service
        raise e
    except Exception as e:
        logger.error(f"Error charging credits for user {payload.user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error charging credits: {str(e)}")
