from fastapi import APIRouter, Depends, Request, Response, Cookie, HTTPException, status
import logging
import time
from typing import Optional, Dict, Any # Added Dict, Any
from backend.core.api.app.schemas.auth import SessionResponse, SessionRequest # Added SessionRequest
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
# Import new fingerprinting and risk assessment functions
# generate_device_fingerprint, DeviceFingerprint, should_require_2fa are already imported correctly
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint, should_require_2fa, DeviceFingerprint
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service
from backend.core.api.app.routes.auth_routes.auth_common import verify_authenticated_user
# from backend.core.api.app.models.user import User # No longer needed here
from backend.core.api.app.schemas.user import UserResponse

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/session", response_model=SessionResponse)
async def get_session(
    request: Request,
    response: Response,
    session_data: Optional[SessionRequest] = None, # Added optional request body
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
        # Step 1: Verify basic authentication (token validity) without device check
        is_auth, user_data, refresh_token, auth_status = await verify_authenticated_user(
            request, cache_service, directus_service, require_known_device=False # Device check replaced by risk assessment
        )

        # Handle authentication failures (invalid/expired token, etc.)
        if not is_auth or not user_data:
            logger.info(f"Session validation failed (basic auth): {auth_status or 'Unknown reason'}")
            return SessionResponse(success=False, message="Not logged in", token_refresh_needed=False)

        # --- Authentication successful, proceed with risk assessment ---
        user_id = user_data.get("user_id")
        if not user_id:
             logger.error("User ID missing from cached data after successful basic auth.")
             return SessionResponse(success=False, message="Internal server error", token_refresh_needed=False)

        # Step 2: Generate current fingerprint, including client signals if provided
        client_signals = session_data.deviceSignals if session_data else None
        logger.debug(f"Received client signals for /session: {bool(client_signals)}")
        current_fingerprint: DeviceFingerprint = generate_device_fingerprint(request, client_signals=client_signals)
        current_stable_hash = current_fingerprint.calculate_stable_hash()

        # Step 3: Get stored device data for the current hash
        stored_device_data = await directus_service.get_stored_device_data(user_id, current_stable_hash)

        # Step 4: Perform risk assessment
        # Only require 2FA if the user actually has it enabled
        if user_data.get("tfa_enabled", False):
            if stored_device_data is None:
                # If the specific hash isn't stored, it's treated as a new/unknown device.
                # The risk calculation might handle this, or we can enforce 2FA directly.
                # For now, let's rely on should_require_2fa which might score high if stored_data is empty/None.
                logger.warning(f"Device hash {current_stable_hash[:8]}... not found in stored records for user {user_id[:6]}. Performing risk assessment.")
                # Pass an empty dict if None, so calculate_risk_level doesn't crash
                stored_data_for_calc = stored_device_data or {}
            else:
                stored_data_for_calc = stored_device_data

            require_2fa = should_require_2fa(stored_data_for_calc, current_fingerprint)

            if require_2fa:
                logger.warning(f"High risk score detected for user {user_id[:6]}. Triggering 2FA re-auth.")
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
                    user=minimal_user_info # Send user info for the verification screen
                )
        else:
             logger.debug(f"User {user_id[:6]} does not have 2FA enabled. Skipping risk assessment check for re-auth.")


        # --- Risk assessment passed (or 2FA not enabled), proceed with session validation ---
        logger.debug(f"Risk assessment passed for user {user_id[:6]}. Proceeding with session validation.")

        # Step 5: Update last online timestamp (moved here, only if risk assessment passes)
        current_time = int(time.time())
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

        # Step 6: Check token expiry
        token_expiry = user_data.get("token_expiry", 0)
        expires_soon = token_expiry - current_time < 300  # 5 minutes

        # Step 7: If token expires soon, refresh it
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
                return SessionResponse(success=False, message="Session expired", token_refresh_needed=True)

        # Step 8: Return successful session validation
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
            token_refresh_needed=False
        )

    except Exception as e:
        logger.error(f"Session check error: {str(e)}", exc_info=True)
        return SessionResponse(success=False, message="Session error", token_refresh_needed=False)
