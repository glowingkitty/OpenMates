# backend/core/api/app/tasks/auto_delete_tasks.py
#
# Daily Celery Beat tasks for automatic deletion of stale data.
#
# ─── Task 1: auto_delete_old_chats ───────────────────────────────────────────
# Deletes old chats for users who have configured a retention period via
# Privacy → Auto Deletion → Chats.
#
# How it works:
#   - Users can set auto_delete_chats_after_days via POST /v1/settings/auto-delete-chats.
#   - This task runs daily at 02:30 UTC and queries for all users who have a
#     non-null value for that field.
#   - For each such user, it finds chats whose last_message_timestamp is older
#     than the configured retention period.
#   - Stale chats are passed to the existing persist_delete_chat Celery task,
#     which handles the full deletion pipeline:
#       drafts → messages → embeds (incl. shared embeds no longer needed) →
#       S3 files → upload_files records → storage counter update → chat record.
#
# Scalability and rate-limiting:
#   - Users are processed one at a time (not in parallel) to avoid thundering-herd.
#   - At most MAX_CHATS_PER_USER_PER_RUN chats are scheduled per user per run.
#     If a user has more stale chats, the remainder are caught the following day.
#   - Each chat deletion is dispatched as an independent Celery task, distributing
#     load across the persistence queue workers over time.
#
# Schedule: every day at 02:30 UTC (celery_config.py beat_schedule).
#
# ─── Task 2: auto_delete_old_issues ──────────────────────────────────────────
# Deletes all issue reports older than ISSUE_RETENTION_DAYS (14 days).
#
# How it works:
#   - This is a system-level policy — no per-user preference is required.
#   - The task runs daily at 03:00 UTC (staggered from chat auto-delete).
#   - It queries Directus for all issues whose created_at is older than the
#     retention cutoff.
#   - For each stale issue, it performs a full deletion:
#       1. Decrypt and delete the YAML report from S3 (if present)
#       2. Decrypt and delete the screenshot PNG from S3 (if present)
#       3. Delete the Directus record
#   - S3 failures are logged and skipped (do not abort the Directus delete).
#   - Issues are processed in batches of MAX_ISSUES_PER_RUN to limit system
#     load; remaining issues are handled in the next daily run.
#
# Architecture notes:
#   - S3 keys stored in Directus are Vault-encrypted; they must be decrypted
#     via EncryptionService before being passed to S3.
#   - The same deletion logic is used by inspect_issue.py --delete and the
#     DELETE /v1/admin/debug/issues/{id} REST endpoint.
#   - The S3 bucket already has a 365-day lifecycle policy. This task ensures
#     that both the Directus record AND the S3 objects are cleaned up at 14
#     days instead of waiting for S3 auto-expiry (which leaves orphaned DB rows).
#
# Schedule: every day at 03:00 UTC (celery_config.py beat_schedule).
#
# ─── Task 3: auto_delete_old_usage ───────────────────────────────────────────
# Permanently deletes usage records that have exceeded the user's configured
# retention period (default: 3 years / 1095 days).
#
# Relationship to the usage archive task:
#   - The existing monthly usage_archive task (usage.archive_old_entries) moves
#     usage records older than 3 months from Directus to S3 (compressed JSON).
#     This is a performance measure — it keeps Directus lean.
#   - THIS task is different: it permanently deletes BOTH the Directus record
#     (if still present) AND the corresponding S3 archive file for entries that
#     have exceeded the user-configured retention period.
#   - The two tasks complement each other: archive task compresses old records
#     quickly; this task permanently purges them after the retention window.
#
# How it works:
#   - Users can set auto_delete_usage_after_days via POST /v1/settings/auto-delete-usage.
#   - Null means apply the platform default (USAGE_DEFAULT_RETENTION_DAYS = 1095 days).
#   - This task runs daily at 03:30 UTC (staggered from other auto-delete tasks).
#   - For each user, it:
#       1. Deletes Directus usage records older than the cutoff (the archive task
#          may have already removed most of them, but any not yet archived are caught here).
#       2. Finds and deletes S3 usage archive files for months older than the cutoff.
#          S3 archives use key pattern: usage-archives/{user_id_hash}/{year-month}/usage.json.gz
#   - Rate-limited to MAX_USAGE_USERS_PER_RUN users per run.
#
# Schedule: every day at 03:30 UTC (celery_config.py beat_schedule).

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ─── Rate-limit constants ─────────────────────────────────────────────────────

