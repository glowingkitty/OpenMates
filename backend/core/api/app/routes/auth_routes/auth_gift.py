import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService
from app.routes.auth_routes.auth_dependencies import (
    get_directus_service, get_cache_service, get_encryption_service, get_current_user # Import the correct dependency
)
from app.models.user import User # Import the User model

router = APIRouter()
logger = logging.getLogger(__name__)

# --- Schemas ---

class CheckGiftResponse(BaseModel):
    has_gift: bool
    amount: Optional[int] = None

class AcceptGiftResponse(BaseModel):
    success: bool
    message: str
    current_credits: Optional[int] = None


@router.get("/check-gift", response_model=CheckGiftResponse)
async def check_gift(
    current_user: User = Depends(get_current_user) # Use correct dependency and type hint
):
    """
    Check if the currently logged-in user has gifted credits from signup.
    """
    # Dependency get_current_user raises HTTPException if not authenticated

    gift_amount = current_user.gifted_credits_for_signup # Access attribute

    if gift_amount and gift_amount > 0: # Already checked for int in model/dependency
        logger.info(f"User {current_user.id} has {gift_amount} gifted credits available.")
        return CheckGiftResponse(has_gift=True, amount=gift_amount)
    else:
        logger.info(f"User {current_user.id} has no gifted credits available.")
        return CheckGiftResponse(has_gift=False, amount=None)

@router.post("/accept-gift", response_model=AcceptGiftResponse)
async def accept_gift(
    current_user: User = Depends(get_current_user), # Use correct dependency and type hint
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Accepts the gifted signup credits, adds them to the user's balance,
    and clears the gift flag.
    """
    # Dependency get_current_user raises HTTPException if not authenticated

    user_id = current_user.id
    vault_key_id = current_user.vault_key_id
    gift_amount = current_user.gifted_credits_for_signup
    current_credits = current_user.credits # Access attribute

    if not vault_key_id: # user_id is guaranteed by get_current_user
         logger.error(f"Cannot accept gift for user {user_id}: Missing vault_key_id.")
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User encryption key missing.")

    if not gift_amount or gift_amount <= 0:
        logger.warning(f"User {user_id} attempted to accept gift, but none available.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No gift available to accept.")

    logger.info(f"User {user_id} accepting gift of {gift_amount} credits. Current balance: {current_credits}.")

    try:
        # Calculate new balance
        current_credits = current_credits + gift_amount

        # Encrypt the new balance
        encrypted_current_credits_tuple = await encryption_service.encrypt_with_user_key(str(current_credits), vault_key_id)
        encrypted_current_credits = encrypted_current_credits_tuple[0]

        # Update Directus: Set new balance, clear gift field, set last_opened
        directus_update_payload = {
            "encrypted_credit_balance": encrypted_current_credits,
            "last_opened": "/chat/new",
            "encrypted_gifted_credits_for_signup": None # Clear the gift field
        }
        update_directus_success = await directus_service.update_user(user_id, directus_update_payload)

        if not update_directus_success:
            logger.error(f"Failed to update Directus record for user {user_id} after accepting gift.")
            # Don't update cache if Directus failed
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user record.")

        logger.info(f"Successfully updated Directus for user {user_id}. New balance (encrypted): {encrypted_current_credits[:10]}..., Last opened: /chat/new, Gift cleared.")

        # Update Cache: Set new balance, clear gift field, set last_opened
        cache_update_payload = {
            "credits": current_credits,
            "last_opened": "/chat/new",
            "gifted_credits_for_signup": None # Clear the gift field from cache
        }
        update_cache_success = await cache_service.update_user(user_id, cache_update_payload)

        if not update_cache_success:
            # Log warning but proceed, Directus is the source of truth
            logger.warning(f"Failed to update cache for user {user_id} after accepting gift. Directus was updated.")
        else:
             logger.info(f"Successfully updated cache for user {user_id}. New balance: {current_credits}, Last opened: /chat/new, Gift cleared.")

        return AcceptGiftResponse(success=True, message="Gift accepted successfully.", current_credits=current_credits)

    except Exception as e:
        logger.error(f"Error accepting gift for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while accepting the gift.")