# backend/core/api/app/services/directus/daily_inspiration_defaults_methods.py
"""
Directus methods for the daily_inspiration_defaults collection.

Architecture:
- Stores daily-selected "top 3" inspiration entries per language.
- Populated once per day by the daily defaults selection Celery task.
- Content is denormalized from daily_inspiration_pool to avoid JOINs.
- Old dates are cleaned up automatically.
- The public /v1/default-inspirations endpoint reads from this table.
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService

logger = logging.getLogger(__name__)

COLLECTION = "daily_inspiration_defaults"


class DailyInspirationDefaultsMethods:
    """Directus CRUD for the daily_inspiration_defaults collection."""

    def __init__(self, directus_service_instance: "DirectusService") -> None:
        self.directus_service = directus_service_instance

    # ──────────────────────────────────────────────────────────────────────────
    # Read: get today's defaults for a given language
    # ──────────────────────────────────────────────────────────────────────────

    async def get_defaults_for_date(
        self,
        date_str: str,
        language: str,
    ) -> List[Dict[str, Any]]:
        """
        Fetch today's default inspirations for a language.

        Args:
            date_str: Date string in YYYY-MM-DD format (UTC).
            language: Language code (e.g. 'en', 'de').

        Returns:
            List of up to 3 default inspiration records, ordered by position.
        """
        try:
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "filter": {
                        "_and": [
                            {"date": {"_eq": date_str}},
                            {"language": {"_eq": language}},
                        ]
                    },
                    "sort": ["position"],
                    "limit": 3,
                },
                admin_required=True,
            )
            return items or []
        except Exception as exc:
            logger.error(
                "[InspirationDefaults] get_defaults_for_date failed for date=%s lang=%s: %s",
                date_str,
                language,
                exc,
                exc_info=True,
            )
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # Write: set today's defaults (called by the daily selection job)
    # ──────────────────────────────────────────────────────────────────────────

    async def set_defaults_for_date(
        self,
        date_str: str,
        language: str,
        pool_entries: List[Dict[str, Any]],
    ) -> int:
        """
        Write the daily defaults for a language.  Deletes any existing entries
        for the same date+language first (idempotent).

        Args:
            date_str: Date string in YYYY-MM-DD format (UTC).
            language: Language code.
            pool_entries: List of up to 3 pool entry dicts (from daily_inspiration_pool)
                          to store as today's defaults.

        Returns:
            Number of entries successfully written.
        """
        # Delete existing entries for this date + language
        await self._delete_for_date_language(date_str, language)

        now_iso = datetime.now(timezone.utc).isoformat()
        created = 0

        for idx, entry in enumerate(pool_entries[:3]):
            position = idx + 1
            payload: Dict[str, Any] = {
                "date": date_str,
                "language": language,
                "position": position,
                "pool_entry_id": str(entry.get("id", "")),
                # Denormalized content
                "phrase": entry.get("phrase", ""),
                "title": entry.get("title", ""),
                "assistant_response": entry.get("assistant_response", ""),
                "category": entry.get("category", ""),
                "content_type": entry.get("content_type", "video"),
                "youtube_id": entry.get("youtube_id", ""),
                "video_title": entry.get("video_title"),
                "video_thumbnail_url": entry.get("video_thumbnail_url"),
                "video_channel_name": entry.get("video_channel_name"),
                "video_view_count": entry.get("video_view_count"),
                "video_duration_seconds": entry.get("video_duration_seconds"),
                "video_published_at": entry.get("video_published_at"),
                "follow_up_suggestions": entry.get("follow_up_suggestions", "[]"),
                "generated_at": entry.get("generated_at", 0),
                "created_at": now_iso,
            }

            try:
                success, _result = await self.directus_service.create_item(
                    COLLECTION, payload
                )
                if success:
                    created += 1
                else:
                    logger.warning(
                        "[InspirationDefaults] Failed to create default pos=%d for date=%s lang=%s",
                        position,
                        date_str,
                        language,
                    )
            except Exception as exc:
                logger.error(
                    "[InspirationDefaults] create_item failed for pos=%d date=%s lang=%s: %s",
                    position,
                    date_str,
                    language,
                    exc,
                    exc_info=True,
                )

        if created > 0:
            logger.info(
                "[InspirationDefaults] Set %d defaults for date=%s lang=%s",
                created,
                date_str,
                language,
            )
        return created

    # ──────────────────────────────────────────────────────────────────────────
    # Cleanup: delete old dates
    # ──────────────────────────────────────────────────────────────────────────

    async def delete_old_defaults(self, before_date_str: str) -> int:
        """
        Delete all default entries with date < before_date_str.

        Args:
            before_date_str: YYYY-MM-DD string.  All entries with date strictly
                             before this will be deleted.

        Returns:
            Number of deleted entries.
        """
        try:
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "filter": {"date": {"_lt": before_date_str}},
                    "fields": ["id"],
                    "limit": 500,
                },
                admin_required=True,
            )

            if not items:
                return 0

            deleted = 0
            for item in items:
                item_id = item.get("id")
                if not item_id:
                    continue
                try:
                    success = await self.directus_service.delete_item(
                        COLLECTION, str(item_id)
                    )
                    if success:
                        deleted += 1
                except Exception as del_exc:
                    logger.warning(
                        "[InspirationDefaults] Failed to delete old default id=%s: %s",
                        item_id,
                        del_exc,
                    )

            if deleted > 0:
                logger.info(
                    "[InspirationDefaults] Cleaned up %d old defaults (before %s)",
                    deleted,
                    before_date_str,
                )
            return deleted

        except Exception as exc:
            logger.error(
                "[InspirationDefaults] delete_old_defaults failed: %s",
                exc,
                exc_info=True,
            )
            return 0

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _delete_for_date_language(
        self, date_str: str, language: str
    ) -> int:
        """Delete all entries for a specific date + language (idempotent write prep)."""
        try:
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "filter": {
                        "_and": [
                            {"date": {"_eq": date_str}},
                            {"language": {"_eq": language}},
                        ]
                    },
                    "fields": ["id"],
                    "limit": 10,
                },
                admin_required=True,
            )

            if not items:
                return 0

            deleted = 0
            for item in items:
                item_id = item.get("id")
                if not item_id:
                    continue
                try:
                    success = await self.directus_service.delete_item(
                        COLLECTION, str(item_id)
                    )
                    if success:
                        deleted += 1
                except Exception:
                    pass

            return deleted

        except Exception:
            return 0
