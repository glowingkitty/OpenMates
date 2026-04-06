# backend/apps/reminder/tasks.py
#
# Celery tasks for the Reminder app.
#
# ARCHITECTURE (Hybrid PostgreSQL + Hot Cache):
# - PostgreSQL/Directus is the durable source of truth for all reminders.
# - A "hot cache" ZSET in Dragonfly holds reminders due within 48 hours.
# - process_due_reminders (every 60s): fires due reminders from the hot cache.
# - promote_to_hot_cache (twice daily): loads near-term reminders from DB -> cache.
# - On every fire cycle, if the ZSET is empty, a DB fallback check runs to catch
#   reminders that were never promoted (crash recovery).
#
# Reference: docs/apps/reminder.md

import logging
import asyncio
import hashlib
import json
import uuid
import time

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.apps.reminder.utils import (
    calculate_next_repeat_time,
    format_reminder_time,
)

logger = logging.getLogger(__name__)

# Hot cache window: 48 hours
HOT_CACHE_WINDOW_SECONDS = 48 * 3600

# Embed display content for all reminder types (shown in the reminder_fired WebSocket event).
REMINDER_MESSAGE_TEMPLATE = """🔔 **Reminder**

{prompt}

---
*This reminder was set on {created_date}*"""

# System message injected into the AI's message history for response_type="full".
# Wraps the user's task prompt with clear context so the LLM knows it was scheduled
# to execute a task — not that a user just typed a message.
REMINDER_TASK_TEMPLATE = "[Scheduled Reminder — Task Triggered]\n\nTask: {prompt}\n\nCarry out this task now. Do not explain that a reminder fired unless the user explicitly asks."


# =========================================================================
# TASK 1: FIRE DUE REMINDERS (every 60 seconds)
# =========================================================================

@app.task(name="reminder.process_due_reminders", base=BaseServiceTask, bind=True)
def process_due_reminders(self):
    """
    Scheduled task that processes all due reminders.

    Called by Celery Beat every 60 seconds. It:
    1. Queries the hot cache ZSET for reminders with trigger_at <= now
    2. Claims each reminder atomically (ZREM) to prevent double-firing
    3. Decrypts vault-encrypted fields (prompt, user_id, chat history)
    4. Delivers via WebSocket + email + pending delivery queue
    5. Updates the DB record (status, occurrence_count, next trigger_at)
    6. If the ZSET is empty, runs a DB fallback check for overdue reminders
    """
    return asyncio.run(_process_due_reminders_async(self))


