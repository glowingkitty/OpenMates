# backend/core/api/app/routes/internal_api.py
#
# This module defines FastAPI routes for internal services (e.g., apps)
# to communicate with the main API. These endpoints are secured by an
# internal service token.

import logging
import os
import time
import yaml
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from fastapi.responses import Response
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
import base64
import hashlib
import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import datetime, timezone

from backend.core.api.app.utils.internal_auth import VerifiedInternalRequest
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.server_stats_service import ServerStatsService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService
from backend.core.api.app.services.payment.payment_service import PaymentService
from backend.core.api.app.services.openobserve_push_service import openobserve_push_service
from typing import List

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

def get_server_stats_service(request: Request) -> ServerStatsService:
    if not hasattr(request.app.state, 'server_stats_service'):
        logger.error("ServerStatsService not found in app.state during internal API call.")
        # Optional: don't fail if not found, just return None
        return None
    return request.app.state.server_stats_service

def get_billing_service(
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    server_stats_service: ServerStatsService = Depends(get_server_stats_service)
) -> BillingService:
    return BillingService(cache_service, directus_service, encryption_service, server_stats_service)

def get_s3_service(request: Request) -> S3UploadService:
    if not hasattr(request.app.state, 's3_service'):
        logger.error("S3UploadService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: S3UploadService not available.")
    return request.app.state.s3_service

def get_email_template_service(request: Request) -> EmailTemplateService:
    if not hasattr(request.app.state, 'email_template_service'):
        logger.error("EmailTemplateService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: EmailTemplateService not available.")
    return request.app.state.email_template_service

def get_invoice_ninja_service(request: Request) -> InvoiceNinjaService:
    if not hasattr(request.app.state, 'invoice_ninja_service'):
        logger.error("InvoiceNinjaService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: InvoiceNinjaService not available.")
    return request.app.state.invoice_ninja_service

def get_payment_service(request: Request) -> PaymentService:
    if not hasattr(request.app.state, 'payment_service'):
        logger.error("PaymentService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: PaymentService not available.")
    return request.app.state.payment_service


# --- Endpoint Implementations ---


# ---------------------------------------------------------------------------
# Token validation endpoint (used by app-uploads microservice)
# ---------------------------------------------------------------------------

class ValidateTokenResponse(BaseModel):
    """Response model for token validation (returned to internal services)."""
    user_id: str
    vault_key_id: str
    username: str


class UserNormalizedEmailResponse(BaseModel):
    """Response model for internal normalized-email lookup."""

    user_id: str
    email: str


