from fastapi import APIRouter, HTTPException, Depends, status, Request, Response, Cookie
import logging
from typing import Optional

from app.schemas.auth import InviteCodeRequest, InviteCodeResponse, RequestEmailCodeRequest, RequestEmailCodeResponse, CheckEmailCodeRequest, CheckEmailCodeResponse
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.limiter import limiter
from app.utils.invite_code import validate_invite_code

# Import the Celery task directly from the tasks module
from app.tasks.celery_config import app as celery_app

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
        is_valid, message = await validate_invite_code(invite_request.invite_code, directus_service, cache_service)
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
            return InviteCodeResponse(valid=True, message=message)
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
                message="Missing invite code. Please go back and try again."
            )
        
        # Validate the invite code first
        is_valid, message = await validate_invite_code(invite_code, directus_service, cache_service)
        if not is_valid:
            logger.warning(f"Invalid invite code used in email verification request")
            return RequestEmailCodeResponse(
                success=False, 
                message="Invalid invite code. Please go back and start again."
            )
        
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
            message="An error occurred while processing your request."
        )

@router.post("/check_confirm_email_code", response_model=CheckEmailCodeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def check_confirm_email_code(
    request: Request,
    code_request: CheckEmailCodeRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    signup_invite_code: Optional[str] = Cookie(None),
    signup_email: Optional[str] = Cookie(None),
    signup_username: Optional[str] = Cookie(None),
    signup_password: Optional[str] = Cookie(None)
):
    """
    Verify the 6-digit confirmation code for the provided email.
    Also re-verify the invite code is still valid.
    If all is valid, proceed to create the user account.
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
        is_valid, message = await validate_invite_code(invite_code, directus_service, cache_service)
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
        
        # Here we would normally create the user account
        # For now, just log that we would create it
        logger.info(f"Creating user account next... (placeholder)")
        if signup_username and signup_password:
            logger.info(f"Account creation would use username and password from cookies")
        
        # Clear all signup cookies after successful verification
        # This is important for security
        response.delete_cookie(key="signup_invite_code")
        response.delete_cookie(key="signup_email")
        response.delete_cookie(key="signup_username")
        response.delete_cookie(key="signup_password")
        
        return CheckEmailCodeResponse(
            success=True, 
            message="Email verified successfully."
        )
        
    except Exception as e:
        logger.error(f"Error checking email verification code: {str(e)}", exc_info=True)
        return CheckEmailCodeResponse(
            success=False, 
            message="An error occurred while verifying the code."
        )