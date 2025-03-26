from fastapi import APIRouter, Depends, Request, Response, Cookie, HTTPException, status
import logging
import time
from typing import Optional
from app.schemas.auth import SessionResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service
from app.routes.auth_routes.auth_common import verify_authenticated_user
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@router.post("/session", response_model=SessionResponse)
async def get_session(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token")
):
    """Simple session validation using cache"""
    try:
        # Use the shared authentication function to verify user
        is_auth, user_data, refresh_token = await verify_authenticated_user(
            request, cache_service, directus_service, require_known_device=False
        )
        
        if not is_auth or not user_data:
            return SessionResponse(success=False, message="Not logged in", token_refresh_needed=False)

        # 2. Check token expiry
        current_time = int(time.time())
        token_expiry = user_data.get("token_expiry", 0)
        expires_soon = token_expiry - current_time < 300  # 5 minutes

        # 3. If token expires soon, refresh it with Directus
        if expires_soon:
            logger.info("Token expires soon, refreshing...")
            success, auth_data, _ = await directus_service.refresh_token(refresh_token)
            
            if success and auth_data.get("cookies"):
                # Get the new refresh token
                new_refresh_token = None
                for name, value in auth_data["cookies"].items():
                    if name == "directus_refresh_token":
                        new_refresh_token = value
                        
                    # Set cookies with our prefix
                    cookie_name = name.replace("directus_", "auth_") if name.startswith("directus_") else name
                    response.set_cookie(
                        key=cookie_name,
                        value=value,
                        httponly=True,
                        secure=True,
                        samesite="strict",
                        max_age=86400
                    )
                
                # If we got a new refresh token, update the cache
                if new_refresh_token:
                    # Keep the existing user data but associate it with the new token
                    await cache_service.set_user(user_data, refresh_token=new_refresh_token)
                    logger.info("Token refreshed successfully")
                else:
                    logger.warning("No new refresh token in response")
            else:
                logger.error("Failed to refresh token")
                return SessionResponse(success=False, message="Session expired", token_refresh_needed=True)

        # 4. Return cached user data
        logger.info("Returning cached user data")
        return SessionResponse(
            success=True,
            message="Session valid",
            user=UserResponse(
                username=user_data.get("username"),
                is_admin=user_data.get("is_admin", False),
                credits=user_data.get("credits", 0),
                profile_image_url=user_data.get("profile_image_url"),
                last_opened=user_data.get("last_opened"),
                tfa_app_name=user_data.get("tfa_app_name") # Include the 2FA app name
            ),
            token_refresh_needed=False
        )

    except Exception as e:
        logger.error(f"Session check error: {str(e)}")
        return SessionResponse(success=False, message="Session error", token_refresh_needed=False)
