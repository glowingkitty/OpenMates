"""
Bank Transfer Service Tests
============================
Unit tests for the Revolut Business webhook verification, transfer parsing,
and amount tolerance logic. These tests don't require a running server —
they test the service class directly with mock data.

Execution:
  /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_bank_transfer.py
"""

import hashlib
import hmac
import json
import time

import pytest

from backend.core.api.app.services.payment.revolut_business_service import (
    RevolutBusinessService,
)


# =============================================================================
# Fixtures
# =============================================================================

SIGNING_SECRET = "wsk_test_secret_for_unit_tests_only"


def _make_signature(payload_str: str, timestamp: str, secret: str = SIGNING_SECRET) -> str:
    """Generate a valid Revolut webhook signature for testing."""
    payload_to_sign = f"v1.{timestamp}.{payload_str}"
    digest = hmac.new(
        secret.encode("utf-8"),
        payload_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"v1={digest}"


def _make_transaction_created_event(
    amount: float = 100.0,
    currency: str = "EUR",
    reference: str = "OM-ABC12345-bt_abcd1234",
    transaction_id: str = "txn-uuid-123",
    state: str = "completed",
) -> dict:
    """Build a minimal TransactionCreated event payload."""
    return {
        "event": "TransactionCreated",
        "timestamp": "2026-04-13T12:00:00.000Z",
        "data": {
            "id": transaction_id,
            "type": "transfer",
            "state": state,
            "request_id": "req-uuid-456",
            "created_at": "2026-04-13T12:00:00.000Z",
            "updated_at": "2026-04-13T12:00:00.000Z",
            "reference": reference,
            "legs": [
                {
                    "leg_id": "leg-uuid-789",
                    "account_id": "acc-uuid-company",
                    "counterparty": {
                        "id": "cp-uuid-sender",
                        "account_type": "external",
                        "account_id": "cp-acc-sender",
                    },
                    "amount": amount,
                    "currency": currency,
                    "description": "SEPA transfer",
                }
            ],
        },
    }


def _make_state_changed_event(
    transaction_id: str = "txn-uuid-123",
    old_state: str = "pending",
    new_state: str = "completed",
) -> dict:
    """Build a minimal TransactionStateChanged event payload."""
    return {
        "event": "TransactionStateChanged",
        "timestamp": "2026-04-13T12:01:00.000Z",
        "data": {
            "id": transaction_id,
            "request_id": "req-uuid-456",
            "old_state": old_state,
            "new_state": new_state,
        },
    }


# =============================================================================
# Webhook Signature Verification Tests
# =============================================================================

class TestWebhookSignatureVerification:
    """Test Revolut Business webhook HMAC-SHA256 signature verification."""

    @pytest.fixture
    def service(self):
        """Create a RevolutBusinessService with a test signing secret (no Vault needed)."""
        svc = RevolutBusinessService.__new__(RevolutBusinessService)
        svc._webhook_secret = SIGNING_SECRET
        svc._is_production = False
        svc._iban = "DE89370400440532013000"
        svc._bic = "COBADEFFXXX"
        svc._account_holder_name = "OpenMates GmbH"
        svc.provider_name = "bank_transfer"
        return svc

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self, service):
        """A correctly signed webhook should be parsed and returned."""
        event = _make_transaction_created_event()
        payload_str = json.dumps(event)
        timestamp = str(int(time.time() * 1000))
        signature = _make_signature(payload_str, timestamp)

        result = await service.verify_webhook(
            payload_str.encode("utf-8"), timestamp, signature
        )

        assert result is not None
        assert result["event"] == "TransactionCreated"
        assert result["data"]["id"] == "txn-uuid-123"

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self, service):
        """A webhook with a wrong signature should return None."""
        event = _make_transaction_created_event()
        payload_str = json.dumps(event)
        timestamp = str(int(time.time() * 1000))
        bad_signature = "v1=0000000000000000000000000000000000000000000000000000000000000000"

        result = await service.verify_webhook(
            payload_str.encode("utf-8"), timestamp, bad_signature
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_tampered_payload_rejected(self, service):
        """Signature over original payload should fail if payload was modified."""
        event = _make_transaction_created_event()
        payload_str = json.dumps(event)
        timestamp = str(int(time.time() * 1000))
        signature = _make_signature(payload_str, timestamp)

        # Tamper with the payload after signing
        tampered = payload_str.replace("txn-uuid-123", "txn-uuid-TAMPERED")

        result = await service.verify_webhook(
            tampered.encode("utf-8"), timestamp, signature
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_stale_timestamp_rejected(self, service):
        """A webhook with a timestamp older than 5 minutes should be rejected."""
        event = _make_transaction_created_event()
        payload_str = json.dumps(event)
        # Timestamp from 10 minutes ago
        stale_ts = str(int((time.time() - 600) * 1000))
        signature = _make_signature(payload_str, stale_ts)

        result = await service.verify_webhook(
            payload_str.encode("utf-8"), stale_ts, signature
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_signatures_rotation(self, service):
        """During secret rotation, multiple signatures may be present (comma-separated)."""
        event = _make_transaction_created_event()
        payload_str = json.dumps(event)
        timestamp = str(int(time.time() * 1000))

        # Generate valid signature with current secret
        valid_sig = _make_signature(payload_str, timestamp)
        # Generate signature with an old secret
        old_sig = _make_signature(payload_str, timestamp, secret="old_secret_abc")

        # Revolut sends both, comma-separated
        combined = f"{old_sig}, {valid_sig}"

        result = await service.verify_webhook(
            payload_str.encode("utf-8"), timestamp, combined
        )

        assert result is not None
        assert result["event"] == "TransactionCreated"

    @pytest.mark.asyncio
    async def test_missing_headers_rejected(self, service):
        """Missing timestamp or signature headers should return None."""
        event = _make_transaction_created_event()
        payload_str = json.dumps(event)

        result = await service.verify_webhook(payload_str.encode("utf-8"), None, None)
        assert result is None

        result = await service.verify_webhook(
            payload_str.encode("utf-8"), str(int(time.time() * 1000)), None
        )
        assert result is None


# =============================================================================
# Transfer Parsing Tests
# =============================================================================

class TestTransferParsing:
    """Test parsing of Revolut Business webhook events."""

    def test_incoming_transfer_parsed(self):
        """TransactionCreated with positive amount should be parsed as incoming."""
        event = _make_transaction_created_event(amount=100.0, currency="EUR")
        result = RevolutBusinessService.parse_incoming_transfer(event)

        assert result is not None
        assert result["event_type"] == "TransactionCreated"
        assert result["amount_cents"] == 10000
        assert result["currency"] == "eur"
        assert result["reference"] == "OM-ABC12345-bt_abcd1234"
        assert result["transaction_id"] == "txn-uuid-123"

    def test_outgoing_transfer_ignored(self):
        """TransactionCreated with negative amount (outgoing) should return None."""
        event = _make_transaction_created_event(amount=-50.0)
        result = RevolutBusinessService.parse_incoming_transfer(event)

        assert result is None

    def test_state_changed_parsed(self):
        """TransactionStateChanged should be parsed with old and new states."""
        event = _make_state_changed_event(old_state="pending", new_state="completed")
        result = RevolutBusinessService.parse_incoming_transfer(event)

        assert result is not None
        assert result["event_type"] == "TransactionStateChanged"
        assert result["old_state"] == "pending"
        assert result["new_state"] == "completed"

    def test_irrelevant_event_ignored(self):
        """Unknown event types should return None."""
        event = {"event": "PayoutLinkCreated", "data": {"id": "payout-123"}}
        result = RevolutBusinessService.parse_incoming_transfer(event)

        assert result is None

    def test_no_legs_ignored(self):
        """TransactionCreated with empty legs should return None."""
        event = _make_transaction_created_event()
        event["data"]["legs"] = []
        result = RevolutBusinessService.parse_incoming_transfer(event)

        assert result is None

    def test_fractional_amount_rounded(self):
        """Amounts like 20.50 should be correctly converted to 2050 cents."""
        event = _make_transaction_created_event(amount=20.50)
        result = RevolutBusinessService.parse_incoming_transfer(event)

        assert result is not None
        assert result["amount_cents"] == 2050

    def test_small_amount_parsed(self):
        """Small amounts like 2.00 (€2 tier) should work."""
        event = _make_transaction_created_event(amount=2.0)
        result = RevolutBusinessService.parse_incoming_transfer(event)

        assert result is not None
        assert result["amount_cents"] == 200


# =============================================================================
# Amount Tolerance Tests
# =============================================================================

class TestAmountTolerance:
    """Test the ±€0.50 amount tolerance for SEPA fee absorption."""

    def test_exact_match(self):
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 10000) is True

    def test_within_positive_tolerance(self):
        """Received slightly more than expected (rare but possible)."""
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 10050) is True

    def test_within_negative_tolerance(self):
        """Received slightly less due to intermediary bank fees."""
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 9950) is True

    def test_at_tolerance_boundary(self):
        """Exactly at the boundary should pass."""
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 9950) is True
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 10050) is True

    def test_outside_tolerance(self):
        """Amounts outside ±€0.50 should fail."""
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 9900) is False
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 10100) is False

    def test_small_tier_tolerance(self):
        """The €2 tier (200 cents) should still use 50 cents tolerance."""
        assert RevolutBusinessService.is_amount_within_tolerance(200, 150) is True
        assert RevolutBusinessService.is_amount_within_tolerance(200, 100) is False

    def test_zero_amount_rejected(self):
        """Zero received should fail tolerance for any positive expected amount."""
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 0) is False

    def test_custom_tolerance(self):
        """Custom tolerance parameter should be respected."""
        # 100 cents tolerance (€1.00)
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 9900, tolerance_cents=100) is True
        assert RevolutBusinessService.is_amount_within_tolerance(10000, 9800, tolerance_cents=100) is False


# =============================================================================
# Bank Details Tests
# =============================================================================

class TestBankDetails:
    """Test bank details accessor."""

    def test_returns_configured_details(self):
        svc = RevolutBusinessService.__new__(RevolutBusinessService)
        svc._iban = "DE89370400440532013000"
        svc._bic = "COBADEFFXXX"
        svc._account_holder_name = "OpenMates GmbH"

        details = svc.get_bank_details()

        assert details["iban"] == "DE89370400440532013000"
        assert details["bic"] == "COBADEFFXXX"
        assert details["bank_name"] == "Revolut Bank UAB"
        assert details["account_holder_name"] == "OpenMates GmbH"

    def test_defaults_when_unconfigured(self):
        svc = RevolutBusinessService.__new__(RevolutBusinessService)
        svc._iban = None
        svc._bic = None
        svc._account_holder_name = None

        details = svc.get_bank_details()

        assert details["iban"] == ""
        assert details["bic"] == ""
        assert details["bank_name"] == "Revolut Bank UAB"
        assert details["account_holder_name"] == ""
