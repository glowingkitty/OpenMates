from fastapi import APIRouter, Depends, Request
import logging
import time

# Import schemas
from backend.core.api.app.schemas.auth_2fa import (
    Setup2FAInitiateRequest, Setup2FAResponse, VerifySignup2FARequest, VerifySignup2FAResponse,
    BackupCodesResponse, ConfirmCodesStoredRequest, ConfirmCodesStoredResponse,
    Setup2FAProviderRequest, Setup2FAProviderResponse
)
from backend.core.api.app.models.user import User

# Import services and dependencies
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_compliance_service,
    get_current_user
)
# Import utils and common functions
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
from backend.core.api.app.routes.auth_routes.auth_common import verify_authenticated_user
from backend.core.api.app.utils.device_fingerprint import _extract_client_ip # Import the new helper

# Import helpers from the new utils file
from .auth_2fa_utils import (
    generate_2fa_secret,
    hash_backup_code,
    generate_backup_codes
)

# Define router for 2FA setup endpoints
router = APIRouter(
    prefix="/2fa/setup", # Corrected prefix for these routes
    tags=["Auth - 2FA Setup"],
    dependencies=[Depends(verify_allowed_origin)] # Apply origin check to all routes here
)

logger = logging.getLogger(__name__)

# Dependency to get encryption service (can be defined here or imported if moved)
def get_encryption_service():
    return EncryptionService()

