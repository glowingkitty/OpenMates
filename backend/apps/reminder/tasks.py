# backend/apps/reminder/tasks.py
#
# Celery tasks for the Reminder app.
# Includes the scheduled task that processes due reminders.

import logging
import asyncio
import uuid
import time
import json
from typing import Dict, Any

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

                # Process based on target type
                if target_type == "new_chat":
                    success, result_data = await _create_new_chat_with_reminder(
                        reminder=reminder,
                        message_content=message_content,
                        encryption_service=encryption_service,
                        directus_service=directus_service,
                        cache_service=cache_service,
                    )
                else:  # existing_chat
                    success, result_data = await _send_reminder_to_existing_chat(
                        reminder=reminder,
                        message_content=message_content,
                        encryption_service=encryption_service,
                        directus_service=directus_service,
                        cache_service=cache_service,
                    )
                
                # Send WebSocket notification to user if processing succeeded
                if success and user_id and result_data:
                    try:
                        await task.publish_websocket_event(
                            user_id_hash=user_id,
                            event="reminder_fired",
                            payload={
                                "reminder_id": reminder_id,
                                "chat_id": result_data.get("chat_id"),
                                "message_id": result_data.get("message_id"),
                                "target_type": target_type,
                                "is_repeating": repeat_config is not None,
                                "encrypted_content": result_data.get("encrypted_content"),
                            }
                        )
                        logger.debug(f"Sent WebSocket notification for reminder {reminder_id}")
                    except Exception as ws_error:
                        # WebSocket notification failure should not fail the reminder
                        logger.warning(f"Failed to send WebSocket notification for reminder {reminder_id}: {ws_error}")
                    
                    # Send email notification if user has email notifications enabled
                    try:
                        await _send_reminder_email_notification(
                            user_id=user_id,
                            reminder_prompt=prompt,
                            trigger_time=format_reminder_time(current_time, timezone),
                            chat_id=result_data.get("chat_id", ""),
                            chat_title=result_data.get("chat_title"),
                            is_new_chat=result_data.get("is_new_chat", True),
                            directus_service=directus_service,
                        )
                    except Exception as email_error:
                        # Email notification failure should not fail the reminder
                        logger.warning(f"Failed to send email notification for reminder {reminder_id}: {email_error}")

                if not success:
                    logger.error(f"Failed to process reminder {reminder_id}")
                    error_count += 1
                    continue

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


async def _create_new_chat_with_reminder(
    reminder: Dict[str, Any],
    message_content: str,
    encryption_service,
    directus_service,
    cache_service,
) -> tuple[bool, Dict[str, Any]]:
    """
    Create a new chat with the reminder as a system message.
    
    Returns:
        Tuple of (success: bool, result_data: dict with chat_id, message_id, encrypted_content)
    """
    try:
        user_id = reminder.get("user_id")
        vault_key_id = reminder.get("vault_key_id")
        reminder_id = reminder.get("reminder_id")
        encrypted_new_chat_title = reminder.get("encrypted_new_chat_title")

        # Generate IDs
        chat_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        now_ts = int(time.time())

        # Decrypt the chat title
        chat_title = "Reminder"
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

        # Hash user_id for Directus storage
        import hashlib
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()

        # Encrypt the title and message for storage
        encrypted_title, _ = await encryption_service.encrypt_with_user_key(
            plaintext=chat_title,
            key_id=vault_key_id
        )
        
        encrypted_content, _ = await encryption_service.encrypt_with_user_key(
            plaintext=message_content,
            key_id=vault_key_id
        )

        # Create the chat in Directus
        chat_payload = {
            "id": chat_id,
            "hashed_user_id": hashed_user_id,
            "encrypted_title": encrypted_title,
            "created_at": now_ts,
            "updated_at": now_ts,
            "messages_v": 1,
            "title_v": 1,
            "last_edited_overall_timestamp": now_ts,
            "last_message_timestamp": now_ts,
            "unread_count": 1,
        }

        created_chat, is_duplicate = await directus_service.chat.create_chat_in_directus(chat_payload)
        
        if not created_chat and not is_duplicate:
            logger.error(f"Failed to create chat for reminder {reminder_id}")
            return False, {}

        # Create the system message
        message_payload = {
            "id": message_id,
            "chat_id": chat_id,
            "hashed_user_id": hashed_user_id,
            "role": "system",
            "encrypted_content": encrypted_content,
            "created_at": now_ts,
        }

        created_message = await directus_service.chat.create_message_in_directus(message_payload)
        
        if not created_message:
            logger.error(f"Failed to create message for reminder {reminder_id}")
            return False, {}

        logger.info(f"Created new chat {chat_id} with reminder message for reminder {reminder_id}")
        
        # Return success with result data for WebSocket and email notifications
        return True, {
            "chat_id": chat_id,
            "message_id": message_id,
            "encrypted_content": encrypted_content,
            "encrypted_title": encrypted_title,
            "chat_title": chat_title,  # Plain text title for email
            "is_new_chat": True,
        }

    except Exception as e:
        logger.error(f"Error creating new chat with reminder: {e}", exc_info=True)
        return False, {}


