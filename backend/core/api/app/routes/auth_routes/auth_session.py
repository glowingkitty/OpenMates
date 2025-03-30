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
    """
    Validate session using cache and check device fingerprint.
    Triggers 2FA re-auth if device mismatches and 2FA is enabled.
    """
    try:
        # Use the shared authentication function to verify user AND device
        is_auth, user_data, refresh_token, auth_status = await verify_authenticated_user(
            request, cache_service, directus_service, require_known_device=True
        )

        # Always clear potentially leftover signup cookies as a safety measure
        response.delete_cookie(key="signup_invite_code")
        response.delete_cookie(key="signup_email")
        response.delete_cookie(key="signup_username")
        response.delete_cookie(key="signup_password")

        # Handle device mismatch status first
        if auth_status == "device_mismatch":
            if user_data.get("tfa_enabled", False):
                logger.warning(f"Device mismatch for user, 2FA enabled. Triggering re-auth.")
                return SessionResponse(success=False, message="Device mismatch, 2FA required", re_auth_required="2fa")
            else:
                logger.warning(f"Device mismatch for user, 2FA disabled. Invalidating session.")
                # TODO: Consider explicitly clearing the cookie/cache here? For now, just return failure.
                return SessionResponse(success=False, message="Session invalid due to device change", token_refresh_needed=False)

        # Handle other authentication failures
        if not is_auth or not user_data:
            logger.info(f"Session validation failed: {auth_status or 'Unknown reason'}")
            return SessionResponse(success=False, message="Not logged in", token_refresh_needed=False)

        # --- Authentication successful, device known ---

        # Update last online timestamp
        current_time = int(time.time())
        user_id = user_data.get("user_id") # Should exist if is_auth is True

        if user_id:
            # Update Directus (fire and forget, log errors)
            try:
                await directus_service.update_user(user_id, {"last_online_timestamp": str(current_time)})
            except Exception as e:
                logger.error(f"Failed to update last_online_timestamp in Directus for user {user_id}: {e}")
            
            # Update cache
            update_success = await cache_service.update_user(user_id, {"last_online_timestamp": current_time})
            if update_success:
                # Update local user_data dict as well for the response
                user_data['last_online_timestamp'] = current_time
            else:
                 logger.warning(f"Failed to update last_online_timestamp in cache for user {user_id}")

        # 2. Check token expiry
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
                tfa_app_name=user_data.get("tfa_app_name"),
                tfa_enabled=user_data.get("tfa_enabled", False),
                consent_privacy_and_apps_default_settings=user_data.get("consent_privacy_and_apps_default_settings", False),
                consent_mates_default_settings=user_data.get("consent_mates_default_settings", False)
            ),
            token_refresh_needed=False
        )

    except Exception as e:
        logger.error(f"Session check error: {str(e)}")
        return SessionResponse(success=False, message="Session error", token_refresh_needed=False)
