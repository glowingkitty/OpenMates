# backend/core/api/app/tasks/storage_billing_tasks.py
#
# Weekly Celery Beat task that charges users for S3 file storage.
#
# Billing model:
#   - First 1 GB (FREE_BYTES) is free for every user.
#   - Beyond that: 3 credits per GB per week (CREDITS_PER_GB_PER_WEEK).
#   - Only users with more than 1 GB of stored files are charged.
#   - Hetzner costs us ≈ €0.005/GB/month; at 3 credits/GB/week (~12 credits/GB/month,
#     or $0.012/GB/month) we have a healthy margin above cost.
#
# Efficiency and scalability:
#   - Queries upload_files aggregated by user_id directly from Directus (one DB call).
#   - Filters users below 1 GB at the DB level — only billable users are processed.
#   - Processes users in configurable batches with bounded concurrency to prevent
#     overloading the API, cache, or Directus under large user counts.
#   - Each user charge is independent — one failure does not block the rest.
#   - storage_used_bytes on the user is reconciled each run from the real aggregate,
#     correcting any drift from the running counter (increments/decrements).
#   - A usage entry is created per charge so users can see storage costs in their
#     activity log (app_id="system", skill_id="storage").
#
# Schedule: every Sunday at 03:00 UTC (celery_config.py beat_schedule).

import asyncio
import logging
import math
import time
from typing import Any, Dict, List

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.server_stats_service import ServerStatsService

logger = logging.getLogger(__name__)

# ─── Billing constants ────────────────────────────────────────────────────────

# 1 GB in bytes — storage below this threshold is free
FREE_BYTES: int = 1_073_741_824  # 1 * 1024³

# Credits charged per GB per week above the free tier
CREDITS_PER_GB_PER_WEEK: int = 3

# Processing batch size — how many users are processed in one asyncio gather call
BATCH_SIZE: int = 50

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _compute_billable_credits(total_bytes: int) -> int:
    """
    Return the number of credits to charge for a given storage volume.

    Billing formula:
      billable_gb = ceil((total_bytes - FREE_BYTES) / 1_073_741_824)
      credits     = billable_gb * CREDITS_PER_GB_PER_WEEK

    Examples:
      1.0 GB → 0 credits   (within free tier)
      1.1 GB → 3 credits   (1 GB over free tier, ceil → 1 billable GB)
      2.5 GB → 6 credits   (1.5 GB over free, ceil → 2 billable GB)
      10 GB  → 27 credits  (9 GB over free, ceil → 9 billable GB)
    """
    if total_bytes <= FREE_BYTES:
        return 0
    billable_bytes = total_bytes - FREE_BYTES
    billable_gb = math.ceil(billable_bytes / 1_073_741_824)
    return billable_gb * CREDITS_PER_GB_PER_WEEK


async def _charge_single_user(
    user_id: str,
    total_bytes: int,
    directus_service: DirectusService,
    cache_service: CacheService,
    encryption_service: EncryptionService,
    billing_service: BillingService,
) -> bool:
    """
    Charge one user for their weekly storage fees and update their storage counter.

    Steps:
    1. Compute billable credits.
    2. Fetch the user's hashed_user_id for the usage entry.
    3. Call BillingService.charge_user_credits — this deducts credits, updates
       Directus, broadcasts to WebSocket clients, and creates a usage entry.
    4. Reconcile storage_used_bytes with the real aggregate value.
    5. Update storage_last_billed_at.

    Returns True on success, False on failure.
    """
    credits = _compute_billable_credits(total_bytes)
    if credits <= 0:
        # Should not happen (callers filter <1 GB), but guard defensively.
        return True

    try:
        # Fetch the user record for vault_key_id (needed by billing) and hashed user id
        user_record_list = await directus_service.get_items(
            'directus_users',
            params={
                'filter[id][_eq]': user_id,
                'fields': 'id,vault_key_id,hashed_email',
                'limit': 1,
            },
            no_cache=True,
        )
        if not user_record_list or not isinstance(user_record_list, list):
            logger.error(
                f"[StorageBilling] Cannot charge user {user_id}: user record not found in Directus."
            )
            return False

        user_record = user_record_list[0]
        vault_key_id = user_record.get('vault_key_id')
        if not vault_key_id:
            logger.error(
                f"[StorageBilling] Cannot charge user {user_id}: vault_key_id missing."
            )
            return False

        # Build a SHA-256 hash of the user_id to use as user_id_hash for the usage entry.
        import hashlib
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

        billable_gb = math.ceil((total_bytes - FREE_BYTES) / 1_073_741_824)

        # Charge the user. BillingService also creates a usage entry automatically.
        await billing_service.charge_user_credits(
            user_id=user_id,
            credits_to_deduct=credits,
            user_id_hash=user_id_hash,
            app_id="system",
            skill_id="storage",
            usage_details={
                "storage_bytes": total_bytes,
                "billable_gb": billable_gb,
                "free_gb": 1,
                "credits_per_gb": CREDITS_PER_GB_PER_WEEK,
            },
        )

        logger.info(
            f"[StorageBilling] Charged user {user_id}: {credits} credits "
            f"({billable_gb} billable GB, {total_bytes:,} bytes total)."
        )

        # Reconcile storage_used_bytes (corrects any counter drift)
        now_ts = int(time.time())
        await directus_service.update_user(
            user_id,
            {
                'storage_used_bytes': total_bytes,
                'storage_last_billed_at': now_ts,
            },
        )
        # Also update cache so the frontend sees the fresh value immediately
        try:
            await cache_service.update_user(
                user_id,
                {
                    'storage_used_bytes': total_bytes,
                    'storage_last_billed_at': now_ts,
                },
            )
        except Exception as cache_err:
            logger.warning(
                f"[StorageBilling] Failed to update cache for user {user_id}: {cache_err}"
            )

        return True

    except Exception as e:
        logger.error(
            f"[StorageBilling] Failed to charge user {user_id}: {e}", exc_info=True
        )
        return False


