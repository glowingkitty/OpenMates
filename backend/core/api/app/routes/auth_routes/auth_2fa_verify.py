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
# Import Celery app instance
from app.tasks.celery_config import app

# Define router for 2FA verification endpoints
router = APIRouter(
    prefix="/2fa/verify", # Define a prefix for these routes
    tags=["Auth - 2FA Verify"],
    dependencies=[Depends(verify_allowed_origin)] # Apply origin check to all routes here
)

logger = logging.getLogger(__name__)

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

        # Fetch the decrypted TFA secret directly (bypasses cache)
        # No need to fetch the full profile anymore
        decrypted_secret = await directus_service.get_decrypted_tfa_secret(user_id)

        # Check if secret was retrieved and decrypted successfully
        if not decrypted_secret:
            # This covers cases where 2FA is not enabled, secret is missing, or decryption failed.
            # The get_decrypted_tfa_secret function logs the specific reason.
            logger.error(f"Could not get decrypted TFA secret for user {user_id} during device verification.")
            # Use generic error message for frontend
            return VerifyDevice2FAResponse(success=False, message="Could not verify 2FA status or code. Please try again.")

        # Verify the TOTP code using the directly fetched secret
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
        logger.info(f"Successful device 2FA verification for user {user_id} from device")

        # Mark the current device as known
        current_time = int(time.time())
        device_cache_key = f"{cache_service.USER_DEVICE_KEY_PREFIX}{user_id}:{device_fingerprint}"

        # Update cache
        await cache_service.set(
            device_cache_key,
            {"loc": device_location, "first": current_time, "recent": current_time},
            ttl=cache_service.USER_TTL
        )
        logger.info(f"Updated device cache for user {user_id}, device")

        # Update DB (fire and forget, log errors)
        try:
            await directus_service.update_user_device(
                user_id=user_id, device_fingerprint=device_fingerprint, device_location=device_location
            )
            logger.info(f"Updated device DB for user {user_id}, device")
        except Exception as db_err:
            logger.error(f"Failed to update device DB for user {user_id}, device: {db_err}")
            # Continue even if DB update fails, cache was updated.

        # Log successful verification for compliance
        compliance_service.log_auth_event(
            event_type="login_new_device", user_id=user_id, ip_address=client_ip, 
            status="success", details={"device_fingerprint": device_fingerprint, "location": device_location}
        )

        # --- Send 'New device logged in' email notification ---
        try:
            logger.info(f"Attempting to send new device notification for user {user_id[:6]}...")
            # Fetch full profile for email and preferences
            profile_success, user_profile, profile_message = await directus_service.get_user_profile(user_id)

            if not profile_success or not user_profile:
                logger.error(f"Failed to fetch profile for user {user_id[:6]}... to send new device email: {profile_message}")
                # Don't fail the whole request, just log the error
            else:
                encrypted_email = user_profile.get("encrypted_email_address")
                vault_key_id = user_profile.get("vault_key_id")
                decrypted_email = None

                if encrypted_email and vault_key_id:
                    logger.info(f"Attempting to decrypt email for user {user_id[:6]}... for new device notification.")
                    try:
                        decrypted_email = await encryption_service.decrypt_with_user_key(encrypted_email, vault_key_id)
                        if not decrypted_email:
                            logger.error(f"Decryption failed for user {user_id[:6]}... - received None.")
                        else:
                             logger.info(f"Successfully decrypted email for user {user_id[:6]}...")
                    except Exception as decrypt_exc:
                        logger.error(f"Error decrypting email for user {user_id[:6]}...: {decrypt_exc}", exc_info=True)
                else:
                    logger.error(f"Cannot send new device email for user {user_id[:6]}...: Missing encrypted_email_address or vault_key_id in profile data.")

                # Only send task if email was successfully decrypted
                if decrypted_email:
                    user_agent_string = request.headers.get("User-Agent", "unknown")
                    user_language = user_profile.get("language", "en")
                    user_darkmode = user_profile.get("darkmode", False)
                    
                    # Re-use location data from earlier
                    location_data = get_location_from_ip(client_ip) # Cached call
                    latitude = location_data.get("latitude")
                    longitude = location_data.get("longitude")
                    location_name = location_data.get("location_string", "unknown")
                    is_localhost = location_name == "localhost"

                    logger.info(f"Dispatching new device email task for user {user_id[:6]}... (Email: {decrypted_email[:2]}***) via device verification flow.")
                    app.send_task(
                        name='app.tasks.email_tasks.send_new_device_email',
                        kwargs={
                            'email_address': decrypted_email,
                            'user_agent_string': user_agent_string,
                            'ip_address': client_ip,
                            'latitude': latitude,
                            'longitude': longitude,
                            'location_name': location_name,
                            'is_localhost': is_localhost,
                            'language': user_language,
                            'darkmode': user_darkmode
                        },
                        queue='email'
                    )
        except Exception as email_task_exc:
            logger.error(f"Failed to dispatch new device email task during device verification for user {user_id[:6]}: {email_task_exc}", exc_info=True)
            # Do not fail the request if email sending fails

        return VerifyDevice2FAResponse(success=True, message="Device verified successfully")

    except Exception as e:
        logger.error(f"Error in verify_device_2fa: {str(e)}", exc_info=True)
        # Compliance log removed for generic exception case
        # Use generic error message for frontend
        return VerifyDevice2FAResponse(success=False, message="An error occurred. Please try again another time.")

# Potential future endpoint for verifying 2FA for sensitive actions
# @router.post("/action", ...)
# async def verify_action_2fa(...): ...