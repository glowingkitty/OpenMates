from fastapi import APIRouter, Depends, Request, Response
import logging
import time
import hashlib
import base64
from backend.core.api.app.schemas.auth import RequestEmailCodeRequest, RequestEmailCodeResponse, CheckEmailCodeRequest, CheckEmailCodeResponse
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.invite_code import validate_invite_code, get_signup_requirements
from backend.core.api.app.utils.newsletter_utils import hash_email, check_ignored_email
# Import EncryptionService and its getter
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_metrics_service, get_compliance_service, get_encryption_service
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin, validate_username
from backend.core.api.app.tasks.celery_config import app as celery_app

router = APIRouter()
logger = logging.getLogger(__name__)
event_logger = logging.getLogger("app.events")

@router.post("/request_confirm_email_code", response_model=RequestEmailCodeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def request_confirm_email_code(
    request: Request,
    email_request: RequestEmailCodeRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Generate and send a 6-digit confirmation code to the provided email.
    This endpoint no longer uses cookies for state management.
    """
    try:
        invite_code = email_request.invite_code
        code_data = None
        
        # Get signup requirements based on server edition and configuration
        # SIGNUP_DOMAIN_RESTRICTION is ALWAYS enforced when set (for all server editions)
        # For self-hosted: domain restriction OR invite code required
        # For non-self-hosted: use SIGNUP_LIMIT logic
        require_invite_code, require_domain_restriction, allowed_domains = await get_signup_requirements(
            directus_service, cache_service
        )
        
        # Check domain restriction if configured (ALWAYS enforced when set, regardless of server edition)
        if require_domain_restriction and allowed_domains:
            email_parts = email_request.email.split('@')
            email_domain = email_parts[1].lower() if len(email_parts) == 2 else None
            # Domain checks intentionally compare exact domains to avoid unintended wildcard access.
            if not email_domain or email_domain not in allowed_domains:
                logger.warning(
                    "Email domain not allowed: "
                    f"{email_domain or 'invalid email format'} (allowed: {', '.join(allowed_domains)})"
                )
                return RequestEmailCodeResponse(
                    success=False,
                    message="signup.domain_not_allowed.text",
                    error_code="DOMAIN_NOT_ALLOWED"
                )
            logger.info(f"Email domain check passed: {email_domain}")
        
        # If invite code is required, validate it
        if require_invite_code:
            if not invite_code:
                logger.warning(f"Missing invite code in email verification request when required")
                return RequestEmailCodeResponse(
                    success=False,
                    message="Missing invite code. Please go back and try again.",
                    error_code="MISSING_INVITE_CODE"
                )

            # Validate the invite code
            is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
            if not is_valid:
                logger.warning(f"Invalid invite code used in email verification request")
                return RequestEmailCodeResponse(
                    success=False,
                    message="Invalid invite code. Please go back and start again.",
                    error_code="INVALID_INVITE_CODE"
                )
        else:
            logger.info(f"Invite code not required, skipping validation")
        
        # Check domain security policies (validates against encrypted restricted domains list)
        # Only check if domain security service is available (it's optional for signup validation)
        # SIGNUP_DOMAIN_RESTRICTION is handled separately above (lines 54-63)
        domain_security_service = None
        if hasattr(request.app.state, 'domain_security_service'):
            domain_security_service = request.app.state.domain_security_service
        
        # Only validate against domain security service if it's available and loaded
        # If service is not available, skip validation (allow all domains except those blocked by SIGNUP_DOMAIN_RESTRICTION)
        if domain_security_service and domain_security_service.config_loaded:
            # Validate email domain against encrypted restricted domains list
            # This only checks the restricted domains list, not platform name variations
            is_allowed, error_message = domain_security_service.validate_email_domain(email_request.email)
            if not is_allowed:
                logger.warning(f"Email domain restricted: {email_request.email} - {error_message}")
                return RequestEmailCodeResponse(
                    success=False,
                    message=error_message or "Domain not supported",
                    error_code="DOMAIN_NOT_SUPPORTED"
                )
        else:
            # Domain security service not available or not loaded - log but don't block
            # This allows signups when domain security config is not available
            logger.debug("Domain security service not available or not loaded - skipping domain security validation")
        
        # Check if email is in ignored list (before checking if registered)
        hashed_email = hash_email(email_request.email)
        is_ignored = await check_ignored_email(hashed_email, directus_service)
        if is_ignored:
            logger.info(f"Signup attempt from ignored email: {hashed_email[:16]}...")
            # Return generic error to avoid revealing that email is ignored
            return RequestEmailCodeResponse(
                success=False,
                message="Unable to process signup request. Please contact support if you believe this is an error.",
                error_code="SIGNUP_NOT_ALLOWED"
            )
        
        # Check if email is already registered
        logger.info(f"Checking if email is already registered...")
        
        exists_result, existing_user, error_msg = await directus_service.get_user_by_hashed_email(hashed_email)

        if error_msg and error_msg not in ["User found", "User not found"]:
            logger.error(f"Error checking email existence: {error_msg}")
            return RequestEmailCodeResponse(
                success=False,
                message="Unable to verify email availability. Please try again later.",
                error_code="EMAIL_CHECK_ERROR"
            )

        if exists_result:
            logger.warning(f"Attempted to register with existing email")
            return RequestEmailCodeResponse(
                success=False,
                message="This email is already registered. Please log in instead.",
                error_code="EMAIL_ALREADY_EXISTS"
            )

        logger.info(f"Email check passed, not already registered")

        logger.info(f"Submitting email verification task to Celery")

        # Send the task with explicit task name
        task = celery_app.send_task(
            name='app.tasks.email_tasks.verification_email_task.generate_and_send_verification_email',
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
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Verify the 6-digit confirmation code for the provided email.
    In the new architecture, this only verifies the email and stores verification status in cache.
    User account creation happens later in the password setup step.
    """
    try:
        email = code_request.email
        invite_code = code_request.invite_code
        code_data = None
        
        # Get signup requirements based on server edition and configuration
        # For self-hosted: domain restriction OR invite code required
        # For non-self-hosted: use SIGNUP_LIMIT logic
        require_invite_code, require_domain_restriction, allowed_domains = await get_signup_requirements(
            directus_service, cache_service
        )
        
        # If invite code is required, validate it
        if require_invite_code:
            # First, validate that the invite code is still valid
            is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
            if not is_valid:
                logger.warning(f"Invalid invite code used in email verification check")
                return CheckEmailCodeResponse(
                    success=False,
                    message="Invalid invite code. Please go back and start again."
                )
        else:
            logger.info(f"Invite code not required, skipping validation")

        # Note: Domain validation should have already happened in request_confirm_email_code
        # We don't validate here again to avoid blocking users who already received a code
        # If domain validation failed, the code would not have been sent in the first place

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
        if str(stored_code) != str(code_request.code):
            logger.warning(f"Invalid verification code.")
            return CheckEmailCodeResponse(
                success=False,
                message="Invalid verification code. Please try again."
            )

        # Code is valid - remove it from cache
        await cache_service.delete(cache_key)

        # Log successful verification
        event_logger.info(f"Email verified successfully")
        logger.info(f"Email verified successfully")

        # Validate username from request body
        username_valid, username_error = validate_username(code_request.username)
        if not username_valid:
            logger.warning(f"Invalid username format: {username_error}")
            return CheckEmailCodeResponse(
                success=False,
                message=f"Invalid username: {username_error}"
            )

        # Check if user already exists (double-check)
        # Hash the email for lookup
        email_bytes = email.encode('utf-8')
        hashed_email_buffer = hashlib.sha256(email_bytes).digest()
        hashed_email = base64.b64encode(hashed_email_buffer).decode('utf-8')
        
        exists_result, existing_user, _ = await directus_service.get_user_by_hashed_email(hashed_email)
        if exists_result and existing_user:
            logger.warning(f"Attempted to register with existing email")
            return CheckEmailCodeResponse(
                success=False,
                message="This email is already registered. Please log in instead."
            )

        # Store email verification status and signup data in cache for password setup step
        verification_data = {
            "email": email,
            "username": code_request.username,
            "invite_code": invite_code,
            "language": code_request.language,
            "darkmode": code_request.darkmode,
            "verified_at": int(time.time()),
            "code_data": code_data  # Store invite code data for later use
        }
        
        # Store verification data in cache with 30 minute expiry
        # Use hashed_email for the cache key to match the lookup in auth_password.py
        verification_cache_key = f"email_verified:{hashed_email}"
        await cache_service.set(verification_cache_key, verification_data, ttl=1800)  # 30 minutes
        
        logger.info(f"Email verification successful, stored verification data in cache")

        # Return success - user will proceed to secure account step
        return CheckEmailCodeResponse(
            success=True,
            message="Email verified successfully. Please continue to secure your account."
        )

    except Exception as e:
        logger.error(f"Error checking email verification code: {str(e)}", exc_info=True)
        return CheckEmailCodeResponse(
            success=False,
            message="An error occurred while verifying the code."
        )
