# backend/apps/reminder/skills/set_reminder_skill.py
#
# Set Reminder skill implementation.
# Creates scheduled reminders with support for specific/random times, 
# new chat/existing chat targets, and repeating schedules.
#
# This skill stores reminders in PostgreSQL (Directus) as the durable source
# of truth, with vault encryption for all sensitive fields. Near-term reminders
# (within 48h) are also loaded into the Dragonfly hot cache for fast polling.

import logging
import uuid
import time
import json
import hashlib
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from celery import Celery

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.reminder.utils import (
    parse_specific_datetime,
    calculate_random_trigger,
    format_reminder_time,
    validate_timezone,
)

logger = logging.getLogger(__name__)


class SetReminderRequest(BaseModel):
    """Request model for set-reminder skill."""
    prompt: str = Field(..., description="The reminder message/prompt")
    trigger_type: str = Field(..., description="'specific' or 'random'")
    timezone: str = Field(..., description="User's timezone")

    # For specific trigger
    trigger_datetime: Optional[str] = Field(None, description="ISO 8601 datetime for specific trigger")

    # For random trigger
    random_start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    random_end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    random_time_start: Optional[str] = Field(None, description="Earliest time (HH:MM)")
    random_time_end: Optional[str] = Field(None, description="Latest time (HH:MM)")

    # Target configuration
    target_type: str = Field(default="new_chat", description="'new_chat' or 'existing_chat'")
    new_chat_title: Optional[str] = Field(None, description="Title for new chat")

    # Response type: "simple" = notification-only (no AI), "full" = AI executes a task
    response_type: str = Field(default="simple", description="'simple' for notification-only (no AI), 'full' for AI action trigger")

    # Repeat configuration
    repeat: Optional[Dict[str, Any]] = Field(None, description="Repeat configuration")


class SetReminderResponse(BaseModel):
    """Response model for set-reminder skill."""
    success: bool = Field(default=False, description="Whether the reminder was created successfully")
    reminder_id: Optional[str] = Field(None, description="UUID of the created reminder")
    trigger_at: Optional[int] = Field(None, description="Unix timestamp when reminder will fire")
    trigger_at_formatted: Optional[str] = Field(None, description="Human-readable trigger time")
    target_type: Optional[str] = Field(None, description="'new_chat' or 'existing_chat'")
    is_repeating: bool = Field(default=False, description="Whether this is a repeating reminder")
    prompt: Optional[str] = Field(None, description="The reminder prompt/content (echoed back for display)")
    message: Optional[str] = Field(None, description="Confirmation or informational message")
    email_notification_warning: Optional[str] = Field(None, description="Warning if email notifications not set up")
    error: Optional[str] = Field(None, description="Error message if creation failed")


