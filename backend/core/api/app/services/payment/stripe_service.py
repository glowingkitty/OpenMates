import stripe
import logging
from typing import Optional, Dict, Any
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

class StripeService:
    def __init__(self, secrets_manager: SecretsManager):
        self.secrets_manager = secrets_manager
        self._is_production = False
        self.api_key = None
        self.webhook_secret = None
        self.provider_name = "stripe" # Consistent with RevolutService

    async def initialize(self, is_production: bool):
        self._is_production = is_production
        self.api_key = await self._get_api_key()
        if not self.api_key:
            raise ValueError(f"Stripe API key for {'production' if is_production else 'sandbox'} environment is missing. Please add SECRET__STRIPE__{('PRODUCTION' if is_production else 'SANDBOX')}_SECRET_KEY to your Vault configuration.")
        
        self.webhook_secret = await self._get_webhook_secret()
        if not self.webhook_secret:
            raise ValueError(f"Stripe Webhook Secret for {'production' if is_production else 'sandbox'} environment is missing. Please add SECRET__STRIPE__{('PRODUCTION' if is_production else 'SANDBOX')}_WEBHOOK_SECRET to your Vault configuration.")
        
        stripe.api_key = self.api_key
        logger.info(f"StripeService initialized. Production: {self._is_production}")

    async def _get_api_key(self):
        key_suffix = "secret_key"
        if self._is_production:
            secret_key_name = f"production_{key_suffix}"
        else:
            secret_key_name = f"sandbox_{key_suffix}"
        
        secret_path = f"kv/data/providers/{self.provider_name}"
        api_key = await self.secrets_manager.get_secret(secret_path=secret_path, secret_key=secret_key_name)
        if not api_key:
            logger.error(f"Stripe Secret Key '{secret_key_name}' not found in '{secret_path}' using Secrets Manager.")
        return api_key

    async def _get_webhook_secret(self):
        key_suffix = "webhook_secret"
        if self._is_production:
            secret_key_name = f"production_{key_suffix}"
        else:
            secret_key_name = f"sandbox_{key_suffix}"

        secret_path = f"kv/data/providers/{self.provider_name}"
        secret = await self.secrets_manager.get_secret(secret_path=secret_path, secret_key=secret_key_name)
        if not secret:
            logger.error(f"Stripe Webhook Secret '{secret_key_name}' not found in '{secret_path}' using Secrets Manager.")
        return secret

    async def create_order(self, amount: int, currency: str, email: str, credits_amount: int) -> Optional[Dict[str, Any]]:
        """
        Creates a Stripe PaymentIntent.

        Args:
            amount: Amount in the smallest currency unit (e.g., cents).
            currency: 3-letter ISO currency code (e.g., "EUR").
            email: Customer's email address.
            credits_amount: Number of credits being purchased (for metadata).

        Returns:
            A dictionary containing the PaymentIntent details, including 'id' and 'client_secret',
            or None if an error occurred.
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            # Stripe PaymentIntents require amount in cents (or smallest currency unit)
            # The `amount` passed here is already in the smallest unit.
            payment_intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                receipt_email=email,
                metadata={
                    "credits_purchased": str(credits_amount),
                    "purchase_type": "credits",
                    "customer_email": email, # Store email in metadata for easier lookup
                },
                automatic_payment_methods={"enabled": True},
            )
            logger.info(f"Stripe PaymentIntent created successfully. ID: {payment_intent.id}")
            return {
                "id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "status": payment_intent.status,
            }
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error creating PaymentIntent: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating Stripe PaymentIntent: {str(e)}", exc_info=True)
            return None

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a Stripe PaymentIntent by its ID.

        Args:
            order_id: The ID of the PaymentIntent.

        Returns:
            A dictionary containing the PaymentIntent details, or None if not found or an error occurred.
        """
        if not self.api_key:
            logger.error("Stripe API key not initialized.")
            return None

        try:
            payment_intent = stripe.PaymentIntent.retrieve(order_id)
            logger.info(f"Stripe PaymentIntent retrieved. ID: {payment_intent.id}, Status: {payment_intent.status}")
            return {
                "id": payment_intent.id,
                "status": payment_intent.status,
                "client_secret": payment_intent.client_secret,
                "metadata": payment_intent.metadata,
            }
        except stripe.error.InvalidRequestError as e:
            if "No such payment_intent" in str(e):
                logger.warning(f"Stripe PaymentIntent {order_id} not found.")
                return None
            logger.error(f"Stripe API error retrieving PaymentIntent {order_id}: {e.user_message}", exc_info=True)
            return None
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error retrieving PaymentIntent {order_id}: {e.user_message}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving Stripe PaymentIntent {order_id}: {str(e)}", exc_info=True)
            return None

    async def verify_and_parse_webhook(self, payload: bytes, sig_header: str) -> Optional[Dict[str, Any]]:
        """
        Verifies the Stripe webhook signature and parses the event.

        Args:
            payload: The raw request body bytes.
            sig_header: The value of the 'Stripe-Signature' header.

        Returns:
            The parsed Stripe Event object as a dictionary, or None if verification fails.
        """
        if not self.webhook_secret:
            logger.error("Stripe Webhook Secret not initialized.")
            return None

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            logger.info(f"Stripe webhook event verified successfully. Type: {event.type}")
            return event.to_dict()
        except ValueError as e:
            # Invalid payload
            logger.error(f"Stripe webhook ValueError: Invalid payload: {str(e)}")
            return None
        except stripe.error.SignatureVerificationError as e:
            # Invalid signature
            logger.error(f"Stripe webhook SignatureVerificationError: Invalid signature: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error verifying Stripe webhook: {str(e)}", exc_info=True)
            return None

    async def close(self):
        logger.info("StripeService close called.")
        pass