@router.get("/validate-token", response_model=ValidateTokenResponse)
async def validate_token_route(
    request: Request,
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ValidateTokenResponse:
    """
    Validate a user's refresh token and return their user_id and vault_key_id.

    Called by the app-uploads microservice to authenticate upload requests
    without duplicating auth logic. The refresh token is forwarded from the
    client's cookie via the X-Refresh-Token header.

    Security:
    - Protected by INTERNAL_API_SHARED_TOKEN (same as all /internal/* routes).
    - The refresh token is never logged.
    - Returns 401 if the token is missing, invalid, or the user is not found.
    """
    # Read the refresh token forwarded from the uploads service
    refresh_token = request.headers.get("X-Refresh-Token")
    if not refresh_token:
        logger.warning("[ValidateToken] Missing X-Refresh-Token header in internal request")
        raise HTTPException(status_code=401, detail="Missing refresh token")

    # Check cache first (same path as auth_dependencies.get_current_user)
    cached_data = await cache_service.get_user_by_token(refresh_token)

    if cached_data:
        user_id = cached_data.get("user_id")
        vault_key_id = cached_data.get("vault_key_id")
        username = cached_data.get("username", "")

        if not user_id or not vault_key_id:
            logger.error(
                f"[ValidateToken] Cached user data missing required fields: "
                f"user_id={bool(user_id)}, vault_key_id={bool(vault_key_id)}"
            )
            raise HTTPException(status_code=401, detail="Invalid or incomplete user session")

        logger.debug(f"[ValidateToken] Token validated from cache for user {user_id[:8]}...")
        return ValidateTokenResponse(
            user_id=user_id,
            vault_key_id=vault_key_id,
            username=username,
        )

    # Not in cache — validate token via Directus then fetch user profile
    # (same flow as auth_dependencies.get_current_user)
    try:
        success, token_data = await directus_service.validate_token(refresh_token)
    except Exception as e:
        logger.error(f"[ValidateToken] Error validating token against Directus: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="Token validation failed")

    if not success or not token_data:
        logger.warning("[ValidateToken] Token rejected by Directus")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = token_data.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token data: Missing user ID")

    # Fetch full user profile for vault_key_id
    try:
        profile_success, user_data, profile_message = await directus_service.get_user_profile(user_id)
    except Exception as e:
        logger.error(f"[ValidateToken] Error fetching user profile for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch user profile")

    if not profile_success or not user_data:
        logger.error(f"[ValidateToken] Could not fetch profile for user {user_id}: {profile_message}")
        raise HTTPException(status_code=500, detail="Could not fetch user data")

    vault_key_id = user_data.get("vault_key_id")
    username = user_data.get("username", "")

    if not vault_key_id:
        logger.error(f"[ValidateToken] vault_key_id missing for user {user_id}")
        raise HTTPException(status_code=500, detail="User account incomplete: missing encryption key")

    logger.info(f"[ValidateToken] Token validated via Directus for user {user_id[:8]}...")
    return ValidateTokenResponse(
        user_id=user_id,
        vault_key_id=vault_key_id,
        username=username,
    )


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
        # Use config_manager's method to get model details
        model_details = config_manager.get_model_pricing(provider_id, model_id_suffix)
        
        if not model_details:
            # Try full model ID if suffix didn't work
            full_model_id = f"{provider_id}/{model_id_suffix}"
            model_details = config_manager.get_model_pricing(provider_id, full_model_id)

        if not model_details:
            raise HTTPException(status_code=404, detail=f"Model pricing for '{model_id_suffix}' (provider '{provider_id}') not found.")

        # Extract the pricing block from the model details
        model_pricing = model_details.get("pricing")
        if not model_pricing:
            raise HTTPException(status_code=404, detail=f"Pricing not found for model '{model_id_suffix}' in provider '{provider_id}'.")

        return model_pricing
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching pricing for {provider_id}/{model_id_suffix}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error fetching pricing: {str(e)}")


@router.get("/users/{user_id}/normalized-email", response_model=UserNormalizedEmailResponse)
async def get_user_normalized_email_route(
    user_id: str,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> UserNormalizedEmailResponse:
    """Return a user's decrypted email in normalized lowercase form for internal service checks."""
    profile_success, user_data, profile_message = await directus_service.get_user_profile(user_id)
    if not profile_success or not user_data:
        raise HTTPException(status_code=404, detail=f"User profile not found: {profile_message}")

    encrypted_email = user_data.get("encrypted_email_address")
    vault_key_id = user_data.get("vault_key_id")
    if not encrypted_email or not vault_key_id:
        raise HTTPException(status_code=404, detail="User email is not available")

    try:
        decrypted_email = await encryption_service.decrypt_with_user_key(encrypted_email, vault_key_id)
    except Exception as exc:
        logger.error(
            "Internal API: failed decrypting email for user '%s': %s",
            user_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to decrypt user email") from exc

    if not decrypted_email:
        raise HTTPException(status_code=404, detail="User email is empty")

    return UserNormalizedEmailResponse(user_id=user_id, email=decrypted_email.strip().lower())

@router.get("/config/provider_pricing/{provider_id}")
async def get_provider_pricing_route(
    provider_id: str,
    config_manager: ConfigManager = Depends(get_config_manager)
) -> Dict[str, Any]:
    """
    Provides pricing configuration for a provider (provider-level pricing, not model-specific).
    Called by app services (e.g., main_processor) to determine costs for skills that use provider-level pricing.
    
    Example: Brave Search has per_request_credits in brave.yml, not model-specific pricing.
    """
    logger.info(f"Internal API: Requesting provider-level pricing for provider '{provider_id}'.")
    try:
        provider_config = config_manager.get_provider_config(provider_id)
        if not provider_config:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        # Get provider-level pricing (not model-specific)
        provider_pricing = provider_config.get("pricing")
        if not provider_pricing:
            raise HTTPException(
                status_code=404, 
                detail=f"Provider-level pricing not found for provider '{provider_id}'. Provider may only have model-specific pricing."
            )
        
        return provider_pricing
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching provider pricing for {provider_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error fetching provider pricing: {str(e)}")


@router.get("/config/provider_info/{provider_id}")
async def get_provider_info_route(
    provider_id: str,
    model_ref: Optional[str] = None,
    config_manager: ConfigManager = Depends(get_config_manager)
) -> Dict[str, Any]:
    """
    Returns display name and region for a provider.
    
    For API-only providers (brave, firecrawl, youtube, google_maps, context7),
    the region comes from the top-level 'region' field in the provider YAML.
    
    For model-based providers, if model_ref is provided (e.g., "anthropic/claude-haiku-4-5-20251001"),
    we look up the model's default server to find the region. Falls back to the
    top-level region if model/server lookup fails.
    
    Args:
        provider_id: The provider ID (e.g., "brave", "anthropic", "bfl")
        model_ref: Optional full model reference (e.g., "anthropic/claude-haiku-4-5-20251001")
                   Used to find model-specific server region for model-based providers.
    
    Returns:
        Dict with "name" (display name) and "region" (e.g., "US", "EU")
    """
    try:
        provider_config = config_manager.get_provider_config(provider_id)
        if not provider_config:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        name = provider_config.get("name", provider_id)
        region = provider_config.get("region")  # Top-level region (API-only providers)
        
        # For model-based providers, try to find region from the model's default server
        if model_ref and "/" in model_ref:
            _, model_suffix = model_ref.split("/", 1)
            models = provider_config.get("models", [])
            for model in models:
                if isinstance(model, dict) and model.get("id") == model_suffix:
                    # Found the model - look up its default server's region
                    default_server = model.get("default_server")
                    servers = model.get("servers", [])
                    for server in servers:
                        if isinstance(server, dict) and server.get("name") == default_server:
                            server_region = server.get("region")
                            if server_region:
                                region = server_region
                            break
                    # If no default_server match, try the first server
                    if not region and servers:
                        first_server = servers[0]
                        if isinstance(first_server, dict):
                            region = first_server.get("region", region)
                    break
        
        return {"name": name, "region": region}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching provider info for {provider_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error fetching provider info: {str(e)}")


# Pydantic model for usage recording payload (mirroring BaseSkill.record_skill_usage)
class UsageRecordPayload(BaseModel):
    user_id: str  # Actual user ID (needed to look up vault_key_id for encryption)
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
    api_key_hash: Optional[str] = None  # SHA-256 hash of API key for tracking
    device_hash: Optional[str] = None  # SHA-256 hash of device for tracking
    server_provider: Optional[str] = None  # Server provider display name (e.g., "AWS Bedrock")
    server_region: Optional[str] = None  # Server region (e.g., "EU", "US")

@router.post("/usage/record")
async def record_usage_route(
    payload: UsageRecordPayload,
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service)
) -> Dict[str, Any]:
    """
    Records skill usage data. Called by app services (e.g., BaseSkill).
    
    Dual-write architecture:
    1. Writes encrypted user-specific data to 'usage' collection (blocking)
    2. Writes anonymous analytics data to 'app_analytics' collection (fire-and-forget)
    
    The main API handles encryption and persistence for usage entries.
    Analytics entries are written in cleartext (no user data, no encryption needed).
    """
    logger.info(f"Internal API: Recording usage for user '{payload.user_id_hash}', app '{payload.app_id}', skill '{payload.skill_id}'.")
    
    try:
        # Get user's vault_key_id for encryption (try cache first, then Directus)
        user_vault_key_id = await cache_service.get_user_vault_key_id(payload.user_id)
        
        if not user_vault_key_id:
            logger.debug(f"vault_key_id not in cache for user {payload.user_id}, fetching from Directus")
            try:
                user_profile_result = await directus_service.get_user_profile(payload.user_id)
                if not user_profile_result or not user_profile_result[0]:
                    logger.error(f"Failed to fetch user profile for encryption: {payload.user_id}")
                    raise HTTPException(status_code=404, detail="User profile not found")
                
                user_vault_key_id = user_profile_result[1].get("vault_key_id")
                if not user_vault_key_id:
                    logger.error(f"User {payload.user_id} missing vault_key_id in Directus profile")
                    raise HTTPException(status_code=500, detail="User encryption key not found")
                
                # Cache the vault_key_id for future use
                await cache_service.update_user(payload.user_id, {"vault_key_id": user_vault_key_id})
                logger.debug(f"Cached vault_key_id for user {payload.user_id}")
            except HTTPException:
                raise
            except Exception as e_profile:
                logger.error(f"Error fetching user profile for encryption: {e_profile}", exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to retrieve user encryption key")
        
        # 1. Create usage entry (user-specific, private) - blocking
        # The directus_service.usage.create_usage_entry stores cleartext app_id/skill_id/chat_id/message_id
        # and encrypts sensitive fields (credits, tokens, model) using the user vault key
        # Determine source: "api_key" if api_key_hash is provided, otherwise "chat" if chat_id is provided, else "direct"
        if payload.api_key_hash:
            source = "api_key"
        elif payload.chat_id:
            source = "chat"
        else:
            source = "direct"
        
        usage_entry_id = await directus_service.usage.create_usage_entry(
            user_id_hash=payload.user_id_hash,
            app_id=payload.app_id,
            skill_id=payload.skill_id,
            usage_type=payload.type,
            timestamp=payload.timestamp,
            credits_charged=payload.credits_charged,
            user_vault_key_id=user_vault_key_id,
            model_used=payload.model_used,
            chat_id=payload.chat_id,
            message_id=payload.message_id,
            source=source,
            cost_system_prompt_credits=payload.cost_details.get("system_prompt_credits") if payload.cost_details else None,
            cost_history_credits=payload.cost_details.get("history_credits") if payload.cost_details else None,
            cost_response_credits=payload.cost_details.get("response_credits") if payload.cost_details else None,
            actual_input_tokens=payload.cost_details.get("input_tokens") if payload.cost_details else None,
            actual_output_tokens=payload.cost_details.get("output_tokens") if payload.cost_details else None,
            user_input_tokens=payload.cost_details.get("user_input_tokens") if payload.cost_details else None,
            system_prompt_tokens=payload.cost_details.get("system_prompt_tokens") if payload.cost_details else None,
            api_key_hash=payload.api_key_hash,  # API key hash for tracking which API key created this usage
            device_hash=payload.device_hash,  # Device hash for tracking which device created this usage
            server_provider=payload.server_provider,
            server_region=payload.server_region,
        )
        
        # 2. Write anonymous analytics entry (fire-and-forget, non-blocking)
        # This doesn't block the response and failures are non-critical
        # Analytics are used for public statistics like "most used apps"
        import asyncio
        asyncio.create_task(
            directus_service.analytics.create_analytics_entry(
                app_id=payload.app_id,  # Cleartext for analytics
                skill_id=payload.skill_id,  # Cleartext for analytics
                model_used=payload.model_used,  # Cleartext for analytics
                focus_mode_id=None,  # TODO: Add focus_mode_id to payload when available
                settings_memory_type=None,  # TODO: Add settings_memory_type to payload when available
                timestamp=payload.timestamp
            )
        )
        
        # Track aggregate usage entry counters (fire-and-forget, non-blocking)
        # These feed into server_stats_global_daily.usage_entries_created / usage_entries_by_app
        try:
            await cache_service.increment_stat("usage_entries_created")
            if payload.app_id:
                await cache_service.increment_json_stat("usage_entries_by_app", payload.app_id)
        except Exception as stats_err:
            logger.warning(f"Failed to increment usage_entries stats: {stats_err}")

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
    api_key_hash: Optional[str] = None  # SHA-256 hash of API key for tracking
    device_hash: Optional[str] = None  # SHA-256 hash of device for tracking

@router.get("/billing/balance")
async def get_user_credit_balance(
    user_id: str,
    cache_service: CacheService = Depends(get_cache_service)
) -> Dict[str, Any]:
    """
    Returns the current credit balance for a user.

    Reads from cache (fast, sub-millisecond). Used by app services for
    pre-flight credit checks before expensive operations (e.g., transcription).

    Returns 0 if user is not found in cache — callers should treat this as
    "unknown balance" and proceed rather than block on a cache miss.
    """
    try:
        user = await cache_service.get_user_by_id(user_id)
        if not user or not isinstance(user, dict):
            logger.debug(f"[InternalAPI] User {user_id} not found in cache for balance check — returning 0")
            return {"user_id": user_id, "credits": 0, "cached": False}
        credits = user.get("credits", 0)
        if not isinstance(credits, int):
            credits = 0
        return {"user_id": user_id, "credits": credits, "cached": True}
    except Exception as e:
        logger.error(f"[InternalAPI] Error fetching credit balance for user {user_id}: {e}", exc_info=True)
        # Return 0 rather than 500 — balance check is non-critical, callers must handle gracefully
        return {"user_id": user_id, "credits": 0, "cached": False}


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
            usage_details=payload.usage_details,
            api_key_hash=payload.api_key_hash,  # API key hash for tracking which API key created this usage
            device_hash=payload.device_hash,  # Device hash for tracking which device created this usage
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


class CreditRefundPayload(BaseModel):
    """Request model for refunding credits to a user after a failed background task."""
    user_id: str
    user_id_hash: str
    credits: int
    skill_id: str
    app_id: str
    reason: Optional[str] = None


@router.post("/billing/refund")
async def refund_credits_route(
    payload: CreditRefundPayload,
    billing_service: BillingService = Depends(get_billing_service)
) -> Dict[str, Any]:
    """
    Refund credits to a user after a failed background task (e.g. PDF OCR failure).

    Called by app workers (e.g. app-pdf-worker) after exhausting all retries.
    This endpoint is the reverse of /billing/charge:
    - Adds credits back to the user's cached and persisted balance.
    - Broadcasts the updated balance to all connected devices.

    Only called for background task failures where credits were already charged
    before the task began (e.g. PDF OCR charged at upload time).
    """
    logger.info(
        f"Internal API: Refunding {payload.credits} credits for user '{payload.user_id}', "
        f"app '{payload.app_id}', skill '{payload.skill_id}'. "
        f"Reason: {(payload.reason or '')[:200]}"
    )

    if payload.credits <= 0:
        logger.warning(
            f"Attempted to refund non-positive credits ({payload.credits}) for user {payload.user_id}. Skipping."
        )
        return {"status": "skipped", "reason": "Non-positive credits"}

    try:
        await billing_service.refund_user_credits(
            user_id=payload.user_id,
            credits_to_refund=payload.credits,
            user_id_hash=payload.user_id_hash,
            app_id=payload.app_id,
            skill_id=payload.skill_id,
            reason=payload.reason or "",
        )
        return {
            "status": "success",
            "refunded_credits": payload.credits,
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error refunding credits for user {payload.user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error refunding credits: {str(e)}")


@router.post("/reprocess-invoice")
async def reprocess_invoice(
    user_id: str,
    order_id: str,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service),
    s3_service: S3UploadService = Depends(get_s3_service),
    email_template_service: EmailTemplateService = Depends(get_email_template_service),
    invoice_ninja_service: InvoiceNinjaService = Depends(get_invoice_ninja_service),
    payment_service: PaymentService = Depends(get_payment_service),
) -> Dict[str, Any]:
    """
    Reprocesses a failed invoice.
    """
    logger.info(f"Internal API: Reprocessing invoice for user '{user_id}', order '{order_id}'.")
    try:
        # 1. Hash the user ID
        user_id_hash = hashlib.sha256(user_id.encode('utf-8')).hexdigest()
        logger.info(f"Hashed user ID {user_id} to {user_id_hash}")

        # 2. Search in Directus for the invoice entry
        params = {
            "filter[user_id_hash][_eq]": user_id_hash,
            "filter[order_id][_eq]": order_id,
            "limit": 1
        }
        invoices = await directus_service.get_items("invoices", params)
        if not invoices:
            logger.error(f"No invoice found for user_id_hash {user_id_hash} and order_id {order_id}")
            raise HTTPException(status_code=404, detail="Invoice not found")

        invoice = invoices[0]
        logger.info(f"Found invoice record: {invoice['id']}")

        # 3. Get user profile to retrieve vault_key_id
        user_profile = await cache_service.get_user_by_id(user_id)
        if not user_profile:
            logger.error(f"Could not retrieve user profile for user {user_id}")
            raise HTTPException(status_code=404, detail="User profile not found")

        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            logger.error(f"vault_key_id not found for user {user_id}")
            raise HTTPException(status_code=500, detail="vault_key_id not found for user")

        user_language = user_profile.get("language", "en")
        user_darkmode = user_profile.get("darkmode", False)

        # 4. Decrypt S3 object key and AES key
        encrypted_s3_object_key = invoice["encrypted_s3_object_key"]
        encrypted_aes_key = invoice["encrypted_aes_key"]
        aes_nonce_b64 = invoice["aes_nonce"]

        s3_object_key = await encryption_service.decrypt_with_user_key(encrypted_s3_object_key, vault_key_id)
        aes_key_b64 = await encryption_service.decrypt_with_user_key(encrypted_aes_key, vault_key_id)

        if not s3_object_key or not aes_key_b64:
            logger.error("Failed to decrypt S3 object key or AES key.")
            raise HTTPException(status_code=500, detail="Failed to decrypt S3 object key or AES key")

        aes_key = base64.b64decode(aes_key_b64)
        nonce = base64.b64decode(aes_nonce_b64)
        logger.info(f"Successfully decrypted S3 object key: {s3_object_key}")

        # 5. Download the PDF file from S3
        bucket_name = s3_service.get_bucket_name('invoices', os.getenv('SERVER_ENVIRONMENT', 'development'))
        presigned_url = s3_service.generate_presigned_url(bucket_name, s3_object_key)

        async with httpx.AsyncClient() as client:
            response = await client.get(presigned_url)
            response.raise_for_status()
            encrypted_pdf_payload = response.content

        logger.info("Successfully downloaded encrypted PDF from S3.")

        # 6. Decrypt the PDF file
        aesgcm = AESGCM(aes_key)
        pdf_bytes = aesgcm.decrypt(nonce, encrypted_pdf_payload, None)
        logger.info("Successfully decrypted PDF file.")

        # 7. Process the PDF file
        now_utc = datetime.now(timezone.utc)
        date_str_filename = now_utc.strftime('%Y_%m_%d')
        
        # Use account ID instead of user_id_last_8 for invoice numbering
        account_id = user_profile.get("account_id")
        if not account_id:
            logger.error(f"Missing account_id for user {user_id} in reprocess invoice.")
            raise HTTPException(status_code=500, detail="Missing account_id for user")

        payment_order_details = await payment_service.get_order(order_id)
        if not payment_order_details:
            logger.error(f"Failed to fetch payment order details for {order_id} in invoice task.")
            raise HTTPException(status_code=500, detail="Failed to fetch payment order details")

        invoice_number = f"{account_id}-MANUAL"  # Placeholder for reprocessed invoices

        invoice_filename_en = f"openmates_invoice_{date_str_filename}_{invoice_number}.pdf"

        # 8. Upload decrypted PDF to Invoice Ninja
        decrypted_email = await encryption_service.decrypt_with_user_key(user_profile["encrypted_email_address"], vault_key_id)

        cardholder_name = payment_order_details.get('metadata', {}).get('cardholder_name', '')
        customer_firstname = ""
        customer_lastname = ""
        if cardholder_name:
            if ' ' in cardholder_name:
                name_parts = cardholder_name.split(' ', 1)
                customer_firstname = name_parts[0]
                customer_lastname = name_parts[-1] if len(name_parts) > 1 else ""
            else:
                customer_firstname = cardholder_name

        amount_paid = payment_order_details.get('amount')
        currency_paid = payment_order_details.get('currency')

        credits_purchased_encrypted = invoice.get("encrypted_credits_purchased")
        credits_purchased = await encryption_service.decrypt_with_user_key(credits_purchased_encrypted, vault_key_id)

        await invoice_ninja_service.process_income_transaction(
            user_hash=user_id_hash,
            external_order_id=order_id,
            customer_firstname=customer_firstname,
            customer_lastname=customer_lastname,
            customer_email=decrypted_email,
            customer_country_code=user_profile.get("country_code", ""),
            credits_value=int(credits_purchased),
            currency_code=currency_paid,
            purchase_price_value=float(amount_paid) / 100,
            invoice_date=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            due_date=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            payment_processor=payment_service.provider_name,
            card_brand_lower=payment_order_details.get('payment_method_details', {}).get('card', {}).get('brand', ''),
            custom_invoice_number=invoice_number,
            custom_pdf_data=pdf_bytes
        )
        logger.info("Successfully processed income transaction in Invoice Ninja.")

        # 9. Send email to user
        email_context = {
            "darkmode": user_darkmode,
            "account_id": account_id  # Add account ID for email template
        }
        attachments = [{
            "filename": invoice_filename_en,
            "content": base64.b64encode(pdf_bytes).decode('utf-8')
        }]

        email_success = await email_template_service.send_email(
            template="purchase-confirmation",
            recipient_email=decrypted_email,
            context=email_context,
            lang=user_language,
            attachments=attachments
        )

        if email_success:
            logger.info("Successfully sent purchase confirmation email.")
            return {"status": "success"}
        else:
            logger.error("Failed to send purchase confirmation email.")
            raise HTTPException(status_code=500, detail="Failed to send purchase confirmation email")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"An error occurred during invoice reprocessing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Issue Report Endpoints ---

class IssueResponse(BaseModel):
    """Response model for issue data"""
    id: str
    title: str
    description: Optional[str]
    chat_or_embed_url: Optional[str]  # Decrypted URL
    contact_email: Optional[str]  # Decrypted email
    timestamp: str
    estimated_location: Optional[str]  # Decrypted location
    device_info: Optional[str]  # Decrypted device info
    console_logs: Optional[str] = None  # Decrypted logs (only included if include_logs=true)
    created_at: str
    updated_at: str


@router.get("/issues", response_model=List[IssueResponse])
async def get_issues(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> List[IssueResponse]:
    """
    Get issue reports with optional text search in title.
    
    This endpoint is only accessible from within the Docker network via internal service token.
    It allows searching for text in the issue title and returns issues with decrypted contact emails.
    
    Args:
        search: Optional text to search for in issue titles (case-insensitive partial match)
        limit: Maximum number of issues to return (default: 100, max: 1000)
        offset: Number of issues to skip for pagination (default: 0)
        
    Returns:
        List of issue reports with decrypted contact emails
    """
    logger.info(f"Internal API: Getting issues (search='{search}', limit={limit}, offset={offset})")
    
    try:
        # Build query parameters
        params = {
            "limit": min(limit, 1000),  # Cap at 1000 for performance
            "offset": offset,
            "sort": "-created_at"  # Sort by newest first
        }
        
        # Add search filter if provided
        if search:
            # Use Directus filter for case-insensitive partial match on title
            params["filter[title][_icontains]"] = search
        
        # Fetch issues from Directus
        issues = await directus_service.get_items("issues", params)
        
        # Decrypt encrypted fields and format response
        result = []
        for issue in issues:
            # Decrypt contact email if present
            decrypted_email = None
            if issue.get("encrypted_contact_email"):
                try:
                    decrypted_email = await encryption_service.decrypt_issue_report_email(
                        issue["encrypted_contact_email"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt contact email for issue {issue.get('id')}: {str(e)}")
            
            # Decrypt chat or embed URL if present
            decrypted_url = None
            if issue.get("encrypted_chat_or_embed_url"):
                try:
                    decrypted_url = await encryption_service.decrypt_issue_report_data(
                        issue["encrypted_chat_or_embed_url"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt chat or embed URL for issue {issue.get('id')}: {str(e)}")
            
            # Decrypt estimated location if present
            decrypted_location = None
            if issue.get("encrypted_estimated_location"):
                try:
                    decrypted_location = await encryption_service.decrypt_issue_report_data(
                        issue["encrypted_estimated_location"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt estimated location for issue {issue.get('id')}: {str(e)}")
            
            # Decrypt device info if present
            decrypted_device_info = None
            if issue.get("encrypted_device_info"):
                try:
                    decrypted_device_info = await encryption_service.decrypt_issue_report_data(
                        issue["encrypted_device_info"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt device info for issue {issue.get('id')}: {str(e)}")
            
            result.append(IssueResponse(
                id=issue["id"],
                title=issue["title"],
                description=issue.get("description"),
                chat_or_embed_url=decrypted_url,
                contact_email=decrypted_email,
                timestamp=issue.get("timestamp", ""),
                estimated_location=decrypted_location,
                device_info=decrypted_device_info,
                created_at=issue.get("created_at", ""),
                updated_at=issue.get("updated_at", "")
            ))
        
        logger.info(f"Internal API: Retrieved {len(result)} issues")
        return result
        
    except Exception as e:
        logger.error(f"Error retrieving issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve issues: {str(e)}")


@router.get("/issues/{issue_id}", response_model=IssueResponse)
async def get_issue(
    issue_id: str,
    include_logs: bool = False,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    s3_service: S3UploadService = Depends(get_s3_service)
) -> IssueResponse:
    """
    Get a specific issue report by ID.
    
    This endpoint is only accessible from within the Docker network via internal service token.
    Returns the issue with decrypted fields. Console logs are only included if include_logs=true.
    
    Args:
        issue_id: UUID of the issue to retrieve
        include_logs: If True, fetch and decrypt console logs from S3 (default: False)
        
    Returns:
        Issue report with decrypted fields (and optionally console logs)
    """
    logger.info(f"Internal API: Getting issue {issue_id}")
    
    try:
        # Fetch issue from Directus using filter
        params = {
            "filter[id][_eq]": issue_id,
            "limit": 1
        }
        issues = await directus_service.get_items("issues", params)
        
        if not issues or len(issues) == 0:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        issue = issues[0]
        
        # Decrypt contact email if present
        decrypted_email = None
        if issue.get("encrypted_contact_email"):
            try:
                decrypted_email = await encryption_service.decrypt_issue_report_email(
                    issue["encrypted_contact_email"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt contact email for issue {issue_id}: {str(e)}")
        
        # Decrypt chat or embed URL if present
        decrypted_url = None
        if issue.get("encrypted_chat_or_embed_url"):
            try:
                decrypted_url = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_chat_or_embed_url"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt chat or embed URL for issue {issue_id}: {str(e)}")
        
        # Decrypt estimated location if present
        decrypted_location = None
        if issue.get("encrypted_estimated_location"):
            try:
                decrypted_location = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_estimated_location"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt estimated location for issue {issue_id}: {str(e)}")
        
        # Decrypt device info if present
        decrypted_device_info = None
        if issue.get("encrypted_device_info"):
            try:
                decrypted_device_info = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_device_info"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt device info for issue {issue_id}: {str(e)}")
        
        # Optionally fetch and decrypt issue report YAML from S3
        decrypted_console_logs = None
        if include_logs and issue.get("encrypted_issue_report_yaml_s3_key"):
            try:
                # Decrypt the S3 object key
                s3_object_key = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_issue_report_yaml_s3_key"]
                )
                
                if s3_object_key:
                    # Get bucket name for issue_logs
                    from backend.core.api.app.services.s3.config import get_bucket_name
                    bucket_name = get_bucket_name('issue_logs', os.getenv('SERVER_ENVIRONMENT', 'development'))
                    
                    # Download encrypted YAML from S3
                    encrypted_yaml_bytes = await s3_service.get_file(
                        bucket_name=bucket_name,
                        object_key=s3_object_key
                    )
                    
                    if encrypted_yaml_bytes:
                        # Decrypt the YAML
                        encrypted_yaml_str = encrypted_yaml_bytes.decode('utf-8')
                        decrypted_yaml = await encryption_service.decrypt_issue_report_data(
                            encrypted_yaml_str
                        )
                        
                        # Parse YAML to extract console logs
                        yaml_data = yaml.safe_load(decrypted_yaml)
                        if yaml_data and 'issue_report' in yaml_data and 'logs' in yaml_data['issue_report']:
                            decrypted_console_logs = yaml_data['issue_report']['logs'].get('console_logs')
                        logger.info(f"Successfully fetched and decrypted issue report YAML for issue {issue_id}")
                    else:
                        logger.warning(f"Issue report YAML file not found in S3 for issue {issue_id}: {s3_object_key}")
            except Exception as e:
                logger.warning(f"Failed to fetch issue report YAML for issue {issue_id}: {str(e)}", exc_info=True)
        
        return IssueResponse(
            id=issue["id"],
            title=issue["title"],
            description=issue.get("description"),
            chat_or_embed_url=decrypted_url,
            contact_email=decrypted_email,
            timestamp=issue.get("timestamp", ""),
            estimated_location=decrypted_location,
            device_info=decrypted_device_info,
            console_logs=decrypted_console_logs,
            created_at=issue.get("created_at", ""),
            updated_at=issue.get("updated_at", "")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving issue {issue_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve issue: {str(e)}")


# --- E2E Test Notification Endpoints ---

# ---------------------------------------------------------------------------
# Upload Service Endpoints
# ---------------------------------------------------------------------------
# These endpoints are called by the app-uploads microservice running on a
# separate VM. They proxy Directus and Vault operations so the upload server
# never needs direct access to Directus or the main Vault instance.
#
# Security:
#   - Protected by INTERNAL_API_SHARED_TOKEN (same as all /internal/* routes).
#   - wrap-key only calls Vault Transit ENCRYPT (never decrypt).
#   - store-record only creates records (never reads user data).
#   - check-duplicate returns only upload dedup metadata, not user secrets.
# ---------------------------------------------------------------------------


class UploadCheckDuplicateRequest(BaseModel):
    """Request model for upload deduplication check."""
    user_id: str = Field(..., description="User ID who uploaded the file")
    content_hash: str = Field(..., description="SHA-256 hash of the original file content")


class UploadCheckDuplicateResponse(BaseModel):
    """Response model for upload deduplication check."""
    duplicate: bool = Field(..., description="True if a duplicate record exists")
    record: Optional[Dict[str, Any]] = Field(None, description="Existing upload record if duplicate")


@router.post("/uploads/check-duplicate", response_model=UploadCheckDuplicateResponse)
async def check_upload_duplicate(
    payload: UploadCheckDuplicateRequest,
    directus_service: DirectusService = Depends(get_directus_service),
) -> UploadCheckDuplicateResponse:
    """
    Check whether a user has already uploaded a file with the same content hash.

    Called by the app-uploads microservice to avoid re-processing duplicate files.
    Returns the existing upload record if found, allowing the uploads service to
    return cached metadata immediately.

    Security: Only returns upload dedup metadata (S3 keys, embed_id, etc.).
    Does not expose user secrets or Vault data beyond what was originally
    returned to the uploading client.

    Validation: For any upload that has an embed_id, we verify that the corresponding
    embed record exists in Directus with status='finished'. If the embed is missing or
    not finished (e.g. a previous upload failed mid-way after storing the upload_files
    record but before OCR/processing completed), we discard the stale record and return
    duplicate=False so the uploads service falls through to a fresh upload + processing run.
    This prevents the UI from hanging forever on 'Processing…' with no WS event arriving.
    """
    log_prefix = f"[UploadDedup] [user:{payload.user_id[:8]}...]"
    logger.debug(f"{log_prefix} Checking duplicate for hash {payload.content_hash[:16]}...")

    try:
        params = {
            "filter[user_id][_eq]": payload.user_id,
            "filter[content_hash][_eq]": payload.content_hash,
            "limit": 1,
        }
        items = await directus_service.get_items("upload_files", params)

        if not items or len(items) == 0:
            logger.debug(f"{log_prefix} No duplicate found")
            return UploadCheckDuplicateResponse(duplicate=False, record=None)

        record = items[0]
        embed_id = record.get("embed_id")
        # page_count IS stored on upload_files records (for PDFs) and returned
        # on dedup hits so the frontend can display the correct page count.
        # Stale detection applies to all uploads with an embed_id regardless of file type.

        # For any upload with an embed_id, validate that the embed actually exists
        # in Directus with status='finished'. A stale record with no corresponding
        # finished embed means a previous upload failed after storing the upload_files
        # row but before processing completed — returning it as a dedup hit would
        # leave the frontend stuck on 'Processing…' indefinitely.
        if embed_id:
            try:
                embed_params = {
                    "filter[embed_id][_eq]": embed_id,
                    "fields": "embed_id,status",
                    "limit": 1,
                }
                embed_items = await directus_service.get_items("embeds", embed_params)
                embed_status = embed_items[0].get("status") if embed_items else None

                if embed_status != "finished":
                    logger.warning(
                        f"{log_prefix} Stale dedup record detected: upload_files has embed_id={embed_id} "
                        f"but embed status is {embed_status!r} (expected 'finished'). "
                        f"Discarding stale record — fresh upload will be performed."
                    )
                    # Clean up the stale upload_files record so it won't block future uploads.
                    try:
                        await directus_service.delete_item("upload_files", record["id"])
                        logger.info(f"{log_prefix} Deleted stale upload_files record id={record['id']}")
                    except Exception as del_err:
                        logger.warning(f"{log_prefix} Could not delete stale record: {del_err}")
                    return UploadCheckDuplicateResponse(duplicate=False, record=None)

            except Exception as embed_check_err:
                # Non-fatal: if embed status check fails, be conservative and treat as stale.
                logger.warning(
                    f"{log_prefix} Embed status check failed for {embed_id}: {embed_check_err}. "
                    f"Treating as stale — fresh upload will be performed."
                )
                return UploadCheckDuplicateResponse(duplicate=False, record=None)

        logger.info(f"{log_prefix} Duplicate found: embed_id={embed_id}")
        return UploadCheckDuplicateResponse(duplicate=True, record=record)

    except Exception as e:
        logger.error(f"{log_prefix} Dedup check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Deduplication check failed: {str(e)}")


class UploadWrapKeyRequest(BaseModel):
    """Request model for Vault Transit AES key wrapping."""
    aes_key_b64: str = Field(..., description="Base64-encoded plaintext AES-256 key to wrap")
    vault_key_id: str = Field(..., description="User's Vault Transit key name (user_{uuid})")


class UploadWrapKeyResponse(BaseModel):
    """Response model for Vault Transit AES key wrapping."""
    vault_wrapped_aes_key: str = Field(..., description="Vault-wrapped ciphertext (vault:v1:...)")


@router.post("/uploads/wrap-key", response_model=UploadWrapKeyResponse)
async def wrap_upload_aes_key(
    payload: UploadWrapKeyRequest,
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> UploadWrapKeyResponse:
    """
    Wrap a plaintext AES key using the user's Vault Transit key.

    Called by the app-uploads microservice after encrypting a file with AES-256-GCM.
    The wrapped key is stored in the embed TOON content so backend skills can later
    unwrap it via Vault Transit to decrypt the file on demand.

    Security:
    - This endpoint only calls Vault Transit ENCRYPT (wrapping).
    - It NEVER calls Vault Transit DECRYPT (unwrapping).
    - Even if the uploads service is compromised, an attacker can only wrap
      new keys — they cannot unwrap/decrypt any existing file.
    - The plaintext AES key travels over the private network between VMs.
      Ensure the VMs are on a Hetzner private network (vSwitch) or use TLS.
    """
    log_prefix = f"[UploadWrapKey] [key:{payload.vault_key_id[:12]}...]"
    logger.debug(f"{log_prefix} Wrapping AES key via Vault Transit")

    try:
        # encrypt_with_user_key calls Vault Transit POST /transit/encrypt/{vault_key_id}
        # Returns (ciphertext, key_version) — we only need the ciphertext for key wrapping.
        vault_wrapped, _key_version = await encryption_service.encrypt_with_user_key(
            payload.aes_key_b64, payload.vault_key_id
        )

        if not vault_wrapped:
            logger.error(f"{log_prefix} Vault Transit encrypt returned empty result")
            raise HTTPException(status_code=500, detail="Vault key wrapping failed")

        logger.info(f"{log_prefix} AES key wrapped successfully")
        return UploadWrapKeyResponse(vault_wrapped_aes_key=vault_wrapped)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Vault key wrapping failed: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Encryption service unavailable: {str(e)}")


class UploadStoreRecordRequest(BaseModel):
    """Request model for storing an upload record in Directus."""
    embed_id: str = Field(..., description="UUID used as embed_id in the embed system")
    user_id: str = Field(..., description="User ID who uploaded the file")
    content_hash: str = Field(..., description="SHA-256 hash of the original file content")
    original_filename: str = Field(..., description="Original uploaded filename")
    content_type: str = Field(..., description="Detected MIME type")
    file_size_bytes: int = Field(..., description="Original file size in bytes")
    s3_base_url: str = Field(..., description="S3 base URL for constructing full file URLs")
    files_metadata: Dict[str, Any] = Field(..., description="Stored file variants metadata")
    aes_key: str = Field(..., description="Base64 AES-256 key for client-side decryption")
    aes_nonce: str = Field(..., description="Base64 AES-GCM nonce")
    vault_wrapped_aes_key: str = Field(..., description="Vault-wrapped AES key for server-side access")
    malware_scan: str = Field(default="clean", description="ClamAV scan result")
    ai_detection: Optional[Dict[str, Any]] = Field(None, description="AI-generated detection result")
    created_at: int = Field(..., description="Unix timestamp of upload")
    # PDF-specific: number of pages extracted by pymupdf during upload.
    # Stored so that deduplication responses can return the correct page_count
    # without re-parsing the PDF on subsequent uploads of the same file.
    page_count: Optional[int] = Field(None, description="Number of pages (PDFs only)")


@router.post("/uploads/store-record")
async def store_upload_record(
    payload: UploadStoreRecordRequest,
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """
    Store an upload record in Directus for future deduplication.

    Called by the app-uploads microservice after a successful upload.
    The record contains all metadata needed to reconstruct the upload response
    if the same user uploads the same file again (deduplication).

    Security:
    - This endpoint only CREATES records in the upload_files collection.
    - It does not read, update, or delete any existing records.
    - The aes_key stored here is the same one already returned to the client;
      it is NOT a new secret introduced by this endpoint.
    """
    log_prefix = f"[UploadStore] [user:{payload.user_id[:8]}...] [embed:{payload.embed_id[:8]}...]"
    logger.info(f"{log_prefix} Storing upload record (hash={payload.content_hash[:16]}...)")

    try:
        record = payload.model_dump()
        await directus_service.create_item("upload_files", record)
        logger.info(f"{log_prefix} Upload record stored successfully")

        # Increment the user's storage counter.
        # This is a best-effort operation — if it fails, the weekly billing job
        # will reconcile the counter from the upload_files table directly.
        try:
            user_data = await directus_service.get_items(
                'directus_users',
                params={'filter[id][_eq]': payload.user_id, 'fields': 'storage_used_bytes', 'limit': 1},
            )
            current_bytes = 0
            if user_data and isinstance(user_data, list) and len(user_data) > 0:
                current_bytes = int(user_data[0].get('storage_used_bytes') or 0)
            new_bytes = current_bytes + payload.file_size_bytes
            await directus_service.update_user(payload.user_id, {'storage_used_bytes': new_bytes})
            logger.info(
                f"{log_prefix} Storage counter updated: {current_bytes} → {new_bytes} bytes "
                f"(+{payload.file_size_bytes} bytes)"
            )
        except Exception as counter_err:
            # Non-fatal: weekly billing reconciliation will correct the counter.
            logger.warning(
                f"{log_prefix} Failed to update storage counter after upload: {counter_err}. "
                f"Weekly billing job will reconcile."
            )

        return {"status": "success", "embed_id": payload.embed_id}

    except Exception as e:
        # Non-fatal: upload already succeeded (files in S3). Dedup just won't work
        # for this file. Log the error but don't fail the upload.
        logger.error(f"{log_prefix} Failed to store upload record: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to store upload record: {str(e)}")


class UploadCacheEmbedRequest(BaseModel):
    """
    Request model for caching an upload embed in Redis so that app skills
    (e.g. images-view, pdf-read) can look it up server-side.

    Background: AI-generated embeds are cached in Redis by generate_task.py.
    User-uploaded embeds were never cached, so images-view / pdf-read raised
    "Embed not found in cache" when called on uploaded files.  This endpoint
    bridges that gap by letting the upload server push the embed data into
    Redis immediately after a successful upload.
    """
    embed_id: str = Field(..., description="UUID used as embed_id in the embed system")
    user_id: str = Field(..., description="User ID who uploaded the file")
    vault_wrapped_aes_key: str = Field(..., description="Vault-wrapped AES key (vault:v1:... string)")
    aes_nonce: str = Field(..., description="Base64 AES-GCM nonce")
    s3_base_url: str = Field(..., description="S3 base URL for constructing full file URLs")
    files: Dict[str, Any] = Field(..., description="File variants metadata dict (original/full/preview etc.)")
    content_type: str = Field(..., description="MIME type of the uploaded file (e.g. image/webp)")
    original_filename: str = Field(..., description="Original uploaded filename")
    ai_detection: Optional[Dict[str, Any]] = Field(None, description="AI-generated detection result")


@router.post("/uploads/cache-embed")
async def cache_upload_embed(
    payload: UploadCacheEmbedRequest,
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Cache an upload embed in Redis so that app skills (images-view, pdf-read, etc.)
    can retrieve it server-side.

    Called by the app-uploads microservice immediately after a successful upload,
    alongside /uploads/store-record.  Without this, skills that call
    embed_service._lookup_embed_content() would get "Embed not found in cache"
    because the upload pipeline previously never wrote to Redis.

    The cached data mirrors the structure written by generate_task.py for
    AI-generated images so that view_skill.py and read_skill.py can decrypt
    and serve both kinds of embeds identically.

    TTL: 72 hours (259200 s) — same as CHAT_MESSAGES_TTL.
    """
    import json as json_lib

    log_prefix = f"[UploadCacheEmbed] [user:{payload.user_id[:8]}...] [embed:{payload.embed_id[:8]}...]"
    logger.info(f"{log_prefix} Caching upload embed in Redis")

    try:
        client = await cache_service.client
        if not client:
            logger.warning(f"{log_prefix} Redis client not available — skipping embed cache")
            return {"status": "skipped", "reason": "redis_unavailable"}

        # Build embed data matching the structure expected by embed_service._lookup_embed_content()
        # and view_skill._lookup_embed_content().  Key fields:
        #   - vault_wrapped_aes_key: needed by the skill to decrypt S3 files
        #   - s3_base_url + files: needed to construct download URLs
        #   - aes_nonce: needed for AES-GCM decryption
        #   - user_id: stored so the fallback persistence task can re-send if needed
        embed_data: Dict[str, Any] = {
            "embed_id": payload.embed_id,
            "user_id": payload.user_id,
            "type": "image",  # upload server currently handles images (and PDFs as "pdf")
            "status": "finished",
            "filename": payload.original_filename,
            "content_type": payload.content_type,
            "files": payload.files,
            "s3_base_url": payload.s3_base_url,
            "aes_nonce": payload.aes_nonce,
            "vault_wrapped_aes_key": payload.vault_wrapped_aes_key,
            "ai_detection": payload.ai_detection,
            # skill_id / app_id are not set because this is a user upload, not a skill result
        }
        if payload.content_type == "application/pdf":
            embed_data["type"] = "pdf"

        cache_key = f"embed:{payload.embed_id}"
        await client.set(cache_key, json_lib.dumps(embed_data), ex=259200)  # 72 hours

        logger.info(f"{log_prefix} Upload embed cached at key '{cache_key}' (72h TTL)")
        return {"status": "success", "embed_id": payload.embed_id}

    except Exception as e:
        # Non-fatal: the upload already succeeded (file is in S3 and Directus).
        # Skills will fail with "not found in cache" rather than the upload itself failing.
        logger.error(f"{log_prefix} Failed to cache upload embed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cache upload embed: {str(e)}")


# --- Test Run Summary Email Dispatch ---
# Called by scripts/_daily_runner_helper.py (running on the host via admin-sidecar)
# to dispatch the test run summary email through Celery without needing celery
# installed on the host.

class TestRunSummaryEmailPayload(BaseModel):
    """Payload for dispatching a test run summary email via Celery."""
    recipient_email: str
    environment: str = "development"  # "development" or "production"
    run_id: str
    git_sha: str
    git_branch: str
    duration_seconds: int
    total: int
    passed: int
    failed: int
    skipped: int
    not_started: int
    suites: List[Dict[str, Any]]
    failed_tests: List[Dict[str, Any]]
    all_tests: Optional[List[Dict[str, Any]]] = None  # All tests with name, suite, status, duration
    opencode_chat_url: Optional[str] = None  # Shareable opencode session URL for failure analysis


class TestRunOpenObservePayload(BaseModel):
    """Payload for forwarding a normalized daily test run summary to OpenObserve."""

    environment: str = "development"
    run_id: str
    git_sha: str
    git_branch: str
    duration_seconds: int
    total: int
    passed: int
    failed: int
    skipped: int
    not_started: int
    suites: List[Dict[str, Any]]
    failed_tests: List[Dict[str, Any]]


@router.post("/dispatch-test-summary-email")
async def dispatch_test_summary_email(
    payload: TestRunSummaryEmailPayload,
    request: Request,
) -> Dict[str, Any]:
    """
    Dispatch the test run summary email Celery task.

    Called by the host-side daily runner helper script (which runs inside the
    admin-sidecar container where celery is not installed). This endpoint
    accepts the same data that would have been passed as Celery task args and
    dispatches the task onto the 'email' queue.

    Security: Protected by INTERNAL_API_SHARED_TOKEN (same as all /internal/* routes).
    """
    logger.info(
        f"[InternalAPI] Dispatching test run summary email to {payload.recipient_email} "
        f"(run_id={payload.run_id}, failed={payload.failed}, total={payload.total})"
    )

    try:
        from backend.core.api.app.tasks.celery_config import app as celery_app

        celery_app.send_task(
            name="app.tasks.email_tasks.test_run_summary_email_task.send_test_run_summary",
            args=[
                payload.recipient_email,
                payload.run_id,
                payload.git_sha,
                payload.git_branch,
                payload.duration_seconds,
                payload.total,
                payload.passed,
                payload.failed,
                payload.skipped,
                payload.not_started,
                payload.suites,
                payload.failed_tests,
                payload.environment,
            ],
            kwargs={
                "all_tests": payload.all_tests,
                "opencode_chat_url": payload.opencode_chat_url,
            },
            queue="email",
        )

        logger.info("[InternalAPI] Test run summary email task dispatched successfully")
        return {"status": "dispatched"}
    except Exception as e:
        logger.error(f"[InternalAPI] Failed to dispatch test summary email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to dispatch email task: {str(e)}")


@router.post("/openobserve/push-test-run")
async def push_test_run_to_openobserve(
    payload: TestRunOpenObservePayload,
) -> Dict[str, Any]:
    """
    Forward the normalized daily test-run summary to OpenObserve test-runs stream.

    Called by scripts/_daily_runner_helper.py after run-tests-daily.sh completes.
    """
    status = "failed" if payload.failed > 0 else "passed"
    logger.info(
        "[InternalAPI] Pushing test run summary to OpenObserve "
        f"(run_id={payload.run_id}, status={status}, failed={payload.failed}, total={payload.total})"
    )

    push_payload = payload.dict()
    push_payload["status"] = status
    push_payload["suite"] = "daily"

    pushed = await openobserve_push_service.push_test_run_summary(push_payload)
    if not pushed:
        raise HTTPException(status_code=502, detail="Failed to push test run summary to OpenObserve")

    return {
        "status": "pushed",
        "run_id": payload.run_id,
        "failed": payload.failed,
        "total": payload.total,
    }


# --- Per-Spec Test Event Push to OpenObserve ---
# Called by the Playwright api-reporter.ts during E2E test execution.
# Each event represents a spec lifecycle milestone (suite_start, test_end, suite_end).

class TestEventOpenObservePayload(BaseModel):
    """Payload for a single Playwright spec lifecycle event pushed to OpenObserve."""
    event_type: str  # "suite_start", "test_end", "suite_end"
    environment: str = "development"
    worker_slot: str = "0"
    git_branch: str = ""
    run_id: str = ""
    # test_end fields
    test_file: str = ""
    test_name: str = ""
    status: str = ""  # "passed", "failed", "timedOut", "skipped"
    duration_ms: int = 0
    error_message: str = ""
    # suite_end summary fields
    total: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None
    # Console log aggregation fields (from console-monitor.ts)
    total_console_messages: Optional[int] = None
    console_errors: Optional[List[Dict[str, Any]]] = None
    console_warnings: Optional[List[Dict[str, Any]]] = None
    console_logs_top: Optional[List[Dict[str, Any]]] = None


@router.post("/openobserve/push-test-event")
async def push_test_event_to_openobserve(
    payload: TestEventOpenObservePayload,
) -> Dict[str, Any]:
    """
    Forward a single Playwright spec lifecycle event to the OpenObserve test-events stream.

    Called by api-reporter.ts inside the Playwright Docker container during E2E runs.
    Provides real-time per-spec visibility: which specs are starting, passing, or failing.
    """
    pushed = await openobserve_push_service.push_test_event(payload.dict())
    if not pushed:
        raise HTTPException(status_code=502, detail="Failed to push test event to OpenObserve")

    return {"status": "pushed", "event_type": payload.event_type, "test_file": payload.test_file}


# --- Test Run Started Email Dispatch ---
# Called by scripts/_daily_runner_helper.py (run from crontab on the host).
# The helper has no Celery dependency, so it POSTs here and we dispatch
# the email task via Celery.

class TestRunStartedEmailPayload(BaseModel):
    """Payload for dispatching a test run started notification email via Celery."""
    recipient_email: str
    environment: str = "development"  # "development" or "production"
    trigger_type: str  # e.g. "Scheduled (daily)" or "Manual (admin)"
    git_sha: str
    git_branch: str
    started_at: str  # ISO 8601 UTC timestamp


@router.post("/dispatch-test-start-email")
async def dispatch_test_start_email(
    payload: TestRunStartedEmailPayload,
    request: Request,
) -> Dict[str, Any]:
    """
    Dispatch the test run started notification email Celery task.

    Called by the host-side daily runner helper script (which runs inside the
    admin-sidecar container where celery is not installed). The admin API and
    Celery Beat tasks call the Celery task directly instead of using this bridge.

    Security: Protected by INTERNAL_API_SHARED_TOKEN (same as all /internal/* routes).
    """
    logger.info(
        f"[InternalAPI] Dispatching test run started email to {payload.recipient_email} "
        f"(trigger={payload.trigger_type}, git={payload.git_sha}@{payload.git_branch})"
    )

    try:
        from backend.core.api.app.tasks.celery_config import app as celery_app

        celery_app.send_task(
            name="app.tasks.email_tasks.test_run_started_email_task.send_test_run_started",
            args=[
                payload.recipient_email,
                payload.trigger_type,
                payload.git_sha,
                payload.git_branch,
                payload.started_at,
                payload.environment,
            ],
            queue="email",
        )

        logger.info("[InternalAPI] Test run started email task dispatched successfully")
        return {"status": "dispatched"}
    except Exception as e:
        logger.error(f"[InternalAPI] Failed to dispatch test run started email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to dispatch email task: {str(e)}")


# --- E2E Test Notification Endpoints ---

class TestFailureNotificationPayload(BaseModel):
    """Payload for E2E test failure notification."""
    environment: str  # "development" or "production"
    test_file: str  # e.g., "chat-flow.spec.ts"
    test_name: str  # e.g., "logs in and sends a chat message"
    status: str  # "failed", "timedout", "passed"
    timestamp: str  # ISO timestamp
    duration_seconds: float  # Test duration in seconds
    error_message: Optional[str] = None  # Error message or stack trace
    console_logs: Optional[str] = None  # Last 20 console log entries
    network_activities: Optional[str] = None  # Last 20 network activities


class TestRunSummary(BaseModel):
    """Summary of a test run with multiple test results."""
    environment: str  # "development" or "production"
    total_tests: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    timestamp: str  # ISO timestamp
    failures: list[TestFailureNotificationPayload]  # Details of failed tests


@router.post("/e2e-tests/notify-failure")
async def notify_test_failure(
    payload: TestFailureNotificationPayload,
    request: Request
) -> Dict[str, Any]:
    """
    Receives E2E test failure notification and sends alert email to admin.
    
    This endpoint is called by the Playwright test runner (via API reporter)
    when a test fails. It dispatches an email notification task.
    
    Protected by internal service token (X-Internal-Service-Token header).
    """
    import os
    from backend.core.api.app.tasks.celery_config import app as celery_app
    
    logger.info(
        f"Internal API: Received E2E test failure notification - "
        f"test='{payload.test_name}', status='{payload.status}', env='{payload.environment}'"
    )
    
    # Get admin email from environment
    admin_email = os.getenv("SERVER_OWNER_EMAIL")
    if not admin_email:
        logger.error("SERVER_OWNER_EMAIL not configured - cannot send test failure notification")
        raise HTTPException(
            status_code=500,
            detail="Server admin email not configured. Cannot send notification."
        )
    
    # Only send notifications for failures (not passed tests)
    if payload.status == "passed":
        logger.info(f"Test '{payload.test_name}' passed - skipping notification")
        return {"status": "skipped", "reason": "Test passed, no notification needed"}
    
    try:
        # Dispatch email notification task
        celery_app.send_task(
            name='app.tasks.email_tasks.test_notification_email_task.send_test_failure_notification',
            args=[
                admin_email,
                payload.environment,
                payload.test_file,
                payload.test_name,
                payload.status,
                payload.timestamp,
                payload.duration_seconds,
                payload.error_message,
                payload.console_logs,
                payload.network_activities
            ],
            queue='email'
        )
        
        logger.info(
            f"Dispatched test failure notification email task for test '{payload.test_name}' "
            f"to {admin_email}"
        )
        
        return {
            "status": "notification_dispatched",
            "test_name": payload.test_name,
            "test_status": payload.status,
            "recipient": admin_email
        }
        
    except Exception as e:
        logger.error(f"Failed to dispatch test failure notification: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to dispatch notification: {str(e)}"
        )


@router.post("/e2e-tests/notify-run-summary")
async def notify_test_run_summary(
    payload: TestRunSummary,
    request: Request
) -> Dict[str, Any]:
    """
    Receives a summary of a complete E2E test run and sends alert if there are failures.
    
    This endpoint is called at the end of a scheduled test run to provide
    a summary email with all failed tests.
    
    Protected by internal service token (X-Internal-Service-Token header).
    """
    import os
    from backend.core.api.app.tasks.celery_config import app as celery_app
    
    logger.info(
        f"Internal API: Received E2E test run summary - "
        f"env='{payload.environment}', total={payload.total_tests}, "
        f"passed={payload.passed}, failed={payload.failed}"
    )
    
    # Get admin email from environment
    admin_email = os.getenv("SERVER_OWNER_EMAIL")
    if not admin_email:
        logger.error("SERVER_OWNER_EMAIL not configured - cannot send test run summary")
        raise HTTPException(
            status_code=500,
            detail="Server admin email not configured. Cannot send notification."
        )
    
    # Only send notifications if there are failures
    if payload.failed == 0:
        logger.info(f"All {payload.total_tests} tests passed - skipping summary notification")
        return {
            "status": "skipped",
            "reason": "All tests passed, no notification needed",
            "total_tests": payload.total_tests,
            "passed": payload.passed
        }
    
    try:
        # Send individual notifications for each failed test
        for failure in payload.failures:
            celery_app.send_task(
                name='app.tasks.email_tasks.test_notification_email_task.send_test_failure_notification',
                args=[
                    admin_email,
                    failure.environment,
                    failure.test_file,
                    failure.test_name,
                    failure.status,
                    failure.timestamp,
                    failure.duration_seconds,
                    failure.error_message,
                    failure.console_logs,
                    failure.network_activities
                ],
                queue='email'
            )
        
        logger.info(
            f"Dispatched {payload.failed} test failure notification emails for test run "
            f"in {payload.environment} environment"
        )
        
        return {
            "status": "notifications_dispatched",
            "environment": payload.environment,
            "total_tests": payload.total_tests,
            "passed": payload.passed,
            "failed": payload.failed,
            "notifications_sent": payload.failed,
            "recipient": admin_email
        }
        
    except Exception as e:
        logger.error(f"Failed to dispatch test run summary notifications: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to dispatch notifications: {str(e)}"
        )


# ---------------------------------------------------------------------------
# PDF processing trigger endpoint
# Called by the uploads server after a PDF is stored in S3.
# Dispatches the background OCR/TOC/screenshot processing Celery task.
# ---------------------------------------------------------------------------

class PdfProcessPayload(BaseModel):
    """Payload sent by the uploads server to trigger PDF background processing."""
    embed_id: str = Field(..., description="Embed ID for the uploaded PDF.")
    user_id: str = Field(..., description="User ID who uploaded the PDF.")
    vault_key_id: str = Field(..., description="User's Vault Transit key ID for decryption.")
    s3_key: str = Field(..., description="S3 key of the encrypted PDF file.")
    s3_base_url: str = Field(..., description="S3 bucket base URL.")
    vault_wrapped_aes_key: str = Field(..., description="Vault-wrapped AES key for the PDF.")
    aes_nonce: str = Field(..., description="Base64 AES-GCM nonce for the PDF.")
    filename: str = Field(..., description="Original filename of the PDF.")
    page_count: int = Field(..., description="Number of pages in the PDF.")
    credits_charged: int = Field(default=0, description="Credits charged upfront (for refund on failure).")
    user_id_hash: str = Field(default="", description="SHA256 hash of user_id for billing.")
    chat_id: Optional[str] = Field(None, description="Chat ID (may be available from context).")
    message_id: Optional[str] = Field(None, description="Message ID (may be available from context).")


@router.post("/pdf/process", status_code=202)
async def trigger_pdf_processing(
    payload: PdfProcessPayload,
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Trigger background PDF processing after a successful upload.

    Called by the uploads microservice (fire-and-forget pattern).
    Dispatches a Celery task on the app_pdf queue to run:
      - Mistral OCR
      - Page screenshot rendering (pymupdf)
      - TOC and legend detection (Groq)
      - S3 artefact upload
      - Embed TOON content delivery to client

    Also stores the Celery task ID in Redis under pdf_task:<embed_id> (TTL 2h)
    so that a subsequent cancel request can revoke the task.

    Returns 202 Accepted immediately; processing happens in the background.
    """
    logger.info(
        f"[PDF Process] Triggering background processing for embed {payload.embed_id[:8]}... "
        f"({payload.page_count} pages, user {payload.user_id[:8]}...)"
    )

    from backend.core.api.app.tasks.celery_config import send_task_validated

    task_result = send_task_validated(
        task_name="apps.pdf.tasks.process_pdf",
        kwargs={"arguments": payload.dict()},
        queue="app_pdf",
    )

    logger.info(
        f"[PDF Process] Task dispatched: task_id={task_result.id}, "
        f"embed_id={payload.embed_id[:8]}..."
    )

    # Cache the task ID so a cancel request can revoke it.
    # TTL of 2 hours is generous — OCR tasks typically finish in under 5 minutes.
    try:
        await cache_service.set(
            key=f"pdf_task:{payload.embed_id}",
            value=task_result.id,
            ttl=7200,
        )
    except Exception as cache_err:
        # Non-fatal: cancel won't work but OCR will still complete.
        logger.warning(
            f"[PDF Process] Failed to cache task ID for embed {payload.embed_id[:8]}: {cache_err}"
        )

    return {
        "status": "accepted",
        "task_id": task_result.id,
        "embed_id": payload.embed_id,
        "page_count": payload.page_count,
    }


class PdfCancelPayload(BaseModel):
    """Payload sent by the WebSocket handler to cancel an in-progress PDF OCR task."""
    embed_id: str = Field(..., description="Embed ID whose Celery task should be revoked.")
    user_id: str = Field(..., description="User ID — used for logging and auth verification.")


@router.post("/pdf/cancel", status_code=200)
async def cancel_pdf_processing(
    payload: PdfCancelPayload,
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Cancel an in-progress PDF OCR Celery task.

    Called by the cancel_pdf_processing WebSocket handler when the user presses
    Stop during OCR processing (status='processing').

    Flow:
      1. Look up the Celery task ID stored at pdf_task:<embed_id> in Redis.
      2. If found, revoke the task (with SIGTERM so it terminates cleanly).
      3. Remove the Redis key so subsequent accidental calls are no-ops.

    Returns 200 even if the task was not found (it may have already completed).
    The client-side cleanup (delete embed node, deleteDraftEmbed) is handled
    separately by the WebSocket handler.
    """
    logger.info(
        f"[PDF Cancel] Cancel request for embed {payload.embed_id[:8]}... by user {payload.user_id[:8]}..."
    )

    # Look up the Celery task ID in Redis.
    task_id: Optional[str] = None
    try:
        task_id = await cache_service.get(f"pdf_task:{payload.embed_id}")
    except Exception as cache_err:
        logger.warning(
            f"[PDF Cancel] Failed to read task ID from cache for embed {payload.embed_id[:8]}: {cache_err}"
        )

    if not task_id:
        logger.info(
            f"[PDF Cancel] No pending task found for embed {payload.embed_id[:8]} — "
            "task may have already completed or was never started."
        )
        return {"status": "not_found", "embed_id": payload.embed_id}

    # Revoke the Celery task so the PDF worker stops processing.
    # terminate=True sends SIGTERM to the worker process handling this task.
    try:
        from backend.core.api.app.tasks.celery_config import app as celery_app
        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        logger.info(
            f"[PDF Cancel] Revoked Celery task {task_id[:8]}... for embed {payload.embed_id[:8]}..."
        )
    except Exception as revoke_err:
        logger.error(
            f"[PDF Cancel] Failed to revoke task {task_id[:8]}: {revoke_err}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to revoke PDF processing task: {str(revoke_err)}",
        )

    # Remove the Redis key — the task is no longer cancellable.
    try:
        await cache_service.delete(f"pdf_task:{payload.embed_id}")
    except Exception as del_err:
        # Non-fatal — TTL will clean it up.
        logger.warning(
            f"[PDF Cancel] Failed to delete cached task ID for embed {payload.embed_id[:8]}: {del_err}"
        )

    return {
        "status": "revoked",
        "task_id": task_id,
        "embed_id": payload.embed_id,
    }


# ---------------------------------------------------------------------------
# Content safety rejection tracking endpoint
# Called by the upload server when SightEngine rejects a chat image or profile
# image upload for nudity, violence, or gore.  Tracks per-user rejection counts
# in Redis and deletes accounts that repeatedly upload policy-violating content.
# ---------------------------------------------------------------------------

class ContentSafetyRejectRequest(BaseModel):
    """Payload sent by the upload server when SightEngine rejects an image."""
    user_id: str = Field(..., description="ID of the user who uploaded the rejected image")
    rejection_reason: str = Field(
        ..., description="Short reason string from SightEngine (e.g. 'sexual_activity=0.95')"
    )
    upload_type: str = Field(
        default="chat_image",
        description="'chat_image' or 'profile_image' — separate Redis counters per type"
    )


@router.post("/uploads/content-safety-reject")
async def content_safety_reject(
    payload: ContentSafetyRejectRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Track a content safety rejection for a user and delete the account on the 4th violation.

    Called by the app-uploads microservice when SightEngine (nudity-2.0, offensive, gore
    models) rejects a user-uploaded image.  Mirrors the rejection tracking logic that was
    previously inline in settings.py's update_profile_image endpoint.

    Rejection counter logic:
    - Redis key: "{upload_type}_rejects:{user_id}" — separate counter per upload type
    - TTL: 24 hours (same as the original settings.py implementation)
    - On 4th rejection (>= 4): delete the user account immediately
    - Returns "tracked" on normal increments, "account_deleted" when the account is removed

    Security:
    - Protected by INTERNAL_API_SHARED_TOKEN (same as all /internal/* routes)
    - Never modifies anything other than the reject counter and optional account deletion
    """
    log_prefix = f"[ContentSafetyReject] [user:{payload.user_id[:8]}...] [{payload.upload_type}]"
    logger.info(
        f"{log_prefix} Received rejection — reason: {payload.rejection_reason[:80]}"
    )

    # Redis key uses upload_type as prefix so chat_image and profile_image counters are
    # tracked independently (the original settings.py used "profile_image_rejects:" only).
    reject_key = f"{payload.upload_type}_rejects:{payload.user_id}"

    try:
        # Fetch current reject count from Redis
        raw = await cache_service.get(reject_key)
        reject_count = int(raw) if raw else 0

        # Increment and persist with 24-hour TTL
        reject_count += 1
        await cache_service.set(reject_key, reject_count, ttl=86400)

        logger.info(f"{log_prefix} Rejection count updated → {reject_count}")

        if reject_count >= 4:
            # Policy violation threshold reached — delete the account.
            # We do NOT have the client IP / device fingerprint here (the upload server
            # doesn't forward them to internal endpoints).  We pass None for those fields
            # so the deletion is still logged correctly in Directus.
            logger.warning(
                f"{log_prefix} Threshold reached (count={reject_count}). "
                f"Deleting user account."
            )
            try:
                await directus_service.delete_user(
                    payload.user_id,
                    deletion_type="policy_violation",
                    reason=f"repeated_inappropriate_{payload.upload_type}s",
                    ip_address=None,
                    device_fingerprint=None,
                    details={
                        "reject_count": reject_count,
                        "upload_type": payload.upload_type,
                        "timestamp": int(time.time()),
                    },
                )
            except Exception as del_err:
                logger.error(
                    f"{log_prefix} Account deletion FAILED: {del_err}", exc_info=True
                )
                # Still clean up cache so subsequent requests don't keep incrementing
                # a now-orphaned counter.  Fall through to return tracked.

            # Clean up cache regardless of deletion success
            await cache_service.delete_user_cache(payload.user_id)
            await cache_service.delete(reject_key)

            return {
                "result": "account_deleted",
                "reject_count": reject_count,
            }

        return {
            "result": "tracked",
            "reject_count": reject_count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Content safety rejection tracking failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Profile image processing endpoint
# Called by the upload server after a profile image is stored in S3.
# Encrypts the public image URL and updates the user's Directus profile + cache.
# Does NOT update last_opened (user is past signup when using settings).
# ---------------------------------------------------------------------------

class ProfileImageProcessRequest(BaseModel):
    """
    Payload sent by the upload server after AES-encrypting and uploading a profile image.

    The upload server performs AES-256-GCM encryption locally and uploads the ciphertext
    to the private S3 bucket before calling this endpoint.  This endpoint then:
    - Vault-wraps the plaintext AES key (the upload server never touches Vault)
    - Reads and deletes the old profile_image_s3_key from S3 (to prevent orphaned blobs)
    - Persists the three new encrypted-image fields to Directus
    - Updates the Redis cache with the proxy URL for fast UI reads
    """
    user_id: str = Field(..., description="ID of the user whose profile image was uploaded")
    s3_key: str = Field(..., description="S3 object key in the private profile-images bucket (e.g. '{user_id}-{ts}-{rand}.enc')")
    aes_key_b64: str = Field(..., description="Plaintext AES-256 key (base64) — will be Vault-wrapped; NEVER stored as-is")
    nonce_b64: str = Field(..., description="AES-GCM nonce (base64, 12 bytes)")
    target_env: str = Field(default="prod", description="'dev' or 'prod' — selects the correct S3 bucket for old-key deletion")


@router.post("/profile-image/process")
async def process_profile_image(
    payload: ProfileImageProcessRequest,
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """
    Vault-wrap the AES key, clean up old S3 object, persist encrypted profile image fields.

    Called by the app-uploads microservice (POST /v1/upload/profile-image) after
    AES-256-GCM encrypting the image bytes and uploading the ciphertext to the
    private S3 profile-images bucket.

    Pipeline:
    1. Fetch the user's vault_key_id (cache-first, then Directus)
    2. Read existing profile_image_s3_key from Directus (needed for old-object cleanup)
    3. Vault-wrap the plaintext AES key using the user's Transit key
    4. Write profile_image_s3_key, encrypted_profile_image_aes_key, profile_image_aes_nonce
       to Directus (intentionally NOT updating last_opened)
    5. Delete the old S3 object from the private bucket (if one existed)
    6. Update Redis cache with the proxy URL /v1/users/{user_id}/profile-image

    Security:
    - Protected by INTERNAL_API_SHARED_TOKEN (same as all /internal/* routes)
    - Plaintext AES key is Vault-wrapped immediately; never stored in plaintext
    - Old S3 objects are cleaned up to prevent orphaned encrypted blobs
    """
    log_prefix = f"[ProfileImageProcess] [user:{payload.user_id[:8]}...]"
    logger.info(f"{log_prefix} Processing encrypted profile image (s3_key={payload.s3_key})")

    proxy_url = f"/v1/users/{payload.user_id}/profile-image"

    try:
        # 1. Always fetch profile from Directus to get vault_key_id + existing s3_key for cleanup
        # (Cache only stores a subset of fields; profile_image_s3_key is not cached)
        vault_key_id = await cache_service.get_user_vault_key_id(payload.user_id)

        profile_success, user_data, profile_msg = await directus_service.get_user_profile(
            payload.user_id
        )
        if not profile_success or not user_data:
            logger.error(f"{log_prefix} Could not fetch user profile: {profile_msg}")
            raise HTTPException(status_code=404, detail="User not found")

        if not vault_key_id:
            vault_key_id = user_data.get("vault_key_id")
            if not vault_key_id:
                logger.error(f"{log_prefix} vault_key_id missing in Directus profile")
                raise HTTPException(
                    status_code=500,
                    detail="User account incomplete: missing encryption key",
                )
            # Cache it so future requests skip the Directus round-trip
            await cache_service.update_user(payload.user_id, {"vault_key_id": vault_key_id})

        # Read old S3 key BEFORE overwriting so we can delete it after a successful write
        old_s3_key: Optional[str] = user_data.get("profile_image_s3_key")
        if old_s3_key:
            logger.debug(f"{log_prefix} Existing profile_image_s3_key will be replaced: {old_s3_key}")

        # 2. Vault-wrap the plaintext AES key using the user's Transit key.
        # The wrapped (ciphertext) form is what gets stored in Directus.
        # The plaintext key is never persisted.
        wrapped_aes_key, _key_version = await encryption_service.encrypt_with_user_key(
            payload.aes_key_b64, vault_key_id
        )
        if not wrapped_aes_key:
            logger.error(f"{log_prefix} Vault Transit key-wrapping returned empty result")
            raise HTTPException(status_code=500, detail="AES key wrapping failed")

        # 3. Persist the three new encrypted-image fields to Directus.
        # Intentionally NOT updating last_opened here.
        success = await directus_service.update_user(
            payload.user_id,
            {
                "profile_image_s3_key": payload.s3_key,
                "encrypted_profile_image_aes_key": wrapped_aes_key,
                "profile_image_aes_nonce": payload.nonce_b64,
            },
        )
        if not success:
            logger.error(f"{log_prefix} Directus update_user returned failure")
            raise HTTPException(
                status_code=500, detail="Failed to persist profile image to user profile"
            )

        # 4. Delete the old encrypted S3 object (only after a successful Directus write).
        # Non-fatal: if deletion fails the old blob is orphaned but the new image is live.
        if old_s3_key:
            try:
                s3_service = request.app.state.s3_service
                await s3_service.delete_file("profile_images_private", old_s3_key)
                logger.info(f"{log_prefix} Deleted old profile image S3 object: {old_s3_key}")
            except Exception as e:
                logger.warning(
                    f"{log_prefix} Failed to delete old S3 object {old_s3_key}: {e} "
                    f"(Directus updated successfully — new image is active)"
                )

        # 5. Update Redis cache with the proxy URL for fast UI reads
        cache_success = await cache_service.update_user(
            payload.user_id,
            {"profile_image_url": proxy_url},
        )
        if not cache_success:
            # Non-fatal: Directus is source of truth; cache refreshes on next login
            logger.warning(
                f"{log_prefix} Redis cache update failed (Directus was updated successfully)"
            )

        logger.info(f"{log_prefix} Encrypted profile image processed successfully → {proxy_url}")
        return {"status": "ok", "url": proxy_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Profile image processing failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# S3 file download endpoint (internal, for app containers)
# ---------------------------------------------------------------------------


@router.get("/s3/download")
async def download_s3_file(
    request: Request,
    bucket_key: str = Query(..., description="Bucket config key (e.g. 'chatfiles')"),
    s3_key: str = Query(..., description="S3 object key"),
    s3_service: S3UploadService = Depends(get_s3_service),
):
    """
    Download an encrypted file from S3 and return its raw bytes.

    Internal-only endpoint for app containers (app-images, app-audio, app-pdf)
    that need to fetch encrypted files from the private chatfiles bucket.
    The chatfiles bucket is private — direct HTTP GET is no longer allowed.
    This endpoint uses boto3 get_object with server-side credentials.

    Args:
        bucket_key: Bucket config key (e.g. "chatfiles", "invoices").
        s3_key: Full S3 object key.

    Returns:
        Raw bytes of the S3 object (encrypted ciphertext).

    Raises:
        400: Invalid bucket_key or s3_key.
        404: File not found in S3.
        500: Download failed.
    """
    from backend.core.api.app.services.s3.config import get_bucket_name

    if not s3_key or not s3_key.strip():
        raise HTTPException(status_code=400, detail="s3_key is required")
    if ".." in s3_key or s3_key.startswith("/") or "://" in s3_key:
        raise HTTPException(status_code=400, detail="Invalid s3_key")

    try:
        environment = os.getenv("SERVER_ENVIRONMENT", "development")
        bucket_name = get_bucket_name(bucket_key, environment)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown bucket: {bucket_key}")

    try:
        content = await s3_service.get_file(bucket_name=bucket_name, object_key=s3_key)
        if content is None:
            raise HTTPException(status_code=404, detail=f"File not found: {s3_key}")

        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Cache-Control": "no-store"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[S3 Download] Failed for {bucket_key}/{s3_key}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"S3 download failed: {str(e)}")



# ---------------------------------------------------------------------------
# S3 temporary public image upload (for reverse image search via Google Lens)
# ---------------------------------------------------------------------------

class UploadTempImageRequest(BaseModel):
    """Request body for /internal/s3/upload-temp-image."""
    image_bytes_b64: str = Field(
        ...,
        description="Base64-encoded plaintext image bytes to upload.",
    )
    content_type: str = Field(
        default="image/webp",
        description="MIME type of the image (e.g. 'image/webp', 'image/jpeg').",
    )
    filename: str = Field(
        ...,
        description="Filename used as the S3 object key suffix (e.g. 'abc123.webp').",
    )


class UploadTempImageResponse(BaseModel):
    """Response from /internal/s3/upload-temp-image."""
    public_url: str = Field(..., description="Public HTTP URL accessible by Google Lens.")
    s3_key: str = Field(..., description="S3 object key for cleanup after search.")


@router.post("/s3/upload-temp-image", response_model=UploadTempImageResponse)
async def upload_temp_image(
    request: Request,
    body: UploadTempImageRequest,
    s3_service: S3UploadService = Depends(get_s3_service),
) -> UploadTempImageResponse:
    """
    Upload a plaintext image to the temporary public S3 bucket for Google Lens reverse search.

    The 'temp_images' bucket is public-read with a 1-day lifecycle policy, so Google's
    crawlers can fetch the image URL without auth. The skill calls this endpoint, obtains
    the public URL, passes it to SerpAPI Google Lens, then optionally deletes the file.

    Protected by INTERNAL_API_SHARED_TOKEN like all /internal/* routes.

    Args:
        body.image_bytes_b64: Base64-encoded plaintext image bytes.
        body.content_type: MIME type of the image.
        body.filename: Suffix for the S3 key (e.g. 'abc123.webp').

    Returns:
        public_url: Publicly accessible URL Google Lens can fetch.
        s3_key:     Object key for the caller to delete after use.
    """
    import base64 as _b64
    import uuid as _uuid
    from backend.core.api.app.services.s3.config import get_bucket_name

    if not body.image_bytes_b64.strip():
        raise HTTPException(status_code=400, detail="image_bytes_b64 is required")

    try:
        image_bytes = _b64.b64decode(body.image_bytes_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {exc}")

    # Max 20 MB
    MAX_TEMP_IMAGE_BYTES = 20 * 1024 * 1024
    if len(image_bytes) > MAX_TEMP_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large: {len(image_bytes)} bytes (max {MAX_TEMP_IMAGE_BYTES})",
        )

    # Generate a unique S3 key with a short random prefix so filenames cannot be guessed
    unique_prefix = _uuid.uuid4().hex[:16]
    s3_key = f"reverse_search/{unique_prefix}_{body.filename}"

    environment = os.getenv("SERVER_ENVIRONMENT", "development")
    bucket_name = get_bucket_name("temp_images", environment)

    try:
        await s3_service.upload_file(
            bucket_key="temp_images",
            file_key=s3_key,
            content=image_bytes,
            content_type=body.content_type,
        )
    except Exception as exc:
        logger.error(
            "[UploadTempImage] S3 upload failed for key %s: %s", s3_key, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Temp image upload failed: {exc}")

    # Construct the public URL for the uploaded object
    # Format: https://{bucket_name}.{region}.your-objectstorage.com/{s3_key}
    public_url = f"https://{bucket_name}.{s3_service.base_domain}/{s3_key}"
    logger.info(
        "[UploadTempImage] Uploaded %d bytes to %s (key=%s)",
        len(image_bytes), bucket_name, s3_key,
    )

    return UploadTempImageResponse(public_url=public_url, s3_key=s3_key)


@router.delete("/s3/temp-image")
async def delete_temp_image(
    request: Request,
    s3_key: str = Query(..., description="S3 object key to delete from temp_images bucket"),
    s3_service: S3UploadService = Depends(get_s3_service),
) -> Dict[str, Any]:
    """
    Delete a previously uploaded temporary public image from the temp_images bucket.

    Called by the search skill after Google Lens finishes, so plaintext images do not
    linger in the public bucket longer than necessary. The 1-day lifecycle policy is
    a safety net; this endpoint provides immediate cleanup.

    Protected by INTERNAL_API_SHARED_TOKEN like all /internal/* routes.
    """
    if not s3_key or not s3_key.strip():
        raise HTTPException(status_code=400, detail="s3_key is required")
    if ".." in s3_key or s3_key.startswith("/") or "://" in s3_key:
        raise HTTPException(status_code=400, detail="Invalid s3_key")

    try:
        await s3_service.delete_file(bucket_key="temp_images", file_key=s3_key)
        logger.info("[DeleteTempImage] Deleted temp image: %s", s3_key)
        return {"status": "deleted", "s3_key": s3_key}
    except Exception as exc:
        logger.error(
            "[DeleteTempImage] Failed to delete %s: %s", s3_key, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to delete temp image: {exc}")


# ---------------------------------------------------------------------------
# Alertmanager webhook receiver
# ---------------------------------------------------------------------------

class AlertmanagerAlert(BaseModel):
    """A single alert entry in the Alertmanager webhook payload."""
    status: str  # "firing" or "resolved"
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    startsAt: str = ""
    endsAt: Optional[str] = None


class AlertmanagerWebhookPayload(BaseModel):
    """
    Alertmanager webhook v4 payload.
    See: https://prometheus.io/docs/alerting/latest/configuration/#webhook_config
    """
    version: str = "4"
    status: str  # "firing" or "resolved" (group-level)
    groupLabels: Dict[str, str] = Field(default_factory=dict)
    commonLabels: Dict[str, str] = Field(default_factory=dict)
    commonAnnotations: Dict[str, str] = Field(default_factory=dict)
    alerts: List[AlertmanagerAlert] = Field(default_factory=list)


@router.post("/alerts/webhook")
async def alertmanager_webhook(
    payload: AlertmanagerWebhookPayload,
    request: Request,
) -> Dict[str, Any]:
    """
    Receive Alertmanager webhook notifications and dispatch email tasks.

    Alertmanager still handles grouping, throttling and inhibition.
    This endpoint replaces Alertmanager's built-in SMTP delivery with
    the existing Brevo/Mailjet email infrastructure.

    For each alert in the payload a separate email task is queued so
    that each alert produces one email. If SERVER_OWNER_EMAIL is not
    configured the payload is accepted (200 OK) but no email is sent —
    this prevents Alertmanager from retrying endlessly when email is
    intentionally disabled.

    Protected by internal service token (X-Internal-Service-Token header).
    Architecture: See docs/architecture/logging-and-monitoring.md
    """
    from backend.core.api.app.tasks.celery_config import app as celery_app

    logger.info(
        f"Alertmanager webhook received: status={payload.status}, "
        f"alert_count={len(payload.alerts)}, "
        f"group_labels={payload.groupLabels}"
    )

    admin_email = os.getenv("SERVER_OWNER_EMAIL")
    if not admin_email:
        logger.warning(
            "SERVER_OWNER_EMAIL not configured — alertmanager webhook received but "
            "no email will be sent. Set SERVER_OWNER_EMAIL in .env to enable alerts."
        )
        return {
            "status": "no_recipient",
            "reason": "SERVER_OWNER_EMAIL not configured",
            "alerts_received": len(payload.alerts),
        }

    dispatched = 0
    errors = 0

    for alert in payload.alerts:
        alertname = alert.labels.get("alertname") or payload.groupLabels.get("alertname", "UnknownAlert")
        severity = alert.labels.get("severity") or payload.commonLabels.get("severity", "unknown")
        summary = alert.annotations.get("summary") or payload.commonAnnotations.get("summary", "")
        description = alert.annotations.get("description") or payload.commonAnnotations.get("description")
        starts_at = alert.startsAt or ""

        # Only include ends_at for resolved alerts (Alertmanager sets it to epoch for firing)
        ends_at = None
        if alert.status == "resolved" and alert.endsAt and alert.endsAt != "0001-01-01T00:00:00Z":
            ends_at = alert.endsAt

        # Format all alert labels as a human-readable string for debugging context
        labels_str = None
        if alert.labels:
            labels_str = "\n".join(f"{k}: {v}" for k, v in sorted(alert.labels.items()))

        try:
            celery_app.send_task(
                name="app.tasks.email_tasks.alert_notification_email_task.send_alert_notification",
                args=[
                    admin_email,
                    alertname,
                    alert.status,
                    severity,
                    summary,
                    starts_at,
                    description,
                    ends_at,
                    labels_str,
                ],
                queue="email",
            )
            dispatched += 1
            logger.info(
                f"Dispatched alert notification task: alertname='{alertname}', "
                f"status={alert.status}, severity={severity}, recipient={admin_email}"
            )
        except Exception as e:
            errors += 1
            logger.error(
                f"Failed to dispatch alert notification for alertname='{alertname}': {e}",
                exc_info=True,
            )

    return {
        "status": "processed",
        "alerts_received": len(payload.alerts),
        "notifications_dispatched": dispatched,
        "errors": errors,
        "recipient": admin_email,
    }


# ---------------------------------------------------------------------------
# Cron Job Session Notification
# ---------------------------------------------------------------------------

class CronSessionNotificationPayload(BaseModel):
    """Payload for cron job session email notification."""
    job_type: str = Field(..., description="Job category: audit, security, redteam, dependabot, dead-code, deploy-fix, test-analysis, issues, workflow-review")
    job_name: str = Field(..., description="Human-readable session title")
    status: str = Field(..., description="Session outcome: completed, failed, or timeout")
    session_id: Optional[str] = Field(None, description="Claude Code session UUID")
    duration_seconds: Optional[int] = Field(None, description="Session duration in seconds")
    context_summary: Optional[str] = Field(None, description="Brief description of what happened")
    exit_code: Optional[int] = Field(None, description="Process exit code")


@router.post("/dispatch-cron-session-email")
async def dispatch_cron_session_email(
    payload: CronSessionNotificationPayload,
    request: Request,
) -> Dict[str, Any]:
    """
    Dispatch a cron job session notification email to the admin.

    Called by scripts/_claude_utils.py after each automated Claude Code session
    completes (or fails/times out). Non-fatal — cron jobs should not fail if
    this endpoint is unreachable.

    Protected by internal service token (X-Internal-Service-Token header).
    Architecture: See docs/architecture/infrastructure/cronjobs.md
    """
    from backend.core.api.app.tasks.celery_config import app as celery_app

    admin_email = os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL")
    if not admin_email:
        logger.warning(
            "SERVER_OWNER_EMAIL/ADMIN_NOTIFY_EMAIL not configured — "
            "cron session notification skipped."
        )
        return {"status": "no_recipient", "reason": "no admin email configured"}

    try:
        celery_app.send_task(
            name="app.tasks.email_tasks.cron_session_email_task.send_cron_session_notification",
            args=[
                admin_email,
                payload.job_type,
                payload.job_name,
                payload.status,
                payload.session_id,
                payload.duration_seconds,
                payload.context_summary,
                payload.exit_code,
            ],
            queue="email",
        )
        logger.info(
            f"Dispatched cron session notification: job_type={payload.job_type}, "
            f"status={payload.status}, recipient={admin_email}"
        )
        return {"status": "dispatched", "recipient": admin_email}
    except Exception as e:
        logger.error(f"Failed to dispatch cron session notification: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
