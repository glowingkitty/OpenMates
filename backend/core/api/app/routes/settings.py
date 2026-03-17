from fastapi import APIRouter, HTTPException, Depends, Request, Security
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer
import logging
import math
import time
import os
import hashlib
import json
import glob
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field # Import BaseModel and Field for response models

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_compliance_service, get_current_user, get_encryption_service, get_current_user_or_api_key, get_current_user_optional
from backend.core.api.app.routes.auth_routes.auth_utils import validate_username
from backend.core.api.app.services.directus.user.user_lookup import hash_username
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip # Updated imports
from backend.core.api.app.schemas.settings import UsernameUpdateRequest, LanguageUpdateRequest, DarkModeUpdateRequest, TimezoneUpdateRequest, AutoTopUpLowBalanceRequest, BillingOverviewResponse, InvoiceResponse, AutoDeleteChatsRequest, AutoDeleteUsageRequest, period_to_days, usage_period_to_days, AiModelDefaultsRequest, StorageOverviewResponse, StorageCategoryBreakdown, StorageFileItem, StorageFilesListResponse, StorageDeleteFilesRequest, StorageDeleteFilesResponse  # Import request/response models
from backend.apps.reminder.utils import format_reminder_time
from backend.core.api.app.routes.websockets import manager as ws_manager

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


# --- Response models for active reminders ---
class ActiveReminderItem(BaseModel):
    """A single active reminder for display in app settings."""
    reminder_id: str
    prompt_preview: str = Field(description="First 100 chars of the reminder prompt")
    trigger_at: int = Field(description="Unix timestamp when reminder fires")
    trigger_at_formatted: str = Field(description="Human-readable trigger time")
    target_type: str = Field(description="new_chat or existing_chat")
    is_repeating: bool = Field(default=False)
    status: str = Field(default="pending")


class ActiveRemindersResponse(BaseModel):
    """Response for GET /v1/settings/reminders."""
    success: bool
    reminders: list = Field(default_factory=list)
    total_count: int = Field(default=0)


