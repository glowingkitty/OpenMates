from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Cookie, Request
import logging
import time
from typing import Optional
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService
from app.models.user import User
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_compliance_service
import os
import random
import string
from app.services.image_safety import ImageSafetyService
from app.services.s3 import S3UploadService
from app.services.compliance import ComplianceService
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip

router = APIRouter(prefix="/v1/settings")
logger = logging.getLogger(__name__)

# Initialize services
cache_service = CacheService()
directus_service = DirectusService(cache_service=cache_service)
encryption_service = EncryptionService(cache_service=cache_service)
s3_service = S3UploadService()
image_safety_service = ImageSafetyService()


async def get_current_user(
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token")
) -> User:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Check cache first using the enhanced cache service method
    cached_data = await cache_service.get_user_by_token(refresh_token)

    if cached_data:
        return User(
            id=cached_data.get("user_id"),
            username=cached_data.get("username"),
            is_admin=cached_data.get("is_admin"),
            credits=cached_data.get("credits"),
            profile_image_url=cached_data.get("profile_image_url"),
            tfa_app_name=cached_data.get("tfa_app_name"),
            last_opened=cached_data.get("last_opened"),
            vault_key_id=cached_data.get("vault_key_id")
        )
    
    # If no cache hit, validate token and get user data
    success, token_data = await directus_service.validate_token(refresh_token)
    if not success or not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Get user ID from token data
    user_id = token_data.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token data")

    # Fetch complete user profile
    success, user_data, _ = await directus_service.get_user_profile(user_id)
    if not success or not user_data:
        raise HTTPException(status_code=401, detail="Could not fetch user data")

    # Credits are already in user_data from get_user_profile

    # Create User object from profile data
    user = User(
        id=user_id,
        username=user_data.get("username"),
        is_admin=user_data.get("is_admin", False),  # Use direct is_admin field
        credits=user_data.get("credits", 0), # Use credits from user_data
        profile_image_url=user_data.get("profile_image_url"),
        last_opened=user_data.get("last_opened"),
        vault_key_id=user_data.get("vault_key_id") # Populate from fresh fetch
    )
    
    # Cache the user data for future requests using the enhanced cache service method
    user_data_for_cache = {
        "user_id": user_id,
        "username": user.username,
        "is_admin": user.is_admin,
        "credits": user.credits,
        "profile_image_url": user.profile_image_url,
        "last_opened": user.last_opened,
        "vault_key_id": user.vault_key_id # Add vault_key_id to cache
    }
    
    await cache_service.set_user(user_data_for_cache, refresh_token=refresh_token)
    
    return user

@router.post("/user/update_profile_image")
async def update_profile_image(
    request: Request,  # Add request parameter to get IP and fingerprint
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
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

        # Check rejected uploads count from cache using a standardized key format
        reject_key = f"profile_image_rejects:{current_user.id}"
        reject_count = await cache_service.get(reject_key) or 0

        # Check image safety with stricter profile image rules
        is_safe = await image_safety_service.check_profile_image(image_content)
        if not is_safe:
            # Increment and store reject count
            reject_count += 1
            await cache_service.set(reject_key, reject_count, ttl=86400)  # 24h TTL

            if reject_count >= 4:  # Changed from 3 to 4 (delete on 4th attempt)
                # Get device information for compliance logging
                device_fingerprint = get_device_fingerprint(request)
                client_ip = get_client_ip(request)
                
                # Delete user account with proper reason
                # Note: The deletion will be logged by the delete_user method
                await directus_service.delete_user(
                    current_user.id, 
                    deletion_type="policy_violation",
                    reason="repeated_inappropriate_profile_images",
                    ip_address=client_ip,
                    device_fingerprint=device_fingerprint,
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

        # Upload new image
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

        # Encrypt URL using user-specific key and context
        encrypted_url, _ = await encryption_service.encrypt_with_user_key(image_url, vault_key_id) # Use encrypt_with_user_key

        # Update Directus user entry with profile image and last_opened field
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
            await s3_service.delete_file('profile_images', old_key)

        return {"url": image_url}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        raise HTTPException(status_code=500, detail="Error processing image")