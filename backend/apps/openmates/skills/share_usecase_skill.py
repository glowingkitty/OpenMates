# backend/apps/openmates/skills/share_usecase_skill.py
#
# Share Use-Case skill implementation.
# Anonymously stores a user's summarized use cases to help improve the OpenMates platform.
# IMPORTANT: This skill deliberately does NOT store any user identifier.
# The data is fully anonymous — only the summary text and language are persisted.

import logging
import os
import time
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from celery import Celery

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

# Maximum allowed length for the use-case summary text
MAX_SUMMARY_LENGTH = 3000

# Valid ISO 639-1 language codes (subset — extend as needed)
VALID_LANGUAGES = {
    "en",
    "de",
    "fr",
    "es",
    "it",
    "pt",
    "nl",
    "pl",
    "sv",
    "da",
    "no",
    "fi",
    "cs",
    "ro",
    "hu",
    "bg",
    "hr",
    "sk",
    "sl",
    "uk",
    "ru",
    "ja",
    "ko",
    "zh",
    "ar",
    "hi",
    "tr",
    "el",
    "he",
    "th",
}


class ShareUsecaseRequest(BaseModel):
    """Request model for the share-usecase skill (REST API documentation)."""

    summary: str = Field(
        ...,
        description="A brief summary (2-5 sentences) of what the user wants to use "
        "OpenMates for, as discussed in the conversation."
    )
    language: str = Field(
        ...,
        description="ISO 639-1 language code of the conversation (e.g., 'en', 'de')"
    )


class ShareUsecaseResponse(BaseModel):
    """Response model for the share-usecase skill."""

    success: bool = Field(default=False)
    message: Optional[str] = Field(None)
    error: Optional[str] = Field(None)


class ShareUsecaseSkill(BaseSkill):
    """
    Skill for anonymously sharing a user's intended use-case summary
    with the OpenMates team.

    The summary is stored in the 'onboarding_usecases' Directus collection
    with NO user identifier attached. Only the summary text, language, and
    a timestamp are persisted.
    """

    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "production",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer: Optional[Celery] = None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None,
    ):
        """Initialize ShareUsecaseSkill."""
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
        )

    async def execute(
        self,
        summary: str,
        language: str,
        # Context parameters injected by BaseApp (we accept but deliberately ignore user_id)
        cache_service=None,
        encryption_service=None,
        directus_service=None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> ShareUsecaseResponse:
        """
        Store the user's use-case summary anonymously.

        Args:
            summary: Brief summary (2-5 sentences) of what the user wants to use OpenMates for.
            language: ISO 639-1 language code of the conversation.
            directus_service: Directus CMS client (lazy-initialized if not provided).
            cache_service: Cache service (needed for DirectusService initialization).
            encryption_service: Encryption service (needed for DirectusService initialization).
            user_id: Deliberately NOT stored — accepted only because BaseApp injects it.
            **kwargs: Additional context (ignored).

        Returns:
            ShareUsecaseResponse with success status.
        """
        try:
            # --- Validation ---
            if not summary or not summary.strip():
                return ShareUsecaseResponse(
                    success=False,
                    error="Summary text is empty. Please provide a description of your use cases.",
                )

            summary = summary.strip()
            if len(summary) > MAX_SUMMARY_LENGTH:
                return ShareUsecaseResponse(
                    success=False,
                    error=f"Summary is too long ({len(summary)} characters). "
                    f"Please keep it under {MAX_SUMMARY_LENGTH} characters.",
                )

            language = (language or "en").strip().lower()
            if language not in VALID_LANGUAGES:
                # Gracefully fall back to 'en' rather than rejecting
                logger.warning(
                    f"ShareUsecaseSkill: Unknown language code '{language}', falling back to 'en'"
                )
                language = "en"

            # --- Initialize Directus service if not provided ---
            if not directus_service:
                try:
                    if not cache_service:
                        from backend.core.api.app.services.cache import CacheService

                        cache_service = CacheService()

                    from backend.core.api.app.services.directus.directus import (
                        DirectusService,
                    )

                    directus_service = DirectusService(
                        cache_service=cache_service,
                        encryption_service=encryption_service,
                    )
                    logger.debug(
                        "ShareUsecaseSkill: Initialized own DirectusService instance"
                    )
                except Exception as e:
                    logger.error(
                        f"ShareUsecaseSkill: Failed to initialize DirectusService: {e}",
                        exc_info=True,
                    )
                    return ShareUsecaseResponse(
                        success=False,
                        error="Unable to save your feedback at this time. Please try again later.",
                    )

            # --- Store anonymously (NO user_id) ---
            payload = {
                "summary": summary,
                "language": language,
                "timestamp": int(time.time()),
            }

            success, result = await directus_service.create_item(
                "onboarding_usecases", payload
            )

            if success:
                logger.info(
                    f"ShareUsecaseSkill: Anonymous use-case summary stored successfully "
                    f"(language={language}, length={len(summary)} chars)"
                )

                # --- Notify the server admin by email (fire-and-forget via Celery) ---
                # The email is intentionally anonymous: only the summary text and language
                # are forwarded — no user identifier is included.
                admin_email = os.getenv("SERVER_OWNER_EMAIL")
                if admin_email and self.celery_producer:
                    try:
                        self.celery_producer.send_task(
                            name=(
                                "app.tasks.email_tasks"
                                ".usecase_submitted_email_task"
                                ".send_usecase_submitted_notification"
                            ),
                            kwargs={
                                "admin_email": admin_email,
                                "summary": summary,
                                "language": language,
                            },
                            queue="email",
                        )
                        logger.info(
                            f"ShareUsecaseSkill: Dispatched use-case submission email "
                            f"notification to admin (language={language})"
                        )
                    except Exception as e:
                        # Non-fatal: the submission was already stored — only the admin
                        # notification failed. Log the error so it is visible but do NOT
                        # return a failure response to the user.
                        logger.error(
                            f"ShareUsecaseSkill: Failed to dispatch admin email notification: {e}",
                            exc_info=True,
                        )
                elif not admin_email:
                    logger.warning(
                        "ShareUsecaseSkill: SERVER_OWNER_EMAIL not set — "
                        "skipping admin email notification for use-case submission."
                    )
                elif not self.celery_producer:
                    logger.warning(
                        "ShareUsecaseSkill: celery_producer not available — "
                        "skipping admin email notification for use-case submission."
                    )

                return ShareUsecaseResponse(
                    success=True,
                    message="Thank you! Your feedback has been shared anonymously with the OpenMates team.",
                )
            else:
                logger.error(
                    f"ShareUsecaseSkill: Failed to store use-case summary: {result}"
                )
                return ShareUsecaseResponse(
                    success=False,
                    error="Failed to save your feedback. Please try again later.",
                )

        except Exception as e:
            logger.error(f"ShareUsecaseSkill: Unexpected error: {e}", exc_info=True)
            return ShareUsecaseResponse(
                success=False,
                error="An unexpected error occurred. Please try again later.",
            )
