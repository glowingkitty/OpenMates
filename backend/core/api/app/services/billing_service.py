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
        
        Args:
            user_id: Actual user ID for cache lookup
            credits_to_deduct: Number of credits to charge
            user_id_hash: Hashed user ID for privacy
            app_id: ID of the app that executed the skill (required, must not be empty)
            skill_id: ID of the skill that was executed (required, must not be empty)
            usage_details: Optional dict containing additional usage metadata:
                - chat_id: Chat ID if skill was triggered in a chat context
                - message_id: Message ID if skill was triggered from a message
                - model_used: Model identifier if applicable
                - input_tokens: Input token count if applicable
                - output_tokens: Output token count if applicable
        """
        if not isinstance(credits_to_deduct, int) or credits_to_deduct < 0:
            raise HTTPException(status_code=400, detail="Credits to deduct must be a non-negative integer.")
        
        # Validate required fields - app_id and skill_id must be provided and non-empty
        if not app_id or not isinstance(app_id, str) or not app_id.strip():
            logger.error(f"Invalid app_id provided for credit charge: {app_id}. Cannot create usage entry.")
            raise HTTPException(status_code=400, detail="app_id is required and must not be empty.")
        
        if not skill_id or not isinstance(skill_id, str) or not skill_id.strip():
            logger.error(f"Invalid skill_id provided for credit charge: {skill_id}. Cannot create usage entry.")
            raise HTTPException(status_code=400, detail="skill_id is required and must not be empty.")

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
                # TODO this should be replaced later by checking during processing of a stream response if the user has enough credits for the tokens.
                # and once that is not the case anymore, the stream should be stopped and the user informed to recharge their credits.
                logger.warning(f"User {user_id} has insufficient credits: {current_credits} < {credits_to_deduct}. Setting credits to 0 and continuing.")
                new_credits = 0
                credits_to_deduct = current_credits  # Only charge what they have
            else:
                new_credits = current_credits - credits_to_deduct
            user['credits'] = new_credits  # Store as integer in the dictionary for caching

            # 3. Update user in cache
            await self.cache_service.set_user(user, user_id=user_id)

            # 3.5. Check if low balance auto top-up should trigger
            await self._check_and_trigger_low_balance_topup(user_id, user, new_credits)

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
            # Extract optional fields from usage_details, ensuring we only pass non-empty values
            # chat_id and message_id should be included when skill is triggered in a chat context
            timestamp = int(time.time())
            
            # Extract chat_id and message_id from usage_details if available
            # These are important for linking usage entries to chat sessions
            chat_id = None
            message_id = None
            if usage_details:
                # Only use chat_id and message_id if they are non-empty strings
                chat_id_val = usage_details.get("chat_id")
                if chat_id_val and isinstance(chat_id_val, str) and chat_id_val.strip():
                    chat_id = chat_id_val.strip()
                
                message_id_val = usage_details.get("message_id")
                if message_id_val and isinstance(message_id_val, str) and message_id_val.strip():
                    message_id = message_id_val.strip()
            
            await self.directus_service.usage.create_usage_entry(
                user_id_hash=user_id_hash,
                app_id=app_id.strip(),  # Ensure no leading/trailing whitespace
                skill_id=skill_id.strip(),  # Ensure no leading/trailing whitespace
                usage_type="skill_execution",
                timestamp=timestamp,
                credits_charged=credits_to_deduct,
                user_vault_key_id=user['vault_key_id'],
                model_used=usage_details.get("model_used") if usage_details else None,
                chat_id=chat_id,  # Only set if provided and non-empty
                message_id=message_id,  # Only set if provided and non-empty
                actual_input_tokens=usage_details.get("input_tokens") if usage_details else None,
                actual_output_tokens=usage_details.get("output_tokens") if usage_details else None,
            )

        except HTTPException as e:
            # Re-raise HTTPExceptions to be handled by FastAPI
            raise e
        except Exception as e:
            logger.error(f"An unexpected error occurred while charging credits for user {user_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="An internal error occurred during credit deduction.")

    async def _check_and_trigger_low_balance_topup(
        self,
        user_id: str,
        user: Dict[str, Any],
        new_credits: int
    ) -> None:
        """
        Checks if low balance auto top-up should trigger and initiates it asynchronously.
        This method is fire-and-forget to not block the credit deduction.
        """
        try:
            # Check if feature is enabled and threshold is set
            if not user.get('auto_topup_low_balance_enabled', False):
                return

            threshold = user.get('auto_topup_low_balance_threshold', 0)
            if threshold <= 0:
                return

            # Check if balance is at or below threshold
            if new_credits > threshold:
                return

            logger.info(f"Low balance detected for user {user_id}: {new_credits} <= {threshold}. Triggering auto top-up.")

            # Trigger async top-up (fire and forget - don't block current request)
            asyncio.create_task(
                self._trigger_low_balance_topup(user_id, user)
            )

        except Exception as e:
            # Log but don't raise - we don't want to fail the main credit deduction
            logger.error(f"Error checking low balance auto top-up for user {user_id}: {e}", exc_info=True)

    async def _trigger_low_balance_topup(
        self,
        user_id: str,
        user: Dict[str, Any]
    ) -> None:
        """
        Triggers automatic credit purchase when balance falls below threshold.
        Runs asynchronously to not block the main credit deduction.
        """
        try:
            # 1. Check cooldown period (prevent multiple triggers within 1 hour)
            last_triggered = await self._get_last_topup_timestamp(user)
            if last_triggered and (time.time() - last_triggered) < 3600:
                logger.info(f"Low balance auto top-up for user {user_id} on cooldown (last trigger: {int(time.time() - last_triggered)}s ago)")
                return

            # 2. Decrypt payment method
            payment_method_id = await self._get_decrypted_payment_method(user)
            if not payment_method_id:
                logger.warning(f"No payment method found for user {user_id} auto top-up. Feature may not be configured properly.")
                return

            # 3. Get configuration
            credits_amount = user.get('auto_topup_low_balance_amount')
            if not credits_amount or credits_amount <= 0:
                logger.warning(f"Invalid credits amount for user {user_id} auto top-up: {credits_amount}")
                return

            currency = user.get('auto_topup_low_balance_currency', 'eur').lower()

            # 4. Get pricing info from config
            price_data = await self._get_price_for_tier(credits_amount, currency)
            if not price_data:
                logger.error(f"No pricing found for {credits_amount} credits in {currency} for user {user_id}")
                return

            # 5. Get decrypted email for receipt
            email = await self._get_decrypted_email(user)

            # 6. Create one-time PaymentIntent using existing payment service
            from backend.core.api.app.services.payment.payment_service import PaymentService
            payment_service = PaymentService(self.cache_service, self.directus_service, self.encryption_service)

            order_result = await payment_service.create_order(
                user_id=user_id,
                credits=credits_amount,
                currency=currency,
                provider="stripe",  # For now, only Stripe
                email=email
            )

            if not order_result or not order_result.get('client_secret'):
                logger.error(f"Failed to create payment intent for user {user_id} auto top-up")
                return

            # 7. Confirm payment with saved payment method using Stripe directly
            import stripe
            stripe.api_key = await self._get_stripe_api_key()

            try:
                confirmed_intent = stripe.PaymentIntent.confirm(
                    order_result['order_id'],
                    payment_method=payment_method_id
                )

                logger.info(f"Auto top-up payment confirmed for user {user_id}: {credits_amount} credits, Payment Intent: {confirmed_intent.id}")

            except stripe.error.StripeError as e:
                logger.error(f"Stripe error confirming auto top-up payment for user {user_id}: {e.user_message}", exc_info=True)
                return

            # 8. Update last triggered timestamp
            await self._update_last_topup_timestamp(user_id)

            logger.info(f"✅ Auto top-up successfully triggered for user {user_id}: {credits_amount} credits via {currency.upper()}")

        except Exception as e:
            logger.error(f"❌ Auto top-up failed for user {user_id}: {e}", exc_info=True)
            # Don't raise - this is a background operation

    async def _get_last_topup_timestamp(self, user: Dict[str, Any]) -> Optional[float]:
        """
        Retrieves the last auto top-up timestamp.
        Checks cache first (plaintext float), falls back to decrypting from Directus if needed.
        Returns timestamp as float (Unix time) or None if not set.
        """
        try:
            # Check cache first (stored as float)
            cached_timestamp = user.get('auto_topup_last_triggered')
            if cached_timestamp is not None:
                return float(cached_timestamp)

            # Fallback: decrypt from encrypted field if not in cache
            encrypted_timestamp = user.get('encrypted_auto_topup_last_triggered')
            if not encrypted_timestamp:
                return None

            decrypted_timestamp = await self.encryption_service.decrypt_with_user_key(
                ciphertext=encrypted_timestamp,
                key_id=user['vault_key_id']
            )

            # Store in cache for next time
            timestamp_float = float(decrypted_timestamp)
            user['auto_topup_last_triggered'] = timestamp_float

            return timestamp_float
        except Exception as e:
            logger.warning(f"Error getting last topup timestamp: {e}")
            return None

    async def _update_last_topup_timestamp(self, user_id: str) -> None:
        """
        Updates the last auto top-up timestamp to current time.
        Follows cache-first pattern: update cache, then Directus.
        Cache stores plaintext timestamp (float), Directus stores encrypted.
        """
        try:
            # Get user from cache
            user = await self.cache_service.get_user_by_id(user_id)
            if not user:
                logger.error(f"User {user_id} not found when updating topup timestamp")
                return

            # Current timestamp
            current_time = time.time()

            # 1. Update cache first (store as float in cache)
            user['auto_topup_last_triggered'] = current_time
            await self.cache_service.set_user(user, user_id=user_id)

            # 2. Encrypt timestamp for Directus
            encrypted_timestamp_tuple = await self.encryption_service.encrypt_with_user_key(
                plaintext=str(current_time),
                key_id=user['vault_key_id']
            )
            encrypted_timestamp = encrypted_timestamp_tuple[0]

            # 3. Update Directus
            await self.directus_service.update_user(
                user_id,
                {"encrypted_auto_topup_last_triggered": encrypted_timestamp}
            )

            logger.debug(f"Updated last topup timestamp for user {user_id}: {current_time}")

        except Exception as e:
            logger.error(f"Error updating last topup timestamp for user {user_id}: {e}", exc_info=True)

    async def _get_decrypted_payment_method(self, user: Dict[str, Any]) -> Optional[str]:
        """
        Decrypts and returns the saved payment method ID.
        Returns None if not found or decryption fails.
        """
        try:
            encrypted_pm = user.get('encrypted_payment_method_id')
            if not encrypted_pm:
                return None

            decrypted_pm = await self.encryption_service.decrypt_with_user_key(
                ciphertext=encrypted_pm,
                key_id=user['vault_key_id']
            )

            return decrypted_pm
        except Exception as e:
            logger.error(f"Error decrypting payment method: {e}", exc_info=True)
            return None

    async def _get_decrypted_email(self, user: Dict[str, Any]) -> str:
        """
        Decrypts and returns user email for receipts.
        Returns empty string if decryption fails.
        """
        try:
            encrypted_email = user.get('encrypted_email_address')
            if not encrypted_email:
                return ""

            decrypted_email = await self.encryption_service.decrypt_with_user_key(
                ciphertext=encrypted_email,
                key_id=user['vault_key_id']
            )

            return decrypted_email
        except Exception as e:
            logger.warning(f"Error decrypting email: {e}")
            return ""

    async def _get_price_for_tier(self, credits_amount: int, currency: str) -> Optional[Dict[str, Any]]:
        """
        Gets price information for a credit tier from pricing config.
        Returns dict with 'amount' (in cents) and 'currency', or None if not found.
        """
        try:
            # Import pricing config
            import yaml
            import os

            pricing_file = os.path.join(
                os.path.dirname(__file__),
                '../../../../../shared/config/pricing.yml'
            )

            with open(pricing_file, 'r') as f:
                pricing_config = yaml.safe_load(f)

            # Find matching tier
            for tier in pricing_config.get('tiers', []):
                if tier.get('credits') == credits_amount:
                    price = tier.get('price', {}).get(currency)
                    if price is not None:
                        # Convert to cents (Stripe expects smallest currency unit)
                        if currency.lower() == 'jpy':
                            amount_cents = int(price)  # JPY has no decimal
                        else:
                            amount_cents = int(price * 100)  # EUR/USD use cents

                        return {
                            'amount': amount_cents,
                            'currency': currency
                        }

            logger.warning(f"No pricing found for {credits_amount} credits in {currency}")
            return None

        except Exception as e:
            logger.error(f"Error loading pricing config: {e}", exc_info=True)
            return None

    async def _get_stripe_api_key(self) -> str:
        """
        Gets Stripe API key from secrets manager.
        This is a simplified version - in production you'd use the StripeService.
        """
        try:
            from backend.core.api.app.utils.secrets_manager import SecretsManager
            secrets_manager = SecretsManager()

            # Determine if production or sandbox
            import os
            is_production = os.getenv('ENVIRONMENT', 'development') == 'production'

            key_suffix = "production_secret_key" if is_production else "sandbox_secret_key"
            secret_path = "kv/data/providers/stripe"

            api_key = await secrets_manager.get_secret(
                secret_path=secret_path,
                secret_key=key_suffix
            )

            if not api_key:
                raise ValueError(f"Stripe API key not found in vault")

            return api_key

        except Exception as e:
            logger.error(f"Error getting Stripe API key: {e}", exc_info=True)
            raise
