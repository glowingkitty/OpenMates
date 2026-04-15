"""
Revolut Business Service — SEPA Bank Transfer Provider

Handles incoming SEPA bank transfers via the Revolut Business API.
Unlike Stripe/Polar which process card payments, this provider monitors
the company's Revolut Business account for incoming transfers and matches
them to pending orders by structured reference.

Webhook events:
  - TransactionCreated: incoming transfer detected (may be in "pending" state)
  - TransactionStateChanged: transfer state updated (pending → completed)

Webhook verification:
  Headers: Revolut-Request-Timestamp, Revolut-Signature
  Algorithm: HMAC-SHA256 over "v1.{timestamp}.{raw_payload}"
  Signature format: "v1={hex_digest}" (may contain multiple comma-separated signatures)

Revolut Business API docs: https://developer.revolut.com/docs/business/
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Revolut Business API base URLs
REVOLUT_API_BASE_PRODUCTION = "https://b2b.revolut.com/api/1.0"
REVOLUT_API_BASE_SANDBOX = "https://sandbox-b2b.revolut.com/api/1.0"

# Maximum allowed age for webhook timestamps (5 minutes) to prevent replay attacks
WEBHOOK_TIMESTAMP_TOLERANCE_MS = 5 * 60 * 1000

# Amount tolerance for matching incoming transfers (in cents).
# SEPA transfers may lose small amounts to intermediary bank fees.
AMOUNT_TOLERANCE_CENTS = 50  # ±€0.50

# Bank name displayed to users in the bank transfer UI.
# Revolut Business EUR accounts are held by Revolut Bank UAB (Lithuania).
BANK_NAME = "Revolut Bank UAB"


class RevolutBusinessService:
    """
    Revolut Business API integration for receiving SEPA bank transfers.

    This service does NOT create outgoing payments — it only:
    1. Provides company bank details (IBAN/BIC) for display
    2. Verifies incoming webhook signatures
    3. Parses incoming transfer events for order matching
    """

    def __init__(self, secrets_manager: SecretsManager) -> None:
        self.secrets_manager = secrets_manager
        self._is_production: bool = False
        self._webhook_secret: Optional[str] = None
        self._api_base: str = REVOLUT_API_BASE_SANDBOX
        self.provider_name: str = "bank_transfer"

        # Static bank details loaded from Vault (avoids API call on every order)
        self._iban: Optional[str] = None
        self._bic: Optional[str] = None
        self._account_holder_name: Optional[str] = None

    async def initialize(self, is_production: bool) -> None:
        """
        Load credentials and bank details from Vault.

        Vault path: kv/data/providers/revolut_business
        Required keys (per environment):
          - {env}_webhook_secret
          - {env}_iban
          - {env}_bic
          - {env}_account_holder_name  (legal account holder name shown to bank transfer senders)

        Production and sandbox use separate IBAN/BIC because the sandbox account
        has a different (test) IBAN. Keeping them strictly separated prevents
        accidentally displaying the production IBAN in dev or vice versa.

        Args:
            is_production: True for live environment, False for sandbox
        """
        self._is_production = is_production
        self._api_base = (
            REVOLUT_API_BASE_PRODUCTION if is_production else REVOLUT_API_BASE_SANDBOX
        )
        env = "production" if is_production else "sandbox"
        secret_path = "kv/data/providers/revolut_business"

        self._webhook_secret = await self.secrets_manager.get_secret(
            secret_path=secret_path,
            secret_key=f"{env}_webhook_secret",
        )
        if not self._webhook_secret:
            # Webhook secret is optional — bank transfer display and manual processing
            # work without it. Incoming webhooks from Revolut will be rejected until
            # SECRET__REVOLUT_BUSINESS__{ENV}_WEBHOOK_SECRET is configured.
            logger.warning(
                f"Revolut Business webhook secret for '{env}' is not configured. "
                f"Incoming Revolut webhooks will be rejected. "
                f"Use apply_bank_transfer.py for manual processing in the meantime."
            )

        # IBAN/BIC are environment-specific — sandbox uses a separate test IBAN
        self._iban = await self.secrets_manager.get_secret(
            secret_path=secret_path, secret_key=f"{env}_iban"
        )
        self._bic = await self.secrets_manager.get_secret(
            secret_path=secret_path, secret_key=f"{env}_bic"
        )

        if not self._iban or not self._bic:
            raise ValueError(
                f"Revolut Business IBAN and BIC for '{env}' environment must be configured "
                f"in Vault at {secret_path} (keys: '{env}_iban', '{env}_bic'). "
                f"These are displayed to users when they choose bank transfer."
            )

        # Account holder name — required for SEPA transfers (displayed to user for their banking app)
        self._account_holder_name = await self.secrets_manager.get_secret(
            secret_path=secret_path, secret_key=f"{env}_account_holder_name"
        )
        if not self._account_holder_name:
            logger.warning(
                f"Revolut Business account holder name for '{env}' is not configured "
                f"(key: '{env}_account_holder_name'). It is required for SEPA transfers."
            )

        logger.info(
            f"RevolutBusinessService initialized. Production: {is_production}, "
            f"IBAN: {self._iban[:8]}...{self._iban[-4:]}, "
            f"Account holder: {self._account_holder_name or '(not set)'}"
        )

    def get_bank_details(self) -> Dict[str, str]:
        """
        Return company bank details for display in the payment UI.

        Returns:
            Dict with 'iban', 'bic', 'bank_name', 'account_holder_name'
        """
        return {
            "iban": self._iban or "",
            "bic": self._bic or "",
            "bank_name": BANK_NAME,
            "account_holder_name": self._account_holder_name or "",
        }

    async def verify_webhook(
        self,
        payload: bytes,
        timestamp_header: Optional[str],
        signature_header: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Verify a Revolut Business webhook signature and parse the payload.

        Revolut signs webhooks with HMAC-SHA256:
          payload_to_sign = "v1.{timestamp}.{raw_body}"
          signature = "v1=" + hmac_sha256(signing_secret, payload_to_sign)

        Multiple signatures may be present (comma-separated) if the signing
        secret was recently rotated.

        Args:
            payload: Raw request body bytes
            timestamp_header: Value of Revolut-Request-Timestamp header
            signature_header: Value of Revolut-Signature header

        Returns:
            Parsed event dict if signature valid, None otherwise
        """
        if not self._webhook_secret:
            logger.error(
                "RevolutBusinessService: cannot verify webhook — webhook secret not initialized"
            )
            return None

        if not timestamp_header or not signature_header:
            logger.warning(
                "RevolutBusinessService: missing timestamp or signature header"
            )
            return None

        # Replay attack prevention: reject timestamps older than 5 minutes
        try:
            webhook_ts_ms = int(timestamp_header)
            current_ts_ms = int(time.time() * 1000)
            if abs(current_ts_ms - webhook_ts_ms) > WEBHOOK_TIMESTAMP_TOLERANCE_MS:
                logger.warning(
                    f"RevolutBusinessService: webhook timestamp too old or in future. "
                    f"Webhook: {webhook_ts_ms}, Current: {current_ts_ms}, "
                    f"Diff: {abs(current_ts_ms - webhook_ts_ms)}ms"
                )
                return None
        except (ValueError, TypeError):
            logger.warning(
                f"RevolutBusinessService: invalid timestamp header: {timestamp_header}"
            )
            return None

        # Compute expected signature
        raw_body = payload.decode("utf-8")
        payload_to_sign = f"v1.{timestamp_header}.{raw_body}"
        expected_signature = hmac.new(
            self._webhook_secret.encode("utf-8"),
            payload_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Check if any of the provided signatures match
        # (multiple signatures present during secret rotation)
        signatures = signature_header.split(",")
        signature_valid = False
        for sig in signatures:
            sig = sig.strip()
            if sig.startswith("v1="):
                provided = sig[3:]  # Remove "v1=" prefix
                if hmac.compare_digest(expected_signature, provided):
                    signature_valid = True
                    break

        if not signature_valid:
            logger.warning("RevolutBusinessService: webhook signature verification failed")
            return None

        # Parse the JSON payload
        try:
            event = json.loads(raw_body)
            logger.info(
                f"RevolutBusinessService: verified webhook event: {event.get('event')}"
            )
            return event
        except json.JSONDecodeError as exc:
            logger.error(f"RevolutBusinessService: failed to parse webhook payload: {exc}")
            return None

    @staticmethod
    def parse_incoming_transfer(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract relevant fields from a TransactionCreated or TransactionStateChanged event.

        For TransactionCreated events, returns the transfer details including
        amount, currency, reference, and sender info.

        For TransactionStateChanged events, returns the transaction ID and new state.

        Args:
            event: Parsed webhook event dict

        Returns:
            Normalized transfer dict, or None if not a relevant event
        """
        event_type = event.get("event")
        data = event.get("data", {})

        if event_type == "TransactionCreated":
            # Only process incoming transfers (positive amount in legs)
            legs = data.get("legs", [])
            if not legs:
                logger.debug("TransactionCreated event with no legs — skipping")
                return None

            # Find the leg with positive amount (incoming money)
            incoming_leg = None
            for leg in legs:
                if leg.get("amount", 0) > 0:
                    incoming_leg = leg
                    break

            if not incoming_leg:
                # All legs have negative or zero amounts — this is an outgoing transfer
                logger.debug("TransactionCreated event is outgoing — skipping")
                return None

            # Reference is in data.reference for real SEPA transfers.
            # For sandbox topups (POST /sandbox/topup), Revolut puts the reference
            # in the leg's description field instead. Fall back to leg description
            # when data.reference is empty.
            reference = data.get("reference", "").strip()
            if not reference:
                reference = incoming_leg.get("description", "").strip()

            return {
                "event_type": "TransactionCreated",
                "transaction_id": data.get("id"),
                "state": data.get("state"),
                "reference": reference,
                "amount_cents": int(round(incoming_leg["amount"] * 100)),
                "currency": incoming_leg.get("currency", "").lower(),
                "counterparty": incoming_leg.get("counterparty", {}),
                "created_at": data.get("created_at"),
            }

        elif event_type == "TransactionStateChanged":
            return {
                "event_type": "TransactionStateChanged",
                "transaction_id": data.get("id"),
                "old_state": data.get("old_state"),
                "new_state": data.get("new_state"),
            }

        else:
            logger.debug(
                f"RevolutBusinessService: ignoring event type '{event_type}'"
            )
            return None

    @staticmethod
    def is_amount_within_tolerance(
        expected_cents: int,
        received_cents: int,
        tolerance_cents: int = AMOUNT_TOLERANCE_CENTS,
    ) -> bool:
        """
        Check if a received amount is within the acceptable tolerance of the expected amount.

        SEPA transfers may lose small amounts to intermediary bank fees.
        We accept ±€0.50 (50 cents) by default.

        Args:
            expected_cents: Expected amount in cents
            received_cents: Received amount in cents
            tolerance_cents: Acceptable deviation in cents (default: 50)

        Returns:
            True if within tolerance
        """
        return abs(expected_cents - received_cents) <= tolerance_cents

    async def close(self) -> None:
        """Clean up resources. Currently a no-op (no persistent connections)."""
        pass
