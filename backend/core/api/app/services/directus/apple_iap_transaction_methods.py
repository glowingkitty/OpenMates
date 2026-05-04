# backend/core/api/app/services/directus/apple_iap_transaction_methods.py
# Durable Apple IAP transaction idempotency helpers.

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)

APPLE_IAP_TRANSACTIONS_COLLECTION = "apple_iap_transactions"
APPLE_IAP_TRANSACTION_NAMESPACE = uuid.UUID("5ee6bf17-9023-4d60-901e-f6fead61c4f1")


class AppleIAPTransactionMethods:
    """Methods for the durable Apple IAP transaction ledger."""

    def __init__(self, directus_service):
        self.directus = directus_service

    async def get_by_transaction_id(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Return the ledger row for an Apple transaction, if it exists."""
        rows = await self.directus.get_items(
            APPLE_IAP_TRANSACTIONS_COLLECTION,
            params={
                "filter": {"transaction_id": {"_eq": transaction_id}},
                "fields": "*",
                "limit": 1,
            },
            admin_required=True,
        )
        if not rows:
            return None
        return rows[0]

    async def reserve_processed_transaction(
        self,
        *,
        transaction_id: str,
        original_transaction_id: str,
        user_id: str,
        product_id: str,
        credits: int,
        environment: str,
    ) -> tuple[bool, Optional[Dict[str, Any]]]:
        """Create the unique ledger row before fulfillment to prevent replays."""
        payload = {
            "id": str(uuid.uuid5(APPLE_IAP_TRANSACTION_NAMESPACE, transaction_id)),
            "transaction_id": transaction_id,
            "original_transaction_id": original_transaction_id,
            "user_id": user_id,
            "product_id": product_id,
            "credits": credits,
            "environment": environment,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        success, created = await self.directus.create_item(
            APPLE_IAP_TRANSACTIONS_COLLECTION,
            payload,
            admin_required=True,
        )
        if success:
            return True, created

        existing = await self.get_by_transaction_id(transaction_id)
        if existing:
            return False, existing

        logger.error("Failed to reserve Apple IAP transaction and no existing row was found")
        return False, None

    async def delete_processed_transaction(self, transaction_id: str) -> bool:
        """Remove a reservation if fulfillment failed before credits were added."""
        item_id = str(uuid.uuid5(APPLE_IAP_TRANSACTION_NAMESPACE, transaction_id))
        return await self.directus.delete_item(
            APPLE_IAP_TRANSACTIONS_COLLECTION,
            item_id,
            admin_required=True,
        )
