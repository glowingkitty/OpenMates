# backend/core/api/app/tasks/storage_billing_tasks.py
#
# Weekly Celery Beat task that charges users for S3 file storage.
#
# Billing model:
#   - First 1 GB (FREE_BYTES) is free for every user.
#   - Beyond that: 3 credits per GB per week (CREDITS_PER_GB_PER_WEEK).
#   - Only users with more than 1 GB of stored files are charged.
#
# Billing failure handling:
#   - A per-user storage_billing_failures counter (integer, default 0) is
#     incremented on each insufficient-credits failure.
#   - Week 1 failure: warning email sent.
#   - Week 2 failure: second notice email sent.
#   - Week 3 failure: final warning email sent (files at risk in 7 days).
#   - Week 4 failure: all upload files deleted from S3 + Directus, deletion
#     confirmation email sent, counter reset to 0.
#   - Counter is also reset to 0 on any successful charge.
#   - Users with failure_count > 0 are included in each billing run even if
#     they have since dropped below 1 GB, so the counter can be resolved.
#
# Efficiency and scalability:
#   - Queries upload_files aggregated by user_id directly from Directus.
#   - Filters users below 1 GB at the DB level — only billable/at-risk users
#     are processed.
#   - Processes users in configurable batches with bounded concurrency to
#     prevent overloading the API, cache, or Directus under large user counts.
#   - Each user charge is independent — one failure does not block the rest.
#   - storage_used_bytes on the user is reconciled each run from the real
#     aggregate, correcting any drift from the running counter.
#   - A usage entry is created per charge so users can see storage costs in
#     their activity log (app_id="system", skill_id="storage").
#
# Schedule: every Sunday at 03:00 UTC (celery_config.py beat_schedule).

import asyncio
import hashlib
import logging
import math
import os
import time
from typing import Any, Dict, List, Literal

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.server_stats_service import ServerStatsService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ─── Billing constants ────────────────────────────────────────────────────────

# 1 GB in bytes — storage below this threshold is free
FREE_BYTES: int = 1_073_741_824  # 1 * 1024³

# Credits charged per GB per week above the free tier
CREDITS_PER_GB_PER_WEEK: int = 3

# Processing batch size — how many users are processed in one asyncio gather call
BATCH_SIZE: int = 50

# Charge result type — distinguishes success from insufficient credits vs other errors
ChargeResult = Literal["charged", "insufficient_credits", "error"]

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


async def _send_storage_billing_email(
    user_id: str,
    template: str,
    total_bytes: int,
    credits_needed: int,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    email_template_service: EmailTemplateService,
) -> None:
    """
    Decrypt the user's email address and send a storage billing notification.

    Args:
        user_id:               Plaintext user ID.
        template:              MJML template name (e.g. "storage-billing-failed-1").
        total_bytes:           Total bytes the user currently has stored.
        credits_needed:        Credits per week required to cover their storage.
        directus_service:      Initialised DirectusService.
        encryption_service:    Initialised EncryptionService.
        email_template_service: Initialised EmailTemplateService.
    """
    try:
        # Fetch encrypted email + vault_key_id + preferred language from Directus
        user_records = await directus_service.get_items(
            'directus_users',
            params={
                'filter[id][_eq]': user_id,
                'fields': 'id,encrypted_email_address,vault_key_id,language',
                'limit': 1,
            },
            no_cache=True,
        )
        if not user_records or not isinstance(user_records, list) or not user_records[0]:
            logger.error(
                f"[StorageBilling] Cannot send {template} email for user {user_id}: "
                f"user record not found."
            )
            return

        user_record = user_records[0]
        encrypted_email = user_record.get('encrypted_email_address')
        vault_key_id = user_record.get('vault_key_id')
        language = user_record.get('language') or 'en'

        if not encrypted_email or not vault_key_id:
            logger.error(
                f"[StorageBilling] Cannot send {template} email for user {user_id}: "
                f"missing encrypted_email_address or vault_key_id."
            )
            return

        # Decrypt the email address
        plaintext_email = await encryption_service.decrypt_with_user_key(
            ciphertext=encrypted_email,
            key_id=vault_key_id,
        )
        if not plaintext_email:
            logger.error(
                f"[StorageBilling] Failed to decrypt email for user {user_id}. Skipping {template} email."
            )
            return

        # Build template context
        storage_gb = round(total_bytes / 1_073_741_824, 2)
        base_url = os.getenv("WEBAPP_URL", "https://openmates.org")
        context: Dict[str, Any] = {
            'storage_gb': storage_gb,
            'credits_needed': credits_needed,
            'credits_url': f"{base_url}/settings/billing",
            'darkmode': False,
        }

        success = await email_template_service.send_email(
            template=template,
            recipient_email=plaintext_email,
            context=context,
            lang=language,
        )
        if success:
            logger.info(
                f"[StorageBilling] Sent {template} email to user {user_id} "
                f"({storage_gb} GB, {credits_needed} credits/week)."
            )
        else:
            logger.error(
                f"[StorageBilling] Email send failed for {template} to user {user_id}."
            )

    except Exception as e:
        logger.error(
            f"[StorageBilling] Error sending {template} email for user {user_id}: {e}",
            exc_info=True,
        )


