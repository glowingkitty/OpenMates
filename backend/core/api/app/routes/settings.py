from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request, Security
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer
import logging
import time
import os
import random
import string
import hashlib
import json
import glob
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field # Import BaseModel and Field for response models

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_compliance_service, get_current_user, get_encryption_service, get_current_user_or_api_key
from backend.core.api.app.services.image_safety import ImageSafetyService
from backend.core.api.app.services.s3 import S3UploadService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip # Updated imports
from backend.core.api.app.schemas.settings import LanguageUpdateRequest, DarkModeUpdateRequest, TimezoneUpdateRequest, AutoTopUpLowBalanceRequest, BillingOverviewResponse, InvoiceResponse # Import request/response models

# Create an optional API key scheme that doesn't fail if missing (for endpoints that support both session and API key auth)
optional_api_key_scheme = HTTPBearer(
    scheme_name="API Key",
    description="Enter your API key. API keys start with 'sk-api-'. Use format: Bearer sk-api-...",
    auto_error=False  # Don't raise error if missing - allows session auth to work
)

router = APIRouter(prefix="/v1/settings", tags=["Settings"])
logger = logging.getLogger(__name__)

# --- Define a simple success response model ---
class SimpleSuccessResponse(BaseModel):
    success: bool
    message: str


# --- Endpoint for updating profile image ---
@router.post("/user/update_profile_image", response_model=dict, include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("10/minute")  # Prevent abuse of profile image uploads
async def update_profile_image(
    request: Request,  # Keep request parameter for IP/fingerprint
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    # Access services from app state
    s3_service: S3UploadService = request.app.state.s3_service
    image_safety_service: ImageSafetyService = request.app.state.image_safety_service
    cache_service: CacheService = request.app.state.cache_service # Explicitly get cache service
    directus_service: DirectusService = request.app.state.directus_service # Explicitly get directus service
    encryption_service: EncryptionService = request.app.state.encryption_service # Explicitly get encryption service

    if not s3_service or not image_safety_service or not cache_service or not directus_service or not encryption_service:
         logger.error("Required services not available in app state for settings route.")
         raise HTTPException(status_code=503, detail="Service unavailable")

    bucket_config = s3_service.get_bucket_config('profile_images')
    
    try:
        # Validate content type first (cheapest check)
        if file.content_type not in bucket_config['allowed_types']:
            raise HTTPException(status_code=400, detail="Invalid file type")

        # Check file size before reading entire content
        if file.size and file.size > bucket_config['max_size']:
            raise HTTPException(status_code=400, detail="File too large")

        # Read image content only after validation
        image_content = await file.read()
        
        # Double check actual content size
        if len(image_content) > bucket_config['max_size']:
            raise HTTPException(status_code=400, detail="File too large")

        # Check rejected uploads count from cache (using service from backend.core.api.app.state)
        reject_key = f"profile_image_rejects:{current_user.id}"
        reject_count = await cache_service.get(reject_key) or 0

        # Check image safety (using service from backend.core.api.app.state)
        is_safe = await image_safety_service.check_profile_image(image_content)
        if not is_safe:
            # Increment and store reject count
            reject_count += 1
            await cache_service.set(reject_key, reject_count, ttl=86400)  # 24h TTL

            if reject_count >= 4:  # Changed from 3 to 4 (delete on 4th attempt)
                # Get device information for compliance logging
                # Generate device hash using the current_user.id
                device_hash, _, _, _, _, _, _, _ = generate_device_fingerprint_hash(request, user_id=current_user.id)
                client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)

                # Delete user account with proper reason
                # Note: The deletion will be logged by the delete_user method (using service from backend.core.api.app.state)
                await directus_service.delete_user(
                    current_user.id,
                    deletion_type="policy_violation",
                    reason="repeated_inappropriate_profile_images",
                    ip_address=client_ip,
                    device_fingerprint=device_hash, # Use generated device_hash
                    details={
                        "reject_count": reject_count,
                        "timestamp": int(time.time())
                    }
                )
                
                # Clean all user data from cache using the enhanced method
                await cache_service.delete_user_cache(current_user.id)
                
                # Also delete the reject count key
                await cache_service.delete(reject_key)
                    
                return {
                    "status": "account_deleted",
                    "detail": "Account deleted due to policy violations"
                }
            
            return {
                "status": "error",
                "detail": "Image not allowed",
                "reject_count": reject_count
            }

        # Reset reject count if upload is successful
        await cache_service.delete(reject_key)

        # Generate unique filename
        file_ext = os.path.splitext(file.filename)[1].lower()
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        new_filename = f"{current_user.id}-{int(time.time())}-{random_suffix}{file_ext}"

        # Get old image URL from the current user object (already fetched/cached)
        old_url = current_user.profile_image_url

        # Upload new image (using service from backend.core.api.app.state)
        upload_result = await s3_service.upload_file(
            bucket_key='profile_images',
            file_key=new_filename,
            content=image_content,
            content_type=file.content_type
        )
        
        # Profile images bucket is public read - always use regular URL, not presigned URL
        image_url = upload_result['url']

        # --- Get vault_key_id from current_user (cached or fetched by dependency) ---
        vault_key_id = current_user.vault_key_id
        if not vault_key_id:
             logger.error(f"User {current_user.id} does not have a vault_key_id in current_user object")
             raise HTTPException(status_code=500, detail="User encryption key not found")
        # --- End get vault_key_id ---

        # Encrypt URL (using service from backend.core.api.app.state)
        encrypted_url, _ = await encryption_service.encrypt_with_user_key(image_url, vault_key_id) # Use encrypt_with_user_key

        # Update Directus (using service from backend.core.api.app.state)
        await directus_service.update_user(current_user.id, {
            "encrypted_profileimage_url": encrypted_url,
            "last_opened": "/signup/credits" # For now we skip settings and mate settings, will implement those later again
        })

        # Update cache with new image URL and last_opened step
        logger.info(f"Attempting to update cache for user {current_user.id} after profile image upload.")
        cache_update_success = await cache_service.update_user(current_user.id, {
            "profile_image_url": image_url,
            "last_opened": "/signup/credits" # For now we skip settings and mate settings, will implement those later again
        })
        if cache_update_success:
            logger.info(f"Successfully updated cache for user {current_user.id} with new profile image URL.")
        else:
            # Log warning, but don't fail the request as Directus was updated
            logger.warning(f"Failed to update cache for user {current_user.id} after profile image upload, but Directus was updated.")

        # Delete old image from S3
        if old_url:
            old_key = old_url.split('/')[-1]
            await s3_service.delete_file('profile_images', old_key) # Use service from backend.core.api.app.state

        return {"url": image_url}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        raise HTTPException(status_code=500, detail="Error processing image")

# --- Endpoint for Privacy & Apps Consent ---
@router.post("/user/consent/privacy-apps", response_model=SimpleSuccessResponse, include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("30/minute")  # Prevent abuse of consent updates
async def record_privacy_apps_consent(
    request: Request, # Add request parameter for compliance logging
    current_user: User = Depends(get_current_user), # Use get_current_user dependency
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service) # Inject compliance service
):
    """Records the timestamp for privacy and apps settings consent."""
    logger.info(f"Recording privacy/apps consent for user {current_user.id}")
    current_timestamp_str = str(int(time.time()))
    user_id = current_user.id
    client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None) # Get client IP

    # Data to update
    update_data = {
        "consent_privacy_and_apps_default_settings": current_timestamp_str,
        "last_opened": "/signup/mate-settings"
    }
    
    try:
        # Update Directus
        success_directus = await directus_service.update_user(user_id, update_data)
        if not success_directus:
            logger.error(f"Failed to update Directus for privacy/apps consent for user {user_id}")
            # NO compliance log for failure
            raise HTTPException(status_code=500, detail="Failed to save consent")
            
        # Update Cache using user_id with string timestamp value for consent
        cache_update_data = {
            "consent_privacy_and_apps_default_settings": current_timestamp_str, # Store string timestamp
            "last_opened": update_data["last_opened"] # Keep last_opened update
        }
        cache_update_success = await cache_service.update_user(user_id, cache_update_data)
        if not cache_update_success:
            # Log warning, but don't fail the request as Directus was updated
            logger.warning(f"Failed to update cache for user {user_id} after privacy/apps consent, but Directus was updated.")
        else:
            logger.info(f"Successfully updated cache for user {user_id} after privacy/apps consent.")

        # Log compliance event success with correct event type
        compliance_service.log_auth_event(
            event_type="consent_privacy_and_apps_default_settings", # Use field name as event type
            user_id=user_id, 
            ip_address=client_ip, 
            status="success", 
            details={"timestamp": current_timestamp_str}
        )

        return SimpleSuccessResponse(success=True, message="Privacy and apps consent recorded")

    except HTTPException as e:
        # NO compliance log for failure
        raise e
    except Exception as e:
        logger.error(f"Error recording privacy/apps consent for user {user_id}: {str(e)}")
        # NO compliance log for failure
        raise HTTPException(status_code=500, detail="An error occurred while saving consent")

