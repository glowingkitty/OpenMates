from fastapi import APIRouter, Depends, Request, Response
import logging
import time
import hashlib
import pyotp # Added for 2FA verification
from backend.core.api.app.schemas.auth import LoginRequest, LoginResponse
from backend.core.api.app.schemas.user import UserResponse # Added for constructing partial user response
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
# generate_device_fingerprint, DeviceFingerprint, _extract_client_ip are already imported correctly
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint, DeviceFingerprint, _extract_client_ip
from backend.core.api.app.utils.device_cache import store_device_in_cache # Added for explicit caching on login
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service, get_cache_service, get_metrics_service,
    get_compliance_service, get_encryption_service
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
# Import backup code verification and hashing utilities
# Use sha_hash for cache, hash_backup_code (Argon2) for storage, verify_backup_code (Argon2) for verification
from backend.core.api.app.routes.auth_routes.auth_2fa_utils import verify_backup_code, sha_hash_backup_code 
# Import Celery app instance and specific task
from backend.core.api.app.tasks.celery_config import app # General Celery app

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/login", response_model=LoginResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
):
    """
    Authenticate a user, handle 2FA if enabled, and create a session.
    Accepts optional tfa_code for the second step of 2FA login.
    """
    logger.info(f"Processing POST /login")
    
    try:
        # Generate comprehensive device fingerprint
        # TODO: Update LoginRequest schema to include deviceSignals: Optional[Dict[str, Any]] = None
        client_signals = getattr(login_data, 'deviceSignals', None) # Safely get signals if schema updated
        current_fingerprint: DeviceFingerprint = generate_device_fingerprint(request, client_signals)
        # Extract necessary info for logging/compliance (IP is not stored in fingerprint object itself)
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None) # Get IP separately for logging
        device_location_str = f"{current_fingerprint.city}, {current_fingerprint.country_code}" if current_fingerprint.city and current_fingerprint.country_code else current_fingerprint.country_code or "Unknown"
        stable_hash = current_fingerprint.calculate_stable_hash() # Calculate stable hash

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
                    details={
                        "reason": "invalid_credentials",
                        "device_fingerprint_stable_hash": stable_hash, # Log stable hash
                        "ip_address": client_ip,
                        "location": device_location_str
                    }
                )
            return LoginResponse(success=False, message=message or "Invalid credentials")

        # Password is valid, now check for 2FA
        user = auth_data.get("user", {})
        user_id = user.get("id")
        if not user_id:
            logger.error("User ID missing after successful password validation.")
            return LoginResponse(success=False, message="Internal server error: User ID missing.")

        # Fetch standard user profile (will not contain sensitive TFA data)
        profile_success, user_profile, profile_message = await directus_service.get_user_profile(user_id)
        if not profile_success or not user_profile:
            # This profile is still needed for non-sensitive data like tfa_app_name etc.
            logger.error(f"Failed to fetch standard profile for user {user_id}: {profile_message}")
            return LoginResponse(success=False, message="Failed to retrieve user profile.")
        
        # Merge profile into user object for consistency
        user.update(user_profile)
        auth_data["user"] = user # Ensure auth_data has the full profile

        # tfa_enabled is now included directly in the profile from get_user_profile
        tfa_enabled = user_profile.get("tfa_enabled", False)
        
        logger.info(f"User {user_id[:6]}... Correctly read 2FA enabled status: {tfa_enabled}")

        user_profile["consent_privacy_and_apps_default_settings"] = bool(user_profile.get("consent_privacy_and_apps_default_settings"))
        user_profile["consent_mates_default_settings"] = bool(user_profile.get("consent_mates_default_settings"))

        # --- Scenario 1: 2FA Not Enabled ---
        if not tfa_enabled:
            logger.info("2FA not enabled, proceeding with standard login finalization.")
            # Finalize login (set cookies, cache user, etc.)
            await finalize_login_session(
                    request=request,
                    response=response,
                    user=user,
                    auth_data=auth_data,
                    cache_service=cache_service,
                    compliance_service=compliance_service,
                    directus_service=directus_service,
                    current_fingerprint=current_fingerprint, # Pass the full fingerprint object
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service
                )
            
            # Dispatch warm_user_cache task if not already primed
            last_opened_path = user_profile.get("last_opened") # This is last_opened_path_from_user_model
            if user_id:
                cache_primed = await cache_service.is_user_cache_primed(user_id)
                if not cache_primed:
                    logger.info(f"User cache not primed for {user_id}. Dispatching warm_user_cache task.")
                    if app.conf.task_always_eager is False: # Check if not running eagerly for tests
                        logger.info(f"Dispatching warm_user_cache task for user {user_id} with last_opened_path: {last_opened_path}")
                        app.send_task(
                            name='app.tasks.user_cache_tasks.warm_user_cache', # Full path to the task
                            kwargs={'user_id': user_id, 'last_opened_path_from_user_model': last_opened_path},
                            queue='user_init' # Optional: specify a queue
                        )
                        await cache_service.set_user_cache_primed_flag(user_id) # Set flag after dispatch
                    elif app.conf.task_always_eager:
                        logger.info(f"Celery is in eager mode. warm_user_cache for user {user_id} would run synchronously. Setting primed flag.")
                        # In eager mode, the task would run here. We can set the flag.
                        await cache_service.set_user_cache_primed_flag(user_id)
                    else: # Should not happen if user_id is present, but defensive
                        logger.error(f"Cannot dispatch warm_user_cache task: user_id is missing, though it was checked.")
                else:
                    logger.info(f"User cache already primed for {user_id}. Skipping warm_user_cache task.")
            else:
                logger.error(f"Cannot dispatch warm_user_cache task or check primed status: user_id is missing.")


            return LoginResponse(
                success=True,
                message="Login successful",
                user=UserResponse(
                    username=user_profile.get("username"),
                    is_admin=user_profile.get("is_admin", False),
                    credits=user_profile.get("credits", 0),
                    profile_image_url=user_profile.get("profile_image_url"),
                    last_opened=last_opened_path, # Already included
                    tfa_app_name=user_profile.get("tfa_app_name"),
                    tfa_enabled=user_profile.get("tfa_enabled", False),
                    consent_privacy_and_apps_default_settings=bool(user_profile.get("consent_privacy_and_apps_default_settings")),
                    consent_mates_default_settings=bool(user_profile.get("consent_mates_default_settings")),
                    language=user_profile.get("language", 'en'),
                    darkmode=user_profile.get("darkmode", False)
                )
            )

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
        logger.info(f"2FA enabled, code provided. Verifying code type: {login_data.code_type}...")
        
        # Ensure tfa_code is provided if we reach this stage
        if not login_data.tfa_code:
             logger.warning(f"2FA code missing in request for user {user_id} despite tfa_required being implied.")
             return LoginResponse(success=False, message="2FA code is required.", tfa_required=True)

        try:
            # --- Sub-Scenario 3a: Verify using OTP Code ---
            if login_data.code_type == "otp":
                logger.info(f"Verifying OTP code for user {user_id}...")
                
                # Fetch decrypted secret directly (bypasses cache)
                # Fetch encrypted TFA secret and vault_key_id
                user_fields = await directus_service.get_user_fields_direct(
                    user_id, ["encrypted_tfa_secret", "vault_key_id"]
                )
                encrypted_tfa_secret = user_fields.get("encrypted_tfa_secret") if user_fields else None
                vault_key_id = user_fields.get("vault_key_id") if user_fields else None

                if not encrypted_tfa_secret or not vault_key_id:
                    logger.error(f"Missing encrypted_tfa_secret or vault_key_id for user {user_id} during OTP verification.")
                    return LoginResponse(success=False, message="Error verifying 2FA code.", tfa_required=True)

                # Decrypt the TFA secret
                try:
                    decrypted_secret = await encryption_service.decrypt_with_user_key(
                        encrypted_tfa_secret, vault_key_id
                    )
                except Exception as e:
                    logger.error(f"Failed to decrypt TFA secret for user {user_id}: {str(e)}", exc_info=True)
                    return LoginResponse(success=False, message="Error verifying 2FA code.", tfa_required=True)
                
                if not decrypted_secret:
                    # Handle cases where secret isn't found or decryption failed
                    logger.error(f"Could not retrieve or decrypt TFA secret for user {user_id} during OTP verification.")
                    # Don't reveal specific error, keep user on 2FA screen
                    return LoginResponse(success=False, message="Error verifying 2FA code.", tfa_required=True)

                # Verify the code using the directly fetched secret
                totp = pyotp.TOTP(decrypted_secret)
                if not totp.verify(login_data.tfa_code):
                    logger.warning(f"Invalid OTP code provided for user {user_id}")
                    compliance_service.log_auth_event(
                        event_type="login_failed", user_id=user_id, ip_address=client_ip,
                        status="failed",
                        details={
                            "reason": "invalid_2fa_otp_code",
                            "device_fingerprint_stable_hash": stable_hash,
                            "ip_address": client_ip,
                            "location": device_location_str
                        }
                    )
                    return LoginResponse(success=False, message="Invalid verification code", tfa_required=True)
                
                # OTP Code is valid! Finalize the login.
                logger.info("OTP code verified successfully. Finalizing login.")
                await finalize_login_session(
                    request=request,
                    response=response,
                    user=user,
                    auth_data=auth_data,
                    cache_service=cache_service,
                    compliance_service=compliance_service,
                    directus_service=directus_service,
                    current_fingerprint=current_fingerprint, # Pass the full fingerprint object
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service
                )

                # Dispatch warm_user_cache task if not already primed (OTP login)
                last_opened_path_otp = user_profile.get("last_opened")
                if user_id:
                    cache_primed_otp = await cache_service.is_user_cache_primed(user_id)
                    if not cache_primed_otp:
                        logger.info(f"User cache not primed for {user_id} (OTP login). Dispatching warm_user_cache task.")
                        if app.conf.task_always_eager is False:
                            logger.info(f"Dispatching warm_user_cache task for user {user_id} (OTP login) with last_opened_path: {last_opened_path_otp}")
                            app.send_task(
                                name='app.tasks.user_cache_tasks.warm_user_cache',
                                kwargs={'user_id': user_id, 'last_opened_path_from_user_model': last_opened_path_otp},
                                queue='user_init'
                            )
                            await cache_service.set_user_cache_primed_flag(user_id) # Set flag after dispatch
                        elif app.conf.task_always_eager:
                            logger.info(f"Celery is in eager mode. warm_user_cache for user {user_id} (OTP login) would run synchronously. Setting primed flag.")
                            await cache_service.set_user_cache_primed_flag(user_id)
                        else: # Should not happen
                            logger.error(f"Cannot dispatch warm_user_cache task (OTP login): user_id is missing, though it was checked.")
                    else:
                        logger.info(f"User cache already primed for {user_id} (OTP login). Skipping warm_user_cache task.")
                else:
                    logger.error(f"Cannot dispatch warm_user_cache task or check primed status (OTP login): user_id is missing.")

                return LoginResponse(
                    success=True, message="Login successful",
                    user=UserResponse(
                        username=user_profile.get("username"),
                        is_admin=user_profile.get("is_admin", False),
                        credits=user_profile.get("credits", 0),
                        profile_image_url=user_profile.get("profile_image_url"),
                        last_opened=last_opened_path_otp,
                        tfa_app_name=user_profile.get("tfa_app_name"),
                        tfa_enabled=user_profile.get("tfa_enabled", False),
                        consent_privacy_and_apps_default_settings=bool(user_profile.get("consent_privacy_and_apps_default_settings")),
                        consent_mates_default_settings=bool(user_profile.get("consent_mates_default_settings")),
                        language=user_profile.get("language", 'en'),
                        darkmode=user_profile.get("darkmode", False)
                    )
                )

            # --- Sub-Scenario 3b: Verify using Backup Code ---
            elif login_data.code_type == "backup":
                logger.info(f"Verifying backup code for user {user_id}...")
                
                # Step 1: Calculate SHA256 hash of the provided code for cache operations
                try:
                    provided_code_sha_hash = sha_hash_backup_code(login_data.tfa_code)
                except Exception as e:
                    logger.error(f"Error SHA hashing provided backup code for user {user_id}: {e}", exc_info=True)
                    # Treat as invalid code if hashing fails
                    return LoginResponse(success=False, message="Error processing backup code.", tfa_required=True)

                # Step 2: Check cache for recently used backup code SHA hash (user-specific)
                used_code_cache_key = f"used_backup_code:{user_id}:{provided_code_sha_hash}"
                logger.info(f"Checking recently used backup code SHA hash...")
                recently_used = await cache_service.get(used_code_cache_key)

                if recently_used is not None:
                    logger.info(f"Backup code provided by user {user_id} matches a recently used code's SHA hash found in cache key.")
                    compliance_service.log_auth_event(
                        event_type="login_failed", user_id=user_id, ip_address=client_ip,
                        status="failed",
                        details={
                            "reason": "invalid_2fa_backup_code_used",
                            "device_fingerprint_stable_hash": stable_hash,
                            "ip_address": client_ip,
                            "location": device_location_str
                        }
                    )
                    return LoginResponse(success=False, message="Invalid backup code", tfa_required=True)
                
                logger.info(f"Provided backup code's SHA hash not found in recently used cache for user {user_id}.")

                # Step 3: Fetch valid backup code Argon2 hashes from Directus
                hashed_codes_from_directus = await directus_service.get_tfa_backup_code_hashes(user_id)

                # Handle cases where hashes couldn't be fetched or parsed
                if hashed_codes_from_directus is None:
                     logger.error(f"Could not retrieve or parse backup code hashes from Directus for user {user_id}.")
                     return LoginResponse(success=False, message="Error verifying backup code.", tfa_required=True)
                
                # Check if list is empty (no codes configured or all used)
                if not hashed_codes_from_directus:
                    logger.warning(f"Backup code submitted for user {user_id}, but no backup codes found/remaining in Directus.")
                    compliance_service.log_auth_event(
                        event_type="login_failed", user_id=user_id, ip_address=client_ip,
                        status="failed",
                        details={
                            "reason": "invalid_2fa_backup_code_none_remaining",
                            "device_fingerprint_stable_hash": stable_hash,
                            "ip_address": client_ip,
                            "location": device_location_str
                        }
                    )
                    return LoginResponse(success=False, message="No backup codes configured or remaining for this account.", tfa_required=True)

                # Step 4: Verify the plain text code against Directus Argon2 hashes
                logger.info(f"Attempting to verify plain text backup code against Directus Argon2 hashes. Provided code: '{login_data.tfa_code[:1]}***'") # Log only first char
                is_valid, matched_index = verify_backup_code(login_data.tfa_code, hashed_codes_from_directus)
                logger.info(f"Backup code verification result against Directus Argon2 hashes: {is_valid}, Matched index: {matched_index}")

                if not is_valid:
                    logger.warning(f"Invalid backup code provided for user {user_id} (did not match Directus hashes).")
                    compliance_service.log_auth_event(
                        event_type="login_failed", user_id=user_id, ip_address=client_ip,
                        status="failed",
                        details={
                            "reason": "invalid_2fa_backup_code",
                            "device_fingerprint_stable_hash": stable_hash,
                            "ip_address": client_ip,
                            "location": device_location_str
                        }
                    )
                    return LoginResponse(success=False, message="Invalid backup code", tfa_required=True)

                # Step 5: Backup Code is valid! Add its SHA hash to Cache, Remove Argon2 hash from Directus, Finalize login.
                logger.info(f"Backup code verified successfully against Directus Argon2 hashes for user {user_id}. Processing...")
                
                # Step 5a: Add the SHA hash of the used code to the cache with a 30-minute TTL FIRST
                # Use the SHA hash calculated before the cache check (provided_code_sha_hash)
                # Use the same cache key format as the check (used_code_cache_key)
                logger.info(f"Adding used backup code's SHA hash to cache key '{used_code_cache_key}' with 30min TTL for user {user_id}.")
                
                # Set the user-specific used code key - CRITICAL: If this fails, stop processing.
                # TTL = 30 minutes = 1800 seconds
                cache_set_success = await cache_service.set(
                    used_code_cache_key, 
                    "used",  # Value doesn't matter, just needs to exist
                    ttl=1800 
                )
                if not cache_set_success:
                     logger.error(f"CRITICAL: Failed to set cache key '{used_code_cache_key}' for recently used backup code SHA hash for user {user_id}. Aborting login.")
                     # Return an error, preventing the code from being removed from Directus
                     return LoginResponse(
                         success=False, 
                         message="Failed to update security state. Please try again.", 
                         tfa_required=True
                     )
                else:
                     logger.info(f"Successfully added used backup code's SHA hash to cache key '{used_code_cache_key}' for user {user_id}.")

                # Step 5b: Remove the used Argon2 hash from the list for Directus update
                # Use the matched_index from the Argon2 verification
                remaining_hashes_for_directus = [h for i, h in enumerate(hashed_codes_from_directus) if i != matched_index]
                remaining_count = len(remaining_hashes_for_directus) # Still useful for logging
                logger.info(f"Remaining backup codes count after removal: {remaining_count}")

                # Step 5c: Update Directus and WAIT for confirmation
                logger.info(f"Updating Directus for user {user_id} to remove used backup code hash.")
                update_directus_success = await directus_service.update_user(user_id, {
                    "tfa_backup_codes_hashes": remaining_hashes_for_directus
                })

                # Handle Directus update failure (Cache was already updated, but log this)
                if not update_directus_success:
                    logger.error(f"Failed to update backup codes in Directus for user {user_id} (Cache was updated).")
                    # Return an error and keep the user on the 2FA screen
                    return LoginResponse(
                        success=False, 
                        message="Failed to process backup code fully. Please try again.", 
                        tfa_required=True
                    )
                
                logger.info(f"Successfully updated backup codes in Directus for user {user_id}.")

                # --- Verification Complete ---
                
                # Step 5d: Send Backup Code Used Email Notification
                try:
                    # Anonymize the code (assuming format XXXX-XXXX-XXXX)
                    original_code = login_data.tfa_code
                    if len(original_code) == 14 and original_code[4] == '-' and original_code[9] == '-':
                         anonymized_code = f"{original_code[:10]}****"
                    else:
                         # Fallback if format is unexpected (log warning)
                         logger.warning(f"Backup code format unexpected for anonymization: '{original_code[:1]}***'. Using full code for anonymization fallback.")
                         anonymized_code = f"{original_code[:-4]}****" if len(original_code) > 4 else "****"

                    # Decrypt email address
                    encrypted_email_address = user.get("encrypted_email_address")
                    vault_key_id = user.get("vault_key_id")
                    decrypted_email = None
                    if encrypted_email_address and vault_key_id:
                        logger.info(f"Attempting to decrypt email for user {user_id[:6]}... for backup code used notification.")
                        try:
                            decrypted_email = await encryption_service.decrypt_with_user_key(encrypted_email_address, vault_key_id)
                            if not decrypted_email:
                                logger.error(f"Decryption failed for user {user_id[:6]}... - received None.")
                            else:
                                logger.info(f"Successfully decrypted email for user {user_id[:6]}...")
                        except Exception as decrypt_exc:
                            logger.error(f"Error decrypting email for user {user_id[:6]}...: {decrypt_exc}", exc_info=True)
                    else:
                        logger.error(f"Cannot send backup code used email for user {user_id[:6]}...: Missing encrypted_email_address or vault_key_id.")

                    # Get preferences
                    user_language = user.get("language", "en")
                    user_darkmode = user.get("darkmode", False)

                    # Dispatch task if email was decrypted
                    if decrypted_email:
                        logger.info(f"Dispatching backup code used email task for user {user_id[:6]}... (Email: {decrypted_email[:2]}***)")
                        app.send_task(
                            name='app.tasks.email_tasks.backup_code_email_task.send_backup_code_used_email',
                            kwargs={
                                'email_address': decrypted_email,
                                'anonymized_code': anonymized_code,
                                'language': user_language,
                                'darkmode': user_darkmode
                            },
                            queue='email'
                        )
                except Exception as email_task_exc:
                     logger.error(f"Failed to dispatch backup code used email task for user {user_id[:6]}: {email_task_exc}", exc_info=True)
                     # Log error but continue with login finalization

                # Step 5e: Log successful backup code use (Removed remaining count from details)
                compliance_service.log_auth_event(
                    event_type="login_success_backup_code", user_id=user_id, ip_address=client_ip,
                    status="success",
                    details={
                        "device_fingerprint_stable_hash": stable_hash,
                        "location": device_location_str # Use derived location string
                    }
                )

                # Step 5f: Finalize the login session
                await finalize_login_session(
                    request=request,
                    response=response,
                    user=user,
                    auth_data=auth_data,
                    cache_service=cache_service,
                    compliance_service=compliance_service,
                    directus_service=directus_service,
                    current_fingerprint=current_fingerprint, # Pass the full fingerprint object
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service
                )
                
                # Dispatch warm_user_cache task if not already primed (Backup code login)
                last_opened_path_backup = user_profile.get("last_opened")
                if user_id:
                    cache_primed_backup = await cache_service.is_user_cache_primed(user_id)
                    if not cache_primed_backup:
                        logger.info(f"User cache not primed for {user_id} (Backup code login). Dispatching warm_user_cache task.")
                        if app.conf.task_always_eager is False:
                            logger.info(f"Dispatching warm_user_cache task for user {user_id} (Backup code login) with last_opened_path: {last_opened_path_backup}")
                            app.send_task(
                                name='app.tasks.user_cache_tasks.warm_user_cache',
                                kwargs={'user_id': user_id, 'last_opened_path_from_user_model': last_opened_path_backup},
                                queue='user_init'
                            )
                            await cache_service.set_user_cache_primed_flag(user_id) # Set flag after dispatch
                        elif app.conf.task_always_eager:
                            logger.info(f"Celery is in eager mode. warm_user_cache for user {user_id} (Backup code login) would run synchronously. Setting primed flag.")
                            await cache_service.set_user_cache_primed_flag(user_id)
                        else: # Should not happen
                            logger.error(f"Cannot dispatch warm_user_cache task (Backup code login): user_id is missing, though it was checked.")
                    else:
                        logger.info(f"User cache already primed for {user_id} (Backup code login). Skipping warm_user_cache task.")
                else:
                    logger.error(f"Cannot dispatch warm_user_cache task or check primed status (Backup code login): user_id is missing.")

                return LoginResponse(
                    success=True, message="Login successful using backup code",
                    user=UserResponse(
                        username=user_profile.get("username"),
                        is_admin=user_profile.get("is_admin", False),
                        credits=user_profile.get("credits", 0),
                        profile_image_url=user_profile.get("profile_image_url"),
                        last_opened=last_opened_path_backup,
                        tfa_app_name=user_profile.get("tfa_app_name"),
                        tfa_enabled=user_profile.get("tfa_enabled", False),
                        consent_privacy_and_apps_default_settings=bool(user_profile.get("consent_privacy_and_apps_default_settings")),
                        consent_mates_default_settings=bool(user_profile.get("consent_mates_default_settings")),
                        language=user_profile.get("language", 'en'),
                        darkmode=user_profile.get("darkmode", False)
                    )
                )
            
            # --- Sub-Scenario 3c: Invalid Code Type ---
            else:
                logger.warning(f"Invalid code_type '{login_data.code_type}' received for user {user_id}")
                return LoginResponse(success=False, message="Invalid request type.", tfa_required=True)

        except Exception as e:
            logger.error(f"Error during 2FA verification (type: {login_data.code_type}) for user {user_id}: {str(e)}", exc_info=True)
            return LoginResponse(
                success=False, 
                message="Error during 2FA verification", 
                tfa_required=True # Keep user on 2FA screen
            )

    except Exception as e:
        logger.error(f"Generic login error: {str(e)}", exc_info=True)
        return LoginResponse(success=False, message="An error occurred during login")


