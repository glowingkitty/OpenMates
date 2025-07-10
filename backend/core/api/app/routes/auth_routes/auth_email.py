from fastapi import APIRouter, Depends, Request, Response, Cookie
import logging
import time
import hashlib
import urllib.parse
from typing import Optional, Tuple
from backend.core.api.app.schemas.auth import RequestEmailCodeRequest, RequestEmailCodeResponse, CheckEmailCodeRequest, CheckEmailCodeResponse
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip, get_geo_data_from_ip, parse_user_agent # Updated imports
from backend.core.api.app.utils.invite_code import validate_invite_code
# Import EncryptionService and its getter
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_metrics_service, get_compliance_service, get_encryption_service
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin, validate_username, validate_password
from backend.core.api.app.tasks.celery_config import app as celery_app

router = APIRouter()
logger = logging.getLogger(__name__)
event_logger = logging.getLogger("app.events")

@router.post("/request_confirm_email_code", response_model=RequestEmailCodeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("3/minute")
async def request_confirm_email_code(
    request: Request,
    email_request: RequestEmailCodeRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Generate and send a 6-digit confirmation code to the provided email.
    This endpoint no longer uses cookies for state management.
    """
    try:
        invite_code = email_request.invite_code

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

        # Check if email is already registered
        logger.info(f"Checking if email is already registered...")
        exists_result, existing_user, error_msg = await directus_service.get_user_by_email(email_request.email)

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
    If valid, create user account and log user in.
    All signup data is now received in the request body.
    """
    try:
        email = code_request.email
        invite_code = code_request.invite_code

        # First, validate that the invite code is still valid
        is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
        if not is_valid:
            logger.warning(f"Invalid invite code used in email verification check")
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

        # Validate username and password from request body
        username_valid, username_error = validate_username(code_request.username)
        if not username_valid:
            logger.warning(f"Invalid username format: {username_error}")
            return CheckEmailCodeResponse(
                success=False,
                message=f"Invalid username: {username_error}"
            )

        password_valid, password_error = validate_password(code_request.password)
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
            return CheckEmailCodeResponse(
                success=False,
                message="This email is already registered. Please log in instead."
            )

        # Get language and darkmode from request body
        language = code_request.language
        darkmode = code_request.darkmode

        # Create the user account without initial device fingerprint
        success, user_data, create_message = await directus_service.create_user(
            username=code_request.username,
            email=email,
            language=language,
            darkmode=darkmode,
            password=code_request.password,
            is_admin=is_admin,
            role=role,
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

        # --- Generate device fingerprint with actual user_id and add to connected devices ---
        device_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
        device_location_str = f"{city}, {country_code}" if city and country_code else country_code or "Unknown"

        # Add device hash to Directus (it will also update cache via add_user_device_hash)
        # This function handles updating the user's connected_devices list in Directus and cache
        await directus_service.add_user_device_hash(user_id, device_hash)

        # --- Create Encryption Key Record ---
        try:
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            await directus_service.create_encryption_key(
                hashed_user_id=hashed_user_id,
                login_method='password',
                encrypted_key=code_request.encrypted_master_key,
                salt=code_request.salt
            )
            logger.info(f"Successfully created encryption key record for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to create encryption key for user {user_id}: {e}", exc_info=True)
            # This is a critical failure. We might want to roll back user creation
            # or at least flag the account for manual review.
            # For now, we'll log the error and continue, but this is a point of concern.

        vault_key_id = user_data.get("vault_key_id") # Get vault key for encryption

        # --- Handle Gifted Credits ---
        gifted_credits = code_data.get('gifted_credits')
        encrypted_gift_value = None # Initialize
        plain_gift_value = 0 # Initialize

        if gifted_credits and isinstance(gifted_credits, (int, float)) and gifted_credits > 0:
            plain_gift_value = int(gifted_credits)
            logger.info(f"Invite code included {plain_gift_value} gifted credits for user {user_id}.")
            if vault_key_id:
                try:
                    # Encrypt the gifted credits amount (as string)
                    encrypted_gift_tuple = await encryption_service.encrypt_with_user_key(str(plain_gift_value), vault_key_id)
                    encrypted_gift_value = encrypted_gift_tuple[0] # Get the ciphertext

                    # Update the user record in Directus with the encrypted value
                    update_success = await directus_service.update_user(
                        user_id,
                        {"encrypted_gifted_credits_for_signup": encrypted_gift_value}
                    )
                    if update_success:
                        logger.info(f"Successfully stored encrypted gifted credits for user {user_id} in Directus.")
                    else:
                        logger.error(f"Failed to store encrypted gifted credits for user {user_id} in Directus.")
                        # Continue signup, but gift might not be properly stored

                except Exception as encrypt_err:
                    logger.error(f"Failed to encrypt gifted credits for user {user_id}: {encrypt_err}", exc_info=True)
                    # Continue signup without storing encrypted gift if encryption fails
            else:
                 logger.error(f"Cannot encrypt gifted credits for user {user_id}: Missing vault_key_id.")
        else:
            logger.info(f"No valid gifted credits found in invite code for user {user_id}.")

        # --- Consume Invite Code ---
        try:
            consume_success = await directus_service.consume_invite_code(invite_code, code_data)
            if consume_success:
                logger.info(f"Successfully consumed invite code {invite_code} for user {user_id}.")
                # Also clear the specific invite code from cache
                await cache_service.delete(f"invite_code:{invite_code}")
            else:
                 logger.error(f"Failed to consume invite code {invite_code} for user {user_id}.")
        except Exception as consume_err:
             logger.error(f"Error consuming invite code {invite_code} for user {user_id}: {consume_err}", exc_info=True)

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

        # Now log the user in
        login_success, auth_data, login_message = await directus_service.login_user(
            email=email,
            password=code_request.password
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
                    "username": code_request.username,
                    "is_admin": is_admin,
                    "credits": 0,
                    "profile_image_url": None, # Assuming profile image is not set on creation
                    "last_opened": "/signup/secure-account", # Secure account with either password + 2fa or passkey
                    "language": language,
                    "country_code": country_code, # Use the country_code from the correctly generated fingerprint
                    "darkmode": darkmode,
                    "vault_key_id": vault_key_id,
                    "encrypted_email_address": user_data.get("encrypted_email_address"),
                    "token_expiry": int(time.time()) + 86400, # Use default TTL from CacheService
                    "gifted_credits_for_signup": plain_gift_value if plain_gift_value > 0 else None,
                    "tfa_enabled": False # Add default TFA status for new users
                }

                # Use set_user to cache both session and user data (using default TTL)
                await cache_service.set_user(user_data=cached_data, user_id=user_id, refresh_token=refresh_token, ttl=86400)
                logger.info("Session and user data cached successfully")

        # Log the successful login for compliance
        event_logger.info(f"User logged in - ID: {user_id}")

        # Return success with user information
        return CheckEmailCodeResponse(
            success=True,
            message="Email verified and account created successfully.",
            user={
                "id": user_id,
                "username": code_request.username,
                "is_admin": is_admin,
                "last_opened": "/signup/secure-account", # Secure account with either password + 2fa or passkey
            }
        )

    except Exception as e:
        logger.error(f"Error checking email verification code: {str(e)}", exc_info=True)
        return CheckEmailCodeResponse(
            success=False,
            message="An error occurred while verifying the code."
        )