# Maximum number of chats to schedule for deletion per user per daily run.
# If a user has more stale chats they will be handled over subsequent runs.
MAX_CHATS_PER_USER_PER_RUN: int = 100

# Maximum number of issues to delete per daily run.
# Issue volume is much lower than chats — 200 is a safe upper bound.
# If more stale issues exist they will be caught on subsequent runs.
MAX_ISSUES_PER_RUN: int = 200

# System-level retention period for issue reports (in days).
# Issues older than this are unconditionally deleted (Directus + S3).
ISSUE_RETENTION_DAYS: int = 14

# Maximum number of users to process per usage auto-delete daily run.
MAX_USAGE_USERS_PER_RUN: int = 500

# Maximum number of Directus usage records to delete per user per run.
# The archive task handles most records; this catches any left behind.
MAX_USAGE_RECORDS_PER_USER_PER_RUN: int = 1000

# Platform default retention for usage records when the user has not configured a period.
# Matches USAGE_DEFAULT_RETENTION_DAYS in backend/core/api/app/schemas/settings.py.
USAGE_DEFAULT_RETENTION_DAYS: int = 1095  # 3 years

# ─── Core logic ──────────────────────────────────────────────────────────────


async def _process_auto_delete_for_user(
    user_id: str,
    cutoff_ts: int,
    directus_service: DirectusService,
) -> int:
    """
    Find and schedule deletion for stale chats belonging to one user.

    Args:
        user_id:           Plaintext user ID.
        cutoff_ts:         Unix timestamp; chats last updated before this are stale.
        directus_service:  Authenticated Directus service.

    Returns:
        Number of chats scheduled for deletion.
    """
    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()

    # Query chats that belong to this user and haven't had any message since cutoff.
    # We use last_message_timestamp (most recent completed message) as the primary
    # staleness signal. We fall back to last_edited_overall_timestamp to catch
    # chats that were opened but never sent a message (draft-only chats).
    params = {
        'filter[hashed_user_id][_eq]': hashed_user_id,
        # Chat must be stale by BOTH message and edit timestamps (more conservative).
        # Using _lt (less than) on the cutoff so we only delete genuinely old chats.
        'filter[last_message_timestamp][_lt]': cutoff_ts,
        'filter[last_message_timestamp][_nnull]': True,  # Must have at least one message
        'fields': 'id',
        'limit': MAX_CHATS_PER_USER_PER_RUN,
        'sort': 'last_message_timestamp',  # oldest first
    }

    stale_chats = await directus_service.get_items('chats', params=params, no_cache=True)

    if not stale_chats or not isinstance(stale_chats, list):
        return 0

    chat_ids = [c.get('id') for c in stale_chats if c.get('id')]
    if not chat_ids:
        return 0

    # Dispatch persist_delete_chat for each stale chat.
    # We use the existing Celery task so the full deletion pipeline runs
    # (embeds, S3, upload_files, storage counter update).
    for chat_id in chat_ids:
        try:
            app.send_task(
                'app.tasks.persistence_tasks.persist_delete_chat',
                kwargs={'user_id': user_id, 'chat_id': chat_id},
                queue='persistence',
            )
        except Exception as dispatch_err:
            logger.error(
                f"[AutoDelete] Failed to dispatch deletion for chat {chat_id} "
                f"(user {user_id[:8]}...): {dispatch_err}"
            )

    logger.info(
        f"[AutoDelete] Scheduled {len(chat_ids)} chat(s) for deletion "
        f"for user {user_id[:8]}... (cutoff: {cutoff_ts})."
    )
    return len(chat_ids)