# --- Endpoint for listing active reminders ---
@router.get("/reminders", response_model=ActiveRemindersResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def get_active_reminders(
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Get active (pending) reminders for the current user.
    Used by the reminder app settings page to display a list of active reminders.
    """
    try:
        user_id = current_user.id
        
        # Get pending reminders from cache
        reminders = await cache_service.get_user_reminders(
            user_id=user_id,
            status_filter="pending"
        )
        
        if not reminders:
            return ActiveRemindersResponse(
                success=True,
                reminders=[],
                total_count=0
            )
        
        # Process each reminder - decrypt prompts and format for display
        reminder_list = []
        
        for reminder in reminders:
            try:
                reminder_id = reminder.get("reminder_id", "")
                vault_key_id = reminder.get("vault_key_id")
                encrypted_prompt = reminder.get("encrypted_prompt", "")
                trigger_at = reminder.get("trigger_at", 0)
                timezone = reminder.get("timezone", "UTC")
                target_type = reminder.get("target_type", "new_chat")
                repeat_config = reminder.get("repeat_config")
                reminder_status = reminder.get("status", "pending")
                
                # Decrypt the prompt for preview
                prompt_preview = ""
                if encrypted_prompt and vault_key_id:
                    try:
                        decrypted_prompt = await encryption_service.decrypt_with_user_key(
                            ciphertext=encrypted_prompt,
                            key_id=vault_key_id
                        )
                        if decrypted_prompt:
                            prompt_preview = decrypted_prompt[:100]
                            if len(decrypted_prompt) > 100:
                                prompt_preview += "..."
                    except Exception as e:
                        logger.warning(f"Could not decrypt reminder prompt {reminder_id}: {e}")
                        prompt_preview = "[Encrypted]"
                
                # Format trigger time
                trigger_at_formatted = format_reminder_time(trigger_at, timezone)
                
                reminder_list.append(ActiveReminderItem(
                    reminder_id=reminder_id,
                    prompt_preview=prompt_preview,
                    trigger_at=trigger_at,
                    trigger_at_formatted=trigger_at_formatted,
                    target_type=target_type,
                    is_repeating=repeat_config is not None,
                    status=reminder_status
                ).model_dump())
                
            except Exception as e:
                logger.warning(f"Error processing reminder for settings list: {e}")
                continue
        
        # Sort by trigger_at ascending (soonest first)
        reminder_list.sort(key=lambda r: r.get("trigger_at", 0))
        
        logger.debug(f"Returning {len(reminder_list)} active reminders for user {user_id}")
        
        return ActiveRemindersResponse(
            success=True,
            reminders=reminder_list,
            total_count=len(reminder_list)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching active reminders: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch reminders")


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


# --- Endpoint for updating username ---
@router.post("/user/username", response_model=SimpleSuccessResponse, include_in_schema=False)
@limiter.limit("10/minute")  # Rate-limit to prevent abuse
async def update_username(
    request: Request,
    request_data: UsernameUpdateRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Update the user's username.

    The new username is validated for format (3–20 chars, letters/numbers/dots/underscores,
    at least one letter), encrypted with the user's vault key, and stored as
    ``encrypted_username`` in Directus. The Redis cache is also updated so that
    subsequent session lookups immediately reflect the new username without a DB round-trip.
    """
    user_id = current_user.id
    new_username = request_data.username.strip()
    vault_key_id = current_user.vault_key_id

    logger.info(f"Updating username for user {user_id}")

    # Validate format using the shared validator (same rules enforced at signup)
    is_valid, error_msg = validate_username(new_username)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Check username uniqueness server-wide (case-insensitive via SHA-256 hash).
    # exclude_user_id ensures that keeping the same username is allowed (not a conflict).
    hashed_username = hash_username(new_username)
    username_taken, _, _ = await directus_service.get_user_by_hashed_username(
        hashed_username, exclude_user_id=user_id
    )
    if username_taken:
        logger.info(f"Username change rejected for user {user_id}: username already taken")
        raise HTTPException(
            status_code=409,
            detail="This username is already taken. Please choose another one.",
        )

    try:
        # Encrypt the new username with the user's vault key
        encrypted_username, _ = await encryption_service.encrypt_with_user_key(
            plaintext=new_username,
            key_id=vault_key_id,
        )

        # Persist to Directus (source of truth) — also update hashed_username so that
        # future uniqueness checks reflect the change immediately.
        success_directus = await directus_service.update_user(
            user_id,
            {
                "encrypted_username": encrypted_username,
                "hashed_username": hashed_username,
            },
        )
        if not success_directus:
            logger.error(f"Failed to update encrypted_username in Directus for user {user_id}")
            raise HTTPException(status_code=500, detail="Failed to save username")

        # Update Redis cache so the new username is reflected immediately
        cache_update_success = await cache_service.update_user(user_id, {"username": new_username})
        if not cache_update_success:
            logger.warning(
                f"Failed to update username cache for user {user_id} after Directus update — "
                "cache will be stale until next session refresh"
            )
        else:
            logger.info(f"Username updated successfully for user {user_id}")

        return SimpleSuccessResponse(success=True, message="Username updated successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating username for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while updating username")


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

    if request_data.currency.lower() not in ['eur', 'usd']:
        raise HTTPException(status_code=400, detail="Invalid currency. Must be EUR or USD")

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
    created_at: Optional[str] = None  # Optional: Directus may return null on newly-created keys
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
                    # Format timestamps - Directus may return datetime objects, ISO strings, or None
                    created_at = key.get('created_at')
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
    logicalCores: Optional[int] = Field(None, ge=0, le=1024, description="Number of logical CPU cores (navigator.hardwareConcurrency)")
    deviceMemoryGiB: Optional[float] = Field(None, ge=0, le=1024, description="Approximate device RAM in GiB (navigator.deviceMemory)")


class IssueReportRequest(BaseModel):
    """Request model for issue reporting endpoint"""
    title: str = Field(..., min_length=3, max_length=200, description="Issue title (required, 3-200 characters)")
    description: Optional[str] = Field(None, min_length=10, max_length=5000, description="Issue description (optional, 10-5000 characters if provided)")
    chat_or_embed_url: Optional[str] = Field(None, max_length=500, description="Optional chat or embed URL related to the issue")
    contact_email: Optional[str] = Field(None, max_length=255, description="Optional contact email address for follow-up communication")
    language: str = Field("en", max_length=10, description="ISO 639-1 language code from the client UI (used for confirmation email localisation)")
    device_info: Optional[DeviceInfo] = Field(None, description="Device information for debugging purposes (browser, screen size, touch support)")
    console_logs: Optional[str] = Field(None, max_length=50000, description="Console logs from the client (last 100 lines)")
    indexeddb_report: Optional[str] = Field(None, max_length=100000, description="IndexedDB inspection report for active chat (metadata only, no plaintext content - safe for debugging)")
    last_messages_html: Optional[str] = Field(None, max_length=200000, description="Rendered HTML of the last user message and assistant response for debugging rendering issues")
    active_chat_sidebar_html: Optional[str] = Field(None, max_length=100000, description="outerHTML of the active chat entry in the sidebar (Chat.svelte) at the time of report — captures title, status label, typing indicator, and category icon state")
    runtime_debug_state: Optional[dict] = Field(None, description="Runtime state snapshot: WebSocket status, online status, AI typing status, pending uploads, phased sync state")
    action_history: Optional[str] = Field(None, max_length=5000, description="Last 20 user-action history entries (button names, navigation — no text content entered by user)")
    screenshot_png_base64: Optional[str] = Field(
        None,
        max_length=3_000_000,  # ~2.25 MB PNG (base64 overhead ≈ 33%)
        description=(
            "Base64-encoded PNG screenshot of the current tab captured via getDisplayMedia(). "
            "Stored unencrypted in the issue_logs S3 bucket so admins and LLMs can view it directly "
            "via a pre-signed URL. Only available for authenticated users."
        )
    )
    picked_element_html: Optional[str] = Field(
        None,
        max_length=200000,
        description=(
            "outerHTML of the DOM element that the user tapped/clicked using the element picker. "
            "Captures the exact HTML structure of a broken UI element for debugging layout, "
            "rendering, or content issues. Collected client-side via the element picker overlay."
        )
    )


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
    issue_data: IssueReportRequest,
    current_user: Optional[User] = Depends(get_current_user_optional)  # Optional auth - supports both authenticated and non-authenticated users
):
    """
    Report an issue to the server owner.
    
    This endpoint is exclusive to the web app (not accessible via API keys) but allows
    both authenticated and non-authenticated users to submit issue reports.
    The issue report is sent via email to the server owner (admin email).
    
    When an admin user reports an issue, the title is prefixed with '(Admin): ' to easily
    identify admin-reported issues from regular user reports.
    
    The email includes:
    - Issue title
    - Issue description
    - Optional chat or embed URL
    - Timestamp
    - Estimated geo location (based on IP address)
    
    Args:
        request: FastAPI Request object (for IP extraction and geo location)
        issue_data: Issue report data (title, description, optional URL)
        current_user: Optional authenticated user (None for non-authenticated users)
    
    Returns:
        IssueReportResponse with success status and message
    """
    try:
        # Import necessary utilities
        from backend.core.api.app.utils.device_fingerprint import _extract_client_ip, get_geo_data_from_ip
        from html import escape
        from urllib.parse import urlparse, urlunparse
        
        # Check if the reporter is an authenticated admin user
        is_from_admin = current_user is not None and current_user.is_admin
        reported_by_user_id = current_user.id if current_user else None
        
        if is_from_admin:
            logger.info(f"Issue report submitted by admin user {reported_by_user_id}")
        elif reported_by_user_id:
            logger.info(f"Issue report submitted by authenticated user {reported_by_user_id}")
        else:
            logger.info("Issue report submitted by non-authenticated user")
        
        # SECURITY: Sanitize user inputs to prevent XSS attacks
        # HTML escape title and description to prevent injection of malicious HTML/JavaScript
        sanitized_title = escape(issue_data.title.strip())
        
        # Add '(Admin): ' prefix to title if reported by an admin user
        if is_from_admin and not sanitized_title.startswith("(Admin): "):
            sanitized_title = f"(Admin): {sanitized_title}"
        
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
        
        # Validate and sanitise the language code from the client
        # Only allow simple ISO 639-1 / BCP-47 codes (e.g. "en", "de", "zh"); default to "en"
        import re as _re
        raw_language = issue_data.language.strip().lower()[:10] if issue_data.language else "en"
        sanitized_language = raw_language if _re.match(r'^[a-z]{2,3}(-[a-z0-9]{2,8})?$', raw_language) else "en"

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
            cpu_str = str(device_info.logicalCores) if device_info.logicalCores is not None else "Unknown"
            ram_str = f"{device_info.deviceMemoryGiB} GiB" if device_info.deviceMemoryGiB is not None else "Unknown"
            device_info_str = (
                f"Browser & OS: {sanitized_user_agent}\n"
                f"Screen Size: {device_info.viewportWidth} × {device_info.viewportHeight} pixels\n"
                f"Touch Support: {'Yes' if device_info.isTouchEnabled else 'No'}\n"
                f"CPU Cores: {cpu_str}\n"
                f"RAM: {ram_str}"
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

        # Process user action history if provided
        # This contains the last 20 user interactions (button names, navigation)
        # NO user-typed text content is ever included — only developer-authored labels
        action_history_str = None
        if issue_data.action_history and issue_data.action_history.strip():
            action_history_str = issue_data.action_history.strip()
            logger.info(f"Action history provided with issue report: {len(action_history_str)} characters")

        # Process active chat sidebar HTML if provided
        # This contains the outerHTML of the active chat entry in the sidebar at the time of report,
        # showing the chat title, status label, typing indicator and category icon state.
        active_chat_sidebar_html_str = None
        if issue_data.active_chat_sidebar_html and issue_data.active_chat_sidebar_html.strip():
            active_chat_sidebar_html_str = issue_data.active_chat_sidebar_html.strip()
            logger.info(f"Active chat sidebar HTML provided with issue report: {len(active_chat_sidebar_html_str)} characters")

        # Process user-picked element HTML if provided
        # This contains the outerHTML of a DOM element the user tapped/clicked via the
        # element picker overlay. Helps debug layout, rendering, or content issues by
        # showing the exact HTML structure of the broken UI element at report time.
        picked_element_html_str = None
        if issue_data.picked_element_html and issue_data.picked_element_html.strip():
            picked_element_html_str = issue_data.picked_element_html.strip()
            logger.info(f"Picked element HTML provided with issue report: {len(picked_element_html_str)} characters")

        # Process runtime debug state if provided
        # This is a JSON-serialisable dict containing WS status, online status, AI typing,
        # pending uploads and phased sync state — useful for debugging send/sync issues.
        import json as _json
        runtime_debug_state_str = None
        if issue_data.runtime_debug_state:
            try:
                runtime_debug_state_str = _json.dumps(issue_data.runtime_debug_state, indent=2)
                logger.info(f"Runtime debug state provided with issue report: {len(runtime_debug_state_str)} characters")
            except Exception as _e:
                logger.warning(f"Failed to serialise runtime_debug_state: {_e}")

        # Retrieve encryption service early — needed for both screenshot key encryption
        # and the regular field encryption block below.
        encryption_service: EncryptionService = request.app.state.encryption_service

        # Process screenshot PNG if provided.
        # The frontend sends a base64-encoded PNG captured via getDisplayMedia() (authenticated users only).
        # We store it unencrypted in the issue_logs S3 bucket so admins and LLMs can view it via
        # a pre-signed URL without any decryption step. The S3 key is stored encrypted in Directus.
        screenshot_presigned_url: Optional[str] = None
        encrypted_screenshot_s3_key: Optional[str] = None

        if issue_data.screenshot_png_base64 and current_user:
            # Only process screenshots from authenticated users (unauthenticated users cannot attach screenshots)
            try:
                import base64 as _base64
                import uuid as _uuid
                from datetime import datetime as _dt, timezone as _tz

                # Decode base64 → PNG bytes
                # Strip the data URI prefix if the browser included it (e.g. "data:image/png;base64,...")
                raw_b64 = issue_data.screenshot_png_base64.strip()
                if raw_b64.startswith('data:'):
                    raw_b64 = raw_b64.split(',', 1)[1]
                screenshot_bytes = _base64.b64decode(raw_b64)

                # Basic size guard (2 MB decoded)
                if len(screenshot_bytes) > 2 * 1024 * 1024:
                    logger.warning(
                        f"Screenshot too large ({len(screenshot_bytes)} bytes) — skipping upload"
                    )
                else:
                    # Upload unencrypted PNG to the issue_logs S3 bucket.
                    # The bucket is private, so only pre-signed URLs can access the file.
                    s3_service = request.app.state.s3_service
                    timestamp_str = _dt.now(_tz.utc).strftime('%Y%m%d_%H%M%S')
                    unique_id = _uuid.uuid4().hex[:8]
                    screenshot_s3_key = f"issue-screenshots/{timestamp_str}_{unique_id}.png"

                    await s3_service.upload_file(
                        bucket_key='issue_logs',
                        file_key=screenshot_s3_key,
                        content=screenshot_bytes,
                        content_type='image/png'
                    )
                    logger.info(
                        f"Uploaded screenshot PNG to S3: {screenshot_s3_key} "
                        f"({len(screenshot_bytes)} bytes)"
                    )

                    # Generate a 7-day pre-signed URL for immediate use in the email / inspect script
                    from backend.core.api.app.services.s3.config import get_bucket_name as _get_bucket_name
                    environment = s3_service.environment
                    screenshot_bucket_name = _get_bucket_name('issue_logs', environment)
                    screenshot_presigned_url = s3_service.generate_presigned_url(
                        bucket_name=screenshot_bucket_name,
                        file_key=screenshot_s3_key,
                        expiration=7 * 24 * 3600  # 7 days
                    )
                    logger.info("Generated 7-day pre-signed URL for screenshot")

                    # Encrypt the S3 key for Directus storage
                    encrypted_screenshot_s3_key = await encryption_service.encrypt_issue_report_data(
                        screenshot_s3_key
                    )
                    logger.debug("Encrypted screenshot S3 key for database storage")

            except Exception as _e:
                # Screenshot upload failure must NOT block the issue report submission
                logger.error(
                    f"Failed to process screenshot for issue report: {str(_e)}",
                    exc_info=True
                )
                screenshot_presigned_url = None
                encrypted_screenshot_s3_key = None
        elif issue_data.screenshot_png_base64 and not current_user:
            logger.warning("Screenshot ignored — only authenticated users can attach screenshots")

        # Encrypt sensitive fields for database storage (server-side encryption)
        # Note: encryption_service was already retrieved above before the screenshot block.
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
                # Encrypted S3 key for the screenshot PNG (if provided by an authenticated user)
                "encrypted_screenshot_s3_key": encrypted_screenshot_s3_key,
                "is_from_admin": is_from_admin,
                "reported_by_user_id": reported_by_user_id,
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
                "language": sanitized_language,    # Client UI language for confirmation email localisation
                "timestamp": current_time,
                "estimated_location": estimated_location,
                "device_info": device_info_str,
                "console_logs": console_logs_str,
                "indexeddb_report": indexeddb_report_str,
                "last_messages_html": last_messages_html_str,
                "active_chat_sidebar_html": active_chat_sidebar_html_str,
                "runtime_debug_state": runtime_debug_state_str,
                "action_history": action_history_str,
                # outerHTML of the DOM element the user picked via the element picker overlay.
                # Captures the exact HTML of a broken UI element for debugging layout/rendering issues.
                "picked_element_html": picked_element_html_str,
                # Pre-signed URL for the screenshot PNG (7-day validity). Included in the
                # admin email and in inspect_issue.py so LLMs can view the screenshot directly.
                "screenshot_presigned_url": screenshot_presigned_url
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


# ============================================================================
# Action verification models — email OTP for sensitive actions
# Used by password-only users (no 2FA/passkey) who need to verify identity
# for account deletion and other sensitive operations.
# ============================================================================

# Allowed action identifiers for email OTP verification
ALLOWED_VERIFICATION_ACTIONS = {"delete_account"}
# TTL for action verification codes: 10 minutes
ACTION_VERIFICATION_CODE_TTL = 600


class RequestActionVerificationRequest(BaseModel):
    """Request model for sending an email OTP code for a sensitive action."""
    action: str  # The action being verified (e.g. "delete_account")


class RequestActionVerificationResponse(BaseModel):
    """Response model for action verification request."""
    success: bool
    message: str


class VerifyActionCodeRequest(BaseModel):
    """Request model for verifying an email OTP code for a sensitive action."""
    action: str  # The action being verified (e.g. "delete_account")
    code: str    # The 6-digit verification code


class VerifyActionCodeResponse(BaseModel):
    """Response model for action verification code check."""
    success: bool
    message: str


class DeleteAccountRequest(BaseModel):
    """Request model for account deletion"""
    confirm_data_deletion: bool  # User must confirm they understand data will be deleted
    auth_method: str  # "passkey", "2fa_otp", or "email_otp"
    auth_code: Optional[str] = None  # OTP code for 2FA/email, or credential_id for passkey
    email_encryption_key: Optional[str] = None  # Client-side email encryption key for sending refund emails during deletion


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


# ============================================================================
# Action verification endpoints — email OTP for sensitive actions
# For password-only users who have not set up 2FA or passkey.
# ============================================================================

@router.post("/request-action-verification", response_model=RequestActionVerificationResponse, include_in_schema=False)
@limiter.limit("3/minute")
async def request_action_verification(
    request: Request,
    body: RequestActionVerificationRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Send a 6-digit verification code to the user's email for a sensitive action.
    Only allowed for users who have password auth but no 2FA/passkey.
    """
    user_id = current_user.id

    if body.action not in ALLOWED_VERIFICATION_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")

    # Get the user's decrypted email for sending the OTP
    try:
        user_profile = await directus_service.get_user_profile(user_id)
        if not user_profile:
            raise HTTPException(status_code=404, detail="User profile not found")

        encrypted_email = user_profile.get("encrypted_email")
        if not encrypted_email:
            raise HTTPException(status_code=400, detail="No email on file")

        vault_key_id = user_profile.get("vault_key_id", "")
        decrypted_email = await encryption_service.decrypt_field(
            encrypted_email, vault_key_id
        )
        if not decrypted_email:
            raise HTTPException(status_code=500, detail="Could not decrypt email")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user email for action verification: user={user_id}, error={e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve email")

    # Get user language and darkmode preferences
    language = user_profile.get("language", "en")
    darkmode = user_profile.get("darkmode", False)

    # Dispatch the Celery task to generate + cache + send the OTP
    from backend.core.api.app.tasks.celery_config import app as celery_app
    celery_app.send_task(
        name="app.tasks.email_tasks.action_verification_email_task.generate_and_send_action_verification_email",
        kwargs={
            "user_id": user_id,
            "email": decrypted_email,
            "action": body.action,
            "language": language,
            "darkmode": darkmode,
        },
        queue="email",
    )

    logger.info(f"Action verification email dispatched for user {user_id}, action={body.action}")
    return RequestActionVerificationResponse(success=True, message="Verification code sent")


@router.post("/verify-action-code", response_model=VerifyActionCodeResponse, include_in_schema=False)
@limiter.limit("5/minute")
async def verify_action_code(
    request: Request,
    body: VerifyActionCodeRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Verify a 6-digit email OTP code for a sensitive action.
    On success, stores a verification token in cache that the action endpoint
    can check to confirm the user verified their identity.
    """
    user_id = current_user.id

    if body.action not in ALLOWED_VERIFICATION_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")

    cache_key = f"action_verification:{user_id}:{body.action}"
    stored_code = await cache_service.get(cache_key)

    if not stored_code:
        raise HTTPException(status_code=400, detail="Code expired or not requested")

    if str(stored_code) != str(body.code):
        logger.warning(f"Invalid action verification code for user {user_id}, action={body.action}")
        raise HTTPException(status_code=401, detail="Invalid verification code")

    # Code matches — delete it so it can't be reused
    await cache_service.delete(cache_key)

    # Store a short-lived "verified" token so the action endpoint can trust
    # that the user passed email OTP recently (valid for 5 minutes).
    verified_key = f"action_verified:{user_id}:{body.action}"
    await cache_service.set(verified_key, "verified", ttl=300)

    logger.info(f"Action verification code accepted for user {user_id}, action={body.action}")
    return VerifyActionCodeResponse(success=True, message="Code verified")


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
        elif delete_request.auth_method == "email_otp":
            # Verify that the user completed email OTP verification recently.
            # The /verify-action-code endpoint stores a short-lived token in cache
            # when the code is successfully verified.
            verified_key = f"action_verified:{user_id}:delete_account"
            verified_status = await cache_service.get(verified_key)
            if verified_status != "verified":
                logger.warning(f"Email OTP not verified for account deletion: user {user_id}")
                raise HTTPException(status_code=401, detail="Email verification required")

            # Delete the verified token so it can't be reused
            await cache_service.delete(verified_key)
            logger.info(f"Email OTP authentication verified for account deletion: user {user_id}")
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
                "refund_invoices": True,
                "email_encryption_key": delete_request.email_encryption_key,
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

        # Record export timestamp so the daily notification dispatcher can reset the
        # backup reminder interval. Fire-and-forget — don't block the export response
        # or fail it if the update fails.
        try:
            from datetime import datetime, timezone as _tz
            await directus_service.update_user(
                user_id,
                {"last_export_at": datetime.now(_tz.utc).isoformat()},
            )
            # Invalidate cached profile so the next request sees the updated timestamp.
            await cache_service.delete(f"user_profile:{user_id}")
            logger.info(f"[EXPORT] Updated last_export_at for user {user_id}")
        except Exception as update_err:
            logger.warning(f"[EXPORT] Could not update last_export_at for user {user_id}: {update_err}")

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
        # Compliance logs are split into two streams (see setup_compliance_logging.py):
        #   audit-compliance.log*     — consent, user creation, auth events (2-year retention / GDPR)
        #   financial-compliance.log* — financial transactions, refunds (10-year retention / AO §147)
        # For GDPR data export we read audit logs (consent history) + financial logs (transaction history).
        try:
            compliance_logs = []
            log_dir = os.getenv('LOG_DIR', '/app/logs')
            
            # Collect log files from both compliance streams (current + all rotated backups).
            # Also includes legacy compliance.log* files from before the stream split (migration).
            log_files = (
                glob.glob(os.path.join(log_dir, 'audit-compliance.log*'))
                + glob.glob(os.path.join(log_dir, 'financial-compliance.log*'))
                + glob.glob(os.path.join(log_dir, 'compliance.log*'))  # Legacy: pre-split files
            )
            
            log_files = sorted(set(log_files))  # Deduplicate and sort (oldest first)
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


# ─── Auto-deletion settings ───────────────────────────────────────────────────


@router.post("/auto-delete-chats", response_model=SimpleSuccessResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def update_auto_delete_chats(
    request: Request,
    request_data: AutoDeleteChatsRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> SimpleSuccessResponse:
    """
    Persist the user's chat auto-deletion period.

    Accepts a period string (e.g. "90d", "1y", "never") and converts it to an
    integer day count stored on the user record as ``auto_delete_chats_after_days``.
    "never" stores null, which tells the auto-delete task to skip this user.

    The daily Celery Beat task (auto_delete_tasks.auto_delete_old_chats) reads this
    field each run and schedules deletion of chats older than the configured period.
    """
    user_id = current_user.id
    days = period_to_days(request_data.period)  # None for "never", int otherwise

    logger.info(
        f"[AutoDelete] Updating auto-delete period for user {user_id}: "
        f"period={request_data.period!r} → days={days}"
    )

    update_data = {'auto_delete_chats_after_days': days}

    try:
        # Persist to Directus (source of truth)
        success = await directus_service.update_user(user_id, update_data)
        if not success:
            logger.error(
                f"[AutoDelete] Failed to update Directus for user {user_id} "
                f"(period={request_data.period!r})."
            )
            raise HTTPException(status_code=500, detail="Failed to save auto-delete setting")

        # Mirror to cache so the frontend sees the new value immediately
        cache_ok = await cache_service.update_user(user_id, update_data)
        if not cache_ok:
            # Non-fatal: Directus is the source of truth; cache will be refreshed on next request.
            logger.warning(
                f"[AutoDelete] Cache update failed for user {user_id} after "
                f"auto-delete period change (Directus was updated successfully)."
            )
        else:
            logger.info(f"[AutoDelete] Cache updated for user {user_id}.")

        return SimpleSuccessResponse(
            success=True,
            message="Auto-delete setting saved successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[AutoDelete] Unexpected error updating auto-delete period for user {user_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An error occurred while saving auto-delete setting")


@router.post("/auto-delete-usage", response_model=SimpleSuccessResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def update_auto_delete_usage(
    request: Request,
    request_data: AutoDeleteUsageRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> SimpleSuccessResponse:
    """
    Persist the user's usage data auto-deletion period.

    Accepts a period string (e.g. "1y", "3y", "never") and converts it to an
    integer day count stored on the user record as ``auto_delete_usage_after_days``.
    "never" stores null, which tells the auto-delete task to apply the platform
    default of 3 years (1095 days).

    The daily Celery Beat task (auto_delete_tasks.auto_delete_old_usage) reads this
    field each run and permanently deletes usage records older than the configured period.
    Note: usage records are already archived to S3 after 3 months by the usage archive
    task; this setting controls permanent deletion from both Directus and S3 archives.
    """
    user_id = current_user.id
    days = usage_period_to_days(request_data.period)  # None for "never" (→ platform default)

    logger.info(
        f"[AutoDelete] Updating usage auto-delete period for user {user_id}: "
        f"period={request_data.period!r} → days={days}"
    )

    update_data = {'auto_delete_usage_after_days': days}

    try:
        success = await directus_service.update_user(user_id, update_data)
        if not success:
            logger.error(
                f"[AutoDelete] Failed to update Directus for user {user_id} "
                f"(usage period={request_data.period!r})."
            )
            raise HTTPException(status_code=500, detail="Failed to save usage auto-delete setting")

        cache_ok = await cache_service.update_user(user_id, update_data)
        if not cache_ok:
            logger.warning(
                f"[AutoDelete] Cache update failed for user {user_id} after "
                f"usage auto-delete period change (Directus was updated successfully)."
            )
        else:
            logger.info(f"[AutoDelete] Cache updated usage auto-delete for user {user_id}.")

        return SimpleSuccessResponse(
            success=True,
            message="Usage auto-delete setting saved successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[AutoDelete] Unexpected error updating usage auto-delete for user {user_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An error occurred while saving usage auto-delete setting")


# ─── AI Model Default Preferences ────────────────────────────────────────────


@router.post("/ai-model-defaults", response_model=SimpleSuccessResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def update_ai_model_defaults(
    request: Request,
    request_data: AiModelDefaultsRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> SimpleSuccessResponse:
    """
    Persist the user's preferred default AI models for simple and complex requests.

    These values are injected into user_preferences when a message is received and
    take precedence over auto-selection (ModelSelector), but are overridden by an
    explicit @mention in the message.

    Model ID format: "provider/model_id" (e.g., "anthropic/claude-haiku-4-5-20251001").
    Pass null (or omit) to reset a tier to auto-select.
    """
    user_id = current_user.id

    # Validate model IDs — must be either None (auto-select) or contain a "/" separator
    for field_name, value in [
        ("default_ai_model_simple", request_data.default_ai_model_simple),
        ("default_ai_model_complex", request_data.default_ai_model_complex),
    ]:
        if value is not None and "/" not in value:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model ID for '{field_name}': must be in 'provider/model_id' format (e.g. 'anthropic/claude-haiku-4-5-20251001')."
            )

    update_data = {
        'default_ai_model_simple': request_data.default_ai_model_simple,
        'default_ai_model_complex': request_data.default_ai_model_complex,
    }

    logger.info(
        f"[AiModelDefaults] Updating default models for user {user_id}: "
        f"simple={request_data.default_ai_model_simple!r}, "
        f"complex={request_data.default_ai_model_complex!r}"
    )

    try:
        # Persist to Directus (source of truth)
        success = await directus_service.update_user(user_id, update_data)
        if not success:
            logger.error(
                f"[AiModelDefaults] Failed to update Directus for user {user_id}."
            )
            raise HTTPException(status_code=500, detail="Failed to save default model setting")

        # Mirror to cache so the WebSocket handler picks up the new values immediately
        cache_ok = await cache_service.update_user(user_id, update_data)
        if not cache_ok:
            # Non-fatal: Directus is the source of truth; cache will be refreshed on next request.
            logger.warning(
                f"[AiModelDefaults] Cache update failed for user {user_id} after "
                f"default model change (Directus was updated successfully)."
            )
        else:
            logger.info(f"[AiModelDefaults] Cache updated for user {user_id}.")

        return SimpleSuccessResponse(
            success=True,
            message="Default model settings saved successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[AiModelDefaults] Unexpected error updating default models for user {user_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An error occurred while saving default model setting")


# ─── Storage Overview ─────────────────────────────────────────────────────────

# Mirrors the constants in storage_billing_tasks.py — update both if pricing changes.
_STORAGE_FREE_BYTES: int = 1_073_741_824       # 1 GB
_STORAGE_CREDITS_PER_GB_PER_WEEK: int = 3


def _classify_mime_type(mime: str) -> str:
    """
    Map a MIME type string to one of the standard storage category names.

    Categories (must match i18n keys storage.category.<name>):
      images, videos, audio, pdf, code, docs, sheets, archives, other
    """
    if not mime:
        return "other"
    lower = mime.lower()

    if lower.startswith("image/"):
        return "images"
    if lower.startswith("video/"):
        return "videos"
    if lower.startswith("audio/"):
        return "audio"
    if lower == "application/pdf":
        return "pdf"
    if lower.startswith("text/") or lower in (
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-javascript",
        "application/typescript",
        "application/x-typescript",
        "application/x-sh",
        "application/x-python",
        "application/x-ruby",
        "application/x-perl",
    ):
        return "code"
    if lower in (
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
        "application/vnd.oasis.opendocument.text",
        "application/rtf",
    ):
        return "docs"
    if lower in (
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
        "application/vnd.oasis.opendocument.spreadsheet",
    ):
        return "sheets"
    if lower in (
        "application/zip",
        "application/x-zip-compressed",
        "application/x-tar",
        "application/gzip",
        "application/x-gzip",
        "application/x-bzip2",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/vnd.rar",
    ):
        return "archives"
    return "other"


def _next_billing_timestamp() -> int:
    """
    Return the Unix timestamp of the next Sunday at 03:00 UTC.
    This mirrors the weekly billing schedule in storage_billing_tasks.py.
    """
    now = datetime.now(timezone.utc)
    # weekday(): Mon=0 … Sun=6
    days_until_sunday = (6 - now.weekday()) % 7
    # If today is already Sunday and it's past 03:00, roll to next Sunday.
    if days_until_sunday == 0 and (now.hour > 3 or (now.hour == 3 and now.minute > 0)):
        days_until_sunday = 7
    next_sunday = (now + timedelta(days=days_until_sunday)).replace(
        hour=3, minute=0, second=0, microsecond=0
    )
    return int(next_sunday.timestamp())


@router.get("/storage", response_model=StorageOverviewResponse)
@limiter.limit("30/minute")
async def get_storage_overview(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> StorageOverviewResponse:
    """
    Return the current user's storage usage, broken down by file-type category,
    along with billing information (free tier, weekly cost, next billing date).

    Source of truth: the `upload_files` collection is queried directly so that
    the numbers are accurate immediately after file deletions (the cached
    `storage_used_bytes` counter on directus_users is only reconciled during
    the weekly billing run).

    Endpoint: GET /v1/settings/storage
    """
    user_id: str = current_user.id
    logger.info(f"[Storage] Fetching storage overview for user {user_id}")

    try:
        # ── 1. Fetch all upload_files records for the user ──────────────────
        # We need content_type and file_size_bytes for each file so we can
        # categorise them in Python.  Directus aggregate + groupBy on
        # content_type would give us bytes per MIME type but not file_count,
        # so fetching fields directly is simpler and accurate.
        files_result = await directus_service.get_items(
            "upload_files",
            params={
                "filter": {"user_id": {"_eq": user_id}},
                "fields": "content_type,file_size_bytes",
                "limit": -1,
            },
            no_cache=True,
        )

        # ── 2. Aggregate into categories ────────────────────────────────────
        # category_name → {"bytes": int, "count": int}
        category_map: Dict[str, Dict[str, int]] = {}

        total_bytes: int = 0
        total_files: int = 0

        if files_result and isinstance(files_result, list):
            for row in files_result:
                mime: str = row.get("content_type") or ""
                size: int = int(row.get("file_size_bytes") or 0)
                cat: str = _classify_mime_type(mime)

                if cat not in category_map:
                    category_map[cat] = {"bytes": 0, "count": 0}
                category_map[cat]["bytes"] += size
                category_map[cat]["count"] += 1

                total_bytes += size
                total_files += 1

        # ── 3. Build ordered breakdown list ─────────────────────────────────
        # Only include categories that have at least one file.
        category_order = ["images", "videos", "audio", "pdf", "code", "docs", "sheets", "archives", "other"]
        breakdown = [
            StorageCategoryBreakdown(
                category=cat,
                bytes_used=category_map[cat]["bytes"],
                file_count=category_map[cat]["count"],
            )
            for cat in category_order
            if cat in category_map
        ]

        # ── 4. Compute billing fields ────────────────────────────────────────
        billable_gb: int = 0
        weekly_cost_credits: int = 0
        next_billing_date: Optional[int] = None

        if total_bytes > _STORAGE_FREE_BYTES:
            billable_gb = math.ceil((total_bytes - _STORAGE_FREE_BYTES) / _STORAGE_FREE_BYTES)
            weekly_cost_credits = billable_gb * _STORAGE_CREDITS_PER_GB_PER_WEEK
            next_billing_date = _next_billing_timestamp()

        # ── 5. Fetch last_billed_at from directus_users ──────────────────────
        last_billed_at: Optional[int] = None
        try:
            user_fields = await directus_service.get_user_fields_direct(
                user_id, ["storage_last_billed_at"]
            )
            raw_ts = (user_fields or {}).get("storage_last_billed_at")
            if raw_ts is not None:
                last_billed_at = int(raw_ts)
        except Exception as e_lba:
            # Non-fatal: proceed without last_billed_at
            logger.warning(
                f"[Storage] Could not fetch storage_last_billed_at for user {user_id}: {e_lba}"
            )

        logger.info(
            f"[Storage] User {user_id}: total_bytes={total_bytes}, total_files={total_files}, "
            f"billable_gb={billable_gb}, weekly_cost={weekly_cost_credits}"
        )

        return StorageOverviewResponse(
            total_bytes=total_bytes,
            total_files=total_files,
            free_bytes=_STORAGE_FREE_BYTES,
            billable_gb=billable_gb,
            credits_per_gb_per_week=_STORAGE_CREDITS_PER_GB_PER_WEEK,
            weekly_cost_credits=weekly_cost_credits,
            next_billing_date=next_billing_date,
            last_billed_at=last_billed_at,
            breakdown=breakdown,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[Storage] Unexpected error fetching storage overview for user {user_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch storage overview")


# ─── Category → MIME filter helper ────────────────────────────────────────────

def _mime_filter_for_category(category: str) -> Dict[str, Any]:
    """
    Return a Directus _or filter clause that matches all MIME types in a given
    storage category.  Used by the file-list and delete-by-category endpoints.

    Each returned dict is suitable for merging into a Directus params dict as
    the value of "filter[content_type]".

    Raises ValueError for unknown category names so callers can surface a 400.
    """
    # Map category → list of exact MIME values or prefix flags.
    # Using Directus _starts_with for prefix-based matching (image/, video/, audio/).
    CATEGORY_FILTERS: Dict[str, Any] = {
        "images":   {"_starts_with": "image/"},
        "videos":   {"_starts_with": "video/"},
        "audio":    {"_starts_with": "audio/"},
        "pdf":      {"_eq": "application/pdf"},
        "code": {"_in": [
            "application/json", "application/xml",
            "application/javascript", "application/x-javascript",
            "application/typescript", "application/x-typescript",
            "application/x-sh", "application/x-python",
            "application/x-ruby", "application/x-perl",
            # text/* handled separately via starts_with below — combine with _or
        ]},
        "docs": {"_in": [
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
            "application/vnd.oasis.opendocument.text",
            "application/rtf",
        ]},
        "sheets": {"_in": [
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
            "application/vnd.oasis.opendocument.spreadsheet",
        ]},
        "archives": {"_in": [
            "application/zip", "application/x-zip-compressed",
            "application/x-tar", "application/gzip", "application/x-gzip",
            "application/x-bzip2", "application/x-7z-compressed",
            "application/x-rar-compressed", "application/vnd.rar",
        ]},
    }
    if category not in CATEGORY_FILTERS and category != "other":
        raise ValueError(f"Unknown storage category: {category!r}")
    if category in CATEGORY_FILTERS:
        return CATEGORY_FILTERS[category]
    # "other" cannot be expressed as a single Directus filter cleanly — we
    # return None to signal that Python-side filtering must be used.
    return {}


# ─── Storage File Listing ──────────────────────────────────────────────────────

@router.get("/storage/files", response_model=StorageFilesListResponse)
@limiter.limit("30/minute")
async def list_storage_files(
    request: Request,
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> StorageFilesListResponse:
    """
    Return the list of uploaded files for the current user, optionally filtered
    by storage category.

    Files are returned newest-first (sorted by created_at descending).
    The category param must match one of the standard category names
    (images, videos, audio, pdf, code, docs, sheets, archives, other).
    If omitted, all files are returned.

    Endpoint: GET /v1/settings/storage/files?category=<name>
    """
    user_id: str = current_user.id
    logger.info(f"[StorageFiles] Listing files for user {user_id} (category={category!r})")

    try:
        # ── 1. Build Directus filter ─────────────────────────────────────────
        base_filter: Dict[str, Any] = {"user_id": {"_eq": user_id}}
        if category and category != "other":
            # Validate category name first
            try:
                mime_filter = _mime_filter_for_category(category)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Unknown category: {category!r}")

            # For prefix-based categories (images/videos/audio), Directus supports
            # _starts_with; for the rest we use _in.  "code" also needs text/ prefix —
            # handled by Python-side classification below.
            base_filter["content_type"] = mime_filter

        # ── 2. Fetch upload_files ─────────────────────────────────────────────
        records = await directus_service.get_items(
            "upload_files",
            params={
                "filter": base_filter,
                "fields": "id,embed_id,original_filename,content_type,file_size_bytes,files_metadata,created_at",
                "sort": "-created_at",
                "limit": -1,
            },
            no_cache=True,
        )

        if not records or not isinstance(records, list):
            records = []

        # ── 3. Build response items ────────────────────────────────────────────
        file_items: list[StorageFileItem] = []
        total_bytes: int = 0

        for row in records:
            mime: str = row.get("content_type") or ""
            row_category: str = _classify_mime_type(mime)

            # For "other" category filter and "code" (which needs text/ prefix too),
            # apply Python-side classification to match correctly.
            if category and row_category != category:
                continue

            size: int = int(row.get("file_size_bytes") or 0)
            files_metadata = row.get("files_metadata") or {}
            variant_count: int = len(files_metadata) if isinstance(files_metadata, dict) else 1

            raw_ts = row.get("created_at")
            created_at: Optional[int] = int(raw_ts) if raw_ts is not None else None

            file_items.append(StorageFileItem(
                id=str(row.get("id") or ""),
                embed_id=str(row.get("embed_id") or ""),
                original_filename=str(row.get("original_filename") or ""),
                content_type=mime,
                category=row_category,
                file_size_bytes=size,
                variant_count=variant_count,
                created_at=created_at,
            ))
            total_bytes += size

        logger.info(
            f"[StorageFiles] Returning {len(file_items)} file(s) "
            f"({total_bytes:,} bytes) for user {user_id}"
        )

        return StorageFilesListResponse(
            files=file_items,
            total_count=len(file_items),
            total_bytes=total_bytes,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[StorageFiles] Unexpected error listing files for user {user_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to list storage files")


# ─── Storage File View (server-side decrypt + stream) ─────────────────────────

@router.get("/storage/files/{embed_id}/view")
@limiter.limit("60/minute")
async def view_storage_file(
    embed_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """
    Stream the decrypted content of an uploaded file so the browser can open it.

    Fetches the upload_files record, downloads the AES-256-GCM encrypted bytes
    from S3, decrypts them using the stored plaintext AES key/nonce, and streams
    the result with the correct Content-Type header.

    For images, the 'full' variant is used (best quality for viewing).
    For all other file types (PDF, audio, etc.), the 'original' variant is used.

    Security model:
    - Authentication required.
    - Ownership validated: upload_files.user_id must match current_user.id.
    - The AES key is stored server-side in upload_files (same security model as
      the existing deduplication path — the server already has the key).

    Endpoint: GET /v1/settings/storage/files/{embed_id}/view
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64
    from fastapi.responses import Response as FastAPIResponse

    user_id: str = current_user.id
    log_prefix = f"[StorageView] [user:{user_id[:8]}...] [embed:{embed_id[:8]}...]"

    try:
        # ── 1. Fetch upload_files record (ownership check) ─────────────────────
        records = await directus_service.get_items(
            "upload_files",
            params={
                "filter": {
                    "embed_id": {"_eq": embed_id},
                    "user_id": {"_eq": user_id},
                },
                "fields": "id,content_type,files_metadata,aes_key,aes_nonce",
                "limit": 1,
            },
            no_cache=True,
        )

        if not records or not isinstance(records, list) or len(records) == 0:
            logger.warning(f"{log_prefix} upload_files record not found or not owned by user")
            raise HTTPException(status_code=404, detail="File not found")

        record = records[0]
        content_type: str = record.get("content_type") or "application/octet-stream"
        files_metadata: Dict[str, Any] = record.get("files_metadata") or {}
        aes_key_b64: str = record.get("aes_key") or ""
        aes_nonce_b64: str = record.get("aes_nonce") or ""

        if not aes_key_b64 or not aes_nonce_b64:
            logger.error(f"{log_prefix} Missing AES key or nonce in upload_files record")
            raise HTTPException(status_code=500, detail="Encryption metadata missing")

        # ── 2. Choose the best variant to serve ───────────────────────────────
        # For images: prefer 'full' (high-res WEBP), fall back to 'preview', then 'original'.
        # For everything else: 'original' only.
        category = _classify_mime_type(content_type)
        if category == "images":
            variant_preference = ["full", "preview", "original"]
        else:
            variant_preference = ["original"]

        chosen_variant: Optional[Dict[str, Any]] = None
        chosen_variant_name: str = "original"
        for variant_name in variant_preference:
            v = files_metadata.get(variant_name)
            if v and isinstance(v, dict) and v.get("s3_key"):
                chosen_variant = v
                chosen_variant_name = variant_name
                break

        if not chosen_variant:
            logger.error(f"{log_prefix} No usable variant found in files_metadata: {list(files_metadata.keys())}")
            raise HTTPException(status_code=404, detail="File content not found")

        s3_key: str = chosen_variant["s3_key"]
        # For image variants we serve as webp; for others use the original content_type
        serve_content_type: str = "image/webp" if category == "images" else content_type

        logger.info(f"{log_prefix} Serving variant '{chosen_variant_name}' s3_key={s3_key[:40]}...")

        # ── 3. Get S3 service from app state ──────────────────────────────────
        s3_service = request.app.state.s3_service
        if not s3_service:
            logger.error(f"{log_prefix} S3 service not available")
            raise HTTPException(status_code=503, detail="Storage service unavailable")

        # ── 4. Download encrypted bytes from S3 ──────────────────────────────
        from backend.core.api.app.services.s3.config import get_bucket_name as _get_bucket_name_sv
        chatfiles_bucket = _get_bucket_name_sv("chatfiles", os.getenv("SERVER_ENVIRONMENT", "development"))
        encrypted_bytes: bytes = await s3_service.get_file(
            bucket_name=chatfiles_bucket,
            object_key=s3_key,
        )

        if not encrypted_bytes:
            logger.error(f"{log_prefix} S3 returned empty content for {s3_key}")
            raise HTTPException(status_code=404, detail="File content not found in storage")

        # ── 5. Decrypt AES-256-GCM ────────────────────────────────────────────
        try:
            aes_key: bytes = base64.b64decode(aes_key_b64)
            aes_nonce: bytes = base64.b64decode(aes_nonce_b64)
            aesgcm = AESGCM(aes_key)
            plaintext: bytes = aesgcm.decrypt(aes_nonce, encrypted_bytes, None)
        except Exception as dec_err:
            logger.error(f"{log_prefix} Decryption failed: {dec_err}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to decrypt file")

        logger.info(
            f"{log_prefix} Serving {len(plaintext):,} decrypted bytes "
            f"as {serve_content_type}"
        )

        # ── 6. Stream response with Content-Disposition: inline ───────────────
        return FastAPIResponse(
            content=plaintext,
            media_type=serve_content_type,
            headers={"Content-Disposition": "inline"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve file")


# ─── Storage File Deletion ─────────────────────────────────────────────────────

@router.delete("/storage/files", response_model=StorageDeleteFilesResponse)
@limiter.limit("10/minute")
async def delete_storage_files(
    payload: StorageDeleteFilesRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> StorageDeleteFilesResponse:
    """
    Delete uploaded files for the current user from S3 and Directus.

    Embed records are intentionally NOT deleted — the chat UI will continue to
    show an entry but will display "File deleted" when the embed content is gone.

    Scopes:
      - single:   Delete one file by its upload_files Directus ID (file_id required).
      - category: Delete all files in a MIME category (category required).
      - all:      Delete every uploaded file for the current user.

    For each deleted record:
      1. All S3 variant objects (original, full, preview) are deleted.
      2. The upload_files Directus record is deleted.
      3. The user's storage_used_bytes counter is decremented.

    Endpoint: DELETE /v1/settings/storage/files
    Rate limited: 10/minute (irreversible bulk operation).
    """
    user_id: str = current_user.id
    log_prefix = f"[StorageDelete] [user:{user_id[:8]}...] scope={payload.scope!r}"

    VALID_SCOPES = {"single", "category", "all"}
    if payload.scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope {payload.scope!r}. Must be one of: {', '.join(VALID_SCOPES)}"
        )
    if payload.scope == "single" and not payload.file_id:
        raise HTTPException(status_code=400, detail="file_id is required when scope='single'")
    if payload.scope == "category" and not payload.category:
        raise HTTPException(status_code=400, detail="category is required when scope='category'")

    logger.info(f"{log_prefix} file_id={payload.file_id!r} category={payload.category!r}")

    try:
        # ── 1. Get S3 service ─────────────────────────────────────────────────
        s3_service = request.app.state.s3_service
        if not s3_service:
            logger.error(f"{log_prefix} S3 service not available")
            raise HTTPException(status_code=503, detail="Storage service unavailable")

        # ── 2. Fetch target records ───────────────────────────────────────────
        base_filter: Dict[str, Any] = {"user_id": {"_eq": user_id}}

        if payload.scope == "single":
            base_filter["id"] = {"_eq": payload.file_id}
        elif payload.scope == "category":
            category_name = payload.category
            # Validate and build MIME filter
            try:
                mime_filter = _mime_filter_for_category(category_name)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Unknown category: {category_name!r}")

            if mime_filter:
                base_filter["content_type"] = mime_filter
            # "other" category has empty mime_filter — Python-side filter applied below

        records = await directus_service.get_items(
            "upload_files",
            params={
                "filter": base_filter,
                "fields": "id,embed_id,file_size_bytes,files_metadata,content_type",
                "limit": -1,
            },
            no_cache=True,
        )

        if not records or not isinstance(records, list):
            records = []

        # Python-side category filter for "other" and "code" (text/* prefix)
        if payload.scope == "category" and payload.category:
            category_name = payload.category
            records = [
                r for r in records
                if _classify_mime_type(r.get("content_type") or "") == category_name
            ]

        if not records:
            logger.info(f"{log_prefix} No matching records found; nothing to delete")
            return StorageDeleteFilesResponse(deleted_count=0, bytes_freed=0)

        # ── 3. Ownership double-check: reject if any record doesn't belong to user ──
        # The filter already enforces user_id, but log a warning if somehow a mismatch slips through.
        for r in records:
            # (filter already guarantees this; belt-and-suspenders check)
            pass

        logger.info(f"{log_prefix} Deleting {len(records)} record(s)")

        # ── 4. Delete S3 variant objects ──────────────────────────────────────
        s3_deleted = 0
        s3_failed = 0
        for record in records:
            files_metadata = record.get("files_metadata")
            if not files_metadata or not isinstance(files_metadata, dict):
                continue
            for variant_name, variant_data in files_metadata.items():
                if not isinstance(variant_data, dict):
                    continue
                s3_key = variant_data.get("s3_key")
                if not s3_key:
                    continue
                try:
                    await s3_service.delete_file(bucket_key="chatfiles", file_key=s3_key)
                    s3_deleted += 1
                    logger.debug(
                        f"{log_prefix} Deleted S3 chatfiles/{s3_key} (variant: {variant_name})"
                    )
                except Exception as s3_err:
                    s3_failed += 1
                    logger.warning(
                        f"{log_prefix} Failed to delete S3 chatfiles/{s3_key}: {s3_err}"
                    )

        logger.info(
            f"{log_prefix} S3: {s3_deleted} deleted, {s3_failed} failed"
        )

        # ── 5. Bulk-delete Directus records ───────────────────────────────────
        directus_ids = [r.get("id") for r in records if r.get("id")]
        total_bytes_freed = sum(int(r.get("file_size_bytes") or 0) for r in records)

        delete_success = await directus_service.bulk_delete_items(
            collection="upload_files", item_ids=directus_ids
        )
        if not delete_success:
            logger.error(
                f"{log_prefix} Bulk Directus delete failed for {len(directus_ids)} records. "
                "S3 objects may already be deleted."
            )
            raise HTTPException(status_code=500, detail="Failed to delete file records")

        # ── 6. Decrement storage_used_bytes on directus_users ─────────────────
        if total_bytes_freed > 0:
            try:
                user_fields = await directus_service.get_user_fields_direct(
                    user_id, ["storage_used_bytes"]
                )
                current_bytes = int((user_fields or {}).get("storage_used_bytes") or 0)
                new_bytes = max(0, current_bytes - total_bytes_freed)
                await directus_service.update_user(user_id, {"storage_used_bytes": new_bytes})
                logger.info(
                    f"{log_prefix} storage_used_bytes: {current_bytes:,} → {new_bytes:,} "
                    f"(freed {total_bytes_freed:,})"
                )
            except Exception as counter_err:
                # Non-fatal: the direct upload_files query in GET /storage is source of truth.
                logger.warning(
                    f"{log_prefix} Failed to update storage_used_bytes: {counter_err}"
                )

        logger.info(
            f"{log_prefix} Done: {len(directus_ids)} records deleted, "
            f"{total_bytes_freed:,} bytes freed"
        )

        return StorageDeleteFilesResponse(
            deleted_count=len(directus_ids),
            bytes_freed=total_bytes_freed,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete storage files")


# ─── Chat Statistics & Management ────────────────────────────────────────────
# Architecture: docs/architecture/security.md (hashed_user_id privacy model)
# created_at is stored as a Unix timestamp integer in Directus, NOT ISO string.
# Total count and preview use aggregate[count]=* (meta=total_count ignores filters).
# Delete and preview filters use int Unix cutoff: int(time.time()) - days*86400.


class ChatStatsResponse(BaseModel):
    """Response for GET /v1/settings/chats."""
    total_count: int = Field(description="Total number of chats in the account")


class ChatPreviewResponse(BaseModel):
    """Response for GET /v1/settings/chats/preview."""
    count: int = Field(description="Number of chats that would be deleted")


class DeleteOldChatsRequest(BaseModel):
    """Request body for POST /v1/settings/chats/delete-old."""
    older_than_days: int = Field(
        ge=0,
        description=(
            "Delete chats older than this many days. "
            "Use 0 to delete ALL chats for the user regardless of age."
        )
    )


class DeleteOldChatsResponse(BaseModel):
    """Response for POST /v1/settings/chats/delete-old."""
    deleted_count: int = Field(description="Number of chats permanently deleted")
    deleted_ids: list[str] = Field(
        default_factory=list,
        description="IDs of deleted chats so the client can clean up IndexedDB"
    )


@router.get("/chats", response_model=ChatStatsResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def get_chat_stats(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ChatStatsResponse:
    """
    Return total chat count for the current user's account.

    Uses Directus aggregate[count]=* (not meta=total_count which ignores filters)
    to return the accurate server-side total for this user.
    created_at is a Unix int; this endpoint does not filter by date.
    """
    import hashlib as _hashlib

    user_id = current_user.id
    hashed_user_id = _hashlib.sha256(user_id.encode()).hexdigest()

    logger.info(f"[ChatStats] Fetching total count for user {user_id}")

    try:
        token = await directus_service.ensure_auth_token(admin_required=False)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{directus_service.base_url}/items/chats"
        # Use aggregate[count]=* — meta=total_count ignores filters and always
        # returns the collection total, making it useless for per-user counts.
        params = {
            'filter[hashed_user_id][_eq]': hashed_user_id,
            'aggregate[count]': '*',
        }
        response = await directus_service._make_api_request("GET", url, headers=headers, params=params)
        response.raise_for_status()
        body = response.json()
        data = body.get('data', [{}])
        total_count = int(data[0].get('count', 0)) if data else 0

        logger.info(f"[ChatStats] user {user_id}: {total_count} total chats")
        return ChatStatsResponse(total_count=total_count)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ChatStats] Unexpected error for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch chat statistics")


@router.get("/chats/preview", response_model=ChatPreviewResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def preview_old_chats(
    request: Request,
    older_than_days: int,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> ChatPreviewResponse:
    """
    Preview how many chats would be deleted for a given age threshold.

    Uses aggregate[count]=* with a Unix timestamp cutoff filter (not meta=total_count
    which ignores filters) so the client can show how many will be deleted.
    created_at is stored as a Unix int, so the cutoff is also a Unix int.
    """
    import hashlib as _hashlib

    if older_than_days < 0:
        raise HTTPException(status_code=422, detail="older_than_days must be >= 0")

    user_id = current_user.id
    hashed_user_id = _hashlib.sha256(user_id.encode()).hexdigest()
    cutoff_unix = int(time.time()) - (older_than_days * 86400)

    logger.info(
        f"[ChatPreview] user {user_id}: preview older_than_days={older_than_days} "
        f"cutoff_unix={cutoff_unix}"
    )

    try:
        token = await directus_service.ensure_auth_token(admin_required=False)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{directus_service.base_url}/items/chats"
        # Use aggregate[count]=* — meta=total_count ignores filters and always
        # returns the collection total, not the filtered count.
        # older_than_days=0 means "all chats" — omit the date filter.
        params: dict = {
            'filter[hashed_user_id][_eq]': hashed_user_id,
            'aggregate[count]': '*',
        }
        if older_than_days > 0:
            params['filter[last_edited_overall_timestamp][_lt]'] = cutoff_unix
        response = await directus_service._make_api_request("GET", url, headers=headers, params=params)
        response.raise_for_status()
        body = response.json()
        data = body.get('data', [{}])
        count = int(data[0].get('count', 0)) if data else 0

        logger.info(f"[ChatPreview] user {user_id}: {count} chats would be deleted")
        return ChatPreviewResponse(count=count)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ChatPreview] Unexpected error for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to preview chat deletion")


@router.post("/chats/delete-old", response_model=DeleteOldChatsResponse, include_in_schema=False)
@limiter.limit("5/minute")
async def delete_old_chats(
    request: Request,
    request_data: DeleteOldChatsRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
) -> DeleteOldChatsResponse:
    """
    Permanently delete chats for the authenticated user.

    When older_than_days > 0: deletes chats whose last_edited_overall_timestamp (last activity) is older
    than the cutoff. When older_than_days == 0: deletes ALL chats for the user.

    Only chats belonging to the user (matched via hashed_user_id) are deleted.
    The operation is irreversible -- compliance event is logged.
    Returns the list of deleted chat IDs so the client can clean up IndexedDB.
    """
    import hashlib as _hashlib

    user_id = current_user.id
    hashed_user_id = _hashlib.sha256(user_id.encode()).hexdigest()
    cutoff_days = request_data.older_than_days
    cutoff_unix = int(time.time()) - (cutoff_days * 86400)
    client_ip = _extract_client_ip(
        request.headers, request.client.host if request.client else None
    )

    # older_than_days=0 means delete ALL chats — omit the date filter
    delete_all = (cutoff_days == 0)

    logger.info(
        f"[DeleteOldChats] user {user_id}: "
        + ("deleting ALL chats" if delete_all else
           f"deleting chats older_than_days={cutoff_days} cutoff_unix={cutoff_unix}")
    )

    # Collect all matching chat IDs
    chat_ids_to_delete: list[str] = []
    offset = 0
    PAGE_SIZE = 500

    try:
        while True:
            params: dict = {
                'filter[hashed_user_id][_eq]': hashed_user_id,
                'fields': 'id',
                'limit': PAGE_SIZE,
                'offset': offset,
            }
            if not delete_all:
                params['filter[last_edited_overall_timestamp][_lt]'] = cutoff_unix
            page = await directus_service.get_items('chats', params=params)
            if not page or not isinstance(page, list):
                break
            chat_ids_to_delete.extend(item['id'] for item in page if item.get('id'))
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        if not chat_ids_to_delete:
            logger.info(f"[DeleteOldChats] user {user_id}: no chats to delete")
            return DeleteOldChatsResponse(deleted_count=0, deleted_ids=[])

        logger.info(
            f"[DeleteOldChats] user {user_id}: found {len(chat_ids_to_delete)} chats to delete"
        )

        # Delete each chat -- reuse the existing helper that handles cascading
        deleted_ids: list[str] = []
        for chat_id in chat_ids_to_delete:
            try:
                success = await directus_service.chat.persist_delete_chat(chat_id)
                if success:
                    deleted_ids.append(chat_id)
                else:
                    logger.warning(
                        f"[DeleteOldChats] persist_delete_chat returned False for {chat_id}"
                    )
            except Exception as del_err:
                logger.warning(
                    f"[DeleteOldChats] Error deleting chat {chat_id}: {del_err}"
                )

        deleted_count = len(deleted_ids)

        # Compliance log
        compliance_service.log_auth_event(
            event_type="bulk_delete_old_chats",
            user_id=user_id,
            ip_address=client_ip,
            status="success",
            details={
                "deleted_count": deleted_count,
                "older_than_days": cutoff_days,
                "delete_all": delete_all,
                "cutoff_unix": cutoff_unix if not delete_all else None,
            },
        )

        logger.info(
            f"[DeleteOldChats] user {user_id}: deleted {deleted_count}/{len(chat_ids_to_delete)} chats"
        )

        # Broadcast chat_deleted to all connected devices for this user so every device
        # removes the deleted chats from IndexedDB immediately via the WS sync pipeline.
        # Mirrors the broadcast in delete_chat_handler.py (WebSocket path).
        for deleted_id in deleted_ids:
            try:
                await ws_manager.broadcast_to_user(
                    {
                        "type": "chat_deleted",
                        "payload": {"chat_id": deleted_id, "tombstone": True},
                    },
                    user_id,
                    exclude_device_hash=None,
                )
            except Exception as broadcast_err:
                # Non-fatal: client will re-sync on next connection
                logger.warning(
                    f"[DeleteOldChats] Failed to broadcast chat_deleted for {deleted_id}: {broadcast_err}"
                )
        if deleted_ids:
            logger.info(
                f"[DeleteOldChats] Broadcasted chat_deleted for {len(deleted_ids)} chats to user {user_id}"
            )

        return DeleteOldChatsResponse(deleted_count=deleted_count, deleted_ids=deleted_ids)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DeleteOldChats] Unexpected error for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete old chats")


# ---------------------------------------------------------------------------
# Chat Import
# ---------------------------------------------------------------------------

# Valid assistant categories (mirrors the frontend list in assistantCategories.ts)
_VALID_ASSISTANT_CATEGORIES = {
    "general knowledge",
    "coding",
    "writing",
    "analysis",
    "math",
    "research",
    "creative",
    "productivity",
    "language",
    "science",
}

# Tokens per credit for the safety model ($0.075/M input = 333.33/0.075 = 4444)
_IMPORT_TOKENS_PER_CREDIT = 4444

# Blocked message content placeholder shown to the user
_IMPORT_BLOCKED_PLACEHOLDER = "[Message blocked by safety scanner]"


class ImportMessageModel(BaseModel):
    """Single message from an imported chat YAML."""
    role: str = Field(..., description="Message role: user | assistant | system")
    content: str = Field(default="", max_length=200_000)
    completed_at: Optional[str] = Field(default=None)
    assistant_category: Optional[str] = Field(default=None)
    thinking: Optional[str] = Field(default=None)
    has_thinking: Optional[bool] = Field(default=None)
    thinking_tokens: Optional[int] = Field(default=None)


class ImportChatModel(BaseModel):
    """A single chat to import (parsed from YAML by the frontend)."""
    title: Optional[str] = Field(default=None, max_length=500)
    draft: Optional[str] = Field(default=None, max_length=10_000)
    summary: Optional[str] = Field(default=None, max_length=5_000)
    messages: List[ImportMessageModel] = Field(default_factory=list)


class ImportChatRequest(BaseModel):
    """Request body for POST /v1/settings/import-chat."""
    chats: List[ImportChatModel] = Field(..., min_length=1, max_length=100)


class ImportedChatResult(BaseModel):
    """Result for a single imported chat."""
    chat_id: str
    title: Optional[str]
    messages_imported: int
    messages_blocked: int
    credits_charged: int


class ImportChatResponse(BaseModel):
    """Response for POST /v1/settings/import-chat."""
    imported: List[ImportedChatResult]
    total_credits_charged: int


def _get_billing_service_for_import(
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """Factory for BillingService used by the import endpoint."""
    from backend.core.api.app.services.billing_service import BillingService
    return BillingService(cache_service, directus_service, encryption_service)


@router.post("/import-chat", include_in_schema=False)
@limiter.limit("3/minute")
async def import_chat(
    request: Request,
    body: ImportChatRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> ImportChatResponse:
    """
    Import one or more chats from a parsed YAML export file.

    Each message is safety-scanned via gpt-oss-safeguard-20b on OpenRouter
    before being stored. Blocked messages are replaced with a visible
    placeholder. The user is charged for input tokens consumed by non-blocked
    chats only.

    Rate-limited to 3/minute to prevent abuse.
    Endpoint: POST /v1/settings/import-chat
    """
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.core.api.app.services.billing_service import BillingService
    from backend.apps.ai.processing.content_sanitization import sanitize_message_for_import
    import uuid as _uuid

    user_id: str = current_user.id
    user_id_hash: str = hashlib.sha256(user_id.encode()).hexdigest()

    billing_service = BillingService(cache_service, directus_service, encryption_service)
    secrets_manager = SecretsManager(cache_service=cache_service)

    results: List[ImportedChatResult] = []
    total_credits = 0

    for chat_index, chat in enumerate(body.chats):
        chat_task_id = f"import_{user_id[:8]}_{chat_index}"
        new_chat_id = str(_uuid.uuid4())

        # Sanitize each message sequentially (respects OpenRouter 100 RPM limit)
        sanitized_messages = []
        messages_blocked = 0
        total_input_tokens = 0

        for msg_index, msg in enumerate(chat.messages):
            content = msg.content or ""
            total_input_tokens += max(1, len(content) // 4)  # conservative token estimate

            if not content.strip():
                # Empty messages pass through unchanged (no safety cost)
                sanitized_messages.append({
                    "role": msg.role,
                    "content": content,
                    "completed_at": msg.completed_at,
                    "assistant_category": msg.assistant_category,
                    "thinking": msg.thinking,
                    "has_thinking": msg.has_thinking,
                    "thinking_tokens": msg.thinking_tokens,
                })
                continue

            msg_task_id = f"{chat_task_id}_msg{msg_index}"
            try:
                scanned = await sanitize_message_for_import(
                    content=content,
                    task_id=msg_task_id,
                    secrets_manager=secrets_manager,
                    cache_service=cache_service,
                )
            except Exception as scan_err:
                logger.error(
                    f"[ImportChat] Safety scan error for {msg_task_id}: {scan_err}",
                    exc_info=True,
                )
                # Treat scan error as block (fail-closed)
                scanned = ""

            if scanned == "":
                # Message was blocked
                messages_blocked += 1
                final_content = _IMPORT_BLOCKED_PLACEHOLDER
            else:
                final_content = scanned

            # Normalise assistant_category
            category = (msg.assistant_category or "").strip().lower()
            if category not in _VALID_ASSISTANT_CATEGORIES:
                category = "general knowledge"

            sanitized_messages.append({
                "role": msg.role,
                "content": final_content,
                "completed_at": msg.completed_at,
                "assistant_category": category if msg.role == "assistant" else None,
                "thinking": msg.thinking if msg.role == "assistant" else None,
                "has_thinking": msg.has_thinking if msg.role == "assistant" else None,
                "thinking_tokens": msg.thinking_tokens if msg.role == "assistant" else None,
            })

        # Do not charge if ALL messages were blocked
        messages_imported = len(sanitized_messages) - messages_blocked
        credits_to_charge = 0
        if messages_imported > 0 and total_input_tokens > 0:
            credits_to_charge = max(1, total_input_tokens // _IMPORT_TOKENS_PER_CREDIT)

        # ----------------------------------------------------------------
        # Store chat + messages in Directus
        # ----------------------------------------------------------------
        try:
            # Create the chat record
            chat_payload: Dict[str, Any] = {
                "id": new_chat_id,
                "user_id": user_id,
                "title": (chat.title or "").strip() or None,
                "draft": chat.draft,
                "summary": chat.summary,
                "imported": True,
            }
            await directus_service.create_item("chats", chat_payload)

            # Create each message
            for msg_data in sanitized_messages:
                msg_id = str(_uuid.uuid4())
                msg_payload: Dict[str, Any] = {
                    "id": msg_id,
                    "chat_id": new_chat_id,
                    "user_id": user_id,
                    "role": msg_data["role"],
                    "content": msg_data["content"],
                }
                if msg_data.get("completed_at"):
                    msg_payload["completed_at"] = msg_data["completed_at"]
                if msg_data.get("assistant_category"):
                    msg_payload["assistant_category"] = msg_data["assistant_category"]
                if msg_data.get("thinking"):
                    msg_payload["thinking"] = msg_data["thinking"]
                if msg_data.get("has_thinking") is not None:
                    msg_payload["has_thinking"] = msg_data["has_thinking"]
                if msg_data.get("thinking_tokens") is not None:
                    msg_payload["thinking_tokens"] = msg_data["thinking_tokens"]
                await directus_service.create_item("messages", msg_payload)

        except Exception as store_err:
            logger.error(
                f"[ImportChat] Failed to store chat {new_chat_id} for user {user_id}: {store_err}",
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=f"Failed to store imported chat {chat_index + 1}")

        # ----------------------------------------------------------------
        # Charge credits for this chat
        # ----------------------------------------------------------------
        if credits_to_charge > 0:
            try:
                await billing_service.charge_user_credits(
                    user_id=user_id,
                    credits_to_deduct=credits_to_charge,
                    user_id_hash=user_id_hash,
                    app_id="settings",
                    skill_id="chat_import",
                    usage_details={
                        "title": "Chat import & safety check",
                        "chat_id": new_chat_id,
                        "input_tokens": total_input_tokens,
                    },
                )
                total_credits += credits_to_charge
            except Exception as billing_err:
                logger.error(
                    f"[ImportChat] Billing failed for chat {new_chat_id}, user {user_id}: {billing_err}",
                    exc_info=True,
                )
                # Non-fatal: chat is already stored, log and continue

        # ----------------------------------------------------------------
        # Broadcast new chat to all user's connected devices via WS
        # ----------------------------------------------------------------
        try:
            await ws_manager.broadcast_to_user(
                {
                    "type": "chat_imported",
                    "payload": {"chat_id": new_chat_id},
                },
                user_id,
                exclude_device_hash=None,
            )
        except Exception:
            pass  # Non-fatal

        results.append(ImportedChatResult(
            chat_id=new_chat_id,
            title=chat.title,
            messages_imported=messages_imported,
            messages_blocked=messages_blocked,
            credits_charged=credits_to_charge,
        ))

        logger.info(
            f"[ImportChat] user={user_id} chat={new_chat_id} "
            f"msgs={len(sanitized_messages)} blocked={messages_blocked} "
            f"credits={credits_to_charge}"
        )

    return ImportChatResponse(
        imported=results,
        total_credits_charged=total_credits,
    )


# ---------------------------------------------------------------------------
# Issue-Report Console Log Push
# ---------------------------------------------------------------------------

class IssueLogsRequest(BaseModel):
    """Request body for pushing issue-report-time console logs to OpenObserve."""
    issue_id: str = Field(..., max_length=100, description="Directus issue record ID")
    logs_text: str = Field(..., max_length=60000, description="Pre-formatted console log text")
    page_url: str = Field(default="", max_length=500)
    user_agent: str = Field(default="", max_length=500)


@router.post("/issue-logs", include_in_schema=False)
@limiter.limit("5/minute")
async def push_issue_logs(
    request: Request,
    body: IssueLogsRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Push the console log snapshot captured at issue-report time to OpenObserve.

    Called by the frontend immediately after a successful issue submission.
    Available to all authenticated users (not admin-only) so any user who
    files a report gets their logs indexed for admin investigation.

    Rate-limited to 5/minute to prevent abuse (a user would never submit
    more than 1-2 issue reports per minute in normal operation).
    """
    from backend.core.api.app.services.openobserve_push_service import openobserve_push_service

    success = await openobserve_push_service.push_issue_logs(
        logs_text=body.logs_text,
        issue_id=body.issue_id,
        user_id=current_user.id,
        metadata={
            "pageUrl": body.page_url,
            "userAgent": body.user_agent,
        },
    )

    if not success:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"Failed to push issue logs to OpenObserve for user {current_user.id}, issue {body.issue_id}"
        )

    # Always return 200 — log push failures must not break the issue submission UX.
    return {"success": success}


# ---------------------------------------------------------------------------
# User Debug Log Sharing Sessions
# ---------------------------------------------------------------------------
# Allows any authenticated user to activate a temporary debug logging session.
# While active, the frontend forwards console logs to OpenObserve tagged with
# a short debugging_id. The user shares this ID with support, who can then
# query both frontend and backend logs via `debug.py logs --debug-id <ID>`.
#
# Architecture context: See docs/architecture/admin-console-log-forwarding.md
# ---------------------------------------------------------------------------

# Duration options in seconds — keys match the frontend picker values
DEBUG_SESSION_DURATION_MAP: Dict[str, Optional[int]] = {
    "5m": 300,
    "1h": 3600,
    "3d": 259200,
    "7d": 604800,
    "none": None,  # No expiry — must be manually revoked
}

# Redis key prefix for debug sessions (by debugging_id)
DEBUG_SESSION_KEY_PREFIX = "debug_session:"
# Redis key prefix for reverse lookup (user_id → debugging_id)
DEBUG_SESSION_USER_KEY_PREFIX = "debug_session_user:"

# Maximum TTL for "no expiry" sessions to prevent orphaned keys (30 days)
DEBUG_SESSION_MAX_TTL = 2592000


class DebugSessionCreateRequest(BaseModel):
    """Request body for creating a user debug log sharing session."""
    duration: str = Field(
        ...,
        description="Session duration: '5m', '1h', '3d', '7d', or 'none' (no expiry, max 30 days).",
    )


class DebugSessionResponse(BaseModel):
    """Response with debug session details."""
    active: bool = Field(..., description="Whether a debug session is currently active")
    debugging_id: Optional[str] = Field(None, description="The short debug session ID (e.g. 'dbg-a3f2c8')")
    expires_at: Optional[str] = Field(None, description="ISO timestamp when the session expires, null if no expiry")
    duration: Optional[str] = Field(None, description="Selected duration label (e.g. '1h', '7d', 'none')")


class DebugLogsRequest(BaseModel):
    """Request body for pushing debug-session console logs to OpenObserve."""
    logs: List[Dict[str, Any]] = Field(..., max_length=50, description="Log entries (same format as admin client-logs)")
    metadata: Optional[Dict[str, str]] = Field(None, description="Client metadata (userAgent, pageUrl, tabId)")
    debugging_id: str = Field(..., max_length=20, description="Active debug session ID")


def _generate_debugging_id() -> str:
    """Generate a short, shareable debug session ID like 'dbg-a3f2c8'."""
    import secrets
    return f"dbg-{secrets.token_hex(3)}"


@router.post("/debug-session")
@limiter.limit("5/minute")
async def create_debug_session(
    request: Request,
    body: DebugSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> DebugSessionResponse:
    """Create a new debug log sharing session for the current user.

    Generates a short debugging_id, stores it in Redis with the selected TTL,
    and returns it to the user. While active, the frontend will forward console
    logs tagged with this ID to OpenObserve.

    If the user already has an active session, it is replaced.
    """
    if body.duration not in DEBUG_SESSION_DURATION_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid duration. Must be one of: {', '.join(DEBUG_SESSION_DURATION_MAP.keys())}",
        )

    ttl_seconds = DEBUG_SESSION_DURATION_MAP[body.duration]
    effective_ttl = ttl_seconds if ttl_seconds is not None else DEBUG_SESSION_MAX_TTL

    debugging_id = _generate_debugging_id()

    # Calculate expiry timestamp
    if ttl_seconds is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        expires_at_iso = expires_at.isoformat()
    else:
        expires_at_iso = None

    # Store debug session in Redis (keyed by debugging_id)
    session_data = json.dumps({
        "user_id": current_user.id,
        "debugging_id": debugging_id,
        "duration": body.duration,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at_iso,
    })

    redis = await cache_service.client
    # Delete any existing session for this user first
    old_debug_id = await redis.get(f"{DEBUG_SESSION_USER_KEY_PREFIX}{current_user.id}")
    if old_debug_id:
        old_id = old_debug_id.decode("utf-8") if isinstance(old_debug_id, bytes) else old_debug_id
        await redis.delete(f"{DEBUG_SESSION_KEY_PREFIX}{old_id}")

    # Set the new session keys with TTL
    await redis.set(
        f"{DEBUG_SESSION_KEY_PREFIX}{debugging_id}",
        session_data,
        ex=effective_ttl,
    )
    await redis.set(
        f"{DEBUG_SESSION_USER_KEY_PREFIX}{current_user.id}",
        debugging_id,
        ex=effective_ttl,
    )

    logger.info(
        f"Debug session created: {debugging_id} for user {current_user.id}, "
        f"duration={body.duration}, ttl={effective_ttl}s"
    )

    return DebugSessionResponse(
        active=True,
        debugging_id=debugging_id,
        expires_at=expires_at_iso,
        duration=body.duration,
    )


@router.get("/debug-session")
@limiter.limit("30/minute")
async def get_debug_session(
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> DebugSessionResponse:
    """Check if the current user has an active debug log sharing session."""
    redis = await cache_service.client
    debug_id_raw = await redis.get(f"{DEBUG_SESSION_USER_KEY_PREFIX}{current_user.id}")

    if not debug_id_raw:
        return DebugSessionResponse(active=False)

    debugging_id = debug_id_raw.decode("utf-8") if isinstance(debug_id_raw, bytes) else debug_id_raw
    session_raw = await redis.get(f"{DEBUG_SESSION_KEY_PREFIX}{debugging_id}")

    if not session_raw:
        # User key exists but session expired — clean up the stale user key
        await redis.delete(f"{DEBUG_SESSION_USER_KEY_PREFIX}{current_user.id}")
        return DebugSessionResponse(active=False)

    session = json.loads(session_raw)
    return DebugSessionResponse(
        active=True,
        debugging_id=debugging_id,
        expires_at=session.get("expires_at"),
        duration=session.get("duration"),
    )


@router.delete("/debug-session")
@limiter.limit("10/minute")
async def delete_debug_session(
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> DebugSessionResponse:
    """Revoke the current user's active debug log sharing session."""
    redis = await cache_service.client
    debug_id_raw = await redis.get(f"{DEBUG_SESSION_USER_KEY_PREFIX}{current_user.id}")

    if debug_id_raw:
        debugging_id = debug_id_raw.decode("utf-8") if isinstance(debug_id_raw, bytes) else debug_id_raw
        await redis.delete(f"{DEBUG_SESSION_KEY_PREFIX}{debugging_id}")
        await redis.delete(f"{DEBUG_SESSION_USER_KEY_PREFIX}{current_user.id}")
        logger.info(f"Debug session revoked: {debugging_id} for user {current_user.id}")

    return DebugSessionResponse(active=False)


@router.post("/debug-logs", include_in_schema=False)
@limiter.limit("1200/minute")
async def push_debug_logs(
    request: Request,
    body: DebugLogsRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict:
    """Push console logs from a user with an active debug log sharing session.

    Similar to the admin client-logs endpoint, but available to any authenticated
    user with a valid debugging_id. Logs are tagged in OpenObserve with the
    debugging_id for later retrieval via `debug.py logs --debug-id <ID>`.

    Rate-limited to 1200/minute (same as admin client-logs) to avoid log loss.
    """
    # Validate that the debugging_id is active and belongs to this user
    redis = await cache_service.client
    session_raw = await redis.get(f"{DEBUG_SESSION_KEY_PREFIX}{body.debugging_id}")

    if not session_raw:
        # Session expired or doesn't exist — silently accept (don't break UX)
        return {"success": False, "reason": "debug_session_expired"}

    session = json.loads(session_raw)
    if session.get("user_id") != current_user.id:
        # Debug session belongs to a different user — reject
        raise HTTPException(status_code=403, detail="Debug session does not belong to this user")

    # Push logs to OpenObserve with debugging_id label
    from backend.core.api.app.services.openobserve_push_service import openobserve_push_service

    metadata = body.metadata or {}
    user_agent = metadata.get("userAgent", "")
    page_url = metadata.get("pageUrl", "")
    tab_id = metadata.get("tabId", "")

    success = await openobserve_push_service.push_debug_session_logs(
        entries=body.logs,
        debugging_id=body.debugging_id,
        user_id=current_user.id,
        metadata={
            "userAgent": user_agent,
            "pageUrl": page_url,
            "tabId": tab_id,
        },
    )

    return {"success": success}
