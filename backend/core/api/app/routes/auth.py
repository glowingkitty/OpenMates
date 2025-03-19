from fastapi import APIRouter, HTTPException, Depends, status, Request, Response, Cookie
import logging
import time  # Add time module import
from typing import Optional, Tuple
import regex  # Use regex module instead of re

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
        
        if not login_success:
            logger.error(f"Failed to log in new user: {login_message}")
            return CheckEmailCodeResponse(
                success=True,
                message="Account created successfully. Please log in to continue."
            )
        
        # Set authentication cookies
        if "cookies" in auth_data:
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
                "is_admin": is_admin
            }
        )
        
    except Exception as e:
        logger.error(f"Error checking email verification code: {str(e)}", exc_info=True)
        return CheckEmailCodeResponse(
            success=False, 
            message="An error occurred while verifying the code."
        )

@router.get("/session", response_model=SessionResponse)
async def get_session(
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service)
):
    """
    Check if the user is authenticated and return user information.
    Used primarily for initializing the client-side auth state.
    """
    try:
        # Get user data from directus session
        success, user_data, message = await directus_service.get_current_user()
        
        if not success or not user_data:
            logger.debug("Session check: No authenticated user found")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated"
            )
        
        # Return user data
        return {
            "id": user_data.get("id"),
            "username": user_data.get("encrypted_username"),
            "is_admin": user_data.get("is_admin", False),
            "avatar_url": user_data.get("encrypted_profileimage_url")  # Use encrypted_profileimage_url instead
        }
    except Exception as e:
        logger.error(f"Error checking session: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
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
            # Set authentication cookies
            if "cookies" in auth_data:
                for name, value in auth_data["cookies"].items():
                    response.set_cookie(
                        key=name,
                        value=value,
                        httponly=True,
                        secure=True,
                        samesite="strict",
                        max_age=86400  # 24 hours
                    )
            
            # Get user ID for device tracking and compliance logging
            user_id = auth_data.get("user", {}).get("id")
            if user_id:
                # Check if this device is already known (in cache)
                cache_key = f"user_device:{user_id}:{device_fingerprint}"
                existing_device = await cache_service.get(cache_key)
                is_new_device = existing_device is None
                
                # For security events (new device login), log with IP
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
                user=auth_data.get("user")
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
    directus_service: DirectusService = Depends(get_directus_service)
):
    """
    Log out the current user by clearing session cookies
    """
    try:
        # Attempt to logout from Directus
        success, message = await directus_service.logout_user()
        
        # Clear all auth cookies regardless of server response
        for cookie in request.cookies:
            if cookie.startswith(("directus_", "auth_")):
                response.delete_cookie(key=cookie, httponly=True, secure=True)
        
        return LogoutResponse(
            success=True,
            message="Logged out successfully"
        )
    except Exception as e:
        logger.error(f"Logout error: {str(e)}", exc_info=True)
        
        # Still clear cookies on error
        for cookie in request.cookies:
            if cookie.startswith(("directus_", "auth_")):
                response.delete_cookie(key=cookie, httponly=True, secure=True)
        
        return LogoutResponse(
            success=False,
            message="An error occurred during logout"
        )

@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    request: Request,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    refresh_token: Optional[str] = Cookie(None, alias="directus_refresh_token")
):
    """
    Refresh the authentication token using the refresh token.
    Returns a new access token and sets it in cookies.
    """
    try:
        if not refresh_token:
            logger.warning("Token refresh attempted without refresh token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No refresh token provided"
            )
        
        # Call the DirectusService to refresh the token
        success, auth_data, message = await directus_service.refresh_token(refresh_token)
        
        if success and auth_data:
            # Set new authentication cookies
            if "cookies" in auth_data:
                for name, value in auth_data["cookies"].items():
                    response.set_cookie(
                        key=name,
                        value=value,
                        httponly=True,
                        secure=True,
                        samesite="strict",
                        max_age=86400  # 24 hours
                    )
            
            return LoginResponse(
                success=True,
                message="Token refreshed successfully",
                user=auth_data.get("user")
            )
        else:
            # Clear all auth cookies on refresh failure
            for cookie in request.cookies:
                if cookie.startswith(("directus_", "auth_")):
                    response.delete_cookie(key=cookie, httponly=True, secure=True)
                    
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=message or "Failed to refresh token"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while refreshing the token"
        )