async def _async_auto_delete_old_chats() -> Dict[str, Any]:
    """
    Main async logic for the daily auto-delete run.

    1. Query all users who have auto_delete_chats_after_days set.
    2. For each user, compute the cutoff timestamp and dispatch deletions.
    3. Return a summary dict for logging/monitoring.
    """
    run_start = time.time()
    logger.info("[AutoDelete] Starting daily auto-delete run.")

    directus_service = DirectusService()

    summary: Dict[str, Any] = {
        'users_processed': 0,
        'chats_scheduled': 0,
        'users_failed': 0,
        'duration_seconds': 0.0,
    }

    try:
        await directus_service.ensure_auth_token()

        # Fetch all users with a non-null auto_delete_chats_after_days.
        # We only need id and auto_delete_chats_after_days.
        params = {
            'filter[auto_delete_chats_after_days][_nnull]': True,
            'fields': 'id,auto_delete_chats_after_days',
            'limit': -1,
        }
        users_with_auto_delete = await directus_service.get_items(
            'directus_users', params=params, no_cache=True
        )

        if not users_with_auto_delete or not isinstance(users_with_auto_delete, list):
            logger.info("[AutoDelete] No users with auto-delete configured. Nothing to do.")
            return summary

        logger.info(
            f"[AutoDelete] Found {len(users_with_auto_delete)} user(s) "
            f"with auto-delete configured."
        )

        now_ts = int(time.time())

        for user_record in users_with_auto_delete:
            user_id = user_record.get('id')
            days = user_record.get('auto_delete_chats_after_days')

            if not user_id or not days or int(days) <= 0:
                continue

            cutoff_ts = now_ts - int(days) * 86400  # seconds per day

            try:
                chats_scheduled = await _process_auto_delete_for_user(
                    user_id=user_id,
                    cutoff_ts=cutoff_ts,
                    directus_service=directus_service,
                )
                summary['users_processed'] += 1
                summary['chats_scheduled'] += chats_scheduled
            except Exception as user_err:
                logger.error(
                    f"[AutoDelete] Error processing user {user_id[:8]}...: {user_err}",
                    exc_info=True,
                )
                summary['users_failed'] += 1

        elapsed = time.time() - run_start
        summary['duration_seconds'] = round(elapsed, 2)

        logger.info(
            f"[AutoDelete] Daily run complete in {elapsed:.1f}s. "
            f"Users processed: {summary['users_processed']}, "
            f"Chats scheduled: {summary['chats_scheduled']}, "
            f"Failures: {summary['users_failed']}."
        )
        return summary

    except Exception as e:
        logger.error(f"[AutoDelete] Fatal error in auto-delete run: {e}", exc_info=True)
        raise


# ─── Celery task wrapper ──────────────────────────────────────────────────────


