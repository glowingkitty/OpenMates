from fastapi import APIRouter, Depends, Request, Response
import logging
import time
import hashlib
import base64
import pyotp # Added for 2FA verification
from backend.core.api.app.schemas.auth import LoginRequest, LoginResponse
from backend.core.api.app.schemas.user import UserResponse # Added for constructing partial user response
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from typing import Optional
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip, get_geo_data_from_ip, parse_user_agent # Updated imports
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
        # Step 1: Check if hashed_email and lookup_hash are provided
        if not login_data.hashed_email or not login_data.lookup_hash:
            logger.warning("Login attempt without required hashed_email or lookup_hash")
            return LoginResponse(success=False, message="Invalid login request: missing required parameters")
        
        # Step 2: Authenticate user with hashed_email and lookup_hash
        auth_success, auth_data, message = await directus_service.login_user_with_lookup_hash(
            hashed_email=login_data.hashed_email,
            lookup_hash=login_data.lookup_hash
        )
        
        metrics_service.track_login_attempt(auth_success)
        
        if not auth_success or not auth_data:
            # Log failed authentication attempt
            temp_client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
            temp_user_agent = request.headers.get("User-Agent", "unknown")
            _, _, temp_os_name, _, _ = parse_user_agent(temp_user_agent)
            temp_geo_data = get_geo_data_from_ip(temp_client_ip)
            temp_country_code = temp_geo_data.get("country_code", "Unknown")
            temp_fingerprint_string = f"{temp_os_name}:{temp_country_code}:unknown_user" # Use "unknown_user" as salt
            temp_stable_hash = hashlib.sha256(temp_fingerprint_string.encode()).hexdigest()
            temp_device_location_str = f"{temp_geo_data.get('city')}, {temp_geo_data.get('country_code')}" if temp_geo_data.get('city') and temp_geo_data.get('country_code') else temp_geo_data.get('country_code') or "Unknown"

            # Try to get user ID for logging if possible using hashed_email
            exists_result, user_data_for_log, _ = await directus_service.get_user_by_hashed_email(login_data.hashed_email)
            if exists_result and user_data_for_log:
                compliance_service.log_auth_event(
                    event_type="login_failed", 
                    user_id=user_data_for_log.get("id"),
                    ip_address=temp_client_ip,
                    status="failed",
                    details={
                        "reason": "invalid_credentials",
                        "device_fingerprint_stable_hash": temp_stable_hash, # Log stable hash
                        "ip_address": temp_client_ip,
                        "location": temp_device_location_str
                    }
                )
            return LoginResponse(success=False, message=message or "Invalid credentials")
            
        # Authentication successful
        # Get user data from auth_data
        user = auth_data.get("user", {})
        user_id = user.get("id")
        if not user_id:
            logger.error("User ID missing after successful password validation.")
            return LoginResponse(success=False, message="Internal server error: User ID missing.")

        # Generate simplified device fingerprint hash and detailed geo data
        device_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        device_location_str = f"{city}, {country_code}" if city and country_code else country_code or "Unknown" # More detailed location string

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
                    current_device_hash=device_hash, # Pass the new device hash
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service,
                    device_location_str=device_location_str, # Pass location string
                    latitude=latitude, # Pass latitude
                    longitude=longitude # Pass longitude
                )
            
            # Get encryption key
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, "password")
            if not encryption_key_data:
                logger.error(f"Encryption key not found for user {user_id}. Login failed.")
                return LoginResponse(success=False, message="Login failed. Please try again later.")
            user_profile.update(encryption_key_data)
            
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
                    darkmode=user_profile.get("darkmode", False),
                    encrypted_key=user_profile.get("encrypted_key"),
                    salt=user_profile.get("salt")
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
                            "device_fingerprint_stable_hash": device_hash, # Log stable hash
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
                    current_device_hash=device_hash, # Pass the new device hash
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service,
                    device_location_str=device_location_str, # Pass location string
                    latitude=latitude, # Pass latitude
                    longitude=longitude # Pass longitude
                )

                # Get encryption key
                hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, "password")
                if not encryption_key_data:
                    logger.error(f"Encryption key not found for user {user_id}. Login failed.")
                    return LoginResponse(success=False, message="Login failed. Please try again later.")
                user_profile.update(encryption_key_data)

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
                        darkmode=user_profile.get("darkmode", False),
                        encrypted_key=user_profile.get("encrypted_key"), # Pass encrypted_key
                        salt=user_profile.get("salt") # Pass salt
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
                            "device_fingerprint_stable_hash": device_hash,
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
                            "device_fingerprint_stable_hash": device_hash,
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
                            "device_fingerprint_stable_hash": device_hash,
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
                        "device_fingerprint_stable_hash": device_hash,
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
                    current_device_hash=device_hash, # Pass the new device hash
                    client_ip=client_ip, # Pass IP for logging inside finalize
                    encryption_service=encryption_service,
                    device_location_str=device_location_str, # Pass location string
                    latitude=latitude, # Pass latitude
                    longitude=longitude # Pass longitude
                )

                # Get encryption key
                hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, "password")
                if not encryption_key_data:
                    logger.error(f"Encryption key not found for user {user_id}. Login failed.")
                    return LoginResponse(success=False, message="Login failed. Please try again later.")
                user_profile.update(encryption_key_data)
                
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
                            logger.error(f"Cannot dispatch warm_user_cache task or check primed status (Backup code login): user_id is missing, though it was checked.")
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
                        darkmode=user_profile.get("darkmode", False),
                        encrypted_key=user_profile.get("encrypted_key"), # Pass encrypted_key
                        salt=user_profile.get("salt") # Pass salt
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
    current_device_hash: str, # Changed: Pass the new device hash
    client_ip: str, # Pass IP for logging/notification context
    encryption_service: EncryptionService, # Added missing dependency
    device_location_str: str, # Added location string
    latitude: Optional[float], # Added latitude
    longitude: Optional[float] # Added longitude
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
        # --- New Device Hash Handling ---
        logger.info(f"Checking device status for user {user_id[:6]}... with hash {current_device_hash[:8]}...")

        # Determine if this is a new device hash *before* adding it
        known_device_hashes = await directus_service.get_user_device_hashes(user_id)
        is_new_device_hash = current_device_hash not in known_device_hashes

        # Add the device hash to Directus (adds if new, does nothing if existing)
        update_success, update_msg = await directus_service.add_user_device_hash(user_id, current_device_hash)
        if not update_success:
            logger.error(f"Failed to add device hash for user {user_id}: {update_msg}")
            # Continue with login, but log the failure

        # If it's a new device hash, log and send notification
        if is_new_device_hash:
            logger.info(f"New device hash detected for user {user_id[:6]}...")
            # Log the event
            compliance_service.log_auth_event(
                event_type="login_new_device",
                user_id=user_id,
                ip_address=client_ip, # Keep IP for context
                status="success",
                details={
                    "device_fingerprint_stable_hash": current_device_hash,
                    "location": device_location_str,
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
                    is_localhost = "Local" in device_location_str # Simple check based on location string

                    logger.info(f"Dispatching new device email task for user {user_id[:6]}... (Email: {decrypted_email[:2]}***) with location data.")
                    app.send_task(
                        name='app.tasks.email_tasks.new_device_email_task.send_new_device_email',
                        kwargs={
                            'email_address': decrypted_email,
                            'user_agent_string': request.headers.get("User-Agent", "unknown"), # Get user agent directly from request
                            'ip_address': client_ip, # Still send the actual IP used for lookup
                            'latitude': latitude, # Pass latitude
                            'longitude': longitude, # Pass longitude
                            'location_name': device_location_str, # Use the derived location string
                            'is_localhost': is_localhost,
                            'language': user_language,
                            'darkmode': user_darkmode
                        },
                        queue='email'
                    )
            except Exception as task_exc:
                logger.error(f"Failed to dispatch new device email task for user {user_id[:6]}: {task_exc}", exc_info=True)
        # --- End New Device Hash Handling ---

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
                "encrypted_key": user.get("encrypted_key"), # Include encrypted_key in cache
                "salt": user.get("salt") # Include salt in cache
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
