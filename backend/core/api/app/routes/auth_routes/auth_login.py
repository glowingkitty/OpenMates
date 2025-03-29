from fastapi import APIRouter, Depends, Request, Response
import logging
import time
import hashlib
import pyotp # Added for 2FA verification
from fastapi import HTTPException, status # Added for error handling
from app.schemas.auth import LoginRequest, LoginResponse
from app.schemas.user import UserResponse # Added for constructing partial user response
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService # Added for decrypting 2FA secret
from app.services.metrics import MetricsService
from app.services.compliance import ComplianceService
from app.services.limiter import limiter
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip
from app.routes.auth_routes.auth_dependencies import (
    get_directus_service, get_cache_service, get_metrics_service, 
    get_compliance_service, get_encryption_service # Added encryption service dependency
)
from app.routes.auth_routes.auth_utils import verify_allowed_origin
import json
from typing import Optional
# from app.models.user import User # No longer directly used here

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
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service) # Inject encryption service
):
    """
    Authenticate a user, handle 2FA if enabled, and create a session.
    Accepts optional tfa_code for the second step of 2FA login.
    """
    logger.info(f"Processing /login request for email: {login_data.email[:2]}***")
    
    try:
        # Get device fingerprint and location for tracking
        device_fingerprint = get_device_fingerprint(request)
        client_ip = get_client_ip(request)
        device_location = get_location_from_ip(client_ip)
        
        # Step 1: Validate email and password
        password_valid, auth_data, message = await directus_service.login_user(
            email=login_data.email,
            password=login_data.password
        )
        
        metrics_service.track_login_attempt(password_valid)
        
        if not password_valid or not auth_data:
            # Log failed password attempt
            exists_result, user_data_for_log, _ = await directus_service.get_user_by_email(login_data.email)
            if exists_result and user_data_for_log:
                compliance_service.log_auth_event(
                    event_type="login_failed", 
                    user_id=user_data_for_log.get("id"), 
                    ip_address=client_ip, 
                    status="failed", 
                    details={"reason": "invalid_credentials"}
                )
            return LoginResponse(success=False, message=message or "Invalid credentials")

        # Password is valid, now check for 2FA
        user = auth_data.get("user", {})
        user_id = user.get("id")
        if not user_id:
            logger.error("User ID missing after successful password validation.")
            return LoginResponse(success=False, message="Internal server error: User ID missing.")

        # Fetch complete user profile to check for 2FA secret
        profile_success, user_profile, profile_message = await directus_service.get_user_profile(user_id)
        if not profile_success or not user_profile:
            logger.error(f"Failed to fetch profile for user {user_id}: {profile_message}")
            return LoginResponse(success=False, message="Failed to retrieve user profile.")
        
        # Merge profile into user object for consistency
        user.update(user_profile)
        auth_data["user"] = user # Ensure auth_data has the full profile

        encrypted_tfa_secret = user_profile.get("encrypted_tfa_secret")
        tfa_enabled = bool(encrypted_tfa_secret)
        
        logger.info(f"User {user_id[:6]}... 2FA enabled: {tfa_enabled}")

        user_profile["consent_privacy_and_apps_default_settings"] = bool(user_profile.get("consent_privacy_and_apps_default_settings"))
        user_profile["consent_mates_default_settings"] = bool(user_profile.get("consent_mates_default_settings"))

        # --- Scenario 1: 2FA Not Enabled ---
        if not tfa_enabled:
            logger.info("2FA not enabled, proceeding with standard login finalization.")
            # Finalize login (set cookies, cache user, etc.)
            await finalize_login_session(
                response, user, auth_data, cache_service, compliance_service, 
                directus_service, device_fingerprint, device_location, client_ip
            )

            # Corrected return statement
            return LoginResponse(
                success=True,
                message="Login successful",
                user=UserResponse(
                    **user_profile, 
                    tfa_enabled=tfa_enabled
                ) 
            )
            # Removed nested return

        # --- 2FA IS Enabled ---
        
        # --- Scenario 2: 2FA Enabled, Code NOT Provided (First Step) ---
        if not login_data.tfa_code:
            logger.info("2FA enabled, code not provided. Returning tfa_required=True.")
            # Return minimal user info needed for the 2FA screen, using valid defaults for required fields
            minimal_user_info = UserResponse(
                username="",  # Default empty string
                is_admin=False, # Default False
                credits=0,      # Default 0
                profile_image_url=None, # Optional field
                tfa_app_name=user_profile.get("tfa_app_name"), # Send app name if available
                last_opened=None, # Optional field
                tfa_enabled=True # Explicitly set required field
            )
            return LoginResponse(
                success=True,
                message="2FA required", 
                tfa_required=True,
                user=minimal_user_info
            )
            
        # --- Scenario 3: 2FA Enabled, Code IS Provided (Second Step) ---
        logger.info("2FA enabled, code provided. Verifying code...")
        try:
            vault_key_id = user_profile.get("vault_key_id")
            if not vault_key_id:
                raise ValueError("Vault key ID missing for 2FA decryption.")
                
            # Decrypt using the user's key, as it's now encrypted with user key during setup
            decrypted_secret = await encryption_service.decrypt_with_user_key(
                encrypted_tfa_secret, vault_key_id
            )
            
            if not decrypted_secret:
                 raise ValueError("Failed to decrypt 2FA secret.")

            totp = pyotp.TOTP(decrypted_secret)
            if not totp.verify(login_data.tfa_code):
                logger.warning(f"Invalid 2FA code provided for user {user_id}")
                compliance_service.log_auth_event(
                    event_type="login_failed", user_id=user_id, ip_address=client_ip, 
                    status="failed", details={"reason": "invalid_2fa_code"}
                )
                # Return error, but indicate 2FA is still required
                return LoginResponse(
                    success=False, 
                    message="Invalid 2FA code", 
                    tfa_required=True # Keep user on 2FA screen
                )
            
            # 2FA Code is valid! Finalize the login.
            logger.info("2FA code verified successfully. Finalizing login.")
            await finalize_login_session(
                response, user, auth_data, cache_service, compliance_service, 
                directus_service, device_fingerprint, device_location, client_ip
            )

            # Corrected return statement
            return LoginResponse(
                success=True,
                message="Login successful",
                user=UserResponse(
                    **user_profile, 
                    tfa_enabled=tfa_enabled
                )
            )
            # Removed nested return

        except Exception as e:
            logger.error(f"Error during 2FA verification for user {user_id}: {str(e)}", exc_info=True)
            compliance_service.log_auth_event(
                event_type="login_failed", user_id=user_id, ip_address=client_ip, 
                status="failed", details={"reason": "2fa_verification_error"}
            )
            return LoginResponse(
                success=False, 
                message="Error during 2FA verification", 
                tfa_required=True # Keep user on 2FA screen
            )

    except Exception as e:
        logger.error(f"Generic login error: {str(e)}", exc_info=True)
        metrics_service.track_login_attempt(False) # Track generic failure
        # Attempt to log compliance event if possible
        try:
            exists_result, user_data_for_log, _ = await directus_service.get_user_by_email(login_data.email)
            user_id_for_log = user_data_for_log.get("id") if exists_result and user_data_for_log else "unknown"
            compliance_service.log_auth_event(
                event_type="login_failed", user_id=user_id_for_log, ip_address=get_client_ip(request), 
                status="failed", details={"reason": "internal_error"}
            )
        except Exception as log_e:
            logger.error(f"Failed to log compliance event during generic error: {log_e}")
            
        return LoginResponse(success=False, message="An error occurred during login")


