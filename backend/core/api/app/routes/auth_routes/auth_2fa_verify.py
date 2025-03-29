from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
import logging
import pyotp
import time
from typing import Optional, Dict, Any

# Import schemas
from app.schemas.auth_2fa import VerifyDevice2FARequest, VerifyDevice2FAResponse

# Import services and dependencies
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.compliance import ComplianceService
from app.utils.encryption import EncryptionService
from app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_compliance_service
)
# Import utils and common functions
from app.routes.auth_routes.auth_utils import verify_allowed_origin
from app.routes.auth_routes.auth_common import verify_authenticated_user
from app.utils.device_fingerprint import get_device_fingerprint, get_client_ip, get_location_from_ip

# Define router for 2FA verification endpoints
router = APIRouter(
    prefix="/2fa/verify", # Define a prefix for these routes
    tags=["Auth - 2FA Verify"],
    dependencies=[Depends(verify_allowed_origin)] # Apply origin check to all routes here
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Dependency to get encryption service
def get_encryption_service():
    return EncryptionService()

@router.post("/device", response_model=VerifyDevice2FAResponse)
async def verify_device_2fa(
    request: Request,
    verify_request: VerifyDevice2FARequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Verify a 2FA code when prompted due to an unrecognized device accessing
    an existing valid session. If successful, marks the current device as known.
    """
    logger.info("Processing /verify/device request")

    # Get device info early for logging purposes, even on failure
    device_fingerprint = get_device_fingerprint(request)
    client_ip = get_client_ip(request)
    device_location = get_location_from_ip(client_ip)

    try:
        # Verify user authentication first (device check not strictly needed here,
        # as the trigger assumes a valid token but mismatched device)
        # We need user_data to get the secret.
        is_auth, user_data, _, auth_status = await verify_authenticated_user(
            request, cache_service, directus_service, require_known_device=False
        )

        if not is_auth or not user_data:
            # This shouldn't typically happen if /session triggered this flow correctly,
            # but handle it defensively.
            logger.warning("Attempt to verify device 2FA without valid session token.")
            # Compliance log removed for this case as per user request
            return VerifyDevice2FAResponse(success=False, message="Authentication required")

        user_id = user_data.get("user_id") # We know user_id exists from the is_auth check

        # Fetch the full user profile directly from Directus to ensure we have the 2FA details
        try:
            profile_success, profile_data, profile_message = await directus_service.get_user_profile(user_id)
            if not profile_success or not profile_data:
                logger.error(f"Could not retrieve user profile for user {user_id} during device verification: {profile_message}")
                # Use generic error message for frontend
                return VerifyDevice2FAResponse(success=False, message="An error occurred. Please try again another time.")
        except Exception as profile_err:
            logger.error(f"Exception retrieving user profile for {user_id}: {profile_err}", exc_info=True)
            # Use generic error message for frontend
            return VerifyDevice2FAResponse(success=False, message="An error occurred. Please try again another time.")


        # Check if 2FA is actually enabled for this user by checking for the secret in the fresh profile data
        encrypted_secret = profile_data.get("encrypted_tfa_secret")
        if not encrypted_secret:
            logger.error(f"Attempt to verify device 2FA for user {user_id} but no encrypted_tfa_secret found in DB profile.")
            # Compliance log removed for this case as per user request
            # Keep specific error message as this is user state, not internal error
            return VerifyDevice2FAResponse(success=False, message="2FA is not enabled for this account")

        # Get stored vault key from the fetched profile (secret already retrieved above)
        vault_key_id = profile_data.get("vault_key_id")

        if not encrypted_secret or not vault_key_id:
            # This indicates a data integrity issue if 2FA is enabled but secrets are missing in DB
            logger.error(f"Missing 2FA secret or vault key in DB for user {user_id} during device verification.")
            # Compliance log removed for this case as per user request
            # Use generic error message for frontend
            return VerifyDevice2FAResponse(success=False, message="An error occurred. Please try again another time.")

        # Decrypt the secret
        try:
            decrypted_secret = await encryption_service.decrypt_with_user_key(encrypted_secret, vault_key_id)
            if not decrypted_secret:
                 raise ValueError("Decryption returned None") # This will be caught by the outer exception handler
        except Exception as decrypt_err:
            logger.error(f"Failed to decrypt 2FA secret for user {user_id}: {decrypt_err}")
            # Compliance log removed for this case as per user request
            # Use generic error message for frontend
            return VerifyDevice2FAResponse(success=False, message="An error occurred. Please try again another time.")

        # Verify the TOTP code
        totp = pyotp.TOTP(decrypted_secret)
        if not totp.verify(verify_request.tfa_code):
            logger.warning(f"Invalid device verification 2FA code for user {user_id}")
            # Log compliance event ONLY for invalid code attempt
            compliance_service.log_auth_event(
                event_type="2fa_device_verification",
                user_id=user_id,
                ip_address=client_ip,
                status="failed",
                details={"reason": "invalid_code", "device_fingerprint": device_fingerprint, "location": device_location}
            )
            return VerifyDevice2FAResponse(success=False, message="Invalid verification code")

        # --- Code is valid ---
        logger.info(f"Successful device 2FA verification for user {user_id} from device {device_fingerprint}")

        # Mark the current device as known
        current_time = int(time.time())
        device_cache_key = f"{cache_service.USER_DEVICE_KEY_PREFIX}{user_id}:{device_fingerprint}"

        # Update cache
        await cache_service.set(
            device_cache_key,
            {"loc": device_location, "first": current_time, "recent": current_time},
            ttl=cache_service.USER_TTL
        )
        logger.info(f"Updated device cache for user {user_id}, device {device_fingerprint}")

        # Update DB (fire and forget, log errors)
        try:
            await directus_service.update_user_device(
                user_id=user_id, device_fingerprint=device_fingerprint, device_location=device_location
            )
            logger.info(f"Updated device DB for user {user_id}, device {device_fingerprint}")
        except Exception as db_err:
            logger.error(f"Failed to update device DB for user {user_id}, device {device_fingerprint}: {db_err}")
            # Continue even if DB update fails, cache was updated.
        
        # TODO: Send 'New device logged in' email notification

        # Log successful verification for compliance
        compliance_service.log_auth_event(
            event_type="2fa_device_verification",
            user_id=user_id,
            ip_address=client_ip,
            status="success",
            details={"device_fingerprint": device_fingerprint, "location": device_location}
        )

        return VerifyDevice2FAResponse(success=True, message="Device verified successfully")

    except Exception as e:
        logger.error(f"Error in verify_device_2fa: {str(e)}", exc_info=True)
        # Compliance log removed for generic exception case
        # Use generic error message for frontend
        return VerifyDevice2FAResponse(success=False, message="An error occurred. Please try again another time.")

# Potential future endpoint for verifying 2FA for sensitive actions
# @router.post("/action", ...)
# async def verify_action_2fa(...): ...