from fastapi import APIRouter, Depends, Request
import logging
import time
import hashlib

# Import schemas
from backend.core.api.app.schemas.auth_recoverykey import (
    ConfirmRecoveryKeyStoredRequest, ConfirmRecoveryKeyStoredResponse,
    RegenerateRecoveryKeyRequest, RegenerateRecoveryKeyResponse
)
from backend.core.api.app.models.user import User

# Import services and dependencies
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_compliance_service,
    get_current_user
)

# Import utils and common functions
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
from backend.core.api.app.routes.auth_routes.auth_common import verify_authenticated_user
from backend.core.api.app.utils.device_fingerprint import _extract_client_ip

# Define router for recovery key endpoints
router = APIRouter(
    prefix="/recovery-key",
    tags=["Auth - Recovery Key"],
    dependencies=[Depends(verify_allowed_origin)]
)

logger = logging.getLogger(__name__)

@router.post("/confirm-stored", response_model=ConfirmRecoveryKeyStoredResponse)
async def confirm_recovery_key_stored(
    request: Request,
    confirm_request: ConfirmRecoveryKeyStoredRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Confirm that the user has stored their recovery key.
    This endpoint stores the lookup hash and wrapped master key in the database,
    allowing the user to use the recovery key for authentication in the future.
    """
    logger.info("Processing /recovery-key/confirm-stored request")

    try:
        if not confirm_request.confirmed:
            return ConfirmRecoveryKeyStoredResponse(
                success=False,
                message="You must confirm that you have stored your recovery key"
            )

        # Verify user authentication
        is_auth, user_data, refresh_token, _ = await verify_authenticated_user(
            request, cache_service, directus_service
        )

        if not is_auth or not user_data:
            return ConfirmRecoveryKeyStoredResponse(success=False, message="Not authenticated")

        user_id = user_data.get("user_id")
        current_time = int(time.time())

        # Get the current lookup_hashes array
        success, user_profile, _ = await directus_service.get_user_profile(user_id)
        if not success or not user_profile:
            logger.error(f"Failed to get user profile for user_id: {user_id}")
            return ConfirmRecoveryKeyStoredResponse(success=False, message="Failed to get user profile")
        
        # Get existing lookup_hashes or initialize as empty array
        lookup_hashes = user_profile.get("lookup_hashes", [])
        
        if not isinstance(lookup_hashes, list):
            lookup_hashes = []
            logger.warning(f"lookup_hashes is not a list, initializing empty array for user_id: {user_id}")

        # Add only the lookup hash string to the array (not a dictionary)
        lookup_hashes.append(confirm_request.lookup_hash)

        # Create encryption key record for the recovery key
        try:
            # Hash the user ID for security
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            
            # Store the wrapped master key in the encryption_keys table
            encryption_key_success = await directus_service.create_encryption_key(
                hashed_user_id=hashed_user_id,
                login_method='recovery_key',
                encrypted_key=confirm_request.wrapped_master_key,
                salt=confirm_request.salt,
                key_iv=confirm_request.key_iv
            )
            
            if not encryption_key_success:
                logger.error(f"Failed to create encryption key record for recovery key for user {user_id}")
                return ConfirmRecoveryKeyStoredResponse(
                    success=False,
                    message="Failed to set up recovery key encryption. Please try again."
                )
                
            logger.info(f"Successfully created encryption key record for recovery key for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to create encryption key for recovery key for user {user_id}: {e}", exc_info=True)
            return ConfirmRecoveryKeyStoredResponse(
                success=False,
                message="Failed to set up recovery key encryption. Please try again."
            )

        # Update the user profile with the new lookup_hashes array
        success = await directus_service.update_user(user_id, {
            "lookup_hashes": lookup_hashes,
            "consent_recovery_key_stored_timestamp": current_time,
            "last_opened": "/signup/profile-picture"
        })

        if not success:
            logger.error("Failed to record recovery key data or update last_opened")
            return ConfirmRecoveryKeyStoredResponse(success=False, message="Failed to record your recovery key")

        # Update user cache
        user_data["last_opened"] = "/signup/profile-picture"
        await cache_service.set_user(user_data, refresh_token=refresh_token)
        logger.info(f"Updated user cache for {user_id} with last_opened=/signup/profile-picture")

        # Log the event for compliance
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        compliance_service.log_auth_event(
            event_type="recovery_key_setup_complete",
            user_id=user_id,
            ip_address=client_ip,
            status="success"
        )

        logger.info(f"Recovery key setup completed successfully for user {user_id}")

        return ConfirmRecoveryKeyStoredResponse(
            success=True,
            message="Recovery key confirmed and stored successfully"
        )

    except Exception as e:
        logger.error(f"Error in confirm_recovery_key_stored: {str(e)}", exc_info=True)
        return ConfirmRecoveryKeyStoredResponse(success=False, message="An error occurred while confirming recovery key")


@router.post("/regenerate", response_model=RegenerateRecoveryKeyResponse)
async def regenerate_recovery_key(
    request: Request,
    regen_request: RegenerateRecoveryKeyRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service)
):
    """
    Regenerate the user's recovery key.
    This endpoint requires authentication (user must be logged in).
    It replaces the old recovery key with a new one:
    1. Deletes the old recovery_key entry from encryption_keys
    2. Creates a new recovery_key entry with the new wrapped master key
    3. Updates lookup_hashes array (removes old hash if provided, adds new hash)
    """
    logger.info(f"Processing /recovery-key/regenerate for user {current_user.id}")

    try:
        user_id = current_user.id
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        current_time = int(time.time())

        # Step 1: Get current user profile to access lookup_hashes
        success, user_profile, _ = await directus_service.get_user_profile(user_id)
        if not success or not user_profile:
            logger.error(f"Failed to get user profile for user_id: {user_id}")
            return RegenerateRecoveryKeyResponse(
                success=False, 
                message="Failed to get user profile"
            )

        # Step 2: Delete old recovery key from encryption_keys
        try:
            delete_success = await directus_service.delete_encryption_key(
                hashed_user_id=hashed_user_id,
                login_method='recovery_key'
            )
            if delete_success:
                logger.info(f"Successfully deleted old recovery key for user {user_id}")
            else:
                # It's possible the user doesn't have a recovery key yet, which is fine
                logger.info(f"No existing recovery key found to delete for user {user_id}")
        except Exception as e:
            logger.warning(f"Error deleting old recovery key for user {user_id}: {e}")
            # Continue anyway - we'll create the new one

        # Step 3: Create new recovery key entry
        try:
            create_success = await directus_service.create_encryption_key(
                hashed_user_id=hashed_user_id,
                login_method='recovery_key',
                encrypted_key=regen_request.new_wrapped_master_key,
                salt=regen_request.new_salt,
                key_iv=regen_request.new_key_iv
            )
            
            if not create_success:
                logger.error(f"Failed to create new recovery key for user {user_id}")
                return RegenerateRecoveryKeyResponse(
                    success=False,
                    message="Failed to create new recovery key. Please try again."
                )
            
            logger.info(f"Successfully created new recovery key for user {user_id}")
        except Exception as e:
            logger.error(f"Error creating new recovery key for user {user_id}: {e}", exc_info=True)
            return RegenerateRecoveryKeyResponse(
                success=False,
                message="Failed to create new recovery key. Please try again."
            )

        # Step 4: Update lookup_hashes array
        # Get existing lookup_hashes
        lookup_hashes = user_profile.get("lookup_hashes", [])
        if not isinstance(lookup_hashes, list):
            lookup_hashes = []
            logger.warning(f"lookup_hashes is not a list, initializing empty array for user_id: {user_id}")

        # Remove old lookup hash if provided
        if regen_request.old_lookup_hash and regen_request.old_lookup_hash in lookup_hashes:
            lookup_hashes.remove(regen_request.old_lookup_hash)
            logger.info(f"Removed old lookup hash from user {user_id}")

        # Add new lookup hash
        if regen_request.new_lookup_hash not in lookup_hashes:
            lookup_hashes.append(regen_request.new_lookup_hash)
            logger.info(f"Added new lookup hash for user {user_id}")

        # Update user profile with new lookup_hashes and timestamp
        update_success = await directus_service.update_user(user_id, {
            "lookup_hashes": lookup_hashes,
            "consent_recovery_key_stored_timestamp": current_time
        })

        if not update_success:
            logger.error(f"Failed to update lookup_hashes for user {user_id}")
            return RegenerateRecoveryKeyResponse(
                success=False,
                message="Failed to update recovery key data. Please try again."
            )

        # Step 5: Invalidate relevant caches
        try:
            await cache_service.delete(f"user_profile:{user_id}")
            await cache_service.delete(f"login_methods:{user_id}")
            logger.info(f"Invalidated caches for user {user_id}")
        except Exception as e:
            logger.warning(f"Error invalidating caches for user {user_id}: {e}")
            # Non-critical, continue

        # Step 6: Log compliance event
        client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        compliance_service.log_auth_event(
            event_type="recovery_key_regenerated",
            user_id=user_id,
            ip_address=client_ip,
            status="success"
        )

        logger.info(f"Recovery key regeneration completed successfully for user {user_id}")

        return RegenerateRecoveryKeyResponse(
            success=True,
            message="Recovery key regenerated successfully. Make sure to save your new recovery key!"
        )

    except Exception as e:
        logger.error(f"Error in regenerate_recovery_key: {str(e)}", exc_info=True)
        return RegenerateRecoveryKeyResponse(
            success=False,
            message="An error occurred while regenerating recovery key"
        )