async def _async_charge_storage_fees() -> Dict[str, Any]:
    """
    Main async logic for the weekly storage billing run.

    Algorithm:
    1. Aggregate upload_files by user_id to get total bytes per user.
    2. Filter to only users over the free tier (>1 GB).
    3. Process in batches with bounded concurrency (BATCH_SIZE at a time).
    4. Return a summary dict for logging/monitoring.
    """
    run_start = time.time()
    logger.info("[StorageBilling] Starting weekly storage billing run.")

    directus_service = DirectusService()
    cache_service = CacheService()
    encryption_service = EncryptionService()
    server_stats_service = ServerStatsService(cache_service, directus_service)
    billing_service = BillingService(
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
        server_stats_service=server_stats_service,
    )

    summary: Dict[str, Any] = {
        'users_checked': 0,
        'users_billed': 0,
        'users_failed': 0,
        'total_credits_charged': 0,
        'duration_seconds': 0.0,
    }

    try:
        await directus_service.ensure_auth_token()

        # ──────────────────────────────────────────────────────────────────────
        # Step 1: Aggregate upload_files by user_id.
        # Directus supports aggregation via ?aggregate[sum]=field&groupBy[]=field.
        # We request the total file_size_bytes per user_id.
        # ──────────────────────────────────────────────────────────────────────
        agg_params = {
            'aggregate[sum]': 'file_size_bytes',
            'groupBy[]': 'user_id',
            'limit': -1,
        }
        aggregate_result = await directus_service.get_items(
            'upload_files', params=agg_params, no_cache=True
        )

        if not aggregate_result or not isinstance(aggregate_result, list):
            logger.info("[StorageBilling] No upload_files records found. Nothing to charge.")
            return summary

        # ──────────────────────────────────────────────────────────────────────
        # Step 2: Filter to users above the free tier.
        # ──────────────────────────────────────────────────────────────────────
        billable_users: List[tuple[str, int]] = []
        for row in aggregate_result:
            user_id = row.get('user_id')
            # Directus returns aggregate results under a nested 'sum' key
            sum_data = row.get('sum') or {}
            total_bytes_raw = sum_data.get('file_size_bytes') or row.get('file_size_bytes') or 0
            total_bytes = int(total_bytes_raw)

            if not user_id:
                continue

            summary['users_checked'] += 1

            if total_bytes > FREE_BYTES:
                billable_users.append((user_id, total_bytes))

        logger.info(
            f"[StorageBilling] {summary['users_checked']} users checked, "
            f"{len(billable_users)} users above free tier."
        )

        if not billable_users:
            logger.info("[StorageBilling] No users above free tier. Billing complete.")
            return summary

        # ──────────────────────────────────────────────────────────────────────
        # Step 3: Process in batches with bounded concurrency.
        # Each gather call processes up to BATCH_SIZE users in parallel.
        # ──────────────────────────────────────────────────────────────────────
        for batch_start in range(0, len(billable_users), BATCH_SIZE):
            batch = billable_users[batch_start: batch_start + BATCH_SIZE]

            tasks = [
                _charge_single_user(
                    user_id=uid,
                    total_bytes=tbytes,
                    directus_service=directus_service,
                    cache_service=cache_service,
                    encryption_service=encryption_service,
                    billing_service=billing_service,
                )
                for uid, tbytes in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (uid, tbytes), result in zip(batch, results):
                credits = _compute_billable_credits(tbytes)
                if isinstance(result, Exception):
                    logger.error(
                        f"[StorageBilling] Batch error for user {uid}: {result}", exc_info=False
                    )
                    summary['users_failed'] += 1
                elif result is True:
                    summary['users_billed'] += 1
                    summary['total_credits_charged'] += credits
                else:
                    summary['users_failed'] += 1

            logger.info(
                f"[StorageBilling] Batch {batch_start // BATCH_SIZE + 1}: "
                f"processed {len(batch)} users."
            )

        elapsed = time.time() - run_start
        summary['duration_seconds'] = round(elapsed, 2)

        logger.info(
            f"[StorageBilling] Weekly billing run complete in {elapsed:.1f}s. "
            f"Billed: {summary['users_billed']}, "
            f"Failed: {summary['users_failed']}, "
            f"Total credits charged: {summary['total_credits_charged']}."
        )
        return summary

    except Exception as e:
        logger.error(
            f"[StorageBilling] Fatal error in billing run: {e}", exc_info=True
        )
        raise


# ─── Celery task wrapper ───────────────────────────────────────────────────────


@app.task(
    name="app.tasks.storage_billing_tasks.charge_storage_fees",
    bind=True,
    max_retries=1,
    default_retry_delay=300,  # 5-minute delay before retrying on catastrophic failure
)
def charge_storage_fees(self) -> Dict[str, Any]:
    """
    Celery Beat task — runs every Sunday at 03:00 UTC.

    Charges users 3 credits per GB per week for S3 file storage above the
    1 GB free tier. Each charge creates a usage entry (app_id='system',
    skill_id='storage') so users can see the charge in their activity log.

    Processes users in batches (BATCH_SIZE=50 at a time) for scalability.
    A single user failure does not block other users from being billed.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN'
    logger.info(f"[StorageBilling] Task started. task_id={task_id}")

    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_charge_storage_fees())
        logger.info(f"[StorageBilling] Task completed. Summary: {result}")
        return result
    except Exception as e:
        logger.error(
            f"[StorageBilling] Task failed. task_id={task_id}: {e}", exc_info=True
        )
        raise self.retry(exc=e)
    finally:
        if loop:
            loop.close()
