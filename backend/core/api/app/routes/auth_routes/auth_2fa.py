from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
import logging
import secrets
import string
import pyotp
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from typing import List, Optional, Dict, Any

# Import schemas from dedicated schema file
from app.schemas.auth_2fa import (
    Setup2FAResponse, Verify2FACodeRequest, Verify2FACodeResponse,
    BackupCodesResponse, ConfirmCodesStoredRequest, ConfirmCodesStoredResponse,
    Setup2FAProviderRequest, Setup2FAProviderResponse
)

from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.compliance import ComplianceService
from app.utils.encryption import EncryptionService
from app.routes.auth_routes.auth_dependencies import (
    get_directus_service, 
    get_cache_service, 
    get_metrics_service, 
    get_compliance_service
)
from app.routes.auth_routes.auth_utils import verify_allowed_origin
from app.routes.auth_routes.auth_common import verify_authenticated_user, require_auth
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip

router = APIRouter()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize Argon2 hasher
argon2_hasher = PasswordHasher()

# Dependency to get encryption service
def get_encryption_service():
    return EncryptionService()

# Generate a new 2FA secret
def generate_2fa_secret(app_name="OpenMates", username=""):
    """Generate a new TOTP secret for 2FA"""
    secret = pyotp.random_base32()
    display_name = username if username else "User"
    otpauth_url = pyotp.totp.TOTP(secret).provisioning_uri(
        name=display_name,
        issuer_name=app_name
    )
    return secret, otpauth_url, app_name

# Helper function to hash a backup code with Argon2
def hash_backup_code(code):
    """Hash a backup code using Argon2"""
    return argon2_hasher.hash(code)

# Helper function to verify a backup code against hashed codes
def verify_backup_code(code, hashed_codes):
    """Verify a backup code against a list of hashed codes"""
    for hashed_code in hashed_codes:
        try:
            argon2_hasher.verify(hashed_code, code)
            return True, hashed_codes.index(hashed_code)
        except VerifyMismatchError:
            continue
    return False, -1


# Helper function to generate backup codes
def generate_backup_codes(count=5, length=12):
    """Generate random backup codes with hyphens every 4 characters."""
    backup_codes = []
    for _ in range(count):
        chars = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))
        # Insert hyphens every 4 characters
        formatted_code = '-'.join(chars[i:i+4] for i in range(0, len(chars), 4))
        backup_codes.append(formatted_code)
    return backup_codes


