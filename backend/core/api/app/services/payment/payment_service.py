"""
Payment Service

Top-level orchestrator that holds all payment providers simultaneously
and selects the correct one based on user region and any explicit override.

Routing logic:
  - All card payments → Stripe (Polar deactivated — account rejected by Polar on 2026-04-23)
  - SEPA bank transfers → Revolut Business (separate flow, not region-based)

All providers are always initialized at startup so provider switching
is instant (no re-initialization on override).
"""

import logging
from typing import Optional, Dict, Any, Tuple

from backend.core.api.app.services.payment.stripe_service import StripeService
from backend.core.api.app.services.payment.polar_service import PolarService
from backend.core.api.app.services.payment.revolut_business_service import RevolutBusinessService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


class PaymentService:
    """
    Manages all payment providers and routes transactions to the correct one.

    Provider selection priority (highest to lowest):
      1. Explicit provider_override in the request ("stripe" or "polar")
      2. Region-based detection: EU → Stripe, non-EU → Polar
    """

    def __init__(self, secrets_manager: SecretsManager) -> None:
        self.secrets_manager = secrets_manager

        self._stripe_provider: Optional[StripeService] = StripeService(secrets_manager)
        # POLAR DISABLED 2026-04-23 — account rejected by Polar (risk metrics out of bounds).
        # To re-enable: uncomment the line below and remove the None assignment.
        # self._polar_provider: Optional[PolarService] = PolarService(secrets_manager)
        self._polar_provider: Optional[PolarService] = None
        self._revolut_business: Optional[RevolutBusinessService] = RevolutBusinessService(secrets_manager)
        # Default provider_name for legacy callers (e.g. /payments/config without override)
        self.provider_name = "stripe"
        # Legacy .provider points to Stripe for backwards compatibility
        # (StripeProductSync accesses payment_service.provider directly)
        self.provider = self._stripe_provider
        logger.info("PaymentService: running in Stripe-only mode (Polar deactivated) + Revolut Business SEPA")

    async def initialize(self, is_production: bool) -> None:
        """
        Initialize all active providers by loading credentials from Vault.

        Args:
            is_production: True for live environment, False for sandbox
        """
        if self._stripe_provider:
            await self._stripe_provider.initialize(is_production)
            logger.info("PaymentService: Stripe provider initialized")

        if self._polar_provider:
            try:
                await self._polar_provider.initialize(is_production)
                logger.info("PaymentService: Polar provider initialized")
            except ValueError as exc:
                # Polar credentials missing — log warning but don't fail startup.
                # Polar simply won't be available until credentials are added to Vault.
                logger.warning(
                    f"PaymentService: Polar provider could not be initialized "
                    f"(credentials missing from Vault): {exc}. "
                    f"Non-EU users will fall back to Stripe until Polar is configured."
                )
                self._polar_provider = None

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
            provider_override: Optional explicit provider name ("stripe" or "polar")

        Returns:
            Tuple of (provider_name, provider_instance)
        """
        # Explicit override takes highest priority
        if provider_override:
            normalized = provider_override.lower().strip()
            if normalized == "polar":
                if self._polar_provider:
                    return ("polar", self._polar_provider)
                else:
                    logger.warning(
                        "PaymentService: Polar requested via override but not initialized. "
                        "Falling back to Stripe."
                    )
                    return ("stripe", self._stripe_provider)
            elif normalized == "stripe":
                return ("stripe", self._stripe_provider)
            else:
                logger.warning(
                    f"PaymentService: unknown provider_override '{provider_override}', "
                    f"falling back to region-based selection"
                )

        # Region-based selection
        if is_eu or not self._polar_provider:
            # EU users → Stripe
            # Also use Stripe if Polar isn't available (credentials not yet configured)
            return ("stripe", self._stripe_provider)
        else:
            # Non-EU users → Polar
            return ("polar", self._polar_provider)

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
    ) -> Optional[Dict[str, Any]]:
        """
        Create a payment order through the appropriate provider.

        Args:
            amount: Amount in smallest currency unit (cents for USD/EUR)
            currency: ISO currency code
            email: Customer email
            credits_amount: Number of credits being purchased
            customer_id: Optional existing customer ID (provider-specific)
            provider_override: Optional explicit provider ("stripe" or "polar")
            is_eu: Whether the user is in the EU/EEA region
            success_url: URL for Polar to redirect after successful checkout
            embed_origin: Embedding page origin for Polar iframe security

        Returns:
            Provider-specific order dict, or None on error
        """
        provider_name, provider = self.get_provider(is_eu, provider_override)

        if provider_name == "polar":
            return await provider.create_order(
                amount=amount,
                currency=currency,
                email=email,
                credits_amount=credits_amount,
                customer_id=customer_id,
                success_url=success_url,
                embed_origin=embed_origin,
            )
        else:
            # Stripe
            return await provider.create_order(amount, currency, email, credits_amount, customer_id)

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
        Polar does not support supporter contributions in Phase 1.
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

        For Polar orders the order_id is a Polar checkout session ID (UUID).
        For Stripe orders it's a PaymentIntent ID (pi_...).
        The correct provider is determined by the ID prefix.

        Args:
            order_id: Provider-specific order/checkout ID

        Returns:
            Normalized order dict, or None on error
        """
        # Route by ID format: Polar uses UUID-style IDs, Stripe uses "pi_" prefix
        if self._polar_provider and not order_id.startswith("pi_"):
            # Try Polar first for non-Stripe IDs
            result = await self._polar_provider.get_order(order_id)
            if result:
                return result
            # Fall through to Stripe if Polar 404s (shouldn't happen in normal flow)

        return await self._stripe_provider.get_order(order_id)

    async def verify_and_parse_webhook(
        self,
        payload: bytes,
        sig_header: str,
        request_timestamp_header: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Verify and parse a Stripe webhook event.

        The payments.py route layer already detects which provider sent the
        webhook (by checking the signature header name) and passes in the
        correct provider. This method is kept for backwards compatibility
        with code that calls it directly on the service.

        Polar webhooks are handled via verify_polar_webhook() called directly
        from payments.py.
        """
        return await self._stripe_provider.verify_and_parse_webhook(payload, sig_header)

    async def verify_polar_webhook(
        self,
        payload: bytes,
        headers: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Verify and parse a Polar webhook using the Standard Webhooks spec.

        Called directly from payments.py when a 'webhook-signature' header
        is detected (Polar uses Standard Webhooks, not X-Polar-Signature).

        Args:
            payload: Raw request body bytes
            headers: All request headers dict (keys may be mixed-case)

        Returns:
            Parsed event dict if signature valid, None otherwise
        """
        if not self._polar_provider:
            logger.error("PaymentService: received Polar webhook but Polar provider not initialized")
            return None
        return await self._polar_provider.verify_and_parse_webhook(payload, headers)

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
        Refund a payment via the appropriate provider.

        Provider routing order:
        1. Explicit provider override (if given)
        2. Stripe (if order ID starts with 'pi_')
        3. Polar (if initialized and order ID doesn't match Stripe)

        Args:
            payment_intent_id: Provider-specific order/payment ID.
                               For Stripe: PaymentIntent ID ('pi_...').
                               For Polar: the Polar Order UUID (from invoices.provider_order_id).
            amount: Refund amount in smallest currency unit (cents). If None, full refund (Stripe only).
            provider: Explicit provider name ('stripe' or 'polar') to bypass auto-detection.
            reason: Refund reason (used by Polar). Default: 'customer_request'.

        Returns:
            Dict with 'refund_id', 'amount', 'currency', 'status' on success, None on error.
        """
        # Explicit provider override
        if provider == "polar" and self._polar_provider:
            return await self._polar_provider.refund_payment(payment_intent_id, amount, reason=reason)
        if provider == "stripe" and self._stripe_provider:
            return await self._stripe_provider.refund_payment(payment_intent_id, amount)

        # Auto-detection fallback (for backwards compatibility)
        if self._stripe_provider and payment_intent_id.startswith("pi_"):
            return await self._stripe_provider.refund_payment(payment_intent_id, amount)

        # Polar fallback: non-pi_ order ID with Polar initialized
        if self._polar_provider:
            return await self._polar_provider.refund_payment(payment_intent_id, amount, reason=reason)

        logger.warning(
            f"PaymentService.refund_payment: cannot determine provider for order "
            f"'{payment_intent_id}' (provider={provider}). No matching provider available."
        )
        return None

    async def get_customer_portal_url(
        self,
        customer_id: str,
        return_url: str = "https://openmates.org/settings/support",
    ) -> Optional[str]:
        """
        Get a Stripe billing portal URL. Only supported for Stripe.
        """
        if self._stripe_provider and hasattr(self._stripe_provider, "get_customer_portal_url"):
            return await self._stripe_provider.get_customer_portal_url(customer_id, return_url)
        return None

    async def get_polar_order_uuid_by_checkout_id(
        self, checkout_id: str
    ) -> Optional[str]:
        """
        Look up the Polar Order UUID for a checkout session ID.

        Delegates to PolarService.get_order_uuid_by_checkout_id().
        Used as a fallback when the order.paid webhook arrived before the
        Directus invoice was created, leaving provider_order_id unset.

        Args:
            checkout_id: Polar checkout session ID (our invoice's order_id).

        Returns:
            Polar Order UUID string, or None if Polar is not configured
            or the lookup fails.
        """
        if not self._polar_provider:
            logger.warning(
                "PaymentService: cannot look up Polar order UUID — "
                "Polar provider not initialized"
            )
            return None
        return await self._polar_provider.get_order_uuid_by_checkout_id(checkout_id)

    async def close(self) -> None:
        """Clean up provider connections."""
        if self._stripe_provider:
            await self._stripe_provider.close()
        if self._polar_provider:
            await self._polar_provider.close()
        if self._revolut_business:
            await self._revolut_business.close()