async def _handle_billing_failure(
    user_id: str,
    total_bytes: int,
    current_failure_count: int,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    email_template_service: EmailTemplateService,
    s3_service: S3UploadService,
) -> None:
    """
    Handle a single user's billing failure.

    Increments the storage_billing_failures counter, sends the appropriate
    warning email, and on the 4th consecutive failure deletes all user files.

    Args:
        user_id:               Plaintext user ID.
        total_bytes:           Total bytes the user currently has stored.
        current_failure_count: The current value of storage_billing_failures
                               BEFORE this failure (0-based).
        directus_service:      Initialised DirectusService.
        encryption_service:    Initialised EncryptionService.
        email_template_service: Initialised EmailTemplateService.
        s3_service:            Initialised S3UploadService.
    """
    new_failure_count = current_failure_count + 1
    credits_needed = _compute_billable_credits(total_bytes)

    logger.info(
        f"[StorageBilling] Billing failure #{new_failure_count} for user {user_id} "
        f"({total_bytes:,} bytes, {credits_needed} credits/week needed)."
    )

    if new_failure_count >= 4:
        # ── Nuclear deletion path ──────────────────────────────────────────
        logger.warning(
            f"[StorageBilling] 4th consecutive billing failure for user {user_id}. "
            f"Deleting all upload files."
        )
        try:
            from backend.core.api.app.services.directus.embed_methods import EmbedMethods
            embed_methods = EmbedMethods(directus_service)
            bytes_freed = await embed_methods.delete_all_upload_files_for_user(
                user_id=user_id,
                s3_service=s3_service,
            )
            logger.info(
                f"[StorageBilling] Deleted all files for user {user_id}: "
                f"{bytes_freed:,} bytes freed."
            )
        except Exception as del_err:
            logger.error(
                f"[StorageBilling] File deletion failed for user {user_id}: {del_err}",
                exc_info=True,
            )
            # Still reset counter and send email even if deletion failed —
            # caller will see the error in logs.

        # Reset counter to 0 and reconcile storage bytes to 0
        await directus_service.update_user(
            user_id,
            {
                'storage_billing_failures': 0,
                'storage_used_bytes': 0,
            },
        )

        # Send deletion confirmation email
        await _send_storage_billing_email(
            user_id=user_id,
            template='storage-files-deleted',
            total_bytes=total_bytes,
            credits_needed=credits_needed,
            directus_service=directus_service,
            encryption_service=encryption_service,
            email_template_service=email_template_service,
        )

    else:
        # ── Warning email path ────────────────────────────────────────────
        template_map = {
            1: 'storage-billing-failed-1',
            2: 'storage-billing-failed-2',
            3: 'storage-billing-failed-3',
        }
        template_name = template_map.get(new_failure_count, 'storage-billing-failed-3')

        # Persist the incremented counter
        await directus_service.update_user(
            user_id,
            {'storage_billing_failures': new_failure_count},
        )

        # Send the appropriate warning email
        await _send_storage_billing_email(
            user_id=user_id,
            template=template_name,
            total_bytes=total_bytes,
            credits_needed=credits_needed,
            directus_service=directus_service,
            encryption_service=encryption_service,
            email_template_service=email_template_service,
        )


