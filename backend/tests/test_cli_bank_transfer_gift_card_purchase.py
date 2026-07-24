"""
CLI bank-transfer gift-card purchase contract tests.

These tests cover the terminal-specific API aliases that sit on top of the
existing SEPA pending-order infrastructure. They intentionally avoid real
payment providers, Directus, Redis, or Celery and call route functions with
small fakes so the CLI contract stays cheap to verify.

Execution:
  /OpenMates/.venv/bin/python3 -m pytest backend/tests/test_cli_bank_transfer_gift_card_purchase.py
"""

import sys
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

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

if "redis" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedisClient:
        pass

    redis_asyncio_module.Redis = FakeRedisClient
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

if "aiohttp" not in sys.modules:
    aiohttp_module = types.ModuleType("aiohttp")

    class FakeClientSession:
        pass

    aiohttp_module.ClientSession = FakeClientSession
    sys.modules["aiohttp"] = aiohttp_module

if "backend.core.api.app.services.limiter" not in sys.modules:
    limiter_module = types.ModuleType("backend.core.api.app.services.limiter")
    limiter_module.limiter = SimpleNamespace(limit=lambda *_args, **_kwargs: (lambda func: func))
    sys.modules["backend.core.api.app.services.limiter"] = limiter_module

from backend.core.api.app.routes import payments


def fake_request(method="GET", path="/"):
    return Request({"type": "http", "method": method, "path": path, "headers": [], "client": ("127.0.0.1", 12345)})


@pytest.fixture(autouse=True)
def official_cloud_request_domain(monkeypatch):
    monkeypatch.setattr(
        payments,
        "validate_request_domain",
        lambda _request: ("openmates.org", False, "production"),
    )


class FakeBankTransferCache:
    def __init__(self, order=None):
        self.order = order

    async def get_bank_transfer_by_order_id(self, order_id):
        return self.order if self.order and self.order.get("order_id") == order_id else None


class FakeDirectus:
    def __init__(self, orders=None):
        self.orders = orders or []

    async def get_items(self, collection, params=None):
        assert collection == "pending_bank_transfers"
        order_id = (params or {}).get("filter[order_id][_eq]")
        return [order for order in self.orders if order.get("order_id") == order_id]


class FakeSecrets:
    async def get_secret(self, **_kwargs):
        return "pk_test_openmates"


def test_gift_card_bank_transfer_routes_are_registered():
    route_paths = {route.path for route in payments.router.routes}

    assert "/v1/payments/create-gift-card-bank-transfer-order" in route_paths
    assert "/v1/payments/gift-card-purchase-status/{order_id}" in route_paths


@pytest.mark.anyio
async def test_payment_config_hides_bank_transfer_on_self_hosted(monkeypatch):
    monkeypatch.setattr(
        payments,
        "validate_request_domain",
        lambda _request: (None, True, "self_hosted"),
    )
    monkeypatch.setattr(payments, "get_geo_data_from_ip", lambda _ip: {"country_code": "DE"})

    response = await payments.get_payment_config(
        request=fake_request("GET", "/v1/payments/config"),
        secrets_manager=FakeSecrets(),
        payment_service=SimpleNamespace(is_bank_transfer_available=True),
    )

    assert response.bank_transfer_available is False


