from fastapi import APIRouter, Depends, Request, Response, Cookie
import logging
import time
import hashlib
from typing import Optional, Tuple
from app.schemas.auth import RequestEmailCodeRequest, RequestEmailCodeResponse, CheckEmailCodeRequest, CheckEmailCodeResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.compliance import ComplianceService
from app.services.limiter import limiter
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip
from app.utils.invite_code import validate_invite_code
from app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_metrics_service, get_compliance_service
from app.routes.auth_routes.auth_utils import verify_allowed_origin, validate_username, validate_password
from app.tasks.celery_config import app as celery_app

router = APIRouter()
logger = logging.getLogger(__name__)
event_logger = logging.getLogger("app.events")
logger.setLevel(logging.INFO)

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
        
        # Log compliance event for account creation and consents
        # IP, device fingerprint, and location are intentionally NOT logged here
        compliance_service.log_user_creation(
            user_id=user_id,
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
            refresh_token = None
            for name, value in auth_data["cookies"].items():
                if name == "directus_refresh_token":
                    refresh_token = value
                    cookie_name = "auth_refresh_token"
                elif name == "directus_session_token":
                    # Skip setting the session token cookie
                    continue
                else:
                    cookie_name = name
                    
                response.set_cookie(
                    key=cookie_name,
                    value=value,
                    httponly=True,
                    secure=True,
                    samesite="strict",
                    max_age=86400  # 24 hours
                )

            # Cache the session data if we have a refresh token
            if refresh_token:
                # Cache standardized user data
                # Note: token_hash and cache_key are handled internally by set_user
                cached_data = {
                    "user_id": user_id,
                    "username": signup_username,
                    "is_admin": is_admin,
                    "credits": 0,
                    "profile_image_url": None, # Assuming profile image is not set on creation
                    "last_opened": "/signup/step-3",
                    # Use vault_key_id from the user_data returned by create_user
                    "vault_key_id": user_data["vault_key_id"],
                    "token_expiry": int(time.time()) + 86400
                }

                # Use set_user to cache both session and user data
                await cache_service.set_user(user_data=cached_data, user_id=user_id, refresh_token=refresh_token, ttl=86400)
                logger.info("Session and user data cached successfully")

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