@app.task(
    name="app.tasks.auto_delete_tasks.auto_delete_old_chats",
    bind=True,
    max_retries=1,
    default_retry_delay=600,  # 10-minute delay before retry on catastrophic failure
)
def auto_delete_old_chats(self) -> Dict[str, Any]:
    """
    Celery Beat task — runs every day at 02:30 UTC.

    For each user who has configured a chat retention period, finds chats
    older than the retention window (based on last_message_timestamp) and
    dispatches persist_delete_chat for each one.

    At most MAX_CHATS_PER_USER_PER_RUN (100) chats are scheduled per user per
    day to limit system load. Remaining stale chats are caught the next day.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN'
    logger.info(f"[AutoDelete] Task started. task_id={task_id}")

    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_auto_delete_old_chats())
        logger.info(f"[AutoDelete] Task completed. Summary: {result}")
        return result
    except Exception as e:
        logger.error(
            f"[AutoDelete] Task failed. task_id={task_id}: {e}", exc_info=True
        )
        raise self.retry(exc=e)
    finally:
        if loop:
            loop.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Issue auto-delete
# ═══════════════════════════════════════════════════════════════════════════════


async def _delete_issue_s3_files(
    issue: Dict[str, Any],
    encryption_service: EncryptionService,
    s3_service: S3UploadService,
) -> int:
    """
    Delete all S3 files associated with an issue (YAML report + screenshot).

    Failures are logged as warnings but do NOT raise — the caller should still
    proceed with deleting the Directus record so we don't leave orphaned DB rows.

    Args:
        issue:              Raw Directus issue record.
        encryption_service: Initialized EncryptionService (for decrypting S3 keys).
        s3_service:         Initialized S3UploadService.

    Returns:
        Number of S3 files successfully deleted (0, 1, or 2).
    """
    deleted = 0

    # Delete encrypted YAML report (issue-reports/…yaml.encrypted)
    yaml_key_enc = issue.get("encrypted_issue_report_yaml_s3_key")
    if yaml_key_enc:
        try:
            s3_key = await encryption_service.decrypt_issue_report_data(yaml_key_enc)
            if s3_key:
                await s3_service.delete_file(bucket_key="issue_logs", file_key=s3_key)
                deleted += 1
                logger.info(
                    f"[IssueAutoDelete] Deleted S3 YAML for issue {issue.get('id')}: {s3_key}"
                )
        except Exception as exc:
            logger.warning(
                f"[IssueAutoDelete] Failed to delete S3 YAML for issue "
                f"{issue.get('id')}: {exc}"
            )

    # Delete screenshot PNG (issue-screenshots/….png)
    screenshot_key_enc = issue.get("encrypted_screenshot_s3_key")
    if screenshot_key_enc:
        try:
            s3_key = await encryption_service.decrypt_issue_report_data(screenshot_key_enc)
            if s3_key:
                await s3_service.delete_file(bucket_key="issue_logs", file_key=s3_key)
                deleted += 1
                logger.info(
                    f"[IssueAutoDelete] Deleted S3 screenshot for issue {issue.get('id')}: {s3_key}"
                )
        except Exception as exc:
            logger.warning(
                f"[IssueAutoDelete] Failed to delete S3 screenshot for issue "
                f"{issue.get('id')}: {exc}"
            )

    return deleted


async def _async_auto_delete_old_issues() -> Dict[str, Any]:
    """
    Main async logic for the daily issue auto-delete run.

    1. Query Directus for all issues whose created_at is older than
       ISSUE_RETENTION_DAYS (14 days), up to MAX_ISSUES_PER_RUN per run.
    2. For each stale issue:
       a. Delete the YAML report from S3 (if the encrypted key is present).
       b. Delete the screenshot PNG from S3 (if the encrypted key is present).
       c. Delete the Directus record.
    3. Return a summary dict for logging/monitoring.

    S3 deletion failures are treated as warnings — the Directus record is
    deleted regardless so orphaned rows don't accumulate. Any S3 objects that
    were not deleted will be caught by the bucket's 365-day lifecycle policy.
    """
    run_start = time.time()
    logger.info("[IssueAutoDelete] Starting daily issue auto-delete run.")

    summary: Dict[str, Any] = {
        'issues_found': 0,
        'issues_deleted': 0,
        'issues_failed': 0,
        's3_files_deleted': 0,
        'duration_seconds': 0.0,
    }

    directus_service: Optional[DirectusService] = None
    encryption_service: Optional[EncryptionService] = None
    s3_service: Optional[S3UploadService] = None
    secrets_manager: Optional[SecretsManager] = None

    try:
        # ── Initialize services ────────────────────────────────────────────────
        directus_service = DirectusService()
        await directus_service.ensure_auth_token()

        encryption_service = EncryptionService()

        secrets_manager = SecretsManager()
        await secrets_manager.initialize()

        s3_service = S3UploadService(secrets_manager=secrets_manager)
        await s3_service.initialize()

        # ── Compute cutoff timestamp ───────────────────────────────────────────
        # Directus stores created_at as ISO 8601 strings. We use _lt (less than)
        # on a UTC ISO timestamp to find issues created before the cutoff.
        cutoff_dt = datetime.fromtimestamp(
            time.time() - ISSUE_RETENTION_DAYS * 86400, tz=timezone.utc
        )
        cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S")

        # ── Fetch stale issues ─────────────────────────────────────────────────
        params: Dict[str, Any] = {
            'filter[created_at][_lt]': cutoff_iso,
            'fields': (
                'id,'
                'encrypted_issue_report_yaml_s3_key,'
                'encrypted_screenshot_s3_key'
            ),
            'limit': MAX_ISSUES_PER_RUN,
            'sort': 'created_at',  # oldest first
        }
        stale_issues: List[Dict[str, Any]] = await directus_service.get_items(
            'issues', params=params, no_cache=True, admin_required=True
        )

        if not stale_issues or not isinstance(stale_issues, list):
            logger.info("[IssueAutoDelete] No stale issues found. Nothing to do.")
            return summary

        summary['issues_found'] = len(stale_issues)
        logger.info(
            f"[IssueAutoDelete] Found {len(stale_issues)} issue(s) older than "
            f"{ISSUE_RETENTION_DAYS} days (cutoff: {cutoff_iso})."
        )

        # ── Delete each stale issue ────────────────────────────────────────────
        for issue in stale_issues:
            issue_id: Optional[str] = issue.get('id')
            if not issue_id:
                continue

            try:
                # 1 & 2. Delete S3 files (YAML + screenshot). Failures are warnings.
                s3_deleted = await _delete_issue_s3_files(
                    issue=issue,
                    encryption_service=encryption_service,
                    s3_service=s3_service,
                )
                summary['s3_files_deleted'] += s3_deleted

                # 3. Delete Directus record. This is the authoritative step.
                success = await directus_service.delete_item(
                    'issues', issue_id, admin_required=True
                )
                if not success:
                    logger.error(
                        f"[IssueAutoDelete] Directus delete returned False for "
                        f"issue {issue_id}. Skipping."
                    )
                    summary['issues_failed'] += 1
                    continue

                summary['issues_deleted'] += 1
                logger.debug(f"[IssueAutoDelete] Deleted issue {issue_id}.")

            except Exception as issue_err:
                logger.error(
                    f"[IssueAutoDelete] Error deleting issue {issue_id}: {issue_err}",
                    exc_info=True,
                )
                summary['issues_failed'] += 1

        elapsed = time.time() - run_start
        summary['duration_seconds'] = round(elapsed, 2)

        logger.info(
            f"[IssueAutoDelete] Daily run complete in {elapsed:.1f}s. "
            f"Found: {summary['issues_found']}, "
            f"Deleted: {summary['issues_deleted']}, "
            f"S3 files deleted: {summary['s3_files_deleted']}, "
            f"Failures: {summary['issues_failed']}."
        )
        return summary

    except Exception as e:
        logger.error(
            f"[IssueAutoDelete] Fatal error in issue auto-delete run: {e}",
            exc_info=True,
        )
        raise

    finally:
        # Clean up httpx / Redis clients to prevent "event loop is closed" errors
        # on subsequent Celery task runs within the same worker process.
        if secrets_manager is not None:
            try:
                await secrets_manager.aclose()
            except Exception:
                pass
        if directus_service is not None and hasattr(directus_service, 'close'):
            try:
                await directus_service.close()
            except Exception:
                pass


# ─── Celery task wrapper ──────────────────────────────────────────────────────


@app.task(
    name="app.tasks.auto_delete_tasks.auto_delete_old_issues",
    bind=True,
    max_retries=1,
    default_retry_delay=600,  # 10-minute retry delay on catastrophic failure
)
def auto_delete_old_issues(self) -> Dict[str, Any]:
    """
    Celery Beat task — runs every day at 03:00 UTC.

    Deletes all issue reports older than ISSUE_RETENTION_DAYS (14 days).
    Each deletion removes:
      - The encrypted YAML report from S3 (issue-reports/…)
      - The screenshot PNG from S3 (issue-screenshots/…)
      - The Directus record from the issues collection

    At most MAX_ISSUES_PER_RUN (200) issues are deleted per run.
    Remaining stale issues are caught the next day.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN'
    logger.info(f"[IssueAutoDelete] Task started. task_id={task_id}")

    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_auto_delete_old_issues())
        logger.info(f"[IssueAutoDelete] Task completed. Summary: {result}")
        return result
    except Exception as e:
        logger.error(
            f"[IssueAutoDelete] Task failed. task_id={task_id}: {e}", exc_info=True
        )
        raise self.retry(exc=e)
    finally:
        if loop:
            loop.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Usage record auto-delete (Task 3)
