from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Cookie, Request
import logging
import time
from typing import Optional
from pydantic import BaseModel # Import BaseModel for response model
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_compliance_service, get_current_user 
import os
import random
import string
from backend.core.api.app.services.image_safety import ImageSafetyService
from backend.core.api.app.services.s3 import S3UploadService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint, DeviceFingerprint, _extract_client_ip
from backend.core.api.app.schemas.settings import LanguageUpdateRequest, DarkModeUpdateRequest, UserEmailResponse # Import request/response models

router = APIRouter(prefix="/v1/settings")
logger = logging.getLogger(__name__)

# --- Define a simple success response model ---
class SimpleSuccessResponse(BaseModel):
    success: bool
    message: str

# --- Response model for user email ---
class UserEmailResponse(BaseModel):
    email: str

# --- Endpoint for updating profile image ---
@router.post("/user/update_profile_image", response_model=dict) # Keep original response model
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
                current_fingerprint: DeviceFingerprint = generate_device_fingerprint(request)
                client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)

                # Delete user account with proper reason
                # Note: The deletion will be logged by the delete_user method (using service from backend.core.api.app.state)
                await directus_service.delete_user(
                    current_user.id,
                    deletion_type="policy_violation",
                    reason="repeated_inappropriate_profile_images",
                    ip_address=client_ip,
                    device_fingerprint=current_fingerprint.calculate_stable_hash(), # Use stable hash
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
            "last_opened": "/signup/step-4"
        })

        # Update cache with new image URL and last_opened step
        logger.info(f"Attempting to update cache for user {current_user.id} after profile image upload.")
        cache_update_success = await cache_service.update_user(current_user.id, {
            "profile_image_url": image_url,
            "last_opened": "/signup/step-4"
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
@router.post("/user/consent/privacy-apps", response_model=SimpleSuccessResponse)
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
        "last_opened": "/signup/step-8"
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
@router.post("/user/language", response_model=SimpleSuccessResponse)
async def update_user_language(
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
@router.post("/user/darkmode", response_model=SimpleSuccessResponse)
async def update_user_darkmode(
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
@router.post("/user/consent/mates", response_model=SimpleSuccessResponse)
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
        "last_opened": "/signup/step-9"
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


# --- Endpoint for retrieving user email ---
@router.get("/user/email", response_model=UserEmailResponse)
async def get_user_email(
    request: Request, # Needed to get encryption service from state
    current_user: User = Depends(get_current_user)
):
    """Retrieves the decrypted email address for the currently authenticated user."""
    logger.info(f"Request received to fetch email for user {current_user.id}")

    encryption_service: EncryptionService = request.app.state.encryption_service
    if not encryption_service:
         logger.error(f"EncryptionService not available in app state for user {current_user.id}.")
         raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    # The get_current_user dependency should have populated these fields
    encrypted_email_address = getattr(current_user, 'encrypted_email_address', None)
    vault_key_id = getattr(current_user, 'vault_key_id', None)

    if not encrypted_email_address:
        logger.error(f"Encrypted email not found for user {current_user.id}.")
        # Return 404 Not Found as the data is missing for this user
        raise HTTPException(status_code=404, detail="User email information not found.")

    if not vault_key_id:
        logger.error(f"Vault key ID not found for user {current_user.id}. Cannot decrypt email.")
        # Return 500 Internal Server Error as this is a configuration issue
        raise HTTPException(status_code=500, detail="Cannot retrieve email due to key error.")

    try:
        decrypted_email = await encryption_service.decrypt_with_user_key(encrypted_email_address, vault_key_id)
        logger.info(f"Successfully decrypted email for user {current_user.id}")
        return UserEmailResponse(email=decrypted_email)
    except Exception as e:
        logger.error(f"Failed to decrypt email for user {current_user.id}: {str(e)}", exc_info=True)
        # Return 500 Internal Server Error for decryption failures
        raise HTTPException(status_code=500, detail="Failed to retrieve email.")