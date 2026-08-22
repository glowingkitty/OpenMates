# contract-test-file: infrastructure
"""
Contract tests for the privacy-safe credit purchase settlement ledger.

The ledger is the durable source for exact operational purchase totals. It
stores only hashed settlement identities and aggregate purchase metadata.
"""

from datetime import datetime, timezone

import pytest

from backend.core.api.app.services.purchase_settlement_ledger import (
    begin_purchase_settlement,
    complete_purchase_settlement,
)


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class FakeDirectus:
    def __init__(self):
        self.rows = []

    async def get_items(self, collection, params=None, **_kwargs):
        assert collection == "credit_purchase_settlements"
        filters = (params or {}).get("filter", {})
        settlement_hash = filters.get("settlement_key_hash", {}).get("_eq")
        return [row for row in self.rows if row["settlement_key_hash"] == settlement_hash]

    async def create_item(self, collection, payload, **_kwargs):
        assert collection == "credit_purchase_settlements"
        if any(row["settlement_key_hash"] == payload["settlement_key_hash"] for row in self.rows):
            return False, {"error": "unique"}
        row = {"id": f"row-{len(self.rows) + 1}", **payload}
        self.rows.append(row)
        return True, row

    async def update_item(self, collection, item_id, payload, **_kwargs):
        assert collection == "credit_purchase_settlements"
        row = next(row for row in self.rows if row["id"] == item_id)
        row.update(payload)
        return True


@pytest.mark.asyncio
async def test_settlement_identity_is_hashed_and_completion_is_idempotent():
    directus = FakeDirectus()

    settlement = await begin_purchase_settlement(
        directus,
        settlement_key="stripe:pi_private_identifier",
        provider="stripe",
        purchase_type="credit_purchase",
        credits_sold=250,
        started_at=NOW,
    )
    assert settlement["state"] == "pending"
    assert "pi_private_identifier" not in str(directus.rows)

    completed = await complete_purchase_settlement(directus, settlement, completed_at=NOW)
    duplicate = await begin_purchase_settlement(
        directus,
        settlement_key="stripe:pi_private_identifier",
        provider="stripe",
        purchase_type="credit_purchase",
        credits_sold=250,
        started_at=NOW,
    )

    assert completed["state"] == "completed"
    assert duplicate["state"] == "completed"
    assert len(directus.rows) == 1


@pytest.mark.asyncio
async def test_settlement_identity_rejects_conflicting_purchase_metadata():
    directus = FakeDirectus()
    await begin_purchase_settlement(
        directus,
        settlement_key="bank:order-1",
        provider="bank_transfer",
        purchase_type="credit_purchase",
        credits_sold=100,
        started_at=NOW,
    )

    with pytest.raises(RuntimeError, match="purchase_settlement_identity_conflict"):
        await begin_purchase_settlement(
            directus,
            settlement_key="bank:order-1",
            provider="bank_transfer",
            purchase_type="credit_purchase",
            credits_sold=200,
            started_at=NOW,
        )


@pytest.mark.asyncio
async def test_unique_create_race_returns_existing_settlement_as_not_created():
    class RaceDirectus(FakeDirectus):
        reads = 0

        async def get_items(self, collection, params=None, **kwargs):
            self.reads += 1
            if self.reads == 1:
                return []
            return await super().get_items(collection, params, **kwargs)

        async def create_item(self, collection, payload, **_kwargs):
            self.rows.append({"id": "winner", **payload})
            return False, {"error": "unique"}

    settlement = await begin_purchase_settlement(
        RaceDirectus(),
        settlement_key="stripe:race",
        provider="stripe",
        purchase_type="credit_purchase",
        credits_sold=100,
        started_at=NOW,
    )
    assert settlement["_created"] is False
