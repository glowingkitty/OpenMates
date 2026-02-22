"""
backend/core/api/app/services/directus/user_daily_inspiration_methods.py

Directus methods for user daily inspiration persistence.

Architecture:
- Each user's received daily inspirations are stored encrypted in this collection
- All content is encrypted client-side before reaching this service
- The server stores opaque encrypted blobs and metadata; never inspects content
- Used for cross-device sync and "re-login hours later" persistence
"""
import logging
import hashlib
import time
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService

logger = logging.getLogger(__name__)

COLLECTION = "user_daily_inspirations"

# Fields to return from Directus on fetch
INSPIRATION_ALL_FIELDS = (
    "id,"
    "daily_inspiration_id,"
    "hashed_user_id,"
    "embed_id,"
    "encrypted_phrase,"
    "encrypted_assistant_response,"
    "encrypted_title,"
    "encrypted_category,"
    "encrypted_icon,"
    "is_opened,"
    "opened_chat_id,"
    "generated_at,"
    "content_type,"
    "created_at,"
    "updated_at"
)


def _hash_user_id(user_id: str) -> str:
    """SHA256-hash user_id for storage (privacy-preserving)."""
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


class UserDailyInspirationMethods:
    """Directus CRUD for the user_daily_inspirations collection."""

    def __init__(self, directus_service_instance: "DirectusService") -> None:
        self.directus_service = directus_service_instance

    # ──────────────────────────────────────────────────────────────────────────
    # Write operations (called by POST /v1/daily-inspirations)
    # ──────────────────────────────────────────────────────────────────────────

    async def upsert_inspiration(
        self,
        user_id: str,
        inspiration: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Create or update a daily inspiration record for the user.

        The inspiration dict must contain at minimum:
          daily_inspiration_id, encrypted_phrase, encrypted_assistant_response,
          encrypted_title, encrypted_category, generated_at, content_type

        Optional: embed_id, encrypted_icon, is_opened, opened_chat_id

        Returns the stored record dict, or None on failure.
        """
        hashed_user_id = _hash_user_id(user_id)
        daily_inspiration_id = inspiration.get("daily_inspiration_id")

        if not daily_inspiration_id:
            logger.error(
                "[UserDailyInspirationMethods] upsert_inspiration: missing daily_inspiration_id"
            )
            return None

        now_ts = int(time.time())

        try:
            # Check whether the record already exists so we can update vs create
            existing = await self._get_by_inspiration_id(daily_inspiration_id, hashed_user_id)

            payload: Dict[str, Any] = {
                "daily_inspiration_id": daily_inspiration_id,
                "hashed_user_id": hashed_user_id,
                "embed_id": inspiration.get("embed_id"),
                "encrypted_phrase": inspiration.get("encrypted_phrase"),
                "encrypted_assistant_response": inspiration.get("encrypted_assistant_response"),
                "encrypted_title": inspiration.get("encrypted_title"),
                "encrypted_category": inspiration.get("encrypted_category"),
                "encrypted_icon": inspiration.get("encrypted_icon"),
                "is_opened": inspiration.get("is_opened", False),
                "opened_chat_id": inspiration.get("opened_chat_id"),
                "generated_at": inspiration.get("generated_at", now_ts),
                "content_type": inspiration.get("content_type", "video"),
                "updated_at": now_ts,
            }

            if existing:
                # Update the existing record
                record_id = existing.get("id")
                result = await self.directus_service.update_item(
                    COLLECTION, record_id, payload
                )
                logger.debug(
                    "[UserDailyInspirationMethods] Updated inspiration %s for user %s…",
                    daily_inspiration_id,
                    user_id[:8],
                )
                return result
            else:
                # Create a new record
                payload["created_at"] = now_ts
                success, result = await self.directus_service.create_item(COLLECTION, payload)
                if not success:
                    logger.error(
                        "[UserDailyInspirationMethods] Failed to create inspiration %s: %s",
                        daily_inspiration_id,
                        result,
                    )
                    return None
                logger.debug(
                    "[UserDailyInspirationMethods] Created inspiration %s for user %s…",
                    daily_inspiration_id,
                    user_id[:8],
                )
                return result

        except Exception as exc:
            logger.error(
                "[UserDailyInspirationMethods] upsert_inspiration failed for %s: %s",
                daily_inspiration_id,
                exc,
                exc_info=True,
            )
            return None

    async def mark_opened(
        self,
        user_id: str,
        daily_inspiration_id: str,
        opened_chat_id: Optional[str] = None,
    ) -> bool:
        """
        Mark a daily inspiration as opened (user clicked to start a chat).

        Returns True on success, False on failure.
        """
        hashed_user_id = _hash_user_id(user_id)
        try:
            existing = await self._get_by_inspiration_id(daily_inspiration_id, hashed_user_id)
            if not existing:
                logger.warning(
                    "[UserDailyInspirationMethods] mark_opened: record not found for %s",
                    daily_inspiration_id,
                )
                return False

            record_id = existing.get("id")
            patch: Dict[str, Any] = {
                "is_opened": True,
                "updated_at": int(time.time()),
            }
            if opened_chat_id:
                patch["opened_chat_id"] = opened_chat_id

            result = await self.directus_service.update_item(COLLECTION, record_id, patch)
            logger.debug(
                "[UserDailyInspirationMethods] Marked inspiration %s as opened",
                daily_inspiration_id,
            )
            return result is not None

        except Exception as exc:
            logger.error(
                "[UserDailyInspirationMethods] mark_opened failed for %s: %s",
                daily_inspiration_id,
                exc,
                exc_info=True,
            )
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Read operations (called by GET /v1/daily-inspirations at login sync)
    # ──────────────────────────────────────────────────────────────────────────

    async def get_user_inspirations(
        self,
        user_id: str,
        since_timestamp: Optional[int] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Return inspirations for the user, ordered newest first.

        Args:
            user_id:         The authenticated user ID.
            since_timestamp: If provided, only return inspirations generated
                             at or after this Unix timestamp (seconds).
                             Useful for incremental sync.
            limit:           Maximum number of records to return (default 10,
                             which is more than a week of 3-per-day).

        Returns list of inspiration dicts (may be empty).
        """
        hashed_user_id = _hash_user_id(user_id)

        filter_obj: Dict[str, Any] = {
            "hashed_user_id": {"_eq": hashed_user_id}
        }
        if since_timestamp is not None:
            filter_obj["generated_at"] = {"_gte": since_timestamp}

        params = {
            "fields": INSPIRATION_ALL_FIELDS,
            "filter": filter_obj,
            "sort": "-generated_at",
            "limit": limit,
        }

        try:
            items = await self.directus_service.get_items(COLLECTION, params=params)
            logger.debug(
                "[UserDailyInspirationMethods] get_user_inspirations: found %d records for user %s…",
                len(items),
                user_id[:8],
            )
            return items or []

        except Exception as exc:
            logger.error(
                "[UserDailyInspirationMethods] get_user_inspirations failed for user %s…: %s",
                user_id[:8],
                exc,
                exc_info=True,
            )
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _get_by_inspiration_id(
        self,
        daily_inspiration_id: str,
        hashed_user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single record by its stable client-generated ID, scoped to user."""
        params = {
            "fields": "id,daily_inspiration_id,is_opened,opened_chat_id",
            "filter": {
                "_and": [
                    {"daily_inspiration_id": {"_eq": daily_inspiration_id}},
                    {"hashed_user_id": {"_eq": hashed_user_id}},
                ]
            },
            "limit": 1,
        }
        try:
            items = await self.directus_service.get_items(COLLECTION, params=params)
            return items[0] if items else None
        except Exception as exc:
            logger.error(
                "[UserDailyInspirationMethods] _get_by_inspiration_id failed for %s: %s",
                daily_inspiration_id,
                exc,
            )
            return None
