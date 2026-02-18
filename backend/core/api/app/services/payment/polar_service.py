"""
Polar Payment Service

Integrates with Polar.sh as a Merchant of Record (MoR) payment provider
for non-EU users. Polar handles international tax compliance (VAT, GST,
US Sales Tax) automatically, removing the need for manual tax registration.

Polar API:   https://api.polar.sh/v1  (sandbox: https://sandbox-api.polar.sh/v1)
Webhook:     Polar sends checkout.updated events with HMAC-SHA256 signature
             in the X-Polar-Signature header.

Key differences from Stripe:
  - Checkout is redirect/embed-based: backend creates a session, frontend
    embeds Polar's hosted checkout iframe using @polar-sh/checkout.
  - Products must be pre-created in Polar dashboard (or via API at startup
    via PolarProductSync). The checkout links to a pre-created product ID.
  - Polar acts as MoR: they issue the tax invoice to the customer.
    OpenMates generates a "Payment Confirmation" receipt (not an invoice).
  - No saved payment methods / subscriptions in Phase 1 (one-time only).
"""

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Polar API base URLs
POLAR_API_BASE_PRODUCTION = "https://api.polar.sh/v1"
POLAR_API_BASE_SANDBOX = "https://sandbox-api.polar.sh/v1"

# HTTP timeout for Polar API calls (seconds)
POLAR_HTTP_TIMEOUT = 15.0