# --- Endpoint for updating user language ---
@router.post("/user/language", response_model=SimpleSuccessResponse, include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("30/minute")  # Prevent abuse of language updates
async def update_user_language(
    request: Request,
    request_data: LanguageUpdateRequest, # Use Pydantic model for request body validation
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """Updates the user's preferred language setting."""
    user_id = current_user.id
    new_language = request_data.language
    logger.info(f"Updating language for user {user_id} to {new_language}")

    # Basic validation (could add check against allowed languages if needed)
    if not new_language or len(new_language) > 10: # Simple length check
        raise HTTPException(status_code=400, detail="Invalid language code provided")

    update_data = {"language": new_language}

    try:
        # Update Directus
        success_directus = await directus_service.update_user(user_id, update_data)
        if not success_directus:
            logger.error(f"Failed to update Directus for language setting for user {user_id}")
            raise HTTPException(status_code=500, detail="Failed to save language setting")

        # Update Cache
        cache_update_success = await cache_service.update_user(user_id, update_data)
        if not cache_update_success:
            logger.warning(f"Failed to update cache for user {user_id} after language update, but Directus was updated.")
        else:
            logger.info(f"Successfully updated cache for user {user_id} after language update.")

        return SimpleSuccessResponse(success=True, message="Language setting updated successfully")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating language for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred while updating language setting")

# --- Endpoint for updating user dark mode preference ---
@router.post("/user/darkmode", response_model=SimpleSuccessResponse, include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("30/minute")  # Prevent abuse of dark mode updates
async def update_user_darkmode(
    request: Request,
    request_data: DarkModeUpdateRequest, # Use Pydantic model for request body validation
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """Updates the user's dark mode preference."""
    user_id = current_user.id
    new_darkmode_status = request_data.darkmode
    logger.info(f"Updating dark mode for user {user_id} to {new_darkmode_status}")

    update_data = {"darkmode": new_darkmode_status}

    try:
        # Update Directus and Cache (similar pattern to language update)
        success_directus = await directus_service.update_user(user_id, update_data)
        if not success_directus:
            raise HTTPException(status_code=500, detail="Failed to save dark mode setting")

        cache_update_success = await cache_service.update_user(user_id, update_data)
        if not cache_update_success:
            logger.warning(f"Failed to update cache for user {user_id} after dark mode update, but Directus was updated.")
        else:
            logger.info(f"Successfully updated cache for user {user_id} after dark mode update.")

        return SimpleSuccessResponse(success=True, message="Dark mode setting updated successfully")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating dark mode for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred while updating dark mode setting")


# --- Endpoint for updating user timezone ---
@router.post("/user/timezone", response_model=SimpleSuccessResponse, include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("30/minute")  # Prevent abuse of timezone updates
async def update_user_timezone(
    request: Request,
    request_data: TimezoneUpdateRequest,  # Use Pydantic model for request body validation
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Updates the user's timezone setting.
    
    Timezone should be in IANA format (e.g., 'Europe/Berlin', 'America/New_York').
    This is typically auto-detected from the browser on login, but users can
    manually set a different timezone in their account settings.
    """
    user_id = current_user.id
    new_timezone = request_data.timezone
    logger.info(f"Updating timezone for user {user_id} to {new_timezone}")

    # Validate timezone format (IANA timezone names)
    # Common valid timezones are like 'Europe/Berlin', 'America/New_York', 'UTC'
    if not new_timezone or len(new_timezone) > 64:
        raise HTTPException(status_code=400, detail="Invalid timezone provided")
    
    # Basic validation - timezone should contain letters and possibly / or _
    # More thorough validation would check against pytz.all_timezones
    if not all(c.isalnum() or c in '/_+-' for c in new_timezone):
        raise HTTPException(status_code=400, detail="Invalid timezone format")

    update_data = {"timezone": new_timezone}

    try:
        # Update Directus
        success_directus = await directus_service.update_user(user_id, update_data)
        if not success_directus:
            logger.error(f"Failed to update Directus for timezone setting for user {user_id}")
            raise HTTPException(status_code=500, detail="Failed to save timezone setting")

        # Update Cache
        cache_update_success = await cache_service.update_user(user_id, update_data)
        if not cache_update_success:
            logger.warning(f"Failed to update cache for user {user_id} after timezone update, but Directus was updated.")
        else:
            logger.info(f"Successfully updated cache for user {user_id} after timezone update.")

        return SimpleSuccessResponse(success=True, message="Timezone setting updated successfully")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating timezone for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred while updating timezone setting")


# --- Endpoint for disabling 2FA ---
@router.post("/user/disable-2fa", response_model=SimpleSuccessResponse, include_in_schema=False)
@limiter.limit("5/minute")  # Sensitive security operation - strict rate limit
async def disable_2fa(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Disable Two-Factor Authentication for the user.
    This endpoint requires prior authentication (passkey or current password).
    Clears the encrypted 2FA secret and backup codes.
    """
    user_id = current_user.id
    client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
    
    logger.info(f"[2FA] User {user_id} requesting to disable 2FA")

    try:
        # Clear 2FA-related fields
        update_data = {
            "encrypted_tfa_secret": None,
            "encrypted_tfa_app_name": None,
            "tfa_backup_codes_hashes": None,
            "tfa_last_used": None
        }

        # Update Directus
        success_directus = await directus_service.update_user(user_id, update_data)
        if not success_directus:
            logger.error(f"[2FA] Failed to update Directus to disable 2FA for user {user_id}")
            raise HTTPException(status_code=500, detail="Failed to disable 2FA")

        # Update Cache - only update the fields that exist in cache
        cache_update_data = {
            "tfa_enabled": False,
            "tfa_app_name": None
        }
        cache_update_success = await cache_service.update_user(user_id, cache_update_data)
        if not cache_update_success:
            logger.warning(f"[2FA] Failed to update cache for user {user_id} after disabling 2FA")
        else:
            logger.info(f"[2FA] Successfully updated cache for user {user_id} after disabling 2FA")

        # Log compliance event
        compliance_service.log_auth_event(
            event_type="2fa_disabled",
            user_id=user_id,
            ip_address=client_ip,
            status="success"
        )

        logger.info(f"[2FA] Successfully disabled 2FA for user {user_id}")
        return SimpleSuccessResponse(success=True, message="Two-Factor Authentication disabled successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[2FA] Error disabling 2FA for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while disabling 2FA")


# --- Endpoint for Mates Settings Consent ---
@router.post("/user/consent/mates", response_model=SimpleSuccessResponse, include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("30/minute")  # Prevent abuse of consent updates
async def record_mates_consent(
    request: Request, # Add request parameter for compliance logging
    current_user: User = Depends(get_current_user), # Use get_current_user dependency
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service) # Inject compliance service
):
    """Records the timestamp for mates settings consent."""
    logger.info(f"Recording mates consent for user {current_user.id}")
    current_timestamp_str = str(int(time.time()))
    user_id = current_user.id
    client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None) # Get client IP

    # Data to update
    update_data = {
        "consent_mates_default_settings": current_timestamp_str,
        "last_opened": "/signup/credits"
    }
    
    try:
        # Update Directus
        success_directus = await directus_service.update_user(user_id, update_data)
        if not success_directus:
            logger.error(f"Failed to update Directus for mates consent for user {user_id}")
            # NO compliance log for failure
            raise HTTPException(status_code=500, detail="Failed to save consent")
            
        # Update Cache using user_id with string timestamp value for consent
        cache_update_data = {
            "consent_mates_default_settings": current_timestamp_str, # Store string timestamp
            "last_opened": update_data["last_opened"] # Keep last_opened update
        }
        cache_update_success = await cache_service.update_user(user_id, cache_update_data)
        if not cache_update_success:
             # Log warning, but don't fail the request as Directus was updated
            logger.warning(f"Failed to update cache for user {user_id} after mates consent, but Directus was updated.")
        else:
            logger.info(f"Successfully updated cache for user {user_id} after mates consent.")

        # Log compliance event success with correct event type
        compliance_service.log_auth_event(
            event_type="consent_mates_default_settings", # Use field name as event type
            user_id=user_id, 
            ip_address=client_ip, 
            status="success", 
            details={"timestamp": current_timestamp_str}
        )

        return SimpleSuccessResponse(success=True, message="Mates consent recorded")

    except HTTPException as e:
        # NO compliance log for failure
        raise e
    except Exception as e:
        logger.error(f"Error recording mates consent for user {user_id}: {str(e)}")
        # NO compliance log for failure
        raise HTTPException(status_code=500, detail="An error occurred while saving consent")

# --- Endpoint for Low Balance Auto Top-Up Settings ---
@router.post(
    "/auto-topup/low-balance",
    response_model=SimpleSuccessResponse,
    dependencies=[Security(optional_api_key_scheme)]  # Add security requirement for Swagger UI, but don't fail if missing (handled by get_current_user_or_api_key)
)
@limiter.limit("30/minute")  # Prevent abuse of auto-topup settings
async def update_low_balance_auto_topup(
    request: Request,
    request_data: AutoTopUpLowBalanceRequest,
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Updates the user's low balance auto top-up settings.
    No 2FA verification required - users can modify their own settings.
    
    Note: Threshold is fixed at 100 credits and cannot be changed (to simplify setup).
    Any threshold value sent in the request will be ignored and set to 100.
    """
    user_id = current_user.id
    logger.info(f"Updating low balance auto top-up settings for user {user_id}")

    # Validate input
    if request_data.amount < 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    if request_data.currency.lower() not in ['eur', 'usd', 'jpy']:
        raise HTTPException(status_code=400, detail="Invalid currency. Must be EUR, USD, or JPY")

    if request_data.enabled and not request_data.email:
        raise HTTPException(status_code=400, detail="Email is required to enable low balance auto top-up")

    try:
        # Fixed threshold: always 100 credits (cannot be changed to simplify setup)
        FIXED_THRESHOLD = 100
        
        # Update settings with cache-first pattern
        # Threshold is always set to 100, regardless of what's sent in the request
        update_data = {
            "auto_topup_low_balance_enabled": request_data.enabled,
            "auto_topup_low_balance_threshold": FIXED_THRESHOLD,
            "auto_topup_low_balance_amount": request_data.amount,
            "auto_topup_low_balance_currency": request_data.currency.lower()
        }

        # Update cache first (cache-first pattern)
        cache_update_success = await cache_service.update_user(user_id, update_data)
        if not cache_update_success:
            logger.warning(f"Failed to update cache for user {user_id} for auto top-up settings")
        else:
            logger.info(f"Successfully updated cache for user {user_id} for auto top-up settings")

        # Update Directus
        success_directus = await directus_service.update_user(user_id, update_data)
        if not success_directus:
            logger.error(f"Failed to update Directus for auto top-up settings for user {user_id}")
            raise HTTPException(status_code=500, detail="Failed to save auto top-up settings")

        # Handle email encryption for auto top-up notifications
        if request_data.enabled and request_data.email:
            # User is enabling auto top-up and provided email for notifications
            try:
                # Get user's vault key for server-side encryption
                vault_key_id = current_user.vault_key_id

                if not vault_key_id:
                    logger.warning(f"No vault key ID found for user {user_id}. Cannot encrypt email for auto top-up.")
                else:
                    # Encrypt email using server-side vault encryption
                    encrypted_email_tuple = await encryption_service.encrypt_with_user_key(
                        plaintext=request_data.email,
                        key_id=vault_key_id
                    )

                    if encrypted_email_tuple and encrypted_email_tuple[0]:
                        encrypted_email = encrypted_email_tuple[0]

                        # Store encrypted email for auto top-up
                        email_update_data = {
                            "encrypted_email_auto_topup": encrypted_email
                        }

                        # Update cache first
                        cache_email_success = await cache_service.update_user(user_id, email_update_data)
                        if cache_email_success:
                            logger.info(f"Successfully cached encrypted email for auto top-up for user {user_id}")
                        else:
                            logger.warning(f"Failed to cache encrypted email for auto top-up for user {user_id}")

                        # Update Directus
                        directus_email_success = await directus_service.update_user(user_id, email_update_data)
                        if directus_email_success:
                            logger.info(f"Successfully stored encrypted email for auto top-up for user {user_id}")
                        else:
                            logger.warning(f"Failed to store encrypted email for auto top-up for user {user_id}")
                    else:
                        logger.error(f"Failed to encrypt email for auto top-up for user {user_id}")
            except Exception as email_error:
                logger.error(f"Error encrypting email for auto top-up for user {user_id}: {email_error}", exc_info=True)
                # Don't fail the request, just log the error
        elif not request_data.enabled:
            # User is disabling auto top-up, optionally clear the encrypted email
            try:
                email_clear_data = {
                    "encrypted_email_auto_topup": None
                }

                await cache_service.update_user(user_id, email_clear_data)
                await directus_service.update_user(user_id, email_clear_data)
                logger.info(f"Cleared encrypted email for auto top-up for user {user_id}")
            except Exception as clear_error:
                logger.warning(f"Error clearing encrypted email for auto top-up for user {user_id}: {clear_error}")

        logger.info(f"Successfully updated low balance auto top-up settings for user {user_id}")
        return SimpleSuccessResponse(
            success=True,
            message="Low balance auto top-up settings updated successfully"
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating low balance auto top-up settings for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred while updating settings")


# --- API Key Management Models ---
class ApiKeyCreateRequest(BaseModel):
    encrypted_name: str  # Client-side encrypted name (encrypted with user's vault key)
    api_key_hash: str  # SHA-256 hash of the full API key (64 hex chars)
    encrypted_key_prefix: str  # Client-side encrypted key prefix (encrypted with user's vault key)
    encrypted_master_key: str  # Master key encrypted with key derived from API key (for CLI/npm/pip access)
    salt: str  # Salt used for deriving key from API key
    key_iv: Optional[str] = None  # IV for AES-GCM encryption of master key
    expires_at: Optional[str] = None  # Optional expiration timestamp (ISO format)

class ApiKeyResponse(BaseModel):
    """Response model for API key information (encrypted fields excluded for REST API)"""
    id: str
    created_at: str
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    # Note: encrypted_name and encrypted_key_prefix are excluded from REST API responses
    # These fields are only available via CLI tools that have decryption keys

class ApiKeyListResponse(BaseModel):
    api_keys: list[ApiKeyResponse]


# --- API Key Management Endpoints ---

@router.get(
    "/api-keys",
    response_model=ApiKeyListResponse,
    dependencies=[Security(optional_api_key_scheme)]  # Add security requirement for Swagger UI, but don't fail if missing (handled by get_current_user_or_api_key)
)
@limiter.limit("30/minute")
async def get_api_keys(
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """Get all API keys for the current user."""
    try:
        logger.info(f"Fetching API keys for user {current_user.id}")
        
        # Query API keys from the api_keys collection (not from user model)
        api_keys_data = await directus_service.get_user_api_keys_by_user_id(current_user.id)
        
        logger.debug(f"Retrieved {len(api_keys_data) if api_keys_data else 0} API keys from Directus for user {current_user.id}")
        
        # Convert to response format (client will decrypt encrypted fields)
        api_keys = []
        if api_keys_data:
            for key in api_keys_data:
                try:
                    # Format timestamps - Directus may return datetime objects or ISO strings
                    created_at = key.get('created_at', '')
                    if created_at and not isinstance(created_at, str):
                        # Convert datetime object to ISO string
                        if hasattr(created_at, 'isoformat'):
                            created_at = created_at.isoformat()
                        else:
                            created_at = str(created_at)
                    
                    expires_at = key.get('expires_at')
                    if expires_at and not isinstance(expires_at, str):
                        # Convert datetime object to ISO string
                        if hasattr(expires_at, 'isoformat'):
                            expires_at = expires_at.isoformat()
                        else:
                            expires_at = str(expires_at)
                    
                    last_used_at = key.get('last_used_at')
                    if last_used_at and not isinstance(last_used_at, str):
                        # Convert datetime object to ISO string
                        if hasattr(last_used_at, 'isoformat'):
                            last_used_at = last_used_at.isoformat()
                        else:
                            last_used_at = str(last_used_at)
                    
                    # Exclude encrypted fields from REST API response (only available via CLI)
                    api_key_response = ApiKeyResponse(
                        id=key.get('id'),
                        created_at=created_at,
                        expires_at=expires_at,
                        last_used_at=last_used_at
                    )
                    api_keys.append(api_key_response)
                except Exception as key_error:
                    logger.warning(f"Error processing API key {key.get('id', 'unknown')}: {key_error}", exc_info=True)
                    continue
        
        logger.info(f"Returning {len(api_keys)} API keys for user {current_user.id}")
        return ApiKeyListResponse(api_keys=api_keys)

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error retrieving API keys for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve API keys")


@router.post("/api-keys", response_model=ApiKeyResponse, include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("10/minute")
async def create_api_key(
    request: Request,
    request_data: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """Create a new API key for the current user."""
    try:
        # Validate input
        if not request_data.encrypted_name or len(request_data.encrypted_name.strip()) == 0:
            raise HTTPException(status_code=400, detail="API key name is required")

        if not request_data.api_key_hash or len(request_data.api_key_hash) != 64:  # SHA256 hex
            raise HTTPException(status_code=400, detail="Invalid API key hash (must be 64 hex characters)")

        if not request_data.encrypted_key_prefix or len(request_data.encrypted_key_prefix.strip()) == 0:
            raise HTTPException(status_code=400, detail="API key prefix is required")

        if not request_data.encrypted_master_key or len(request_data.encrypted_master_key.strip()) == 0:
            raise HTTPException(status_code=400, detail="Encrypted master key is required")

        if not request_data.salt or len(request_data.salt.strip()) == 0:
            raise HTTPException(status_code=400, detail="Salt is required")

        # Check existing API keys count (max 5 per user)
        existing_keys = await directus_service.get_user_api_keys_by_user_id(current_user.id)
        if len(existing_keys) >= 5:
            raise HTTPException(status_code=400, detail="Maximum number of API keys reached (5)")

        # Check for duplicate key hash (shouldn't happen, but safety check)
        existing_key = await directus_service.get_api_key_by_hash(request_data.api_key_hash)
        if existing_key:
            raise HTTPException(status_code=400, detail="API key hash already exists")

        # Create hashed_user_id for efficient lookups
        hashed_user_id = hashlib.sha256(current_user.id.encode()).hexdigest()

        # Create API key record in api_keys collection
        created_key = await directus_service.create_api_key(
            user_id=current_user.id,
            hashed_user_id=hashed_user_id,
            key_hash=request_data.api_key_hash,
            encrypted_key_prefix=request_data.encrypted_key_prefix,
            encrypted_name=request_data.encrypted_name,
            expires_at=request_data.expires_at
        )

        if not created_key:
            raise HTTPException(status_code=500, detail="Failed to create API key record")

        # Create encryption key entry for CLI/npm/pip access (similar to passkeys)
        login_method = f"api_key_{request_data.api_key_hash}"
        encryption_key_success = await directus_service.create_encryption_key(
            hashed_user_id=hashed_user_id,
            login_method=login_method,
            encrypted_key=request_data.encrypted_master_key,
            salt=request_data.salt,
            key_iv=request_data.key_iv
        )

        if not encryption_key_success:
            logger.error(f"Failed to create encryption key for API key {request_data.api_key_hash[:16]}..., but API key was created")
            # Don't fail the request, but log the error - the API key can still be used for REST API

        logger.info(f"Successfully created API key for user {current_user.id} with encryption key")

        # Format created_at timestamp
        created_at = created_key.get('created_at', datetime.now(timezone.utc).isoformat())
        if created_at and not isinstance(created_at, str):
            if hasattr(created_at, 'isoformat'):
                created_at = created_at.isoformat()
            else:
                created_at = str(created_at)
        
        # Format expires_at timestamp
        expires_at = created_key.get('expires_at')
        if expires_at and not isinstance(expires_at, str):
            if hasattr(expires_at, 'isoformat'):
                expires_at = expires_at.isoformat()
            else:
                expires_at = str(expires_at)
        
        # Format last_used_at timestamp
        last_used_at = created_key.get('last_used_at')
        if last_used_at and not isinstance(last_used_at, str):
            if hasattr(last_used_at, 'isoformat'):
                last_used_at = last_used_at.isoformat()
            else:
                last_used_at = str(last_used_at)
        
        # Exclude encrypted fields from REST API response (only available via CLI)
        return ApiKeyResponse(
            id=created_key.get('id', ''),
            created_at=created_at,
            expires_at=expires_at,
            last_used_at=last_used_at
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error creating API key for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create API key")


@router.delete("/api-keys/{key_id}", response_model=SimpleSuccessResponse, include_in_schema=False)  # Exclude from schema - not in whitelist, web app only
@limiter.limit("20/minute")
async def delete_api_key(
    request: Request,
    key_id: str,
    current_user: User = Depends(get_current_user),  # Web app only - no API key access
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """Delete an API key for the current user."""
    try:
        # Get all API keys for the user to verify ownership
        user_api_keys = await directus_service.get_user_api_keys_by_user_id(current_user.id)
        
        # Find the key to delete and verify it belongs to the user
        key_to_delete = next((key for key in user_api_keys if key.get('id') == key_id), None)
        if not key_to_delete:
            raise HTTPException(status_code=404, detail="API key not found")

        # Get the key_hash to delete the associated encryption key
        key_hash = key_to_delete.get('key_hash')
        hashed_user_id = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        # Delete the API key record
        delete_success = await directus_service.delete_api_key(key_id)
        if not delete_success:
            raise HTTPException(status_code=500, detail="Failed to delete API key")

        # Also delete the associated encryption key (for CLI/npm/pip access)
        if key_hash:
            login_method = f"api_key_{key_hash}"
            encryption_delete_success = await directus_service.delete_encryption_key(hashed_user_id, login_method)
            if not encryption_delete_success:
                logger.warning(f"Failed to delete encryption key for API key {key_id}, but API key was deleted")
            else:
                logger.info(f"Successfully deleted both API key {key_id} and its encryption key")

        return SimpleSuccessResponse(success=True, message="API key deleted successfully")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error deleting API key {key_id} for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete API key")


# --- API Key Device Management Endpoints ---

class DeviceResponse(BaseModel):
    """Response model for API key device information (encrypted fields excluded for REST API)"""
    id: str
    api_key_id: str
    anonymized_ip: str
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    approved_at: Optional[str] = None  # NULL means pending approval
    first_access_at: Optional[str] = None
    last_access_at: Optional[str] = None
    access_type: str
    machine_identifier: Optional[str] = None
    # Note: encrypted_device_name is excluded from REST API responses
    # This field is only available via CLI tools that have decryption keys

class DeviceListResponse(BaseModel):
    """Response model for list of API key devices"""
    devices: list[DeviceResponse]


@router.get(
    "/api-key-devices",
    response_model=DeviceListResponse,
    dependencies=[Security(optional_api_key_scheme)]  # Add security requirement for Swagger UI, but don't fail if missing (handled by get_current_user_or_api_key)
)
@limiter.limit("30/minute")
async def get_api_key_devices(
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service)
):
    """
    Get all devices for all API keys belonging to the current user.
    This includes both approved and pending devices.
    """
    try:
        # Get all API keys for the user
        api_keys_data = await directus_service.get_user_api_keys_by_user_id(current_user.id)
        
        # Get all devices for all API keys (with decryption)
        all_devices = []
        for api_key in api_keys_data:
            api_key_id = api_key.get('id')
            if api_key_id:
                # Pass user_id for decryption
                devices = await directus_service.get_api_key_devices(api_key_id, user_id=current_user.id)
                all_devices.extend(devices)
        
        # Convert to response format (exclude encrypted fields from REST API)
        device_responses = [
            DeviceResponse(
                id=device.get('id'),
                api_key_id=device.get('api_key_id'),
                anonymized_ip=device.get('anonymized_ip', 'Unknown'),
                country_code=device.get('country_code'),
                region=device.get('region'),
                city=device.get('city'),
                approved_at=device.get('approved_at'),  # NULL means pending approval
                first_access_at=device.get('first_access_at'),
                last_access_at=device.get('last_access_at'),
                access_type=device.get('access_type', 'rest_api'),
                machine_identifier=device.get('machine_identifier')
                # Note: encrypted_device_name excluded from REST API (only available via CLI)
            )
            for device in all_devices
        ]
        
        # Sort by approved_at (pending devices first - NULL comes before timestamps), then by access time
        device_responses.sort(key=lambda d: (
            d.approved_at is None,  # Pending (None) comes before approved (timestamp)
            d.approved_at or '',  # Then by approval time (if approved)
            d.last_access_at or d.first_access_at or '',  # Then by access time
        ), reverse=True)
        
        return DeviceListResponse(devices=device_responses)

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error retrieving API key devices for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve API key devices")


@router.post("/api-key-devices/{device_id}/approve", response_model=SimpleSuccessResponse, include_in_schema=False)  # Exclude from schema - not in whitelist, web app only
@limiter.limit("30/minute")
async def approve_api_key_device(
    request: Request,
    device_id: str,
    current_user: User = Depends(get_current_user),  # Web app only - no API key access
    directus_service: DirectusService = Depends(get_directus_service)
):
    """
    Approve an API key device, allowing it to use the API key.
    Only the owner of the API key can approve devices.
    """
    try:
        # Verify the device belongs to one of the user's API keys
        # First, get all user's API keys
        api_keys_data = await directus_service.get_user_api_keys_by_user_id(current_user.id)
        api_key_ids = [key.get('id') for key in api_keys_data if key.get('id')]
        
        # Get the device to verify ownership
        # We need to check if the device belongs to one of the user's API keys
        # Since we don't have a direct lookup by device_id, we'll get all devices and filter
        user_device = None
        for api_key_id in api_key_ids:
            devices = await directus_service.get_api_key_devices(api_key_id)
            for device in devices:
                if device.get('id') == device_id:
                    user_device = device
                    break
            if user_device:
                break
        
        if not user_device:
            raise HTTPException(status_code=404, detail="Device not found or you don't have permission to approve it")
        
        # Approve the device
        success, message = await directus_service.approve_api_key_device(device_id)
        
        if not success:
            raise HTTPException(status_code=500, detail=message)
        
        # Invalidate device approval cache
        api_key_id = user_device.get('api_key_id')
        device_hash = user_device.get('device_hash')
        if api_key_id and device_hash and hasattr(directus_service, 'cache') and directus_service.cache:
            device_approval_cache_key = f"api_key_device_approval:{api_key_id}:{device_hash}"
            try:
                await directus_service.cache.delete(device_approval_cache_key)
            except Exception as cache_error:
                logger.warning(f"Failed to invalidate device approval cache: {cache_error}")
        
        return SimpleSuccessResponse(success=True, message="Device approved successfully")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error approving API key device {device_id} for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to approve device")


@router.post("/api-key-devices/{device_id}/revoke", response_model=SimpleSuccessResponse, include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("30/minute")
async def revoke_api_key_device(
    request: Request,
    device_id: str,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
):
    """
    Revoke access for an API key device by deleting the device record.
    Only the owner of the API key can revoke devices.
    """
    try:
        # Verify the device belongs to one of the user's API keys
        api_keys_data = await directus_service.get_user_api_keys_by_user_id(current_user.id)
        api_key_ids = [key.get('id') for key in api_keys_data if key.get('id')]
        
        # Get the device to verify ownership and get device_hash for cache invalidation
        user_device = None
        for api_key_id in api_key_ids:
            devices = await directus_service.get_api_key_devices(api_key_id)
            for device in devices:
                if device.get('id') == device_id:
                    user_device = device
                    break
            if user_device:
                break
        
        if not user_device:
            raise HTTPException(status_code=404, detail="Device not found or you don't have permission to revoke it")
        
        # Get device_hash for cache invalidation before deletion
        api_key_id = user_device.get('api_key_id')
        device_hash = user_device.get('device_hash')
        
        # Revoke the device
        success, message = await directus_service.revoke_api_key_device(device_id)
        
        if not success:
            raise HTTPException(status_code=500, detail=message)
        
        # Invalidate device approval cache (already done in revoke_api_key_device, but ensure it's done)
        if api_key_id and device_hash and hasattr(directus_service, 'cache') and directus_service.cache:
            device_approval_cache_key = f"api_key_device_approval:{api_key_id}:{device_hash}"
            try:
                await directus_service.cache.delete(device_approval_cache_key)
            except Exception as cache_error:
                logger.warning(f"Failed to invalidate device approval cache: {cache_error}")
        
        return SimpleSuccessResponse(success=True, message="Device revoked successfully")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error revoking API key device {device_id} for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to revoke device")


class DeviceRenameRequest(BaseModel):
    """Request to rename an API key device"""
    encrypted_device_name: str = Field(..., description="New encrypted device name (encrypted client-side with master key)")


@router.patch(
    "/api-key-devices/{device_id}/rename",
    response_model=SimpleSuccessResponse,
    include_in_schema=False  # Exclude from schema - web app only, not in whitelist
)
@limiter.limit("30/minute")
async def rename_api_key_device(
    request: Request,
    device_id: str,
    rename_request: DeviceRenameRequest,
    current_user: User = Depends(get_current_user),  # Web app only - no API key access
    directus_service: DirectusService = Depends(get_directus_service)
):
    """
    Rename an API key device with a custom name.
    The device name is encrypted client-side with the user's master key (zero-knowledge).
    Only the owner of the API key can rename devices.
    """
    try:
        # Verify the device belongs to one of the user's API keys
        api_keys_data = await directus_service.get_user_api_keys_by_user_id(current_user.id)
        api_key_ids = [key.get('id') for key in api_keys_data if key.get('id')]
        
        # Get the device to verify ownership
        user_device = None
        for api_key_id in api_key_ids:
            devices = await directus_service.get_api_key_devices(api_key_id)
            for device in devices:
                if device.get('id') == device_id:
                    user_device = device
                    break
            if user_device:
                break
        
        if not user_device:
            raise HTTPException(status_code=404, detail="Device not found or you don't have permission to rename it")
        
        # Device name is already encrypted client-side with master key
        # Just store it as-is (zero-knowledge: server never sees plaintext)
        encrypted_device_name = rename_request.encrypted_device_name
        
        # Update the device name
        success = await directus_service.update_api_key_device_name(
            device_id,
            encrypted_device_name
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to rename device")
        
        logger.info(f"Successfully renamed API key device {device_id[:6]}... for user {current_user.id[:8]}...")
        return SimpleSuccessResponse(success=True, message="Device renamed successfully")
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error renaming API key device {device_id} for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to rename device")


# --- Endpoint for fetching usage data ---
@router.get(
    "/usage",
    dependencies=[Security(optional_api_key_scheme)]  # Add security requirement for Swagger UI, but don't fail if missing (handled by get_current_user_or_api_key)
)
@limiter.limit("30/minute")  # Rate limit usage data fetching
async def get_usage(
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Fetch usage data for the current user.
    Returns decrypted usage entries grouped and formatted for display.
    """
    try:
        logger.info(f"Fetching usage data for user {current_user.id}")
        
        # Get user's vault_key_id for decryption
        user_vault_key_id = await cache_service.get_user_vault_key_id(current_user.id)
        
        if not user_vault_key_id:
            logger.debug(f"vault_key_id not in cache for user {current_user.id}, fetching from Directus")
            user_profile_result = await directus_service.get_user_profile(current_user.id)
            if not user_profile_result or not user_profile_result[0]:
                logger.error(f"Failed to fetch user profile for usage decryption: {current_user.id}")
                raise HTTPException(status_code=404, detail="User profile not found")
            
            user_profile = user_profile_result[1]
            user_vault_key_id = user_profile.get("vault_key_id")
            if not user_vault_key_id:
                logger.error(f"User {current_user.id} missing vault_key_id in Directus profile")
                raise HTTPException(status_code=500, detail="User encryption key not found")
            
            # Cache the vault_key_id for future use
            await cache_service.update_user(current_user.id, {"vault_key_id": user_vault_key_id})
            logger.debug(f"Cached vault_key_id for user {current_user.id}")
        
        # Hash user ID for querying usage collection
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        # Get pagination parameters from query string (default to last 10 entries)
        limit = int(request.query_params.get("limit", 10))
        offset = int(request.query_params.get("offset", 0))
        
        # Fetch usage entries with pagination
        usage_entries = await directus_service.usage.get_user_usage_entries(
            user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id,
            limit=limit,
            offset=offset,
            sort="-created_at"
        )
        
        logger.info(f"Successfully fetched {len(usage_entries)} usage entries for user {current_user.id} (limit={limit}, offset={offset})")
        
        return {
            "usage": usage_entries,
            "limit": limit,
            "offset": offset,
            "count": len(usage_entries)
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching usage data for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch usage data")


# --- Endpoint for fetching usage summaries (fast) ---
# Note: This endpoint is also re-exported in usage_api.py for OpenAPI documentation
@router.get("/usage/summaries", include_in_schema=False)  # Exclude from schema - not in whitelist (available via usage_api)
@limiter.limit("30/minute")
async def get_usage_summaries(
    request: Request,
    type: str,  # "chats", "apps", or "api_keys"
    months: int = 3,
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Fetch usage summaries for the last N months.
    Fast endpoint - only queries summary tables.
    """
    try:
        # Validate type parameter
        if type not in ["chats", "apps", "api_keys"]:
            raise HTTPException(status_code=400, detail="Invalid type. Must be 'chats', 'apps', or 'api_keys'")
        
        # Map plural to singular for collection name
        summary_type_map = {
            "chats": "chat",
            "apps": "app",
            "api_keys": "api_key"
        }
        summary_type = summary_type_map[type]
        
        logger.info(f"Fetching {type} usage summaries for user {current_user.id}, last {months} months")
        
        # Hash user ID
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        # Fetch summaries
        summaries = await directus_service.usage.get_monthly_summaries(
            user_id_hash=user_id_hash,
            summary_type=summary_type,
            months=months
        )
        
        # For API key summaries, enrich with encrypted API key data (name and prefix)
        # Client will decrypt these fields using the master key
        if type == "api_keys" and summaries:
            # Collect all unique API key hashes from summaries
            api_key_hashes = list(set(
                summary.get("api_key_hash")
                for summary in summaries
                if summary.get("api_key_hash")
            ))
            
            if api_key_hashes:
                # Fetch API key records by hashes (only for current user's keys)
                # We need to filter by user_id to ensure security
                api_keys_params = {
                    "filter": {
                        "user_id": {"_eq": current_user.id},
                        "key_hash": {"_in": api_key_hashes}
                    },
                    "fields": "key_hash",  # Only fetch key_hash - encrypted fields excluded from REST API
                    "limit": -1
                }
                
                try:
                    api_keys_data = await directus_service.get_items("api_keys", params=api_keys_params, no_cache=True)
                    
                    # Create a map of api_key_hash -> API key exists (for validation only)
                    # Encrypted fields are excluded from REST API responses
                    api_keys_set = set(
                        key.get("key_hash")
                        for key in api_keys_data
                        if key.get("key_hash")
                    )
                    
                    # Note: We don't enrich summaries with encrypted_name/encrypted_key_prefix
                    # These fields are only available via CLI tools that have decryption keys
                    # REST API users can identify API keys by their hash if needed
                    
                    logger.debug(f"Found {len(api_keys_set)} API keys for summaries (encrypted fields excluded from REST API)")
                except Exception as e:
                    logger.warning(f"Failed to fetch API key data for summaries: {e}", exc_info=True)
                    # Continue without enrichment - summaries will still work, just without names
        
        logger.info(f"Successfully fetched {len(summaries)} {type} summaries for user {current_user.id}")
        
        return {
            "summaries": summaries,
            "type": type,
            "months": months,
            "count": len(summaries)
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching usage summaries for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch usage summaries")


# --- Endpoint for fetching usage details (lazy loading) ---
# Note: This endpoint is also re-exported in usage_api.py for OpenAPI documentation
@router.get("/usage/details", include_in_schema=False)  # Exclude from schema - not in whitelist (available via usage_api)
@limiter.limit("30/minute")
async def get_usage_details(
    request: Request,
    type: str,  # "chat", "app", or "api_key"
    identifier: str,  # chat_id, app_id, or api_key_hash
    year_month: str,  # "YYYY-MM"
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Fetch detailed usage entries for a specific chat/app/api_key in a month.
    Checks if archived, loads from S3 if needed, caches result.
    """
    try:
        # Validate type parameter
        if type not in ["chat", "app", "api_key"]:
            raise HTTPException(status_code=400, detail="Invalid type. Must be 'chat', 'app', or 'api_key'")
        
        # Validate year_month format
        try:
            year, month = map(int, year_month.split("-"))
            datetime(year, month, 1)  # Validate it's a valid date
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid year_month format. Must be 'YYYY-MM'")
        
        logger.info(f"Fetching {type} usage details for user {current_user.id}, identifier '{identifier}', month '{year_month}'")
        
        # Get user's vault_key_id
        user_vault_key_id = await cache_service.get_user_vault_key_id(current_user.id)
        if not user_vault_key_id:
            user_profile_result = await directus_service.get_user_profile(current_user.id)
            if not user_profile_result or not user_profile_result[0]:
                raise HTTPException(status_code=404, detail="User profile not found")
            user_profile = user_profile_result[1]
            user_vault_key_id = user_profile.get("vault_key_id")
            if not user_vault_key_id:
                raise HTTPException(status_code=500, detail="User encryption key not found")
            await cache_service.update_user(current_user.id, {"vault_key_id": user_vault_key_id})
        
        # Hash user ID
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        # Check cache first (for archived data)
        cache_key = f"usage_archive:{user_id_hash}:{year_month}"
        cached_entries = await cache_service.get(cache_key)
        
        if cached_entries:
            logger.info(f"Cache HIT for usage archive: {cache_key}")
            # Filter cached entries by identifier
            filtered_entries = []
            identifier_key = {
                "chat": "chat_id",
                "app": "app_id",
                "api_key": "api_key_hash"
            }[type]
            
            for entry in cached_entries:
                if entry.get(identifier_key) == identifier:
                    filtered_entries.append(entry)
            
            return {
                "entries": filtered_entries,
                "type": type,
                "identifier": identifier,
                "year_month": year_month,
                "count": len(filtered_entries),
                "from_cache": True
            }
        
        # Fetch from Directus or S3
        entries = await directus_service.usage.get_usage_entries_for_summary(
            user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id,
            summary_type=type,
            identifier=identifier,
            year_month=year_month
        )
        
        # If entries is empty, might be archived - check summary and load from S3
        if not entries:
            # Check if summary exists and is archived
            from backend.core.api.app.services.usage_archive_service import UsageArchiveService
            # Get S3 service from app state
            s3_service = request.app.state.s3_service
            if not s3_service:
                logger.error("S3 service not available")
                raise HTTPException(status_code=503, detail="Archive service unavailable")
            
            archive_service = UsageArchiveService(
                s3_service=s3_service,
                encryption_service=encryption_service,
                directus_service=directus_service
            )
            
            # Try to load from archive
            identifier_key = {
                "chat": "chat_id",
                "app": "app_id",
                "api_key": "api_key_hash"
            }[type]
            
            filters = {identifier_key: identifier}
            archived_entries = await archive_service.retrieve_archived_usage(
                user_id_hash=user_id_hash,
                year_month=year_month,
                user_vault_key_id=user_vault_key_id,
                filters=filters
            )
            
            if archived_entries:
                # Cache the full archive (all entries for the month) for future requests
                # First, get all entries for the month (without filters)
                all_archived_entries = await archive_service.retrieve_archived_usage(
                    user_id_hash=user_id_hash,
                    year_month=year_month,
                    user_vault_key_id=user_vault_key_id,
                    filters=None
                )
                
                # Cache for 1 hour (3600 seconds)
                await cache_service.set(cache_key, all_archived_entries, ttl=3600)
                logger.info(f"Cached usage archive: {cache_key}")
                
                entries = archived_entries
        
        logger.info(f"Successfully fetched {len(entries)} usage entries for {type} '{identifier}', month '{year_month}'")
        
        return {
            "entries": entries,
            "type": type,
            "identifier": identifier,
            "year_month": year_month,
            "count": len(entries),
            "from_cache": False
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching usage details for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch usage details")


# --- Endpoint for getting total credits for a specific chat ---
@router.get("/usage/chat-total", include_in_schema=False)
@limiter.limit("60/minute")
async def get_chat_total_credits(
    request: Request,
    chat_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """
    Get the total credits used for a specific chat across all months.
    Fast endpoint - uses cleartext total_credits from summary tables (no decryption needed).
    """
    try:
        if not chat_id or not chat_id.strip():
            raise HTTPException(status_code=400, detail="chat_id is required")
        
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        total_credits = await directus_service.usage.get_chat_total_credits(
            user_id_hash=user_id_hash,
            chat_id=chat_id
        )
        
        return {
            "chat_id": chat_id,
            "total_credits": total_credits
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching chat total credits for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch chat total credits")


# --- Endpoint for getting credits for a specific message ---
@router.get("/usage/message-cost", include_in_schema=False)
@limiter.limit("60/minute")
async def get_message_cost(
    request: Request,
    message_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Get the credits charged for a specific message.
    Queries the usage collection by message_id and decrypts the credits field.
    """
    try:
        if not message_id or not message_id.strip():
            raise HTTPException(status_code=400, detail="message_id is required")
        
        # Get user's vault_key_id for decryption
        user_vault_key_id = await cache_service.get_user_vault_key_id(current_user.id)
        if not user_vault_key_id:
            user_profile_result = await directus_service.get_user_profile(current_user.id)
            if not user_profile_result or not user_profile_result[0]:
                raise HTTPException(status_code=404, detail="User profile not found")
            user_profile = user_profile_result[1]
            user_vault_key_id = user_profile.get("vault_key_id")
            if not user_vault_key_id:
                raise HTTPException(status_code=500, detail="User encryption key not found")
            await cache_service.update_user(current_user.id, {"vault_key_id": user_vault_key_id})
        
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        credits = await directus_service.usage.get_message_credits(
            user_id_hash=user_id_hash,
            message_id=message_id,
            user_vault_key_id=user_vault_key_id
        )
        
        return {
            "message_id": message_id,
            "credits": credits
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching message cost for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch message cost")


# --- Endpoint for fetching daily usage overview (all types combined) ---
# Note: This endpoint is also re-exported in usage_api.py for OpenAPI documentation
@router.get("/usage/daily-overview", include_in_schema=False)  # Exclude from schema - not in whitelist (available via usage_api)
@limiter.limit("30/minute")
async def get_daily_overview(
    request: Request,
    days: int = 7,
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Fetch daily usage overview combining all usage types (chats, apps, API keys).
    Returns data grouped by day, with today first and previous days following.
    Used by the Overview tab in usage settings for a day-by-day credit spending view.
    """
    try:
        # Validate days parameter (reasonable limits)
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail="Days must be between 1 and 90")
        
        logger.info(f"Fetching daily overview for user {current_user.id}, last {days} days")
        
        # Hash user ID
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        # Fetch daily overview from the usage service
        daily_data = await directus_service.usage.get_daily_overview(
            user_id_hash=user_id_hash,
            days=days
        )
        
        # Calculate total days available by checking if the oldest requested day has data
        # If the last day has data, there might be more days available
        has_more_days = False
        if daily_data and len(daily_data) >= days:
            # Check if the oldest day has any items - if so, there might be more
            oldest_day = daily_data[-1] if daily_data else None
            if oldest_day and oldest_day.get("items"):
                has_more_days = True
        
        logger.info(f"Successfully fetched {len(daily_data)} days of daily overview for user {current_user.id}")
        
        return {
            "days": daily_data,
            "requested_days": days,
            "total_days": len(daily_data),
            "has_more_days": has_more_days
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching daily overview for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch daily overview")


# --- Endpoint for fetching all usage entries for a specific chat (no month filter) ---
@router.get("/usage/chat-entries", include_in_schema=False)  # Exclude from schema - not in whitelist (available via usage_api)
@limiter.limit("30/minute")
async def get_chat_entries(
    request: Request,
    chat_id: str,
    limit: int = 100,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Fetch all usage entries for a specific chat across all time (no month filter).
    Used by the overview detail view to show all skill uses for a chat.
    Returns entries sorted by created_at descending.
    """
    try:
        # Validate limit
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 500")
        
        logger.info(f"Fetching all chat entries for user {current_user.id}, chat '{chat_id}'")
        
        # Get user's vault_key_id
        user_vault_key_id = await cache_service.get_user_vault_key_id(current_user.id)
        if not user_vault_key_id:
            user_profile_result = await directus_service.get_user_profile(current_user.id)
            if not user_profile_result or not user_profile_result[0]:
                raise HTTPException(status_code=404, detail="User profile not found")
            user_profile = user_profile_result[1]
            user_vault_key_id = user_profile.get("vault_key_id")
            if not user_vault_key_id:
                raise HTTPException(status_code=500, detail="User encryption key not found")
            await cache_service.update_user(current_user.id, {"vault_key_id": user_vault_key_id})
        
        # Hash user ID
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        # Fetch all entries for this chat
        entries = await directus_service.usage.get_all_chat_entries(
            user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id,
            chat_id=chat_id,
            limit=limit
        )
        
        logger.info(f"Returning {len(entries)} chat entries for user {current_user.id}, chat '{chat_id}'")
        
        return {
            "entries": entries,
            "chat_id": chat_id,
            "count": len(entries)
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching chat entries for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch chat entries")


# --- Endpoint for exporting usage data as CSV ---
@router.get("/usage/export", include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("10/minute")  # Lower limit for export to prevent abuse
async def export_usage_csv(
    request: Request,
    months: int = 3,
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Export ALL usage entries for the last N months as CSV.
    Includes all types: chats, apps, and API keys.
    """
    try:
        # Hash user ID
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        # Get user vault key for decryption
        user_vault_key_id = current_user.vault_key_id
        if not user_vault_key_id:
            raise HTTPException(status_code=500, detail="User vault key not found")
        
        logger.info(f"Exporting ALL usage data for user {current_user.id}, last {months} months")
        
        # Calculate date range
        from datetime import timedelta
        start_date = datetime.now() - timedelta(days=months * 30)
        start_timestamp = int(start_date.timestamp())
        
        # Fetch ALL usage entries for the time period (no type filtering)
        params = {
            "filter": {
                "user_id_hash": {"_eq": user_id_hash},
                "created_at": {"_gte": start_timestamp}
            },
            "fields": "*",
            "sort": ["-created_at"],
            "limit": -1  # Get all entries
        }
        
        entries = await directus_service.get_items("usage", params=params, no_cache=True)
        
        if not entries:
            raise HTTPException(status_code=404, detail="No usage entries found for the specified period")
        
        # Decrypt entries using the usage service (already initialized on directus_service)
        decrypted_entries = await directus_service.usage._decrypt_usage_entries(entries, user_vault_key_id)
        
        # Generate CSV content
        import io
        import csv
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        headers = [
            'Date',
            'Time',
            'Type',
            'Source',
            'App',
            'Skill',
            'Credits',
            'Input Tokens',
            'Output Tokens',
            'Model',
            'Chat ID',
            'Message ID',
            'API Key Hash'
        ]
        writer.writerow(headers)
        
        # Write rows
        for entry in decrypted_entries:
            created_at = entry.get("created_at", 0)
            date_obj = datetime.fromtimestamp(created_at)
            
            row = [
                date_obj.strftime("%Y-%m-%d"),
                date_obj.strftime("%H:%M:%S"),
                entry.get("type", ""),
                entry.get("source", ""),
                entry.get("app_id", ""),
                entry.get("skill_id", ""),
                entry.get("credits", 0),
                entry.get("input_tokens", ""),
                entry.get("output_tokens", ""),
                entry.get("model_used", ""),
                entry.get("chat_id", ""),
                entry.get("message_id", ""),
                entry.get("api_key_hash", "")[:16] + "..." if entry.get("api_key_hash") else ""  # Truncate hash for privacy
            ]
            writer.writerow(row)
        
        # Prepare response
        output.seek(0)
        filename = f"usage-export-{datetime.now().strftime('%Y-%m-%d')}.csv"
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error exporting usage data for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export usage data")


# --- Endpoint for billing overview ---
@router.get(
    "/billing",
    response_model=BillingOverviewResponse,
    dependencies=[Security(optional_api_key_scheme)]  # Add security requirement for Swagger UI, but don't fail if missing (handled by get_current_user_or_api_key)
)
@limiter.limit("30/minute")
async def get_billing_overview(
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),  # Supports both session and API key auth
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Get billing overview for the current user.
    Returns current payment tier, auto top-up settings, and list of invoices.
    Secured by API key validation (supports both session and API key authentication).
    """
    logger.info(f"Fetching billing overview for user {current_user.id}")
    
    try:
        # Get user data from cache (or fetch from Directus if not cached)
        user = await cache_service.get_user_by_id(current_user.id)
        
        if not user:
            logger.info(f"User {current_user.id} not found in cache, fetching from Directus")
            profile_success, user_profile, profile_message = await directus_service.get_user_profile(current_user.id)
            
            if not profile_success or not user_profile:
                logger.error(f"User profile not found in Directus for user {current_user.id}: {profile_message}")
                raise HTTPException(status_code=404, detail=f"User with ID {current_user.id} not found.")
            
            # Ensure user_id is present in the profile for caching
            if "user_id" not in user_profile:
                user_profile["user_id"] = current_user.id
            if "id" not in user_profile:
                user_profile["id"] = current_user.id
            
            # Cache the fetched profile
            await cache_service.set_user(user_profile, user_id=current_user.id)
            user = user_profile
            logger.info(f"Successfully fetched and cached user {current_user.id} from Directus")
        
        # Get payment tier (default to 1 if not set)
        payment_tier = user.get("payment_tier", 1)
        if payment_tier < 0 or payment_tier > 4:
            payment_tier = 1
        
        # Get auto top-up settings with proper defaults for None values
        auto_topup_enabled = user.get("auto_topup_low_balance_enabled")
        if auto_topup_enabled is None:
            auto_topup_enabled = False
        
        auto_topup_threshold = user.get("auto_topup_low_balance_threshold")
        if auto_topup_threshold is None:
            auto_topup_threshold = 100  # Fixed threshold is 100
        
        auto_topup_amount = user.get("auto_topup_low_balance_amount")
        if auto_topup_amount is None:
            auto_topup_amount = 0
        
        auto_topup_currency = user.get("auto_topup_low_balance_currency")
        if auto_topup_currency is None:
            auto_topup_currency = "eur"
        
        # Get vault_key_id for invoice decryption
        vault_key_id = user.get("vault_key_id")
        if not vault_key_id:
            logger.error(f"Vault key ID missing for user {current_user.id}")
            raise HTTPException(status_code=500, detail="User encryption key not found")
        
        # Get invoices from Directus
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        
        invoices_data = await directus_service.get_items(
            collection="invoices",
            params={
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash}
                },
                "sort": "-date"  # Most recent first
            }
        )
        
        processed_invoices = []
        
        if invoices_data:
            # Get base URL for constructing download URLs
            # Use request.url to get the base URL (scheme + host)
            base_url = f"{request.url.scheme}://{request.url.netloc}"
            
            for invoice in invoices_data:
                try:
                    # Check if required encrypted fields exist
                    if "encrypted_amount" not in invoice or not invoice.get("encrypted_amount"):
                        logger.error(f"Invoice {invoice.get('id', 'unknown')} missing or empty encrypted_amount field")
                        continue
                    if "encrypted_credits_purchased" not in invoice or not invoice.get("encrypted_credits_purchased"):
                        logger.error(f"Invoice {invoice.get('id', 'unknown')} missing or empty encrypted_credits_purchased field")
                        continue
                    
                    # Decrypt required fields
                    amount = await encryption_service.decrypt_with_user_key(
                        invoice["encrypted_amount"],
                        vault_key_id
                    )
                    
                    credits_purchased = await encryption_service.decrypt_with_user_key(
                        invoice["encrypted_credits_purchased"],
                        vault_key_id
                    )
                    
                    # Check if critical fields decrypted successfully
                    if not amount or not credits_purchased:
                        logger.warning(
                            f"Failed to decrypt critical invoice data for invoice {invoice.get('id', 'unknown')}. "
                            f"amount={bool(amount)}, credits={bool(credits_purchased)}"
                        )
                        continue
                    
                    # Format the date
                    invoice_date = invoice.get("date")
                    formatted_date = None
                    
                    if invoice_date:
                        try:
                            # Handle string format (ISO format from Directus)
                            if isinstance(invoice_date, str):
                                # Normalize timezone indicators (Z or +00:00)
                                date_str = invoice_date.replace('Z', '+00:00')
                                # Parse ISO format string
                                parsed_date = datetime.fromisoformat(date_str)
                            # Handle datetime object (if Directus returns it as object)
                            elif hasattr(invoice_date, 'isoformat'):
                                parsed_date = invoice_date
                            else:
                                # Try to convert to string and parse
                                date_str = str(invoice_date)
                                parsed_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            
                            # Format for display (YYYY-MM-DD)
                            formatted_date = parsed_date.strftime("%Y-%m-%d")
                        except Exception as date_parse_error:
                            logger.warning(
                                f"Failed to parse invoice date for invoice {invoice.get('id', 'unknown')}: {invoice_date}. "
                                f"Error: {date_parse_error}. Using fallback."
                            )
                            # Fallback: try to extract date from string
                            date_str = str(invoice_date)
                            if len(date_str) >= 10:
                                formatted_date = date_str[:10]  # Take first 10 chars (YYYY-MM-DD)
                            else:
                                formatted_date = None
                    
                    # If date parsing failed completely, use a fallback
                    if not formatted_date:
                        logger.error(f"Could not parse date for invoice {invoice.get('id', 'unknown')}. Date value: {invoice_date}")
                        formatted_date = "1970-01-01"  # Fallback date
                    
                    # Get order_id
                    order_id = invoice.get("order_id", "")
                    
                    # Get is_gift_card flag (defaults to False if not set for backward compatibility)
                    is_gift_card = invoice.get("is_gift_card", False)
                    
                    # Get refund information (if available)
                    refund_status = invoice.get("refund_status", "none")
                    
                    # Construct download URL
                    invoice_id = invoice.get("id")
                    download_url = None
                    if invoice_id:
                        download_url = f"{base_url}/v1/payments/invoices/{invoice_id}/download"
                    
                    processed_invoices.append(InvoiceResponse(
                        id=invoice_id,
                        order_id=order_id,
                        date=formatted_date,
                        amount=amount,
                        credits_purchased=int(credits_purchased),
                        is_gift_card=is_gift_card,
                        refund_status=refund_status,
                        download_url=download_url
                    ))
                    
                except Exception as e:
                    logger.error(
                        f"Error processing invoice {invoice.get('id', 'unknown')}: {str(e)}",
                        exc_info=True
                    )
                    continue
        
        logger.info(f"Successfully fetched billing overview for user {current_user.id}: tier={payment_tier}, invoices={len(processed_invoices)}")
        
        return BillingOverviewResponse(
            payment_tier=payment_tier,
            auto_topup_enabled=auto_topup_enabled,
            auto_topup_threshold=auto_topup_threshold,
            auto_topup_amount=auto_topup_amount,
            auto_topup_currency=auto_topup_currency,
            invoices=processed_invoices
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching billing overview for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch billing overview")


# --- Endpoint for server status (payment enabled, server edition, etc.) ---
class ServerStatusResponse(BaseModel):
    """Response model for server status endpoint"""
    payment_enabled: bool
    is_self_hosted: bool
    is_development: bool
    server_edition: str  # "production" | "development" | "self_hosted" (deprecated, use is_self_hosted)
    domain: Optional[str]  # Domain extracted from request (None for localhost)


@router.get(
    "/server-status",
    response_model=ServerStatusResponse,
    include_in_schema=False,  # Exclude from OpenAPI docs - internal endpoint for frontend
    dependencies=[Security(optional_api_key_scheme)]  # Public endpoint, but add security scheme for Swagger UI
)
@limiter.limit("60/minute")  # Rate limit to prevent abuse
async def get_server_status(
    request: Request
):
    """
    Get server status information including payment enablement and server edition.
    
    This is a public endpoint (no authentication required) that allows the frontend
    to check if payment features should be displayed and what server edition is running.
    
    This endpoint uses request-based validation to determine if the server is self-hosted.
    It extracts the domain from the request headers (Origin or Host) and validates it
    against the official domain from encrypted config. This provides better security
    than environment variable-based detection alone.
    
    Returns:
        ServerStatusResponse with payment_enabled, is_self_hosted, is_development, 
        server_edition (deprecated), and domain
    """
    try:
        # Import server mode utilities
        from backend.core.api.app.utils.server_mode import (
            is_payment_enabled,
            get_server_edition,
            validate_request_domain
        )
        
        # Validate request domain against official domain (request-based security)
        # This extracts domain from request headers and checks if it matches official domain
        # Returns: (domain, is_self_hosted, edition) where edition is "production" | "development" | "self_hosted"
        request_domain, is_self_hosted_from_request, request_edition = validate_request_domain(request)
        
        # Use request-based validation for is_self_hosted (more secure)
        # This cannot be easily spoofed by environment variables
        is_self_hosted = is_self_hosted_from_request
        
        # CRITICAL: If self-hosted (from request validation), payment is ALWAYS disabled
        # This overrides any environment-based logic that might enable payment for localhost in dev mode
        if is_self_hosted:
            payment_enabled = False
        else:
            # Only check environment-based payment logic if NOT self-hosted
            payment_enabled = is_payment_enabled()
        
        # Get server edition (for backward compatibility)
        server_edition = get_server_edition()
        
        # Determine is_development based on request edition
        # "development" edition means *.dev.{official_domain} subdomain
        is_development = request_edition == "development"
        
        logger.debug(
            f"Server status requested: payment_enabled={payment_enabled}, "
            f"is_self_hosted={is_self_hosted} (from request), "
            f"is_development={is_development} (from request edition), "
            f"request_edition={request_edition}, "
            f"server_edition={server_edition}, "
            f"request_domain={request_domain or 'localhost'}, "
            f"origin={request.headers.get('origin')}, host={request.headers.get('host')}"
        )
        
        return ServerStatusResponse(
            payment_enabled=payment_enabled,
            is_self_hosted=is_self_hosted,
            is_development=is_development,
            server_edition=request_edition,  # Use request-based edition (more accurate)
            domain=request_domain
        )
        
    except Exception as e:
        logger.error(f"Error fetching server status: {str(e)}", exc_info=True)
        # Return safe defaults on error (assume self-hosted to be safe)
        return ServerStatusResponse(
            payment_enabled=False,
            is_self_hosted=True,
            is_development=False,
            server_edition="self_hosted",
            domain=None
        )


# --- Endpoint for reporting issues ---
class DeviceInfo(BaseModel):
    """Device information for debugging purposes"""
    userAgent: str = Field(..., max_length=1000, description="Browser user agent string")
    viewportWidth: int = Field(..., ge=0, le=10000, description="Viewport width in pixels")
    viewportHeight: int = Field(..., ge=0, le=10000, description="Viewport height in pixels")
    isTouchEnabled: bool = Field(..., description="Whether touch is enabled")


class IssueReportRequest(BaseModel):
    """Request model for issue reporting endpoint"""
    title: str = Field(..., min_length=3, max_length=200, description="Issue title (required, 3-200 characters)")
    description: Optional[str] = Field(None, min_length=10, max_length=5000, description="Issue description (optional, 10-5000 characters if provided)")
    chat_or_embed_url: Optional[str] = Field(None, max_length=500, description="Optional chat or embed URL related to the issue")
    contact_email: Optional[str] = Field(None, max_length=255, description="Optional contact email address for follow-up communication")
    device_info: Optional[DeviceInfo] = Field(None, description="Device information for debugging purposes (browser, screen size, touch support)")
    console_logs: Optional[str] = Field(None, max_length=50000, description="Console logs from the client (last 100 lines)")
    indexeddb_report: Optional[str] = Field(None, max_length=100000, description="IndexedDB inspection report for active chat (metadata only, no plaintext content - safe for debugging)")
    last_messages_html: Optional[str] = Field(None, max_length=200000, description="Rendered HTML of the last user message and assistant response for debugging rendering issues")


class IssueReportResponse(BaseModel):
    """Response model for issue reporting endpoint"""
    success: bool
    message: str
    issue_id: Optional[str] = None  # The database ID of the created issue report (for admin lookup via /v1/admin/debug/issues/{issue_id})


@router.post(
    "/issues",
    response_model=IssueReportResponse,
    include_in_schema=False  # Exclude from schema - web app only, not for API access
)
@limiter.limit("5/minute")  # Rate limit to prevent abuse
async def report_issue(
    request: Request,
    issue_data: IssueReportRequest
):
    """
    Report an issue to the server owner.
    
    This endpoint is exclusive to the web app (not accessible via API keys) but allows
    both authenticated and non-authenticated users to submit issue reports.
    The issue report is sent via email to the server owner (admin email).
    
    The email includes:
    - Issue title
    - Issue description
    - Optional chat or embed URL
    - Timestamp
    - Estimated geo location (based on IP address)
    
    Args:
        request: FastAPI Request object (for IP extraction and geo location)
        issue_data: Issue report data (title, description, optional URL)
    
    Returns:
        IssueReportResponse with success status and message
    """
    try:
        # Import necessary utilities
        from backend.core.api.app.utils.device_fingerprint import _extract_client_ip, get_geo_data_from_ip
        from html import escape
        from urllib.parse import urlparse, urlunparse
        
        # SECURITY: Sanitize user inputs to prevent XSS attacks
        # HTML escape title and description to prevent injection of malicious HTML/JavaScript
        sanitized_title = escape(issue_data.title.strip())
        # Description is optional - only sanitize if provided
        sanitized_description = escape(issue_data.description.strip()) if issue_data.description else None
        
        # SECURITY: Validate and sanitize URL if provided
        sanitized_url = None
        if issue_data.chat_or_embed_url:
            url_str = issue_data.chat_or_embed_url.strip()
            # Validate URL format - must be a valid URL structure
            try:
                parsed = urlparse(url_str)
                # Only allow http/https schemes for security
                if parsed.scheme in ('http', 'https'):
                    # Reconstruct URL to normalize it (removes potential injection attempts)
                    sanitized_url = urlunparse((
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment
                    ))
                else:
                    # If no scheme, check if it's a relative URL (starts with /)
                    if url_str.startswith('/'):
                        # For relative URLs, validate it matches expected patterns
                        # Allow only /share/chat/, /share/embed/, or /#chat-id= patterns
                        if (url_str.startswith('/share/chat/') or 
                            url_str.startswith('/share/embed') or 
                            url_str.startswith('/#chat-id=')):
                            sanitized_url = url_str
                        else:
                            logger.warning(f"Invalid relative URL format in issue report: {url_str[:100]}")
                            sanitized_url = None
                    else:
                        logger.warning(f"Invalid URL scheme in issue report: {parsed.scheme}")
                        sanitized_url = None
            except Exception as e:
                logger.warning(f"Error parsing URL in issue report: {str(e)}")
                sanitized_url = None
        
        # SECURITY: Validate and sanitize email if provided
        sanitized_email = None
        if issue_data.contact_email:
            email_str = issue_data.contact_email.strip()
            # Basic email validation - check for valid email format
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if re.match(email_pattern, email_str):
                # Email is valid - escape it to prevent XSS (though emails shouldn't contain HTML, defense-in-depth)
                sanitized_email = escape(email_str)
            else:
                logger.warning(f"Invalid email format in issue report: {email_str[:50]}")
                sanitized_email = None
        
        # Extract client IP address
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        
        # Get geo location data from IP
        geo_data = get_geo_data_from_ip(client_ip)
        country_code = geo_data.get("country_code", "Unknown")
        region = geo_data.get("region")
        city = geo_data.get("city")
        
        # Build location string
        location_parts = []
        if city:
            location_parts.append(city)
        if region:
            location_parts.append(region)
        if country_code and country_code != "Unknown":
            location_parts.append(country_code)
        estimated_location = ", ".join(location_parts) if location_parts else "Unknown location"
        
        # Get current timestamp
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        
        # Get admin email from environment variable
        admin_email = os.getenv("REPORT_ISSUE_EMAIL", "reportissue@openmates.org")
        
        # Log the full admin email for debugging (this is safe as it's the server owner's email)
        logger.info(f"Issue report received - will send to admin email: {admin_email}")
        
        # Process device information if provided
        device_info_str = "Not provided"
        if issue_data.device_info:
            device_info = issue_data.device_info
            # Format device info in a readable way for the email
            # Sanitize the user agent to prevent any potential injection
            sanitized_user_agent = escape(device_info.userAgent[:500])  # Limit length and escape
            device_info_str = (
                f"Browser & OS: {sanitized_user_agent}\n"
                f"Screen Size: {device_info.viewportWidth} × {device_info.viewportHeight} pixels\n"
                f"Touch Support: {'Yes' if device_info.isTouchEnabled else 'No'}"
            )

        # Process console logs if provided
        console_logs_str = None
        if issue_data.console_logs and issue_data.console_logs.strip():
            console_logs_str = issue_data.console_logs.strip()
            logger.info(f"Console logs provided with issue report: {len(console_logs_str)} characters")
        
        # Process IndexedDB inspection report if provided
        # This contains only metadata (timestamps, versions, encrypted content lengths)
        # and NO plaintext content - safe to include for debugging
        indexeddb_report_str = None
        if issue_data.indexeddb_report and issue_data.indexeddb_report.strip():
            indexeddb_report_str = issue_data.indexeddb_report.strip()
            logger.info(f"IndexedDB report provided with issue report: {len(indexeddb_report_str)} characters")
        
        # Process last messages HTML if provided
        # This contains the rendered HTML of the last user message and assistant response
        # to help debug rendering issues and see exactly what the user saw
        last_messages_html_str = None
        if issue_data.last_messages_html and issue_data.last_messages_html.strip():
            last_messages_html_str = issue_data.last_messages_html.strip()
            logger.info(f"Last messages HTML provided with issue report: {len(last_messages_html_str)} characters")

        # Encrypt sensitive fields for database storage (server-side encryption)
        encryption_service: EncryptionService = request.app.state.encryption_service
        encrypted_contact_email = None
        encrypted_chat_or_embed_url = None
        encrypted_estimated_location = None
        encrypted_device_info = None
        encrypted_issue_report_yaml_s3_key = None
        
        try:
            # Encrypt contact email if provided
            if sanitized_email:
                encrypted_contact_email = await encryption_service.encrypt_issue_report_email(sanitized_email)
                logger.debug("Encrypted contact email for issue report database storage")
            
            # Encrypt chat or embed URL if provided
            if sanitized_url:
                encrypted_chat_or_embed_url = await encryption_service.encrypt_issue_report_data(sanitized_url)
                logger.debug("Encrypted chat or embed URL for issue report database storage")
            
            # Encrypt estimated location if provided
            if estimated_location:
                encrypted_estimated_location = await encryption_service.encrypt_issue_report_data(estimated_location)
                logger.debug("Encrypted estimated location for issue report database storage")
            
            # Encrypt device info if provided
            if device_info_str:
                encrypted_device_info = await encryption_service.encrypt_issue_report_data(device_info_str)
                logger.debug("Encrypted device info for issue report database storage")
            
            # Note: The YAML file will be created and uploaded in the email task after it's generated
            # We'll pass the issue_id to the email task so it can store the S3 key back to the database
        except Exception as e:
            logger.error(f"Failed to encrypt fields for issue report: {str(e)}", exc_info=True)
            # Continue without encrypted fields - email task will still work with plaintext
        
        # Save issue report to database
        try:
            directus_service: DirectusService = request.app.state.directus_service
            
            # Parse timestamp string back to datetime for database
            timestamp_dt = datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc)
            current_timestamp = datetime.now(timezone.utc)
            
            issue_data_dict = {
                "title": sanitized_title,
                "description": sanitized_description,
                "encrypted_chat_or_embed_url": encrypted_chat_or_embed_url,
                "encrypted_contact_email": encrypted_contact_email,
                "timestamp": timestamp_dt.isoformat(),
                "encrypted_estimated_location": encrypted_estimated_location,
                "encrypted_device_info": encrypted_device_info,
                "encrypted_issue_report_yaml_s3_key": encrypted_issue_report_yaml_s3_key,
                "created_at": current_timestamp.isoformat(),
                "updated_at": current_timestamp.isoformat()
            }
            
            # Remove None values to avoid database errors
            issue_data_dict = {k: v for k, v in issue_data_dict.items() if v is not None}
            
            # Log the data being saved (without sensitive encrypted data)
            logger.debug(f"Creating issue record in Directus with data keys: {list(issue_data_dict.keys())}")
            
            # Create issue record in Directus
            # NOTE: create_item returns a tuple (success: bool, data: dict)
            success, issue_record = await directus_service.create_item("issues", issue_data_dict)
            
            if not success:
                # issue_record contains error details when success is False
                error_msg = issue_record.get('text', str(issue_record)) if issue_record else 'Unknown error'
                raise ValueError(f"Directus create_item failed: {error_msg}")
            
            if not issue_record:
                raise ValueError("Directus create_item returned None - issue record was not created")
            
            issue_id = issue_record.get('id')
            if not issue_id:
                raise ValueError(f"Directus create_item returned record without 'id' field: {issue_record}")
            
            logger.info(f"Issue report saved to database with ID: {issue_id}")
        except Exception as e:
            logger.error(
                f"Failed to save issue report to database: {str(e)}. "
                f"Email will still be sent but YAML report will NOT be uploaded to S3 "
                f"(issue_id will be None in the email task).",
                exc_info=True
            )
            # Continue - email will still be sent even if database save fails,
            # but S3 upload will be skipped since issue_id is None
            issue_id = None
        
        # Dispatch the email task with sanitized data
        # The email task will create the YAML file, encrypt it, upload to S3, and update the database with the S3 key
        from backend.core.api.app.tasks.celery_config import app
        task_result = app.send_task(
            name='app.tasks.email_tasks.issue_report_email_task.send_issue_report_email',
            kwargs={
                "admin_email": admin_email,
                "issue_id": issue_id,  # Pass issue ID so email task can update database with S3 key
                "issue_title": sanitized_title,
                "issue_description": sanitized_description,
                "chat_or_embed_url": sanitized_url,
                "contact_email": sanitized_email,  # Use plaintext for email (not encrypted)
                "timestamp": current_time,
                "estimated_location": estimated_location,
                "device_info": device_info_str,
                "console_logs": console_logs_str,
                "indexeddb_report": indexeddb_report_str,
                "last_messages_html": last_messages_html_str
            },
            queue='email'
        )
        
        logger.info(
            f"Issue report submitted: '{issue_data.title[:50]}...' - "
            f"email task dispatched to queue 'email' with task_id={task_result.id}, "
            f"recipient={admin_email}"
        )
        
        return IssueReportResponse(
            success=True,
            message="Issue report submitted successfully. Thank you for your feedback!",
            issue_id=issue_id  # Return issue ID so frontend can display it for admin lookup
        )
        
    except Exception as e:
        logger.error(f"Error processing issue report: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit issue report. Please try again later.")


# --- Account Deletion Endpoints ---

class DeleteAccountPreviewResponse(BaseModel):
    """
    Response model for account deletion preview.
    
    Policy: All unused credits are refunded EXCEPT credits from gift card redemptions.
    This is user-friendly and reduces chargeback risk.
    """
    total_credits: int  # User's current total credit balance
    refundable_credits: int  # Credits that will be refunded (excludes gift card credits)
    credits_from_gift_cards: int  # Credits from gift card redemptions (not refundable)
    has_refundable_credits: bool  # Whether there are credits to refund
    auto_refunds: Dict[str, Any]  # Details about the refund (amount, invoices, etc.)


class DeleteAccountRequest(BaseModel):
    """Request model for account deletion"""
    confirm_data_deletion: bool  # User must confirm they understand data will be deleted
    auth_method: str  # "passkey" or "2fa_otp"
    auth_code: Optional[str] = None  # OTP code for 2FA, or credential_id for passkey


async def _calculate_delete_account_preview(
    user_id: str,
    user_id_hash: str,
    vault_key_id: str,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    cache_service: CacheService
) -> DeleteAccountPreviewResponse:
    """
    Helper function to calculate account deletion preview data.
    
    Policy: Refund ALL unused credits EXCEPT credits from gift card redemptions.
    This is user-friendly and reduces chargeback risk.
    
    Approach:
    1. Get user's total credits from cache
    2. Get all non-refunded invoices for the user
    3. Calculate credits from gift card redemptions (not refundable)
    4. Calculate refundable credits = total credits - gift card credits
    5. Calculate proportional refund amount based on invoices
    """
    # Step 1: Get user's current total credits from cache
    user_data = await cache_service.get_user_by_id(user_id)
    if not user_data:
        logger.warning(f"User not found in cache for deletion preview: {user_id}")
        total_credits = 0
    else:
        total_credits = int(user_data.get("credits", 0))
    
    logger.debug(f"[DeletePreview] User {user_id} has {total_credits} total credits")
    
    # Step 2: Get all non-refunded invoices for the user
    # We need all invoices to calculate the refund proportionally
    invoices_data = await directus_service.get_items(
        collection="invoices",
        params={
            "filter": {
                "_and": [
                    {"user_id_hash": {"_eq": user_id_hash}},
                    {"refunded_at": {"_null": True}}  # Only non-refunded invoices
                ]
            },
            "fields": "*"
        }
    )
    
    if not invoices_data:
        invoices_data = []
    
    logger.debug(f"[DeletePreview] Found {len(invoices_data)} non-refunded invoices")
    
    # Step 3: Process invoices to separate regular purchases from gift card redemptions
    eligible_invoices = []  # Invoices eligible for refund (regular purchases)
    total_credits_from_purchases = 0  # Credits from regular purchases
    total_credits_from_gift_cards = 0  # Credits from gift card redemptions
    total_purchase_amount_cents = 0  # Total amount paid for regular purchases
    
    for invoice in invoices_data:
        # Decrypt invoice data
        encrypted_amount = invoice.get("encrypted_amount")
        encrypted_credits = invoice.get("encrypted_credits_purchased")
        
        if not encrypted_amount or not encrypted_credits:
            logger.debug(f"[DeletePreview] Invoice missing encrypted data: {invoice.get('id')}")
            continue
        
        try:
            invoice_amount_cents = int(await encryption_service.decrypt_with_user_key(encrypted_amount, vault_key_id))
            invoice_credits = int(await encryption_service.decrypt_with_user_key(encrypted_credits, vault_key_id))
        except Exception as e:
            logger.warning(f"Could not decrypt invoice data for invoice {invoice.get('id')}: {e}")
            continue
        
        is_gift_card = invoice.get("is_gift_card", False)
        
        if is_gift_card:
            # Gift card redemption - credits are NOT refundable
            total_credits_from_gift_cards += invoice_credits
            logger.debug(f"[DeletePreview] Gift card invoice {invoice.get('id')}: {invoice_credits} credits (not refundable)")
        else:
            # Regular purchase - credits ARE refundable
            total_credits_from_purchases += invoice_credits
            total_purchase_amount_cents += invoice_amount_cents
            
            # Get currency from order cache or default to EUR
            order_id = invoice.get("order_id")
            currency = "eur"
            if order_id:
                order_data = await cache_service.get_order(order_id)
                if order_data:
                    currency = order_data.get("currency", "eur")
            
            invoice_date_str = invoice.get("date", "")
            eligible_invoices.append({
                "invoice_id": invoice.get("id"),
                "order_id": order_id,
                "date": invoice_date_str,
                "total_credits": invoice_credits,
                "amount_cents": invoice_amount_cents,
                "currency": currency
            })
    
    # Step 4: Calculate refundable credits
    # Refundable = total credits - credits from gift cards
    # But cap at actual credits from purchases (can't refund more than purchased)
    refundable_credits = max(0, min(total_credits - total_credits_from_gift_cards, total_credits_from_purchases))
    
    # Step 5: Calculate refund amount proportionally
    # If user has used some credits, refund is proportional to remaining credits
    if total_credits_from_purchases > 0 and refundable_credits > 0:
        # Calculate average price per credit from all purchases
        price_per_credit = total_purchase_amount_cents / total_credits_from_purchases
        total_refund_amount_cents = int(refundable_credits * price_per_credit)
    else:
        total_refund_amount_cents = 0
    
    logger.debug(
        f"[DeletePreview] Total credits: {total_credits}, "
        f"From purchases: {total_credits_from_purchases}, "
        f"From gift cards: {total_credits_from_gift_cards}, "
        f"Refundable: {refundable_credits}, "
        f"Refund amount: {total_refund_amount_cents} cents"
    )
    
    # Step 6: Get gift card purchases made BY the user (for informational purposes)
    # These are gift cards the user bought for others, not redeemed gift cards
    gift_cards_data = await directus_service.get_items(
        collection="gift_cards",
        params={
            "filter": {
                "purchaser_user_id_hash": {"_eq": user_id_hash}
            },
            "fields": "*"
        }
    )
    
    gift_card_purchases = []
    if gift_cards_data:
        for gift_card in gift_cards_data:
            gift_card_purchases.append({
                "gift_card_code": gift_card.get("code", ""),
                "credits_value": gift_card.get("credits_value", 0),
                "purchased_at": gift_card.get("created_at", ""),
                "is_redeemed": gift_card.get("redeemed_at") is not None
            })
    
    return DeleteAccountPreviewResponse(
        total_credits=total_credits,
        refundable_credits=refundable_credits,
        credits_from_gift_cards=total_credits_from_gift_cards,
        has_refundable_credits=refundable_credits > 0,
        auto_refunds={
            "total_refund_amount_cents": total_refund_amount_cents,
            "total_refund_currency": "eur",  # Default currency
            "eligible_invoices": eligible_invoices,
            "gift_card_purchases": gift_card_purchases
        }
    )


@router.get("/delete-account-preview", response_model=DeleteAccountPreviewResponse, include_in_schema=False)
@limiter.limit("10/minute")
async def get_delete_account_preview(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Get preview information about what will happen during account deletion.
    Returns credits that will be lost, eligible refunds, and gift card information.
    """
    user_id = current_user.id
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    vault_key_id = current_user.vault_key_id
    
    if not vault_key_id:
        logger.error(f"Vault key ID missing for user {user_id}")
        raise HTTPException(status_code=500, detail="User encryption key not found")
    
    logger.info(f"Fetching account deletion preview for user {user_id}")
    
    try:
        return await _calculate_delete_account_preview(
            user_id=user_id,
            user_id_hash=user_id_hash,
            vault_key_id=vault_key_id,
            directus_service=directus_service,
            encryption_service=encryption_service,
            cache_service=cache_service
        )
    except Exception as e:
        logger.error(f"Error fetching account deletion preview for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch deletion preview")


@router.post("/delete-account", response_model=SimpleSuccessResponse, include_in_schema=False)
@limiter.limit("3/minute")  # Very sensitive operation - strict rate limit
async def delete_account(
    request: Request,
    delete_request: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Delete user account and all associated data.
    Requires re-authentication (passkey or 2FA) and confirmation toggles.
    """
    user_id = current_user.id
    client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
    # Generate device fingerprint hash for compliance logging
    device_hash, _, _, _, _, _, _, _ = generate_device_fingerprint_hash(request, user_id=user_id)
    device_fingerprint = device_hash  # Use device_hash for compliance logging
    
    logger.info(f"Account deletion request for user {user_id}")
    
    try:
        # Get preview data to validate confirmations
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
        vault_key_id = current_user.vault_key_id
        
        if not vault_key_id:
            logger.error(f"Vault key ID missing for user {user_id}")
            raise HTTPException(status_code=500, detail="User encryption key not found")
        
        # Note: We call _calculate_delete_account_preview here to validate the user exists
        # and has proper encryption keys before proceeding. The actual refund calculation
        # is done during the deletion task.
        await _calculate_delete_account_preview(
            user_id=user_id,
            user_id_hash=user_id_hash,
            vault_key_id=vault_key_id,
            directus_service=directus_service,
            encryption_service=encryption_service,
            cache_service=cache_service
        )
        
        # Validate confirmations - only data deletion confirmation is required
        # Credits are automatically refunded (except gift card credits), so no separate confirmation needed
        if not delete_request.confirm_data_deletion:
            raise HTTPException(status_code=400, detail="Data deletion confirmation is required")
        
        # Validate authentication
        if delete_request.auth_method == "passkey":
            if not delete_request.auth_code:
                raise HTTPException(status_code=400, detail="Passkey credential ID is required")
            
            # Verify passkey belongs to user
            passkey = await directus_service.get_passkey_by_credential_id(delete_request.auth_code)
            if not passkey or passkey.get("user_id") != user_id:
                logger.warning(f"Invalid passkey verification for account deletion: user {user_id}")
                raise HTTPException(status_code=401, detail="Invalid passkey authentication")
            
            logger.info(f"Passkey authentication verified for account deletion: user {user_id}")
            
        elif delete_request.auth_method == "2fa_otp":
            if not delete_request.auth_code:
                raise HTTPException(status_code=400, detail="2FA code is required")
            
            # Verify 2FA code
            from backend.core.api.app.routes.auth_routes.auth_2fa_verify import verify_device_2fa
            from backend.core.api.app.schemas.auth_2fa import VerifyDevice2FARequest
            
            verify_request = VerifyDevice2FARequest(tfa_code=delete_request.auth_code)
            verify_response = await verify_device_2fa(
                request=request,
                verify_request=verify_request,
                directus_service=directus_service,
                cache_service=cache_service,
                compliance_service=compliance_service,
                encryption_service=encryption_service
            )
            
            if not verify_response.success:
                logger.warning(f"Invalid 2FA verification for account deletion: user {user_id}")
                raise HTTPException(status_code=401, detail="Invalid 2FA code")
            
            logger.info(f"2FA authentication verified for account deletion: user {user_id}")
        else:
            raise HTTPException(status_code=400, detail="Invalid authentication method")
        
        # Trigger Celery task for account deletion
        from backend.core.api.app.tasks.celery_config import app
        task_result = app.send_task(
            name="delete_user_account",
            kwargs={
                "user_id": user_id,
                "deletion_type": "user_requested",
                "reason": "User requested account deletion",
                "ip_address": client_ip,
                "device_fingerprint": device_fingerprint,
                "refund_invoices": True
            },
            queue="user_init"  # Use user_init queue for account deletion
        )
        
        logger.info(f"Account deletion task triggered for user {user_id}, task_id={task_result.id}")
        
        # Logout user immediately (delete sessions)
        try:
            await directus_service.logout_all_sessions(user_id)
            # Clear cache
            await cache_service.delete(f"user_profile:{user_id}")
        except Exception as e:
            logger.warning(f"Error during immediate logout for user {user_id}: {e}")
        
        # Log compliance event
        try:
            compliance_service.log_account_deletion(
                user_id=user_id,
                deletion_type="user_requested",
                reason="User requested account deletion",
                ip_address=client_ip,
                device_fingerprint=device_fingerprint
            )
        except Exception as e:
            logger.warning(f"Error logging account deletion compliance event: {e}")
        
        return SimpleSuccessResponse(
            success=True,
            message="Account deletion initiated. You will be logged out shortly."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing account deletion request for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process account deletion request")


# --- Account Data Export Endpoints (GDPR Article 20 - Right to Data Portability) ---

class ExportManifestResponse(BaseModel):
    """Response model for export manifest - lists all data IDs for client-side sync"""
    success: bool
    manifest: Dict[str, Any]


class UsageEntryExport(BaseModel):
    """Export format for a single usage entry"""
    usage_id: str
    timestamp: int
    app_id: str
    skill_id: str
    usage_type: str
    source: str  # "chat", "api_key", "direct"
    credits_charged: int
    model_used: Optional[str] = None
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    cost_system_prompt_credits: Optional[int] = None
    cost_history_credits: Optional[int] = None
    cost_response_credits: Optional[int] = None
    actual_input_tokens: Optional[int] = None
    actual_output_tokens: Optional[int] = None


class InvoiceExport(BaseModel):
    """Export format for a single invoice"""
    invoice_id: str
    order_id: str
    date: str
    amount_cents: int
    currency: str
    credits_purchased: int
    is_gift_card: bool
    refunded_at: Optional[str] = None
    refund_status: str = "none"


class ExportDataResponse(BaseModel):
    """Response model for export data - contains usage and invoice data"""
    success: bool
    data: Dict[str, Any]


@router.get("/export-account-manifest", response_model=ExportManifestResponse, include_in_schema=False)
@limiter.limit("10/minute")
async def get_export_manifest(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Get export manifest - list of all data IDs the user has.
    Used by client to determine what needs to be synced before export.
    
    GDPR Article 20 - Right to Data Portability:
    This endpoint provides the client with information about all user data
    available for export.
    """
    user_id = current_user.id
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    
    logger.info(f"[EXPORT] Fetching export manifest for user {user_id}")
    
    try:
        # Get all chat IDs for the user (no limit - we need ALL chats for export)
        # Try cache first
        cached_chat_ids = await cache_service.get_chat_ids_versions(user_id, start=0, end=-1)
        
        if cached_chat_ids:
            all_chat_ids = cached_chat_ids
            logger.info(f"[EXPORT] Found {len(all_chat_ids)} chat IDs from cache for user {user_id}")
        else:
            # Fallback to Directus - get ALL chats (no limit)
            chats = await directus_service.get_items(
                "chats",
                params={
                    "filter": {"hashed_user_id": {"_eq": user_id_hash}},
                    "fields": "id",
                    "limit": -1,  # No limit - get ALL chats
                    "sort": "-last_edited_overall_timestamp"
                }
            )
            all_chat_ids = [chat["id"] for chat in (chats or [])]
            logger.info(f"[EXPORT] Found {len(all_chat_ids)} chat IDs from Directus for user {user_id}")
        
        # Count other data types
        # Count invoices
        invoices = await directus_service.get_items(
            "invoices",
            params={
                "filter": {"user_id_hash": {"_eq": user_id_hash}},
                "fields": "id",
                "limit": -1
            }
        )
        invoice_count = len(invoices or [])
        
        # Count usage entries (just count, actual data fetched separately)
        usage_entries = await directus_service.get_items(
            "usage",
            params={
                "filter": {"user_id_hash": {"_eq": user_id_hash}},
                "fields": "id",
                "limit": -1
            }
        )
        usage_count = len(usage_entries or [])
        
        # Check for app settings/memories
        app_settings = await directus_service.get_items(
            "user_app_settings_and_memories",
            params={
                "filter": {"hashed_user_id": {"_eq": user_id_hash}},
                "fields": "id",
                "limit": 1
            }
        )
        has_app_settings = len(app_settings or []) > 0
        
        # Estimate export size (rough estimation)
        # Average chat size: ~5KB, average invoice: ~2KB, average usage entry: ~0.5KB
        estimated_size_mb = (len(all_chat_ids) * 5 + invoice_count * 2 + usage_count * 0.5) / 1024
        
        manifest = {
            "all_chat_ids": all_chat_ids,
            "total_chats": len(all_chat_ids),
            "total_invoices": invoice_count,
            "total_usage_entries": usage_count,
            "has_app_settings": has_app_settings,
            "has_memories": has_app_settings,  # Same collection
            "has_usage_data": usage_count > 0,
            "has_invoices": invoice_count > 0,
            "estimated_size_mb": round(estimated_size_mb, 2)
        }
        
        logger.info(f"[EXPORT] Manifest ready for user {user_id}: {len(all_chat_ids)} chats, {invoice_count} invoices, {usage_count} usage entries")
        
        return ExportManifestResponse(
            success=True,
            manifest=manifest
        )
        
    except Exception as e:
        logger.error(f"[EXPORT] Error fetching export manifest for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch export manifest")


@router.get("/export-account-data", response_model=ExportDataResponse, include_in_schema=False)
@limiter.limit("5/minute")  # Lower rate limit due to heavier processing
async def get_export_data(
    request: Request,
    include_usage: bool = True,
    include_invoices: bool = True,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Get export data - usage records and invoices (data not in client IndexedDB).
    
    GDPR Article 20 - Right to Data Portability:
    Returns encrypted data that needs to be decrypted client-side.
    The client decrypts with master key and includes in export ZIP.
    
    Note: Chat data is already synced to client via WebSocket/IndexedDB.
    This endpoint returns supplementary data not normally synced.
    """
    user_id = current_user.id
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    vault_key_id = current_user.vault_key_id
    
    if not vault_key_id:
        logger.error(f"[EXPORT] Vault key ID missing for user {user_id}")
        raise HTTPException(status_code=500, detail="User encryption key not found")
    
    logger.info(f"[EXPORT] Fetching export data for user {user_id} (usage={include_usage}, invoices={include_invoices})")
    
    try:
        export_data: Dict[str, Any] = {}
        
        # === USAGE DATA ===
        if include_usage:
            try:
                # Fetch ALL usage entries (no limit for export)
                usage_entries = await directus_service.usage.get_user_usage_entries(
                    user_id_hash=user_id_hash,
                    user_vault_key_id=vault_key_id,
                    limit=-1,  # No limit - get ALL entries
                    sort="-created_at"
                )
                
                # Format usage entries for export (already decrypted by get_user_usage_entries)
                export_data["usage_records"] = [
                    {
                        "usage_id": entry.get("id", ""),
                        "timestamp": entry.get("created_at", 0),
                        "app_id": entry.get("app_id", ""),
                        "skill_id": entry.get("skill_id", ""),
                        "usage_type": entry.get("usage_type", ""),
                        "source": entry.get("source", "chat"),
                        "credits_charged": entry.get("credits_charged", 0),
                        "model_used": entry.get("model_used"),
                        "chat_id": entry.get("chat_id"),
                        "message_id": entry.get("message_id"),
                        "cost_system_prompt_credits": entry.get("cost_system_prompt_credits"),
                        "cost_history_credits": entry.get("cost_history_credits"),
                        "cost_response_credits": entry.get("cost_response_credits"),
                        "actual_input_tokens": entry.get("actual_input_tokens"),
                        "actual_output_tokens": entry.get("actual_output_tokens"),
                    }
                    for entry in (usage_entries or [])
                ]
                
                logger.info(f"[EXPORT] Fetched {len(export_data['usage_records'])} usage entries for user {user_id}")
                
            except Exception as e:
                logger.error(f"[EXPORT] Error fetching usage data for user {user_id}: {e}", exc_info=True)
                export_data["usage_records"] = []
                export_data["usage_error"] = str(e)
        
        # === INVOICE DATA ===
        if include_invoices:
            try:
                # Fetch all invoices
                invoices_data = await directus_service.get_items(
                    collection="invoices",
                    params={
                        "filter": {"user_id_hash": {"_eq": user_id_hash}},
                        "sort": "-date",
                        "limit": -1  # No limit - get ALL invoices
                    }
                )
                
                processed_invoices = []
                invoice_ids_for_download = []
                
                for invoice in (invoices_data or []):
                    try:
                        # Decrypt invoice data
                        if not invoice.get("encrypted_amount") or not invoice.get("encrypted_credits_purchased"):
                            logger.warning(f"[EXPORT] Invoice {invoice.get('id')} missing encrypted fields, skipping")
                            continue
                        
                        amount = await encryption_service.decrypt_with_user_key(
                            invoice["encrypted_amount"],
                            vault_key_id
                        )
                        
                        credits_purchased = await encryption_service.decrypt_with_user_key(
                            invoice["encrypted_credits_purchased"],
                            vault_key_id
                        )
                        
                        if not amount or not credits_purchased:
                            logger.warning(f"[EXPORT] Failed to decrypt invoice {invoice.get('id')}")
                            continue
                        
                        # Parse amount to cents (it's stored as formatted string like "€20.00")
                        try:
                            # Remove currency symbol and convert to cents
                            amount_str = str(amount).replace('€', '').replace('$', '').replace(',', '.').strip()
                            amount_cents = int(float(amount_str) * 100)
                        except (ValueError, TypeError):
                            amount_cents = 0
                        
                        # Format date
                        invoice_date = invoice.get("date")
                        formatted_date = ""
                        if invoice_date:
                            if isinstance(invoice_date, str):
                                formatted_date = invoice_date
                            elif hasattr(invoice_date, 'isoformat'):
                                formatted_date = invoice_date.isoformat()
                        
                        processed_invoices.append({
                            "invoice_id": invoice["id"],
                            "order_id": invoice.get("order_id", ""),
                            "date": formatted_date,
                            "amount_cents": amount_cents,
                            "currency": "eur",  # Default currency
                            "credits_purchased": int(credits_purchased),
                            "is_gift_card": invoice.get("is_gift_card", False),
                            "refunded_at": invoice.get("refunded_at"),
                            "refund_status": invoice.get("refund_status", "none"),
                            # Include S3 info for PDF download (encrypted, client will decrypt)
                            "encrypted_s3_object_key": invoice.get("encrypted_s3_object_key"),
                            "encrypted_aes_key": invoice.get("encrypted_aes_key"),
                            "aes_nonce": invoice.get("aes_nonce"),
                            "encrypted_filename": invoice.get("encrypted_filename")
                        })
                        
                        invoice_ids_for_download.append(invoice["id"])
                        
                    except Exception as e:
                        logger.error(f"[EXPORT] Error processing invoice {invoice.get('id')}: {e}", exc_info=True)
                        continue
                
                export_data["invoices"] = processed_invoices
                export_data["invoice_ids_for_pdf_download"] = invoice_ids_for_download
                
                logger.info(f"[EXPORT] Fetched {len(processed_invoices)} invoices for user {user_id}")
                
            except Exception as e:
                logger.error(f"[EXPORT] Error fetching invoice data for user {user_id}: {e}", exc_info=True)
                export_data["invoices"] = []
                export_data["invoice_error"] = str(e)
        
        # === USER PROFILE DATA ===
        try:
            # Get user profile info from cache/Directus
            user_profile_result = await directus_service.get_user_profile(user_id)
            if user_profile_result and user_profile_result[0]:
                user_profile = user_profile_result[1]
                
                logger.debug(f"[EXPORT] User profile raw data: status={user_profile.get('status')}, keys={list(user_profile.keys())}")
                
                # Decrypt email if available (client needs to decrypt with master key)
                email = None
                if user_profile.get("encrypted_email_with_master_key"):
                    # This needs to be decrypted client-side with master key
                    email = user_profile.get("encrypted_email_with_master_key")
                
                # Determine passkey status
                has_passkey = False
                passkey_count = 0
                try:
                    passkeys = await directus_service.get_items(
                        "user_passkeys",
                        params={
                            "filter": {"user_id": {"_eq": user_id}},
                            "fields": "id",
                            "limit": -1
                        }
                    )
                    has_passkey = len(passkeys or []) > 0
                    passkey_count = len(passkeys or [])
                except Exception as e:
                    logger.warning(f"[EXPORT] Error fetching passkeys for user {user_id}: {e}")
                
                # User status from profile
                # Directus user status can be: 'active', 'draft', 'invited', 'suspended', 'archived'
                user_status = user_profile.get("status")
                
                # Email verification is REQUIRED during signup - any existing user account
                # has by definition verified their email (verification code sent to email
                # must be entered before account creation can proceed)
                email_verified = True
                
                # Build user profile export data
                profile_data = {
                    "user_id": user_id,
                    "username": user_profile.get("username", ""),
                    "encrypted_email_with_master_key": email,
                    "email_verified": email_verified,
                    "account_status": user_status,
                    "last_access": user_profile.get("last_access"),
                    "language": user_profile.get("language", "en"),
                    "darkmode": user_profile.get("darkmode", False),
                    "currency": user_profile.get("auto_topup_low_balance_currency", "eur"),
                    "credits": user_profile.get("credits", 0),
                    "tfa_enabled": user_profile.get("tfa_enabled", False),
                    "has_passkey": has_passkey,
                    "passkey_count": passkey_count,
                }
                
                # Only include auto_topup details if enabled
                auto_topup_enabled = user_profile.get("auto_topup_low_balance_enabled", False)
                profile_data["auto_topup_enabled"] = auto_topup_enabled
                if auto_topup_enabled:
                    profile_data["auto_topup_threshold"] = user_profile.get("auto_topup_low_balance_threshold")
                    profile_data["auto_topup_amount"] = user_profile.get("auto_topup_low_balance_amount")
                
                export_data["user_profile"] = profile_data
                
                logger.info(f"[EXPORT] User profile compiled for user {user_id}: email_verified={email_verified}, status={user_status}, passkeys={passkey_count}")
                
        except Exception as e:
            logger.error(f"[EXPORT] Error fetching user profile for export: {e}", exc_info=True)
            export_data["user_profile"] = None
        
        # === COMPLIANCE LOGS (consent history) ===
        # Compliance logs contain privacy policy and terms of service consent records
        # These are stored in /app/logs/compliance.log and rotated files (compliance.log.YYYY-MM-DD)
        # We need to read ALL log files to capture the full history (including user creation/consent from past days)
        try:
            compliance_logs = []
            log_dir = os.getenv('LOG_DIR', '/app/logs')
            
            # Find all compliance log files (main file and rotated files)
            # Pattern matches: compliance.log, compliance.log.2025-12-28, etc.
            log_pattern = os.path.join(log_dir, 'compliance.log*')
            log_files = glob.glob(log_pattern)
            
            # Sort log files to ensure consistent ordering (oldest first)
            log_files.sort()
            
            logger.info(f"[EXPORT] Found {len(log_files)} compliance log files to search: {[os.path.basename(f) for f in log_files]}")
            
            # Event types to include in export:
            # - consent: Privacy policy and terms of service acceptances
            # - user_creation: Account creation timestamp
            # - account_deletion: Account deletion (user requested)
            # - account_deletion_request: Account deletion request (legacy/alternative name)
            # - recovery_key_setup_complete: Recovery key setup for account security
            exportable_event_types = [
                "consent", 
                "user_creation", 
                "account_deletion",  # The actual event type used in logs
                "account_deletion_request",  # Legacy/alternative name
                "recovery_key_setup_complete"  # Important for user to know when they set up recovery
            ]
            
            for log_file_path in log_files:
                if os.path.exists(log_file_path):
                    try:
                        with open(log_file_path, 'r', encoding='utf-8') as log_file:
                            for line in log_file:
                                try:
                                    log_entry = json.loads(line.strip())
                                    # Filter for this user's logs
                                    if log_entry.get("user_id") == user_id:
                                        event_type = log_entry.get("event_type", "")
                                        if event_type in exportable_event_types:
                                            # Remove IP-related fields for export (privacy)
                                            log_entry.pop("ip_address_hash", None)
                                            log_entry.pop("ip_address", None)
                                            log_entry.pop("device_fingerprint", None)
                                            compliance_logs.append(log_entry)
                                except json.JSONDecodeError:
                                    continue
                    except Exception as e:
                        logger.warning(f"[EXPORT] Error reading compliance log file {log_file_path}: {e}")
                        continue
            
            # Sort by timestamp to ensure chronological order
            compliance_logs.sort(key=lambda x: x.get("timestamp", ""))
            
            logger.info(f"[EXPORT] Found {len(compliance_logs)} compliance log entries for user {user_id}")
            
            if len(compliance_logs) == 0:
                logger.warning(f"[EXPORT] No compliance logs found for user {user_id} - this is unexpected for an active user")
            
            export_data["compliance_logs"] = compliance_logs
            
        except Exception as e:
            logger.error(f"[EXPORT] Error reading compliance logs: {e}", exc_info=True)
            export_data["compliance_logs"] = []
        
        # === APP SETTINGS & MEMORIES ===
        try:
            app_settings = await directus_service.get_items(
                "user_app_settings_and_memories",
                params={
                    "filter": {"hashed_user_id": {"_eq": user_id_hash}},
                    "limit": -1
                }
            )
            
            # These are encrypted - pass through for client-side decryption
            export_data["app_settings_memories"] = app_settings or []
            logger.info(f"[EXPORT] Fetched {len(app_settings or [])} app settings/memories for user {user_id}")
            
        except Exception as e:
            logger.error(f"[EXPORT] Error fetching app settings/memories: {e}", exc_info=True)
            export_data["app_settings_memories"] = []
        
        return ExportDataResponse(
            success=True,
            data=export_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[EXPORT] Error fetching export data for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch export data")


# ============================================================================
# PASSWORD MANAGEMENT ENDPOINTS
# ============================================================================

class UpdatePasswordRequest(BaseModel):
    """Request model for adding or changing password."""
    hashed_email: str = Field(..., description="SHA256 hash of user's email for lookup")
    lookup_hash: str = Field(..., description="Hash derived from new password for authentication")
    encrypted_master_key: str = Field(..., description="Master key encrypted with password-derived key")
    salt: str = Field(..., description="Salt used for password key derivation")
    key_iv: str = Field(..., description="IV used for master key encryption")
    is_new_password: bool = Field(..., description="True if adding new password, False if changing existing")

class UpdatePasswordResponse(BaseModel):
    """Response model for password update."""
    success: bool
    message: str


@router.post("/update-password", response_model=UpdatePasswordResponse, include_in_schema=False)  # Exclude from schema - web app only, not for API access
@limiter.limit("5/minute")  # Sensitive operation - prevent abuse
async def update_password(
    request: Request,
    password_request: UpdatePasswordRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Add or change user password.
    
    This endpoint allows users to:
    - Add a new password login method (for passkey-only users)
    - Change their existing password
    
    The frontend must authenticate the user first (via passkey or current password)
    before calling this endpoint.
    
    The client-side encryption works as follows:
    1. User enters new password
    2. Client generates salt and derives wrapping key from password
    3. Client wraps existing master key with the new wrapping key
    4. Client generates lookup_hash from password + email_salt
    5. Client sends encrypted_master_key, salt, key_iv, and lookup_hash to server
    
    The server stores:
    - lookup_hash: For password authentication (indexed for fast lookup)
    - encrypted_master_key: User's encrypted master key
    - salt: For deriving wrapping key during login
    - key_iv: IV used for encryption
    """
    logger.info(f"[PASSWORD] Processing password update for user {current_user.id}")
    
    try:
        user_id = current_user.id
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        # Check if user already has a password
        existing_password_key = await directus_service.get_encryption_key(hashed_user_id, "password")
        has_existing_password = existing_password_key is not None
        
        # Validate the request
        if password_request.is_new_password and has_existing_password:
            logger.warning(f"[PASSWORD] User {user_id} tried to add password but already has one")
            return UpdatePasswordResponse(
                success=False,
                message="You already have a password. Use 'Change Password' instead."
            )
        
        if not password_request.is_new_password and not has_existing_password:
            logger.warning(f"[PASSWORD] User {user_id} tried to change password but doesn't have one")
            return UpdatePasswordResponse(
                success=False,
                message="No existing password found. Use 'Add Password' instead."
            )
        
        # If changing password, delete the old encryption key first
        if has_existing_password:
            logger.info(f"[PASSWORD] Deleting existing password key for user {user_id}")
            delete_success = await directus_service.delete_encryption_key(hashed_user_id, "password")
            if not delete_success:
                logger.error(f"[PASSWORD] Failed to delete existing password key for user {user_id}")
                return UpdatePasswordResponse(
                    success=False,
                    message="Failed to update password. Please try again."
                )
        
        # Create the new password encryption key
        # First, create lookup hash entry in the user_lookup_hashes table or similar
        # The lookup_hash is used for fast authentication during login
        logger.info(f"[PASSWORD] Creating new password key for user {user_id}")
        
        # Store the new encryption key with password as login_method
        success = await directus_service.create_encryption_key(
            hashed_user_id=hashed_user_id,
            login_method="password",
            encrypted_key=password_request.encrypted_master_key,
            salt=password_request.salt,
            key_iv=password_request.key_iv
        )
        
        if not success:
            logger.error(f"[PASSWORD] Failed to create encryption key for user {user_id}")
            return UpdatePasswordResponse(
                success=False,
                message="Failed to save password. Please try again."
            )
        
        # Update lookup_hashes in the users table
        # The lookup_hash allows the user to authenticate with password during login
        try:
            # Get existing lookup hashes
            user_data = await directus_service.get_user_fields_direct(user_id, ["lookup_hashes"])
            existing_hashes = user_data.get("lookup_hashes", []) if user_data else []
            
            if not isinstance(existing_hashes, list):
                existing_hashes = []
            
            # Add new lookup hash if not already present
            if password_request.lookup_hash not in existing_hashes:
                existing_hashes.append(password_request.lookup_hash)
                
                # Update the user record with new lookup hashes
                await directus_service.update_user(user_id, {"lookup_hashes": existing_hashes})
                logger.info(f"[PASSWORD] Added lookup hash for user {user_id}")
            
        except Exception as e:
            logger.error(f"[PASSWORD] Error updating lookup hashes for user {user_id}: {e}", exc_info=True)
            # Don't fail the request - the encryption key is already stored
            # The user might need to re-add password if lookup hash update failed
        
        # Invalidate login methods cache
        login_methods_cache_key = f"login_methods:{user_id}"
        await cache_service.delete(login_methods_cache_key)
        logger.info(f"[PASSWORD] Invalidated login methods cache for user {user_id}")
        
        action = "added" if password_request.is_new_password else "changed"
        logger.info(f"[PASSWORD] Password {action} successfully for user {user_id}")
        
        return UpdatePasswordResponse(
            success=True,
            message=f"Password {action} successfully"
        )
        
    except Exception as e:
        logger.error(f"[PASSWORD] Error updating password for user {current_user.id}: {str(e)}", exc_info=True)
        return UpdatePasswordResponse(
            success=False,
            message="An error occurred while updating password. Please try again."
        )


# --- Account Status and Uncompleted Account Deletion ---
@router.get("/account-status/{account_id}", include_in_schema=False)
async def get_account_status(
    account_id: str,
    directus_service: DirectusService = Depends(get_directus_service),
):
    """
    Check if an account can be deleted without login.
    Returns can_delete_without_login: true if account is NOT completed AND has NO credits AND NO usage.
    """
    try:
        # Find user by account_id
        # Use bracket notation for filter which is more reliable for system endpoints
        params = {
            "filter[account_id][_eq]": account_id,
            "fields": "id,last_opened,signup_completed"
        }
        users = await directus_service.get_items("directus_users", params)
        
        if not users:
            raise HTTPException(status_code=404, detail="Account not found")
            
        user = users[0]
        user_id = user.get("id")
        last_opened = user.get("last_opened")
        signup_completed = user.get("signup_completed", False)

        # 1. Primary Check: signup_completed flag (Denormalized Fast Path)
        if signup_completed:
            return {
                "success": True,
                "can_delete_without_login": False,
                "account_id": account_id,
                "user_id": user_id
            }

        # 2. Fallback Check: last_opened (Heuristic Fast Path)
        # Completed means last_opened starts with '/chat/' or is a UUID
        if last_opened:
            import re
            uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
            if last_opened.startswith("/chat/") or uuid_pattern.match(last_opened):
                # Update the flag for future requests
                await directus_service.update_user(user_id, {"signup_completed": True})
                return {
                    "success": True,
                    "can_delete_without_login": False,
                    "account_id": account_id,
                    "user_id": user_id
                }
        
        # 3. Final Fallback: Usage and invoices (Thorough Parallel Path)
        # Calculate hashed user_id for zero-knowledge collections (usage, invoices)
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

        async def check_usage():
            usage_params = {
                "filter": {"user_id_hash": {"_eq": user_id_hash}},
                "limit": 1,
                "meta": "filter_count"
            }
            resp = await directus_service._make_api_request("GET", f"{directus_service.base_url}/items/usage", params=usage_params)
            if resp.status_code == 200:
                return resp.json().get("meta", {}).get("filter_count", 0) > 0
            return False

        async def check_invoices():
            payment_params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    "status": {"_eq": "completed"}
                },
                "limit": 1,
                "meta": "filter_count"
            }
            resp = await directus_service._make_api_request("GET", f"{directus_service.base_url}/items/invoices", params=payment_params)
            if resp.status_code == 200:
                return resp.json().get("meta", {}).get("filter_count", 0) > 0
            return False

        # Run checks in parallel
        import asyncio
        has_usage, has_credits = await asyncio.gather(check_usage(), check_invoices())
        
        # If any thorough check passes, the account is completed
        if has_usage or has_credits:
            # Update the flag to avoid these expensive checks next time
            await directus_service.update_user(user_id, {"signup_completed": True})
            return {
                "success": True,
                "can_delete_without_login": False,
                "account_id": account_id,
                "user_id": user_id
            }
        
        return {
            "success": True,
            "can_delete_without_login": True,
            "account_id": account_id,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking account status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/delete-uncompleted-account/{account_id}", include_in_schema=False)
async def delete_uncompleted_account(
    account_id: str,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Delete an uncompleted account without requiring login.
    """
    try:
        # Re-check status for security
        status = await get_account_status(account_id, directus_service)
        
        if not status.get("can_delete_without_login"):
            raise HTTPException(status_code=403, detail="Login required to delete this account")
            
        user_id = status.get("user_id")
        
        # Trigger account deletion task
        from backend.core.api.app.tasks.celery_config import app as celery_app
        celery_app.send_task(
            "delete_user_account",
            kwargs={"user_id": user_id},
            queue="user_init"
        )
        
        logger.info(f"Triggered deletion for uncompleted account: {account_id} (user_id: {user_id})")
        
        return {
            "success": True,
            "message": "Account deletion scheduled successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting uncompleted account: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
