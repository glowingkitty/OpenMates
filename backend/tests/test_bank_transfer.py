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
import re
import sys
import time
import types
from datetime import datetime
from pathlib import Path

import pytest

if "stripe" not in sys.modules:
    stripe_module = types.ModuleType("stripe")

    class FakeStripeError(Exception):
        user_message = "stripe unavailable in tests"

    class FakeStripeResource:
        @staticmethod
        def retrieve(*_args, **_kwargs):
            raise FakeStripeError()

        @staticmethod
        def create(*_args, **_kwargs):
            raise FakeStripeError()

    stripe_module.Customer = FakeStripeResource
    stripe_module.checkout = types.SimpleNamespace(Session=FakeStripeResource)
    stripe_module.error = types.SimpleNamespace(StripeError=FakeStripeError)
    sys.modules["stripe"] = stripe_module

if "regex" not in sys.modules:
    regex_module = types.ModuleType("regex")
    regex_module.compile = re.compile
    regex_module.match = re.match
    regex_module.search = re.search
    regex_module.sub = re.sub
    regex_module.IGNORECASE = re.IGNORECASE
    sys.modules["regex"] = regex_module

if "backend.core.api.app.tasks.celery_config" not in sys.modules:
    tasks_module = types.ModuleType("backend.core.api.app.tasks")
    celery_config_module = types.ModuleType("backend.core.api.app.tasks.celery_config")

    class FakeCeleryApp:
        def send_task(self, **_kwargs):
            return None

        def task(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

    celery_config_module.app = FakeCeleryApp()
    tasks_module.__path__ = [str(Path(__file__).resolve().parents[1] / "core/api/app/tasks")]
    sys.modules["backend.core.api.app.tasks"] = tasks_module
    sys.modules["backend.core.api.app.tasks.celery_config"] = celery_config_module

if "backend.core.api.app.services.limiter" not in sys.modules:
    limiter_module = types.ModuleType("backend.core.api.app.services.limiter")
    limiter_module.limiter = types.SimpleNamespace(limit=lambda *_args, **_kwargs: (lambda func: func))
    sys.modules["backend.core.api.app.services.limiter"] = limiter_module

if "redis" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedisClient:
        pass

    redis_asyncio_module.Redis = FakeRedisClient
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

if "aiohttp" not in sys.modules:
    aiohttp_module = types.ModuleType("aiohttp")

    class FakeClientSession:
        pass

    aiohttp_module.ClientSession = FakeClientSession
    sys.modules["aiohttp"] = aiohttp_module

if "boto3" not in sys.modules:
    boto3_module = types.ModuleType("boto3")
    boto3_module.client = lambda *_args, **_kwargs: None
    sys.modules["boto3"] = boto3_module

if "botocore" not in sys.modules:
    botocore_module = types.ModuleType("botocore")
    botocore_config_module = types.ModuleType("botocore.config")
    botocore_config_module.Config = lambda *_args, **_kwargs: None
    botocore_exceptions_module = types.ModuleType("botocore.exceptions")
    botocore_exceptions_module.ClientError = Exception
    botocore_exceptions_module.ReadTimeoutError = Exception
    botocore_exceptions_module.ConnectTimeoutError = Exception
    botocore_exceptions_module.EndpointConnectionError = Exception
    sys.modules["botocore"] = botocore_module
    sys.modules["botocore.config"] = botocore_config_module
    sys.modules["botocore.exceptions"] = botocore_exceptions_module

if "backend.core.api.app.routes.websockets" not in sys.modules:
    websockets_module = types.ModuleType("backend.core.api.app.routes.websockets")

    async def fake_broadcast_to_user_specific_event(**_kwargs):
        return None

    websockets_module.manager = types.SimpleNamespace(
        broadcast_to_user_specific_event=fake_broadcast_to_user_specific_event,
    )
    sys.modules["backend.core.api.app.routes.websockets"] = websockets_module

from backend.core.api.app.routes import payments
from backend.core.api.app.services.payment import revolut_business_service as revolut_business_service_module
from backend.core.api.app.services.payment.revolut_business_service import (
    RevolutBusinessService,
    RevolutBusinessTransactionConfirmationError,
)
from backend.core.api.app.utils.bank_transfer_references import generate_bank_transfer_reference


# =============================================================================
# Fixtures
# =============================================================================

SIGNING_SECRET = "wsk_test_secret_for_unit_tests_only"


def test_generated_bank_transfer_reference_segments_avoid_zero_and_o():
    reference = generate_bank_transfer_reference("OM", "93D2OGN", middle_length=7)

    assert reference == reference.upper()
    assert reference.startswith("OM-")
    generated_segments = reference.removeprefix("OM-")
    assert "0" not in generated_segments
    assert "O" not in generated_segments


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


class _FakeConfirmedRevolutBusiness:
    def __init__(self, event_payload: dict):
        self.event_payload = event_payload

    async def fetch_confirmed_incoming_transfer(self, transaction_id: str) -> dict:
        transfer = RevolutBusinessService.parse_incoming_transfer(self.event_payload)
        assert transfer is not None
        assert transfer["transaction_id"] == transaction_id
        return transfer


class _FakeFailingRevolutBusiness:
    def __init__(self, error: RevolutBusinessTransactionConfirmationError):
        self.error = error

    async def fetch_confirmed_incoming_transfer(self, _transaction_id: str) -> dict:
        raise self.error


def _fake_confirmed_payment_service(event_payload: dict):
    return types.SimpleNamespace(revolut_business=_FakeConfirmedRevolutBusiness(event_payload))


def _fake_failing_payment_service(error: RevolutBusinessTransactionConfirmationError):
    return types.SimpleNamespace(revolut_business=_FakeFailingRevolutBusiness(error))


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


class TestRevolutBusinessTransactionConfirmation:
    """Provider API confirmation coverage for company Revolut credentials."""

    class FakeSecrets:
        def __init__(self, *, store_ok: bool = True):
            self.store_ok = store_ok
            self.data = {
                "sandbox_refresh_token": "vault-fresh-refresh",
                "sandbox_client_id": "client-id",
                "sandbox_account_id": "acc-uuid-company",
                "sandbox_webhook_secret": "webhook-secret",
            }
            self.store_calls = []

        async def get_secret(self, secret_path, secret_key, log_missing=True):
            if secret_key == "sandbox_refresh_token":
                return "stale-cached-refresh"
            return self.data.get(secret_key)

        async def get_secrets_from_path(self, secret_path):
            return dict(self.data)

        async def store_secrets_at_path(self, secret_path, data):
            self.store_calls.append((secret_path, dict(data)))
            if not self.store_ok:
                return False
            self.data = dict(data)
            return True

    @staticmethod
    def _service(secrets):
        svc = RevolutBusinessService(secrets)
        svc._is_production = False
        svc._api_base = revolut_business_service_module.REVOLUT_API_BASE_SANDBOX
        svc._account_id = "acc-uuid-company"
        svc._client_id = "client-id"
        svc._refresh_token = "stale-memory-refresh"
        svc._private_key_pem = "private-key-pem"
        svc._client_assertion = None
        return svc

    @staticmethod
    def _patch_successful_provider(monkeypatch, exchanges):
        async def fake_exchange(refresh_token, scope_context):
            exchanges.append({"refresh_token": refresh_token, "scope_context": scope_context})
            return {
                "access_token": "access-token",
                "rotated_refresh_token_bundle": {
                    "provider": "revolut_business",
                    "refresh_token": "rotated-refresh-token",
                },
            }

        class FakeRevolutClient:
            def __init__(self, *, access_token, base_url):
                assert access_token == "access-token"
                assert base_url == revolut_business_service_module.REVOLUT_API_BASE_SANDBOX

            async def get_transaction(self, transaction_id):
                return types.SimpleNamespace(
                    id=transaction_id,
                    state="completed",
                    amount=2.0,
                    currency="EUR",
                    description="OM-TEST123-bt_abc123",
                    completed_at="2026-07-28T12:00:00Z",
                    created_at="2026-07-28T11:59:00Z",
                    account_id="acc-uuid-company",
                )

        monkeypatch.setattr(
            revolut_business_service_module,
            "exchange_revolut_business_refresh_token",
            fake_exchange,
        )
        monkeypatch.setattr(revolut_business_service_module, "RevolutBusinessClient", FakeRevolutClient)

    @pytest.mark.asyncio
    async def test_transaction_confirmation_refreshes_from_vault_and_persists_rotated_token(self, monkeypatch):
        secrets = self.FakeSecrets()
        svc = self._service(secrets)
        exchanges = []
        self._patch_successful_provider(monkeypatch, exchanges)

        transfer = await svc.fetch_confirmed_incoming_transfer("txn-uuid-123")

        assert transfer["transaction_id"] == "txn-uuid-123"
        assert transfer["amount_cents"] == 200
        assert exchanges[0]["refresh_token"] == "vault-fresh-refresh"
        assert exchanges[0]["scope_context"]["refresh_token_envelope"]["redirect_uri"] == (
            "https://api.dev.openmates.org/v1/payments/webhook"
        )
        assert svc._refresh_token == "rotated-refresh-token"
        assert secrets.store_calls == [
            (
                "kv/data/providers/revolut_business",
                {
                    "sandbox_account_id": "acc-uuid-company",
                    "sandbox_client_id": "client-id",
                    "sandbox_refresh_token": "rotated-refresh-token",
                    "sandbox_webhook_secret": "webhook-secret",
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_rotated_token_persistence_failure_does_not_block_confirmed_transfer(self, monkeypatch, caplog):
        secrets = self.FakeSecrets(store_ok=False)
        svc = self._service(secrets)
        exchanges = []
        self._patch_successful_provider(monkeypatch, exchanges)

        transfer = await svc.fetch_confirmed_incoming_transfer("txn-uuid-123")

        assert transfer["state"] == "completed"
        assert svc._refresh_token == "rotated-refresh-token"
        assert "rotated refresh token persistence failed" in caplog.text
        assert "rotated-refresh-token" not in caplog.text


class TestPersonalBankTransferWebhook:
    """Automation coverage for personal SEPA credit purchases."""

    class FakeEncryption:
        async def encrypt_with_user_key(self, plaintext, key_id):
            return f"encrypted:{plaintext}:{key_id}", "v1"

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

    class FakeReferralService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def reward_after_purchase(self, **_kwargs):
            return types.SimpleNamespace(
                awarded=False,
                referred_new_total=None,
                referrer_user_id=None,
                referrer_new_total=None,
                referred_bonus=0,
                referrer_bonus=0,
            )

    class FakeCache:
        def __init__(self, order):
            self.order = dict(order)
            self.user = {"vault_key_id": "vault-key", "credits": 500}
            self.status_updates = []
            self.set_user_calls = []
            self.stats = []
            self.events = []

        async def get_bank_transfer_by_reference(self, requested_reference):
            assert requested_reference == self.order["reference"]
            return dict(self.order)

        async def update_bank_transfer_status(self, **kwargs):
            self.status_updates.append(kwargs)
            self.order.update(kwargs.get("extra_fields") or {})
            self.order["status"] = kwargs.get("status")
            return True

        async def get_user_by_id(self, requested_user_id):
            assert requested_user_id == self.order["user_id"]
            return dict(self.user)

        async def set_user(self, data, user_id):
            assert user_id == self.order["user_id"]
            self.set_user_calls.append(dict(data))
            self.user = dict(data)
            return True

        async def increment_stat(self, name, value=None):
            self.stats.append(("increment_stat", name, value))

        async def increment_json_stat(self, name, key):
            self.stats.append(("increment_json_stat", name, key))

        async def update_liability(self, amount):
            self.stats.append(("update_liability", amount))

        async def publish_event(self, channel, event_data):
            self.events.append((channel, event_data))

    class FakeDirectus:
        def __init__(self, order):
            self.pending_bank_transfer = {"id": "pending-row-id", **order}
            self.updated_users = []
            self.updated_items = []

        async def get_items(self, collection, params=None, **_kwargs):
            if collection == "pending_bank_transfers":
                return [{"id": self.pending_bank_transfer["id"]}]
            return []

        async def update_item(self, collection, item_id, data):
            assert collection == "pending_bank_transfers"
            assert item_id == "pending-row-id"
            self.updated_items.append((collection, item_id, dict(data)))
            self.pending_bank_transfer.update(data)
            return dict(self.pending_bank_transfer)

        async def update_user(self, user_id, payload):
            self.updated_users.append((user_id, payload))
            return True

    @staticmethod
    def _order(**overrides):
        order = {
            "order_id": "bt_personal01",
            "status": "pending",
            "amount_expected_cents": 5000,
            "user_id": "user-123",
            "credits_amount": 54000,
            "order_type": "credit_purchase",
            "reference": "OM-USER-bt01",
            "email_encryption_key": "email-key",
            "expires_at": "2026-07-29T00:00:00+00:00",
        }
        order.update(overrides)
        return order

    @pytest.mark.asyncio
    async def test_transaction_created_uses_signed_webhook_reference_when_api_reference_missing(self, monkeypatch):
        order = self._order()
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))

        class ApiConfirmedWithoutReference:
            async def fetch_confirmed_incoming_transfer(self, transaction_id):
                return {
                    "event_type": "TransactionCreated",
                    "transaction_id": transaction_id,
                    "state": "completed",
                    "reference": "",
                    "amount_cents": 4500,
                    "currency": "eur",
                    "counterparty": {},
                    "created_at": "2026-04-13T12:00:00.000Z",
                }

        event = _make_transaction_created_event(
            amount=45.0,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-api-no-reference",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=types.SimpleNamespace(revolut_business=ApiConfirmedWithoutReference()),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "bank_transfer_underpaid"}
        assert directus.updated_items[0][2]["received_amount_cents"] == 4500
        assert sent_tasks[0]["name"] == payments.BANK_TRANSFER_AMOUNT_NOTICE_TASK

    @pytest.mark.asyncio
    async def test_state_changed_without_any_reference_waits_for_created_event(self, monkeypatch):
        order = self._order()
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))

        class ApiConfirmedWithoutReference:
            async def fetch_confirmed_incoming_transfer(self, transaction_id):
                return {
                    "event_type": "TransactionCreated",
                    "transaction_id": transaction_id,
                    "state": "completed",
                    "reference": "",
                    "amount_cents": 5000,
                    "currency": "eur",
                    "counterparty": {},
                    "created_at": "2026-04-13T12:00:00.000Z",
                }

        result = await payments._handle_revolut_business_webhook(
            event_payload=_make_state_changed_event(transaction_id="txn-state-no-reference"),
            event_type="TransactionStateChanged",
            payment_service=types.SimpleNamespace(revolut_business=ApiConfirmedWithoutReference()),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "transaction_reference_unavailable"}
        assert directus.updated_items == []
        assert cache.status_updates == []
        assert sent_tasks == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("order_type", "amount", "remaining_amount_eur"),
        [
            ("credit_purchase", 45.0, "5.00"),
            ("credit_purchase", 49.75, "0.25"),
            ("team_credit_purchase", 45.0, "5.00"),
            ("gift_card_purchase", 45.0, "5.00"),
        ],
    )
    async def test_underpaid_transfer_stays_pending_extends_expiry_and_emails(
        self,
        monkeypatch,
        order_type,
        amount,
        remaining_amount_eur,
    ):
        order = self._order(order_type=order_type)
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))

        event = _make_transaction_created_event(
            amount=amount,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-underpaid",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_confirmed_payment_service(event),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "bank_transfer_underpaid"}
        update = directus.updated_items[0][2]
        assert update["status"] == "pending"
        assert update["received_amount_cents"] == int(amount * 100)
        assert update["remaining_amount_cents"] == int(float(remaining_amount_eur) * 100)
        assert update["overpaid_amount_cents"] == 0
        assert update["revolut_transactions"] == [
            {
                "transaction_id": "txn-underpaid",
                "amount_cents": int(amount * 100),
                "currency": "eur",
                "received_at": "2026-04-13T12:00:00.000Z",
            }
        ]
        assert datetime.fromisoformat(update["expires_at"]).tzinfo is not None
        assert cache.set_user_calls == []
        assert sent_tasks[0]["name"] == payments.BANK_TRANSFER_AMOUNT_NOTICE_TASK
        assert sent_tasks[0]["kwargs"]["notice_type"] == "underpaid"
        assert sent_tasks[0]["kwargs"]["remaining_amount_eur"] == remaining_amount_eur

    @pytest.mark.asyncio
    async def test_second_partial_completes_selected_pack_once_total_is_enough(self, monkeypatch):
        order = self._order(
            received_amount_cents=4500,
            remaining_amount_cents=500,
            revolut_transaction_id="txn-first",
            revolut_transactions=[
                {
                    "transaction_id": "txn-first",
                    "amount_cents": 4500,
                    "currency": "eur",
                    "received_at": "2026-04-13T12:00:00.000Z",
                }
            ],
        )
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        compliance_events = []
        broadcasts = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))
        monkeypatch.setattr(payments, "ReferralService", self.FakeReferralService)
        monkeypatch.setattr(
            payments.ComplianceService,
            "log_financial_transaction",
            lambda **kwargs: compliance_events.append(kwargs),
        )
        monkeypatch.setattr(payments.manager, "broadcast_to_user_specific_event", lambda **kwargs: broadcasts.append(kwargs))

        event = _make_transaction_created_event(
            amount=5.0,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-second",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_confirmed_payment_service(event),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "bank_transfer_completed"}
        assert cache.user["credits"] == 54500
        update = directus.updated_items[0][2]
        assert update["status"] == "completed"
        assert update["received_amount_cents"] == 5000
        assert update["remaining_amount_cents"] == 0
        assert len(update["revolut_transactions"]) == 2
        assert [task["name"] for task in sent_tasks] == [
            "app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email"
        ]
        assert compliance_events[0]["details"]["received_amount_cents"] == 5000

    @pytest.mark.asyncio
    async def test_uppercase_bank_reference_matches_legacy_mixed_case_order(self, monkeypatch):
        order = self._order(reference="OM-USER-btcase01")

        class VariantCache(self.FakeCache):
            def __init__(self, order):
                super().__init__(order)
                self.lookup_requests = []

            async def get_bank_transfer_by_reference(self, requested_reference):
                self.lookup_requests.append(requested_reference)
                if requested_reference == self.order["reference"]:
                    return dict(self.order)
                return None

        cache = VariantCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        compliance_events = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))
        monkeypatch.setattr(payments, "ReferralService", self.FakeReferralService)
        monkeypatch.setattr(
            payments.ComplianceService,
            "log_financial_transaction",
            lambda **kwargs: compliance_events.append(kwargs),
        )
        monkeypatch.setattr(payments.manager, "broadcast_to_user_specific_event", lambda **kwargs: None)

        event = _make_transaction_created_event(
            amount=50.0,
            currency="EUR",
            reference="OM-USER-BTCASE01",
            transaction_id="txn-uppercase-reference",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_confirmed_payment_service(event),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "bank_transfer_completed"}
        assert "OM-USER-btcase01" in cache.lookup_requests
        assert cache.status_updates[0]["reference"] == "OM-USER-btcase01"
        assert directus.updated_items[0][2]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_overpaid_transfer_credits_selected_pack_and_queues_surplus_notice(self, monkeypatch):
        order = self._order()
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))
        monkeypatch.setattr(payments, "ReferralService", self.FakeReferralService)
        monkeypatch.setattr(payments.ComplianceService, "log_financial_transaction", lambda **_kwargs: None)
        monkeypatch.setattr(payments.manager, "broadcast_to_user_specific_event", lambda **_kwargs: None)

        event = _make_transaction_created_event(
            amount=70.0,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-overpaid",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_confirmed_payment_service(event),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "bank_transfer_completed"}
        assert cache.user["credits"] == 54500
        update = directus.updated_items[0][2]
        assert update["received_amount_cents"] == 7000
        assert update["overpaid_amount_cents"] == 2000
        assert [task["name"] for task in sent_tasks] == [
            "app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email",
            payments.BANK_TRANSFER_AMOUNT_NOTICE_TASK,
        ]
        assert sent_tasks[1]["kwargs"]["notice_type"] == "overpaid"
        assert sent_tasks[1]["kwargs"]["overpaid_amount_eur"] == "20.00"

    @pytest.mark.asyncio
    async def test_duplicate_revolut_transaction_id_is_ignored(self, monkeypatch):
        order = self._order(
            received_amount_cents=4500,
            remaining_amount_cents=500,
            revolut_transaction_id="txn-duplicate",
            revolut_transactions=[
                {
                    "transaction_id": "txn-duplicate",
                    "amount_cents": 4500,
                    "currency": "eur",
                    "received_at": "2026-04-13T12:00:00.000Z",
                }
            ],
        )
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))

        event = _make_transaction_created_event(
            amount=45.0,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-duplicate",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_confirmed_payment_service(event),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "duplicate_transaction_ignored"}
        assert directus.updated_items == []
        assert cache.status_updates == []
        assert sent_tasks == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cache_returns_completed", [True, False])
    async def test_distinct_transaction_for_completed_reference_emails_user_without_recredit(
        self,
        monkeypatch,
        cache_returns_completed,
    ):
        order = self._order(
            status="completed",
            received_amount_cents=5000,
            remaining_amount_cents=0,
            overpaid_amount_cents=0,
            revolut_transaction_id="txn-original",
            revolut_transactions=[
                {
                    "transaction_id": "txn-original",
                    "amount_cents": 5000,
                    "currency": "eur",
                    "received_at": "2026-04-13T12:00:00.000Z",
                }
            ],
        )

        class CompletedReferenceCache(self.FakeCache):
            async def get_bank_transfer_by_reference(self, _reference):
                if cache_returns_completed:
                    return dict(self.order)
                return None

        class CompletedReferenceDirectus(self.FakeDirectus):
            def __init__(self, order):
                super().__init__(order)
                self.query_statuses = []

            async def get_items(self, collection, params=None, **_kwargs):
                if collection == "pending_bank_transfers":
                    status_filter = (params or {}).get("filter[status][_eq]")
                    self.query_statuses.append(status_filter)
                    if status_filter == "pending":
                        return []
                    if status_filter == "completed":
                        return [dict(self.pending_bank_transfer)]
                    return [{"id": self.pending_bank_transfer["id"]}]
                return []

        cache = CompletedReferenceCache(order)
        directus = CompletedReferenceDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))

        event = _make_transaction_created_event(
            amount=50.0,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-duplicate-reference",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_confirmed_payment_service(event),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "duplicate_completed_reference_emailed"}
        assert cache.set_user_calls == []
        assert cache.status_updates == []
        update = directus.updated_items[0][2]
        assert update["status"] == "completed"
        assert update["received_amount_cents"] == 10000
        assert update["overpaid_amount_cents"] == 5000
        assert update["revolut_transaction_id"] == "txn-duplicate-reference"
        assert update["revolut_transactions"][-1]["source"] == "duplicate_completed_reference"
        assert [task["name"] for task in sent_tasks] == [
            payments.BANK_TRANSFER_DUPLICATE_REFERENCE_EMAIL_TASK,
            "app.tasks.email_tasks.alert_notification_email_task.send_alert_notification",
        ]
        assert sent_tasks[0]["kwargs"]["received_amount_eur"] == "50.00"
        assert sent_tasks[0]["kwargs"]["reference"] == order["reference"]
        assert sent_tasks[0]["kwargs"]["transaction_id"] == "txn-duplicate-reference"
        assert order["reference"] in sent_tasks[1]["kwargs"]["description"]

    @pytest.mark.asyncio
    async def test_api_confirmation_failure_alerts_admin_and_does_not_settle(self, monkeypatch):
        order = self._order()
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))
        event = _make_transaction_created_event(
            amount=50.0,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-confirmation-failed",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_failing_payment_service(
                RevolutBusinessTransactionConfirmationError(
                    "provider_lookup_failed",
                    "provider unavailable",
                )
            ),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "transaction_confirmation_failed"}
        assert directus.updated_items == []
        assert cache.status_updates == []
        assert sent_tasks[0]["name"] == "app.tasks.email_tasks.alert_notification_email_task.send_alert_notification"
        assert "txn-confirmation-failed" in sent_tasks[0]["kwargs"]["description"]
        assert order["reference"] in sent_tasks[0]["kwargs"]["description"]

    @pytest.mark.asyncio
    async def test_api_pending_transaction_waits_without_admin_alert(self, monkeypatch):
        order = self._order()
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))
        event = _make_transaction_created_event(
            amount=50.0,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-pending",
            state="pending",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_failing_payment_service(
                RevolutBusinessTransactionConfirmationError(
                    "transaction_not_completed",
                    "transaction pending",
                    alert_required=False,
                    state="pending",
                )
            ),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "transaction_pending"}
        assert directus.updated_items == []
        assert cache.status_updates == []
        assert sent_tasks == []

    @pytest.mark.asyncio
    async def test_missing_api_credentials_do_not_alert_admin(self, monkeypatch):
        order = self._order()
        cache = self.FakeCache(order)
        directus = self.FakeDirectus(order)
        sent_tasks = []
        monkeypatch.setattr(payments.app, "send_task", lambda **kwargs: sent_tasks.append(kwargs))
        event = _make_transaction_created_event(
            amount=50.0,
            currency="EUR",
            reference=order["reference"],
            transaction_id="txn-missing-api-creds",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_failing_payment_service(
                RevolutBusinessTransactionConfirmationError(
                    "api_credentials_missing",
                    "credentials missing",
                    alert_required=False,
                )
            ),
            cache_service=cache,
            directus_service=directus,
            encryption_service=self.FakeEncryption(),
            secrets_manager=self.FakeSecrets(),
            tier_service=self.FakeTier(),
        )

        assert result == {"status": "transaction_confirmation_unavailable"}
        assert directus.updated_items == []
        assert cache.status_updates == []
        assert sent_tasks == []