# ═══════════════════════════════════════════════════════════════════════════════


async def _async_auto_delete_old_usage() -> Dict[str, Any]:
    """
    Main async logic for the daily usage record auto-delete run.

    For each user (with or without a custom period), permanently deletes:
      1. Directus usage records older than the retention cutoff.
      2. S3 usage archive files (usage-archives/{hash}/{year-month}/usage.json.gz)
         for months older than the cutoff.

    The usage archive task (usage.archive_old_entries) moves records to S3 after
    3 months. This task handles permanent deletion after the full retention period.

    Users with null auto_delete_usage_after_days use USAGE_DEFAULT_RETENTION_DAYS.
    """
    run_start = time.time()
    logger.info("[UsageAutoDelete] Starting daily usage auto-delete run.")

    directus_service: Optional[DirectusService] = None
    s3_service: Optional[S3UploadService] = None
    secrets_manager: Optional[SecretsManager] = None

    summary: Dict[str, Any] = {
        'users_processed': 0,
        'directus_records_deleted': 0,
        's3_files_deleted': 0,
        'users_failed': 0,
        'duration_seconds': 0.0,
    }

    try:
        directus_service = DirectusService()
        await directus_service.ensure_auth_token()

        secrets_manager = SecretsManager()
        await secrets_manager.initialize()

        s3_service = S3UploadService(secrets_manager=secrets_manager)
        await s3_service.initialize()

        # ── Fetch all users (process ALL users — those without a custom period
        # also need the platform-default 3-year purge applied) ─────────────────
        users_params = {
            'fields': 'id,auto_delete_usage_after_days',
            'limit': MAX_USAGE_USERS_PER_RUN,
        }
        users = await directus_service.get_items('directus_users', params=users_params, no_cache=True)

        if not users or not isinstance(users, list):
            logger.info("[UsageAutoDelete] No users found. Nothing to do.")
            return summary

        logger.info(f"[UsageAutoDelete] Processing {len(users)} user(s) for usage auto-delete.")

        now_ts = int(time.time())

        for user_record in users:
            user_id = user_record.get('id')
            if not user_id:
                continue

            configured_days = user_record.get('auto_delete_usage_after_days')
            # null → platform default (3 years)
            days = int(configured_days) if configured_days is not None else USAGE_DEFAULT_RETENTION_DAYS
            cutoff_ts = now_ts - days * 86400

            user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

            try:
                dir_deleted, s3_deleted = await _delete_usage_for_user(
                    user_id_hash=user_id_hash,
                    cutoff_ts=cutoff_ts,
                    directus_service=directus_service,
                    s3_service=s3_service,
                )
                summary['users_processed'] += 1
                summary['directus_records_deleted'] += dir_deleted
                summary['s3_files_deleted'] += s3_deleted
            except Exception as user_err:
                logger.error(
                    f"[UsageAutoDelete] Error processing user {user_id[:8]}...: {user_err}",
                    exc_info=True,
                )
                summary['users_failed'] += 1

        elapsed = time.time() - run_start
        summary['duration_seconds'] = round(elapsed, 2)

        logger.info(
            f"[UsageAutoDelete] Daily run complete in {elapsed:.1f}s. "
            f"Users: {summary['users_processed']}, "
            f"Directus records deleted: {summary['directus_records_deleted']}, "
            f"S3 files deleted: {summary['s3_files_deleted']}, "
            f"Failures: {summary['users_failed']}."
        )
        return summary

    except Exception as e:
        logger.error(f"[UsageAutoDelete] Fatal error: {e}", exc_info=True)
        raise
    finally:
        if secrets_manager is not None:
            try:
                await secrets_manager.aclose()
            except Exception:
                pass
        if directus_service is not None and hasattr(directus_service, 'close'):
            try:
                await directus_service.close()
            except Exception:
                pass


