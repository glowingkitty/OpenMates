# backend/apps/reminder/skills/cancel_reminder_skill.py
#
# Cancel Reminder skill implementation.
# Cancels a scheduled reminder by ID.

import logging
import hashlib
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from celery import Celery

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


class CancelReminderRequest(BaseModel):
    """Request model for cancel-reminder skill (REST API documentation)."""
    reminder_id: str = Field(..., description="The UUID of the reminder to cancel")


class CancelReminderResponse(BaseModel):
    """Response model for cancel-reminder skill."""
    success: bool = Field(default=False)
    reminder_id: Optional[str] = Field(None)
    message: Optional[str] = Field(None)
    error: Optional[str] = Field(None)


class CancelReminderSkill(BaseSkill):
    """
    Skill for cancelling a scheduled reminder.
    
    Marks the reminder as cancelled and removes it from the schedule index.
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
        """Initialize CancelReminderSkill."""
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
        reminder_id: str,
        # Context parameters
        secrets_manager: Optional[SecretsManager] = None,
        cache_service=None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> CancelReminderResponse:
        """
        Cancel a scheduled reminder.
        
        Args:
            reminder_id: The UUID of the reminder to cancel
            cache_service: Cache service instance
            user_id: Current user ID
            **kwargs: Additional context
            
        Returns:
            CancelReminderResponse with success status
        """
        try:
            # Initialize services if not provided (skill runs in separate container)
            # Following the same pattern as other app skills (e.g., web/search_skill.py, videos/transcript_skill.py)
            if not cache_service:
                try:
                    from backend.core.api.app.services.cache import CacheService
                    cache_service = CacheService()
                    logger.debug("CancelReminderSkill initialized its own CacheService instance")
                except Exception as e:
                    logger.error(f"Failed to initialize CacheService: {e}", exc_info=True)
                    return CancelReminderResponse(
                        success=False,
                        error="Unable to cancel reminder at this time. Please try again later."
                    )
            
            if not user_id:
                logger.error("CancelReminderSkill: User ID not available in execution context")
                return CancelReminderResponse(
                    success=False,
                    error="Unable to cancel reminder at this time. Please try again later."
                )

            if not reminder_id:
                return CancelReminderResponse(
                    success=False,
                    error="Reminder ID is required"
                )

            # Initialize directus_service if not provided
            directus_service = kwargs.get('directus_service')
            encryption_service = kwargs.get('encryption_service')
            if not directus_service:
                try:
                    if not encryption_service:
                        from backend.core.api.app.utils.encryption import EncryptionService
                        encryption_service = EncryptionService(cache_service=cache_service)
                    from backend.core.api.app.services.directus.directus import DirectusService
                    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
                except Exception as e:
                    logger.warning(f"Could not initialize DirectusService: {e}")
                    directus_service = None

            # Look up the reminder in the DB (source of truth)
            reminder = None
            if directus_service:
                try:
                    reminder = await directus_service.reminder.get_reminder(reminder_id)
                except Exception as db_err:
                    logger.error(f"Failed to query reminder {reminder_id} from DB: {db_err}")

            # Fallback: check cache if DB lookup failed
            if not reminder:
                reminder = await cache_service.get_reminder(reminder_id)

            if not reminder:
                return CancelReminderResponse(
                    success=False,
                    reminder_id=reminder_id,
                    error="Reminder not found"
                )

            # Verify ownership: check hashed_user_id or user_id
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            reminder_owner = reminder.get("hashed_user_id") or ""
            reminder_raw_owner = reminder.get("user_id") or ""

            if reminder_owner != hashed_user_id and reminder_raw_owner != user_id:
                return CancelReminderResponse(
                    success=False,
                    reminder_id=reminder_id,
                    error="You don't have permission to cancel this reminder"
                )

            # Check if already cancelled or fired
            current_status = reminder.get("status", "pending")
            if current_status == "cancelled":
                return CancelReminderResponse(
                    success=True,
                    reminder_id=reminder_id,
                    message="This reminder was already cancelled."
                )
            
            if current_status == "fired":
                return CancelReminderResponse(
                    success=False,
                    reminder_id=reminder_id,
                    error="This reminder has already been triggered and cannot be cancelled."
                )

            # Update DB status to cancelled (source of truth)
            db_success = True
            if directus_service:
                db_success = await directus_service.reminder.update_reminder(
                    reminder_id, {"status": "cancelled"}
                )

            if not db_success:
                return CancelReminderResponse(
                    success=False,
                    reminder_id=reminder_id,
                    error="Failed to cancel reminder"
                )

            # Remove from hot cache (if present)
            await cache_service.remove_reminder_from_cache(reminder_id)

            logger.info(f"Cancelled reminder {reminder_id} for user {user_id}")
            return CancelReminderResponse(
                success=True,
                reminder_id=reminder_id,
                message="Reminder has been cancelled successfully."
            )

        except Exception as e:
            logger.error(f"Error cancelling reminder {reminder_id}: {e}", exc_info=True)
            return CancelReminderResponse(
                success=False,
                reminder_id=reminder_id,
                error=f"Failed to cancel reminder: {str(e)}"
            )