async def _charge_single_user(
    user_id: str,
    total_bytes: int,
    failure_count: int,
    directus_service: DirectusService,
    cache_service: CacheService,
    encryption_service: EncryptionService,
    billing_service: BillingService,
) -> ChargeResult:
    """
    Charge one user for their weekly storage fees and update their storage counter.

    Steps:
    1. Compute billable credits.
    2. Fetch the user's hashed_email for the usage entry.
    3. Call BillingService.charge_user_credits — this deducts credits, updates
       Directus, broadcasts to WebSocket clients, and creates a usage entry.
    4. Reconcile storage_used_bytes with the real aggregate value.
    5. Reset storage_billing_failures counter to 0 on success.
    6. Update storage_last_billed_at.

    Returns:
        "charged"               — charge succeeded
        "insufficient_credits"  — user has too few credits (billing failure)
        "error"                 — unexpected error (not a billing failure)
    """
    credits = _compute_billable_credits(total_bytes)
    if credits <= 0:
        # User is below or at the free tier — reconcile their counter if needed
        if failure_count > 0:
            # They had failures but now have less than 1 GB — still charge 0
            # but do NOT reset the failure counter (they haven't paid yet).
            # Just update the storage bytes.
            now_ts = int(time.time())
            await directus_service.update_user(
                user_id,
                {
                    'storage_used_bytes': total_bytes,
                    'storage_last_billed_at': now_ts,
                },
            )
        return "charged"

    try:
        # Fetch the user record for vault_key_id (needed by billing)
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
            return "error"

        user_record = user_record_list[0]
        vault_key_id = user_record.get('vault_key_id')
        if not vault_key_id:
            logger.error(
                f"[StorageBilling] Cannot charge user {user_id}: vault_key_id missing."
            )
            return "error"

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

        # Successful charge — reconcile storage counter and reset failure counter
        now_ts = int(time.time())
        update_fields: Dict[str, Any] = {
            'storage_used_bytes': total_bytes,
            'storage_last_billed_at': now_ts,
        }
        if failure_count > 0:
            update_fields['storage_billing_failures'] = 0
            logger.info(
                f"[StorageBilling] Resetting storage_billing_failures to 0 for user {user_id} "
                f"after successful charge."
            )
        await directus_service.update_user(user_id, update_fields)

        # Also update cache so the frontend sees the fresh value immediately
        try:
            cache_update: Dict[str, Any] = {'storage_used_bytes': total_bytes, 'storage_last_billed_at': now_ts}
            if failure_count > 0:
                cache_update['storage_billing_failures'] = 0
            await cache_service.update_user(user_id, cache_update)
        except Exception as cache_err:
            logger.warning(
                f"[StorageBilling] Failed to update cache for user {user_id}: {cache_err}"
            )

        return "charged"

    except Exception as e:
        # BillingService raises an HTTPException (or similar) when the user cannot
        # afford the charge. We detect this by checking if the exception message
        # mentions insufficient credits or by inspecting the HTTP status code.
        # Rather than coupling tightly to the exception class, we check the repr.
        err_str = str(e).lower()
        if 'insufficient' in err_str or 'credits' in err_str or '402' in err_str:
            logger.warning(
                f"[StorageBilling] Insufficient credits for user {user_id}: {e}"
            )
            return "insufficient_credits"

        logger.error(
            f"[StorageBilling] Unexpected error charging user {user_id}: {e}", exc_info=True
        )
        return "error"


