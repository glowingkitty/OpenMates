from fastapi import APIRouter, Depends, Request, Response, Cookie, HTTPException, status
import logging
import time
import os
from typing import Optional, Dict, Any # Added Dict, Any
from backend.core.api.app.schemas.auth import SessionResponse
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
# Import new fingerprinting and risk assessment functions
# generate_device_fingerprint, DeviceFingerprint, should_require_2fa are already imported correctly
from backend.core.api.app.utils.device_fingerprint import (
    generate_device_fingerprint_hash, _extract_client_ip
)
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service
from backend.core.api.app.routes.auth_routes.auth_common import verify_authenticated_user
from backend.core.api.app.schemas.user import UserResponse

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/session", response_model=SessionResponse)
async def get_session(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token")
):
    """
    Validate session using cache and perform risk assessment based on device fingerprint,
    including optional client-side signals.
    Triggers 2FA re-auth if risk score is high.
    """
    try:
        logger.info("Processing POST /session")

        # Check if invite code requirement is enabled based on SIGNUP_LIMIT
        signup_limit = int(os.getenv("SIGNUP_LIMIT", "0"))
        logger.info(f"Checking invite code requirement against SIGNUP_LIMIT={signup_limit}")
        require_invite_code = True  # Default to requiring invite code
        
        if signup_limit > 0:  # Only check if limit is set
            try:
                # Check if we have this value cached
                cached_require_invite_code = await cache_service.get("require_invite_code")
                if cached_require_invite_code is not None:
                    require_invite_code = cached_require_invite_code
                else:
                    # Get the total user count and compare with SIGNUP_LIMIT
                    total_users = await directus_service.get_total_users_count()
                    require_invite_code = total_users >= signup_limit
                    # Cache this value for quick access
                    await cache_service.set("require_invite_code", require_invite_code, ttl=172800)  # Cache for 48 hours
                    
                logger.info(f"Invite code requirement check: limit={signup_limit}, users={total_users if 'total_users' in locals() else 'cached'}, required={require_invite_code}")
            except Exception as e:
                logger.error(f"Error checking user count against signup limit: {e}")
                # Default to requiring invite code on error
                require_invite_code = True


        # Step 1: Verify basic authentication (token validity) without device check
        is_auth, user_data, refresh_token, auth_status = await verify_authenticated_user(
            request, cache_service, directus_service, require_known_device=False # Device check replaced by risk assessment
        )

        # Handle authentication failures (invalid/expired token, etc.)
        if not is_auth or not user_data:
            logger.info(f"Session validation failed (basic auth): {auth_status or 'Unknown reason'}")
            return SessionResponse(
                success=False, 
                message="Not logged in", 
                token_refresh_needed=False,
                require_invite_code=require_invite_code  # Include the invite code requirement
            )

        # --- Authentication successful, proceed with risk assessment ---
        user_id = user_data.get("user_id")
        if not user_id:
             logger.error("User ID missing from cached data after successful basic auth.")
             return SessionResponse(
                success=False, 
                message="Internal server error", 
                token_refresh_needed=False,
                require_invite_code=require_invite_code  # Include the invite code requirement
             )

        # Step 2: Generate current fingerprint hash and detailed geo data
        device_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        device_location_str = f"{city}, {country_code}" if city and country_code else country_code or "Unknown" # More detailed location string

        # Step 3: Check if this device hash is already known for the user
        known_device_hashes = await directus_service.get_user_device_hashes(user_id)
        is_new_device_hash = device_hash not in known_device_hashes
        logger.info(f"Session: Device hash {device_hash[:8]}... is new: {is_new_device_hash} for user {user_id[:6]}...")

        # Step 4: Perform 2FA check if it's a new device and 2FA is enabled
        if is_new_device_hash and user_data.get("tfa_enabled", False):
            logger.warning(f"New device detected for user {user_id[:6]} and 2FA is enabled. Triggering 2FA re-auth.")
            # Return minimal user info needed for the re-auth screen
            minimal_user_info = UserResponse(
                username=user_data.get("username"), # Send username if available
                is_admin=user_data.get("is_admin", False),
                credits=user_data.get("credits", 0),
                profile_image_url=user_data.get("profile_image_url"),
                tfa_app_name=user_data.get("tfa_app_name"),
                tfa_enabled=True, # Explicitly true as we are triggering 2FA
                last_opened=user_data.get("last_opened"),
                consent_privacy_and_apps_default_settings=bool(user_data.get("consent_privacy_and_apps_default_settings")),
                consent_mates_default_settings=bool(user_data.get("consent_mates_default_settings")),
                language=user_data.get("language", 'en'),
                darkmode=user_data.get("darkmode", False),
                invoice_counter=user_data.get("invoice_counter", 0)
            )
            return SessionResponse(
                success=False, # Indicate session is not fully valid *yet*
                message="Device verification required",
                re_auth_required="2fa",
                user=minimal_user_info, # Send user info for the verification screen
                require_invite_code=require_invite_code
            )
        else:
             logger.debug(f"User {user_id[:6]} does not require 2FA re-auth (device known or 2FA not enabled).")


        # --- Risk assessment passed (or 2FA not enabled), proceed with session validation ---
        logger.debug(f"Device check passed for user {user_id[:6]}. Proceeding with session validation.")

        # Step 5: Update device records in Directus and cache (if it was a new device, it will be added)
        current_time = int(time.time())
        try:
            # This function now handles the caching and storing of the new format.
            logger.debug(f"Triggering update to device record in Directus for user {user_id[:6]}...")
            await directus_service.add_user_device_hash(user_id, device_hash)

        except Exception as e:
            # Log the error but don't let it interrupt the user's session validation.
            logger.error(f"Failed during device record update process for user {user_id}: {e}", exc_info=True)


        # Step 6: Update last online timestamp
        try:
            await directus_service.update_user(user_id, {"last_online_timestamp": str(current_time)})
        except Exception as e:
            logger.error(f"Failed to update last_online_timestamp in Directus for user {user_id}: {e}")
        # Update cache
        update_success = await cache_service.update_user(user_id, {"last_online_timestamp": current_time})
        if update_success:
            user_data['last_online_timestamp'] = current_time # Update local dict
        else:
             logger.warning(f"Failed to update last_online_timestamp in cache for user {user_id}")

        # Step 7: Check token expiry
        token_expiry = user_data.get("token_expiry", 0)
        expires_soon = token_expiry - current_time < 300  # 5 minutes

        # Step 8: If token expires soon, refresh it
        if expires_soon:
            logger.info(f"Token expires soon for user {user_id[:6]}, refreshing...")
            success, auth_data, _ = await directus_service.refresh_token(refresh_token)

            if success and auth_data.get("cookies"):
                new_refresh_token = None
                for name, value in auth_data["cookies"].items():
                    if name == "directus_refresh_token":
                        new_refresh_token = value
                    cookie_name = name.replace("directus_", "auth_") if name.startswith("directus_") else name
                    response.set_cookie(
                        key=cookie_name, value=value, httponly=True, secure=True,
                        samesite="strict", max_age=cache_service.SESSION_TTL # Use TTL from cache service
                    )

                if new_refresh_token:
                    # Update cache with new token, keeping existing user data
                    await cache_service.set_user(user_data, refresh_token=new_refresh_token)
                    logger.info(f"Token refreshed successfully for user {user_id[:6]}")
                else:
                    logger.warning(f"No new refresh token in response for user {user_id[:6]}")
            else:
                logger.error(f"Failed to refresh token for user {user_id[:6]}")
                # If refresh fails, treat session as invalid
                return SessionResponse(success=False, message="Session expired", token_refresh_needed=True, require_invite_code=require_invite_code)
        
        # Step 9: Ensure user data is properly cached with token association
        # This is critical for WebSocket authentication to work
        logger.debug(f"Ensuring user data is properly cached with token for user {user_id[:6]}")
        await cache_service.set_user(user_data, refresh_token=refresh_token)
        
        # Step 10: Return successful session validation
        logger.info(f"Session valid for user {user_id[:6]}. Returning user data.")
        return SessionResponse(
            success=True,
            message="Session valid",
            user=UserResponse( # Map from user_data dictionary
                username=user_data.get("username"),
                is_admin=user_data.get("is_admin", False),
                credits=user_data.get("credits", 0),
                profile_image_url=user_data.get("profile_image_url"),
                last_opened=user_data.get("last_opened"),
                tfa_app_name=user_data.get("tfa_app_name"),
                tfa_enabled=user_data.get("tfa_enabled", False),
                consent_privacy_and_apps_default_settings=bool(user_data.get("consent_privacy_and_apps_default_settings")),
                consent_mates_default_settings=bool(user_data.get("consent_mates_default_settings")),
                language=user_data.get("language", 'en'),
                darkmode=user_data.get("darkmode", False),
                invoice_counter=user_data.get("invoice_counter", 0),
            ),
            token_refresh_needed=False,
            require_invite_code=require_invite_code
        )

    except Exception as e:
        logger.error(f"Session check error: {str(e)}", exc_info=True)
        return SessionResponse(success=False, message="Session error", token_refresh_needed=False, require_invite_code=require_invite_code)