async def finalize_login_session(
    request: Request, # Added request parameter
    response: Response, 
    user: dict, 
    auth_data: dict, 
    cache_service: CacheService, 
    compliance_service: ComplianceService,
    directus_service: DirectusService,
    current_fingerprint: DeviceFingerprint, # Changed: Pass the full fingerprint object
    client_ip: str, # Pass IP for logging/notification context
    encryption_service: EncryptionService # Added missing dependency
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
        # --- New Device Fingerprint Handling ---
        current_stable_hash = current_fingerprint.calculate_stable_hash()
        logger.info(f"Checking device status for user {user_id[:6]}... with stable hash {current_stable_hash[:8]}...")

        # Check if this device hash is already known for the user
        stored_data = await directus_service.get_stored_device_data(user_id, current_stable_hash)
        is_new_device_hash = stored_data is None

        # Update the device record in Directus (adds if new, updates last_seen if existing)
        update_success, update_msg = await directus_service.update_user_device_record(user_id, current_fingerprint)
        if not update_success:
            logger.error(f"Failed to update device record for user {user_id}: {update_msg}")
            # Continue with login, but log the failure
        else: # If Directus update was successful
            # Explicitly cache the device fingerprint hash as known to prevent race conditions with WebSocket auth
            device_location_str_for_cache = f"{current_fingerprint.city}, {current_fingerprint.country_code}" if current_fingerprint.city and current_fingerprint.country_code else current_fingerprint.country_code or "Unknown"
            logger.info(f"Login: Explicitly caching device {current_stable_hash[:8]} for user {user_id[:6]} as known. New device to Directus: {is_new_device_hash}, Location: {device_location_str_for_cache}")
            await store_device_in_cache(
                cache_service=cache_service,
                user_id=user_id,
                device_fingerprint=current_stable_hash, # This is the hash
                device_location=device_location_str_for_cache,
                is_new_device=is_new_device_hash # Reflects if it was new to Directus before this login's update
            )

        # If it's a new device hash (to Directus, prior to this login's update), log and send notification
        if is_new_device_hash:
            logger.info(f"New device hash detected for user {user_id[:6]}...")
            # Log the event
            location_str = f"{current_fingerprint.city}, {current_fingerprint.country_code}" if current_fingerprint.city and current_fingerprint.country_code else current_fingerprint.country_code or "Unknown"
            compliance_service.log_auth_event(
                event_type="login_new_device",
                user_id=user_id,
                ip_address=client_ip, # Keep IP for context
                status="success",
                details={
                    "device_fingerprint_stable_hash": current_stable_hash,
                    "location": location_str,
                    # Removed other fingerprint details for privacy
                    # "user_agent": current_fingerprint.user_agent,
                    # "browser": f"{current_fingerprint.browser_name} {current_fingerprint.browser_version}",
                    # "os": f"{current_fingerprint.os_name} {current_fingerprint.os_version}",
                    # "device_type": current_fingerprint.device_type
                }
            )

            # Send notification email about new device login via Celery
            try:
                user_language = user.get("language", "en")
                user_darkmode = user.get("darkmode", False)

                # Decrypt email before sending task
                encrypted_email_address = user.get("encrypted_email_address")
                vault_key_id = user.get("vault_key_id")
                decrypted_email = None

                if encrypted_email_address and vault_key_id:
                    logger.info(f"Attempting to decrypt email for user {user_id[:6]}... for new device notification.")
                    try:
                        decrypted_email = await encryption_service.decrypt_with_user_key(encrypted_email_address, vault_key_id)
                        if not decrypted_email:
                            logger.error(f"Decryption failed for user {user_id[:6]}... - received None.")
                        else:
                             logger.info(f"Successfully decrypted email for user {user_id[:6]}...")
                    except Exception as decrypt_exc:
                        logger.error(f"Error decrypting email for user {user_id[:6]}...: {decrypt_exc}", exc_info=True)
                else:
                    logger.error(f"Cannot send new device email for user {user_id[:6]}...: Missing encrypted_email_address or vault_key_id in user data.")

                # Only send task if email was successfully decrypted
                if decrypted_email:
                    # Determine if IP was localhost based on fingerprint data
                    is_localhost = current_fingerprint.country_code == "Local" and current_fingerprint.city == "Local Network"

                    logger.info(f"Dispatching new device email task for user {user_id[:6]}... (Email: {decrypted_email[:2]}***) with location data.")
                    app.send_task(
                        name='app.tasks.email_tasks.new_device_email_task.send_new_device_email',
                        kwargs={
                            'email_address': decrypted_email,
                            'user_agent_string': current_fingerprint.user_agent,
                            'ip_address': client_ip, # Still send the actual IP used for lookup
                            'latitude': current_fingerprint.latitude,
                            'longitude': current_fingerprint.longitude,
                            'location_name': location_str, # Use the derived location string
                            'is_localhost': is_localhost,
                            'language': user_language,
                            'darkmode': user_darkmode
                        },
                        queue='email'
                    )
            except Exception as task_exc:
                logger.error(f"Failed to dispatch new device email task for user {user_id[:6]}: {task_exc}", exc_info=True)
        # --- End New Device Fingerprint Handling ---

        # Update last online timestamp in Directus
        current_time = int(time.time()) # Define current_time here
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
                "tfa_enabled": user.get("tfa_enabled", False), 
                "last_opened": user.get("last_opened"),
                "vault_key_id": user.get("vault_key_id"),
                "last_online_timestamp": current_time,
                "consent_privacy_and_apps_default_settings": user.get("consent_privacy_and_apps_default_settings"),
                "consent_mates_default_settings": user.get("consent_mates_default_settings"),
                "language": user.get("language", "en"),
                "darkmode": user.get("darkmode", False),
                "gifted_credits_for_signup": user.get("gifted_credits_for_signup"),
                "encrypted_email_address": user.get("encrypted_email_address"),
                "invoice_counter": user.get("invoice_counter"),
            }
            # Remove gifted_credits_for_signup if it's None or 0 before caching
            if not user_data_to_cache.get("gifted_credits_for_signup"):
                user_data_to_cache.pop("gifted_credits_for_signup", None)
                
            await cache_service.set_user(user_data_to_cache, refresh_token=refresh_token)

            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            user_tokens_key = f"user_tokens:{user_id}"
            current_tokens = await cache_service.get(user_tokens_key) or {}
            current_tokens[token_hash] = int(time.time())
            await cache_service.set(user_tokens_key, current_tokens, ttl=cache_service.SESSION_TTL * 7)
            logger.info(f"Updated token list for user {user_id[:6]}... ({len(current_tokens)} active)")
    
    logger.info("Login session finalization complete.")
