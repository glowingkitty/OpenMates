# backend/apps/reminder/tasks.py
#
# Celery tasks for the Reminder app.
# Includes the scheduled task that processes due reminders.

import logging
import asyncio
import hashlib
import json
import uuid
import time

import httpx

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

                # PRE-CREATE CHAT IN DIRECTUS (for new_chat targets)
                # This prevents a race condition where the frontend receives the
                # reminder_fired WebSocket event and sends chat_system_message_added
                # before the chat exists in Directus, causing "Chat not found" errors.
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
                        encryption_service=encryption_service,
                    )
                except Exception as email_error:
                    # Email notification failure should not fail the reminder
                    logger.warning(f"Failed to send email notification for reminder {reminder_id}: {email_error}")

                # ======================================================
                # DISPATCH AI ASK REQUEST
                # 
                # Trigger an AI response for the reminder. The AI will
                # receive the reminder prompt as the user message and
                # generate a helpful follow-up. This runs regardless of
                # whether the user is online.
                #
                # - If user is online: AI streams via WebSocket normally
                # - If user is offline: existing offline handling stores
                #   the response in pending delivery queue (60d) + sends email
                # ======================================================
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
                    # AI dispatch failure should not fail the reminder itself
                    logger.warning(f"Failed to dispatch AI request for reminder {reminder_id}: {ai_error}")

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
    
    Builds the message history from cached vault-encrypted chat history (for
    existing_chat reminders) and sends the reminder prompt as the latest user
    message. The AI response streams through the normal pipeline:
    - Online user: real-time WebSocket streaming
    - Offline user: response stored in pending delivery queue + email notification
    
    Args:
        user_id: User's UUID
        chat_id: Target chat ID
        message_id: The system message ID (for reference)
        prompt: The decrypted reminder prompt (plaintext)
        target_type: 'new_chat' or 'existing_chat'
        chat_title: Chat title (for new chats)
        reminder: Full reminder data dict
        encryption_service: EncryptionService instance
        cache_service: CacheService instance
    """
    vault_key_id = reminder.get("vault_key_id")
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

    # Build message history for AI context
    message_history = []

    if target_type == "existing_chat":
        # Restore cached chat history from vault-encrypted storage
        encrypted_chat_history = reminder.get("encrypted_chat_history")
        if encrypted_chat_history and vault_key_id:
            try:
                decrypted_history = await encryption_service.decrypt_with_user_key(
                    ciphertext=encrypted_chat_history,
                    key_id=vault_key_id
                )
                if decrypted_history:
                    cached_messages = json.loads(decrypted_history)
                    for msg in cached_messages:
                        # get_ai_messages_history() returns List[str] (JSON strings from Redis),
                        # so each element may be a raw JSON string that needs parsing first.
                        if isinstance(msg, str):
                            try:
                                msg = json.loads(msg)
                            except (json.JSONDecodeError, TypeError):
                                logger.debug("Skipping unparseable cached message for reminder AI request")
                                continue
                        
                        if not isinstance(msg, dict):
                            logger.debug(f"Skipping non-dict cached message (type={type(msg).__name__})")
                            continue
                        
                        # Extract content from vault-encrypted cache messages.
                        # These are server-side encrypted with encryption_key_user_server,
                        # so we need to decrypt the encrypted_content field.
                        encrypted_content = msg.get("encrypted_content")
                        if encrypted_content:
                            try:
                                decrypted_content = await encryption_service.decrypt_with_user_key(
                                    ciphertext=encrypted_content,
                                    key_id=vault_key_id
                                )
                                if decrypted_content:
                                    message_history.append({
                                        "content": decrypted_content,
                                        "role": msg.get("role", "user"),
                                        "created_at": msg.get("created_at", int(time.time())),
                                    })
                            except Exception as e_decrypt:
                                logger.debug(f"Could not decrypt cached message for reminder AI request: {e_decrypt}")
                                continue
                        else:
                            # Fallback: if content is plaintext (shouldn't happen in normal flow)
                            content = msg.get("content", "")
                            if content:
                                message_history.append({
                                    "content": content,
                                    "role": msg.get("role", "user"),
                                    "created_at": msg.get("created_at", int(time.time())),
                                })
                    logger.info(
                        f"Restored {len(message_history)} messages from cached history "
                        f"for reminder AI request"
                    )
            except Exception as e:
                logger.warning(f"Could not restore chat history for AI request: {e}")

    # Add the reminder prompt as the latest "user" message for the AI to respond to
    message_history.append({
        "content": prompt,
        "role": "user",
        "created_at": int(time.time()),
    })

    # Get user's timezone for AI context
    user_timezone = await cache_service.get_user_timezone(user_id)
    user_preferences = {}
    if user_timezone:
        user_preferences["timezone"] = user_timezone

    # Build AskSkillRequest payload
    # CRITICAL: For new_chat targets, always set chat_has_title=False so the
    # AI preprocessor generates title, icon_names, and category for the new chat.
    # Without this, the preprocessor sees chat_has_title=True (because we have a
    # decrypted title from the reminder) and skips icon/category generation,
    # resulting in chats with no icon and no category gradient color.
    chat_has_title_flag = False if target_type == "new_chat" else bool(chat_title)
    
    ask_request = {
        "chat_id": chat_id,
        "message_id": message_id,
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "message_history": message_history,
        "chat_has_title": chat_has_title_flag,
        "mate_id": None,  # Let preprocessor determine
        "active_focus_id": None,
        "user_preferences": user_preferences,
        "app_settings_memories_metadata": None,
    }

    # Dispatch to AI app via HTTP (same pattern as message_received_handler.py)
    ai_app_url = "http://app-ai:8000/skills/ask"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ai_app_url,
            json=ask_request,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        response_data = response.json()
        ai_task_id = response_data.get("task_id")

    if ai_task_id:
        # Mark this chat as having an active AI task
        await cache_service.set_active_ai_task(chat_id, ai_task_id)
        logger.info(
            f"Dispatched AI ask request for reminder in chat {chat_id}, "
            f"task_id={ai_task_id}"
        )
    else:
        logger.warning(
            f"AI app returned response but no task_id for reminder chat {chat_id}. "
            f"Response: {response_data}"
        )


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
    
    Checks if the user has email notifications enabled before sending.
    Decrypts the vault-encrypted notification email before dispatching.
    Uses a Celery task to send the email asynchronously.
    
    Args:
        user_id: User's UUID
        reminder_prompt: The decrypted reminder prompt text
        trigger_time: Human-readable trigger time string
        chat_id: The chat ID where the reminder was delivered
        chat_title: Optional title of the chat
        is_new_chat: Whether a new chat was created
        directus_service: Directus service for fetching user profile
        encryption_service: EncryptionService for decrypting vault-encrypted fields
        
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
        email_notifications_enabled = user_profile.get("email_notifications_enabled", False)
        if not email_notifications_enabled:
            logger.debug(f"User {user_id} does not have email notifications enabled")
            return False
        
        # Decrypt the vault-encrypted notification email
        encrypted_notification_email = user_profile.get("encrypted_notification_email")
        if not encrypted_notification_email:
            logger.debug(f"User {user_id} has no encrypted_notification_email configured")
            return False
        
        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            logger.warning(f"User {user_id} has no vault_key_id, cannot decrypt notification email")
            return False
        
        try:
            notification_email = await encryption_service.decrypt_with_user_key(
                encrypted_notification_email, vault_key_id
            )
        except Exception as decrypt_error:
            logger.error(f"Failed to decrypt notification email for user {user_id}: {decrypt_error}", exc_info=True)
            return False
        
        if not notification_email:
            logger.warning(f"Notification email decryption returned empty result for user {user_id}")
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
        
        logger.info(f"Dispatched reminder email notification for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error dispatching reminder email notification: {e}", exc_info=True)
        return False


@app.task(name="reminder.audit_pending_deliveries", base=BaseServiceTask, bind=True)
def audit_pending_deliveries(self):
    """
    Periodic task that audits pending delivery entries.
    
    Called by Celery Beat every 6 hours. It:
    1. Scans all pending delivery lists in cache
    2. Logs users who have undelivered messages (for monitoring)
    3. Redis TTL handles actual expiry (60 days) - this task is for audit/visibility
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

        return {
            "success": True,
            "users_with_pending": users_with_pending
        }

    except Exception as e:
        logger.error(f"Error auditing pending deliveries: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()


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