@router.post("/initiate", response_model=Setup2FAResponse)
async def setup_2fa(
    request: Request,
    setup_request: Setup2FAInitiateRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Setup 2FA for a user by generating a secret key.
    Uses custom encrypted fields instead of Directus built-in 2FA.
    Email decryption is mandatory for security reasons.
    """
    logger.info("Processing /setup/initiate request")

    try:
        # Verify user authentication using shared function
        is_auth, user_data, refresh_token, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )

        if not is_auth or not user_data:
            logger.warning(f"Authentication failed or user_data missing for 2FA setup initiate. is_auth: {is_auth}")
            return Setup2FAResponse(success=False, message="Not authenticated")

        # Extract user_id from user_data
        user_id = user_data.get("user_id")
        if not user_id:
            return Setup2FAResponse(success=False, message="User ID not found")

        # Get user profile data
        logger.info(f"Attempting to get user profile for user_id: {user_id}")
        success, user_profile, _ = await directus_service.get_user_profile(user_id)
        if not success or not user_profile:
            logger.error(f"Failed to get user profile for user_id: {user_id}. Success: {success}")
            return Setup2FAResponse(success=False, message="Failed to get user profile")

        # Get email for the OTP name - decrypt it using client-provided key
        email = None
        if "encrypted_email_address" in user_profile and user_profile.get("encrypted_email_address"):
            # Client-provided email_encryption_key is required for zero-knowledge email decryption
            if not setup_request.email_encryption_key:
                logger.error(f"Missing email_encryption_key for user_id: {user_id}. Cannot decrypt email for 2FA setup.")
                return Setup2FAResponse(success=False, message="Email encryption key required for 2FA setup")
                
            try:
                logger.info(f"Attempting to decrypt email using client-provided key for user_id: {user_id}")
                try:
                    # Import the key for use with NaCl
                    import base64
                    import nacl.secret
                    from nacl.exceptions import CryptoError
                    
                    # Log the lengths for debugging
                    encrypted_email_b64 = user_profile.get("encrypted_email_address")
                    key_b64 = setup_request.email_encryption_key
                    logger.info(f"Encrypted email length (base64): {len(encrypted_email_b64)}")
                    logger.info(f"Email encryption key length (base64): {len(key_b64)}")
                    
                    # Decode the encrypted email and key
                    try:
                        encrypted_data = base64.b64decode(encrypted_email_b64)
                        logger.info(f"Encrypted data length (bytes): {len(encrypted_data)}")
                    except Exception as decode_error:
                        logger.error(f"Failed to decode encrypted email: {str(decode_error)}")
                        return Setup2FAResponse(success=False, message="Invalid encrypted email format")
                    
                    try:
                        key_bytes = base64.b64decode(key_b64)
                        logger.info(f"Key bytes length: {len(key_bytes)}")
                        
                        # Verify key length for NaCl
                        if len(key_bytes) != nacl.secret.SecretBox.KEY_SIZE:
                            logger.error(f"Invalid key length: {len(key_bytes)}, expected {nacl.secret.SecretBox.KEY_SIZE}")
                            return Setup2FAResponse(success=False, message=f"Invalid key length: {len(key_bytes)}, expected {nacl.secret.SecretBox.KEY_SIZE}")
                    except Exception as key_error:
                        logger.error(f"Failed to decode encryption key: {str(key_error)}")
                        return Setup2FAResponse(success=False, message="Invalid encryption key format")
                    
                    # Verify encrypted data has enough bytes for nonce
                    if len(encrypted_data) <= nacl.secret.SecretBox.NONCE_SIZE:
                        logger.error(f"Encrypted data too short: {len(encrypted_data)} bytes, need > {nacl.secret.SecretBox.NONCE_SIZE}")
                        return Setup2FAResponse(success=False, message="Encrypted email data is invalid or corrupted")
                    
                    # Extract nonce and ciphertext
                    nonce = encrypted_data[:nacl.secret.SecretBox.NONCE_SIZE]
                    ciphertext = encrypted_data[nacl.secret.SecretBox.NONCE_SIZE:]
                    logger.info(f"Nonce length: {len(nonce)}, Ciphertext length: {len(ciphertext)}")
                    
                    # Decrypt using NaCl
                    try:
                        box = nacl.secret.SecretBox(key_bytes)
                        plaintext = box.decrypt(ciphertext, nonce)
                        email = plaintext.decode('utf-8')
                        logger.info(f"Successfully decrypted email using client key for user_id: {user_id}")
                    except CryptoError as crypto_error:
                        logger.error(f"NaCl decryption failed: {str(crypto_error)}")
                        return Setup2FAResponse(success=False, message="Decryption failed - the key may be incorrect")
                    except Exception as decrypt_error:
                        logger.error(f"Unexpected error during decryption: {str(decrypt_error)}")
                        return Setup2FAResponse(success=False, message="Failed to decrypt email - unexpected error")
                    
                except (ValueError, Exception) as client_key_error:
                    logger.error(f"Failed to decrypt with client key: {str(client_key_error)}")
                    return Setup2FAResponse(success=False, message="Failed to decrypt email with provided key")
                    
            except Exception as e:
                logger.error(f"Error decrypting email: {str(e)}")
                return Setup2FAResponse(success=False, message="Failed to decrypt email for 2FA setup")

        # If email was not found or decryption failed, try to get it from vault as a fallback
        if not email:
            logger.info(f"Client-side decryption failed, attempting to get email from vault for user_id: {user_id}")
            
            # Try to get the email using the vault key
            vault_key_id = user_profile.get("vault_key_id")
            encrypted_email = user_profile.get("encrypted_email_address")
            
            if vault_key_id and encrypted_email:
                try:
                    # Try to decrypt using the user's vault key
                    email = await encryption_service.decrypt_with_user_key(encrypted_email, vault_key_id)
                    if email:
                        logger.info(f"Successfully retrieved email from vault for user_id: {user_id}")
                    else:
                        logger.error(f"Vault decryption returned None for user_id: {user_id}")
                except Exception as vault_error:
                    logger.error(f"Vault decryption error for user_id: {user_id}: {str(vault_error)}")
            
        # Final check - if we still don't have an email, abort
        if not email:
            logger.error(f"Email could not be obtained for user_id: {user_id}. Cannot proceed with 2FA setup.")
            return Setup2FAResponse(success=False, message="Email required for 2FA setup - please try again or contact support")

        # Generate new 2FA secret using the decrypted email
        secret, otpauth_url, _ = generate_2fa_secret(app_name="OpenMates", username=email)

        # Store the secret in cache temporarily (will be saved to the database when verified)
        await cache_service.set(f"2fa_setup:{user_id}", {
            "secret": secret,
            "otpauth_url": otpauth_url,
            "setup_complete": False
        }, ttl=3600)  # 1 hour expiry for setup completion

        # Log the successful 2FA setup initiation
        logger.info(f"2FA setup initiated for user {user_id}")

        # If in signup flow, update last_opened to step 4
        is_signup = user_data.get("last_opened", "").startswith("/signup")
        if is_signup:
            logger.info(f"Updating last_opened to /signup/one-time-codes for user {user_id}")
            success_update = await directus_service.update_user(user_id, {
                "last_opened": "/signup/one-time-codes"
            })
            if not success_update:
                logger.error(f"Failed to update last_opened for user {user_id} during 2FA setup initiation")
            else:
                # Update cache only if Directus update was successful
                user_data["last_opened"] = "/signup/one-time-codes"
                await cache_service.set_user(user_data, refresh_token=refresh_token)
                logger.info(f"Updated user cache for {user_id} with last_opened=/signup/one-time-codes")

        response_payload = Setup2FAResponse(
            success=True,
            message="2FA setup initiated successfully",
            secret=secret,
            otpauth_url=otpauth_url
        )
        logger.info(f"Successfully initiated 2FA setup for user {user_id}. Returning secret and otpauth_url.")
        return response_payload

    except Exception as e:
        logger.error(f"Error in setup_2fa: {str(e)}", exc_info=True)
        return Setup2FAResponse(success=False, message=f"An error occurred during 2FA setup: {str(e)}")


@router.post("/verify-signup", response_model=VerifySignup2FAResponse)
async def verify_signup_2fa(
    request: Request,
    verify_request: VerifySignup2FARequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Verify a 2FA code during the signup process.
    """
    logger.info("Processing /setup/verify-signup request")

    try:
        # Verify user authentication using shared function
        is_auth, user_data, refresh_token, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )

        if not is_auth or not user_data:
            return VerifySignup2FAResponse(success=False, message="Not authenticated")

        user_id = user_data.get("user_id")

        # Get 2FA setup data from cache (specific to signup flow)
        setup_data = await cache_service.get(f"2fa_setup:{user_id}")
        if not setup_data:
            logger.warning(f"Attempt to verify signup 2FA code for user {user_id} without setup data in cache.")
            return VerifySignup2FAResponse(success=False, message="2FA setup not active or expired")

        # Verify the TOTP code using pyotp
        secret = setup_data.get("secret")
        # Need pyotp import
        import pyotp
        totp = pyotp.TOTP(secret)
        if not totp.verify(verify_request.code):
            client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
            compliance_service.log_auth_event(
                event_type="2fa_verification",
                user_id=user_id,
                ip_address=client_ip,
                status="failed"
            )
            logger.info(f"Failed 2FA verification attempt during signup for user {user_id}")
            return VerifySignup2FAResponse(success=False, message="Invalid verification code")

        # Successful verification during signup flow
        logger.info(f"Successful 2FA verification for user {user_id}")

        current_time = int(time.time())
        vault_key_id = user_data.get("vault_key_id")
        if not vault_key_id:
            logger.error(f"Vault key ID not found for user {user_id} during 2FA signup verification.")
            return VerifySignup2FAResponse(success=False, message="Encryption key not found for user")

        encrypted_secret, _ = await encryption_service.encrypt_with_user_key(secret, vault_key_id)
        if not encrypted_secret:
             logger.error(f"Failed to encrypt 2FA secret for user {user_id} during signup.")
             return VerifySignup2FAResponse(success=False, message="Failed to secure 2FA secret")

        success = await directus_service.update_user(user_id, {
            "encrypted_tfa_secret": encrypted_secret,
            "tfa_last_used": current_time,
            "last_opened": "/signup/tfa_app_reminder"
        })

        if not success:
            logger.error("Failed to update user 2FA settings during signup verification")
            return VerifySignup2FAResponse(success=False, message="Failed to save 2FA settings")

        cache_update_success = await cache_service.update_user(user_id, {
            "tfa_enabled": True,
            "last_opened": "/signup/tfa_app_reminder"
            })
        if not cache_update_success:
             logger.warning(f"Failed to update cache for user {user_id} after 2FA signup verification, but Directus was updated.")
        else:
             logger.info(f"Successfully updated cache for user {user_id} after 2FA signup verification.")

        setup_data['tfa_added_to_app'] = True
        await cache_service.set(f"2fa_setup:{user_id}", setup_data, ttl=3600)
        logger.info(f"Updated 2FA setup cache for user {user_id} to mark app addition during signup.")

        return VerifySignup2FAResponse(success=True, message="Verification successful")

    except Exception as e:
        logger.error(f"Error in verify_signup_2fa: {str(e)}", exc_info=True)
        return VerifySignup2FAResponse(success=False, message="An error occurred during 2FA verification")


