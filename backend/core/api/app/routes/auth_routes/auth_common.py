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
        if not user_data:
            logger.info("No session data in cache for token")
            # Return token here so caller might attempt Directus refresh if applicable
            return False, {}, refresh_token, "authentication_failed"

        user_id = user_data.get("user_id")
        if not user_id:
            logger.warning("Invalid user data in cache - missing user_id")
            # Return token here as well
            return False, {}, refresh_token, "authentication_failed"

        # If device verification is required
        if require_known_device:
            # Generate simplified device fingerprint hash
            device_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
            
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
