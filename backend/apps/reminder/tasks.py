# backend/apps/reminder/tasks.py
#
# Celery tasks for the Reminder app.
# Includes the scheduled task that processes due reminders.

import logging
import asyncio
import uuid
import time

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.apps.reminder.utils import (
    calculate_next_repeat_time,
    format_reminder_time,
)

logger = logging.getLogger(__name__)

# System message template for reminders
REMINDER_MESSAGE_TEMPLATE = """🔔 **Reminder**

{prompt}

---
*This reminder was set on {created_date}*"""


@app.task(name="reminder.process_due_reminders", base=BaseServiceTask, bind=True)
def process_due_reminders(self):
    """
    Scheduled task that processes all due reminders.
    
    This task is called by Celery Beat every 60 seconds. It:
    1. Queries for all reminders where trigger_at <= now
    2. For each due reminder:
       - Decrypts the prompt and chat history
       - Creates a system message in the target chat (new or existing)
       - Sends notifications (WebSocket + email if configured)
       - For repeating reminders: reschedules to next occurrence
       - For one-time reminders: deletes the reminder
    """
    return asyncio.run(_process_due_reminders_async(self))


async def _process_due_reminders_async(task: BaseServiceTask):
    """
    Async implementation of process_due_reminders.
    """
    try:
        # Initialize services
        await task.initialize_services()
        
        cache_service = task._cache_service
        encryption_service = task._encryption_service
        directus_service = task._directus_service
        
        if not cache_service or not encryption_service:
            logger.error("Required services not available for reminder processing")
            return {"success": False, "error": "Services not available"}

        current_time = int(time.time())
        
        # Get all due reminders
        due_reminders = await cache_service.get_due_reminders(current_time)
        
        if not due_reminders:
            logger.debug("No due reminders to process")
            return {"success": True, "processed": 0}

        logger.info(f"Processing {len(due_reminders)} due reminders")
        
        processed_count = 0
        error_count = 0

        for reminder in due_reminders:
            try:
                reminder_id = reminder.get("reminder_id")
                user_id = reminder.get("user_id")
                vault_key_id = reminder.get("vault_key_id")
                target_type = reminder.get("target_type", "new_chat")
                repeat_config = reminder.get("repeat_config")
                timezone = reminder.get("timezone", "UTC")
                created_at = reminder.get("created_at", current_time)

                logger.info(f"Processing reminder {reminder_id} for user {user_id}")

                # Decrypt the prompt
                encrypted_prompt = reminder.get("encrypted_prompt")
                if not encrypted_prompt or not vault_key_id:
                    logger.error(f"Reminder {reminder_id} missing encrypted_prompt or vault_key_id")
                    error_count += 1
                    continue

                try:
                    prompt = await encryption_service.decrypt_with_user_key(
                        ciphertext=encrypted_prompt,
                        key_id=vault_key_id
                    )
                except Exception as e:
                    logger.error(f"Failed to decrypt prompt for reminder {reminder_id}: {e}")
                    error_count += 1
                    # Mark as failed and continue
                    await cache_service.update_reminder_status(reminder_id, "failed")
                    continue

                if not prompt:
                    logger.error(f"Decrypted prompt is empty for reminder {reminder_id}")
                    error_count += 1
                    continue

                # Format the system message
                created_date = format_reminder_time(created_at, timezone)
                message_content = REMINDER_MESSAGE_TEMPLATE.format(
                    prompt=prompt,
                    created_date=created_date
                )

                # Determine target chat_id
                # For new_chat: generate a new chat_id
                # For existing_chat: use the stored target_chat_id
                if target_type == "new_chat":
                    target_chat_id = str(uuid.uuid4())
                else:
                    target_chat_id = reminder.get("target_chat_id")
                    if not target_chat_id:
                        logger.error(f"No target_chat_id for existing_chat reminder {reminder_id}")
                        error_count += 1
                        continue

                # Generate message ID for the system message
                message_id = str(uuid.uuid4())

                # Decrypt chat title for new_chat target
                chat_title = None
                if target_type == "new_chat":
                    encrypted_new_chat_title = reminder.get("encrypted_new_chat_title")
                    if encrypted_new_chat_title:
                        try:
                            decrypted_title = await encryption_service.decrypt_with_user_key(
                                ciphertext=encrypted_new_chat_title,
                                key_id=vault_key_id
                            )
                            if decrypted_title:
                                chat_title = decrypted_title
                        except Exception as e:
                            logger.warning(f"Could not decrypt chat title for reminder {reminder_id}: {e}")
                    if not chat_title:
                        # Derive title from prompt (first 50 chars)
                        chat_title = prompt[:50] + ("..." if len(prompt) > 50 else "")

                # ARCHITECTURE: Zero-Knowledge Reminder Delivery
                # 
                # Phase 1 (User Online): Send PLAINTEXT content via WebSocket.
                #   The client encrypts with the chat key, persists, and syncs back.
                #
                # Phase 2 (User Offline): Queue the delivery payload in cache.
                #   When the user reconnects, the WebSocket endpoint delivers
                #   pending reminders. Email notification is sent as a backup.
                #
                # This ensures the server never stores messages encrypted with a key
                # the client can't access (vault key vs chat key mismatch).

                delivery_payload = {
                    "reminder_id": reminder_id,
                    "chat_id": target_chat_id,
                    "message_id": message_id,
                    "target_type": target_type,
                    "is_repeating": repeat_config is not None,
                    "content": message_content,  # PLAINTEXT - client encrypts with chat key
                    "chat_title": chat_title,  # For new_chat target
                    "user_id": user_id,  # Required by WebSocket relay for routing
                    "fired_at": current_time,  # When the reminder actually fired
                }

                # Try real-time WebSocket delivery first
                try:
                    await task.publish_websocket_event(
                        user_id_hash=user_id,
                        event="reminder_fired",
                        payload=delivery_payload
                    )
                    logger.info(f"Published reminder_fired WebSocket event for reminder {reminder_id} to user {user_id[:8]}...")
                except Exception as ws_error:
                    logger.error(f"Failed to publish WebSocket event for reminder {reminder_id}: {ws_error}")

                # Always queue for pending delivery as a safety net.
                # The WebSocket pub/sub is fire-and-forget - we can't know if the user
                # actually received it. The client will deduplicate by message_id if it
                # receives both the real-time event and the pending delivery on reconnect.
                try:
                    await cache_service.add_pending_reminder_delivery(
                        user_id=user_id,
                        delivery_payload=delivery_payload
                    )
                    logger.debug(f"Queued pending delivery for reminder {reminder_id}")
                except Exception as queue_error:
                    logger.warning(f"Failed to queue pending delivery for reminder {reminder_id}: {queue_error}")

                # Send email notification if user has email notifications enabled
                try:
                    await _send_reminder_email_notification(
                        user_id=user_id,
                        reminder_prompt=prompt,
                        trigger_time=format_reminder_time(current_time, timezone),
                        chat_id=target_chat_id,
                        chat_title=chat_title,
                        is_new_chat=(target_type == "new_chat"),
                        directus_service=directus_service,
                    )
                except Exception as email_error:
                    # Email notification failure should not fail the reminder
                    logger.warning(f"Failed to send email notification for reminder {reminder_id}: {email_error}")

                # Handle repeating vs one-time
                if repeat_config:
                    # Calculate next trigger time
                    next_trigger_at = calculate_next_repeat_time(
                        current_trigger_at=reminder.get("trigger_at"),
                        repeat_config=repeat_config,
                        timezone_str=timezone,
                        random_config=reminder.get("random_config")
                    )

                    if next_trigger_at:
                        # Check max_occurrences limit
                        occurrence_count = reminder.get("occurrence_count", 0) + 1
                        max_occurrences = repeat_config.get("max_occurrences")
                        
                        if max_occurrences and occurrence_count >= max_occurrences:
                            logger.info(f"Reminder {reminder_id} reached max occurrences ({max_occurrences}), deleting")
                            await cache_service.delete_reminder(reminder_id, user_id)
                        else:
                            # Reschedule for next occurrence
                            await cache_service.reschedule_reminder(
                                reminder_id=reminder_id,
                                new_trigger_at=next_trigger_at,
                                increment_occurrence=True
                            )
                            logger.info(f"Rescheduled reminder {reminder_id} to {format_reminder_time(next_trigger_at, timezone)}")
                    else:
                        # No next occurrence (end date reached or error)
                        logger.info(f"Reminder {reminder_id} has no more occurrences, deleting")
                        await cache_service.delete_reminder(reminder_id, user_id)
                else:
                    # One-time reminder - delete after firing
                    await cache_service.delete_reminder(reminder_id, user_id)
                    logger.info(f"Deleted one-time reminder {reminder_id}")

                processed_count += 1

            except Exception as e:
                logger.error(f"Error processing reminder: {e}", exc_info=True)
                error_count += 1
                continue

        logger.info(f"Reminder processing complete. Processed: {processed_count}, Errors: {error_count}")
        
        return {
            "success": True,
            "processed": processed_count,
            "errors": error_count
        }

    except Exception as e:
        logger.error(f"Error in process_due_reminders: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()


## NOTE: _create_new_chat_with_reminder and _send_reminder_to_existing_chat
## were removed as part of the zero-knowledge architecture fix.
## 
## Previously, the server would encrypt reminder messages with the user's Vault key
## and insert them directly into Directus. However, the client expects messages to be
## encrypted with the chat key (client-side zero-knowledge encryption).
## 
## The new approach sends plaintext reminder content to the client via WebSocket.
## The client encrypts with the chat key, saves to IndexedDB, and sends back to
## the server for persistence via the existing chat_system_message_added flow.
## This ensures the zero-knowledge encryption model is preserved.


async def _send_reminder_email_notification(
    user_id: str,
    reminder_prompt: str,
    trigger_time: str,
    chat_id: str,
    chat_title: str | None,
    is_new_chat: bool,
    directus_service,
) -> bool:
    """
    Send an email notification for a fired reminder.
    
    Checks if the user has email notifications enabled before sending.
    Uses a Celery task to send the email asynchronously.
    
    Args:
        user_id: User's UUID
        reminder_prompt: The decrypted reminder prompt text
        trigger_time: Human-readable trigger time string
        chat_id: The chat ID where the reminder was delivered
        chat_title: Optional title of the chat
        is_new_chat: Whether a new chat was created
        directus_service: Directus service for fetching user profile
        
    Returns:
        True if email was dispatched, False otherwise
    """
    try:
        # Get user profile to check email notification settings
        user_profile_result = await directus_service.get_user_profile(user_id)
        
        if not user_profile_result or not user_profile_result[0]:
            logger.debug(f"Could not fetch user profile for email notification (user_id={user_id})")
            return False
        
        user_profile = user_profile_result[1]
        
        # Check if user has email notifications enabled
        notification_email = user_profile.get("notification_email")
        email_notifications_enabled = user_profile.get("email_notifications_enabled", False)
        
        if not notification_email or not email_notifications_enabled:
            logger.debug(f"User {user_id} does not have email notifications enabled")
            return False
        
        # Get user preferences for the email
        language = user_profile.get("language", "en")
        darkmode = user_profile.get("darkmode", False)
        
        # Dispatch the email task
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
        
        logger.info(f"Dispatched reminder email notification to {notification_email} for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error dispatching reminder email notification: {e}", exc_info=True)
        return False


@app.task(name="reminder.get_stats", base=BaseServiceTask, bind=True)
def get_reminder_stats(self):
    """
    Get statistics about reminders in the system.
    Used for monitoring and admin purposes.
    """
    return asyncio.run(_get_reminder_stats_async(self))


async def _get_reminder_stats_async(task: BaseServiceTask):
    """Async implementation of get_reminder_stats."""
    try:
        await task.initialize_services()
        
        cache_service = task._cache_service
        if not cache_service:
            return {"success": False, "error": "Cache service not available"}

        stats = await cache_service.get_reminder_stats()
        
        return {
            "success": True,
            **stats
        }

    except Exception as e:
        logger.error(f"Error getting reminder stats: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()