async def _delete_usage_for_user(
    user_id_hash: str,
    cutoff_ts: int,
    directus_service: DirectusService,
    s3_service: S3UploadService,
) -> tuple[int, int]:
    """
    Delete Directus usage records and S3 archives older than cutoff_ts for one user.

    Args:
        user_id_hash: SHA256 hash of the user ID.
        cutoff_ts:    Unix timestamp; records created before this are stale.
        directus_service: Authenticated Directus service.
        s3_service:   Initialized S3UploadService (for S3 archive deletion).

    Returns:
        Tuple of (directus_records_deleted, s3_files_deleted).
    """
    dir_deleted = 0
    s3_deleted = 0

    # ── Step 1: Delete Directus usage records older than cutoff ──────────────
    # The usage archive task moves records to S3 after ~3 months, so most old
    # records won't be in Directus. This catches any that slipped through.
    cutoff_dt = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc)
    cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S")

    params: Dict[str, Any] = {
        'filter[user_id_hash][_eq]': user_id_hash,
        'filter[created_at][_lt]': cutoff_iso,
        'fields': 'id',
        'limit': MAX_USAGE_RECORDS_PER_USER_PER_RUN,
        'sort': 'created_at',
    }
    try:
        stale_records = await directus_service.get_items('usage', params=params, no_cache=True)
        if stale_records and isinstance(stale_records, list):
            record_ids = [r.get('id') for r in stale_records if r.get('id')]
            if record_ids:
                success = await directus_service.bulk_delete_items(
                    collection='usage', item_ids=record_ids
                )
                if success:
                    dir_deleted = len(record_ids)
                    logger.debug(
                        f"[UsageAutoDelete] Deleted {dir_deleted} Directus usage records "
                        f"for user {user_id_hash[:12]}..."
                    )
                else:
                    logger.warning(
                        f"[UsageAutoDelete] bulk_delete_items failed for user {user_id_hash[:12]}..."
                    )
    except Exception as e:
        logger.warning(
            f"[UsageAutoDelete] Error deleting Directus records for user {user_id_hash[:12]}...: {e}"
        )

    # ── Step 2: Delete S3 usage archive files for months older than cutoff ────
    # Archive keys follow the pattern: usage-archives/{user_id_hash}/{YYYY-MM}/usage.json.gz
    # We generate the year-month strings deterministically: every month from
    # (cutoff - 10 years) to (cutoff - 3 months) is a candidate.  We attempt
    # deletion for each; a 404 from S3 (file not found) is silently ignored.
    # This avoids the need for a listing API call.
    cutoff_dt_local = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc)
    # Look back at most 10 years to bound the loop.  Archives older than that
    # are extremely unlikely.
    MAX_LOOKBACK_MONTHS = 120  # 10 years

    try:
        # Walk backwards from the cutoff month, trying each archive key.
        check_year = cutoff_dt_local.year
        check_month = cutoff_dt_local.month
        # The cutoff month itself may be partially in range; start one month earlier.
        if check_month == 1:
            check_year -= 1
            check_month = 12
        else:
            check_month -= 1

        for _ in range(MAX_LOOKBACK_MONTHS):
            year_month = f"{check_year:04d}-{check_month:02d}"
            s3_key = f"usage-archives/{user_id_hash}/{year_month}/usage.json.gz"
            try:
                await s3_service.delete_file(bucket_key="usage_archives", file_key=s3_key)
                s3_deleted += 1
                logger.debug(
                    f"[UsageAutoDelete] Deleted S3 archive {s3_key} for user {user_id_hash[:12]}..."
                )
            except Exception:
                # 404 / not found is expected for months with no archive — continue
                pass

            # Step backward one month
            if check_month == 1:
                check_year -= 1
                check_month = 12
            else:
                check_month -= 1

    except Exception as e:
        logger.warning(
            f"[UsageAutoDelete] Error deleting S3 archives for user {user_id_hash[:12]}...: {e}"
        )

    return dir_deleted, s3_deleted


