from fastapi import Request, HTTPException, status
import logging
from typing import Tuple, Dict, Any, Optional

from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def verify_authenticated_user(
    request: Request,
    cache_service: CacheService,
    directus_service: DirectusService,
    require_known_device: bool = True
) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """
    Verify that a user is authenticated and their session is valid.
    Also verifies that the device is known if required.
    
    Args:
        request: The FastAPI request object
        cache_service: The cache service instance
        directus_service: The directus service instance
        require_known_device: Whether to require that the device is known
        
    Returns:
        Tuple containing:
            - Success (bool): True if authentication is valid
            - User data (dict): User data from cache
            - Refresh token (str): The refresh token used
    """
    try:
        # Get refresh token from cookies
        refresh_token = request.cookies.get("auth_refresh_token")
        if not refresh_token:
            logger.info("No refresh token provided")
            return False, {}, None

        # Get user data from cache using refresh token
        user_data = await cache_service.get_user_by_token(refresh_token)
        if not user_data:
            logger.info("No session data in cache for token")
            return False, {}, refresh_token
        
        user_id = user_data.get("user_id")
        if not user_id:
            logger.info("Invalid user data - missing user_id")
            return False, {}, refresh_token
            
        # If device verification is required
        if require_known_device:
            device_fingerprint = get_device_fingerprint(request)
            
            # Check if device is in cache
            device_cache_key = f"{cache_service.USER_DEVICE_KEY_PREFIX}{user_id}:{device_fingerprint}"
            existing_device = await cache_service.get(device_cache_key)
            
            if existing_device is None:
                # Not in cache, check database as fallback
                device_in_db = await directus_service.check_user_device(user_id, device_fingerprint)
                if not device_in_db:
                    logger.warning(f"Unknown device attempting to access authenticated endpoint: {device_fingerprint}")
                    return False, {}, refresh_token
                
                # Device is in DB but not cache - update cache
                client_ip = get_client_ip(request)
                import time
                current_time = int(time.time())
                await cache_service.set(
                    device_cache_key,
                    {
                        "loc": "Unknown",  # We don't have location info at this point
                        "first": current_time,
                        "recent": current_time
                    },
                    ttl=cache_service.USER_TTL
                )
        
        # If we reached here, authentication is valid
        return True, user_data, refresh_token
        
    except Exception as e:
        logger.error(f"Authentication verification error: {str(e)}", exc_info=True)
        return False, {}, None

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
