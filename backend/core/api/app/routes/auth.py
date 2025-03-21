from fastapi import APIRouter, HTTPException, Depends, status, Request, Response, Cookie
import logging
import time  # Add time module import
from typing import Optional, Tuple
import regex  # Use regex module instead of re
import json  # Add json import
from app.schemas.auth import InviteCodeRequest, InviteCodeResponse, RequestEmailCodeRequest, RequestEmailCodeResponse, CheckEmailCodeRequest, CheckEmailCodeResponse, LoginRequest, LoginResponse, LogoutResponse, SessionResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.compliance import ComplianceService  # Add compliance service import
from app.services.limiter import limiter
from app.utils.invite_code import validate_invite_code
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip  # Add device fingerprinting utilities

# Import the Celery task directly from the tasks module
from app.tasks.celery_config import app as celery_app

# Add new import for session response schema
from app.schemas.auth import SessionResponse

# IMPORTANT INSTRUCTION START (DO NOT DELETE/MODIFY)
#
# LOGGING PRIVACY RULES
# 1. NEVER LOG SENSITIVE USER DATA under normal circumstances:
#    - IP addresses
#    - User IDs
#    - Email addresses
#    - Names
#    - Usernames
#    - Passwords
#
# 2. COMPLIANCE EXCEPTION: For EU/Germany legal requirements, the following events:
#    - Successful/failed login
#    - Signup
#    - Consent to terms
#    - Password change
#    - Email address change
#    - 2FA change
#    - Account deletion
#
# 3. FOR COMPLIANCE LOGS ONLY, record:
#    - IP address
#    - User ID
#    - Action type
#    - Timestamp
#
# 4. RETENTION & STORAGE:
#    - PRIMARY STORAGE: Compliance logs remain in Grafana for 48 hours
#    - BACKUP PROCEDURE: After 48 hours, logs are automatically:
#        a) Encrypted and transferred to Hetzner S3
#        b) Deleted from Grafana
#    - LONG-TERM RETENTION: Encrypted logs in Hetzner S3 are permanently deleted after 1 year
#    - ACCESS CONTROLS: Only authorized security personnel may access archived logs
#    - DOCUMENTATION: All automatic transfers and deletions must be logged in a separate audit system
#
# IMPORTANT INSTRUCTION END (DO NOT DELETE/MODIFY)

router = APIRouter(
    prefix="/v1/auth",
    tags=["Authentication"]
)

logger = logging.getLogger(__name__)
event_logger = logging.getLogger("app.events")

# Ensure the logger is configured to show INFO logs
logger.setLevel(logging.INFO)

# Remove in-memory storage and use cache_service instead

def get_directus_service():
    from main import directus_service
    return directus_service

def get_cache_service():
    from main import cache_service
    return cache_service

def get_metrics_service():
    from main import metrics_service
    return metrics_service

def get_compliance_service():
    from app.services.compliance import ComplianceService
    return ComplianceService()

def get_email_template_service():
    from app.services.email_template import EmailTemplateService
    return EmailTemplateService()

async def verify_allowed_origin(request: Request):
    """
    Security dependency to verify the request originates from an allowed origin.
    This prevents direct API access to auth endpoints that should only be used by the frontend.
    """
    origin = request.headers.get("origin")
    allowed_origins = request.app.state.allowed_origins
    
    if not origin or origin not in allowed_origins:
        logger.warning(f"Unauthorized origin access to auth endpoint: {request.url.path}, Origin: {origin}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Authentication endpoints can only be accessed from authorized applications"
        )
    
    return True