async def finalize_login_session(
    response: Response, 
    user: dict, 
    auth_data: dict, 
    cache_service: CacheService, 
    compliance_service: ComplianceService,
    directus_service: DirectusService,
    device_fingerprint: str,
    device_location: Optional[str],
    client_ip: str
):
    """
    Helper function to perform common session finalization tasks:
    - Set cookies
    - Handle device tracking/logging
    - Cache user data
    """
    logger.info(f"Finalizing login session for user {user.get('id')[:6]}...")
    refresh_token = None
    
    # Set authentication cookies
    if "cookies" in auth_data:
        logger.info(f"Setting {len(auth_data['cookies'])} cookies")
        for name, value in auth_data["cookies"].items():
            if name == "directus_refresh_token":
                refresh_token = value
            cookie_name = name
            if name.startswith("directus_"):
                cookie_name = "auth_" + name[9:]
                
            response.set_cookie(
                key=cookie_name, value=value, httponly=True, secure=True, 
                samesite="strict", max_age=cache_service.SESSION_TTL # Use TTL from cache service
            )

    user_id = user.get("id")
    if user_id:
        # Device tracking and logging
        device_cache_key = f"{cache_service.USER_DEVICE_KEY_PREFIX}{user_id}:{device_fingerprint}"
        existing_device = await cache_service.get(device_cache_key)
        is_new_device = existing_device is None
        
        if is_new_device:
            device_in_db = await directus_service.check_user_device(user_id, device_fingerprint)
            is_new_device = not device_in_db

        if is_new_device:
            compliance_service.log_auth_event(
                event_type="login_new_device", user_id=user_id, ip_address=client_ip, 
                status="success", details={"device_fingerprint": device_fingerprint, "location": device_location}
            )
            # TODO: Send notification email about new device login
        
        # Update device in cache and Directus
        current_time = int(time.time())
        if is_new_device:
            await cache_service.set(
                device_cache_key, 
                {"loc": device_location, "first": current_time, "recent": current_time},
                ttl=cache_service.USER_TTL
            )
        elif existing_device:
            existing_device["recent"] = current_time
            await cache_service.set(device_cache_key, existing_device, ttl=cache_service.USER_TTL)
        
        await directus_service.update_user_device(
            user_id=user_id, device_fingerprint=device_fingerprint, device_location=device_location
        )

        # Update last online timestamp in Directus
        await directus_service.update_user(user_id, {"last_online_timestamp": str(current_time)})

        # Cache user data and update token list
        if refresh_token:
            # Prepare standardized user data (using the already merged 'user' dict)
            user_data_to_cache = {
                "user_id": user.get("id"),
                "username": user.get("username"),
                "is_admin": user.get("is_admin"),
                "credits": user.get("credits"),
                "profile_image_url": user.get("profile_image_url"),
                "tfa_app_name": user.get("tfa_app_name"),
                "tfa_enabled": bool(user.get("encrypted_tfa_secret")), # Add tfa_enabled status
                "last_opened": user.get("last_opened"),
                "vault_key_id": user.get("vault_key_id"),
                "last_online_timestamp": current_time, # Add last online timestamp
                # Add boolean consent flags to cache data, deriving safely from user dict
                "consent_privacy_and_apps_default_settings": bool(user.get("consent_privacy_and_apps_default_settings")),
                "consent_mates_default_settings": bool(user.get("consent_mates_default_settings"))
            }
            await cache_service.set_user(user_data_to_cache, refresh_token=refresh_token)

            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            user_tokens_key = f"user_tokens:{user_id}"
            current_tokens = await cache_service.get(user_tokens_key) or {}
            current_tokens[token_hash] = int(time.time())
            await cache_service.set(user_tokens_key, current_tokens, ttl=cache_service.SESSION_TTL * 7)
            logger.info(f"Updated token list for user {user_id[:6]}... ({len(current_tokens)} active)")
    
    logger.info("Login session finalization complete.")