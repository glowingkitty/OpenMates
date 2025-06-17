import logging
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
import time
import asyncio
from typing import Dict, Any, Optional

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.websockets import manager as websocket_manager

logger = logging.getLogger(__name__)

class BillingService:
    def __init__(
        self,
        cache_service: CacheService,
        directus_service: DirectusService,
        encryption_service: EncryptionService,
    ):
        self.cache_service = cache_service
        self.directus_service = directus_service
        self.encryption_service = encryption_service
        self.websocket_manager = websocket_manager

    async def charge_user_credits(
        self,
        user_id: str,
        credits_to_deduct: int,
        user_id_hash: str,
        app_id: str,
        skill_id: str,
        usage_details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Deducts credits and records the usage entry.
        """
        if not isinstance(credits_to_deduct, int) or credits_to_deduct < 0:
            raise HTTPException(status_code=400, detail="Credits to deduct must be a non-negative integer.")

        try:
            # 1. Get user profile using the cache service
            user = await self.cache_service.get_user_by_id(user_id)
            if not user:
                raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found.")

            # Ensure credits are treated as integers, matching preprocessor logic
            current_credits = user.get("credits", 0)
            if not isinstance(current_credits, int):
                logger.warning(f"User credits for {user_id} were not an integer: {current_credits}. Converting to 0.")
                current_credits = 0

            # 2. Check for sufficient balance and calculate new balance
            if current_credits < credits_to_deduct:
                raise HTTPException(status_code=402, detail="Insufficient credits.")

            new_credits = current_credits - credits_to_deduct
            user['credits'] = new_credits  # Store as integer in the dictionary for caching

            # 3. Update user in cache
            await self.cache_service.set_user(user, user_id=user_id)

            # 4. Update Directus with the encrypted string representation of the integer
            encrypted_new_credits_tuple = await self.encryption_service.encrypt_with_user_key(
                plaintext=str(new_credits),
                key_id=user['vault_key_id']
            )
            encrypted_new_credits = encrypted_new_credits_tuple[0] # Extract the encrypted string from the tuple
            # 4. Update Directus with retry logic
            max_retries = 3
            retry_delay = 5  # seconds
            for attempt in range(max_retries):
                update_successful = await self.directus_service.update_user(
                    user_id, {"encrypted_credit_balance": encrypted_new_credits}
                )
                if update_successful:
                    logger.info(f"Successfully updated user {user_id} credits in Directus on attempt {attempt + 1}.")
                    break
                else:
                    logger.warning(
                        f"Attempt {attempt + 1} to update user {user_id} credits in Directus failed. "
                        f"Retrying in {retry_delay} seconds..."
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
            else:
                # This block executes if the loop completes without a `break`
                logger.critical(
                    f"CRITICAL: Failed to update user {user_id} credits in Directus after {max_retries} attempts. "
                    f"The user has been charged in cache, but the database update failed. Manual intervention required."
                )
                # We do NOT revert the cache. The charge is valid.
                # We raise an exception to inform the client of the persistent failure.
                raise HTTPException(
                    status_code=500,
                    detail="Your transaction was completed, but there was a delay in saving the final balance. Please refresh shortly."
                )
            
            logger.info(f"Successfully charged {credits_to_deduct} credits from user {user_id}. New balance: {new_credits}")

            # 5. Broadcast the new credit balance to all user devices
            await self.websocket_manager.broadcast_to_user(
                user_id=user_id,
                message={
                    "type": "user_credits_updated",
                    "payload": {"credits": new_credits}
                }
            )

            # 6. Create usage entry
            timestamp = int(time.time())
            await self.directus_service.usage.create_usage_entry(
                user_id_hash=user_id_hash,
                app_id=app_id,
                skill_id=skill_id,
                usage_type="skill_execution",
                timestamp=timestamp,
                credits_charged=credits_to_deduct,
                user_vault_key_id=user['vault_key_id'],
                model_used=usage_details.get("model_used") if usage_details else None,
                chat_id=usage_details.get("chat_id") if usage_details else None,
                message_id=usage_details.get("message_id") if usage_details else None,
                actual_input_tokens=usage_details.get("input_tokens") if usage_details else None,
                actual_output_tokens=usage_details.get("output_tokens") if usage_details else None,
            )

        except HTTPException as e:
            # Re-raise HTTPExceptions to be handled by FastAPI
            raise e
        except Exception as e:
            logger.error(f"An unexpected error occurred while charging credits for user {user_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="An internal error occurred during credit deduction.")
