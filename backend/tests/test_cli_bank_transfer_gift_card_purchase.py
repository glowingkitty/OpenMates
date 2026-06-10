"""
CLI bank-transfer gift-card purchase contract tests.

These tests cover the terminal-specific API aliases that sit on top of the
existing SEPA pending-order infrastructure. They intentionally avoid real
payment providers, Directus, Redis, or Celery and call route functions with
small fakes so the CLI contract stays cheap to verify.

Execution:
  /OpenMates/.venv/bin/python3 -m pytest backend/tests/test_cli_bank_transfer_gift_card_purchase.py
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.core.api.app.routes import payments


def fake_request(method="GET", path="/"):
    return Request({"type": "http", "method": method, "path": path, "headers": [], "client": ("127.0.0.1", 12345)})


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


def test_gift_card_bank_transfer_routes_are_registered():
    route_paths = {route.path for route in payments.router.routes}

    assert "/v1/payments/create-gift-card-bank-transfer-order" in route_paths
    assert "/v1/payments/gift-card-purchase-status/{order_id}" in route_paths


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