@router.post("/check_invite_token_valid", response_model=InviteCodeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def check_invite_token_valid(
    request: Request,
    invite_request: InviteCodeRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service)
):
    """
    Check if the provided invite code is valid.
    If valid, store it in a secure HTTP-only cookie.
    """
    try:
        is_valid, message, code_data = await validate_invite_code(invite_request.invite_code, directus_service, cache_service)
        metrics_service.track_invite_code_check(is_valid)
        
        if is_valid:
            # Set invite code in HTTP-only cookie
            response.set_cookie(
                key="signup_invite_code",
                value=invite_request.invite_code,
                httponly=True,
                secure=True,
                samesite="strict",
                max_age=3600  # 1 hour expiry
            )
            
            # Extract additional properties from code_data
            is_admin = code_data.get('is_admin', False) if code_data else False
            gifted_credits = code_data.get('gifted_credits') if code_data else None
            
            return InviteCodeResponse(
                valid=True, 
                message=message,
                is_admin=is_admin,
                gifted_credits=gifted_credits
            )
        else:
            return InviteCodeResponse(valid=False, message=message)
    
    except Exception as e:
        metrics_service.track_invite_code_check(False)
        logger.error(f"Error validating invite code: {str(e)}", exc_info=True)
        return InviteCodeResponse(valid=False, message="An error occurred checking the invite code")

