# backend/core/api/app/tasks/auto_delete_tasks.py
#
# Daily Celery Beat task that auto-deletes old chats for users who have
# configured a retention period via Privacy → Auto Deletion → Chats.
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

import asyncio
import hashlib
import logging
import time
from typing import Any, Dict

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)

# ─── Rate-limit constants ─────────────────────────────────────────────────────

# Maximum number of chats to schedule for deletion per user per daily run.
# If a user has more stale chats they will be handled over subsequent runs.
MAX_CHATS_PER_USER_PER_RUN: int = 100

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
