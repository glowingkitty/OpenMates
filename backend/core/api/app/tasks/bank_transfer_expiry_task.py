"""
Bank Transfer Expiry Task

Periodic Celery task that marks expired pending bank transfer orders.
Runs every 6 hours via Celery Beat. Orders expire 7 days after creation.

Expired orders are updated in Directus and their Redis cache keys are cleaned up.
"""

import logging
from datetime import datetime, timezone

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_service_task import BaseServiceTask

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    base=BaseServiceTask,
    name="app.tasks.bank_transfer_expiry_task.expire_stale_bank_transfers",
    queue="persistence",
    max_retries=2,
    default_retry_delay=300,
)
def expire_stale_bank_transfers(self: BaseServiceTask) -> dict:
    """
    Find and expire pending bank transfer orders past their deadline.

    Queries Directus for pending_bank_transfers with status='pending' and
    expires_at < now(), marks them as 'expired', and cleans up Redis keys.

    Returns:
        Dict with expired_count and any errors
    """
    import asyncio

    async def _run():
        await self.initialize_services()

        directus_service = self.directus_service
        cache_service = self.cache_service

        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            # Query for expired pending orders
            expired_orders = await directus_service.get_items(
                "pending_bank_transfers",
                params={
                    "filter[status][_eq]": "pending",
                    "filter[expires_at][_lt]": now_iso,
                    "limit": 100,
                }
            )

            if not expired_orders:
                logger.info("No expired bank transfer orders found.")
                return {"expired_count": 0}

            expired_count = 0
            errors = []

            for order in expired_orders:
                order_id = order.get("order_id", "")
                reference = order.get("reference", "")

                try:
                    # Update status in Directus
                    await directus_service.update_items(
                        "pending_bank_transfers",
                        params={"filter[order_id][_eq]": order_id},
                        data={"status": "expired"},
                    )

                    # Clean up Redis cache keys
                    await cache_service.delete_bank_transfer_keys(order_id, reference)

                    expired_count += 1
                    logger.info(f"Expired bank transfer order {order_id} (ref: {reference})")

                except Exception as e:
                    error_msg = f"Failed to expire order {order_id}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            logger.info(f"Expired {expired_count}/{len(expired_orders)} bank transfer orders.")
            return {
                "expired_count": expired_count,
                "errors": errors if errors else None,
            }

        except Exception as e:
            logger.error(f"Error in expire_stale_bank_transfers task: {e}", exc_info=True)
            return {"expired_count": 0, "error": str(e)}

    return asyncio.get_event_loop().run_until_complete(_run())
