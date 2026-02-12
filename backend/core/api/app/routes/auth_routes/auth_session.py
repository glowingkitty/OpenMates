from fastapi import APIRouter, Depends, Request, Response, Cookie
import logging
import time
import os
import hashlib
from typing import Optional # Added Dict, Any
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
from backend.core.api.app.routes.auth_routes.auth_utils import get_cookie_domain
from backend.core.api.app.schemas.user import UserResponse

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/session", response_model=SessionResponse)
async def get_session(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False)  # Hidden from API docs - internal use only
):
    """
    Validate session using cache and perform risk assessment based on device fingerprint,
    including optional client-side signals.
    Triggers 2FA re-auth if risk score is high.
    """
    try:
        logger.info("Processing POST /session")

        # Check if invite code requirement is enabled based on SIGNUP_LIMIT
        # SIGNUP_LIMIT=0 means open signup (no invite codes required)
        # SIGNUP_LIMIT>0 means require invite codes once user count reaches the limit
        signup_limit = int(os.getenv("SIGNUP_LIMIT", "0"))
        logger.info(f"Checking invite code requirement against SIGNUP_LIMIT={signup_limit}")
        
        # Default to not requiring invite code (open signup) unless SIGNUP_LIMIT is set
        if signup_limit == 0:
            require_invite_code = False
            logger.info("SIGNUP_LIMIT is 0 - open signup enabled (invite codes not required)")
        else:
            # SIGNUP_LIMIT > 0: require invite codes when user count reaches the limit
            try:
                # Check if we have this value cached
                cached_require_invite_code = await cache_service.get("require_invite_code")
                if cached_require_invite_code is not None:
                    require_invite_code = cached_require_invite_code
                else:
                    # Get the count of users who completed signup (not just registered)
                    # This counts users who completed payment/signup (last_opened is not a signup path)
                    completed_signups = await directus_service.get_completed_signups_count()
                    require_invite_code = completed_signups >= signup_limit
                    # Cache this value for quick access
                    await cache_service.set("require_invite_code", require_invite_code, ttl=172800)  # Cache for 48 hours
                    logger.info(f"Completed signups count: {completed_signups}, signup limit: {signup_limit}, require_invite_code: {require_invite_code}")
                    
                logger.info(f"Invite code requirement check: limit={signup_limit}, completed_signups={completed_signups if 'completed_signups' in locals() else 'cached'}, required={require_invite_code}")
            except Exception as e:
                logger.error(f"Error checking user count against signup limit: {e}")
                # Default to requiring invite code on error (safer default)
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
        
        # Extract session_id from the request body
        try:
            body = await request.json()
            session_id = body.get("session_id")
        except Exception:
            session_id = None # Fallback if body is not JSON or session_id is missing
            
        if not session_id:
             logger.error("session_id missing from /session request body. Cannot generate device hash.")
             return SessionResponse(
                success=False, 
                message="Internal server error - session_id is missing", 
                token_refresh_needed=False,
                require_invite_code=require_invite_code
             )

        device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id, session_id)
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        device_location_str = f"{city}, {country_code}" if city and country_code else country_code or "Unknown" # More detailed location string

        # Step 3: Check if this device hash is already known for the user
        known_device_hashes = await directus_service.get_user_device_hashes(user_id)
        is_new_device_hash = device_hash not in known_device_hashes
        logger.info(f"Session: Device hash {device_hash[:8]}... is new: {is_new_device_hash} for user {user_id[:6]}...")

        # Step 3b: Check for sudden country change within the same session
        # This detects suspicious location changes (e.g., VPN switch, session hijacking)
        # even when the device hash is already known from a previous session.
        # The last_session_country is stored in the user cache on every successful session validation.
        is_country_change = False
        previous_country = user_data.get("last_session_country")
        if previous_country and country_code and previous_country != country_code:
            # Country has changed since the last session validation
            # Only flag if both countries are real (not "Local" or "Unknown")
            if previous_country not in ("Local", "Unknown", None) and country_code not in ("Local", "Unknown", None):
                is_country_change = True
                logger.warning(
                    f"[SECURITY] Country change detected for user {user_id[:6]}...: "
                    f"{previous_country} -> {country_code}. Triggering re-authentication."
                )

        # Step 4: Perform re-auth check if it's a new device OR a suspicious country change
        # Three scenarios require re-authentication:
        # 1. New device hash + 2FA (OTP) enabled -> require OTP code
        # 2. New device hash + passkeys configured -> require passkey assertion
        # 3. Country change detected (even for known devices) -> require passkey/2FA to prevent session hijacking
        # This prevents account takeover via stolen session cookies from a different location
        re_auth_reason = None
        if is_country_change:
            re_auth_reason = "location_change"
        elif is_new_device_hash:
            re_auth_reason = "new_device"

        if is_new_device_hash or is_country_change:
            tfa_enabled = user_data.get("tfa_enabled", False)
            
            if tfa_enabled:
                logger.warning(f"Re-auth triggered for user {user_id[:6]} (reason: {re_auth_reason}, 2FA enabled).")
                # Return minimal user info needed for the re-auth screen
                minimal_user_info = UserResponse(
                    id=user_id,
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
                    invoice_counter=user_data.get("invoice_counter", 0),
                    # Low balance auto top-up fields (use defaults for minimal user info)
                    # Use bool() to convert None to False, as .get() only uses default when key doesn't exist, not when value is None
                    auto_topup_low_balance_enabled=bool(user_data.get("auto_topup_low_balance_enabled", False)),
                    auto_topup_low_balance_threshold=user_data.get("auto_topup_low_balance_threshold"),
                    auto_topup_low_balance_amount=user_data.get("auto_topup_low_balance_amount"),
                    auto_topup_low_balance_currency=user_data.get("auto_topup_low_balance_currency")
                )
                return SessionResponse(
                    success=False, # Indicate session is not fully valid *yet*
                    message="Device verification required",
                    re_auth_required="2fa",
                    re_auth_reason=re_auth_reason, # "new_device" or "location_change"
                    user=minimal_user_info, # Send user info for the verification screen
                    require_invite_code=require_invite_code
                )
            
            # Check if user has passkeys configured (passkey-only users without OTP 2FA)
            # This ensures passkey users also re-authenticate on new devices to prevent account takeover
            try:
                has_passkeys = False
                hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                passkeys = await directus_service.get_user_passkeys(hashed_user_id)
                has_passkeys = len(passkeys) > 0 if passkeys else False
            except Exception as e:
                logger.error(f"Error checking passkeys for user {user_id[:6]}: {e}", exc_info=True)
                has_passkeys = False
            
            if has_passkeys:
                logger.warning(f"Re-auth triggered for user {user_id[:6]} (reason: {re_auth_reason}, passkeys configured).")
                minimal_user_info = UserResponse(
                    id=user_id,
                    username=user_data.get("username"),
                    is_admin=user_data.get("is_admin", False),
                    credits=user_data.get("credits", 0),
                    profile_image_url=user_data.get("profile_image_url"),
                    tfa_app_name=user_data.get("tfa_app_name"),
                    tfa_enabled=False, # Passkey user may not have OTP 2FA
                    last_opened=user_data.get("last_opened"),
                    consent_privacy_and_apps_default_settings=bool(user_data.get("consent_privacy_and_apps_default_settings")),
                    consent_mates_default_settings=bool(user_data.get("consent_mates_default_settings")),
                    language=user_data.get("language", 'en'),
                    darkmode=user_data.get("darkmode", False),
                    invoice_counter=user_data.get("invoice_counter", 0),
                    auto_topup_low_balance_enabled=bool(user_data.get("auto_topup_low_balance_enabled", False)),
                    auto_topup_low_balance_threshold=user_data.get("auto_topup_low_balance_threshold"),
                    auto_topup_low_balance_amount=user_data.get("auto_topup_low_balance_amount"),
                    auto_topup_low_balance_currency=user_data.get("auto_topup_low_balance_currency")
                )
                return SessionResponse(
                    success=False, # Indicate session is not fully valid *yet*
                    message="Passkey verification required",
                    re_auth_required="passkey",
                    re_auth_reason=re_auth_reason, # "new_device" or "location_change"
                    user=minimal_user_info, # Send user info for the verification screen
                    require_invite_code=require_invite_code
                )
            
            logger.debug(f"User {user_id[:6]} does not require re-auth (no 2FA and no passkeys).")
        else:
             logger.debug(f"User {user_id[:6]} does not require re-auth (device already known, no country change).")


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

        # Step 5b: Update last_session_country in cache for country change detection on next session check.
        # This is stored AFTER re-auth checks pass, so the country is only updated when the session is fully validated.
        # This ensures that if a user switches country and re-authenticates, the new country is stored.
        if country_code and country_code not in ("Local", "Unknown", None):
            try:
                await cache_service.update_user(user_id, {"last_session_country": country_code})
                logger.debug(f"Updated last_session_country to {country_code} for user {user_id[:6]}...")
            except Exception as e:
                logger.error(f"Failed to update last_session_country for user {user_id}: {e}", exc_info=True)

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
                # Get stay_logged_in preference from cached user data
                # Default to False if not present (for backward compatibility with old sessions)
                stay_logged_in = user_data.get("stay_logged_in", False)
                logger.info(f"Retrieved stay_logged_in={stay_logged_in} from cache for user {user_id[:6]}... (key present: {'stay_logged_in' in user_data})")
                # Calculate cookie max_age based on stay_logged_in preference
                # 30 days = 2592000 seconds (for mobile Safari compatibility)
                # 24 hours = 86400 seconds (default SESSION_TTL)
                cookie_max_age = 2592000 if stay_logged_in else cache_service.SESSION_TTL
                logger.info(f"Refreshing cookies with max_age={cookie_max_age} seconds ({'30 days' if stay_logged_in else '24 hours'})")
                
                # Determine cookie domain for cross-subdomain authentication
                # Returns None for localhost (development), ".domain.com" for production subdomains
                cookie_domain = get_cookie_domain(request)
                if cookie_domain:
                    logger.info(f"Refreshing cookies with domain={cookie_domain} for cross-subdomain authentication")
                
                # Determine if we should use secure cookies based on environment
                # Safari iOS strictly enforces that Secure=True cookies can ONLY be set over HTTPS
                # In development (localhost), we must set Secure=False to allow HTTP cookies
                is_dev = os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"
                use_secure_cookies = not is_dev  # Only use Secure=True in production (HTTPS)
                
                if is_dev:
                    logger.info("Development environment detected - using non-secure cookies for Safari iOS compatibility")
                
                new_refresh_token = None
                for name, value in auth_data["cookies"].items():
                    if name == "directus_refresh_token":
                        new_refresh_token = value
                    cookie_name = name.replace("directus_", "auth_") if name.startswith("directus_") else name
                    
                    # Build cookie parameters
                    # Safari/iOS cookie requirements:
                    # - SameSite=Lax works for same-site subdomains (app.domain.com <-> api.domain.com)
                    # - Secure=True ONLY on HTTPS (Safari strictly enforces this)
                    # - Secure=False on HTTP/localhost (development mode)
                    # - Path=/ ensures cookie is available to all endpoints
                    cookie_params = {
                        "key": cookie_name,
                        "value": value,
                        "httponly": True,
                        "secure": use_secure_cookies,  # False in dev (HTTP), True in prod (HTTPS)
                        "samesite": "lax",  # Lax works for same-site subdomains (Safari compatible)
                        "max_age": cookie_max_age,
                        "path": "/"
                    }

                    # Only set domain parameter for cross-subdomain scenarios
                    # This enables cookie sharing between app.domain.com and api.domain.com
                    if cookie_domain:
                        cookie_params["domain"] = cookie_domain

                    response.set_cookie(**cookie_params)

                if new_refresh_token:
                    # Update cache with new token, keeping existing user data
                    # CRITICAL: Ensure stay_logged_in is preserved in user_data before caching
                    if "stay_logged_in" not in user_data:
                        user_data["stay_logged_in"] = stay_logged_in
                        logger.warning(f"stay_logged_in was missing from user_data for user {user_id[:6]}..., restored from retrieved value: {stay_logged_in}")
                    # Use extended TTL for cache when stay_logged_in is True
                    cache_ttl = cookie_max_age if stay_logged_in else cache_service.SESSION_TTL
                    await cache_service.set_user(user_data, refresh_token=new_refresh_token, ttl=cache_ttl)
                    logger.info(f"Token refreshed successfully for user {user_id[:6]}... with stay_logged_in={stay_logged_in}, cache_ttl={cache_ttl}s")
                else:
                    logger.warning(f"No new refresh token in response for user {user_id[:6]}")
            else:
                logger.error(f"Failed to refresh token for user {user_id[:6]}")
                # If refresh fails, treat session as invalid
                return SessionResponse(success=False, message="Session expired", token_refresh_needed=True, require_invite_code=require_invite_code)
        
        # Step 9: Ensure user data is properly cached with token association
        # This is critical for WebSocket authentication to work
        # Use extended TTL if stay_logged_in is True
        # Get stay_logged_in from user_data (may have been set during token refresh above)
        stay_logged_in = user_data.get("stay_logged_in", False)
        cache_ttl = 2592000 if stay_logged_in else cache_service.SESSION_TTL
        logger.info(f"Ensuring user data is properly cached with token for user {user_id[:6]}... (stay_logged_in={stay_logged_in}, TTL: {cache_ttl}s)")
        # Ensure stay_logged_in is in user_data before caching
        if "stay_logged_in" not in user_data:
            user_data["stay_logged_in"] = stay_logged_in
            logger.warning(f"stay_logged_in was missing from user_data for user {user_id[:6]}..., setting to default: {stay_logged_in}")
        await cache_service.set_user(user_data, refresh_token=refresh_token, ttl=cache_ttl)
        
        # Step 10: Return successful session validation
        logger.info(f"Session valid for user {user_id[:6]}. Returning user data.")
        return SessionResponse(
            success=True,
            message="Session valid",
            user=UserResponse( # Map from user_data dictionary
                id=user_id,
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
                # Low balance auto top-up fields
                # Use bool() to convert None to False, as .get() only uses default when key doesn't exist, not when value is None
                auto_topup_low_balance_enabled=bool(user_data.get("auto_topup_low_balance_enabled", False)),
                auto_topup_low_balance_threshold=user_data.get("auto_topup_low_balance_threshold"),
                auto_topup_low_balance_amount=user_data.get("auto_topup_low_balance_amount"),
                auto_topup_low_balance_currency=user_data.get("auto_topup_low_balance_currency")
            ),
            token_refresh_needed=False,
            require_invite_code=require_invite_code,
            ws_token=refresh_token  # Return token for WebSocket auth (Safari iOS compatibility)
        )

    except Exception as e:
        logger.error(f"Session check error: {str(e)}", exc_info=True)
        return SessionResponse(success=False, message="Session error", token_refresh_needed=False, require_invite_code=require_invite_code)
