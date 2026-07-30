"""
Invoice Ninja bank integration mapping tests.

These tests cover local accounting-provider selection only. They do not call
Invoice Ninja, Stripe, Vault, or Directus. The production incident that prompted
them was a missing bank-transfer mapping after successful Directus invoice
creation, so the tests keep the contract small and deterministic.
"""

import pytest

from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService


class DummySecretsManager:
    pass


class FakeInvoiceNinjaService(InvoiceNinjaService):
    async def get_bank_integrations(self, params=None):
        return [
            {
                "bank_account_name": "Revolut Business Merchant",
                "bank_account_id": "merchant-bank-account-id",
                "id": "merchant-integration-id",
            },
            {
                "bank_account_name": "Revolut Business",
                "bank_account_id": "revolut-bank-account-id",
                "id": "revolut-integration-id",
            },
            {
                "bank_account_name": "Stripe",
                "bank_account_id": "stripe-bank-account-id",
                "id": "stripe-integration-id",
            },
        ]


@pytest.mark.asyncio
async def test_bank_transfer_uses_revolut_business_bank_integration():
    service = FakeInvoiceNinjaService(DummySecretsManager())
    service.headers = {"X-API-TOKEN": "test"}

    await service._load_bank_integration_details()

    assert service._bank_integration_for_processor("stripe") == (
        "stripe-bank-account-id",
        "stripe-integration-id",
    )
    assert service._bank_integration_for_processor("bank_transfer") == (
        "revolut-bank-account-id",
        "revolut-integration-id",
    )


@pytest.mark.asyncio
async def test_unknown_processor_still_has_no_bank_integration():
    service = FakeInvoiceNinjaService(DummySecretsManager())
    service.headers = {"X-API-TOKEN": "test"}
    await service._load_bank_integration_details()

    assert service._bank_integration_for_processor("paypal") == (None, None)
