"""
Payment Service

Top-level orchestrator that holds all payment providers simultaneously
and selects the correct one based on user region and any explicit override.

Routing logic:
  - EU users → Stripe PaymentIntent (standard EU prices, no VAT via §19 UStG)
  - Non-EU users → Stripe Managed Payments (Checkout Session, global prices)
  - SEPA bank transfers → Revolut Business (separate flow, not region-based)

All providers are always initialized at startup so provider switching
is instant (no re-initialization on override).
"""

import logging
from typing import Optional, Dict, Any, Tuple

from backend.core.api.app.services.payment.stripe_service import StripeService
from backend.core.api.app.services.payment.revolut_business_service import RevolutBusinessService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


class PaymentService:
    """
    Manages all payment providers and routes transactions to the correct one.

    Provider selection priority (highest to lowest):
      1. Explicit provider_override in the request
      2. Region-based detection: EU → Stripe PaymentIntent, non-EU → Stripe Managed Payments
    """

    def __init__(self, secrets_manager: SecretsManager) -> None:
        self.secrets_manager = secrets_manager

        self._stripe_provider: Optional[StripeService] = StripeService(secrets_manager)
        self._revolut_business: Optional[RevolutBusinessService] = RevolutBusinessService(secrets_manager)
        # Default provider_name for legacy callers (e.g. /payments/config without override)
        self.provider_name = "stripe"
        # Legacy .provider points to Stripe for backwards compatibility
        # (StripeProductSync accesses payment_service.provider directly)
        self.provider = self._stripe_provider
        logger.info("PaymentService: initialized with Stripe + Revolut Business SEPA")

    async def initialize(self, is_production: bool) -> None:
        """
        Initialize all active providers by loading credentials from Vault.

        Args:
            is_production: True for live environment, False for sandbox
        """
        if self._stripe_provider:
            await self._stripe_provider.initialize(is_production)
            logger.info("PaymentService: Stripe provider initialized")

        if self._revolut_business:
            try:
                await self._revolut_business.initialize(is_production)
                logger.info("PaymentService: Revolut Business provider initialized (SEPA transfers)")
            except ValueError as exc:
                # Revolut Business credentials missing — log warning but don't fail startup.
                # SEPA bank transfers won't be available until credentials are added to Vault.
                logger.warning(
                    f"PaymentService: Revolut Business provider could not be initialized "
                    f"(credentials missing from Vault): {exc}. "
                    f"SEPA bank transfer option will be disabled."
                )
                self._revolut_business = None

    def get_provider(
        self,
        is_eu: bool,
        provider_override: Optional[str] = None,
    ) -> Tuple[str, Any]:
        """
        Select the correct payment provider based on region and optional override.

        Args:
            is_eu: True if the user's IP resolves to an EU/EEA/CH/GB country
            provider_override: Optional explicit provider name ("stripe" or "managed")

        Returns:
            Tuple of (provider_name, provider_instance)
        """
        # Explicit override takes highest priority
        if provider_override:
            normalized = provider_override.lower().strip()
            if normalized == "stripe":
                return ("stripe", self._stripe_provider)
            elif normalized == "managed":
                return ("stripe_managed", self._stripe_provider)
            else:
                logger.warning(
                    f"PaymentService: unknown provider_override '{provider_override}', "
                    f"falling back to region-based selection"
                )

        # Region-based selection
        if is_eu:
            return ("stripe", self._stripe_provider)
        else:
            return ("stripe_managed", self._stripe_provider)

    async def create_order(
        self,
        amount: int,
        currency: str,
        email: str,
        credits_amount: int,
        customer_id: Optional[str] = None,
        provider_override: Optional[str] = None,
        is_eu: bool = True,
        success_url: Optional[str] = None,
        embed_origin: Optional[str] = None,
        return_url: Optional[str] = None,
        use_global_pricing: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a payment order through the appropriate provider.

        Args:
            amount: Amount in smallest currency unit (cents for EUR)
            currency: ISO currency code
            email: Customer email
            credits_amount: Number of credits being purchased
            customer_id: Optional existing customer ID (provider-specific)
            provider_override: Optional explicit provider ("stripe" or "managed")
            is_eu: Whether the user is in the EU VAT territory (EU27 only)
            success_url: Unused — kept for signature compatibility
            embed_origin: Unused — kept for signature compatibility
            return_url: URL Stripe redirects to after Embedded Checkout
            use_global_pricing: Non-EU path — use global product prices with
                Stripe Managed Payments (Checkout Session). EU path uses
                PaymentIntents at standard EU prices.

        Returns:
            Provider-specific order dict, or None on error
        """
        provider_name, provider = self.get_provider(is_eu, provider_override)

        if provider_name == "stripe_managed" or use_global_pricing:
            # Non-EU: Stripe Managed Payments via Checkout Session, global prices
            return await provider.create_order(
                amount, currency, email, credits_amount, customer_id,
                return_url=return_url, use_global_pricing=True,
            )
        else:
            # EU27: regular Stripe PaymentIntent, standard EU prices, no VAT
            return await provider.create_order_eu(
                amount, currency, email, credits_amount, customer_id,
            )

    async def create_support_order(
        self,
        amount: int,
        currency: str,
        email: str,
        is_recurring: bool,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Supporter contributions always use Stripe (for all users, all regions).
        """
        # Support orders always go through Stripe regardless of region
        if self._stripe_provider is None:
            logger.error("PaymentService.create_support_order: Stripe provider not available")
            return None
        return await self._stripe_provider.create_support_order(
            amount, currency, email, is_recurring, user_id
        )

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve an order by ID.

        For managed Stripe orders the order_id is a Checkout Session ID (cs_...).
        For direct Stripe orders it's a PaymentIntent ID (pi_...).
        The correct provider is determined by the ID prefix.

        Args:
            order_id: Provider-specific order/checkout ID

        Returns:
            Normalized order dict, or None on error
        """
        return await self._stripe_provider.get_order(order_id)

    async def verify_and_parse_webhook(
        self,
        payload: bytes,
        sig_header: str,
        request_timestamp_header: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Verify and parse a Stripe webhook event.
        """
        return await self._stripe_provider.verify_and_parse_webhook(payload, sig_header)

    async def verify_revolut_business_webhook(
        self,
        payload: bytes,
        timestamp_header: Optional[str],
        signature_header: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Verify and parse a Revolut Business webhook event.

        Called from payments.py when Revolut-Signature header is detected.

        Args:
            payload: Raw request body bytes
            timestamp_header: Value of Revolut-Request-Timestamp header
            signature_header: Value of Revolut-Signature header

        Returns:
            Parsed event dict if signature valid, None otherwise
        """
        if not self._revolut_business:
            logger.error(
                "PaymentService: received Revolut Business webhook but provider not initialized"
            )
            return None
        return await self._revolut_business.verify_webhook(
            payload, timestamp_header, signature_header
        )

    def get_bank_transfer_details(self) -> Optional[Dict[str, str]]:
        """
        Get company bank details for SEPA transfer display.

        Returns:
            Dict with 'iban', 'bic', 'bank_name', or None if Revolut Business not configured
        """
        if not self._revolut_business:
            return None
        return self._revolut_business.get_bank_details()

    @property
    def revolut_business(self) -> Optional[RevolutBusinessService]:
        """Direct access to the Revolut Business service for transfer parsing."""
        return self._revolut_business

    @property
    def is_bank_transfer_available(self) -> bool:
        """Whether SEPA bank transfer payments are available.

        Requires IBAN and BIC to be configured. The webhook secret is optional —
        its absence only disables automatic incoming transfer processing, not the
        payment option itself.
        """
        if self._revolut_business is None:
            return False
        details = self._revolut_business.get_bank_details()
        return bool(details.get("iban") and details.get("bic"))

    async def refund_payment(
        self,
        payment_intent_id: str,
        amount: Optional[int] = None,
        provider: Optional[str] = None,
        reason: str = "customer_request",
    ) -> Optional[Dict[str, Any]]:
        """
        Refund a payment via Stripe.

        Args:
            payment_intent_id: Stripe PaymentIntent ID ('pi_...').
            amount: Refund amount in smallest currency unit (cents). If None, full refund.
            provider: Explicit provider name ('stripe' or 'stripe_managed') — both route to Stripe.
            reason: Refund reason (unused for Stripe, kept for signature compatibility).

        Returns:
            Dict with 'refund_id', 'amount', 'currency', 'status' on success, None on error.
        """
        if self._stripe_provider:
            return await self._stripe_provider.refund_payment(payment_intent_id, amount)

        logger.warning(
            f"PaymentService.refund_payment: Stripe provider not available for order "
            f"'{payment_intent_id}'."
        )
        return None

    async def get_customer_portal_url(
        self,
        customer_id: str,
        return_url: str = "https://openmates.org/settings/support",
    ) -> Optional[str]:
        """
        Get a Stripe billing portal URL.
        """
        if self._stripe_provider and hasattr(self._stripe_provider, "get_customer_portal_url"):
            return await self._stripe_provider.get_customer_portal_url(customer_id, return_url)
        return None

    async def close(self) -> None:
        """Clean up provider connections."""
        if self._stripe_provider:
            await self._stripe_provider.close()
        if self._revolut_business:
            await self._revolut_business.close()
