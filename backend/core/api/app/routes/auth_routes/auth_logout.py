from fastapi import APIRouter, Depends, Request, Response, Cookie
import logging
import hashlib
from typing import Optional
from backend.core.api.app.schemas.auth import LogoutResponse
from backend.core.api.app.services.directus import DirectusService # No longer need chat_methods here
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService # Import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_compliance_service, get_encryption_service # Add get_encryption_service
from backend.core.api.app.services.compliance import ComplianceService
import time
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip # Updated imports
from backend.core.api.app.tasks.celery_config import app as celery_app # Import the Celery app instance

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service), # Add EncryptionService
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),  # Hidden from API docs - internal use only
    directus_refresh_token: Optional[str] = Cookie(None, include_in_schema=False)  # Also try original directus name - hidden from API docs
):
    """
    Log out the current user by clearing session cookies, invalidating the session,
    and persisting cached drafts to Directus.
    """
    # Add clear request log at INFO level
    logger.info("Processing logout request")
    
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

            # If we have the user_id, persist drafts and then check if this was the last active device
            if user_id:
                user_tokens_key = f"user_tokens:{user_id}"
                current_tokens_map = await cache_service.get(user_tokens_key) or {}
                
                token_found_in_list = False
                if token_hash in current_tokens_map:
                    token_found_in_list = True
                    del current_tokens_map[token_hash]
                
                is_last_device_logout = not current_tokens_map

                if is_last_device_logout:
                    logger.info(f"User {user_id[:6]}... logging out. Last active session. Persisting drafts.")
                    draft_tasks = []
                    try:
                        all_user_chat_ids = await cache_service.get_chat_ids_versions(user_id)
                        if all_user_chat_ids:
                            logger.debug(f"Found {len(all_user_chat_ids)} chats for user {user_id[:6]}... to check for drafts (last device).")

                        for chat_id_to_check in all_user_chat_ids:
                            cached_draft_data = await cache_service.get_user_draft_from_cache(user_id, chat_id_to_check)
                            if not cached_draft_data:
                                continue

                            encrypted_content, version = cached_draft_data
                            if encrypted_content is None and version == 0:
                                logger.debug(f"Skipping empty/initial draft for user {user_id[:6]}..., chat {chat_id_to_check} (last device).")
                                continue

                            logger.debug(f"Dispatching persistence task for user {user_id[:6]}..., chat {chat_id_to_check}, version {version} (last device).")
                            task_result = celery_app.send_task(
                                name='app.tasks.persistence_tasks.persist_chat_and_draft_on_logout',
                                kwargs={
                                    'hashed_user_id': hashlib.sha256(user_id.encode()).hexdigest(), # Hash user_id
                                    'chat_id': chat_id_to_check,
                                    'encrypted_draft_content': encrypted_content,
                                    'draft_version': version
                                },
                                queue='persistence'
                            )
                            draft_tasks.append(task_result)
                            logger.debug(f"Queued draft persistence task {task_result.id} for chat {chat_id_to_check}")
                    except Exception as e_dispatch:
                        logger.error(f"Error dispatching draft persistence tasks for user {user_id[:6]}... on last device logout: {e_dispatch}", exc_info=True)

                    # CRITICAL: Wait for draft persistence tasks to complete before deleting cache
                    # This ensures drafts are persisted to Directus before cache deletion
                    if draft_tasks:
                        logger.info(f"Waiting for {len(draft_tasks)} draft persistence task(s) to complete before deleting cache...")
                        import asyncio
                        # Wait up to 10 seconds for tasks to complete
                        max_wait_time = 10.0
                        start_time = time.time()
                        for task_result in draft_tasks:
                            try:
                                # Check task status with timeout
                                elapsed = time.time() - start_time
                                remaining_time = max(0, max_wait_time - elapsed)
                                if remaining_time <= 0:
                                    logger.warning("Timeout waiting for draft persistence tasks. Proceeding with cache deletion.")
                                    break
                                
                                # Use asyncio.to_thread to run blocking get() call in thread pool
                                # This allows us to wait for task completion without blocking the event loop
                                await asyncio.to_thread(task_result.get, timeout=remaining_time)
                                logger.debug(f"Draft persistence task {task_result.id} completed")
                            except Exception as task_error:
                                logger.warning(f"Draft persistence task {task_result.id} may not have completed: {task_error}")
                        
                        elapsed = time.time() - start_time
                        logger.info(f"Waited {elapsed:.2f}s for draft persistence tasks. Proceeding with cache deletion.")
                    else:
                        logger.debug("No draft persistence tasks to wait for.")

                    # Last device cache cleanup (AFTER drafts are persisted)
                    if await cache_service.has_pending_orders(user_id):
                        logger.warning(f"User {user_id[:6]}... has pending orders. Skipping user cache deletion on last device logout.")
                    else:
                        await cache_service.delete_user_cache(user_id)
                        await cache_service.clear_user_cache_primed_flag(user_id)
                        logger.info(f"Cleared all user-related cache (including devices and primed_flag) for user {user_id[:6]}... (last device logout)")
                
                elif token_found_in_list: # Not the last device, but token was in list and removed. current_tokens_map is not empty.
                    await cache_service.set(user_tokens_key, current_tokens_map, ttl=604800)  # 7 days
                    logger.info(f"User {user_id[:6]}... logged out. Other devices active ({len(current_tokens_map)} remaining). Drafts kept in cache.")
                
                else: # Token not found in list, and list was not empty initially (is_last_device_logout is False, token_found_in_list is False)
                    logger.warning(f"Token {token_hash[:6]}... for user {user_id[:6]}... was not in their active token list, but other tokens exist ({len(current_tokens_map)}). Drafts kept in cache. Token list unchanged by this specific token's logout.")
        
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
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),  # Hidden from API docs - internal use only
    directus_refresh_token: Optional[str] = Cookie(None)
):
    """
    Log out all sessions for the current user
    """
    logger.info("Processing logout-all request")
    
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
            logger.warning("User ID not found in cache for logout-all request")
            
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
                await cache_service.clear_user_cache_primed_flag(user_id) # Clear primed flag
                logger.info(f"Cleared all user-related cache (including primed_flag) for user {user_id[:6]}... (logout all)")
        
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
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False)  # Hidden from API docs - internal use only
):
    """
    Special logout endpoint for policy violations - aggressively cleans up all user data
    """
    logger.info("Processing policy violation logout")
    
    # Initialize device_hash to None
    device_hash = None
    client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)

    # Get deletion reason from request body
    try:
        body = await request.json()
        reason = body.get("reason", "unknown")
        details = body.get("details", {})
    except Exception:
        reason = "unknown"
        details = {}
    
    # Clear all authentication cookies
    for cookie_name in ["auth_refresh_token", "auth_access_token"]:
        response.delete_cookie(
            key=cookie_name,
            httponly=True,
            secure=True,
            samesite="lax"  # Match the setting used when creating cookies
        )
    
    # If we have a refresh token, get user data and clean up thoroughly
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        session_key = f"session:{token_hash}"
        
        # Get user ID from session cache before deleting
        session_data = await cache_service.get(session_key)
        if session_data and "user_id" in session_data:
            user_id = session_data["user_id"]

            # Generate device hash using the retrieved user_id
            device_hash, _, _, _, _, _, _, _ = generate_device_fingerprint_hash(request, user_id=user_id)

            # Log the policy violation logout
            compliance_service.log_account_deletion(
                user_id=user_id,
                deletion_type="policy_violation",
                reason=reason or "frontend_initiated_violation",
                ip_address=client_ip,
                device_fingerprint=device_hash, # Use generated device_hash
                details={
                    "timestamp": int(time.time()),
                    **details
                }
            )
            
            # Clear all user-related cache entries (sessions, profile, devices)
            await cache_service.delete_user_cache(user_id)
            await cache_service.clear_user_cache_primed_flag(user_id) # Clear primed flag
            logger.info(f"Cleared all user-related cache for user {user_id} (policy violation, including primed_flag)")
            
        elif session_data: # If session_data exists but no user_id (shouldn't happen, but safety)
             # Still delete the session if it exists
            await cache_service.delete(session_key)
            logger.warning(f"Cleared session cache {session_key} but user_id was missing (policy violation)")
            # Log without user_id or device_hash if user_id is not available
            compliance_service.log_account_deletion(
                user_id="unknown", # Log as unknown user
                deletion_type="policy_violation",
                reason=reason or "frontend_initiated_violation",
                ip_address=client_ip,
                device_fingerprint=None, # No user_id to salt, so no device_hash
                details={
                    "timestamp": int(time.time()),
                    **details
                }
            )
        else:
             # If no session data was found for the token
             logger.warning(f"No session data found for token hash {token_hash} during policy violation logout.")
             # Log without user_id or device_hash if no session data
             compliance_service.log_account_deletion(
                user_id="unknown", # Log as unknown user
                deletion_type="policy_violation",
                reason=reason or "frontend_initiated_violation",
                ip_address=client_ip,
                device_fingerprint=None, # No user_id to salt, so no device_hash
                details={
                    "timestamp": int(time.time()),
                    **details
                }
            )
    
    return {"success": True, "message": "Policy violation logout completed"}