# ─── Celery task wrapper ──────────────────────────────────────────────────────


@app.task(
    name="app.tasks.auto_delete_tasks.auto_delete_old_usage",
    bind=True,
    max_retries=1,
    default_retry_delay=600,  # 10-minute retry delay on catastrophic failure
)
def auto_delete_old_usage(self) -> Dict[str, Any]:
    """
    Celery Beat task — runs every day at 03:30 UTC.

    For each user, permanently deletes usage records that have exceeded the
    configured retention period (default: 3 years / 1095 days when not set).

    Deletion covers:
      - Directus usage collection records (entries not yet archived, or very old)
      - S3 usage archive files (usage-archives/{hash}/{year-month}/usage.json.gz)
        for months whose entire content is older than the retention cutoff

    At most MAX_USAGE_USERS_PER_RUN (500) users are processed per run.
    """
    task_id = self.request.id if self and hasattr(self, 'request') else 'UNKNOWN'
    logger.info(f"[UsageAutoDelete] Task started. task_id={task_id}")

    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_auto_delete_old_usage())
        logger.info(f"[UsageAutoDelete] Task completed. Summary: {result}")
        return result
    except Exception as e:
        logger.error(
            f"[UsageAutoDelete] Task failed. task_id={task_id}: {e}", exc_info=True
        )
        raise self.retry(exc=e)
    finally:
        if loop:
            loop.close()
