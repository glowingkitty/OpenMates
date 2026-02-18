"""
Payment Service

Top-level orchestrator that holds both the Stripe and Polar providers
simultaneously and selects the correct one based on user region and
any explicit override.

Routing logic:
  - EU/EEA/CH/GB users → Stripe (default)
  - All other countries → Polar (handles global tax compliance as MoR)
  - Either provider can be overridden explicitly via the `provider_override` param

Both providers are always initialized at startup so provider switching
is instant (no re-initialization on override).
"""

import os
import logging
from typing import Optional, Dict, Any, Tuple

from backend.core.api.app.services.payment.revolut_service import RevolutService
from backend.core.api.app.services.payment.stripe_service import StripeService
from backend.core.api.app.services.payment.polar_service import PolarService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Sentinel used to distinguish "no override" from an explicit provider choice
_NO_OVERRIDE = object()


class PaymentService:
    """
    Manages all payment providers and routes transactions to the correct one.

    Provider selection priority (highest to lowest):
      1. Explicit provider_override in the request ("stripe" or "polar")
      2. Region-based detection: EU → Stripe, non-EU → Polar
      3. Legacy PAYMENT_PROVIDER env var for Revolut (backwards compatibility)
    """

    def __init__(self, secrets_manager: SecretsManager) -> None:
        self.secrets_manager = secrets_manager

        # Legacy single-provider mode (Revolut) — kept for backwards compatibility
        self._legacy_provider_name = os.getenv("PAYMENT_PROVIDER", "stripe").lower()

        if self._legacy_provider_name == "revolut":
            # Revolut mode: use only Revolut, no Polar/Stripe dual-provider
            self._revolut_provider: Optional[RevolutService] = RevolutService(secrets_manager)
            self._stripe_provider: Optional[StripeService] = None
            self._polar_provider: Optional[PolarService] = None
            self.provider_name = "revolut"
            # Legacy .provider attribute for code that accesses it directly (e.g. StripeProductSync)
            self.provider = self._revolut_provider
            logger.info("PaymentService: running in legacy Revolut-only mode")
        else:
            # Dual-provider mode: Stripe (EU) + Polar (non-EU)
            self._revolut_provider = None
            self._stripe_provider = StripeService(secrets_manager)
            self._polar_provider = PolarService(secrets_manager)
            # Default provider_name for legacy callers (e.g. /payments/config without override)
            self.provider_name = "stripe"
            # Legacy .provider points to Stripe for backwards compatibility
            # (StripeProductSync accesses payment_service.provider directly)
            self.provider = self._stripe_provider
            logger.info("PaymentService: running in dual-provider mode (Stripe EU + Polar non-EU)")

    async def initialize(self, is_production: bool) -> None:
        """
        Initialize all active providers by loading credentials from Vault.

        Args:
            is_production: True for live environment, False for sandbox
        """
        if self._revolut_provider:
            await self._revolut_provider.initialize(is_production)
            return

        # Initialize both Stripe and Polar for dual-provider mode
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
        # Legacy Revolut mode — no routing, always return Revolut
        if self._revolut_provider:
            return ("revolut", self._revolut_provider)

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
        if self._revolut_provider:
            return await self._revolut_provider.create_order(
                amount, currency, email, credits_amount, customer_id
            )

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
        if self._revolut_provider:
            return await self._revolut_provider.create_support_order(
                amount, currency, email, is_recurring, user_id
            )
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
        if self._revolut_provider:
            return await self._revolut_provider.get_order(order_id)

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
        Verify and parse a webhook event from either provider.

        The payments.py route layer already detects which provider sent the
        webhook (by checking the signature header name) and passes in the
        correct provider. This method is kept for backwards compatibility
        with code that calls it directly on the service.

        For Revolut: passes request_timestamp_header through
        For Stripe/Polar: ignores request_timestamp_header
        """
        if self._revolut_provider:
            is_valid, parsed_payload = await self._revolut_provider.verify_and_parse_webhook(
                payload, sig_header, request_timestamp_header
            )
            return parsed_payload if is_valid else None

        # Delegate to Stripe (default) — Polar webhooks are handled via
        # verify_polar_webhook() called directly from payments.py
        return await self._stripe_provider.verify_and_parse_webhook(payload, sig_header)

    async def verify_polar_webhook(
        self,
        payload: bytes,
        sig_header: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Verify and parse a Polar-specific webhook event.

        Called directly from payments.py when an X-Polar-Signature header
        is detected, bypassing the generic verify_and_parse_webhook routing.

        Args:
            payload: Raw request body bytes
            sig_header: Value of the X-Polar-Signature header

        Returns:
            Parsed event dict if signature valid, None otherwise
        """
        if not self._polar_provider:
            logger.error("PaymentService: received Polar webhook but Polar provider not initialized")
            return None
        return await self._polar_provider.verify_and_parse_webhook(payload, sig_header)

    async def refund_payment(
        self,
        payment_intent_id: str,
        amount: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Refund a payment. Currently only supported for Stripe.
        Polar refunds must be issued via the Polar dashboard (Phase 1).
        """
        if self._revolut_provider and hasattr(self._revolut_provider, "refund_payment"):
            return await self._revolut_provider.refund_payment(payment_intent_id, amount)

        if self._stripe_provider and payment_intent_id.startswith("pi_"):
            return await self._stripe_provider.refund_payment(payment_intent_id, amount)

        logger.warning(
            f"PaymentService.refund_payment: cannot determine provider for order "
            f"'{payment_intent_id}'. Polar refunds require the Polar dashboard."
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

    async def close(self) -> None:
        """Clean up provider connections."""
        if self._revolut_provider:
            await self._revolut_provider.close()
        if self._stripe_provider:
            await self._stripe_provider.close()
        if self._polar_provider:
            await self._polar_provider.close()