@pytest.mark.anyio
async def test_create_gift_card_bank_transfer_order_forces_gift_card_type(monkeypatch):
    captured = {}

    async def fake_create_bank_transfer_order(**kwargs):
        captured["order_data"] = kwargs["order_data"]
        return SimpleNamespace(order_id="bt_test")

    monkeypatch.setattr(payments, "create_bank_transfer_order", fake_create_bank_transfer_order)

    result = await payments.create_gift_card_bank_transfer_order(
        request=fake_request("POST", "/v1/payments/create-gift-card-bank-transfer-order"),
        order_data=payments.CreateBankTransferOrderRequest(
            credits_amount=21000,
            currency="eur",
            email_encryption_key="email-key",
            is_signup=True,
            is_gift_card=False,
        ),
        payment_service=SimpleNamespace(),
        cache_service=SimpleNamespace(),
        directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(),
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result.order_id == "bt_test"
    assert captured["order_data"].is_gift_card is True
    assert captured["order_data"].is_signup is False


@pytest.mark.anyio
async def test_gift_card_purchase_status_hides_code_until_completed():
    order = {
        "order_id": "bt_pending",
        "user_id": "user-1",
        "order_type": "gift_card_purchase",
        "status": "pending",
        "credits_amount": 21000,
        "amount_expected_cents": 2000,
        "reference": "OM-USER-bt_pend",
        "expires_at": "2026-06-16T00:00:00+00:00",
        "created_at": "2026-06-09T00:00:00+00:00",
        "gift_card_code": "SHOULD-NOT-SHOW",
    }

    response = await payments.get_gift_card_purchase_status(
        request=fake_request("GET", "/v1/payments/gift-card-purchase-status/bt_pending"),
        order_id="bt_pending",
        cache_service=FakeBankTransferCache(order),
        directus_service=FakeDirectus(),
        current_user=SimpleNamespace(id="user-1"),
    )

    assert response.status == "pending"
    assert response.gift_card_code is None


@pytest.mark.anyio
async def test_gift_card_purchase_status_reveals_code_after_completion():
    order = {
        "order_id": "bt_done",
        "user_id": "user-1",
        "order_type": "gift_card_purchase",
        "status": "completed",
        "credits_amount": 21000,
        "amount_expected_cents": 2000,
        "reference": "OM-USER-bt_done",
        "expires_at": "2026-06-16T00:00:00+00:00",
        "created_at": "2026-06-09T00:00:00+00:00",
        "gift_card_code": "OM-GIFT-CODE",
    }

    response = await payments.get_gift_card_purchase_status(
        request=fake_request("GET", "/v1/payments/gift-card-purchase-status/bt_done"),
        order_id="bt_done",
        cache_service=FakeBankTransferCache(order),
        directus_service=FakeDirectus(),
        current_user=SimpleNamespace(id="user-1"),
    )

    assert response.status == "completed"
    assert response.gift_card_code == "OM-GIFT-CODE"


@pytest.mark.anyio
async def test_gift_card_purchase_status_rejects_credit_purchase_order():
    order = {
        "order_id": "bt_credit",
        "user_id": "user-1",
        "order_type": "credit_purchase",
        "status": "completed",
    }

    with pytest.raises(HTTPException) as exc_info:
        await payments.get_gift_card_purchase_status(
            request=fake_request("GET", "/v1/payments/gift-card-purchase-status/bt_credit"),
            order_id="bt_credit",
            cache_service=FakeBankTransferCache(order),
            directus_service=FakeDirectus(),
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_gift_card_bank_transfer_routes_reject_self_hosted(monkeypatch):
    monkeypatch.setattr(
        payments,
        "validate_request_domain",
        lambda _request: (None, True, "self_hosted"),
    )

    with pytest.raises(HTTPException) as create_exc:
        await payments.create_gift_card_bank_transfer_order(
            request=fake_request("POST", "/v1/payments/create-gift-card-bank-transfer-order"),
            order_data=payments.CreateBankTransferOrderRequest(
                credits_amount=21000,
                currency="eur",
                email_encryption_key="email-key",
            ),
            payment_service=SimpleNamespace(),
            cache_service=SimpleNamespace(),
            directus_service=SimpleNamespace(),
            encryption_service=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1"),
        )

    with pytest.raises(HTTPException) as status_exc:
        await payments.get_gift_card_purchase_status(
            request=fake_request("GET", "/v1/payments/gift-card-purchase-status/bt_done"),
            order_id="bt_done",
            cache_service=FakeBankTransferCache(),
            directus_service=FakeDirectus(),
            current_user=SimpleNamespace(id="user-1"),
        )

    assert create_exc.value.status_code == 404
    assert status_exc.value.status_code == 404


@pytest.mark.anyio
async def test_credit_bank_transfer_routes_reject_self_hosted(monkeypatch):
    monkeypatch.setattr(
        payments,
        "validate_request_domain",
        lambda _request: (None, True, "self_hosted"),
    )

    with pytest.raises(HTTPException) as create_exc:
        await payments.create_bank_transfer_order(
            request=fake_request("POST", "/v1/payments/create-bank-transfer-order"),
            order_data=payments.CreateBankTransferOrderRequest(
                credits_amount=21000,
                currency="eur",
                email_encryption_key="email-key",
            ),
            payment_service=SimpleNamespace(is_bank_transfer_available=True),
            cache_service=SimpleNamespace(),
            directus_service=SimpleNamespace(),
            encryption_service=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1", account_id="acct-1"),
        )

    with pytest.raises(HTTPException) as status_exc:
        await payments.get_bank_transfer_status(
            request=fake_request("GET", "/v1/payments/bank-transfer-status/bt_done"),
            order_id="bt_done",
            cache_service=FakeBankTransferCache(),
            directus_service=FakeDirectus(),
            current_user=SimpleNamespace(id="user-1"),
        )

    with pytest.raises(HTTPException) as pending_exc:
        await payments.get_pending_bank_transfers(
            request=fake_request("GET", "/v1/payments/bank-transfer-pending"),
            cache_service=SimpleNamespace(),
            directus_service=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1"),
        )

    assert create_exc.value.status_code == 404
    assert status_exc.value.status_code == 404
    assert pending_exc.value.status_code == 404


@pytest.mark.anyio
async def test_support_bank_transfer_route_rejects_self_hosted(monkeypatch):
    monkeypatch.setattr(
        payments,
        "validate_request_domain",
        lambda _request: (None, True, "self_hosted"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await payments.create_support_bank_transfer_order(
            request=fake_request("POST", "/v1/payments/create-support-bank-transfer-order"),
            order_data=payments.CreateSupportBankTransferRequest(
                amount=1000,
                currency="eur",
                support_email="supporter@example.com",
            ),
            payment_service=SimpleNamespace(is_bank_transfer_available=True),
            cache_service=SimpleNamespace(),
            directus_service=SimpleNamespace(),
            current_user=None,
        )

    assert exc_info.value.status_code == 404
