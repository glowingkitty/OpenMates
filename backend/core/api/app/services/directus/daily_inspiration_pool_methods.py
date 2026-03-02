# backend/core/api/app/services/directus/daily_inspiration_pool_methods.py
"""
Directus methods for the daily_inspiration_pool collection.

Architecture:
- Stores cleartext copies of personalized daily inspirations (no PII).
- Capped at 100 entries (oldest evicted when full).
- Deduplicates by youtube_id (keeps the entry with higher interaction_count).
- Provides an aggregate interaction counter (no user association).
- Queried by the daily defaults selection job to pick top 3 per language.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService

logger = logging.getLogger(__name__)

COLLECTION = "daily_inspiration_pool"
MAX_POOL_SIZE = 100


class DailyInspirationPoolMethods:
    """Directus CRUD for the daily_inspiration_pool collection."""

    def __init__(self, directus_service_instance: "DirectusService") -> None:
        self.directus_service = directus_service_instance

    # ──────────────────────────────────────────────────────────────────────────
    # Write: add inspiration to pool (called after personalized generation)
    # ──────────────────────────────────────────────────────────────────────────

    async def add_to_pool(
        self,
        youtube_id: str,
        language: str,
        phrase: str,
        title: str,
        assistant_response: str,
        category: str,
        content_type: str,
        video_title: Optional[str] = None,
        video_thumbnail_url: Optional[str] = None,
        video_channel_name: Optional[str] = None,
        video_view_count: Optional[int] = None,
        video_duration_seconds: Optional[int] = None,
        video_published_at: Optional[str] = None,
        follow_up_suggestions: Optional[List[str]] = None,
        generated_at: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Add an inspiration to the pool.  If an entry with the same youtube_id
        already exists, skip (keep the existing one — it may already have
        interactions).

        After insertion, enforces the MAX_POOL_SIZE cap.

        Returns the created/existing record, or None on failure.
        """
        try:
            # Check for existing entry with same youtube_id (deduplication)
            existing = await self._get_by_youtube_id(youtube_id)
            if existing:
                logger.debug(
                    "[InspirationPool] Skipping duplicate youtube_id=%s (pool entry already exists)",
                    youtube_id,
                )
                return existing

            now_iso = datetime.now(timezone.utc).isoformat()
            payload: Dict[str, Any] = {
                "youtube_id": youtube_id,
                "language": language,
                "phrase": phrase,
                "title": title or "",
                "assistant_response": assistant_response or "",
                "category": category,
                "content_type": content_type or "video",
                "video_title": video_title,
                "video_thumbnail_url": video_thumbnail_url,
                "video_channel_name": video_channel_name,
                "video_view_count": video_view_count,
                "video_duration_seconds": video_duration_seconds,
                "video_published_at": video_published_at,
                "follow_up_suggestions": json.dumps(follow_up_suggestions or []),
                "interaction_count": 0,
                "generated_at": generated_at or int(time.time()),
                "created_at": now_iso,
            }

            success, result = await self.directus_service.create_item(COLLECTION, payload)
            if not success:
                logger.error(
                    "[InspirationPool] Failed to create pool entry for youtube_id=%s: %s",
                    youtube_id,
                    result,
                )
                return None

            logger.info(
                "[InspirationPool] Added pool entry: youtube_id=%s, lang=%s, category=%s",
                youtube_id,
                language,
                category,
            )

            # Enforce cap — delete oldest entries beyond MAX_POOL_SIZE
            await self.enforce_pool_cap()

            return result

        except Exception as exc:
            logger.error(
                "[InspirationPool] add_to_pool failed for youtube_id=%s: %s",
                youtube_id,
                exc,
                exc_info=True,
            )
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Read: get pool entries for daily defaults selection
    # ──────────────────────────────────────────────────────────────────────────

    async def get_pool_entries_by_language(
        self,
        language: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get pool entries for a given language, ordered newest first.

        Used by the daily defaults selection job to score and pick top 3.
        """
        try:
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "filter": {"language": {"_eq": language}},
                    "sort": ["-generated_at"],
                    "limit": limit,
                },
                admin_required=True,
            )
            return items or []
        except Exception as exc:
            logger.error(
                "[InspirationPool] get_pool_entries_by_language failed for lang=%s: %s",
                language,
                exc,
                exc_info=True,
            )
            return []

    async def get_all_pool_entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all pool entries, ordered newest first."""
        try:
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "sort": ["-generated_at"],
                    "limit": limit,
                },
                admin_required=True,
            )
            return items or []
        except Exception as exc:
            logger.error(
                "[InspirationPool] get_all_pool_entries failed: %s",
                exc,
                exc_info=True,
            )
            return []

    async def get_pool_languages(self) -> List[str]:
        """
        Get a list of distinct languages present in the pool.

        Uses a GROUP BY query via Directus aggregate.
        Falls back to fetching all entries and extracting unique languages.
        """
        try:
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "fields": ["language"],
                    "groupBy": ["language"],
                    "limit": 100,
                },
                admin_required=True,
            )
            if items:
                return [item.get("language") for item in items if item.get("language")]
        except Exception:
            pass

        # Fallback: fetch all and deduplicate
        try:
            items = await self.directus_service.get_items(
                COLLECTION,
                {"fields": ["language"], "limit": MAX_POOL_SIZE},
                admin_required=True,
            )
            if items:
                return list({item.get("language") for item in items if item.get("language")})
        except Exception as exc:
            logger.error(
                "[InspirationPool] get_pool_languages failed: %s", exc, exc_info=True
            )

        return []

    # ──────────────────────────────────────────────────────────────────────────
    # Interaction counter (aggregate, no user association)
    # ──────────────────────────────────────────────────────────────────────────

    async def increment_interaction(self, pool_entry_id: str) -> bool:
        """
        Increment the interaction_count for a pool entry by 1.

        Called when any user opens an inspiration that was sourced from this
        pool entry.  No user ID is stored — purely aggregate.

        Returns True on success, False on failure.
        """
        try:
            # Fetch current count
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "filter": {"id": {"_eq": pool_entry_id}},
                    "fields": ["id", "interaction_count"],
                    "limit": 1,
                },
                admin_required=True,
            )
            if not items:
                logger.warning(
                    "[InspirationPool] increment_interaction: pool entry not found id=%s",
                    pool_entry_id,
                )
                return False

            current_count = items[0].get("interaction_count", 0) or 0
            result = await self.directus_service.update_item(
                COLLECTION,
                pool_entry_id,
                {"interaction_count": current_count + 1},
                admin_required=True,
            )
            return result is not None

        except Exception as exc:
            logger.error(
                "[InspirationPool] increment_interaction failed for id=%s: %s",
                pool_entry_id,
                exc,
                exc_info=True,
            )
            return False

    async def increment_interaction_by_youtube_id(self, youtube_id: str) -> bool:
        """
        Increment interaction_count for the pool entry matching a youtube_id.

        Convenience method used when we only know the video ID (from the
        inspiration the user opened), not the pool entry's Directus UUID.
        """
        try:
            entry = await self._get_by_youtube_id(youtube_id)
            if not entry:
                return False
            entry_id = entry.get("id")
            if not entry_id:
                return False
            return await self.increment_interaction(str(entry_id))
        except Exception as exc:
            logger.error(
                "[InspirationPool] increment_interaction_by_youtube_id failed for yt=%s: %s",
                youtube_id,
                exc,
                exc_info=True,
            )
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Cap enforcement
    # ──────────────────────────────────────────────────────────────────────────

    async def enforce_pool_cap(self) -> int:
        """
        Enforce the MAX_POOL_SIZE cap.  Deletes the oldest entries (by
        generated_at) beyond the cap.

        Returns the number of deleted entries.
        """
        try:
            # Fetch all entries ordered oldest first
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "fields": ["id", "generated_at"],
                    "sort": ["-generated_at"],
                    "limit": MAX_POOL_SIZE + 50,  # fetch a few extra to find overflow
                },
                admin_required=True,
            )

            if not items or len(items) <= MAX_POOL_SIZE:
                return 0

            # Entries beyond the cap (oldest)
            overflow = items[MAX_POOL_SIZE:]
            deleted = 0

            for entry in overflow:
                entry_id = entry.get("id")
                if not entry_id:
                    continue
                try:
                    success = await self.directus_service.delete_item(
                        COLLECTION, str(entry_id)
                    )
                    if success:
                        deleted += 1
                except Exception as del_exc:
                    logger.warning(
                        "[InspirationPool] Failed to delete overflow entry id=%s: %s",
                        entry_id,
                        del_exc,
                    )

            if deleted > 0:
                logger.info(
                    "[InspirationPool] enforce_pool_cap: deleted %d overflow entries (cap=%d)",
                    deleted,
                    MAX_POOL_SIZE,
                )
            return deleted

        except Exception as exc:
            logger.error(
                "[InspirationPool] enforce_pool_cap failed: %s", exc, exc_info=True
            )
            return 0

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _get_by_youtube_id(self, youtube_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a pool entry by its YouTube video ID."""
        try:
            items = await self.directus_service.get_items(
                COLLECTION,
                {
                    "filter": {"youtube_id": {"_eq": youtube_id}},
                    "limit": 1,
                },
                admin_required=True,
            )
            return items[0] if items else None
        except Exception as exc:
            logger.error(
                "[InspirationPool] _get_by_youtube_id failed for yt=%s: %s",
                youtube_id,
                exc,
            )
            return None
