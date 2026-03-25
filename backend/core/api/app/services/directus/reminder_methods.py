# backend/core/api/app/services/directus/reminder_methods.py
#
# Directus CRUD methods for the reminders collection.
# The reminders table is the durable source of truth; the Dragonfly cache ZSET
# is a disposable hot index rebuilt from this table on startup or cache miss.
#
# All content fields are vault-encrypted (prompt, chat history, chat title,
# chat IDs, user ID). Only scheduling metadata (trigger_at, status) is stored
# in plaintext to enable efficient DB queries.
#
# Reference: docs/apps/reminder.md

import logging
import time
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Directus collection name
COLLECTION = "reminders"

# Hot cache window: reminders due within this many seconds are loaded into cache
HOT_CACHE_WINDOW_SECONDS = 48 * 3600  # 48 hours


class ReminderMethods:
    """
    Methods for CRUD operations on the reminders Directus collection.

    This class follows the same pattern as HealthEventMethods, ChatMethods, etc.
    All methods access Directus via the parent DirectusService instance (self.ds).
    """

    def __init__(self, directus_service):
        """
        Initialize ReminderMethods.

        Args:
            directus_service: The parent DirectusService instance.
        """
        self.ds = directus_service

    async def create_reminder(self, reminder_data: Dict[str, Any]) -> bool:
        """
        Create a new reminder in Directus.

        Args:
            reminder_data: Dict with all reminder fields. Must include at minimum:
                - id (UUID)
                - hashed_user_id
                - encrypted_user_id
                - encrypted_prompt
                - vault_key_id
                - trigger_at
                - status

        Returns:
            True if created successfully, False otherwise.
        """
        try:
            reminder_id = reminder_data.get("id")
            if not reminder_id:
                logger.error("[REMINDER_DB] Cannot create reminder: missing id")
                return False

            success, result = await self.ds.create_item(COLLECTION, reminder_data)

            if success:
                logger.info(
                    f"[REMINDER_DB] Created reminder {reminder_id} in Directus, "
                    f"trigger_at={reminder_data.get('trigger_at')}"
                )
            else:
                logger.error(f"[REMINDER_DB] Failed to create reminder {reminder_id}: {result}")

            return success

        except Exception as e:
            logger.error(f"[REMINDER_DB] Error creating reminder: {e}", exc_info=True)
            return False

    async def update_reminder(self, reminder_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Update fields on an existing reminder.

        Args:
            reminder_id: The reminder UUID.
            update_data: Dict of fields to update (e.g., status, trigger_at, occurrence_count).

        Returns:
            True if updated successfully, False otherwise.
        """
        try:
            if not reminder_id:
                return False

            result = await self.ds.update_item(COLLECTION, reminder_id, update_data)

            if result:
                logger.debug(f"[REMINDER_DB] Updated reminder {reminder_id}: {list(update_data.keys())}")
                return True
            else:
                logger.error(f"[REMINDER_DB] Failed to update reminder {reminder_id}")
                return False

        except Exception as e:
            logger.error(f"[REMINDER_DB] Error updating reminder {reminder_id}: {e}", exc_info=True)
            return False

    async def get_reminder(self, reminder_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single reminder by ID.

        Args:
            reminder_id: The reminder UUID.

        Returns:
            Reminder data dict or None if not found.
        """
        try:
            if not reminder_id:
                return None

            items = await self.ds.get_items(COLLECTION, {
                "filter[id][_eq]": reminder_id,
                "limit": 1,
            })

            if items and len(items) > 0:
                return items[0]
            return None

        except Exception as e:
            logger.error(f"[REMINDER_DB] Error getting reminder {reminder_id}: {e}", exc_info=True)
            return None

    async def get_user_reminders(
        self,
        hashed_user_id: str,
        status_filter: Optional[str] = "pending",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get all reminders for a user, optionally filtered by status.

        Args:
            hashed_user_id: SHA256 hash of the user's UUID.
            status_filter: Filter by status ('pending', 'fired', 'cancelled') or None for all.
            limit: Maximum number of results (default 100).

        Returns:
            List of reminder data dicts sorted by trigger_at ascending.
        """
        try:
            if not hashed_user_id:
                return []

            params: Dict[str, Any] = {
                "filter[hashed_user_id][_eq]": hashed_user_id,
                "sort": "trigger_at",
                "limit": min(max(1, limit), 1000),
            }

            if status_filter:
                params["filter[status][_eq]"] = status_filter

            items = await self.ds.get_items(COLLECTION, params)
            return items if items else []

        except Exception as e:
            logger.error(
                f"[REMINDER_DB] Error getting reminders for hashed_user {hashed_user_id[:16]}...: {e}",
                exc_info=True,
            )
            return []

    async def get_pending_reminders_in_window(
        self,
        window_seconds: int = HOT_CACHE_WINDOW_SECONDS,
    ) -> List[Dict[str, Any]]:
        """
        Get all pending reminders with trigger_at within the hot cache window.

        Used by the promotion task and startup cache warm-up to load near-term
        reminders into the Dragonfly ZSET.

        Args:
            window_seconds: How far ahead to look (default 48 hours).

        Returns:
            List of reminder data dicts.
        """
        try:
            current_time = int(time.time())
            window_end = current_time + window_seconds

            params: Dict[str, Any] = {
                "filter": {
                    "_and": [
                        {"status": {"_eq": "pending"}},
                        {"trigger_at": {"_lte": window_end}},
                    ]
                },
                "sort": "trigger_at",
                "limit": -1,  # No limit — we need all of them for cache loading
            }

            items = await self.ds.get_items(COLLECTION, params)
            count = len(items) if items else 0
            logger.info(
                f"[REMINDER_DB] Found {count} pending reminders within "
                f"{window_seconds // 3600}h window (trigger_at <= {window_end})"
            )
            return items if items else []

        except Exception as e:
            logger.error(f"[REMINDER_DB] Error getting reminders in window: {e}", exc_info=True)
            return []

    async def get_overdue_pending_reminders(self) -> List[Dict[str, Any]]:
        """
        Get pending reminders that are past their trigger time.

        These are reminders that should have fired but were missed (e.g., because
        the cache was empty during their trigger window). The fire task uses this
        as a fallback when the ZSET is empty.

        Returns:
            List of overdue reminder data dicts.
        """
        try:
            current_time = int(time.time())

            params: Dict[str, Any] = {
                "filter": {
                    "_and": [
                        {"status": {"_eq": "pending"}},
                        {"trigger_at": {"_lte": current_time}},
                    ]
                },
                "sort": "trigger_at",
                "limit": 500,  # Safety limit per batch
            }

            items = await self.ds.get_items(COLLECTION, params)
            count = len(items) if items else 0
            if count > 0:
                logger.warning(
                    f"[REMINDER_DB] Found {count} overdue pending reminders (trigger_at <= {current_time})"
                )
            return items if items else []

        except Exception as e:
            logger.error(f"[REMINDER_DB] Error getting overdue reminders: {e}", exc_info=True)
            return []

    async def count_pending_reminders(self) -> int:
        """
        Count the total number of pending reminders in the database.

        Used for monitoring and admin stats.

        Returns:
            Number of pending reminders.
        """
        try:

            url = f"{self.ds.base_url}/items/{COLLECTION}?filter[status][_eq]=pending&limit=0&meta=total_count"
            response = await self.ds._make_api_request("GET", url)

            if response.status_code == 200:
                data = response.json()
                meta = data.get("meta", {})
                return meta.get("total_count", 0) or meta.get("filter_count", 0)

            return 0

        except Exception as e:
            logger.error(f"[REMINDER_DB] Error counting pending reminders: {e}", exc_info=True)
            return 0
