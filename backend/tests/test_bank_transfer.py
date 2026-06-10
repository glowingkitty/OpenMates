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

from backend.core.api.app.routes import payments
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
        svc._account_holder_address_line1 = "Sorauer Str. 19"
        svc._account_holder_address_line2 = ""
        svc._account_holder_postal_code = "10997"
        svc._account_holder_city = "Berlin"
        svc._account_holder_country = "Germany"
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
        svc._account_holder_address_line1 = "Sorauer Str. 19"
        svc._account_holder_address_line2 = ""
        svc._account_holder_postal_code = "10997"
        svc._account_holder_city = "Berlin"
        svc._account_holder_country = "Germany"

        details = svc.get_bank_details()

        assert details["iban"] == "DE89370400440532013000"
        assert details["bic"] == "COBADEFFXXX"
        assert details["bank_name"] == "Revolut Bank UAB"
        assert details["account_holder_name"] == "OpenMates GmbH"
        assert details["account_holder_address_line1"] == "Sorauer Str. 19"
        assert details["account_holder_postal_code"] == "10997"
        assert details["account_holder_city"] == "Berlin"
        assert details["account_holder_country"] == "Germany"

    def test_defaults_when_unconfigured(self):
        svc = RevolutBusinessService.__new__(RevolutBusinessService)
        svc._iban = None
        svc._bic = None
        svc._account_holder_name = None
        svc._account_holder_address_line1 = None
        svc._account_holder_address_line2 = None
        svc._account_holder_postal_code = None
        svc._account_holder_city = None
        svc._account_holder_country = None

        details = svc.get_bank_details()

        assert details["iban"] == ""
        assert details["bic"] == ""
        assert details["bank_name"] == "Revolut Bank UAB"
        assert details["account_holder_name"] == ""
        assert details["account_holder_address_line1"] == ""
        assert details["account_holder_postal_code"] == ""
        assert details["account_holder_city"] == ""
        assert details["account_holder_country"] == ""


class TestGiftCardBankTransferWebhook:
    """Regression coverage for purchased gift cards paid by SEPA transfer."""

    @pytest.mark.asyncio
    async def test_confirmed_gift_card_transfer_creates_card_and_email_not_credits(self, monkeypatch):
        reference = "OM-TEST-btgift01"
        order_id = "bt_gift01"
        user_id = "user-123"

        class FakePaymentService:
            revolut_business = object()

        class FakeCache:
            def __init__(self):
                self.user = {"vault_key_id": "vault-key", "credits": 500}
                self.status_updates = []
                self.events = []
                self.stats = []

            async def get_bank_transfer_by_reference(self, requested_reference):
                assert requested_reference == reference
                return {
                    "order_id": order_id,
                    "status": "pending",
                    "amount_expected_cents": 2000,
                    "user_id": user_id,
                    "credits_amount": 21000,
                    "order_type": "gift_card_purchase",
                    "email_encryption_key": "email-key",
                }

            async def get_user_by_id(self, requested_user_id):
                assert requested_user_id == user_id
                return dict(self.user)

            async def set_user(self, data, user_id):
                self.user = dict(data)

            async def update_bank_transfer_status(self, **kwargs):
                self.status_updates.append(kwargs)

            async def increment_stat(self, name):
                self.stats.append(("increment_stat", name))

            async def increment_json_stat(self, name, key):
                self.stats.append(("increment_json_stat", name, key))

            async def update_liability(self, amount):
                self.stats.append(("update_liability", amount))

            async def publish_event(self, channel, event_data):
                self.events.append((channel, event_data))

        class FakeDirectus:
            def __init__(self):
                self.created_gift_cards = []
                self.updated_items = []
                self.updated_users = []

            async def get_items(self, collection, params=None):
                if collection == "pending_bank_transfers":
                    return [{"id": "pending-row-id"}]
                return []

            async def update_item(self, collection, item_id, data):
                self.updated_items.append((collection, item_id, data))

            async def create_gift_card(self, **kwargs):
                self.created_gift_cards.append(kwargs)
                return {"id": "gift-card-id", **kwargs}

            async def update_user(self, user_id, payload):
                self.updated_users.append((user_id, payload))
                return True

        class FakeSecrets:
            async def get_secret(self, secret_path, secret_key):
                return f"secret-{secret_key}"

        class FakeTier:
            def __init__(self):
                self.spending_updates = []
                self.successful_payments = []

            async def update_monthly_spending(self, **kwargs):
                self.spending_updates.append(kwargs)

            async def handle_successful_payment(self, **kwargs):
                self.successful_payments.append(kwargs)

        sent_tasks = []
        broadcasts = []

        def fake_send_task(**kwargs):
            sent_tasks.append(kwargs)

        async def fake_broadcast_to_user_specific_event(**kwargs):
            broadcasts.append(kwargs)

        monkeypatch.setattr(payments, "generate_gift_card_code", lambda: "GIFT-BANK-TEST")
        monkeypatch.setattr(payments.app, "send_task", fake_send_task)
        monkeypatch.setattr(payments.manager, "broadcast_to_user_specific_event", fake_broadcast_to_user_specific_event)

        cache = FakeCache()
        directus = FakeDirectus()

        result = await payments._handle_revolut_business_webhook(
            event_payload=_make_transaction_created_event(
                amount=20.0,
                currency="EUR",
                reference=reference,
                transaction_id="txn-gift-card",
            ),
            event_type="TransactionCreated",
            payment_service=FakePaymentService(),
            cache_service=cache,
            directus_service=directus,
            encryption_service=object(),
            secrets_manager=FakeSecrets(),
            tier_service=FakeTier(),
        )

        assert result == {"status": "gift_card_bank_transfer_completed"}
        assert directus.created_gift_cards == [{
            "code": "GIFT-BANK-TEST",
            "credits_value": 21000,
            "purchaser_user_id_hash": hashlib.sha256(user_id.encode()).hexdigest(),
        }]
        assert directus.updated_users == []
        assert cache.user["credits"] == 500
        assert cache.status_updates[0]["status"] == "completed"
        assert any(event[1]["event_for_client"] == "gift_card_created" for event in cache.events)
        assert any(event["event_name"] == "gift_card_created" for event in broadcasts)
        assert sent_tasks[0]["name"] == "app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email"
        assert sent_tasks[0]["kwargs"]["is_gift_card"] is True
        assert sent_tasks[0]["kwargs"]["gift_card_code"] == "GIFT-BANK-TEST"
