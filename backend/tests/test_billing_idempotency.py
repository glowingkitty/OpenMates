"""
Billing idempotency contract tests.

These tests require stable charge identities to cross the internal billing route
and reach the personal billing service. The service must claim a charge before
changing balances or creating raw usage so retries can replay one result.
"""

import asyncio
import inspect

import pytest

from backend.upload.billing_payloads import build_pdf_billing_payload


def _require_internal_billing_route():
    pytest.importorskip("celery", reason="internal billing route imports worker wiring")
    pytest.importorskip("redis", reason="internal billing route imports cache wiring")
    from backend.core.api.app.routes.internal_api import CreditChargePayload, charge_credits_route

    return CreditChargePayload, charge_credits_route


def _require_billing_service_class():
    pytest.importorskip("celery", reason="billing service imports WebSocket worker wiring")
    pytest.importorskip("redis", reason="billing service imports cache wiring")
    from backend.core.api.app.services.billing_service import BillingService

    return BillingService


def _require_apps_api_route():
    pytest.importorskip("slowapi", reason="apps API route imports rate limiter wiring")
    from backend.core.api.app.routes import apps_api

    return apps_api


class _CapturingBillingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def charge_user_credits(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"charge_id": kwargs["idempotency_key"], "charged_credits": kwargs["credits_to_deduct"]}


# contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge
def test_personal_charge_route_forwards_stable_idempotency_key() -> None:
    CreditChargePayload, charge_credits_route = _require_internal_billing_route()
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


# contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge
def test_personal_billing_service_requires_charge_identity() -> None:
    BillingService = _require_billing_service_class()
    signature = inspect.signature(BillingService.charge_user_credits)

    assert "idempotency_key" in signature.parameters


# contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge
def test_pdf_upload_charge_payload_uses_embed_scoped_idempotency_key() -> None:
    payload = build_pdf_billing_payload(
        user_id="user-1",
        user_id_hash="hash-1",
        embed_id="embed-123",
        credits_to_charge=6,
        page_count=2,
        credits_per_page=3,
        filename="test_document.pdf",
        deduplicated=True,
    )

    assert payload["idempotency_key"] == "pdf:upload:embed-123"
    assert len(payload["idempotency_key"]) <= 255
    assert payload["usage_details"] == {
        "page_count": 2,
        "credits_per_page": 3,
        "filename": "test_document.pdf",
        "embed_id": "embed-123",
        "deduplicated": True,
    }


# contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge
def test_app_skill_charge_payload_uses_request_scoped_idempotency_key() -> None:
    apps_api = _require_apps_api_route()
    from backend.core.api.app.utils.request_context import set_request_id

    set_request_id("req-app-skill-1")

    key = apps_api._build_app_skill_billing_idempotency_key(
        app_id="code",
        skill_id="get_docs",
        user_id_hash="hash-1",
        credits=20,
        usage_details={"units_processed": 1, "server_provider": "Context7"},
    )

    assert key.startswith("app-skill:req-app-skill-1:code:get_docs:")
    assert len(key) <= 255
