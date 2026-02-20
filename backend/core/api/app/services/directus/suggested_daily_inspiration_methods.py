# backend/core/api/app/services/directus/suggested_daily_inspiration_methods.py
"""
Methods for managing suggested daily inspirations.

Users can suggest YouTube video embeds as default Daily Inspiration entries.
Admins review, generate AI content for, and publish them.
Once published, they appear as default inspirations for all users.

Status flow:
  pending_approval → generating → pending_review → translating → published
  (or) generation_failed / translation_failed

Max 3 published entries at any time — publishing a 4th auto-deactivates the oldest.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Max published inspirations at any time
MAX_PUBLISHED_INSPIRATIONS = 3


class SuggestedDailyInspirationMethods:
    """Methods for managing suggested daily inspirations."""

    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def create_suggestion(
        self,
        suggested_by_user_id: str,
        video_url: str,
        video_id: str,
        video_title: Optional[str] = None,
        video_channel_name: Optional[str] = None,
        video_channel_id: Optional[str] = None,
        video_thumbnail: Optional[str] = None,
        video_duration_seconds: Optional[int] = None,
        video_duration_formatted: Optional[str] = None,
        video_view_count: Optional[int] = None,
        video_like_count: Optional[int] = None,
        video_published_at: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new suggestion entry in pending_approval status.

        Args:
            suggested_by_user_id: UUID of the user submitting the suggestion
            video_url: Full YouTube URL
            video_id: YouTube video ID
            video_title: Video title (original language)
            video_channel_name: Channel name
            video_channel_id: Channel ID
            video_thumbnail: Thumbnail URL
            video_duration_seconds: Duration in seconds
            video_duration_formatted: Formatted duration string
            video_view_count: View count at time of suggestion
            video_like_count: Like count at time of suggestion
            video_published_at: ISO date when the video was published

        Returns:
            Created record dict or None on failure
        """
        try:
            data = {
                "suggested_by_user_id": suggested_by_user_id,
                "status": "pending_approval",
                "video_url": video_url,
                "video_id": video_id,
                "video_title": video_title,
                "video_channel_name": video_channel_name,
                "video_channel_id": video_channel_id,
                "video_thumbnail": video_thumbnail,
                "video_duration_seconds": video_duration_seconds,
                "video_duration_formatted": video_duration_formatted,
                "video_view_count": video_view_count,
                "video_like_count": video_like_count,
                "video_published_at": video_published_at,
                "is_active": True,
                "suggested_at": datetime.now(timezone.utc).isoformat(),
            }
            result = await self.directus_service.create_item(
                "suggested_daily_inspirations", data, admin_required=True
            )
            logger.info(
                f"[SuggestedInspiration] Created suggestion for video_id={video_id} "
                f"by user={suggested_by_user_id[:8]}..."
            )
            return result
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to create suggestion for video_id={video_id}: {e}",
                exc_info=True,
            )
            raise

    async def get_pending_suggestions(self) -> List[Dict[str, Any]]:
        """
        Get all suggestions with status=pending_approval.

        Returns:
            List of pending suggestion records
        """
        try:
            items = await self.directus_service.get_items(
                "suggested_daily_inspirations",
                {
                    "filter": {
                        "status": {"_eq": "pending_approval"},
                        "is_active": {"_eq": True},
                    },
                    "sort": ["-suggested_at"],
                },
                admin_required=True,
            )
            return items or []
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to get pending suggestions: {e}",
                exc_info=True,
            )
            raise

    async def get_pending_review_suggestions(self) -> List[Dict[str, Any]]:
        """
        Get all suggestions with status=pending_review (content generated, awaiting admin confirm).

        Returns:
            List of pending_review records
        """
        try:
            items = await self.directus_service.get_items(
                "suggested_daily_inspirations",
                {
                    "filter": {
                        "status": {"_eq": "pending_review"},
                        "is_active": {"_eq": True},
                    },
                    "sort": ["-suggested_at"],
                },
                admin_required=True,
            )
            return items or []
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to get pending_review suggestions: {e}",
                exc_info=True,
            )
            raise

    async def get_all_admin_items(self) -> List[Dict[str, Any]]:
        """
        Get all active inspiration items (all statuses) for the admin panel.

        Returns:
            List of all active records, sorted by suggested_at desc
        """
        try:
            items = await self.directus_service.get_items(
                "suggested_daily_inspirations",
                {
                    "filter": {"is_active": {"_eq": True}},
                    "sort": ["-suggested_at"],
                },
                admin_required=True,
            )
            return items or []
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to get admin items: {e}",
                exc_info=True,
            )
            raise

    async def get_published_inspirations(self) -> List[Dict[str, Any]]:
        """
        Get all published inspirations ordered by approved_at desc.
        Used for the public default-inspirations endpoint.

        Returns:
            List of published records (max 3)
        """
        try:
            items = await self.directus_service.get_items(
                "suggested_daily_inspirations",
                {
                    "filter": {
                        "status": {"_eq": "published"},
                        "is_active": {"_eq": True},
                    },
                    "sort": ["-approved_at"],
                    "limit": MAX_PUBLISHED_INSPIRATIONS,
                },
                admin_required=True,
            )
            return items or []
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to get published inspirations: {e}",
                exc_info=True,
            )
            raise

    async def get_by_id(self, inspiration_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single inspiration record by its UUID.

        Args:
            inspiration_id: UUID of the record

        Returns:
            Record dict or None if not found
        """
        try:
            items = await self.directus_service.get_items(
                "suggested_daily_inspirations",
                {
                    "filter": {"id": {"_eq": inspiration_id}},
                    "limit": 1,
                },
                admin_required=True,
            )
            return items[0] if items else None
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to get by id={inspiration_id}: {e}",
                exc_info=True,
            )
            raise

    async def update_status(
        self,
        inspiration_id: str,
        status: str,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update the status of an inspiration record, optionally setting extra fields.

        Args:
            inspiration_id: UUID of the record
            status: New status string
            extra_fields: Additional fields to update alongside status

        Returns:
            Updated record dict or None on failure
        """
        try:
            data: Dict[str, Any] = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
            if extra_fields:
                data.update(extra_fields)
            result = await self.directus_service.update_item(
                "suggested_daily_inspirations", inspiration_id, data, admin_required=True
            )
            logger.info(f"[SuggestedInspiration] Updated id={inspiration_id} → status={status}")
            return result
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to update status for id={inspiration_id}: {e}",
                exc_info=True,
            )
            raise

    async def set_generated_content(
        self,
        inspiration_id: str,
        category: str,
        phrase: str,
        assistant_response: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Store AI-generated content (category, phrase, assistant_response) and
        transition status to pending_review.

        Args:
            inspiration_id: UUID of the record
            category: AI-generated category label
            phrase: AI-generated CTA phrase (English)
            assistant_response: AI-generated assistant context text (English)

        Returns:
            Updated record dict
        """
        return await self.update_status(
            inspiration_id,
            "pending_review",
            extra_fields={
                "category": category,
                "phrase": phrase,
                "assistant_response": assistant_response,
            },
        )

    async def confirm_inspiration(
        self,
        inspiration_id: str,
        admin_user_id: str,
        category: Optional[str] = None,
        phrase: Optional[str] = None,
        assistant_response: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Admin confirms the inspiration content and starts translation.
        Transitions status to 'translating'.
        Optionally updates editable fields if admin changed them.

        Args:
            inspiration_id: UUID of the record
            admin_user_id: UUID of the confirming admin
            category: Optional updated category
            phrase: Optional updated phrase
            assistant_response: Optional updated assistant_response

        Returns:
            Updated record dict
        """
        extra: Dict[str, Any] = {
            "approved_by_admin": admin_user_id,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        if category is not None:
            extra["category"] = category
        if phrase is not None:
            extra["phrase"] = phrase
        if assistant_response is not None:
            extra["assistant_response"] = assistant_response

        return await self.update_status(inspiration_id, "translating", extra_fields=extra)

    async def publish_inspiration(self, inspiration_id: str) -> Optional[Dict[str, Any]]:
        """
        Mark the inspiration as published.
        Callers should also call enforce_max_published() after this to trim old entries.

        Args:
            inspiration_id: UUID of the record

        Returns:
            Updated record dict
        """
        return await self.update_status(inspiration_id, "published")

    async def enforce_max_published(self) -> None:
        """
        Ensure at most MAX_PUBLISHED_INSPIRATIONS=3 published entries exist.
        If more than 3 are published, deactivates the oldest (by approved_at).
        """
        try:
            published = await self.directus_service.get_items(
                "suggested_daily_inspirations",
                {
                    "filter": {
                        "status": {"_eq": "published"},
                        "is_active": {"_eq": True},
                    },
                    "sort": ["approved_at"],  # Oldest first
                },
                admin_required=True,
            )
            published = published or []
            overflow = len(published) - MAX_PUBLISHED_INSPIRATIONS

            for i in range(overflow):
                oldest = published[i]
                oldest_id = oldest.get("id")
                if oldest_id:
                    await self.directus_service.update_item(
                        "suggested_daily_inspirations",
                        oldest_id,
                        {
                            "is_active": False,
                            "deactivated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        admin_required=True,
                    )
                    logger.info(
                        f"[SuggestedInspiration] Deactivated oldest published entry id={oldest_id} "
                        f"(overflow, total was {len(published)})"
                    )
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] enforce_max_published failed: {e}",
                exc_info=True,
            )
            raise

    async def deactivate_inspiration(self, inspiration_id: str) -> Optional[Dict[str, Any]]:
        """
        Soft-delete an inspiration entry (admin delete).

        Args:
            inspiration_id: UUID of the record

        Returns:
            Updated record dict
        """
        try:
            result = await self.directus_service.update_item(
                "suggested_daily_inspirations",
                inspiration_id,
                {
                    "is_active": False,
                    "deactivated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                admin_required=True,
            )
            logger.info(f"[SuggestedInspiration] Deactivated id={inspiration_id}")
            return result
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to deactivate id={inspiration_id}: {e}",
                exc_info=True,
            )
            raise

    async def get_translations(self, inspiration_id: str) -> List[Dict[str, Any]]:
        """
        Get all translation rows for an inspiration.

        Args:
            inspiration_id: UUID of the inspiration record

        Returns:
            List of translation records
        """
        try:
            items = await self.directus_service.get_items(
                "suggested_daily_inspiration_translations",
                {
                    "filter": {"inspiration_id": {"_eq": inspiration_id}},
                    "sort": ["language"],
                },
                admin_required=True,
            )
            return items or []
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to get translations for id={inspiration_id}: {e}",
                exc_info=True,
            )
            raise

    async def upsert_translation(
        self,
        inspiration_id: str,
        language: str,
        phrase: str,
        assistant_response: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create or update a translation row for an inspiration.

        Args:
            inspiration_id: UUID of the inspiration record
            language: Language code (e.g., 'de')
            phrase: Translated CTA phrase
            assistant_response: Translated assistant response

        Returns:
            Created/updated translation record
        """
        try:
            # Check if translation already exists
            existing = await self.directus_service.get_items(
                "suggested_daily_inspiration_translations",
                {
                    "filter": {
                        "inspiration_id": {"_eq": inspiration_id},
                        "language": {"_eq": language},
                    },
                    "limit": 1,
                },
                admin_required=True,
            )

            data: Dict[str, Any] = {
                "inspiration_id": inspiration_id,
                "language": language,
                "phrase": phrase,
            }
            if assistant_response is not None:
                data["assistant_response"] = assistant_response

            if existing:
                # Update existing
                translation_id = existing[0]["id"]
                result = await self.directus_service.update_item(
                    "suggested_daily_inspiration_translations",
                    translation_id,
                    data,
                    admin_required=True,
                )
            else:
                # Create new
                data["created_at"] = datetime.now(timezone.utc).isoformat()
                result = await self.directus_service.create_item(
                    "suggested_daily_inspiration_translations",
                    data,
                    admin_required=True,
                )

            return result
        except Exception as e:
            logger.error(
                f"[SuggestedInspiration] Failed to upsert translation "
                f"lang={language} for id={inspiration_id}: {e}",
                exc_info=True,
            )
            raise
