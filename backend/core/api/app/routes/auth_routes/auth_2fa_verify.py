from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
import logging
import pyotp
import time
import hashlib # Added for temporary hash generation
from typing import Optional, Dict, Any

# Import schemas
from backend.core.api.app.schemas.auth_2fa import VerifyDevice2FARequest, VerifyDevice2FAResponse

# Import services and dependencies
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_compliance_service
)
# Import utils and common functions
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
from backend.core.api.app.routes.auth_routes.auth_common import verify_authenticated_user
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip, parse_user_agent, get_geo_data_from_ip # Updated imports
# Import Celery app instance
from backend.core.api.app.tasks.celery_config import app

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
    # Generate simplified device fingerprint hash and detailed geo data
    # We need user_id for salting, but it might not be available yet if verify_authenticated_user fails.
    # So, we'll generate it with a placeholder for initial logging, and regenerate with actual user_id later if available.
    temp_client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
    temp_user_agent = request.headers.get("User-Agent", "unknown")
    _, _, temp_os_name, _, _ = parse_user_agent(temp_user_agent) # Need parse_user_agent here
    temp_geo_data = get_geo_data_from_ip(temp_client_ip) # Need get_geo_data_from_ip here
    temp_country_code = temp_geo_data.get("country_code", "Unknown")
    temp_fingerprint_string = f"{temp_os_name}:{temp_country_code}:temp_user" # Use "temp_user" as salt
    temp_stable_hash = hashlib.sha256(temp_fingerprint_string.encode()).hexdigest()
    temp_device_location_str = f"{temp_geo_data.get('city')}, {temp_geo_data.get('country_code')}" if temp_geo_data.get('city') and temp_geo_data.get('country_code') else temp_geo_data.get('country_code') or "Unknown"

    client_ip = temp_client_ip # Use the extracted client IP
    device_location_str = temp_device_location_str # Use the derived location string
    stable_hash = temp_stable_hash # Use the temporary stable hash for initial logging

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

        # Regenerate device hash with actual user_id for accurate logging and storage
        device_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
        stable_hash = device_hash # Update stable_hash with the user-salted one
        device_location_str = f"{city}, {country_code}" if city and country_code else country_code or "Unknown" # Update location string

        # Fetch necessary fields directly (bypasses cache)
        logger.info(f"Fetching encrypted_tfa_secret and vault_key_id for user {user_id}")
        user_fields = await directus_service.get_user_fields_direct(user_id, ["encrypted_tfa_secret", "vault_key_id"])

        if not user_fields:
            logger.error(f"Could not retrieve required fields (encrypted_tfa_secret, vault_key_id) for user {user_id} during device verification.")
            return VerifyDevice2FAResponse(success=False, message="Could not retrieve necessary user data. Please try again.")

        encrypted_secret = user_fields.get("encrypted_tfa_secret")
        vault_key_id = user_fields.get("vault_key_id")

        if not encrypted_secret or not vault_key_id:
            logger.error(f"User {user_id} does not have 2FA enabled or key information is missing (secret: {'present' if encrypted_secret else 'missing'}, key: {'present' if vault_key_id else 'missing'}).")
            return VerifyDevice2FAResponse(success=False, message="2FA is not enabled for this account or configuration is incomplete.")

        # Decrypt the secret
        decrypted_secret = None
        try:
            decrypted_secret = await encryption_service.decrypt_with_user_key(encrypted_secret, vault_key_id)
            if not decrypted_secret:
                 logger.error(f"Decryption of TFA secret failed for user {user_id} (returned None).")
                 # Use generic error message for frontend
                 return VerifyDevice2FAResponse(success=False, message="Could not verify 2FA status or code. Please try again.")
        except Exception as decrypt_err:
            logger.error(f"Error decrypting TFA secret for user {user_id}: {decrypt_err}", exc_info=True)
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
                details={"reason": "invalid_code", "device_fingerprint_stable_hash": stable_hash, "location": device_location_str}
            )
            return VerifyDevice2FAResponse(success=False, message="Invalid verification code")

        # --- Code is valid ---
        logger.info(f"Successful device 2FA verification for user {user_id} from device")

        # Mark the current device as known by adding its hash to Directus (which also updates cache)
        update_success, update_msg = await directus_service.add_user_device_hash(user_id, stable_hash)
        if update_success:
            logger.info(f"Added/updated device hash {stable_hash[:8]}... in DB and cache for user {user_id}.")
        else:
            logger.error(f"Failed to add/update device hash {stable_hash[:8]}... for user {user_id}: {update_msg}")
            # Continue even if DB update fails, as the user has successfully verified.

        # Log successful verification for compliance
        compliance_service.log_auth_event(
            event_type="login_new_device", user_id=user_id, ip_address=client_ip,
            status="success", details={"device_fingerprint_stable_hash": stable_hash, "location": device_location_str}
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
                encrypted_email_address = user_profile.get("encrypted_email_address")
                vault_key_id = user_profile.get("vault_key_id")
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
                    logger.error(f"Cannot send new device email for user {user_id[:6]}...: Missing encrypted_email_address or vault_key_id in profile data.")

                # Only send task if email was successfully decrypted
                if decrypted_email:
                    user_agent_string = request.headers.get("User-Agent", "unknown") # Get user agent directly from request
                    user_language = user_profile.get("language", "en")
                    user_darkmode = user_profile.get("darkmode", False)

                    # Use location data from the regenerated fingerprint
                    location_name = device_location_str # Use derived string
                    is_localhost = "Local" in device_location_str # Simple check based on location string

                    logger.info(f"Dispatching new device email task for user {user_id[:6]}... (Email: {decrypted_email[:2]}***) via device verification flow.")
                    app.send_task(
                        name='app.tasks.email_tasks.new_device_email_task.send_new_device_email',
                        kwargs={
                            'email_address': decrypted_email,
                            'user_agent_string': user_agent_string,
                            'ip_address': client_ip, # Still send original IP
                            'latitude': latitude, # Pass latitude
                            'longitude': longitude, # Pass longitude
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
