from fastapi import Request, HTTPException, status
import logging
from typing import Tuple, Dict, Any, Optional

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip, get_geo_data_from_ip, parse_user_agent # Updated imports

logger = logging.getLogger(__name__)

async def verify_authenticated_user(
    request: Request,
    cache_service: CacheService,
    directus_service: DirectusService,
    require_known_device: bool = True
) -> Tuple[bool, Dict[str, Any], Optional[str], Optional[str]]:
    """
    Verify that a user is authenticated and their session is valid.
    Optionally verifies that the device is known.
    
    This function implements a fallback mechanism: if the cache is empty but the refresh token
    is still valid (cookie hasn't expired), it will validate the token with Directus and rebuild
    the cache. This fixes the issue where users get logged out after cache expiration even when
    their cookies are still valid (e.g., on iPad/Safari after a few hours).
    
    Args:
        request: The FastAPI request object
        cache_service: The cache service instance
        directus_service: The directus service instance
        require_known_device: Whether to require that the device is known
        
    Returns:
        Tuple containing:
            - Success (bool): True if authentication is valid (ignoring device mismatch status)
            - User data (dict): User data from cache (returned even on device mismatch)
            - Refresh token (str): The refresh token used
            - Auth Status (Optional[str]): "device_mismatch", "authentication_failed", or None
    """
    try:
        # Get refresh token from cookies
        refresh_token = request.cookies.get("auth_refresh_token")
        if not refresh_token:
            logger.info("No refresh token provided")
            return False, {}, None, "authentication_failed"

        # Get user data from cache using refresh token
        user_data = await cache_service.get_user_by_token(refresh_token)
        
        # FALLBACK MECHANISM: If cache is empty, try to validate token with Directus and rebuild cache
        # This fixes the logout issue where cache expires but cookies are still valid
        if not user_data:
            logger.info("No session data in cache for token - attempting fallback validation with Directus")
            
            # Try to refresh the token with Directus - this validates the refresh token
            refresh_success, auth_data, refresh_message = await directus_service.refresh_token(refresh_token)
            
            if not refresh_success or not auth_data:
                logger.info(f"Fallback validation failed: refresh token is invalid or expired ({refresh_message})")
                return False, {}, refresh_token, "authentication_failed"
            
            # Token is valid - now get user_id from the refreshed access token
            # Extract access token from response data or cookies returned by refresh
            response_data = auth_data.get("data", {})
            cookies = auth_data.get("cookies", {})
            access_token = None
            
            # First, try to get access_token from response JSON data
            if "access_token" in response_data:
                access_token = response_data["access_token"]
                logger.debug("Found access_token in response data")
            # Fallback: try to get from cookies (Directus may set it as a cookie)
            elif not access_token:
                for cookie_name in ["directus_access_token", "access_token"]:
                    if cookie_name in cookies:
                        access_token = cookies[cookie_name]
                        logger.debug(f"Found access_token in cookie: {cookie_name}")
                        break
            
            if not access_token:
                logger.warning("Token refresh succeeded but no access token found in response data or cookies")
                return False, {}, refresh_token, "authentication_failed"
            
            # Use access token to get user_id via /users/me endpoint
            is_valid, token_user_data = await directus_service.validate_token(access_token)
            if not is_valid or not token_user_data:
                logger.warning("Failed to validate access token or get user data from /users/me")
                return False, {}, refresh_token, "authentication_failed"
            
            user_id = token_user_data.get("id")
            if not user_id:
                logger.warning("Access token valid but user_id missing from token data")
                return False, {}, refresh_token, "authentication_failed"
            
            logger.info(f"Fallback validation successful - token is valid for user {user_id[:6]}... Rebuilding cache...")
            
            # Fetch complete user profile from Directus
            profile_success, user_profile, profile_message = await directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                logger.error(f"Failed to fetch user profile during cache rebuild: {profile_message}")
                return False, {}, refresh_token, "authentication_failed"
            
            # Ensure user_id is in the profile data
            if "user_id" not in user_profile and "id" in user_profile:
                user_profile["user_id"] = user_profile["id"]
            elif "id" in user_profile:
                user_profile["user_id"] = user_profile["id"]
            
            # Rebuild cache with default TTL (24 hours) since we can't determine stay_logged_in preference
            # The session endpoint will update this with the correct TTL if stay_logged_in is known
            cache_ttl = cache_service.SESSION_TTL  # Default to 24 hours
            cache_success = await cache_service.set_user(user_profile, refresh_token=refresh_token, ttl=cache_ttl)
            
            if not cache_success:
                logger.warning(f"Failed to rebuild cache for user {user_id[:6]}... but continuing with session validation")
            
            logger.info(f"Cache rebuilt successfully for user {user_id[:6]}... (TTL: {cache_ttl}s)")
            
            # Use the rebuilt user data
            user_data = user_profile
        
        # Validate that user_data has required fields
        user_id = user_data.get("user_id") or user_data.get("id")
        if not user_id:
            logger.warning("Invalid user data - missing user_id")
            return False, {}, refresh_token, "authentication_failed"

        # If device verification is required
        if require_known_device:
            # Generate simplified device fingerprint hash
            # Note: connection_hash will be None since no session_id is available in this context
            device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
            
            # Check if device hash is known for the user
            known_device_hashes = await directus_service.get_user_device_hashes(user_id)

            if device_hash not in known_device_hashes:
                logger.warning(f"Device hash mismatch for user {user_id[:6]}... Hash: {device_hash[:8]}...")
                # Return False for is_auth, but include user_data and specific status
                return False, user_data, refresh_token, "device_mismatch"
            else:
                logger.debug(f"Device hash {device_hash[:8]}... recognized for user {user_id[:6]}...")

        # If we reached here, authentication token is valid, and device (if checked) is known
        return True, user_data, refresh_token, None

    except Exception as e:
        logger.error(f"Authentication verification error: {str(e)}", exc_info=True)
        # Return token if available from cookie, even on error
        refresh_token = request.cookies.get("auth_refresh_token")
        return False, {}, refresh_token, "authentication_failed"

def require_auth(
    request: Request, 
    cache_service: CacheService, 
    directus_service: DirectusService,
    require_known_device: bool = True
):
    """
    Dependency that can be used with FastAPI's Depends() to ensure a user is authenticated.
    Raises an HTTPException if not authenticated.
    
    Returns the user data dictionary if authentication is successful.
    """
    async def _require_auth():
        is_auth, user_data, _ = await verify_authenticated_user(
            request, 
            cache_service, 
            directus_service,
            require_known_device
        )
        
        if not is_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return user_data
    
    return _require_auth
