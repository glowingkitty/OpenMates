"""
Billing idempotency contract tests.

These tests require stable charge identities to cross the internal billing route
and reach the personal billing service. The service must claim a charge before
changing balances or creating raw usage so retries can replay one result.
"""

import asyncio
import inspect

from backend.core.api.app.routes.internal_api import CreditChargePayload, charge_credits_route
from backend.core.api.app.services.billing_service import BillingService


class _CapturingBillingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def charge_user_credits(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"charge_id": kwargs["idempotency_key"], "charged_credits": kwargs["credits_to_deduct"]}


def test_personal_charge_route_forwards_stable_idempotency_key() -> None:
    billing = _CapturingBillingService()
    payload = CreditChargePayload(
        user_id="user-1",
        user_id_hash="hash-1",
        credits=25,
        app_id="ai",
        skill_id="ask",
        idempotency_key="turn-1:ai:ask:main",
        usage_details={"chat_id": "child-1", "root_chat_id": "root-1"},
    )

    asyncio.run(charge_credits_route(payload=payload, billing_service=billing))

    assert billing.calls[0]["idempotency_key"] == payload.idempotency_key


def test_personal_billing_service_requires_charge_identity() -> None:
    signature = inspect.signature(BillingService.charge_user_credits)

    assert "idempotency_key" in signature.parameters
