# backend/apps/reminder/skills/set_reminder_skill.py
#
# Set Reminder skill implementation.
# Creates scheduled reminders with support for specific/random times, 
# new chat/existing chat targets, and repeating schedules.
#
# This skill stores reminders vault-encrypted in cache for processing
# by the scheduled Celery task.

import logging
import uuid
import time
import json
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
    
    ARCHITECTURE:
    - Reminders are stored vault-encrypted in Dragonfly cache
    - A Celery beat task polls for due reminders every minute
    - When a reminder fires, it creates a system message in target chat
    - For existing_chat targets, chat history is cached with the reminder
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
            current_time = int(time.time())
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

            # Build reminder data
            reminder_data = {
                "reminder_id": reminder_id,
                "user_id": user_id,
                "vault_key_id": user_vault_key_id,
                "encrypted_prompt": encrypted_prompt,
                "encrypted_chat_history": encrypted_chat_history,
                "encrypted_new_chat_title": encrypted_new_chat_title,
                "trigger_type": trigger_type,
                "trigger_at": trigger_at,
                "random_config": random_config,
                "target_type": target_type,
                "target_chat_id": target_chat_id,
                "repeat_config": repeat,
                "created_at": current_time,
                "created_in_chat_id": chat_id,
                "occurrence_count": 0,
                "status": "pending",
                "timezone": timezone,
            }

            # Store reminder in cache
            success = await cache_service.create_reminder(reminder_data)
            
            if not success:
                return SetReminderResponse(
                    success=False,
                    error="Failed to create reminder in cache"
                )

            # Format trigger time for response
            trigger_at_formatted = format_reminder_time(trigger_at, timezone)

            # Check if user has email notifications configured
            email_warning = None
            try:
                if directus_service:
                    user_profile = await directus_service.get_user_profile(user_id)
                    if user_profile and user_profile[1]:
                        # Check for email notification settings
                        notification_email = user_profile[1].get("notification_email")
                        email_notifications_enabled = user_profile[1].get("email_notifications_enabled", False)
                        
                        if not notification_email or not email_notifications_enabled:
                            email_warning = (
                                "Tip: Set up email notifications in your account settings "
                                "to receive reminder alerts even when you're not using the app."
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
                message=message,
                email_notification_warning=email_warning
            )

        except Exception as e:
            logger.error(f"Error creating reminder: {e}", exc_info=True)
            return SetReminderResponse(
                success=False,
                error=f"Failed to create reminder: {str(e)}"
            )
