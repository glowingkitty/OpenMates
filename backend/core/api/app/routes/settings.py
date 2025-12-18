from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Cookie, Request, Security
from fastapi.responses import StreamingResponse
import logging
import time
from typing import Optional
from pydantic import BaseModel, Field # Import BaseModel and Field for response models
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_compliance_service, get_current_user, get_encryption_service, get_current_user_or_api_key
from backend.core.api.app.utils.api_key_auth import api_key_scheme
from fastapi.security import HTTPBearer

# Create an optional API key scheme that doesn't fail if missing (for endpoints that support both session and API key auth)
optional_api_key_scheme = HTTPBearer(
    scheme_name="API Key",
    description="Enter your API key. API keys start with 'sk-api-'. Use format: Bearer sk-api-...",
    auto_error=False  # Don't raise error if missing - allows session auth to work
) 
import os
import random
import string
from backend.core.api.app.services.image_safety import ImageSafetyService
from backend.core.api.app.services.s3 import S3UploadService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip # Updated imports
from backend.core.api.app.schemas.settings import LanguageUpdateRequest, DarkModeUpdateRequest, AutoTopUpLowBalanceRequest, BillingOverviewResponse, InvoiceResponse # Import request/response models
import hashlib  # For API key hashing and user ID hashing
import secrets  # For secure API key generation
from datetime import datetime, timezone

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
    cache_service: CacheService = Depends(get_cache_service)
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
    current_user: User = Depends(get_current_user),  # Web app only - not in whitelist
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
        except:
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


# --- Endpoint for exporting usage data as CSV ---
@router.get("/usage/export", include_in_schema=False)  # Exclude from schema - not in whitelist
@limiter.limit("10/minute")  # Lower limit for export to prevent abuse
async def export_usage_csv(
    request: Request,
    months: int = 3,
    current_user: User = Depends(get_current_user),  # Web app only - not in whitelist
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