@router.get("/request-backup-codes", response_model=BackupCodesResponse)
async def request_backup_codes(
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Generate and return backup codes for 2FA during setup.
    """
    logger.info("Processing /setup/request-backup-codes request")

    try:
        # Corrected unpacking to include the fourth return value
        is_auth, user_data, _, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )

        if not is_auth or not user_data:
            return BackupCodesResponse(success=False, message="Not authenticated")

        user_id = user_data.get("user_id")

        # RESILIENT BACKUP CODE GENERATION:
        # Check if 2FA is actually enabled in the user profile (persistent state) instead of
        # relying solely on the ephemeral 2fa_setup cache. This allows users who logged out/in
        # or waited too long to still complete the backup codes step.
        #
        # Two valid scenarios:
        # 1. Happy path: Cache exists with tfa_added_to_app=true (normal signup flow)
        # 2. Recovery path: 2FA is enabled in profile AND user is at backup-codes step
        #    (user logged out/in or cache expired after completing 2FA verification)
        
        setup_data = await cache_service.get(f"2fa_setup:{user_id}")
        tfa_enabled = user_data.get("tfa_enabled", False)
        last_opened = user_data.get("last_opened", "")
        is_at_backup_codes_step = (
            last_opened.startswith("/signup/backup-codes") or 
            last_opened.startswith("#signup/backup-codes")
        )
        
        # Allow if either:
        # - Cache exists with tfa_added_to_app (normal flow), OR
        # - 2FA is enabled AND user is at backup codes step (recovery path)
        cache_ok = setup_data and setup_data.get("tfa_added_to_app")
        recovery_ok = tfa_enabled and is_at_backup_codes_step
        
        if not (cache_ok or recovery_ok):
            logger.warning(
                f"User {user_id} attempted to request backup codes without proper setup. "
                f"cache_ok={cache_ok}, recovery_ok={recovery_ok}, "
                f"tfa_enabled={tfa_enabled}, last_opened={last_opened}"
            )
            return BackupCodesResponse(success=False, message="2FA setup not complete")
        
        logger.info(
            f"Generating backup codes for user {user_id}: "
            f"cache_path={'yes' if cache_ok else 'no'}, recovery_path={'yes' if recovery_ok else 'no'}"
        )

        backup_codes = generate_backup_codes()
        hashed_codes = [hash_backup_code(code) for code in backup_codes]

        success = await directus_service.update_user(user_id, {
            "tfa_backup_codes_hashes": hashed_codes
        })

        if not success:
            logger.error("Failed to store backup codes")
            return BackupCodesResponse(success=False, message="Failed to save backup codes")

        logger.info(f"Backup codes generated successfully for user {user_id}")

        return BackupCodesResponse(
            success=True,
            message="Backup codes generated successfully",
            backup_codes=backup_codes
        )

    except Exception as e:
        logger.error(f"Error in request_backup_codes: {str(e)}", exc_info=True)
        return BackupCodesResponse(success=False, message="An error occurred while generating backup codes")


@router.post("/confirm-codes-stored", response_model=ConfirmCodesStoredResponse)
async def confirm_codes_stored(
    request: Request,
    confirm_request: ConfirmCodesStoredRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Confirm that the user has stored their backup codes during setup.
    """
    logger.info("Processing /setup/confirm-codes-stored request")

    try:
        if not confirm_request.confirmed:
            return ConfirmCodesStoredResponse(
                success=False,
                message="You must confirm that you have stored your backup codes"
            )

        # Corrected unpacking to include the fourth return value
        is_auth, user_data, refresh_token, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )

        if not is_auth or not user_data:
            return ConfirmCodesStoredResponse(success=False, message="Not authenticated")

        user_id = user_data.get("user_id")
        current_time = int(time.time())

        success = await directus_service.update_user(user_id, {
            "consent_tfa_safely_stored_timestamp": current_time,
            "last_opened": "/signup/recovery-key"
        })

        if not success:
            logger.error("Failed to record confirmation timestamp or update last_opened")
            return ConfirmCodesStoredResponse(success=False, message="Failed to record your confirmation")

        user_data["last_opened"] = "/signup/recovery-key"
        await cache_service.set_user(user_data, refresh_token=refresh_token)
        logger.info(f"Updated user cache for {user_id} with last_opened=/signup/recovery-key")

        await cache_service.delete(f"2fa_setup:{user_id}")
        logger.info(f"Removed 2FA setup data from cache for user {user_id}")

        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        compliance_service.log_auth_event(
            event_type="2fa_setup_complete",
            user_id=user_id,
            ip_address=client_ip,
            status="success"
        )

        logger.info(f"2FA setup completed successfully for user {user_id}")

        return ConfirmCodesStoredResponse(
            success=True,
            message="Backup codes confirmed and stored successfully"
        )

    except Exception as e:
        logger.error(f"Error in confirm_codes_stored: {str(e)}", exc_info=True)
        return ConfirmCodesStoredResponse(success=False, message="An error occurred while confirming backup codes")


