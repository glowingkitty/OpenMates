from fastapi import APIRouter, Depends, Request, Response, Cookie
import logging
import hashlib
from typing import Optional
from app.schemas.auth import LogoutResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service

router = APIRouter()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token"),
    directus_refresh_token: Optional[str] = Cookie(None)  # Also try original directus name
):
    """
    Log out the current user by clearing session cookies and invalidating the session
    """
    # Add clear request log at INFO level
    logger.info(f"Processing logout request")
    
    try:
        # Use either our renamed cookie or the original directus cookie
        refresh_token = refresh_token or directus_refresh_token
        
        if refresh_token:
            # Hash the token for cache operations
            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            cache_key = f"session:{token_hash}"
            user_key = f"user_token:{token_hash}"
            
            # Get user_id from cache
            user_id = await cache_service.get(user_key)
            
            # Attempt to logout from Directus
            success, message = await directus_service.logout_user(refresh_token)
            if not success:
                logger.warning(f"Directus logout failed: {message}")
            
            # Remove this token from cache
            await cache_service.delete(cache_key)
            await cache_service.delete(user_key)
            logger.info(f"Removed token {token_hash[:6]}...{token_hash[-6:]} from cache")
            
            # If we have the user_id, check if this was the last active device
            if user_id:
                user_tokens_key = f"user_tokens:{user_id}"
                current_tokens = await cache_service.get(user_tokens_key) or {}
                
                # Remove this token from the user's tokens
                if token_hash in current_tokens:
                    del current_tokens[token_hash]
                    
                    # If this was the last token, remove the entire user tokens cache
                    if not current_tokens:
                        await cache_service.delete(user_tokens_key)
                        logger.info(f"Removed all token references for user {user_id[:6]}... (last device)")
                    else:
                        # Update the user tokens cache with the token removed
                        await cache_service.set(user_tokens_key, current_tokens, ttl=604800)  # 7 days
                        logger.info(f"Updated token list for user {user_id[:6]}... ({len(current_tokens)} remaining)")
        
        # Clear all auth cookies regardless of server response
        for cookie in request.cookies:
            if cookie.startswith("auth_"):
                response.delete_cookie(key=cookie, httponly=True, secure=True)
        
        return LogoutResponse(
            success=True,
            message="Logged out successfully"
        )
    except Exception as e:
        logger.error(f"Logout error: {str(e)}", exc_info=True)
        
        # Still clear cookies on error
        for cookie in request.cookies:
            if cookie.startswith("auth_"):
                response.delete_cookie(key=cookie, httponly=True, secure=True)
        
        return LogoutResponse(
            success=False,
            message="An error occurred during logout"
        )

@router.post("/logout-all", response_model=LogoutResponse)
async def logout_all(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token"),
    directus_refresh_token: Optional[str] = Cookie(None)
):
    """
    Log out all sessions for the current user
    """
    logger.info(f"Processing logout-all request")
    
    try:
        # Use either our renamed cookie or the original directus cookie
        refresh_token = refresh_token or directus_refresh_token
        
        if not refresh_token:
            logger.warning("No valid refresh token found in cookies for logout-all")
            return LogoutResponse(
                success=False,
                message="Not logged in"
            )
            
        # Hash the token to get user_id
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        user_key = f"user_token:{token_hash}"
        
        # Get user_id from cache
        user_id = await cache_service.get(user_key)
        
        if not user_id:
            logger.warning(f"User ID not found in cache for logout-all request")
            
            # Try to get user information from Directus by refreshing the token
            success, auth_data, message = await directus_service.refresh_token(refresh_token)
            
            if success and auth_data and "user" in auth_data:
                user_id = auth_data["user"].get("id")
                logger.info(f"Retrieved user ID {user_id[:6]}... from token refresh")
        
        # If we have the user_id, clear all tokens
        if user_id:
            # Attempt to logout all sessions from Directus
            success, message = await directus_service.logout_all_sessions(user_id)
            if not success:
                logger.warning(f"Directus logout-all failed: {message}")
            
            # Get all tokens for this user and remove from cache
            user_tokens_key = f"user_tokens:{user_id}"
            current_tokens = await cache_service.get(user_tokens_key) or {}
            
            # Remove all tokens from cache
            for t_hash in current_tokens:
                t_cache_key = f"session:{t_hash}"
                t_user_key = f"user_token:{t_hash}"
                await cache_service.delete(t_cache_key)
                await cache_service.delete(t_user_key)
            
            # Remove the user tokens index
            await cache_service.delete(user_tokens_key)
            
            logger.info(f"Removed all {len(current_tokens)} tokens for user {user_id[:6]}...")
        
        # Clear all auth cookies for this session regardless of server response
        for cookie in request.cookies:
            if cookie.startswith("auth_"):
                response.delete_cookie(key=cookie, httponly=True, secure=True)
        
        return LogoutResponse(
            success=True,
            message="All sessions logged out successfully"
        )
    except Exception as e:
        logger.error(f"Logout-all error: {str(e)}", exc_info=True)
        
        # Still clear cookies on error
        for cookie in request.cookies:
            if cookie.startswith("auth_"):
                response.delete_cookie(key=cookie, httponly=True, secure=True)
        
        return LogoutResponse(
            success=False,
            message="An error occurred during logout-all operation"
        )
