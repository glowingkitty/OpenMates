from fastapi import APIRouter, Depends, Request, Response, Cookie
import logging
import hashlib
from typing import Optional
from app.schemas.auth import LogoutResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_compliance_service
from app.services.compliance import ComplianceService
import time
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip

router = APIRouter()
logger = logging.getLogger(__name__)

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
            # user_key = f"user_token:{token_hash}" # No longer needed

            # Get user_id from session cache before deleting it
            session_data = await cache_service.get(cache_key)
            user_id = session_data.get("user_id") if session_data else None

            # Attempt to logout from Directus
            success, message = await directus_service.logout_user(refresh_token)
            if not success:
                logger.warning(f"Directus logout failed: {message}")

            # Remove this token's session cache
            await cache_service.delete(cache_key)
            # await cache_service.delete(user_key) # No longer needed
            logger.info(f"Removed session cache for token {token_hash[:6]}...{token_hash[-6:]}")

            # If we have the user_id, check if this was the last active device
            if user_id:
                user_tokens_key = f"user_tokens:{user_id}"
                current_tokens = await cache_service.get(user_tokens_key) or {}
                
                # Remove this token from the user's tokens
                if token_hash in current_tokens:
                    del current_tokens[token_hash]
                    
                    # If this was the last token, remove user-specific caches and the token list
                    if not current_tokens:
                       # Check for pending orders before clearing cache
                       if await cache_service.has_pending_orders(user_id):
                           logger.warning(f"User {user_id[:6]}... has pending orders. Skipping user cache deletion on logout.")
                       else:
                           # Call the comprehensive cache clearing function which includes devices
                           await cache_service.delete_user_cache(user_id)
                           logger.info(f"Cleared all user-related cache (including devices) for user {user_id[:6]}... (last device logout)")

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
            
            # Check for pending orders before clearing cache
            if await cache_service.has_pending_orders(user_id):
                logger.warning(f"User {user_id[:6]}... has pending orders. Skipping user cache deletion on logout-all.")
            else:
                # Clear all user-related cache entries (sessions, profile, devices)
                await cache_service.delete_user_cache(user_id)
                logger.info(f"Cleared all user-related cache for user {user_id[:6]}... (logout all)")
        
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

@router.post("/policy-violation-logout")
async def policy_violation_logout(
    request: Request,
    response: Response,
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token")
):
    """
    Special logout endpoint for policy violations - aggressively cleans up all user data
    """
    logger.info("Processing policy violation logout")
    
    # Get device information for compliance logging
    device_fingerprint = get_device_fingerprint(request)
    client_ip = get_client_ip(request)
    
    # Get deletion reason from request body
    try:
        body = await request.json()
        reason = body.get("reason", "unknown")
        details = body.get("details", {})
    except:
        reason = "unknown"
        details = {}
    
    # Clear all authentication cookies
    for cookie_name in ["auth_refresh_token", "auth_access_token"]:
        response.delete_cookie(
            key=cookie_name,
            httponly=True,
            secure=True,
            samesite="strict"
        )
    
    # If we have a refresh token, get user data and clean up thoroughly
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        session_key = f"session:{token_hash}"
        
        # Get user ID from session cache before deleting
        session_data = await cache_service.get(session_key)
        if session_data and "user_id" in session_data:
            user_id = session_data["user_id"]
            
            # Log the policy violation logout
            compliance_service.log_account_deletion(
                user_id=user_id,
                deletion_type="policy_violation",
                reason=reason or "frontend_initiated_violation",
                ip_address=client_ip,
                device_fingerprint=device_fingerprint,
                details={
                    "timestamp": int(time.time()),
                    **details
                }
            )
            
            # Clear all user-related cache entries (sessions, profile, devices)
            await cache_service.delete_user_cache(user_id)
            logger.info(f"Cleared all user-related cache for user {user_id} (policy violation)")
            
        elif session_data: # If session_data exists but no user_id (shouldn't happen, but safety)
             # Still delete the session if it exists
            await cache_service.delete(session_key)
            logger.warning(f"Cleared session cache {session_key} but user_id was missing (policy violation)")
        else:
             # If no session data was found for the token
             logger.warning(f"No session data found for token hash {token_hash} during policy violation logout.")
    
    return {"success": True, "message": "Policy violation logout completed"}
