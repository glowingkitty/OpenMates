from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Cookie
import logging
import time
import hashlib
from typing import Optional
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService
from app.models.user import User
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service
import os
import random
import string
from app.services.image_safety import ImageSafetyService
from app.services.s3 import S3UploadService

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
    
    # Check cache first using the same key format as auth_session
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    cache_key = f"session:{token_hash}"
    cached_data = await cache_service.get(cache_key)

    if cached_data:
        return User(
            id=cached_data.get("user_id"),
            username=cached_data.get("username"),
            is_admin=cached_data.get("is_admin", False),
            credits=cached_data.get("credits", 0),
            profile_image_url=cached_data.get("profile_image_url"),
            last_opened=cached_data.get("last_opened")
        )
    
    # If no cache hit, try to get from Directus
    success, user_data = await directus_service.validate_token(refresh_token)
    if not success or not user_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Create User object from Directus data
    user = User(
        id=user_data.get("id"),
        username=user_data.get("username"),
        is_admin=user_data.get("role", {}).get("name") == "admin",
        credits=user_data.get("credits", 0),
        profile_image_url=user_data.get("profile_image_url"),
        last_opened=user_data.get("last_opened")
    )
    
    # Cache the user data for future requests
    await cache_service.set(cache_key, {
        "user_id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "credits": user.credits,
        "profile_image_url": user.profile_image_url,
        "last_opened": user.last_opened,
        "token_expiry": int(time.time()) + 86400  # 24 hours
    }, ttl=86400)
    
    return user

@router.post("/user/update_profile_image")
async def update_profile_image(
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

        # Check image safety
        is_safe = await image_safety_service.check_image_safety(image_content)
        if not is_safe:
            raise HTTPException(status_code=400, detail="Image content not allowed")

        # Generate unique filename
        file_ext = os.path.splitext(file.filename)[1].lower()
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        new_filename = f"{current_user.id}-{int(time.time())}-{random_suffix}{file_ext}"

        # Delete old image if exists
        old_url = await directus_service.get_user_profile_image_url(current_user.id)
        if old_url:
            old_key = old_url.split('/')[-1]
            await s3_service.delete_file(bucket_config['name'], old_key)

        # Upload new image
        image_url = await s3_service.upload_file(
            bucket_config['name'],
            new_filename,
            image_content,
            file.content_type
        )

        # Encrypt URL for storage
        encrypted_url = await encryption_service.encrypt(image_url)

        # Update Directus user entry
        await directus_service.update_user(current_user.id, {
            "encrypted_profileimage_url": encrypted_url
        })

        # Update cache
        cache_key = f"user_profile_image:{current_user.id}"
        await cache_service.set(cache_key, image_url)

        return {"url": image_url}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        raise HTTPException(status_code=500, detail="Error processing image")