class PolarService:
    """
    Payment service implementation for Polar.sh.

    Follows the same interface contract as StripeService so PaymentService
    can route to either provider transparently.
    """

    def __init__(self, secrets_manager: SecretsManager) -> None:
        self.secrets_manager = secrets_manager
        self._is_production: bool = False
        self._access_token: Optional[str] = None
        self._webhook_secret: Optional[str] = None
        self._api_base: str = POLAR_API_BASE_SANDBOX
        self.provider_name: str = "polar"
        # Dict of credits_amount -> polar_product_id, populated by PolarProductSync
        self._product_id_map: Dict[int, str] = {}

    async def initialize(self, is_production: bool) -> None:
        """
        Load credentials from Vault and configure the service.

        Args:
            is_production: True for live environment, False for sandbox
        """
        self._is_production = is_production
        self._api_base = POLAR_API_BASE_PRODUCTION if is_production else POLAR_API_BASE_SANDBOX
        env = "production" if is_production else "sandbox"
        secret_path = "kv/data/providers/polar"

        self._access_token = await self.secrets_manager.get_secret(
            secret_path=secret_path,
            secret_key=f"{env}_access_token"
        )
        if not self._access_token:
            raise ValueError(
                f"Polar access token for '{env}' environment is missing. "
                f"Add '{env}_access_token' to Vault at '{secret_path}'."
            )

        self._webhook_secret = await self.secrets_manager.get_secret(
            secret_path=secret_path,
            secret_key=f"{env}_webhook_secret"
        )
        if not self._webhook_secret:
            raise ValueError(
                f"Polar webhook secret for '{env}' environment is missing. "
                f"Add '{env}_webhook_secret' to Vault at '{secret_path}'."
            )

        logger.info(f"PolarService initialized. Production: {self._is_production}, base: {self._api_base}")

    def set_product_id_map(self, product_id_map: Dict[int, str]) -> None:
        """
        Store the credits_amount → Polar product_id mapping built by PolarProductSync.
        Called during application startup after product sync completes.

        Args:
            product_id_map: e.g. {1000: "polar-prod-uuid-...", 10000: "polar-prod-uuid-..."}
        """
        self._product_id_map = product_id_map
        logger.info(f"PolarService: loaded {len(product_id_map)} product ID mappings")

    def _get_headers(self) -> Dict[str, str]:
        """Build standard auth headers for Polar API requests."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_order(
        self,
        amount: int,
        currency: str,
        email: str,
        credits_amount: int,
        customer_id: Optional[str] = None,
        success_url: Optional[str] = None,
        embed_origin: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a Polar checkout session for a one-time credit purchase.

        Polar checkout sessions are redirect/embed based. The response contains:
          - id: Polar checkout session ID (used as our order_id)
          - client_secret: used by @polar-sh/checkout to embed the form
          - url: full URL for redirect-based checkout (fallback)

        Args:
            amount: Amount in smallest currency unit (cents for USD/EUR, yen for JPY)
            currency: ISO currency code (usd, eur, jpy, etc.)
            email: Customer email (pre-fills Polar checkout form)
            credits_amount: Number of credits being purchased (maps to Polar product)
            customer_id: Optional existing Polar customer external_id (our user_id)
            success_url: URL Polar redirects to after successful payment
            embed_origin: Origin of the embedding page for CORS (required for embedded checkout)

        Returns:
            Dict with 'id' (order_id), 'client_secret', 'checkout_url', or None on error
        """
        if not self._access_token:
            logger.error("PolarService: access token not initialized")
            return None

        # Resolve the pre-created product ID for this credit tier
        product_id = self._product_id_map.get(credits_amount)
        if not product_id:
            logger.error(
                f"PolarService: no product ID found for {credits_amount} credits. "
                f"Run PolarProductSync first. Known products: {list(self._product_id_map.keys())}"
            )
            return None

        # Build the checkout creation payload
        # Polar uses USD as the primary currency for non-EU; currency is pre-set on the product.
        payload: Dict[str, Any] = {
            "products": [product_id],
            "customer_email": email,
            "allow_discount_codes": False,
        }

        # Pass our user_id as external_customer_id so Polar links orders to our users
        if customer_id:
            payload["external_customer_id"] = customer_id

        # Success URL with our order_id placeholder (Polar appends ?checkout_id=...)
        if success_url:
            payload["success_url"] = success_url

        # embed_origin is required for embedded (iframe) checkout security
        if embed_origin:
            payload["embed_origin"] = embed_origin

        # Store credits_amount in metadata so webhook handler can retrieve it
        payload["metadata"] = {
            "credits_amount": credits_amount,
            "product_type": "credit_purchase",
        }

        try:
            async with httpx.AsyncClient(timeout=POLAR_HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{self._api_base}/checkouts",
                    headers=self._get_headers(),
                    json=payload,
                )

            if response.status_code not in (200, 201):
                logger.error(
                    f"PolarService: checkout creation failed. "
                    f"Status: {response.status_code}, Body: {response.text[:500]}"
                )
                return None

            data = response.json()
            checkout_id = data.get("id")
            client_secret = data.get("client_secret")
            checkout_url = data.get("url")

            if not checkout_id:
                logger.error(f"PolarService: checkout response missing 'id'. Response: {data}")
                return None

            logger.info(
                f"PolarService: created checkout session {checkout_id} "
                f"for {credits_amount} credits ({currency.upper()})"
            )

            return {
                "id": checkout_id,
                "client_secret": client_secret,
                "checkout_url": checkout_url,
                # Polar doesn't use customer IDs in the same way as Stripe,
                # but we return external_customer_id for reference
                "customer_id": customer_id,
            }

        except httpx.RequestError as exc:
            logger.error(f"PolarService: HTTP error creating checkout: {exc}", exc_info=True)
            return None
        except Exception as exc:
            logger.error(f"PolarService: unexpected error creating checkout: {exc}", exc_info=True)
            return None

    async def create_support_order(
        self,
        amount: int,
        currency: str,
        email: str,
        is_recurring: bool,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Supporter contributions via Polar are not supported in Phase 1.
        Supporter payments remain on Stripe for all users for now.
        """
        logger.warning(
            "PolarService.create_support_order called but not implemented. "
            "Supporter contributions use Stripe for all users."
        )
        return None

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a Polar checkout session by ID.

        Returns a normalized dict compatible with the invoice task's expectations:
          - payments: list with one entry containing payment_method details
          - amount: total amount in smallest unit
          - currency: currency code

        Args:
            order_id: Polar checkout session ID

        Returns:
            Normalized order dict, or None on error
        """
        if not self._access_token:
            logger.error("PolarService: access token not initialized")
            return None

        try:
            async with httpx.AsyncClient(timeout=POLAR_HTTP_TIMEOUT) as client:
                response = await client.get(
                    f"{self._api_base}/checkouts/{order_id}",
                    headers=self._get_headers(),
                )

            if response.status_code == 404:
                logger.warning(f"PolarService: checkout session {order_id} not found")
                return None

            if not response.is_success:
                logger.error(
                    f"PolarService: get_order failed for {order_id}. "
                    f"Status: {response.status_code}, Body: {response.text[:300]}"
                )
                return None

            data = response.json()

            # Normalize to a structure the invoice task can consume.
            # Polar checkout gives us total_amount (after tax) and net_amount (before tax).
            # The customer pays total_amount; we receive net_amount - Polar's fee.
            # For the receipt PDF we show the amount the customer paid (total_amount).
            amount = data.get("total_amount") or data.get("net_amount") or data.get("amount", 0)
            currency = data.get("currency", "usd").lower()

            # Polar doesn't expose raw card details via the checkout API in the same
            # way Stripe does. We show a generic "Polar" payment method on the receipt.
            normalized = {
                "id": order_id,
                "status": data.get("status", ""),
                "amount": amount,
                "currency": currency,
                "metadata": data.get("metadata", {}),
                "payments": [
                    {
                        "state": "SUCCEEDED" if data.get("status") == "succeeded" else data.get("status", "").upper(),
                        "payment_method": {
                            "card_brand": "Polar",
                            "card_last_four": None,
                            "cardholder_name": data.get("customer_name"),
                            "billing_address": self._extract_billing_address(data),
                        },
                    }
                ],
            }

            return normalized

        except httpx.RequestError as exc:
            logger.error(f"PolarService: HTTP error retrieving order {order_id}: {exc}", exc_info=True)
            return None
        except Exception as exc:
            logger.error(f"PolarService: unexpected error retrieving order {order_id}: {exc}", exc_info=True)
            return None

    def _extract_billing_address(self, checkout_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract billing address from Polar checkout data into a normalized format.

        Args:
            checkout_data: Raw Polar checkout response dict

        Returns:
            Normalized billing address dict or None
        """
        addr = checkout_data.get("customer_billing_address")
        if not addr:
            return None
        return {
            "street_line_1": addr.get("line1"),
            "street_line_2": addr.get("line2"),
            "city": addr.get("city"),
            "region": addr.get("state"),
            "country_code": addr.get("country"),
            "postcode": addr.get("postal_code"),
        }

    async def verify_and_parse_webhook(
        self,
        payload: bytes,
        sig_header: str,
        request_timestamp_header: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Verify the Polar webhook HMAC-SHA256 signature and parse the payload.

        Polar sends the webhook signature in the X-Polar-Signature header as a
        hex-encoded HMAC-SHA256 of the raw request body using the webhook secret.

        Args:
            payload: Raw request body bytes
            sig_header: Value of the X-Polar-Signature header
            request_timestamp_header: Not used by Polar (Stripe/Revolut compat param)

        Returns:
            Parsed webhook event dict if signature is valid, None otherwise
        """
        if not self._webhook_secret:
            logger.error("PolarService: webhook secret not initialized, cannot verify signature")
            return None

        if not sig_header:
            logger.warning("PolarService: missing X-Polar-Signature header")
            return None

        try:
            # Compute expected HMAC-SHA256 signature
            expected_sig = hmac.new(
                self._webhook_secret.encode("utf-8"),
                msg=payload,
                digestmod=hashlib.sha256,
            ).hexdigest()

            # Constant-time comparison to prevent timing attacks
            if not hmac.compare_digest(expected_sig, sig_header.strip()):
                logger.warning(
                    "PolarService: webhook signature mismatch — possible tampered request"
                )
                return None

            event = json.loads(payload.decode("utf-8"))
            logger.info(
                f"PolarService: verified webhook event type='{event.get('type', 'unknown')}'"
            )
            return event

        except json.JSONDecodeError as exc:
            logger.error(f"PolarService: failed to parse webhook JSON: {exc}")
            return None
        except Exception as exc:
            logger.error(f"PolarService: error verifying webhook: {exc}", exc_info=True)
            return None

    async def refund_payment(
        self,
        payment_intent_id: str,
        amount: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Polar refunds are initiated via the Polar dashboard or their Refunds API.
        Phase 1: not implemented — returns None to indicate unsupported.

        Note: Polar as MoR handles tax-inclusive refunds automatically when
        issued through their system. Self-service refunds via API require
        the Polar Refunds endpoint (POST /v1/refunds).
        """
        logger.warning(
            f"PolarService.refund_payment called for order {payment_intent_id} but refunds "
            "via API are not implemented in Phase 1. Use the Polar dashboard to issue refunds."
        )
        return None

    async def close(self) -> None:
        """No persistent connections to clean up (httpx clients are context-managed)."""
        pass
