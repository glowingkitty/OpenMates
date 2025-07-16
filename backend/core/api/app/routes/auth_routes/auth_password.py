from fastapi import APIRouter, Depends, Request, Response
import logging
import time
import hashlib
from typing import Optional
from backend.core.api.app.schemas.auth import SetupPasswordRequest, SetupPasswordResponse
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash
from backend.core.api.app.utils.invite_code import validate_invite_code
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_metrics_service, get_compliance_service, get_encryption_service
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin, validate_username

router = APIRouter()
logger = logging.getLogger(__name__)
event_logger = logging.getLogger("app.events")

@router.post("/setup_password", response_model=SetupPasswordResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def setup_password(
    request: Request,
    setup_request: SetupPasswordRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Set up password and create user account with encrypted master key.
    This endpoint validates that the email was previously verified and creates the user account.
    """
    try:
        email = setup_request.email
        invite_code = setup_request.invite_code

        # First, validate that the invite code is still valid
        is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
        if not is_valid:
            logger.warning(f"Invalid invite code used in password setup")
            return SetupPasswordResponse(
                success=False,
                message="Invalid invite code. Please go back and start again."
            )

        # Check if email was verified by looking for verification data in cache
        verification_cache_key = f"email_verified:{email}"
        verification_data = await cache_service.get(verification_cache_key)
        
        if not verification_data:
            logger.warning(f"Password setup attempted without email verification for {email}")
            return SetupPasswordResponse(
                success=False,
                message="Email verification required. Please verify your email first."
            )

        # Validate username
        username_valid, username_error = validate_username(setup_request.username)
        if not username_valid:
            logger.warning(f"Invalid username format: {username_error}")
            return SetupPasswordResponse(
                success=False,
                message=f"Invalid username: {username_error}"
            )

        # Check if user already exists
        exists_result, existing_user, _ = await directus_service.get_user_by_email(email)
        if exists_result and existing_user:
            logger.warning(f"Attempted to register with existing email")
            return SetupPasswordResponse(
                success=False,
                message="This email is already registered. Please log in instead."
            )

        # Extract additional information from invite code
        is_admin = code_data.get('is_admin', False) if code_data else False
        role = code_data.get('role') if code_data else None

        # Create the user account
        success, user_data, create_message = await directus_service.create_user(
            username=setup_request.username,
            email=email,
            language=setup_request.language,
            darkmode=setup_request.darkmode,
            invite_code=invite_code,
            is_admin=is_admin,
            role=role,
        )

        if not success:
            logger.error(f"Failed to create user: {create_message}")
            return SetupPasswordResponse(
                success=False,
                message="Failed to create your account. Please try again later."
            )

        user_id = user_data.get("id")
        vault_key_id = user_data.get("vault_key_id")

        # Create encryption key record
        try:
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            await directus_service.create_encryption_key(
                hashed_user_id=hashed_user_id,
                login_method='password',
                encrypted_key=setup_request.encrypted_master_key,
                salt=setup_request.salt
            )
            logger.info(f"Successfully created encryption key record for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to create encryption key for user {user_id}: {e}", exc_info=True)
            return SetupPasswordResponse(
                success=False,
                message="Failed to set up account encryption. Please try again."
            )

        # Add lookup hash to user's lookup hashes
        try:
            await directus_service.add_user_lookup_hash(user_id, setup_request.lookup_hash)
            logger.info(f"Successfully added lookup hash for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to add lookup hash for user {user_id}: {e}", exc_info=True)
            return SetupPasswordResponse(
                success=False,
                message="Failed to complete account setup. Please try again."
            )

        # Generate device fingerprint and add to connected devices
        device_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
        await directus_service.add_user_device_hash(user_id, device_hash)

        # Handle Gifted Credits
        gifted_credits = code_data.get('gifted_credits')
        plain_gift_value = 0

        if gifted_credits and isinstance(gifted_credits, (int, float)) and gifted_credits > 0:
            plain_gift_value = int(gifted_credits)
            logger.info(f"Invite code included {plain_gift_value} gifted credits for user {user_id}.")
            if vault_key_id:
                try:
                    encrypted_gift_tuple = await encryption_service.encrypt_with_user_key(str(plain_gift_value), vault_key_id)
                    encrypted_gift_value = encrypted_gift_tuple[0]

                    update_success = await directus_service.update_user(
                        user_id,
                        {"encrypted_gifted_credits_for_signup": encrypted_gift_value}
                    )
                    if update_success:
                        logger.info(f"Successfully stored encrypted gifted credits for user {user_id}")
                    else:
                        logger.error(f"Failed to store encrypted gifted credits for user {user_id}")
                except Exception as encrypt_err:
                    logger.error(f"Failed to encrypt gifted credits for user {user_id}: {encrypt_err}", exc_info=True)

        # Consume invite code
        try:
            consume_success = await directus_service.consume_invite_code(invite_code, code_data)
            if consume_success:
                logger.info(f"Successfully consumed invite code {invite_code} for user {user_id}")
                await cache_service.delete(f"invite_code:{invite_code}")
            else:
                logger.error(f"Failed to consume invite code {invite_code} for user {user_id}")
        except Exception as consume_err:
            logger.error(f"Error consuming invite code {invite_code} for user {user_id}: {consume_err}", exc_info=True)

        # Track metrics
        metrics_service.track_user_creation()
        metrics_service.update_active_users(1, 1)

        # Log compliance event
        compliance_service.log_user_creation(
            user_id=user_id,
            status="success"
        )

        # Clean up verification cache
        await cache_service.delete(verification_cache_key)

        # Log successful account creation
        event_logger.info(f"User account created successfully - ID: {user_id}")

        return SetupPasswordResponse(
            success=True,
            message="Password set up successfully. Account created.",
            user={
                "id": user_id,
                "username": setup_request.username,
                "is_admin": is_admin
            }
        )

    except Exception as e:
        logger.error(f"Error setting up password: {str(e)}", exc_info=True)
        return SetupPasswordResponse(
            success=False,
            message="An error occurred while setting up your password."
        )
