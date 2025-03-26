from fastapi import APIRouter, Depends, Request, Response
import logging
import time
import hashlib # Added
from app.schemas.auth import LoginRequest, LoginResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.compliance import ComplianceService
from app.services.limiter import limiter
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_metrics_service, get_compliance_service
from app.routes.auth_routes.auth_utils import verify_allowed_origin
import json
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@router.post("/login", response_model=LoginResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Authenticate a user and create a session
    """
    logger.info(f"Processing /login request for email: {login_data.email[:2]}***")
    
    try:
        # Get device fingerprint and location for tracking
        device_fingerprint = get_device_fingerprint(request)
        client_ip = get_client_ip(request)
        device_location = get_location_from_ip(client_ip)
        
        success, auth_data, message = await directus_service.login_user(
            email=login_data.email,
            password=login_data.password
        )
        
        metrics_service.track_login_attempt(success)
        
        if success and auth_data:
            user = auth_data.get("user", {})
            if user:
                # We already have user data from login, fetch complete profile
                logger.info("Fetching complete profile for user")
                user_id = user.get("id")
                if user_id:
                    success, user_profile, _ = await directus_service.get_user_profile(user_id)
                    if success and user_profile:
                        logger.info("Successfully fetched user profile")
                        # Update user data with complete profile
                        user.update(user_profile)
                        auth_data["user"] = user

            # Set authentication cookies
            if "cookies" in auth_data:
                logger.info(f"Setting {len(auth_data['cookies'])} cookies")
                refresh_token = None
                for name, value in auth_data["cookies"].items():
                    if name == "directus_refresh_token":
                        refresh_token = value
                    # Rename cookies to use our prefix instead of directus prefix
                    cookie_name = name
                    if name.startswith("directus_"):
                        cookie_name = "auth_" + name[9:]  # Replace "directus_" with "auth_"
                        
                    response.set_cookie(
                        key=cookie_name,
                        value=value,
                        httponly=True,
                        secure=True,
                        samesite="strict",
                        max_age=86400  # 24 hours
                    )
            
            if user and isinstance(user, dict):
                user_id = user.get("id")
                
                if user_id:
                    # Get credits information
                    try:
                        logger.info(f"Fetching credits for user")
                        credits_info = await directus_service.get_user_credits(user_id)
                        if credits_info:
                            user["credits"] = credits_info
                            logger.info(f"Credits fetched successfully: {credits_info}")
                    except Exception as e:
                        logger.error(f"Error getting credits for user: {str(e)}")
                        user["credits"] = 0
                    
                    # Check if this device is already known (in cache)
                    device_cache_key = f"{cache_service.USER_DEVICE_KEY_PREFIX}{user_id}:{device_fingerprint}"
                    existing_device = await cache_service.get(device_cache_key)
                    is_new_device = existing_device is None
                    
                    logger.info(f"Device check - New device: {is_new_device}")
                    
                    if is_new_device:
                        # Check if it's in the database but not in cache
                        device_in_db = await directus_service.check_user_device(user_id, device_fingerprint)
                        is_new_device = not device_in_db
                        logger.info(f"Device in DB check - Still new device: {is_new_device}")

                    # For security events (new device login), log with IP and eventually send email
                    if is_new_device:
                        compliance_service.log_auth_event(
                            event_type="login_new_device",
                            user_id=user_id,
                            ip_address=client_ip,  # Include IP for new device login
                            status="success",
                            details={
                                "device_fingerprint": device_fingerprint,
                                "location": device_location
                            }
                        )
                        
                        # TODO: Send notification email about new device login
                    
                    # Update device in cache
                    current_time = int(time.time())
                    if is_new_device:
                        # New device - store in cache
                        await cache_service.set(
                            device_cache_key, 
                            {
                                "loc": device_location, 
                                "first": current_time,
                                "recent": current_time
                            },
                            ttl=cache_service.USER_TTL  # Use standardized TTL
                        )
                    else:
                        # Just update the recent timestamp for existing device
                        if existing_device:
                            existing_device["recent"] = current_time
                            await cache_service.set(device_cache_key, existing_device, ttl=cache_service.USER_TTL)
                    
                    # Update device information in Directus
                    await directus_service.update_user_device(
                        user_id=user_id,
                        device_fingerprint=device_fingerprint,
                        device_location=device_location
                    )
            
            # Cache the user data with the refresh token using the enhanced method
            if refresh_token and user:
                # Prepare standardized user data
                user_data = {
                    "user_id": user.get("id"),
                    "username": user.get("username"),
                    "is_admin": user.get("is_admin"),
                    "credits": user.get("credits"),
                    "profile_image_url": user.get("profile_image_url"),
                    "last_opened": user.get("last_opened"),
                    "vault_key_id": user.get("vault_key_id")
                }
                
                # Use the enhanced method to cache user data with token association
                await cache_service.set_user(user_data, refresh_token=refresh_token)

                # Also update the user's list of active tokens
                if user_id:
                    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                    user_tokens_key = f"user_tokens:{user_id}"
                    current_tokens = await cache_service.get(user_tokens_key) or {}
                    current_tokens[token_hash] = int(time.time())
                    # Use a longer TTL for the token list, e.g., 7 days
                    await cache_service.set(user_tokens_key, current_tokens, ttl=cache_service.SESSION_TTL * 7)
                    logger.info(f"Updated token list for user {user_id[:6]}... ({len(current_tokens)} active)")

            logger.info("Login completed successfully, returning user data")
            # Update to use UserResponse schema
            return LoginResponse(
                success=True,
                message="Login successful",
                user=UserResponse(
                    username=user.get("username"),
                    is_admin=user.get("is_admin"),
                    credits=user.get("credits"),
                    profile_image_url=user.get("profile_image_url"),
                    last_opened=user.get("last_opened")
                )
            )
        else:
            # Failed login attempt - always log IP address for security events
            exists_result, user_data, _ = await directus_service.get_user_by_email(login_data.email)
            if exists_result and user_data:
                compliance_service.log_auth_event(
                    event_type="login_failed",
                    user_id=user_data.get("id"),
                    ip_address=client_ip,  # For security events, include IP
                    status="failed",
                    details={"reason": "invalid_credentials"}
                )
                
            return LoginResponse(
                success=False,
                message=message or "Invalid credentials"
            )
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        metrics_service.track_login_attempt(False)
        return LoginResponse(
            success=False,
            message="An error occurred during login"
        )