class SetReminderSkill(BaseSkill):
    """
    Skill for creating scheduled reminders.
    
    Supports:
    - Specific time reminders (exact datetime)
    - Random time reminders (random time within date/time window)
    - New chat target (creates new chat when reminder fires)
    - Existing chat target (sends follow-up in current chat)
    - Repeating reminders (daily, weekly, monthly, custom interval)
    
    ARCHITECTURE (Hybrid PostgreSQL + Hot Cache):
    - Reminders are stored vault-encrypted in PostgreSQL (Directus) as source of truth
    - Near-term reminders (within 48h) are loaded into a Dragonfly hot cache
    - A Celery beat task polls the hot cache ZSET for due reminders every minute
    - A promotion task loads near-term reminders from DB -> cache twice daily
    - When a reminder fires, it creates a system message in the target chat
    - For existing_chat targets, chat history is stored with the reminder
    """

    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer: Optional[Celery] = None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None
    ):
        """Initialize SetReminderSkill."""
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer
        )
        
        if skill_operational_defaults:
            logger.debug(f"SetReminderSkill received operational_defaults: {skill_operational_defaults}")

    async def execute(
        self,
        prompt: str,
        trigger_type: str,
        timezone: str,
        trigger_datetime: Optional[str] = None,
        random_start_date: Optional[str] = None,
        random_end_date: Optional[str] = None,
        random_time_start: Optional[str] = None,
        random_time_end: Optional[str] = None,
        target_type: str = "new_chat",
        new_chat_title: Optional[str] = None,
        repeat: Optional[Dict[str, Any]] = None,
        response_type: str = "simple",
        # Context parameters passed by skill executor
        secrets_manager: Optional[SecretsManager] = None,
        cache_service=None,
        encryption_service=None,
        directus_service=None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        **kwargs
    ) -> SetReminderResponse:
        """
        Create a scheduled reminder.
        
        Args:
            prompt: The reminder message/prompt
            trigger_type: 'specific' or 'random'
            timezone: User's timezone (e.g., 'Europe/Berlin')
            trigger_datetime: ISO 8601 datetime (for specific trigger)
            random_start_date: Start date YYYY-MM-DD (for random trigger)
            random_end_date: End date YYYY-MM-DD (for random trigger)
            random_time_start: Earliest time HH:MM (for random trigger)
            random_time_end: Latest time HH:MM (for random trigger)
            target_type: 'new_chat' or 'existing_chat'
            new_chat_title: Title for new chat (required if target_type is 'new_chat')
            repeat: Optional repeat configuration dict
            response_type: "simple" for a brief nudge (no LLM), "full" for complete AI response
            secrets_manager: Secrets manager instance
            cache_service: Cache service instance
            encryption_service: Encryption service for vault operations
            directus_service: Directus service for user data
            user_id: Current user ID
            chat_id: Current chat ID
            **kwargs: Additional context
            
        Returns:
            SetReminderResponse with success status and reminder details
        """
        try:
            # Initialize services if not provided (skill runs in separate container)
            # Following the same pattern as other app skills (e.g., web/search_skill.py, videos/transcript_skill.py)
            if not cache_service:
                try:
                    from backend.core.api.app.services.cache import CacheService
                    cache_service = CacheService()
                    logger.debug("SetReminderSkill initialized its own CacheService instance")
                except Exception as e:
                    logger.error(f"Failed to initialize CacheService: {e}", exc_info=True)
                    return SetReminderResponse(
                        success=False,
                        error="Unable to create reminder at this time. Please try again later."
                    )
            
            if not encryption_service:
                try:
                    from backend.core.api.app.utils.encryption import EncryptionService
                    encryption_service = EncryptionService(cache_service=cache_service)
                    logger.debug("SetReminderSkill initialized its own EncryptionService instance")
                except Exception as e:
                    logger.error(f"Failed to initialize EncryptionService: {e}", exc_info=True)
                    return SetReminderResponse(
                        success=False,
                        error="Unable to create reminder at this time. Please try again later."
                    )
            
            if not directus_service:
                try:
                    from backend.core.api.app.services.directus.directus import DirectusService
                    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
                    logger.debug("SetReminderSkill initialized its own DirectusService instance")
                except Exception as e:
                    logger.warning(f"Failed to initialize DirectusService: {e}. Some features may be limited.")
                    # DirectusService is optional for core reminder creation, so continue
            
            if not user_id:
                logger.error("SetReminderSkill: User ID not available in execution context")
                return SetReminderResponse(
                    success=False,
                    error="Unable to create reminder at this time. Please try again later."
                )

            current_time = int(time.time())

            # DEDUPLICATION GUARD: Prevent the AI model from creating duplicate reminders
            # when it calls the set-reminder tool multiple times in the same response.
            # Check if a reminder with the same prompt was created by this user in
            # the last 60 seconds - if so, return the existing reminder as success.
            try:
                dedup_hashed_uid = hashlib.sha256(user_id.encode()).hexdigest()
                existing_reminders = []
                if directus_service:
                    try:
                        existing_reminders = await directus_service.reminder.get_user_reminders(
                            hashed_user_id=dedup_hashed_uid, status_filter="pending", limit=10
                        )
                    except Exception:
                        pass  # Dedup is best-effort
                if existing_reminders:
                    for existing in existing_reminders:
                        # Check if created within last 60 seconds
                        time_diff = current_time - existing.get("created_at", 0)
                        if 0 <= time_diff <= 60:
                            # Compare trigger_type + timezone as a dedup proxy.
                            # trigger_at is not yet parsed at this point, so we rely on the
                            # 60-second window + type + timezone to catch duplicates.
                            if (existing.get("trigger_type") == trigger_type
                                    and existing.get("timezone") == timezone):
                                logger.warning(
                                    f"DEDUP: Skipping duplicate set-reminder call for user {user_id} "
                                    f"in chat {chat_id} - reminder {existing.get('id') or existing.get('reminder_id')} "
                                    f"was created {time_diff}s ago with same parameters"
                                )
                                # Return success with existing reminder details
                                existing_trigger_formatted = format_reminder_time(
                                    existing.get("trigger_at", 0), timezone
                                )
                                return SetReminderResponse(
                                    success=True,
                                    reminder_id=existing.get("id") or existing.get("reminder_id"),
                                    trigger_at=existing_trigger_formatted,
                                    target_type=existing.get("target_type", target_type),
                                    is_repeating=existing.get("repeat_config") is not None,
                                    prompt=prompt,
                                    message=f"Reminder already set for {existing_trigger_formatted}.",
                                )
            except Exception as dedup_err:
                # Dedup check is best-effort, don't fail the skill
                logger.debug(f"Dedup check error (non-fatal): {dedup_err}")

            # Validate timezone
            if not validate_timezone(timezone):
                return SetReminderResponse(
                    success=False,
                    error=f"Invalid timezone: {timezone}"
                )

            # Validate trigger type and calculate trigger_at
            trigger_at: int
            random_config: Optional[Dict[str, Any]] = None

            if trigger_type == "specific":
                if not trigger_datetime:
                    return SetReminderResponse(
                        success=False,
                        error="trigger_datetime is required for specific trigger type"
                    )
                try:
                    trigger_at = parse_specific_datetime(trigger_datetime, timezone)
                except ValueError as e:
                    return SetReminderResponse(
                        success=False,
                        error=str(e)
                    )

            elif trigger_type == "random":
                if not random_start_date or not random_end_date:
                    return SetReminderResponse(
                        success=False,
                        error="random_start_date and random_end_date are required for random trigger type"
                    )
                try:
                    trigger_at, random_config = calculate_random_trigger(
                        start_date=random_start_date,
                        end_date=random_end_date,
                        timezone_str=timezone,
                        time_window_start=random_time_start,
                        time_window_end=random_time_end
                    )
                except ValueError as e:
                    return SetReminderResponse(
                        success=False,
                        error=str(e)
                    )
            else:
                return SetReminderResponse(
                    success=False,
                    error=f"Invalid trigger_type: {trigger_type}. Must be 'specific' or 'random'"
                )

            # Validate trigger is in the future
            if trigger_at <= current_time:
                return SetReminderResponse(
                    success=False,
                    error="Reminder time must be in the future"
                )

            # Validate target type
            if target_type not in ["new_chat", "existing_chat"]:
                return SetReminderResponse(
                    success=False,
                    error=f"Invalid target_type: {target_type}. Must be 'new_chat' or 'existing_chat'"
                )

            # For new_chat, title is required (or derive from prompt)
            if target_type == "new_chat" and not new_chat_title:
                # Derive title from prompt (first 50 chars)
                new_chat_title = prompt[:50] + ("..." if len(prompt) > 50 else "")

            # Get user's vault key for encryption
            user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
            if not user_vault_key_id:
                # Try to get from Directus
                if directus_service:
                    try:
                        user_profile = await directus_service.get_user_profile(user_id)
                        if user_profile and user_profile[1]:
                            user_vault_key_id = user_profile[1].get("vault_key_id")
                    except Exception as e:
                        logger.error(f"Error fetching user profile for vault key: {e}")
                
                if not user_vault_key_id:
                    return SetReminderResponse(
                        success=False,
                        error="Could not retrieve user's encryption key"
                    )

            # Encrypt the prompt
            encrypted_prompt, _ = await encryption_service.encrypt_with_user_key(
                plaintext=prompt,
                key_id=user_vault_key_id
            )

            # Encrypt new_chat_title if present
            encrypted_new_chat_title = None
            if new_chat_title:
                encrypted_new_chat_title, _ = await encryption_service.encrypt_with_user_key(
                    plaintext=new_chat_title,
                    key_id=user_vault_key_id
                )

            # For existing_chat target, cache the current chat history
            encrypted_chat_history = None
            target_chat_id = None
            
            if target_type == "existing_chat":
                if not chat_id:
                    return SetReminderResponse(
                        success=False,
                        error="chat_id is required for existing_chat target type"
                    )
                target_chat_id = chat_id
                
                # Get current chat history from AI cache
                try:
                    chat_history = await cache_service.get_ai_messages_history(
                        user_id=user_id,
                        chat_id=chat_id
                    )
                    if chat_history:
                        # Encrypt the chat history for storage
                        chat_history_json = json.dumps(chat_history)
                        encrypted_chat_history, _ = await encryption_service.encrypt_with_user_key(
                            plaintext=chat_history_json,
                            key_id=user_vault_key_id
                        )
                        logger.debug(f"Cached {len(chat_history)} messages for existing_chat reminder")
                except Exception as e:
                    logger.warning(f"Could not cache chat history for reminder: {e}")
                    # Continue without chat history - will be handled at fire time

            # Validate repeat configuration if provided
            if repeat:
                repeat_type = repeat.get("type")
                if repeat_type not in ["daily", "weekly", "monthly", "custom"]:
                    return SetReminderResponse(
                        success=False,
                        error=f"Invalid repeat type: {repeat_type}"
                    )
                
                if repeat_type == "custom":
                    if not repeat.get("interval") or not repeat.get("interval_unit"):
                        return SetReminderResponse(
                            success=False,
                            error="interval and interval_unit are required for custom repeat type"
                        )

            # Generate reminder ID
            reminder_id = str(uuid.uuid4())

            # Vault-encrypt user_id and chat IDs for DB storage (privacy)
            encrypted_user_id, _ = await encryption_service.encrypt_with_user_key(
                plaintext=user_id, key_id=user_vault_key_id
            )
            encrypted_target_chat_id = None
            if target_chat_id:
                encrypted_target_chat_id, _ = await encryption_service.encrypt_with_user_key(
                    plaintext=target_chat_id, key_id=user_vault_key_id
                )
            encrypted_created_in_chat_id = None
            if chat_id:
                encrypted_created_in_chat_id, _ = await encryption_service.encrypt_with_user_key(
                    plaintext=chat_id, key_id=user_vault_key_id
                )

            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            safe_response_type = response_type if response_type in ("simple", "full") else "simple"

            # Build the Directus (DB) record — source of truth
            db_reminder = {
                "id": reminder_id,
                "hashed_user_id": hashed_user_id,
                "encrypted_user_id": encrypted_user_id,
                "vault_key_id": user_vault_key_id,
                "encrypted_prompt": encrypted_prompt,
                "encrypted_chat_history": encrypted_chat_history,
                "encrypted_new_chat_title": encrypted_new_chat_title,
                "encrypted_target_chat_id": encrypted_target_chat_id,
                "encrypted_created_in_chat_id": encrypted_created_in_chat_id,
                "trigger_type": trigger_type,
                "trigger_at": trigger_at,
                "target_type": target_type,
                "random_config": random_config,
                "repeat_config": repeat,
                "status": "pending",
                "response_type": safe_response_type,
                "occurrence_count": 0,
                "created_at": current_time,
                "timezone": timezone,
            }

            # Write to PostgreSQL via Directus (durable source of truth)
            db_success = False
            if directus_service:
                db_success = await directus_service.reminder.create_reminder(db_reminder)

            if not db_success:
                logger.error(f"Failed to create reminder {reminder_id} in database")
                return SetReminderResponse(
                    success=False,
                    error="Failed to create reminder"
                )

            # Load into hot cache if within the 48-hour window
            hot_window_seconds = 48 * 3600
            if trigger_at <= current_time + hot_window_seconds:
                # Cache version includes user_id in plaintext for WebSocket delivery
                cache_data = dict(db_reminder)
                cache_data["reminder_id"] = reminder_id
                cache_data["user_id"] = user_id  # Plaintext in cache (ephemeral)
                cache_data["target_chat_id"] = target_chat_id  # Plaintext in cache
                cache_data["created_in_chat_id"] = chat_id
                await cache_service.load_reminder_into_cache(cache_data)

            # Format trigger time for response
            trigger_at_formatted = format_reminder_time(trigger_at, timezone)

            # Check if user has email notifications configured.
            # If not, send a real-time WebSocket notification prompting the user to
            # activate email notifications so they don't miss the reminder when offline.
            # The notification includes an action button that deep-links to the
            # email notification settings page (chat/notifications).
            email_warning = None
            try:
                email_notifications_active = False
                if directus_service:
                    user_profile = await directus_service.get_user_profile(user_id)
                    if user_profile and user_profile[1]:
                        email_notifications_active = bool(
                            user_profile[1].get("email_notifications_enabled", False)
                        )

                if not email_notifications_active:
                    email_warning = (
                        "Tip: Set up email notifications in your account settings "
                        "to receive reminder alerts even when you're not using the app."
                    )
                    # Publish a user_notification WebSocket event so the client
                    # immediately shows a toast with a deep-link button to settings.
                    # Channel format matches base_task.publish_websocket_event:
                    #   websocket:user:{user_id}
                    # The websockets.py "Embed Data Listener" relays any event on
                    # websocket:user:* to the correct device via broadcast_to_user_specific_event.
                    ws_channel = f"websocket:user:{user_id}"
                    ws_payload = {
                        "event": "user_notification",
                        "type": "user_notification",
                        "event_for_client": "user_notification",
                        "payload": {
                            "user_id": user_id,
                            "notification_type": "warning",
                            "message": (
                                "Activate email notifications now to not miss your reminder."
                            ),
                            "action_label": "Go to Settings",
                            "action_deep_link": "chat/notifications",
                            "duration": 12000,
                        },
                    }
                    try:
                        await cache_service.publish_event(ws_channel, ws_payload)
                        logger.info(
                            f"Published email-notifications prompt WebSocket event "
                            f"for user {user_id[:8]}..."
                        )
                    except Exception as ws_err:
                        # WS notification failure must not fail reminder creation
                        logger.warning(
                            f"Could not publish email-notification prompt WS event "
                            f"for user {user_id[:8]}...: {ws_err}"
                        )
            except Exception as e:
                logger.debug(f"Could not check email notification settings: {e}")

            # Build confirmation message
            is_repeating = repeat is not None
            repeat_info = ""
            if is_repeating:
                repeat_type = repeat.get("type", "")
                if repeat_type == "daily":
                    repeat_info = " (repeating daily)"
                elif repeat_type == "weekly":
                    repeat_info = " (repeating weekly)"
                elif repeat_type == "monthly":
                    repeat_info = " (repeating monthly)"
                elif repeat_type == "custom":
                    interval = repeat.get("interval", 1)
                    unit = repeat.get("interval_unit", "days")
                    repeat_info = f" (repeating every {interval} {unit})"

            target_info = "create a new chat" if target_type == "new_chat" else "send a follow-up in this chat"
            
            message = (
                f"Reminder set for {trigger_at_formatted}{repeat_info}. "
                f"When it fires, I'll {target_info} with your reminder."
            )

            logger.info(f"Created reminder {reminder_id} for user {user_id}, trigger_at={trigger_at}")

            return SetReminderResponse(
                success=True,
                reminder_id=reminder_id,
                trigger_at=trigger_at,
                trigger_at_formatted=trigger_at_formatted,
                target_type=target_type,
                is_repeating=is_repeating,
                prompt=prompt,  # Echo back the prompt for embed display
                message=message,
                email_notification_warning=email_warning
            )

        except Exception as e:
            logger.error(f"Error creating reminder: {e}", exc_info=True)
            return SetReminderResponse(
                success=False,
                error=f"Failed to create reminder: {str(e)}"
            )
