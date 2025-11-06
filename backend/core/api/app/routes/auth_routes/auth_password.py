from fastapi import APIRouter, Depends, Request, Response
import logging
import time
import hashlib
import os
import base64
from typing import Optional
from backend.core.api.app.schemas.auth import SetupPasswordRequest, SetupPasswordResponse
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip, get_geo_data_from_ip
from backend.core.api.app.utils.invite_code import validate_invite_code
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service, get_cache_service, get_metrics_service, get_compliance_service, get_encryption_service
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin, validate_username
from backend.core.api.app.routes.auth_routes.auth_login import finalize_login_session
from backend.core.api.app.schemas.auth import LoginRequest

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
        invite_code = setup_request.invite_code
        code_data = None
        
        # Check if invite code is required based on SIGNUP_LIMIT
        # SIGNUP_LIMIT=0 means open signup (no invite codes required)
        # SIGNUP_LIMIT>0 means require invite codes once user count reaches the limit
        signup_limit = int(os.getenv("SIGNUP_LIMIT", "0"))
        
        # Default to not requiring invite code (open signup) unless SIGNUP_LIMIT is set
        if signup_limit == 0:
            require_invite_code = False
            logger.info("SIGNUP_LIMIT is 0 - open signup enabled (invite codes not required)")
        else:
            # SIGNUP_LIMIT > 0: require invite codes when user count reaches the limit
            # Check if we have this value cached
            cached_require_invite_code = await cache_service.get("require_invite_code")
            if cached_require_invite_code is not None:
                require_invite_code = cached_require_invite_code
            else:
                # Get the total user count and compare with SIGNUP_LIMIT
                total_users = await directus_service.get_total_users_count()
                require_invite_code = total_users >= signup_limit
                # Cache this value for quick access
                await cache_service.set("require_invite_code", require_invite_code, ttl=172800)  # Cache for 48 hours
                
            logger.info(f"Invite code requirement check: limit={signup_limit}, required={require_invite_code}")
        
        # If invite code is required, validate it
        if require_invite_code:
            # First, validate that the invite code is still valid
            is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
            if not is_valid:
                logger.warning(f"Invalid invite code used in password setup")
                return SetupPasswordResponse(
                    success=False,
                    message="Invalid invite code. Please go back and start again."
                )
        else:
            logger.info(f"Invite code not required, skipping validation")

        # Check if email was verified by looking for verification data in cache
        # Use hashed_email for lookup instead of plaintext email
        verification_cache_key = f"email_verified:{setup_request.hashed_email}"
        verification_data = await cache_service.get(verification_cache_key)
        
        if not verification_data:
            logger.warning(f"Password setup attempted without email verification")
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
        # Use the hashed_email provided in the request for lookup
        exists_result, existing_user, _ = await directus_service.get_user_by_hashed_email(setup_request.hashed_email)
        if exists_result and existing_user:
            logger.warning(f"Attempted to register with existing email")
            return SetupPasswordResponse(
                success=False,
                message="This email is already registered. Please log in instead."
            )

        # Extract additional information from invite code
        is_admin = code_data.get('is_admin', False) if code_data else False
        role = code_data.get('role') if code_data else None

        # Create the user account with encrypted email
        success, user_data, create_message = await directus_service.create_user(
            username=setup_request.username,
            encrypted_email=setup_request.encrypted_email,
            user_email_salt=setup_request.user_email_salt,
            lookup_hash=setup_request.lookup_hash,
            hashed_email=setup_request.hashed_email,
            language=setup_request.language,
            darkmode=setup_request.darkmode,
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
            success = await directus_service.create_encryption_key(
                hashed_user_id=hashed_user_id,
                login_method='password',
                encrypted_key=setup_request.encrypted_master_key,
                salt=setup_request.salt,
                key_iv=setup_request.key_iv
            )
            if success:
                logger.info(f"Successfully created encryption key record for user {user_id}")
            else:
                logger.error(f"Failed to create encryption key for user {user_id}")
                return SetupPasswordResponse(
                    success=False,
                    message="Failed to set up account encryption. Please try again."
                )
        except Exception as e:
            logger.error(f"Failed to create encryption key for user {user_id}: {e}", exc_info=True)
            return SetupPasswordResponse(
                success=False,
                message="Failed to set up account encryption. Please try again."
            )

        # Lookup hash is already added during user creation
        logger.info(f"Lookup hash was added during user creation for user {user_id}")

        # Generate device fingerprint and add to connected devices
        # Note: connection_hash will be None since no session_id is available during signup
        device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
        await directus_service.add_user_device_hash(user_id, device_hash)

        # --- Handle Gifted Credits ---
        gifted_credits = code_data.get('gifted_credits') if code_data else None
        encrypted_gift_value = None  # Initialize
        plain_gift_value = 0  # Initialize

        if gifted_credits and isinstance(gifted_credits, (int, float)) and gifted_credits > 0:
            plain_gift_value = int(gifted_credits)
            logger.info(f"Invite code included {plain_gift_value} gifted credits for user {user_id}.")
            if vault_key_id:
                try:
                    # Encrypt the gifted credits amount (as string)
                    encrypted_gift_tuple = await encryption_service.encrypt_with_user_key(str(plain_gift_value), vault_key_id)
                    encrypted_gift_value = encrypted_gift_tuple[0]  # Get the ciphertext

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

        # Consume invite code if one was provided and required
        if require_invite_code and invite_code and code_data:
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

        # Login the user to get cookies for authentication
        # We need to use the hashed email and lookup hash for authentication
        auth_success, auth_data, auth_message = await directus_service.login_user_with_lookup_hash(
            hashed_email=setup_request.hashed_email,
            lookup_hash=setup_request.lookup_hash
        )
        
        if not auth_success or not auth_data:
            logger.error(f"Failed to authenticate user after creation: {auth_message}")
            # Even if authentication fails, we still return success since the user was created
            return SetupPasswordResponse(
                success=True,
                message="Account created, but automatic login failed. Please log in manually.",
                user={
                    "id": user_id,
                    "username": setup_request.username,
                    "is_admin": is_admin
                }
            )
        
        # Get client IP for logging
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        
        # Create location string for logging
        device_location_str = f"{city}, {country_code}" if city and country_code else country_code or "Unknown"
        
        # Fetch and cache user profile before calling finalize_login_session
        # This is required because finalize_login_session expects the user to be cached
        # (same logic as in /lookup endpoint)
        profile_success, user_profile, profile_message = await directus_service.get_user_profile(user_id)
        if not profile_success or not user_profile:
            logger.error(f"Failed to fetch user profile after creation: {profile_message}")
            return SetupPasswordResponse(
                success=False,
                message="Account created but profile setup failed. Please try logging in manually."
            )
        
        # Add user_email_salt to the profile since get_user_profile doesn't include it
        user_profile["user_email_salt"] = setup_request.user_email_salt
        
        # Cache the user using the same logic as the /lookup endpoint
        user_data_to_cache = {
            "user_id": user_id,
            "username": setup_request.username,
            "is_admin": is_admin,
            "credits": 0,  # Initialize credits to 0
            "profile_image_url": user_profile.get("profile_image_url"),
            "tfa_app_name": user_profile.get("tfa_app_name"),
            "tfa_enabled": user_profile.get("tfa_enabled", False),
            "last_opened": user_profile.get("last_opened"),
            "vault_key_id": user_profile.get("vault_key_id"),
            "consent_privacy_and_apps_default_settings": user_profile.get("consent_privacy_and_apps_default_settings"),
            "consent_mates_default_settings": user_profile.get("consent_mates_default_settings"),
            "language": setup_request.language,
            "darkmode": setup_request.darkmode,
            "gifted_credits_for_signup": user_profile.get("gifted_credits_for_signup"),
            "encrypted_email_address": user_profile.get("encrypted_email_address"),
            "invoice_counter": 0,  # Initialize invoice counter to 0
            "lookup_hashes": user_profile.get("lookup_hashes", []),
            "account_id": user_data.get("account_id"),  # From the original user_data
            "user_email_salt": setup_request.user_email_salt  # Include the salt
        }
        
        # Remove gifted_credits_for_signup if it's None or 0 before caching
        if not user_data_to_cache.get("gifted_credits_for_signup"):
            user_data_to_cache.pop("gifted_credits_for_signup", None)
        
        # Cache the user data (without refresh_token since finalize_login_session will handle that)
        await cache_service.set_user(user_data_to_cache)
        logger.info(f"Cached complete user profile for user {user_id} during signup")
        
        # Update user_data with cached profile data for finalize_login_session
        user_data.update(user_data_to_cache)
        
        # Create a mock LoginRequest object for finalize_login_session
        # We need this because finalize_login_session expects login_data for email decryption
        # Note: session_id is None during signup - it will be provided by the client on subsequent logins
        mock_login_data = LoginRequest(
            hashed_email=setup_request.hashed_email,
            lookup_hash=setup_request.lookup_hash,
            session_id=None,  # No session_id during signup - connection_hash will be None
            email_encryption_key=None,  # Not available during signup
            tfa_code=None,
            code_type=None,
            login_method="password",
            stay_logged_in=False  # Default to short session for signup
        )
        
        await finalize_login_session(
            request=request,
            response=response,
            user=user_data,  # Use updated user_data with cached profile
            auth_data=auth_data,
            cache_service=cache_service,
            compliance_service=compliance_service,
            directus_service=directus_service,
            current_device_hash=device_hash,
            client_ip=client_ip,
            encryption_service=encryption_service,
            device_location_str=device_location_str,
            latitude=latitude,
            longitude=longitude,
            login_data=mock_login_data  # Pass the mock login_data
        )
        
        # Add gifted credits to user data if applicable
        if plain_gift_value > 0:
            logger.info(f"Adding gifted credits ({plain_gift_value}) to user data for {user_id}")
            await cache_service.update_user(user_id, {"gifted_credits_for_signup": plain_gift_value})
        

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