async def _async_charge_storage_fees() -> Dict[str, Any]:
    """
    Main async logic for the weekly storage billing run.

    Algorithm:
    1. Aggregate upload_files by user_id to get total bytes per user.
    2. Build two sets:
       a. Users above the free tier (>1 GB) — need billing.
       b. Users with storage_billing_failures > 0 (have prior failures) — need
          failure-state processing even if they have since dropped below 1 GB.
    3. Merge and deduplicate into a single work list.
    4. Process in batches with bounded concurrency (BATCH_SIZE at a time).
    5. For insufficient-credits results, call _handle_billing_failure.
    6. Return a summary dict for logging/monitoring.
    """
    run_start = time.time()
    logger.info("[StorageBilling] Starting weekly storage billing run.")

    secrets_manager = SecretsManager()
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
        'users_deleted': 0,
        'total_credits_charged': 0,
        'duration_seconds': 0.0,
    }

    try:
        await directus_service.ensure_auth_token()
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

        # Initialise S3 service for the deletion path
        s3_service = S3UploadService(secrets_manager=secrets_manager)
        await s3_service.initialize()

        # ──────────────────────────────────────────────────────────────────
        # Step 1: Aggregate upload_files by user_id.
        # ──────────────────────────────────────────────────────────────────
        agg_params = {
            'aggregate[sum]': 'file_size_bytes',
            'groupBy[]': 'user_id',
            'limit': -1,
        }
        aggregate_result = await directus_service.get_items(
            'upload_files', params=agg_params, no_cache=True
        )

        # Build a map: user_id → total_bytes from the aggregate
        bytes_by_user: Dict[str, int] = {}
        if aggregate_result and isinstance(aggregate_result, list):
            for row in aggregate_result:
                uid = row.get('user_id')
                if not uid:
                    continue
                sum_data = row.get('sum') or {}
                total_bytes_raw = (
                    sum_data.get('file_size_bytes') or row.get('file_size_bytes') or 0
                )
                bytes_by_user[uid] = int(total_bytes_raw)

        # ──────────────────────────────────────────────────────────────────
        # Step 2: Find users with existing billing failures (even if now
        # under 1 GB — they still need their failure state resolved).
        # ──────────────────────────────────────────────────────────────────
        failure_users_result = await directus_service.get_items(
            'directus_users',
            params={
                'filter[storage_billing_failures][_gt]': 0,
                'fields': 'id,storage_billing_failures',
                'limit': -1,
            },
            no_cache=True,
        )
        failure_count_by_user: Dict[str, int] = {}
        if failure_users_result and isinstance(failure_users_result, list):
            for row in failure_users_result:
                uid = row.get('id')
                if uid:
                    failure_count_by_user[uid] = int(row.get('storage_billing_failures') or 0)

        # ──────────────────────────────────────────────────────────────────
        # Step 3: Build the work list — union of billable users and users
        # with active failure counters.
        # ──────────────────────────────────────────────────────────────────
        all_user_ids: set = set()
        for uid, tbytes in bytes_by_user.items():
            if tbytes > FREE_BYTES or uid in failure_count_by_user:
                all_user_ids.add(uid)
        for uid in failure_count_by_user:
            all_user_ids.add(uid)

        work_list: List[tuple] = []
        for uid in all_user_ids:
            tbytes = bytes_by_user.get(uid, 0)
            fc = failure_count_by_user.get(uid, 0)
            work_list.append((uid, tbytes, fc))
            summary['users_checked'] += 1

        logger.info(
            f"[StorageBilling] {len(bytes_by_user)} users have stored files; "
            f"{len(failure_count_by_user)} have active failure counters; "
            f"{len(work_list)} users to process."
        )

        if not work_list:
            logger.info("[StorageBilling] No users to process. Billing complete.")
            return summary

        # ──────────────────────────────────────────────────────────────────
        # Step 4: Process in batches with bounded concurrency.
        # ──────────────────────────────────────────────────────────────────
        for batch_start in range(0, len(work_list), BATCH_SIZE):
            batch = work_list[batch_start: batch_start + BATCH_SIZE]

            charge_tasks = [
                _charge_single_user(
                    user_id=uid,
                    total_bytes=tbytes,
                    failure_count=fc,
                    directus_service=directus_service,
                    cache_service=cache_service,
                    encryption_service=encryption_service,
                    billing_service=billing_service,
                )
                for uid, tbytes, fc in batch
            ]
            results = await asyncio.gather(*charge_tasks, return_exceptions=True)

            # Process results and handle failures
            failure_tasks = []
            failure_task_users = []
            for (uid, tbytes, fc), result in zip(batch, results):
                credits = _compute_billable_credits(tbytes)
                if isinstance(result, Exception):
                    logger.error(
                        f"[StorageBilling] Batch error for user {uid}: {result}",
                        exc_info=False,
                    )
                    summary['users_failed'] += 1
                elif result == "charged":
                    if credits > 0:
                        summary['users_billed'] += 1
                        summary['total_credits_charged'] += credits
                elif result == "insufficient_credits":
                    summary['users_failed'] += 1
                    failure_tasks.append(
                        _handle_billing_failure(
                            user_id=uid,
                            total_bytes=tbytes,
                            current_failure_count=fc,
                            directus_service=directus_service,
                            encryption_service=encryption_service,
                            email_template_service=email_template_service,
                            s3_service=s3_service,
                        )
                    )
                    failure_task_users.append((uid, fc))
                else:  # "error"
                    summary['users_failed'] += 1

            # Run all failure handlers concurrently (within this batch)
            if failure_tasks:
                failure_results = await asyncio.gather(*failure_tasks, return_exceptions=True)
                for (uid, fc), fresult in zip(failure_task_users, failure_results):
                    if isinstance(fresult, Exception):
                        logger.error(
                            f"[StorageBilling] Error in billing failure handler for user {uid}: {fresult}",
                            exc_info=False,
                        )
                    elif fc >= 3:
                        # fc was 3 before this run → this was the 4th failure → deletion occurred
                        summary['users_deleted'] += 1

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
            f"Deleted: {summary['users_deleted']}, "
            f"Total credits charged: {summary['total_credits_charged']}."
        )
        return summary

    except Exception as e:
        logger.error(
            f"[StorageBilling] Fatal error in billing run: {e}", exc_info=True
        )
        raise

    finally:
        # Always close the SecretsManager httpx client to avoid event-loop errors
        try:
            await secrets_manager.aclose()
        except Exception:
            pass


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

    On repeated billing failures (insufficient credits):
      - Sends escalating warning emails at weeks 1, 2, and 3.
      - On the 4th consecutive failure, permanently deletes all upload files
        and sends a deletion confirmation email.

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