@router.post("/setup_2fa", response_model=Setup2FAResponse, dependencies=[Depends(verify_allowed_origin)])
async def setup_2fa(
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Setup 2FA for a user by generating a secret key.
    Uses custom encrypted fields instead of Directus built-in 2FA.
    Email decryption is mandatory for security reasons.
    """
    logger.info("Processing /setup_2fa request")
    
    try:
        # Verify user authentication using shared function
        is_auth, user_data, refresh_token = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return Setup2FAResponse(success=False, message="Not authenticated")
        
        # Extract user_id from user_data
        user_id = user_data.get("user_id")
        if not user_id:
            return Setup2FAResponse(success=False, message="User ID not found")
            
        # Get user profile data
        success, user_profile, _ = await directus_service.get_user_profile(user_id)
        if not success or not user_profile:
            return Setup2FAResponse(success=False, message="Failed to get user profile")
            
        # Get email for the OTP name - decrypt it or fail
        email = None
        if "encrypted_email_address" in user_profile and user_profile.get("encrypted_email_address"):
            try:
                # Attempt to decrypt the email address
                vault_key_id = user_profile.get("vault_key_id")
                if vault_key_id:
                    email = await encryption_service.decrypt_with_user_key(
                        user_profile.get("encrypted_email_address"), 
                        vault_key_id
                    )
            except Exception as e:
                logger.error(f"Error decrypting email: {str(e)}")
                return Setup2FAResponse(success=False, message="Failed to decrypt email for 2FA setup")
        
        # If email was not found or decryption failed, abort the request
        if not email:
            return Setup2FAResponse(success=False, message="Email required for 2FA setup")
        
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
            logger.info(f"Updating last_opened to /signup/step-4 for user {user_id}")
            success_update = await directus_service.update_user(user_id, {
                "last_opened": "/signup/step-4"
            })
            if not success_update:
                logger.error(f"Failed to update last_opened for user {user_id} during 2FA setup initiation")
                # Logged the error, but continue as 2FA setup itself succeeded.
                # Consider if this should be a hard failure in the future.
            else:
                # Update cache only if Directus update was successful
                user_data["last_opened"] = "/signup/step-4"
                await cache_service.set_user(user_data, refresh_token=refresh_token)
                logger.info(f"Updated user cache for {user_id} with last_opened=/signup/step-4")
        
        return Setup2FAResponse(
            success=True,
            message="2FA setup initiated successfully",
            secret=secret,
            otpauth_url=otpauth_url
        )
        
    except Exception as e:
        logger.error(f"Error in setup_2fa: {str(e)}", exc_info=True)
        return Setup2FAResponse(success=False, message="An error occurred during 2FA setup")


@router.post("/verify_2fa_code", response_model=Verify2FACodeResponse, dependencies=[Depends(verify_allowed_origin)])
async def verify_2fa_code(
    request: Request,
    verify_request: Verify2FACodeRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Verify a 2FA code during signup process or login.
    This endpoint detects whether the request comes from signup or login flow and
    updates the user data accordingly.
    """
    logger.info("Processing /verify_2fa_code request")
    
    try:
        # Verify user authentication using shared function
        is_auth, user_data, refresh_token = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return Verify2FACodeResponse(success=False, message="Not authenticated")
        
        user_id = user_data.get("user_id")
        
        # Get 2FA setup data from cache
        setup_data = await cache_service.get(f"2fa_setup:{user_id}")
        if not setup_data:
            return Verify2FACodeResponse(success=False, message="2FA setup not initiated")
        
        # Verify the TOTP code using pyotp
        secret = setup_data.get("secret")
        totp = pyotp.TOTP(secret)
        if not totp.verify(verify_request.code):
            client_ip = get_client_ip(request)
            compliance_service.log_auth_event(
                event_type="2fa_verification",
                user_id=user_id,
                ip_address=client_ip,
                status="failed"
            )
            logger.info(f"Failed 2FA verification attempt for user {user_id}")
            return Verify2FACodeResponse(success=False, message="Invalid verification code")
        
        # Successful verification, proceed without compliance log for this specific event
        logger.info(f"Successful 2FA verification for user {user_id}")

        # Current timestamp for tfa_last_used
        current_time = int(time.time())
        
        # Encrypt the 2FA secret for storage
        encrypted_secret, _ = await encryption_service.encrypt(secret)
        
        # Check if this is part of signup (not login)
        is_signup = user_data.get("last_opened", "").startswith("/signup")
        
        if is_signup:
            # Update user in Directus to store the encrypted 2FA secret and set current timestamp
            success = await directus_service.update_user(user_id, {
                "encrypted_tfa_secret": encrypted_secret,
                "tfa_last_used": current_time,
                "last_opened": "/signup/step-5"
            })
            
            if not success:
                # update_user logs details internally
                logger.error("Failed to update user 2FA settings during signup") 
                return Verify2FACodeResponse(success=False, message="Failed to save 2FA settings")
            
            # Update cache with new signup step and last_opened
            user_data["last_opened"] = "/signup/step-5"
            await cache_service.set_user(user_data, refresh_token=refresh_token)
        else:
            # This is a login flow
            # Just verify the code and continue (no need to update signup steps)
            logger.info("2FA verification successful during login")
        
        # Update cache entry to mark that TOTP verification was successful
        # Keep the entry until backup codes are confirmed stored
        setup_data['tfa_added_to_app'] = True
        await cache_service.set(f"2fa_setup:{user_id}", setup_data, ttl=3600) # Keep original 1hr TTL
        logger.info(f"Updated 2FA setup cache for user {user_id} to mark app addition.")
        
        return Verify2FACodeResponse(success=True, message="Verification successful")
        
    except Exception as e:
        logger.error(f"Error in verify_2fa_code: {str(e)}", exc_info=True)
        return Verify2FACodeResponse(success=False, message="An error occurred during 2FA verification")


@router.get("/request_backup_codes", response_model=BackupCodesResponse, dependencies=[Depends(verify_allowed_origin)])
async def request_backup_codes(
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Generate and return backup codes for 2FA.
    """
    logger.info("Processing /request_backup_codes request")
    
    try:
        # Verify user authentication using shared function
        is_auth, user_data, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return BackupCodesResponse(success=False, message="Not authenticated")
        
        user_id = user_data.get("user_id")
        
        # Check if 2FA TOTP code has been verified (app added)
        setup_data = await cache_service.get(f"2fa_setup:{user_id}")
        if not setup_data or not setup_data.get("tfa_added_to_app"):
            return BackupCodesResponse(success=False, message="2FA setup not complete")
        
        # Always generate new backup codes
        backup_codes = generate_backup_codes()
        
        # Hash backup codes with Argon2 for secure storage
        hashed_codes = [hash_backup_code(code) for code in backup_codes]
        
        # Save hashed backup codes directly to Directus
        success = await directus_service.update_user(user_id, {
            "tfa_backup_codes_hashes": hashed_codes
        })
        
        if not success:
            # update_user logs details internally
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


@router.post("/confirm_codes_stored", response_model=ConfirmCodesStoredResponse, dependencies=[Depends(verify_allowed_origin)])
async def confirm_codes_stored(
    request: Request,
    confirm_request: ConfirmCodesStoredRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Confirm that the user has stored their backup codes.
    """
    logger.info("Processing /confirm_codes_stored request")
    
    try:
        if not confirm_request.confirmed:
            return ConfirmCodesStoredResponse(
                success=False, 
                message="You must confirm that you have stored your backup codes"
            )
        
        # Verify user authentication using shared function
        is_auth, user_data, refresh_token = await verify_authenticated_user( # Capture refresh token
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return ConfirmCodesStoredResponse(success=False, message="Not authenticated")
        
        user_id = user_data.get("user_id")
        
        # Record the timestamp when user confirmed the backup codes were stored
        current_time = int(time.time())
        
        # Update user in Directus to store the confirmation timestamp and update last_opened
        success = await directus_service.update_user(user_id, {
            "consent_tfa_safely_stored_timestamp": current_time,
            "last_opened": "/signup/step-6"  # Update last opened step
        })
        
        if not success:
            # update_user logs details internally
            logger.error("Failed to record confirmation timestamp or update last_opened") 
            return ConfirmCodesStoredResponse(success=False, message="Failed to record your confirmation")

        # Update user cache with the new last_opened step
        user_data["last_opened"] = "/signup/step-6"
        await cache_service.set_user(user_data, refresh_token=refresh_token)
        logger.info(f"Updated user cache for {user_id} with last_opened=/signup/step-6")
        
        # Clean up any remaining 2FA setup data from cache
        await cache_service.delete(f"2fa_setup:{user_id}")
        logger.info(f"Removed 2FA setup data from cache for user {user_id}")
        
        # Log confirmation for compliance
        client_ip = get_client_ip(request)
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


@router.post("/setup_2fa_provider", response_model=Setup2FAProviderResponse, dependencies=[Depends(verify_allowed_origin)])
async def setup_2fa_provider(
    request: Request,
    provider_request: Setup2FAProviderRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Save which 2FA app was used by the user.
    """
    logger.info("Processing /setup_2fa_provider request")
    
    try:
        # Verify user authentication using shared function
        is_auth, user_data, refresh_token = await verify_authenticated_user(
            request, cache_service, directus_service
        )
        
        if not is_auth or not user_data:
            return Setup2FAProviderResponse(success=False, message="Not authenticated")
        
        user_id = user_data.get("user_id")
        
        # No validation needed - app name can be any string
        tfa_app_name = provider_request.provider
        
        # Encrypt app name for Directus storage
        encrypted_app_name, _ = await encryption_service.encrypt(tfa_app_name)
        
        # Update user in Directus to store the encrypted 2FA app name
        success = await directus_service.update_user(user_id, {
            "encrypted_tfa_app_name": encrypted_app_name
        })
        
        if not success:
            # update_user logs details internally
            logger.error("Failed to update user 2FA app name") 
            return Setup2FAProviderResponse(success=False, message="Failed to save 2FA app name")
        
        # Update the user cache (using USER_KEY_PREFIX)
        await cache_service.update_user(user_id, {"tfa_app_name": tfa_app_name})
        
        # Also update the user profile cache if it exists (using a different prefix)
        profile_cache_key = f"user_profile:{user_id}"
        cached_profile = await cache_service.get(profile_cache_key)
        if cached_profile:
            cached_profile["tfa_app_name"] = tfa_app_name
            await cache_service.set(profile_cache_key, cached_profile)
        
        return Setup2FAProviderResponse(
            success=True,
            message="2FA app name saved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error in setup_2fa_provider: {str(e)}", exc_info=True)
        return Setup2FAProviderResponse(success=False, message="An error occurred while saving 2FA provider")