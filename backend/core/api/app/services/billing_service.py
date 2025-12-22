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
        usage_details: Optional[Dict[str, Any]] = None,
        api_key_hash: Optional[str] = None,  # SHA-256 hash of API key for tracking
        device_hash: Optional[str] = None,  # SHA-256 hash of device for tracking
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
            api_key_hash: Optional SHA-256 hash of the API key that created this usage entry (for API key-based usage)
            device_hash: Optional SHA-256 hash of the device that created this usage entry (for API key-based usage)
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
            
            # If user not in cache, fetch from Directus and cache it
            if not user:
                logger.info(f"User {user_id} not found in cache, fetching from Directus")
                profile_success, user_profile, profile_message = await self.directus_service.get_user_profile(user_id)
                
                if not profile_success or not user_profile:
                    logger.error(f"User profile not found in Directus for user {user_id}: {profile_message}")
                    raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found.")
                
                # Ensure user_id is present in the profile for caching
                if "user_id" not in user_profile:
                    user_profile["user_id"] = user_id
                if "id" not in user_profile:
                    user_profile["id"] = user_id
                
                # Cache the fetched profile
                await self.cache_service.set_user(user_profile, user_id=user_id)
                user = user_profile
                logger.info(f"Successfully fetched and cached user {user_id} from Directus")

            # Ensure credits are treated as integers, matching preprocessor logic
            current_credits = user.get("credits", 0)
            if not isinstance(current_credits, int):
                logger.warning(f"User credits for {user_id} were not an integer: {current_credits}. Converting to 0.")
                current_credits = 0

            # 2. Check for sufficient balance and calculate new balance
            # Skip balance check if payment is disabled (self-hosted mode)
            from backend.core.api.app.utils.server_mode import is_payment_enabled
            payment_enabled = is_payment_enabled()
            
            if payment_enabled:
                # Payment enabled - enforce credit balance checks
                if current_credits < credits_to_deduct:
                    # TODO this should be replaced later by checking during processing of a stream response if the user has enough credits for the tokens.
                    # and once that is not the case anymore, the stream should be stopped and the user informed to recharge their credits.
                    logger.warning(f"User {user_id} has insufficient credits: {current_credits} < {credits_to_deduct}. Setting credits to 0 and continuing.")
                    new_credits = 0
                    credits_to_deduct = current_credits  # Only charge what they have
                else:
                    new_credits = current_credits - credits_to_deduct
            else:
                # Payment disabled (self-hosted mode) - skip balance check but still track usage
                # Set new_credits to current_credits (no deduction) but still create usage entry
                logger.info(f"Payment disabled (self-hosted mode). Skipping credit balance check for user {user_id}. Credits remain: {current_credits}")
                new_credits = current_credits
                # Note: credits_to_deduct is still used for usage entry tracking, but not actually deducted
            user['credits'] = new_credits  # Store as integer in the dictionary for caching

            # 3. Update user in cache
            await self.cache_service.set_user(user, user_id=user_id)

            # 3.5. Check if low balance auto top-up should trigger (only if payment enabled)
            if payment_enabled:
                await self._check_and_trigger_low_balance_topup(user_id, user, new_credits)

            # 4. Update Directus with the encrypted string representation of the integer (only if payment enabled)
            # In self-hosted mode, we still track usage but don't update credit balance in Directus
            if payment_enabled:
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
            else:
                logger.debug(f"Payment disabled (self-hosted mode). Skipping Directus credit balance update for user {user_id}.")
            
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
            # CRITICAL: For incognito chats, use "incognito" as chat_id for aggregation
            chat_id = None
            message_id = None
            is_incognito = False
            if usage_details:
                # Check if this is an incognito chat
                is_incognito = usage_details.get("is_incognito", False)
                
                # Only use chat_id and message_id if they are non-empty strings
                chat_id_val = usage_details.get("chat_id")
                if chat_id_val and isinstance(chat_id_val, str) and chat_id_val.strip():
                    if is_incognito:
                        # For incognito chats, use "incognito" as chat_id for aggregation
                        chat_id = "incognito"
                        logger.debug(f"Using 'incognito' as chat_id for incognito chat usage tracking")
                    else:
                        chat_id = chat_id_val.strip()
                
                message_id_val = usage_details.get("message_id")
                if message_id_val and isinstance(message_id_val, str) and message_id_val.strip():
                    message_id = message_id_val.strip()
            
            # Determine source: "chat" if chat_id is provided, otherwise "api_key"
            source = "chat" if chat_id else "api_key"
            
            await self.directus_service.usage.create_usage_entry(
                user_id_hash=user_id_hash,
                app_id=app_id.strip(),  # Ensure no leading/trailing whitespace
                skill_id=skill_id.strip(),  # Ensure no leading/trailing whitespace
                usage_type="skill_execution",
                timestamp=timestamp,
                credits_charged=credits_to_deduct,
                user_vault_key_id=user['vault_key_id'],
                model_used=usage_details.get("model_used") if usage_details else None,
                chat_id=chat_id,  # Cleartext - for client-side matching with IndexedDB
                message_id=message_id,  # Cleartext - for client-side matching with IndexedDB
                source=source,  # "chat" or "api_key"
                actual_input_tokens=usage_details.get("input_tokens") if usage_details else None,
                actual_output_tokens=usage_details.get("output_tokens") if usage_details else None,
                api_key_hash=api_key_hash,  # API key hash for tracking which API key created this usage
                device_hash=device_hash,  # Device hash for tracking which device created this usage
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

            # Fixed threshold: always 100 credits (cannot be changed to simplify setup)
            # Enforce this even if database has a different value
            FIXED_THRESHOLD = 100
            threshold = user.get('auto_topup_low_balance_threshold')
            
            # If threshold is not set or is not 100, use the fixed value
            # This ensures consistency even if old data exists
            if threshold != FIXED_THRESHOLD:
                threshold = FIXED_THRESHOLD
                logger.debug(f"Using fixed threshold of {FIXED_THRESHOLD} credits for user {user_id} (stored value was {user.get('auto_topup_low_balance_threshold')})")

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
            # 1. Check cooldown period - but only if user now has sufficient credits
            # If they still have 0 credits, the previous auto top-up likely failed to add credits
            current_credits = user.get('credits', 0)
            last_triggered = await self._get_last_topup_timestamp(user)

            if last_triggered and (time.time() - last_triggered) < 3600:
                # If user has credits now, respect the cooldown
                if current_credits > 100:  # Above the auto top-up threshold
                    logger.info(f"Low balance auto top-up for user {user_id} on cooldown (last trigger: {int(time.time() - last_triggered)}s ago)")
                    return
                else:
                    # If user still has insufficient credits, previous auto top-up likely failed
                    # Allow retry but with a shorter cooldown (5 minutes) to prevent spam
                    if (time.time() - last_triggered) < 300:  # 5 minutes
                        logger.info(f"Auto top-up retry for user {user_id} on short cooldown (last trigger: {int(time.time() - last_triggered)}s ago, waiting 5min)")
                        return
                    else:
                        logger.info(f"Auto top-up retry for user {user_id} allowed - previous attempt may have failed to add credits")

            # 2. Get customer ID - required for payment method verification
            customer_id = user.get('stripe_customer_id')
            if not customer_id:
                logger.warning(f"No Stripe customer ID found for user {user_id} auto top-up. Feature may not be configured properly.")
                return

            # 3. Decrypt payment method
            logger.debug(f"Decrypting payment method for user {user_id} auto top-up")
            payment_method_id = await self._get_decrypted_payment_method(user)
            if not payment_method_id:
                logger.warning(f"No payment method found for user {user_id} auto top-up. Feature may not be configured properly.")
                return
            logger.debug(f"Successfully decrypted payment method for user {user_id}: pm_****{payment_method_id[-4:]}")

            # 4. Get configuration
            credits_amount = user.get('auto_topup_low_balance_amount')
            if not credits_amount or credits_amount <= 0:
                logger.warning(f"Invalid credits amount for user {user_id} auto top-up: {credits_amount}")
                return

            currency = user.get('auto_topup_low_balance_currency', 'eur').lower()

            # 5. Get pricing info from config
            price_data = await self._get_price_for_tier(credits_amount, currency)
            if not price_data:
                logger.error(f"No pricing found for {credits_amount} credits in {currency} for user {user_id}")
                return

            # 6. Get decrypted email for receipt
            logger.debug(f"Decrypting email for user {user_id} auto top-up")
            email = await self._get_decrypted_email(user)
            logger.debug(f"Email decryption result for user {user_id}: {'success' if email else 'failed/empty'}")

            # 7. Create PaymentIntent using existing payment service
            # Initialize SecretsManager with cache service
            from backend.core.api.app.utils.secrets_manager import SecretsManager
            from backend.core.api.app.services.payment.payment_service import PaymentService
            import os
            
            secrets_manager = SecretsManager(cache_service=self.cache_service)
            await secrets_manager.initialize()
            
            # Determine if production or sandbox environment
            is_production = os.getenv('ENVIRONMENT', 'development') == 'production'
            
            # Create and initialize PaymentService
            payment_service = PaymentService(secrets_manager=secrets_manager)
            await payment_service.initialize(is_production=is_production)

            # Create order with correct parameters
            # PaymentService.create_order expects: (amount, currency, email, credits_amount, customer_id)
            order_result = await payment_service.create_order(
                amount=price_data['amount'],  # Amount in cents from pricing config
                currency=currency,
                email=email,
                credits_amount=credits_amount,
                customer_id=customer_id  # Required for auto top-up with saved payment method
            )

            if not order_result or not order_result.get('client_secret'):
                logger.error(f"Failed to create payment intent for user {user_id} auto top-up")
                return

            # Cache the order for webhook processing (critical for credit addition)
            payment_intent_id = order_result['id']
            cache_success = await self.cache_service.set_order(
                order_id=payment_intent_id,
                user_id=user_id,
                credits_amount=credits_amount,
                currency=currency,
                status="auto_topup_pending",
                is_auto_topup=True  # Flag to indicate this is auto top-up (no client email key)
            )

            if not cache_success:
                logger.error(f"Failed to cache auto top-up order {payment_intent_id} for user {user_id}. Webhook processing will fail.")
                return

            # 8. Validate payment method belongs to customer and confirm payment
            import stripe
            stripe.api_key = await self._get_stripe_api_key()

            try:
                # Verify payment method belongs to customer (same validation as in payments.py)
                payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
                if payment_method.customer != customer_id:
                    logger.error(f"Payment method {payment_method_id} does not belong to customer {customer_id} for user {user_id}")
                    return

                # Use 'id' field from order_result (PaymentIntent ID)
                # Include return_url for automatic payment methods that might redirect
                confirmed_intent = stripe.PaymentIntent.confirm(
                    order_result['id'],
                    payment_method=payment_method_id,
                    return_url="https://app.openmates.com/billing/return"  # Dummy URL for auto top-up (not used)
                )

                logger.info(f"Auto top-up payment confirmed for user {user_id}: {credits_amount} credits, Payment Intent: {confirmed_intent.id}")

                # Update cached order status to completed so webhook can process it
                await self.cache_service.update_order_status(payment_intent_id, "auto_topup_confirmed")

            except stripe.error.StripeError as e:
                logger.error(f"Stripe error confirming auto top-up payment for user {user_id}: {e.user_message}", exc_info=True)
                # Update cached order status to failed
                await self.cache_service.update_order_status(payment_intent_id, "auto_topup_failed")
                return

            # 9. Update last triggered timestamp
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

            try:
                decrypted_timestamp = await self.encryption_service.decrypt_with_user_key(
                    ciphertext=encrypted_timestamp,
                    key_id=user['vault_key_id']
                )

                # Store in cache for next time
                timestamp_float = float(decrypted_timestamp)
                user['auto_topup_last_triggered'] = timestamp_float

                return timestamp_float
            except Exception as vault_error:
                logger.warning(f"Failed to decrypt auto_topup_last_triggered, treating as not set: {vault_error}")
                # Return None to indicate no timestamp available, which allows auto top-up to proceed
                return None
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
        For auto top-up, uses server-encrypted email field.
        Returns empty string if decryption fails.
        """
        try:
            # First try auto top-up specific email (server-encrypted)
            encrypted_email_auto_topup = user.get('encrypted_email_auto_topup')
            if encrypted_email_auto_topup:
                try:
                    decrypted_email = await self.encryption_service.decrypt_with_user_key(
                        ciphertext=encrypted_email_auto_topup,
                        key_id=user['vault_key_id']
                    )
                    logger.debug("Successfully decrypted auto top-up email")
                    return decrypted_email
                except Exception as auto_email_error:
                    logger.warning(f"Failed to decrypt auto top-up email, falling back to regular email: {auto_email_error}")

            # Fallback to regular encrypted email (client-encrypted)
            encrypted_email = user.get('encrypted_email_address')
            if not encrypted_email:
                logger.warning("No email address found for user")
                return ""

            decrypted_email = await self.encryption_service.decrypt_with_user_key(
                ciphertext=encrypted_email,
                key_id=user['vault_key_id']
            )
            logger.debug("Successfully decrypted regular email")
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

            # Try absolute path first (Docker standard)
            pricing_file = "/shared/config/pricing.yml"
            
            if not os.path.exists(pricing_file):
                # Fallback to relative path (local development)
                pricing_file = os.path.join(
                    os.path.dirname(__file__),
                    '../../../../../shared/config/pricing.yml'
                )

            logger.debug(f"Loading pricing config from: {pricing_file}")
            with open(pricing_file, 'r') as f:
                pricing_config = yaml.safe_load(f)

            # Find matching tier
            for tier in pricing_config.get('pricingTiers', []):
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
