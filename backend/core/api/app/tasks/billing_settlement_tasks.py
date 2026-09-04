# backend/core/api/app/tasks/billing_settlement_tasks.py
#
# Durable recovery for retryable personal credit settlement conflicts.
# Outbox payloads remain Vault-encrypted at rest and are only decrypted inside
# the first-party persistence worker. Every attempt reuses the original charge
# identity, making a crash after commit safe to replay without duplicate usage.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.core.api.app.services.billing_settlement_service import process_pending_settlement
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

SETTLEMENT_SWEEP_LIMIT = 100


@app.task(
    name="billing.retry_personal_settlement",
    base=BaseServiceTask,
    bind=True,
)
def retry_personal_billing_settlement(
    self: BaseServiceTask,
    *,
    outbox_id: str,
    charge_id: str,
    user_id_hash: str,
) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        try:
            await self.initialize_services()
            result = await process_pending_settlement(
                outbox_id=outbox_id,
                charge_id=charge_id,
                user_id_hash=user_id_hash,
                directus_service=self.directus_service,
                cache_service=self.cache_service,
                encryption_service=self.encryption_service,
            )
            if result["state"] == "retry_scheduled":
                retry_personal_billing_settlement.apply_async(
                    kwargs={
                        "outbox_id": outbox_id,
                        "charge_id": charge_id,
                        "user_id_hash": user_id_hash,
                    },
                    countdown=result["countdown"],
                    queue="persistence",
                )
            return result
        finally:
            await self.cleanup_services()

    return asyncio.run(run())


@app.task(name="billing.sweep_pending_settlements", base=BaseServiceTask, bind=True)
def sweep_pending_billing_settlements(self: BaseServiceTask) -> dict[str, int]:
    async def run() -> dict[str, int]:
        try:
            await self.initialize_services()
            rows = await self.directus_service.get_items(
                "billing_settlement_outbox",
                params={
                    "filter": {
                        "state": {"_in": ["pending", "retry_scheduled"]},
                        "_or": [
                            {"next_attempt_at": {"_null": True}},
                            {"next_attempt_at": {"_lte": "$NOW"}},
                        ],
                    },
                    "fields": "id,charge_id,hashed_user_id",
                    "sort": "created_at",
                    "limit": SETTLEMENT_SWEEP_LIMIT,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            for row in rows or []:
                retry_personal_billing_settlement.apply_async(
                    kwargs={
                        "outbox_id": row["id"],
                        "charge_id": row["charge_id"],
                        "user_id_hash": row["hashed_user_id"],
                    },
                    queue="persistence",
                )
            return {"dispatched": len(rows or [])}
        finally:
            await self.cleanup_services()

    return asyncio.run(run())
