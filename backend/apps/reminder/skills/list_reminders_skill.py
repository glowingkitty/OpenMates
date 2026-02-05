# backend/apps/reminder/skills/list_reminders_skill.py
#
# List Reminders skill implementation.
# Retrieves and displays user's scheduled reminders.

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from celery import Celery

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.apps.reminder.utils import format_reminder_time

logger = logging.getLogger(__name__)


class ReminderInfo(BaseModel):
    """Information about a single reminder for display."""
    reminder_id: str
    prompt_preview: str = Field(description="First 100 chars of the reminder prompt")
    trigger_at: int
    trigger_at_formatted: str
    target_type: str
    is_repeating: bool
    status: str


class ListRemindersResponse(BaseModel):
    """Response model for list-reminders skill."""
    success: bool = Field(default=False)
    reminders: List[ReminderInfo] = Field(default_factory=list)
    total_count: int = Field(default=0)
    message: Optional[str] = Field(None)
    error: Optional[str] = Field(None)


class ListRemindersSkill(BaseSkill):
    """
    Skill for listing user's scheduled reminders.
    
    Retrieves reminders from cache, decrypts prompts, and returns
    formatted list for display.
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
        """Initialize ListRemindersSkill."""
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

    async def execute(
        self,
        status: str = "pending",
        # Context parameters
        secrets_manager: Optional[SecretsManager] = None,
        cache_service=None,
        encryption_service=None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> ListRemindersResponse:
        """
        List user's reminders.
        
        Args:
            status: Filter by status ("pending" or "all")
            cache_service: Cache service instance
            encryption_service: Encryption service for decrypting prompts
            user_id: Current user ID
            **kwargs: Additional context
            
        Returns:
            ListRemindersResponse with list of reminders
        """
        try:
            # Initialize services if not provided (skill runs in separate container)
            # Following the same pattern as other app skills (e.g., web/search_skill.py, videos/transcript_skill.py)
            if not cache_service:
                try:
                    from backend.core.api.app.services.cache import CacheService
                    cache_service = CacheService()
                    logger.debug("ListRemindersSkill initialized its own CacheService instance")
                except Exception as e:
                    logger.error(f"Failed to initialize CacheService: {e}", exc_info=True)
                    return ListRemindersResponse(
                        success=False,
                        error="Unable to list reminders at this time. Please try again later."
                    )
            
            if not encryption_service:
                try:
                    from backend.core.api.app.utils.encryption import EncryptionService
                    encryption_service = EncryptionService(cache_service=cache_service)
                    logger.debug("ListRemindersSkill initialized its own EncryptionService instance")
                except Exception as e:
                    logger.error(f"Failed to initialize EncryptionService: {e}", exc_info=True)
                    return ListRemindersResponse(
                        success=False,
                        error="Unable to list reminders at this time. Please try again later."
                    )
            
            if not user_id:
                logger.error("ListRemindersSkill: User ID not available in execution context")
                return ListRemindersResponse(
                    success=False,
                    error="Unable to list reminders at this time. Please try again later."
                )

            # Determine status filter
            status_filter = "pending" if status == "pending" else None

            # Get user's reminders from cache
            reminders = await cache_service.get_user_reminders(
                user_id=user_id,
                status_filter=status_filter
            )

            if not reminders:
                return ListRemindersResponse(
                    success=True,
                    reminders=[],
                    total_count=0,
                    message="You don't have any scheduled reminders."
                )

            # Process each reminder
            reminder_list: List[ReminderInfo] = []
            
            for reminder in reminders:
                try:
                    reminder_id = reminder.get("reminder_id", "")
                    vault_key_id = reminder.get("vault_key_id")
                    encrypted_prompt = reminder.get("encrypted_prompt", "")
                    trigger_at = reminder.get("trigger_at", 0)
                    timezone = reminder.get("timezone", "UTC")
                    target_type = reminder.get("target_type", "new_chat")
                    repeat_config = reminder.get("repeat_config")
                    reminder_status = reminder.get("status", "pending")

                    # Decrypt the prompt
                    prompt_preview = "[Unable to decrypt]"
                    if encrypted_prompt and vault_key_id:
                        try:
                            decrypted_prompt = await encryption_service.decrypt_with_user_key(
                                ciphertext=encrypted_prompt,
                                key_id=vault_key_id
                            )
                            if decrypted_prompt:
                                # Truncate for preview
                                prompt_preview = decrypted_prompt[:100]
                                if len(decrypted_prompt) > 100:
                                    prompt_preview += "..."
                        except Exception as e:
                            logger.warning(f"Could not decrypt reminder prompt: {e}")

                    # Format trigger time
                    trigger_at_formatted = format_reminder_time(trigger_at, timezone)

                    reminder_info = ReminderInfo(
                        reminder_id=reminder_id,
                        prompt_preview=prompt_preview,
                        trigger_at=trigger_at,
                        trigger_at_formatted=trigger_at_formatted,
                        target_type=target_type,
                        is_repeating=repeat_config is not None,
                        status=reminder_status
                    )
                    reminder_list.append(reminder_info)

                except Exception as e:
                    logger.warning(f"Error processing reminder: {e}")
                    continue

            # Sort by trigger_at ascending
            reminder_list.sort(key=lambda r: r.trigger_at)

            status_desc = "pending " if status == "pending" else ""
            message = f"You have {len(reminder_list)} {status_desc}reminder{'s' if len(reminder_list) != 1 else ''}."

            return ListRemindersResponse(
                success=True,
                reminders=reminder_list,
                total_count=len(reminder_list),
                message=message
            )

        except Exception as e:
            logger.error(f"Error listing reminders: {e}", exc_info=True)
            return ListRemindersResponse(
                success=False,
                error=f"Failed to list reminders: {str(e)}"
            )
