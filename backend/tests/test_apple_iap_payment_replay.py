# contract-test-file: infrastructure
"""
Regression tests for Apple IAP replay responses.

Completed StoreKit transactions are idempotent, but replay responses still need
the current durable balance. These tests keep cache misses from returning a
false zero balance after successful fulfillment.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException


# contract-test: direct surface=cli assertions=operational-monitoring.digest.real-24h-snapshot
@pytest.mark.anyio
async def test_apple_iap_transaction_completion_is_durable():
    from backend.core.api.app.services.directus.apple_iap_transaction_methods import (
        AppleIAPTransactionMethods,
    )

    directus = AsyncMock()
    directus.update_item = AsyncMock(return_value={"id": "transaction-row", "state": "completed"})

    completed = await AppleIAPTransactionMethods(directus).mark_transaction_completed("tx-123")

    assert completed is True
    payload = directus.update_item.await_args.args[2]
    assert payload["state"] == "completed"
    assert payload["completed_at"]


# contract-test: direct surface=cli assertions=operational-monitoring.digest.real-24h-snapshot
@pytest.mark.anyio
async def test_processed_apple_replay_credit_response_falls_back_to_directus():
    from backend.core.api.app.routes.payments import _current_credit_balance_for_response

    cache_service = AsyncMock()
    cache_service.get_user_by_id = AsyncMock(return_value={})
    directus_service = AsyncMock()
    directus_service.get_user_fields_direct = AsyncMock(return_value={
        "encrypted_credit_balance": "vault:v1:balance",
        "vault_key_id": "vault-key",
    })
    encryption_service = AsyncMock()
    encryption_service.decrypt_with_user_key = AsyncMock(return_value="1234")

    balance = await _current_credit_balance_for_response(
        "user-1",
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
    )

    assert balance == 1234
    directus_service.get_user_fields_direct.assert_awaited_once_with(
        "user-1",
        ["encrypted_credit_balance", "vault_key_id"],
    )
    encryption_service.decrypt_with_user_key.assert_awaited_once_with("vault:v1:balance", "vault-key")


# contract-test: direct surface=cli assertions=operational-monitoring.digest.real-24h-snapshot
@pytest.mark.anyio
async def test_processed_apple_replay_credit_response_fails_closed_without_balance():
    from backend.core.api.app.routes.payments import _current_credit_balance_for_response

    cache_service = AsyncMock()
    cache_service.get_user_by_id = AsyncMock(return_value={})
    directus_service = AsyncMock()
    directus_service.get_user_fields_direct = AsyncMock(return_value=None)

    with pytest.raises(HTTPException, match="Could not read current balance"):
        await _current_credit_balance_for_response(
            "user-1",
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=AsyncMock(),
        )