@router.post("/provider", response_model=Setup2FAProviderResponse)
async def setup_2fa_provider(
    request: Request,
    provider_request: Setup2FAProviderRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Save which 2FA app was used by the user during setup.
    """
    logger.info("Processing /setup/provider request")

    try:
        # Corrected unpacking to include the fourth return value
        is_auth, user_data, refresh_token, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )

        if not is_auth or not user_data:
            return Setup2FAProviderResponse(success=False, message="Not authenticated")

        user_id = user_data.get("user_id")
        vault_key_id = user_data.get("vault_key_id")
        if not vault_key_id:
            logger.error(f"Vault key ID not found for user {user_id} when saving 2FA provider.")
            return Setup2FAProviderResponse(success=False, message="Encryption key not found for user")

        tfa_app_name = provider_request.provider
        encrypted_app_name, _ = await encryption_service.encrypt_with_user_key(tfa_app_name, vault_key_id)

        success = await directus_service.update_user(user_id, {
            "encrypted_tfa_app_name": encrypted_app_name,
            "last_opened": "/signup/backup-codes"
        })

        if not success:
            logger.error("Failed to update user 2FA app name")
            return Setup2FAProviderResponse(success=False, message="Failed to save 2FA app name or update step")

        logger.info(f"Attempting to update cache for user {user_id} after setting 2FA provider.")
        cache_update_success = await cache_service.update_user(user_id, {
            "tfa_app_name": tfa_app_name,
            "last_opened": "/signup/backup-codes"
        })
        if not cache_update_success:
             logger.warning(f"Failed to update cache for user {user_id} after setting 2FA provider, but Directus was updated.")
        else:
            logger.info(f"Successfully updated cache for user {user_id} after setting 2FA provider.")

        return Setup2FAProviderResponse(
            success=True,
            message="2FA app name saved successfully"
        )

    except Exception as e:
        logger.error(f"Error in setup_2fa_provider: {str(e)}", exc_info=True)
        return Setup2FAProviderResponse(success=False, message="An error occurred while saving 2FA provider")


@router.post("/reset-backup-codes", response_model=BackupCodesResponse)
async def reset_backup_codes(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Reset (regenerate) backup codes for an authenticated user.

    This is a standalone endpoint that generates new backup codes without
    requiring the user to go through the full 2FA re-setup flow. The user
    must already have 2FA enabled. SecurityAuth verification is handled
    on the frontend before calling this endpoint.

    Steps:
    1. Verify user has 2FA enabled
    2. Generate new backup codes
    3. Hash and store them in Directus (replacing old codes)
    4. Log compliance event
    5. Return plaintext codes to the user (one-time display)
    """
    logger.info(f"Processing /setup/reset-backup-codes for user {current_user.id}")

    try:
        user_id = current_user.id

        # Step 1: Verify user has 2FA enabled
        success, user_profile, _ = await directus_service.get_user_profile(user_id)
        if not success or not user_profile:
            logger.error(f"Failed to get user profile for backup code reset, user_id: {user_id}")
            return BackupCodesResponse(
                success=False,
                message="Failed to retrieve user profile",
                backup_codes=[]
            )

        tfa_enabled = user_profile.get("tfa_enabled", False)
        if not tfa_enabled:
            logger.warning(f"User {user_id} attempted to reset backup codes without 2FA enabled")
            return BackupCodesResponse(
                success=False,
                message="2FA must be enabled to reset backup codes",
                backup_codes=[]
            )

        # Step 2: Generate new backup codes
        backup_codes = generate_backup_codes()
        hashed_codes = [hash_backup_code(code) for code in backup_codes]

        # Step 3: Store hashed codes in Directus (replaces old codes)
        update_success = await directus_service.update_user(user_id, {
            "tfa_backup_codes_hashes": hashed_codes
        })

        if not update_success:
            logger.error(f"Failed to store new backup codes for user {user_id}")
            return BackupCodesResponse(
                success=False,
                message="Failed to save new backup codes. Please try again.",
                backup_codes=[]
            )

        # Step 4: Invalidate user profile cache so the new codes are fresh
        try:
            await cache_service.delete(f"user_profile:{user_id}")
            logger.info(f"Invalidated user profile cache for user {user_id}")
        except Exception as e:
            logger.warning(f"Error invalidating cache for user {user_id}: {e}")
            # Non-critical, continue

        # Step 5: Log compliance event
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        compliance_service.log_auth_event(
            event_type="backup_codes_regenerated",
            user_id=user_id,
            ip_address=client_ip,
            status="success"
        )

        logger.info(f"Backup codes reset successfully for user {user_id}")

        return BackupCodesResponse(
            success=True,
            message="Backup codes regenerated successfully",
            backup_codes=backup_codes
        )

    except Exception as e:
        logger.error(f"Error in reset_backup_codes: {str(e)}", exc_info=True)
        return BackupCodesResponse(
            success=False,
            message="An error occurred while resetting backup codes",
            backup_codes=[]
        )
