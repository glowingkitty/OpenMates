"""
Durable privacy-safe credit purchase settlement accounting.

This ledger stores only a one-way settlement identity hash and aggregate
purchase metadata. Callers create a pending row before mutating credits and
complete it afterward so monitoring can reject incomplete totals.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any
from uuid import uuid4


PURCHASE_SETTLEMENT_COLLECTION = "credit_purchase_settlements"
PURCHASE_SETTLEMENT_WATERMARK_KEY = "operational-monitoring-purchase-ledger-v1"


def _settlement_key_hash(settlement_key: str) -> str:
    return hashlib.sha256(f"openmates:purchase-settlement:v1:{settlement_key}".encode()).hexdigest()


async def _get_settlement(directus_service: Any, settlement_key_hash: str) -> dict[str, Any] | None:
    rows = await directus_service.get_items(
        PURCHASE_SETTLEMENT_COLLECTION,
        {
            "limit": 1,
            "fields": "id,settlement_key_hash,record_type,provider,purchase_type,credits_sold,state,started_at,completed_at",
            "filter": {"settlement_key_hash": {"_eq": settlement_key_hash}},
        },
        admin_required=True,
        raise_on_error=True,
    )
    return rows[0] if rows else None


async def get_purchase_settlement(
    directus_service: Any,
    *,
    settlement_key: str,
) -> dict[str, Any] | None:
    """Read an existing settlement without creating historical ledger data."""
    return await _get_settlement(
        directus_service,
        _settlement_key_hash(settlement_key),
    )


def _validate_identity(
    settlement: dict[str, Any],
    *,
    provider: str,
    purchase_type: str,
    credits_sold: int,
) -> None:
    expected = (provider, purchase_type, int(credits_sold))
    actual = (
        str(settlement.get("provider")),
        str(settlement.get("purchase_type")),
        int(settlement.get("credits_sold", 0) or 0),
    )
    if actual != expected:
        raise RuntimeError("purchase_settlement_identity_conflict")


async def begin_purchase_settlement(
    directus_service: Any,
    *,
    settlement_key: str,
    provider: str,
    purchase_type: str,
    credits_sold: int,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    """Create or recover one idempotent pending settlement before credit mutation."""
    key_hash = _settlement_key_hash(settlement_key)
    existing = await get_purchase_settlement(directus_service, settlement_key=settlement_key)
    if existing:
        _validate_identity(existing, provider=provider, purchase_type=purchase_type, credits_sold=credits_sold)
        return {**existing, "_created": False}

    timestamp = (started_at or datetime.now(timezone.utc)).isoformat()
    payload = {
        "id": str(uuid4()),
        "settlement_key_hash": key_hash,
        "record_type": "purchase",
        "provider": provider,
        "purchase_type": purchase_type,
        "credits_sold": int(credits_sold),
        "state": "pending",
        "started_at": timestamp,
        "completed_at": None,
    }
    created, row = await directus_service.create_item(
        PURCHASE_SETTLEMENT_COLLECTION,
        payload,
        admin_required=True,
    )
    if not created:
        row = await _get_settlement(directus_service, key_hash)
        if not row:
            raise RuntimeError("purchase_settlement_begin_failed")
    _validate_identity(row, provider=provider, purchase_type=purchase_type, credits_sold=credits_sold)
    return {**row, "_created": created}


async def complete_purchase_settlement(
    directus_service: Any,
    settlement: dict[str, Any],
    *,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    """Mark a pending settlement complete after the durable credit mutation."""
    if settlement.get("state") == "completed":
        return settlement
    timestamp = (completed_at or datetime.now(timezone.utc)).isoformat()
    updated = await directus_service.update_item(
        PURCHASE_SETTLEMENT_COLLECTION,
        str(settlement["id"]),
        {"state": "completed", "completed_at": timestamp},
        admin_required=True,
    )
    if not updated:
        raise RuntimeError("purchase_settlement_complete_failed")
    return {**settlement, "state": "completed", "completed_at": timestamp}


async def cancel_purchase_settlement(directus_service: Any, settlement: dict[str, Any]) -> None:
    """Remove a new pending row only when the caller proved no credit mutation occurred."""
    deleted = await directus_service.delete_item(
        PURCHASE_SETTLEMENT_COLLECTION,
        str(settlement["id"]),
        admin_required=True,
    )
    if not deleted:
        raise RuntimeError("purchase_settlement_cancel_failed")


async def ensure_purchase_ledger_watermark(
    directus_service: Any,
    *,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist the ledger rollout boundary needed to prove a complete 24-hour window."""
    key_hash = _settlement_key_hash(PURCHASE_SETTLEMENT_WATERMARK_KEY)
    existing = await get_purchase_settlement(
        directus_service,
        settlement_key=PURCHASE_SETTLEMENT_WATERMARK_KEY,
    )
    if existing:
        return existing
    timestamp = (started_at or datetime.now(timezone.utc)).isoformat()
    payload = {
        "id": str(uuid4()),
        "settlement_key_hash": key_hash,
        "record_type": "watermark",
        "provider": "internal",
        "purchase_type": "watermark",
        "credits_sold": 0,
        "state": "completed",
        "started_at": timestamp,
        "completed_at": timestamp,
    }
    created, row = await directus_service.create_item(
        PURCHASE_SETTLEMENT_COLLECTION,
        payload,
        admin_required=True,
    )
    if created:
        return row
    row = await _get_settlement(directus_service, key_hash)
    if not row:
        raise RuntimeError("purchase_ledger_watermark_failed")
    return row
