"""
Bank transfer invoice visibility contract tests.

These tests keep Billing > Invoices as the single user-facing place for
recovering the SEPA `OM-...` reference after a credit-purchase bank transfer is
started or completed.
"""

import sys
from types import SimpleNamespace
from importlib import import_module

import pytest

sys.modules.setdefault(
    "stripe",
    SimpleNamespace(api_key=None, error=SimpleNamespace(StripeError=Exception)),
)

class FakeDirectusService:
    def __init__(self, invoices: list[dict], transfers: list[dict]):
        self._invoices = invoices
        self._transfers = transfers

    async def get_items(self, collection: str, params: dict | None = None):
        if collection == "invoices":
            return self._invoices
        if collection == "pending_bank_transfers":
            return self._transfers
        raise AssertionError(f"Unexpected collection: {collection}")


class FakeEncryptionService:
    async def decrypt_with_user_key(self, ciphertext: str, _vault_key_id: str):
        return ciphertext


def _user(vault_key_id: str | None = "vault-key-1"):
    return SimpleNamespace(id="user-1", vault_key_id=vault_key_id)


@pytest.mark.asyncio
async def test_invoices_include_pending_and_completed_bank_transfer_references():
    get_invoices = import_module("backend.core.api.app.routes.payments").get_invoices
    handler = get_invoices
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__

    response = await handler(
        request=SimpleNamespace(),
        current_user=_user(),
        directus_service=FakeDirectusService(
            invoices=[
                {
                    "id": "invoice-1",
                    "order_id": "bt_completed_with_invoice",
                    "date": "2026-07-03T12:00:00+00:00",
                    "encrypted_amount": "10000",
                    "encrypted_credits_purchased": "110000",
                    "encrypted_filename": "Invoice_2026_07_03.pdf",
                    "encrypted_currency": "eur",
                    "provider": "bank_transfer",
                    "is_gift_card": False,
                    "refund_status": "none",
                    "refunded_at": None,
                }
            ],
            transfers=[
                {
                    "order_id": "bt_pending",
                    "user_id": "user-1",
                    "credits_amount": 21000,
                    "amount_expected_cents": 2000,
                    "currency": "eur",
                    "reference": "OM-ACCT-PENDING",
                    "status": "pending",
                    "order_type": "credit_purchase",
                    "created_at": "2026-07-03T10:00:00+00:00",
                    "expires_at": "2026-07-10T10:00:00+00:00",
                },
                {
                    "order_id": "bt_completed_with_invoice",
                    "user_id": "user-1",
                    "credits_amount": 110000,
                    "amount_expected_cents": 10000,
                    "currency": "eur",
                    "reference": "OM-ACCT-COMPLETE",
                    "status": "completed",
                    "order_type": "credit_purchase",
                    "created_at": "2026-07-03T11:00:00+00:00",
                    "completed_at": "2026-07-03T11:30:00+00:00",
                },
                {
                    "order_id": "bt_completed_generating",
                    "user_id": "user-1",
                    "credits_amount": 42000,
                    "amount_expected_cents": 4000,
                    "currency": "eur",
                    "reference": "OM-ACCT-GENERATING",
                    "status": "completed",
                    "order_type": "credit_purchase",
                    "created_at": "2026-07-03T12:30:00+00:00",
                    "completed_at": "2026-07-03T12:45:00+00:00",
                },
                {
                    "order_id": "bt_expired",
                    "user_id": "user-1",
                    "credits_amount": 21000,
                    "amount_expected_cents": 2000,
                    "currency": "eur",
                    "reference": "OM-ACCT-EXPIRED",
                    "status": "expired",
                    "order_type": "credit_purchase",
                    "created_at": "2026-06-01T10:00:00+00:00",
                },
                {
                    "order_id": "bt_review",
                    "user_id": "user-1",
                    "credits_amount": 21000,
                    "amount_expected_cents": 2000,
                    "currency": "eur",
                    "reference": "OM-ACCT-REVIEW",
                    "status": "admin_review",
                    "order_type": "credit_purchase",
                    "created_at": "2026-07-03T09:00:00+00:00",
                },
                {
                    "order_id": "bt_legacy_pending",
                    "user_id": "user-1",
                    "credits_amount": 21000,
                    "amount_expected_cents": 2000,
                    "currency": "eur",
                    "reference": "OM-ACCT-LEGACY",
                    "status": "pending",
                    "created_at": "2026-07-03T08:00:00+00:00",
                },
                {
                    "order_id": "bt_support",
                    "user_id": "user-1",
                    "credits_amount": 0,
                    "amount_expected_cents": 5000,
                    "currency": "eur",
                    "reference": "OM-SUP-SUPPORT",
                    "status": "pending",
                    "order_type": "support_contribution",
                    "created_at": "2026-07-03T09:00:00+00:00",
                },
            ],
        ),
        encryption_service=FakeEncryptionService(),
    )

    rows_by_id = {invoice.id: invoice for invoice in response.invoices}

    assert rows_by_id["bt_pending"].bank_transfer_reference == "OM-ACCT-PENDING"
    assert rows_by_id["bt_pending"].transaction_status == "pending"
    assert rows_by_id["bt_pending"].document_status == "pending_bank_transfer"
    assert rows_by_id["bt_pending"].filename == ""

    assert rows_by_id["invoice-1"].bank_transfer_reference == "OM-ACCT-COMPLETE"
    assert rows_by_id["invoice-1"].transaction_status == "completed"
    assert rows_by_id["invoice-1"].document_status == "ready"

    assert rows_by_id["bt_completed_generating"].bank_transfer_reference == "OM-ACCT-GENERATING"
    assert rows_by_id["bt_completed_generating"].transaction_status == "completed"
    assert rows_by_id["bt_completed_generating"].document_status == "generating"
    assert rows_by_id["bt_completed_generating"].filename == ""

    assert rows_by_id["bt_legacy_pending"].bank_transfer_reference == "OM-ACCT-LEGACY"
    assert rows_by_id["bt_legacy_pending"].transaction_status == "pending"

    assert "bt_completed_with_invoice" not in rows_by_id
    assert "bt_expired" not in rows_by_id
    assert "bt_review" not in rows_by_id
    assert "bt_support" not in rows_by_id


@pytest.mark.asyncio
async def test_pending_bank_transfer_rows_do_not_require_invoice_vault_key():
    get_invoices = import_module("backend.core.api.app.routes.payments").get_invoices
    handler = get_invoices
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__

    response = await handler(
        request=SimpleNamespace(),
        current_user=_user(vault_key_id=None),
        directus_service=FakeDirectusService(
            invoices=[],
            transfers=[
                {
                    "order_id": "bt_pending_no_vault",
                    "user_id": "user-1",
                    "credits_amount": 21000,
                    "amount_expected_cents": 2000,
                    "currency": "eur",
                    "reference": "OM-ACCT-NOVAULT",
                    "status": "pending",
                    "order_type": "credit_purchase",
                    "created_at": "2026-07-03T10:00:00+00:00",
                }
            ],
        ),
        encryption_service=FakeEncryptionService(),
    )

    assert len(response.invoices) == 1
    assert response.invoices[0].id == "bt_pending_no_vault"
    assert response.invoices[0].bank_transfer_reference == "OM-ACCT-NOVAULT"