async def _send_reminder_to_existing_chat(
    reminder: Dict[str, Any],
    message_content: str,
    encryption_service,
    directus_service,
    cache_service,
) -> tuple[bool, Dict[str, Any]]:
    """
    Send a reminder as a system message to an existing chat.
    
    Returns:
        Tuple of (success: bool, result_data: dict with chat_id, message_id, encrypted_content)
    """
    try:
        user_id = reminder.get("user_id")
        vault_key_id = reminder.get("vault_key_id")
        reminder_id = reminder.get("reminder_id")
        target_chat_id = reminder.get("target_chat_id")
        encrypted_chat_history = reminder.get("encrypted_chat_history")

        if not target_chat_id:
            logger.error(f"No target_chat_id for existing_chat reminder {reminder_id}")
            return False, {}

        message_id = str(uuid.uuid4())
        now_ts = int(time.time())

        # Hash user_id for Directus storage
        import hashlib
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()

        # Encrypt the message content
        encrypted_content, _ = await encryption_service.encrypt_with_user_key(
            plaintext=message_content,
            key_id=vault_key_id
        )

        # Restore cached chat history to AI cache if available
        if encrypted_chat_history:
            try:
                decrypted_history = await encryption_service.decrypt_with_user_key(
                    ciphertext=encrypted_chat_history,
                    key_id=vault_key_id
                )
                if decrypted_history:
                    chat_history = json.loads(decrypted_history)
                    # Restore to AI cache for context
                    # This allows the AI to continue the conversation with context
                    for msg in chat_history:
                        await cache_service.add_ai_message_to_history(
                            user_id=user_id,
                            chat_id=target_chat_id,
                            encrypted_message_json=json.dumps(msg)
                        )
                    logger.debug(f"Restored {len(chat_history)} messages to AI cache for reminder {reminder_id}")
            except Exception as e:
                logger.warning(f"Could not restore chat history for reminder {reminder_id}: {e}")

        # Create the system message in Directus
        message_payload = {
            "id": message_id,
            "chat_id": target_chat_id,
            "hashed_user_id": hashed_user_id,
            "role": "system",
            "encrypted_content": encrypted_content,
            "created_at": now_ts,
        }

        created_message = await directus_service.chat.create_message_in_directus(message_payload)
        
        if not created_message:
            logger.error(f"Failed to create message for reminder {reminder_id}")
            return False, {}

        # Update chat metadata
        try:
            await directus_service.chat.update_chat_fields_in_directus(
                chat_id=target_chat_id,
                fields_to_update={
                    "updated_at": now_ts,
                    "last_message_timestamp": now_ts,
                    "unread_count": 1,  # Mark as unread
                }
            )
        except Exception as e:
            logger.warning(f"Could not update chat metadata for reminder {reminder_id}: {e}")

        logger.info(f"Sent reminder message to existing chat {target_chat_id} for reminder {reminder_id}")
        
        # Return success with result data for WebSocket notification
        return True, {
            "chat_id": target_chat_id,
            "message_id": message_id,
            "encrypted_content": encrypted_content,
            "is_new_chat": False,
        }

    except Exception as e:
        logger.error(f"Error sending reminder to existing chat: {e}", exc_info=True)
        return False, {}


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