async def _process_due_reminders_async(task: BaseServiceTask):
    """Async implementation of process_due_reminders."""
    try:
        await task.initialize_services()

        cache_service = task._cache_service
        encryption_service = task._encryption_service
        directus_service = task._directus_service

        if not cache_service or not encryption_service:
            logger.error("Required services not available for reminder processing")
            return {"success": False, "error": "Services not available"}

        current_time = int(time.time())

        # Get all due reminders from the hot cache
        due_reminders = await cache_service.get_due_reminders(current_time)

        # DB FALLBACK: If the cache ZSET is empty, check the DB for overdue reminders.
        # This catches reminders that were never promoted (e.g., cache was wiped).
        if not due_reminders:
            cache_count = await cache_service.get_cache_schedule_count()
            if cache_count == 0 and directus_service:
                try:
                    overdue = await directus_service.reminder.get_overdue_pending_reminders()
                    if overdue:
                        logger.warning(
                            f"[REMINDER] ZSET empty — found {len(overdue)} overdue reminders "
                            f"in DB, loading into cache for immediate processing"
                        )
                        await cache_service.load_reminders_batch_into_cache(overdue)
                        # Re-query the cache now that we've loaded them
                        due_reminders = await cache_service.get_due_reminders(current_time)
                except Exception as fallback_err:
                    logger.error(f"[REMINDER] DB fallback check failed: {fallback_err}", exc_info=True)

        if not due_reminders:
            logger.debug("No due reminders to process")
            return {"success": True, "processed": 0}

        logger.info(f"Processing {len(due_reminders)} due reminders")

        processed_count = 0
        error_count = 0

        for reminder in due_reminders:
            try:
                reminder_id = reminder.get("reminder_id") or reminder.get("id")
                vault_key_id = reminder.get("vault_key_id")
                target_type = reminder.get("target_type", "new_chat")
                repeat_config = reminder.get("repeat_config")
                timezone = reminder.get("timezone", "UTC")
                created_at = reminder.get("created_at", current_time)
                response_type = reminder.get("response_type", "simple")

                # IDEMPOTENCY: Atomically claim this reminder via ZREM.
                # If another worker already claimed it, skip.
                claimed = await cache_service.claim_due_reminder(reminder_id)
                if not claimed:
                    logger.debug(f"Reminder {reminder_id} already claimed, skipping")
                    continue

                # Decrypt user_id from vault-encrypted field.
                # The DB stores encrypted_user_id; cache may still have raw user_id
                # from the old format. Support both for backwards compatibility.
                user_id = reminder.get("user_id")
                if not user_id:
                    encrypted_user_id = reminder.get("encrypted_user_id")
                    if encrypted_user_id and vault_key_id:
                        try:
                            user_id = await encryption_service.decrypt_with_user_key(
                                ciphertext=encrypted_user_id, key_id=vault_key_id
                            )
                        except Exception as e:
                            logger.error(f"Failed to decrypt user_id for reminder {reminder_id}: {e}")

                if not user_id:
                    logger.error(f"Reminder {reminder_id}: no user_id available, skipping")
                    error_count += 1
                    # Mark failed in DB
                    if directus_service:
                        await directus_service.reminder.update_reminder(
                            reminder_id, {"status": "failed"}
                        )
                    continue

                logger.info(f"Processing reminder {reminder_id} for user {user_id[:8]}... (response_type={response_type})")

                # Decrypt the prompt
                encrypted_prompt = reminder.get("encrypted_prompt")
                if not encrypted_prompt or not vault_key_id:
                    logger.error(f"Reminder {reminder_id} missing encrypted_prompt or vault_key_id")
                    error_count += 1
                    if directus_service:
                        await directus_service.reminder.update_reminder(
                            reminder_id, {"status": "failed"}
                        )
                    continue

                try:
                    prompt = await encryption_service.decrypt_with_user_key(
                        ciphertext=encrypted_prompt, key_id=vault_key_id
                    )
                except Exception as e:
                    logger.error(f"Failed to decrypt prompt for reminder {reminder_id}: {e}")
                    error_count += 1
                    if directus_service:
                        await directus_service.reminder.update_reminder(
                            reminder_id, {"status": "failed"}
                        )
                    continue

                if not prompt:
                    logger.error(f"Decrypted prompt is empty for reminder {reminder_id}")
                    error_count += 1
                    continue

                # Format the system message
                created_date = format_reminder_time(created_at, timezone)
                message_content = REMINDER_MESSAGE_TEMPLATE.format(
                    prompt=prompt, created_date=created_date
                )

                # Determine target chat_id
                if target_type == "new_chat":
                    target_chat_id = str(uuid.uuid4())
                else:
                    # Decrypt target_chat_id from vault-encrypted field (new format)
                    # or use plaintext (old cache format)
                    target_chat_id = reminder.get("target_chat_id")
                    if not target_chat_id:
                        encrypted_target = reminder.get("encrypted_target_chat_id")
                        if encrypted_target and vault_key_id:
                            try:
                                target_chat_id = await encryption_service.decrypt_with_user_key(
                                    ciphertext=encrypted_target, key_id=vault_key_id
                                )
                            except Exception as e:
                                logger.error(f"Failed to decrypt target_chat_id for reminder {reminder_id}: {e}")
                    if not target_chat_id:
                        logger.error(f"No target_chat_id for existing_chat reminder {reminder_id}")
                        error_count += 1
                        continue

                message_id = str(uuid.uuid4())

                # Decrypt chat title for new_chat target
                chat_title = None
                if target_type == "new_chat":
                    encrypted_new_chat_title = reminder.get("encrypted_new_chat_title")
                    if encrypted_new_chat_title:
                        try:
                            decrypted_title = await encryption_service.decrypt_with_user_key(
                                ciphertext=encrypted_new_chat_title, key_id=vault_key_id
                            )
                            if decrypted_title:
                                chat_title = decrypted_title
                        except Exception as e:
                            logger.warning(f"Could not decrypt chat title for reminder {reminder_id}: {e}")
                    if not chat_title:
                        chat_title = prompt[:50] + ("..." if len(prompt) > 50 else "")

                # PRE-CREATE CHAT IN DIRECTUS (for new_chat targets)
                if target_type == "new_chat" and directus_service:
                    hashed_uid = hashlib.sha256(user_id.encode()).hexdigest()
                    try:
                        minimal_chat_metadata = {
                            "id": target_chat_id,
                            "hashed_user_id": hashed_uid,
                            "created_at": current_time,
                            "updated_at": current_time,
                            "messages_v": 0,
                            "title_v": 0,
                            "last_edited_overall_timestamp": current_time,
                            "last_message_timestamp": current_time,
                            "unread_count": 1,
                        }
                        created_data, is_duplicate = await directus_service.chat.create_chat_in_directus(minimal_chat_metadata)
                        if created_data:
                            logger.info(f"Pre-created chat {target_chat_id} in Directus for reminder {reminder_id}")
                        elif is_duplicate:
                            logger.debug(f"Chat {target_chat_id} already exists (race condition), continuing")
                        else:
                            logger.warning(f"Failed to pre-create chat {target_chat_id} in Directus, continuing anyway")
                    except Exception as create_err:
                        logger.warning(f"Error pre-creating chat {target_chat_id}: {create_err}, continuing anyway")

                delivery_payload = {
                    "reminder_id": reminder_id,
                    "chat_id": target_chat_id,
                    "message_id": message_id,
                    "target_type": target_type,
                    "is_repeating": repeat_config is not None,
                    "content": message_content,
                    "chat_title": chat_title,
                    "user_id": user_id,
                    "fired_at": current_time,
                    # response_type lets the frontend know whether to render a
                    # timeline marker (simple) or await an AI response bubble (full).
                    "response_type": response_type,
                    "trigger_at_formatted": format_reminder_time(current_time, timezone),
                    "prompt_preview": prompt[:80],
                }

                # WebSocket delivery
                try:
                    await task.publish_websocket_event(
                        user_id_hash=user_id,
                        event="reminder_fired",
                        payload=delivery_payload
                    )
                    logger.info(f"Published reminder_fired WebSocket event for reminder {reminder_id}")
                except Exception as ws_error:
                    logger.error(f"Failed to publish WebSocket event for reminder {reminder_id}: {ws_error}")

                # Pending delivery safety net
                try:
                    await cache_service.add_pending_reminder_delivery(
                        user_id=user_id, delivery_payload=delivery_payload
                    )
                except Exception as queue_error:
                    logger.warning(f"Failed to queue pending delivery for reminder {reminder_id}: {queue_error}")

                # Email notification
                try:
                    await _send_reminder_email_notification(
                        user_id=user_id,
                        reminder_prompt=prompt,
                        trigger_time=format_reminder_time(current_time, timezone),
                        chat_id=target_chat_id,
                        chat_title=chat_title,
                        is_new_chat=(target_type == "new_chat"),
                        directus_service=directus_service,
                        encryption_service=encryption_service,
                    )
                except Exception as email_error:
                    logger.warning(f"Failed to send email notification for reminder {reminder_id}: {email_error}")

                # Dispatch AI response
                if response_type == "full":
                    try:
                        await _dispatch_reminder_ai_request(
                            user_id=user_id,
                            chat_id=target_chat_id,
                            message_id=message_id,
                            prompt=prompt,
                            target_type=target_type,
                            chat_title=chat_title,
                            reminder=reminder,
                            encryption_service=encryption_service,
                            cache_service=cache_service,
                        )
                    except Exception as ai_error:
                        logger.warning(f"Failed to dispatch AI request for reminder {reminder_id}: {ai_error}")
                else:
                    # Simple reminder: no AI response is generated.
                    # The reminder_fired WebSocket event (already published above) carries
                    # response_type="simple" so the frontend renders a timeline marker
                    # in the chat history instead of an AI bubble.
                    logger.debug(f"Simple reminder {reminder_id}: skipping AI response, timeline marker will be shown")

                # Handle repeating vs one-time
                if repeat_config:
                    next_trigger_at = calculate_next_repeat_time(
                        current_trigger_at=reminder.get("trigger_at"),
                        repeat_config=repeat_config,
                        timezone_str=timezone,
                        random_config=reminder.get("random_config")
                    )

                    if next_trigger_at:
                        occurrence_count = reminder.get("occurrence_count", 0) + 1
                        max_occurrences = repeat_config.get("max_occurrences")

                        if max_occurrences and occurrence_count >= max_occurrences:
                            logger.info(f"Reminder {reminder_id} reached max occurrences ({max_occurrences})")
                            # Update DB: mark as fired (completed all occurrences)
                            if directus_service:
                                await directus_service.reminder.update_reminder(reminder_id, {
                                    "status": "fired",
                                    "occurrence_count": occurrence_count,
                                })
                            await cache_service.remove_reminder_from_cache(reminder_id)
                        else:
                            # Reschedule: update DB with new trigger_at
                            if directus_service:
                                await directus_service.reminder.update_reminder(reminder_id, {
                                    "trigger_at": next_trigger_at,
                                    "occurrence_count": occurrence_count,
                                    "status": "pending",
                                })
                            # Reschedule in cache (only if within 48h window)
                            await cache_service.reschedule_reminder_in_cache(
                                reminder_id=reminder_id,
                                reminder_data=reminder,
                                new_trigger_at=next_trigger_at,
                            )
                            logger.info(
                                f"Rescheduled reminder {reminder_id} to "
                                f"{format_reminder_time(next_trigger_at, timezone)}"
                            )
                    else:
                        # No next occurrence (end date reached)
                        logger.info(f"Reminder {reminder_id} has no more occurrences")
                        if directus_service:
                            await directus_service.reminder.update_reminder(reminder_id, {
                                "status": "fired",
                                "occurrence_count": reminder.get("occurrence_count", 0) + 1,
                            })
                        await cache_service.remove_reminder_from_cache(reminder_id)
                else:
                    # One-time reminder: mark as fired in DB, remove from cache
                    if directus_service:
                        await directus_service.reminder.update_reminder(reminder_id, {
                            "status": "fired",
                            "occurrence_count": 1,
                        })
                    await cache_service.remove_reminder_from_cache(reminder_id)
                    logger.info(f"Fired one-time reminder {reminder_id}")

                processed_count += 1
                logger.info(
                    f"[REMINDER_DECRYPTED] Decrypted and fired reminder {reminder_id}",
                    extra={"event": "reminder_decrypted", "reminder_id": reminder_id}
                )

            except Exception as e:
                logger.error(f"Error processing reminder: {e}", exc_info=True)
                error_count += 1
                continue

        logger.info(f"Reminder processing complete. Processed: {processed_count}, Errors: {error_count}")
        return {"success": True, "processed": processed_count, "errors": error_count}

    except Exception as e:
        logger.error(f"Error in process_due_reminders: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()


# =========================================================================
# TASK 2: PROMOTE REMINDERS TO HOT CACHE (twice daily)
# =========================================================================

@app.task(name="reminder.promote_to_hot_cache", base=BaseServiceTask, bind=True)
def promote_to_hot_cache(self):
    """
    Promotion task: load near-term reminders from PostgreSQL into the hot cache.

    Runs twice daily (03:00 and 15:00 UTC). Queries the DB for all pending
    reminders with trigger_at within the 48-hour window and loads them into
    the Dragonfly ZSET if not already present.

    Also runs an empty-ZSET health check: if the ZSET has 0 entries but the
    DB has pending reminders in the window, triggers an immediate reload.
    """
    return asyncio.run(_promote_to_hot_cache_async(self))


async def _promote_to_hot_cache_async(task: BaseServiceTask):
    """Async implementation of promote_to_hot_cache."""
    try:
        await task.initialize_services()

        cache_service = task._cache_service
        directus_service = task._directus_service

        if not cache_service or not directus_service:
            logger.error("[PROMOTION] Required services not available")
            return {"success": False, "error": "Services not available"}

        # Query DB for pending reminders in the hot window
        reminders = await directus_service.reminder.get_pending_reminders_in_window(
            window_seconds=HOT_CACHE_WINDOW_SECONDS
        )

        if not reminders:
            logger.info("[PROMOTION] No pending reminders in the 48h window")
            return {"success": True, "promoted": 0}

        # Load into cache (load_reminders_batch_into_cache handles dedup via ZADD)
        loaded = await cache_service.load_reminders_batch_into_cache(reminders)

        logger.info(f"[PROMOTION] Promoted {loaded} reminders from DB to hot cache")
        return {"success": True, "promoted": loaded, "total_in_window": len(reminders)}

    except Exception as e:
        logger.error(f"[PROMOTION] Error in promote_to_hot_cache: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()


# =========================================================================
# TASK 3: AUDIT PENDING DELIVERIES (every 6 hours)
# =========================================================================

@app.task(name="reminder.audit_pending_deliveries", base=BaseServiceTask, bind=True)
def audit_pending_deliveries(self):
    """
    Periodic task that audits pending delivery entries.

    Called by Celery Beat every 6 hours. Logs users who have undelivered
    messages for monitoring. Redis TTL handles actual expiry (60 days).
    """
    return asyncio.run(_audit_pending_deliveries_async(self))


async def _audit_pending_deliveries_async(task: BaseServiceTask):
    """Async implementation of audit_pending_deliveries."""
    try:
        await task.initialize_services()

        cache_service = task._cache_service
        if not cache_service:
            return {"success": False, "error": "Cache service not available"}

        users_with_pending = await cache_service.cleanup_expired_pending_deliveries()

        return {"success": True, "users_with_pending": users_with_pending}

    except Exception as e:
        logger.error(f"Error auditing pending deliveries: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()


# =========================================================================
# TASK 4: GET STATS (on-demand)
# =========================================================================

@app.task(name="reminder.get_stats", base=BaseServiceTask, bind=True)
def get_reminder_stats(self):
    """Get statistics about reminders (cache + DB)."""
    return asyncio.run(_get_reminder_stats_async(self))


async def _get_reminder_stats_async(task: BaseServiceTask):
    """Async implementation of get_reminder_stats."""
    try:
        await task.initialize_services()

        cache_service = task._cache_service
        directus_service = task._directus_service
        if not cache_service:
            return {"success": False, "error": "Cache service not available"}

        cache_stats = await cache_service.get_reminder_stats()

        # Add DB count if available
        db_pending = 0
        if directus_service:
            try:
                db_pending = await directus_service.reminder.count_pending_reminders()
            except Exception as e:
                logger.warning(f"Could not get DB reminder count: {e}")

        return {
            "success": True,
            **cache_stats,
            "db_pending": db_pending,
        }

    except Exception as e:
        logger.error(f"Error getting reminder stats: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()


# =========================================================================
# HELPER: Dispatch AI request for full response reminders
# =========================================================================

async def _dispatch_reminder_ai_request(
    user_id: str,
    chat_id: str,
    message_id: str,
    prompt: str,
    target_type: str,
    chat_title: str | None,
    reminder: dict,
    encryption_service,
    cache_service,
) -> None:
    """
    Dispatch an AI ask request for a fired reminder.

    Builds message history from cached vault-encrypted chat history (for
    existing_chat reminders) and sends the reminder prompt as the latest
    user message.
    """
    vault_key_id = reminder.get("vault_key_id")
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

    message_history = []

    if target_type == "existing_chat":
        encrypted_chat_history = reminder.get("encrypted_chat_history")
        if encrypted_chat_history and vault_key_id:
            try:
                decrypted_history = await encryption_service.decrypt_with_user_key(
                    ciphertext=encrypted_chat_history, key_id=vault_key_id
                )
                if decrypted_history:
                    cached_messages = json.loads(decrypted_history)
                    for msg in cached_messages:
                        if isinstance(msg, str):
                            try:
                                msg = json.loads(msg)
                            except (json.JSONDecodeError, TypeError):
                                continue

                        if not isinstance(msg, dict):
                            continue

                        encrypted_content = msg.get("encrypted_content")
                        if encrypted_content:
                            try:
                                decrypted_content = await encryption_service.decrypt_with_user_key(
                                    ciphertext=encrypted_content, key_id=vault_key_id
                                )
                                if decrypted_content:
                                    message_history.append({
                                        "content": decrypted_content,
                                        "role": msg.get("role", "user"),
                                        "created_at": msg.get("created_at", int(time.time())),
                                    })
                            except Exception as e_decrypt:
                                logger.debug(f"Could not decrypt cached message: {e_decrypt}")
                                continue
                        else:
                            content = msg.get("content", "")
                            if content:
                                message_history.append({
                                    "content": content,
                                    "role": msg.get("role", "user"),
                                    "created_at": msg.get("created_at", int(time.time())),
                                })
                    logger.info(f"Restored {len(message_history)} messages from cached history")
            except Exception as e:
                logger.warning(f"Could not restore chat history for AI request: {e}")

    # Wrap the prompt with task context so the LLM knows it was triggered by a
    # scheduled reminder — not a spontaneous user message.
    task_content = REMINDER_TASK_TEMPLATE.format(prompt=prompt)
    message_history.append({
        "content": task_content,
        "role": "user",
        "created_at": int(time.time()),
    })

    user_timezone = await cache_service.get_user_timezone(user_id)
    user_preferences = {}
    if user_timezone:
        user_preferences["timezone"] = user_timezone

    chat_has_title_flag = False if target_type == "new_chat" else bool(chat_title)

    ask_request = {
        "chat_id": chat_id,
        "message_id": message_id,
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "message_history": message_history,
        "chat_has_title": chat_has_title_flag,
        "mate_id": None,
        "active_focus_id": None,
        "user_preferences": user_preferences,
        "app_settings_memories_metadata": None,
    }

    # OPE-342: dispatch via in-process SkillRegistry (no HTTP to app-ai container,
    # which no longer exists). The reminder task runs inside task-worker, which
    # builds its own registry in init_worker_process().
    from backend.core.api.app.services.skill_registry import get_global_registry

    response_data = await get_global_registry().dispatch_skill("ai", "ask", ask_request)
    ai_task_id = response_data.get("task_id") if isinstance(response_data, dict) else None

    if ai_task_id:
        await cache_service.set_active_ai_task(chat_id, ai_task_id)
        logger.info(f"Dispatched AI ask request for reminder in chat {chat_id}, task_id={ai_task_id}")
    else:
        logger.warning(f"ai.ask returned no task_id for reminder chat {chat_id}")


# =========================================================================
# HELPER: Send email notification
# =========================================================================

async def _send_reminder_email_notification(
    user_id: str,
    reminder_prompt: str,
    trigger_time: str,
    chat_id: str,
    chat_title: str | None,
    is_new_chat: bool,
    directus_service,
    encryption_service,
) -> bool:
    """
    Send an email notification for a fired reminder.

    Checks if the user has email notifications enabled, decrypts the
    vault-encrypted notification email, then dispatches a Celery email task.
    """
    try:
        user_profile_result = await directus_service.get_user_profile(user_id)

        if not user_profile_result or not user_profile_result[0]:
            logger.debug(f"Could not fetch user profile for email notification (user_id={user_id})")
            return False

        user_profile = user_profile_result[1]

        email_notifications_enabled = user_profile.get("email_notifications_enabled", False)
        if not email_notifications_enabled:
            logger.debug(f"User {user_id[:8]}... does not have email notifications enabled")
            return False

        encrypted_notification_email = user_profile.get("encrypted_notification_email")
        if not encrypted_notification_email:
            logger.debug(f"User {user_id[:8]}... has no encrypted_notification_email configured")
            return False

        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            logger.warning(f"User {user_id[:8]}... has no vault_key_id")
            return False

        try:
            notification_email = await encryption_service.decrypt_with_user_key(
                encrypted_notification_email, vault_key_id
            )
        except Exception as decrypt_error:
            logger.error(f"Failed to decrypt notification email for user {user_id[:8]}...: {decrypt_error}", exc_info=True)
            return False

        if not notification_email:
            logger.warning(f"Notification email decryption returned empty for user {user_id[:8]}...")
            return False

        language = user_profile.get("language", "en")
        darkmode = user_profile.get("darkmode", False)

        app.send_task(
            name='app.tasks.email_tasks.reminder_notification_email_task.send_reminder_notification',
            kwargs={
                "recipient_email": notification_email,
                "reminder_prompt": reminder_prompt,
                "trigger_time": trigger_time,
                "chat_id": chat_id,
                "chat_title": chat_title,
                "is_new_chat": is_new_chat,
                "language": language,
                "darkmode": darkmode,
            },
            queue='email'
        )

        logger.info(f"Dispatched reminder email notification for user {user_id[:8]}...")
        return True

    except Exception as e:
        logger.error(f"Error dispatching reminder email notification: {e}", exc_info=True)
        return False