@router.post("/request_confirm_email_code", response_model=RequestEmailCodeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("3/minute")
async def request_confirm_email_code(
    request: Request,
    email_request: RequestEmailCodeRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    signup_invite_code: Optional[str] = Cookie(None)
):
    """
    Generate and send a 6-digit confirmation code to the provided email.
    Store signup information in secure HTTP-only cookies.
    """
    try:
        # Use invite code from cookie if available, otherwise from request
        invite_code = signup_invite_code or email_request.invite_code
        
        if not invite_code:
            logger.warning(f"Missing invite code in email verification request")
            return RequestEmailCodeResponse(
                success=False, 
                message="Missing invite code. Please go back and try again.",
                error_code="MISSING_INVITE_CODE"
            )
        
        # Validate the invite code first
        is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
        if not is_valid:
            logger.warning(f"Invalid invite code used in email verification request")
            return RequestEmailCodeResponse(
                success=False, 
                message="Invalid invite code. Please go back and start again.",
                error_code="INVALID_INVITE_CODE"
            )
        
        # Check if email is already registered - IMPORTANT! Don't remove this code!
        logger.info(f"Checking if email is already registered...")
        exists_result, existing_user, error_msg = await directus_service.get_user_by_email(email_request.email)
        
        # Only log actual errors, not expected responses like "User found" or "User not found"
        if error_msg and error_msg not in ["User found", "User not found"]:
            logger.error(f"Error checking email existence: {error_msg}")
            return RequestEmailCodeResponse(
                success=False,
                message="Unable to verify email availability. Please try again later.",
                error_code="EMAIL_CHECK_ERROR"
            )
        
        # This is the critical check - if exists_result is True, the email is already registered
        if exists_result:
            logger.warning(f"Attempted to register with existing email")
            return RequestEmailCodeResponse(
                success=False,
                message="This email is already registered. Please log in instead.",
                error_code="EMAIL_ALREADY_EXISTS"
            )
            
        logger.info(f"Email check passed, not already registered")
        
        # Log that we're submitting task to Celery
        logger.info(f"Submitting email verification task to Celery")
        
        # Set cookies for all signup information
        # Set invite code (even if it's already set, to refresh expiry)
        response.set_cookie(
            key="signup_invite_code",
            value=invite_code,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=3600  # 1 hour expiry
        )
        
        # Set email
        response.set_cookie(
            key="signup_email",
            value=email_request.email,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=3600
        )
        
        # Set username if provided
        if email_request.username:
            response.set_cookie(
                key="signup_username",
                value=email_request.username,
                httponly=True,
                secure=True,
                samesite="strict",
                max_age=3600
            )
        
        # Set password if provided
        if email_request.password:
            response.set_cookie(
                key="signup_password",
                value=email_request.password,
                httponly=True,
                secure=True,
                samesite="strict",
                max_age=3600
            )
        
        # Send the task with explicit task name
        task = celery_app.send_task(
            name='app.tasks.email_tasks.generate_and_send_verification_email',
            kwargs={
                'email': email_request.email,
                'invite_code': invite_code,
                'language': email_request.language,
                'darkmode': email_request.darkmode
            },
            queue='email'
        )
        
        logger.info(f"Task {task.id} submitted to Celery")
        
        # Return success immediately, which is common for email sending endpoints
        return RequestEmailCodeResponse(
            success=True, 
            message="Verification code will be sent to your email."
        )
            
    except Exception as e:
        logger.error(f"Error requesting email verification code: {str(e)}", exc_info=True)
        return RequestEmailCodeResponse(
            success=False, 
            message="An error occurred while processing your request.",
            error_code="SERVER_ERROR"
        )

# Add these validation functions that match the frontend validation

def validate_username(username: str) -> Tuple[bool, str]:
    """Validate username according to our requirements with international character support"""
    if not username:
        return False, "Username is required"
    
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    
    if len(username) > 20:
        return False, "Username cannot be longer than 20 characters"
    
    # Check for at least one letter (including international letters)
    if not regex.search(r'\p{L}', username):
        return False, "Username must contain at least one letter"
    
    # Allow letters (including international), numbers, dots, and underscores
    if not regex.fullmatch(r'[\p{L}\p{M}0-9._]+', username):
        return False, "Username can only contain letters, numbers, dots, and underscores"
    
    return True, ""

def validate_password(password: str) -> Tuple[bool, str]:
    """Validate password according to our requirements with international character support"""
    if not password:
        return False, "Password is required"
    
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    
    if len(password) > 60:
        return False, "Password cannot be longer than 60 characters"
    
    # Check for at least one letter (including international letters)
    if not regex.search(r'\p{L}', password):
        return False, "Password must contain at least one letter"
    
    # Check for at least one number
    if not regex.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    
    # Check for at least one special character (anything not a letter or number)
    if not regex.search(r'[^\p{L}\p{N}]', password):
        return False, "Password must contain at least one special character"
    
    return True, ""

# Update the check_confirm_email_code function to include validation

@router.post("/check_confirm_email_code", response_model=CheckEmailCodeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def check_confirm_email_code(
    request: Request,
    code_request: CheckEmailCodeRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    signup_invite_code: Optional[str] = Cookie(None),
    signup_email: Optional[str] = Cookie(None),
    signup_username: Optional[str] = Cookie(None),
    signup_password: Optional[str] = Cookie(None)
):
    """
    Verify the 6-digit confirmation code for the provided email.
    If valid, create user account and log user in.
    """
    try:
        # Use email from cookie if available, otherwise from request
        email = signup_email or code_request.email
        
        # Use invite code from cookie if available, otherwise from request
        invite_code = signup_invite_code or code_request.invite_code
        
        if not email:
            logger.warning(f"Missing email in code verification request")
            return CheckEmailCodeResponse(
                success=False, 
                message="Email address not found. Please go back and try again."
            )
            
        if not invite_code:
            logger.warning(f"Missing invite code in code verification request")
            return CheckEmailCodeResponse(
                success=False, 
                message="Invite code not found. Please go back and try again."
            )
        
        # First, validate that the invite code is still valid
        is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
        if not is_valid:
            logger.warning(f"Invalid invite code used in email verification check")
            
            # Clear all signup cookies
            response.delete_cookie(key="signup_invite_code")
            response.delete_cookie(key="signup_email")
            response.delete_cookie(key="signup_username")
            response.delete_cookie(key="signup_password")
            
            return CheckEmailCodeResponse(
                success=False, 
                message="Invalid invite code. Please go back and start again."
            )

        # Get the code from cache
        cache_key = f"email_verification:{email}"
        stored_code = await cache_service.get(cache_key)
        
        # Check if we have a code for this email
        if not stored_code:
            logger.warning(f"Email verification attempted with no code on record")
            return CheckEmailCodeResponse(
                success=False, 
                message="No verification code requested for this email or code expired."
            )
        
        # Check if code matches
        if stored_code != code_request.code:
            logger.warning(f"Invalid verification code")
            return CheckEmailCodeResponse(
                success=False, 
                message="Invalid verification code. Please try again."
            )
        
        # Code is valid - remove it from cache
        await cache_service.delete(cache_key)
        
        # Log successful verification
        event_logger.info(f"Email verified successfully")
        logger.info(f"Email verified successfully")
        
        # Validate username and password
        username_valid, username_error = validate_username(signup_username)
        if not username_valid:
            logger.warning(f"Invalid username format: {username_error}")
            return CheckEmailCodeResponse(
                success=False,
                message=f"Invalid username: {username_error}"
            )
            
        password_valid, password_error = validate_password(signup_password)
        if not password_valid:
            logger.warning(f"Invalid password format: {password_error}")
            return CheckEmailCodeResponse(
                success=False,
                message=f"Invalid password: {password_error}"
            )
        
        # Extract additional information from invite code
        is_admin = code_data.get('is_admin', False) if code_data else False
        role = code_data.get('role') if code_data else None
        
        # Check if user already exists
        exists_result, existing_user, _ = await directus_service.get_user_by_email(email)
        if exists_result and existing_user:
            logger.warning(f"Attempted to register with existing email")
            
            # Clear signup cookies
            response.delete_cookie(key="signup_invite_code")
            response.delete_cookie(key="signup_email")
            response.delete_cookie(key="signup_username")
            response.delete_cookie(key="signup_password")
            
            return CheckEmailCodeResponse(
                success=False,
                message="This email is already registered. Please log in instead."
            )
        
        # Get device fingerprint and location information for compliance
        device_fingerprint = get_device_fingerprint(request)
        client_ip = get_client_ip(request)
        device_location = get_location_from_ip(client_ip)
        
        # Create the user account with device information
        success, user_data, create_message = await directus_service.create_user(
            username=signup_username,
            email=email,
            password=signup_password,
            is_admin=is_admin,
            role=role,
            device_fingerprint=device_fingerprint,
            device_location=device_location
        )
        
        if not success:
            # Check for Vault-related errors
            if "Vault request failed" in create_message:
                logger.error(f"Failed to create user due to Vault error: {create_message}")
                return CheckEmailCodeResponse(
                    success=False,
                    message="Account creation failed due to encryption service error. Please contact support."
                )
            
            logger.error(f"Failed to create user: {create_message}")
            return CheckEmailCodeResponse(
                success=False,
                message="Failed to create your account. Please try again later."
            )
        
        # User created successfully - log the compliance event and metrics
        user_id = user_data.get("id")
        
        # Track user creation in metrics
        metrics_service.track_user_creation()
        
        # Also update active users count immediately - fix the call to use positional arguments
        metrics_service.update_active_users(1, 1)  # Daily active, Monthly active
        
        # Log compliance event for account creation - only store fingerprint hash, not IP
        compliance_service.log_user_creation(
            user_id=user_id, 
            device_fingerprint=device_fingerprint,
            location=device_location,
            status="success"
        )
        
        # Add device to cache for quick lookups
        await cache_service.set(
            f"user_device:{user_id}:{device_fingerprint}", 
            {
                "loc": device_location, 
                "first": int(time.time()),
                "recent": int(time.time())
            },
            ttl=86400  # 24 hour cache
        )
        
        # Now log the user in
        login_success, auth_data, login_message = await directus_service.login_user(
            email=email,
            password=signup_password
        )

        if not login_success or not auth_data:
            logger.error(f"Failed to log in new user: {login_message}")
            return CheckEmailCodeResponse(
                success=True,
                message="Account created successfully. Please log in to continue."
            )

        # Set authentication cookies
        if auth_data and "cookies" in auth_data:
            for name, value in auth_data["cookies"].items():
                response.set_cookie(
                    key=name,
                    value=value,
                    httponly=True,
                    secure=True,
                    samesite="strict",
                    max_age=86400  # 24 hours
                )
        
        # Log the successful login for compliance
        event_logger.info(f"User logged in - ID: {user_id}")
        
        # Clear signup cookies now that we've created & logged in the user
        response.delete_cookie(key="signup_invite_code")
        response.delete_cookie(key="signup_email")
        response.delete_cookie(key="signup_username")
        response.delete_cookie(key="signup_password")
        
        # Return success with user information
        return CheckEmailCodeResponse(
            success=True,
            message="Email verified and account created successfully.",
            user={
                "id": user_id,
                "username": signup_username,
                "is_admin": is_admin,
                "last_opened": "/signup/step-3"  # Add last_opened information to the response
            }
        )
        
    except Exception as e:
        logger.error(f"Error checking email verification code: {str(e)}", exc_info=True)
        return CheckEmailCodeResponse(
            success=False, 
            message="An error occurred while verifying the code."
        )


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
    # Add clear request log at INFO level
    logger.info(f"Processing login request for email: {login_data.email[:2]}***")
    
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
            # Set authentication cookies with proper prefixes
            if "cookies" in auth_data:
                for name, value in auth_data["cookies"].items():
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
            
            # Get user ID for device tracking and compliance logging
            user = auth_data.get("user", {}) or {}
            
            if user and isinstance(user, dict):
                user_id = user.get("id")
                
                if user_id:
                    # Get credits information
                    try:
                        credits_info = await directus_service.get_user_credits(user_id)
                        if credits_info:
                            user["credits"] = credits_info
                    except Exception as e:
                        logger.error(f"Error getting credits for user {user_id}: {str(e)}")
                        user["credits"] = 0
                    
                    # Check if this device is already known (in cache)
                    cache_key = f"user_device:{user_id}:{device_fingerprint}"
                    existing_device = await cache_service.get(cache_key)
                    is_new_device = existing_device is None
                    
                    if is_new_device:
                        # Check if it's in the database but not in cache
                        device_in_db = await directus_service.check_user_device(user_id, device_fingerprint)
                        is_new_device = not device_in_db
                    
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
                        # This will be implemented later to notify users about logins from new devices
                        # Example call would be:
                        # await email_service.send_new_device_login_notification(
                        #     user_email=login_data.email,
                        #     location=device_location,
                        #     device_info=get_device_info(request),
                        #     timestamp=int(time.time())
                        # )
                    else:
                        # For normal logins (known device), only log device hash, not IP
                        compliance_service.log_auth_event_safe(
                            event_type="login",
                            user_id=user_id,
                            device_fingerprint=device_fingerprint,
                            location=device_location,
                            status="success"
                        )
                    
                    # Update device in cache
                    current_time = int(time.time())
                    if is_new_device:
                        # New device - store in cache
                        await cache_service.set(
                            cache_key, 
                            {
                                "loc": device_location, 
                                "first": current_time,
                                "recent": current_time
                            },
                            ttl=86400  # 24 hour cache
                        )
                    else:
                        # Just update the recent timestamp for existing device
                        if existing_device:
                            existing_device["recent"] = current_time
                            await cache_service.set(cache_key, existing_device, ttl=86400)
                    
                    # Update device information in Directus
                    await directus_service.update_user_device(
                        user_id=user_id,
                        device_fingerprint=device_fingerprint,
                        device_location=device_location
                    )
            
            return LoginResponse(
                success=True,
                message="Login successful",
                user=user
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
        token_to_use = refresh_token or directus_refresh_token
        
        if token_to_use:
            # Hash the token for cache operations
            import hashlib
            token_hash = hashlib.sha256(token_to_use.encode()).hexdigest()
            cache_key = f"session:{token_hash}"
            user_key = f"user_token:{token_hash}"
            
            # Get user_id from cache
            user_id = await cache_service.get(user_key)
            
            # Attempt to logout from Directus
            success, message = await directus_service.logout_user(token_to_use)
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
        token_to_use = refresh_token or directus_refresh_token
        
        if not token_to_use:
            logger.warning("No valid refresh token found in cookies for logout-all")
            return LogoutResponse(
                success=False,
                message="Not logged in"
            )
            
        # Hash the token to get user_id
        import hashlib
        token_hash = hashlib.sha256(token_to_use.encode()).hexdigest()
        user_key = f"user_token:{token_hash}"
        
        # Get user_id from cache
        user_id = await cache_service.get(user_key)
        
        if not user_id:
            logger.warning(f"User ID not found in cache for logout-all request")
            
            # Try to get user information from Directus by refreshing the token
            success, auth_data, message = await directus_service.refresh_token(token_to_use)
            
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

@router.post("/session", response_model=SessionResponse)
async def get_session(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token"),
    directus_refresh_token: Optional[str] = Cookie(None)  # Also try original directus name
):
    """
    Efficient session validation endpoint that uses cache to minimize Directus calls
    Returns session information if a valid session exists
    """
    logger.info("Processing session request")
    
    try:
        # Get device fingerprint for validation
        device_fingerprint = get_device_fingerprint(request)
        logger.info(f"Device fingerprint: {device_fingerprint}")  # Log full fingerprint for debugging
        device_location = get_location_from_ip(get_client_ip(request))
        
        # Use either our renamed cookie or the original directus cookie
        token_to_use = refresh_token or directus_refresh_token
        token_expiry = None
        
        if not token_to_use:
            logger.warning("No valid refresh token found in cookies")
            return SessionResponse(
                success=False,
                message="Not logged in",
                token_refresh_needed=False
            )
        
        # Step 1: Try to get session data from cache
        # Hash the token for cache key to avoid storing raw tokens
        import hashlib
        token_hash = hashlib.sha256(token_to_use.encode()).hexdigest()
        cache_key = f"session:{token_hash}"
        user_key = f"user_token:{token_hash}"
        
        # Log the hash (partial) to help debug consistency
        logger.info(f"Session cache lookup with key hash: {token_hash[:6]}...{token_hash[-6:]}")
        
        # Get session from cache
        cached_session = await cache_service.get(cache_key)
        cached_user_id = await cache_service.get(user_key)
        
        if cached_session:
            logger.info("✓ Found session in cache!")
            
            # Get user data from session
            user_id = cached_session.get("user_id")
            username = cached_session.get("username")
            is_admin = cached_session.get("is_admin", False)
            credits = cached_session.get("credits", 0)
            token_expiry = cached_session.get("token_expiry")
            vault_key_id = cached_session.get("vault_key_id")
            cached_devices = cached_session.get("devices", {})
            
            logger.info(f"Cached session for user: {username}, expires: {token_expiry}")
            
            # Check if this device is authorized
            device_authorized = device_fingerprint in cached_devices
            
            if not device_authorized:
                logger.warning(f"Device fingerprint {device_fingerprint} not found in cached session devices")
                # Check in directus if device exists there but not in cache
                if user_id:
                    device_in_directus = await directus_service.check_user_device(user_id, device_fingerprint)
                    if device_in_directus:
                        # Device exists in Directus but not in cache, update cache
                        logger.info("Device found in Directus but not in cache, adding to cache")
                        current_time = int(time.time())
                        if not cached_devices:
                            cached_devices = {}
                        cached_devices[device_fingerprint] = {
                            "loc": device_location,
                            "first": current_time,
                            "recent": current_time
                        }
                        # Update session in cache
                        cached_session["devices"] = cached_devices
                        await cache_service.set(cache_key, cached_session, ttl=86400)
                        device_authorized = True
                
                if not device_authorized:
                    logger.warning("Device not authorized for this session")
                    # Don't clear session - it might be valid for other devices
                    return SessionResponse(
                        success=False,
                        message="Session not valid for this device",
                        token_refresh_needed=False
                    )
            
            # Check if token is about to expire (within 5 minutes)
            current_time = int(time.time())
            token_needs_refresh = False
            
            if token_expiry and token_expiry - current_time < 300:  # Less than 5 minutes left
                logger.info(f"Token expiry approaching (expires at {token_expiry}, now {current_time}), refreshing")
                token_needs_refresh = True
            
            # If token is still valid and not about to expire, return cached data
            if token_expiry and token_expiry > current_time and not token_needs_refresh:
                # Update last access time for the device
                if cached_devices and device_fingerprint in cached_devices:
                    cached_devices[device_fingerprint]["recent"] = current_time
                    # Update the cache with the new device access time
                    cached_session["devices"] = cached_devices
                    await cache_service.set(cache_key, cached_session, ttl=86400)  # Update with 24h TTL
                
                # Return success with cached user data
                logger.info("Using cached session data - token still valid")
                return SessionResponse(
                    success=True,
                    message="Session valid",
                    user={
                        "id": user_id,
                        "username": username,
                        "is_admin": is_admin,
                        "credits": credits,
                        "last_opened": cached_session.get("last_opened")
                    },
                    token_refresh_needed=False
                )
                
            # If token needs refresh, continue to the refresh process
            logger.info(f"Cache found but token needs refreshing (expiry: {token_expiry}, now: {current_time})")
        else:
            logger.info("No session found in cache, will refresh token")
                
        # Step 2: No valid cache or token needs refresh - check with Directus
        logger.info("Calling Directus refresh_token API...")
        success, auth_data, message = await directus_service.refresh_token(token_to_use)
        
        # If successful, cache the session data
        if success and auth_data and "user" in auth_data:
            user_data = auth_data["user"]
            user_id = user_data.get("id")
            username = user_data.get("username")
            is_admin = user_data.get("is_admin", False)
            vault_key_id = user_data.get("vault_key_id")
            
            # Get user's device information
            user_devices = {}
            encrypted_devices = user_data.get("encrypted_devices")
            
            if vault_key_id and encrypted_devices:
                try:
                    # Get encryption service from app state
                    encryption_service = request.app.state.encryption_service
                    
                    # Decrypt the devices data
                    decrypted_devices = await encryption_service.decrypt_with_user_key(
                        encrypted_devices, vault_key_id
                    )
                    user_devices = json.loads(decrypted_devices) if decrypted_devices else {}
                    
                    # Check if current device is in the user's devices
                    device_authorized = device_fingerprint in user_devices
                    
                    if not device_authorized:
                        logger.warning(f"Device fingerprint {device_fingerprint} not found in user's devices")
                        # Add device if not found since token is valid
                        current_time = int(time.time())
                        user_devices[device_fingerprint] = {
                            "loc": device_location,
                            "first": current_time,
                            "recent": current_time
                        }
                        
                        # Re-encrypt and update devices
                        encrypted_updated_devices, _ = await encryption_service.encrypt_with_user_key(
                            json.dumps(user_devices), vault_key_id
                        )
                        await directus_service.update_user_devices(user_id, encrypted_updated_devices)
                        logger.info(f"Added new device {device_fingerprint} to user devices")
                    else:
                        # Update the last access time for the device
                        current_time = int(time.time())
                        user_devices[device_fingerprint]["recent"] = current_time
                        
                        # Re-encrypt and update devices
                        encrypted_updated_devices, _ = await encryption_service.encrypt_with_user_key(
                            json.dumps(user_devices), vault_key_id
                        )
                        await directus_service.update_user_devices(user_id, encrypted_updated_devices)
                        logger.info(f"Updated device {device_fingerprint} access time")
                    
                except Exception as e:
                    logger.error(f"Error processing devices: {str(e)}", exc_info=True)
                    # Continue with default empty devices if decryption fails
                    user_devices = {}
            
            # Get credits
            credits = 0
            try:
                if user_id:
                    credits = await directus_service.get_user_credits(user_id) 
            except Exception as e:
                logger.error(f"Error getting credits: {str(e)}")
            
            # Calculate token expiry time based on cookies
            cookies_dict = auth_data.get("cookies", {})
            # Assume token valid for 24 hours if we can't determine expiry
            token_expiry = int(time.time()) + 86400
            
            # Cache the session data with the NEW refresh token if provided
            new_refresh_token = None
            for name, value in cookies_dict.items():
                if name == "directus_refresh_token" or name == "auth_refresh_token":
                    new_refresh_token = value
                    break
                    
            # Use the new token for caching if available
            if new_refresh_token:
                # Update token_to_use to the new token
                token_to_use = new_refresh_token
                # Update the token hash for the cache key
                token_hash = hashlib.sha256(token_to_use.encode()).hexdigest()
                cache_key = f"session:{token_hash}"
                user_key = f"user_token:{token_hash}"
                logger.info(f"Using new token for cache. Key hash: {token_hash[:6]}...{token_hash[-6:]}")
                
                # Remove old token from cache if present and different
                if cached_session and refresh_token != new_refresh_token:
                    old_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                    old_cache_key = f"session:{old_token_hash}"
                    old_user_key = f"user_token:{old_token_hash}"
                    await cache_service.delete(old_cache_key)
                    await cache_service.delete(old_user_key)
                    logger.info(f"Deleted old token from cache: {old_token_hash[:6]}...{old_token_hash[-6:]}")
            
            # Cache the session data
            session_data = {
                "user_id": user_id,
                "username": username,
                "is_admin": is_admin,
                "credits": credits,
                "token_expiry": token_expiry,
                "vault_key_id": vault_key_id,
                "devices": user_devices,
                "last_opened": user_data.get("last_opened")
            }
            
            logger.info(f"Caching session data with TTL: 86400, expiry: {token_expiry}")
            await cache_service.set(cache_key, session_data, ttl=86400)  # 24 hour TTL
            
            # Link token to user id for logout handling
            await cache_service.set(user_key, user_id, ttl=86400)
            
            # Track all tokens for this user to enable logout-all functionality
            user_tokens_key = f"user_tokens:{user_id}"
            current_tokens = await cache_service.get(user_tokens_key) or {}
            current_tokens[token_hash] = {
                "device": device_fingerprint,
                "expiry": token_expiry
            }
            await cache_service.set(user_tokens_key, current_tokens, ttl=604800)  # 7 days
            
            # Save user_id to device mapping for quick lookups
            if user_id and device_fingerprint:
                await cache_service.set(
                    f"user_device:{user_id}:{device_fingerprint}", 
                    {
                        "loc": device_location, 
                        "first": user_devices.get(device_fingerprint, {}).get("first", int(time.time())),
                        "recent": int(time.time())
                    },
                    ttl=86400  # 24 hour cache
                )
            
            # Set new authentication cookies if received
            if "cookies" in auth_data and auth_data["cookies"]:
                for name, value in auth_data["cookies"].items():
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
            
            # Return success with user information
            return SessionResponse(
                success=True,
                message="Session authenticated",
                user={
                    "id": user_id,
                    "username": username,
                    "is_admin": is_admin,
                    "credits": credits,
                    "last_opened": user_data.get("last_opened")
                },
                token_refresh_needed=False
            )
        elif success and auth_data:
            # This is the case where we have cached user data but not a full fresh token
            user_data = auth_data.get("user", {})
            
            if user_data:
                # Return the cached user data we have
                return SessionResponse(
                    success=True,
                    message="Using cached session data",
                    user=user_data,
                    token_refresh_needed=True  # Client should try a full refresh soon
                )
            
        # If we get here, session is invalid
        return SessionResponse(
            success=False,
            message="Not logged in",
            token_refresh_needed=False
        )
            
    except Exception as e:
        logger.error(f"Error checking session: {str(e)}", exc_info=True)
        return SessionResponse(
            success=False,
            message="Session error",
            token_refresh_needed=False
        )