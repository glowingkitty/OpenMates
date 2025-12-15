import os
from typing import Optional, Dict, Any
from backend.core.api.app.services.payment.revolut_service import RevolutService
from backend.core.api.app.services.payment.stripe_service import StripeService
from backend.core.api.app.utils.secrets_manager import SecretsManager

class PaymentService:
    def __init__(self, secrets_manager: SecretsManager):
        self.secrets_manager = secrets_manager
        self.provider_name = os.getenv("PAYMENT_PROVIDER", "Stripe").lower()
        if self.provider_name == "stripe":
            self.provider = StripeService(secrets_manager)
        elif self.provider_name == "revolut":
            self.provider = RevolutService(secrets_manager)
        else:
            raise ValueError(f"Unsupported payment provider: {self.provider_name}")

    async def initialize(self, is_production: bool):
        await self.provider.initialize(is_production)

    async def create_order(self, amount: int, currency: str, email: str, credits_amount: int, customer_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Delegates order creation to the active payment provider.
        
        Args:
            amount: Amount in smallest currency unit
            currency: Currency code
            email: Customer email
            credits_amount: Number of credits
            customer_id: Optional existing customer ID (for Stripe)
        """
        return await self.provider.create_order(amount, currency, email, credits_amount, customer_id)

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Delegates order retrieval to the active payment provider.
        """
        return await self.provider.get_order(order_id)

    async def verify_and_parse_webhook(self, payload: bytes, sig_header: str, request_timestamp_header: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Delegates webhook verification and parsing to the active payment provider.
        The request_timestamp_header is only used by Revolut.
        """
        if self.provider_name == "revolut":
            # Revolut's verify_and_parse_webhook returns (is_valid, payload) tuple
            is_valid, parsed_payload = await self.provider.verify_and_parse_webhook(payload, sig_header, request_timestamp_header)
            return parsed_payload if is_valid else None
        elif self.provider_name == "stripe":
            # Stripe's verify_and_parse_webhook returns the event object or None
            return await self.provider.verify_and_parse_webhook(payload, sig_header)
        return None

    async def refund_payment(self, payment_intent_id: str, amount: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Delegates refund processing to the active payment provider.
        
        Args:
            payment_intent_id: The payment intent/order ID
            amount: Optional amount to refund in cents. If None, refunds the full amount.
            
        Returns:
            A dictionary containing refund details, or None if an error occurred.
        """
        if hasattr(self.provider, 'refund_payment'):
            return await self.provider.refund_payment(payment_intent_id, amount)
        else:
            logger.error(f"Refund not supported for provider {self.provider_name}")
            return None

    async def close(self):
        await self.provider.close()