class TestGiftCardBankTransferWebhook:
    """Regression coverage for purchased gift cards paid by SEPA transfer."""

    @pytest.mark.asyncio
    async def test_confirmed_gift_card_transfer_creates_card_and_email_not_credits(self, monkeypatch):
        reference = "OM-TEST-btgift01"
        order_id = "bt_gift01"
        user_id = "user-123"

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

            async def get_items(self, collection, params=None, **_kwargs):
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

        event = _make_transaction_created_event(
            amount=20.0,
            currency="EUR",
            reference=reference,
            transaction_id="txn-gift-card",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_confirmed_payment_service(event),
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


class TestTeamBankTransferWebhook:
    """Regression coverage for team credits paid by SEPA transfer."""

    @pytest.mark.asyncio
    async def test_confirmed_team_transfer_grants_team_credits_not_personal_credits(self, monkeypatch):
        reference = "OMT-team01-bt01"
        order_id = "bt_team01"
        user_id = "owner-123"
        team_id = "team-123"
        team_hash = hashlib.sha256(team_id.encode()).hexdigest()

        class FakeTeam:
            async def require_team_role(self, requested_team_id, requested_user_id, roles):
                assert requested_team_id == team_id
                assert requested_user_id == user_id
                assert "admin" in roles
                return {"role": "owner"}

        class FakeCache:
            def __init__(self):
                self.user = {"vault_key_id": "vault-key", "credits": 500}
                self.status_updates = []
                self.stats = []
                self.set_user_calls = []

            async def get_bank_transfer_by_reference(self, requested_reference):
                assert requested_reference == reference
                return {
                    "order_id": order_id,
                    "status": "pending",
                    "amount_expected_cents": 10000,
                    "user_id": user_id,
                    "team_id": team_id,
                    "hashed_team_id": team_hash,
                    "credits_amount": 110000,
                    "order_type": "team_credit_purchase",
                    "email_encryption_key": "email-key",
                }

            async def get_user_by_id(self, requested_user_id):
                assert requested_user_id == user_id
                return dict(self.user)

            async def set_user(self, data, user_id):
                self.set_user_calls.append((user_id, dict(data)))
                self.user = dict(data)

            async def update_bank_transfer_status(self, **kwargs):
                self.status_updates.append(kwargs)

            async def increment_stat(self, name, value=None):
                self.stats.append(("increment_stat", name, value))

            async def increment_json_stat(self, name, key):
                self.stats.append(("increment_json_stat", name, key))

            async def update_liability(self, amount):
                self.stats.append(("update_liability", amount))

        class FakeDirectus:
            def __init__(self):
                self.team = FakeTeam()
                self.team_credit_accounts = [
                    {
                        "id": "account-row-id",
                        "hashed_team_id": team_hash,
                        "encrypted_balance": "cipher-balance",
                        "balance_credits": 5,
                        "version": 1,
                        "updated_at": 100,
                    }
                ]
                self.team_credit_events = []
                self.pending_bank_transfers = [
                    {
                        "id": "pending-row-id",
                        "order_id": order_id,
                        "reference": reference,
                        "status": "pending",
                    }
                ]

            async def get_items(self, collection, params=None, **_kwargs):
                if collection == "team_credit_accounts":
                    return list(self.team_credit_accounts)
                if collection == "pending_bank_transfers":
                    return list(self.pending_bank_transfers)
                return []

            async def update_item(self, collection, item_id, data, admin_required=False):
                if collection == "team_credit_accounts":
                    assert admin_required is True
                    self.team_credit_accounts[0].update(data)
                    return dict(self.team_credit_accounts[0])
                if collection == "pending_bank_transfers":
                    self.pending_bank_transfers[0].update(data)
                    return dict(self.pending_bank_transfers[0])
                raise AssertionError(f"Unexpected update collection: {collection}")

            async def create_item(self, collection, data, admin_required=False):
                assert collection == "team_credit_events"
                assert admin_required is True
                self.team_credit_events.append(dict(data))
                return True, dict(data)

        compliance_events = []
        monkeypatch.setattr(
            payments.ComplianceService,
            "log_financial_transaction",
            lambda **kwargs: compliance_events.append(kwargs),
        )

        cache = FakeCache()
        directus = FakeDirectus()

        event = _make_transaction_created_event(
            amount=100.0,
            currency="EUR",
            reference=reference,
            transaction_id="txn-team-credit",
        )

        result = await payments._handle_revolut_business_webhook(
            event_payload=event,
            event_type="TransactionCreated",
            payment_service=_fake_confirmed_payment_service(event),
            cache_service=cache,
            directus_service=directus,
            encryption_service=object(),
            secrets_manager=object(),
            tier_service=object(),
        )

        assert result == {"status": "team_bank_transfer_completed"}
        assert directus.team_credit_accounts[0]["balance_credits"] == 110005
        assert directus.team_credit_accounts[0]["encrypted_balance"] == "cipher-balance"
        assert directus.team_credit_events == [
            {
                "event_id": "bank-transfer:bt_team01",
                "hashed_team_id": team_hash,
                "actor_user_hash": hashlib.sha256(user_id.encode()).hexdigest(),
                "event_type": "purchase",
                "amount": 110000,
                "encrypted_metadata": None,
                "created_at": directus.team_credit_events[0]["created_at"],
            }
        ]
        assert directus.pending_bank_transfers[0]["status"] == "completed"
        assert cache.user["credits"] == 500
        assert cache.set_user_calls == []
        assert cache.status_updates[0]["order_id"] == order_id
        assert ("increment_json_stat", "purchases_by_provider", "team_bank_transfer") in cache.stats
        assert compliance_events[0]["transaction_type"] == "team_credit_purchase"
        assert compliance_events[0]["details"]["team_id"] == team_id
