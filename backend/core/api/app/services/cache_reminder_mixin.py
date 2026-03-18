# backend/core/api/app/services/cache_reminder_mixin.py
#
# Hot-cache operations for the Reminder app.
#
# ARCHITECTURE (Hybrid PostgreSQL + Hot Cache):
# - PostgreSQL/Directus is the durable source of truth for ALL reminders.
# - This cache layer holds a "hot window" of reminders due within 48 hours.
# - The ZSET `reminders:schedule` is a disposable index that can be rebuilt
#   from the database at any time (startup, cache restart, promotion task).
# - The Celery Beat fire task only reads from cache (fast path).
# - A promotion task periodically loads near-term reminders from DB -> cache.
#
# Cache key patterns:
# - ZSET `reminders:schedule` -- score=trigger_at, member=reminder_id
# - STRING `reminder:{reminder_id}` -- JSON with vault-encrypted fields
# - LIST `reminder_pending_delivery:{user_id}` -- fired payloads awaiting WebSocket delivery
#
# Reference: docs/apps/reminder.md

import logging
import time
import json
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Cache key patterns
REMINDER_SCHEDULE_KEY = "reminders:schedule"  # ZSET: score=trigger_at, member=reminder_id
REMINDER_KEY_PREFIX = "reminder:"  # Individual reminder data
PENDING_DELIVERY_KEY_PREFIX = "reminder_pending_delivery:"  # Per-user pending delivery list

# TTL for individual reminder entries in the hot cache.
# Set generously (3 days) since the hot window is 48h -- provides overlap for
# reminders that get rescheduled (repeating) or are slightly past the window edge.
REMINDER_CACHE_TTL = 259200  # 3 days in seconds

# TTL for pending delivery entries (60 days). If a user doesn't come online within
# 60 days, entries expire via Redis TTL. Email notifications serve as a backup.
PENDING_DELIVERY_TTL = 5184000  # 60 days in seconds

# Pending embed encryption tracking constants
PENDING_EMBED_KEY_PREFIX = "pending_embed_encryption:"
PENDING_EMBED_TTL = 2592000  # 30 days (seconds)
EMBED_CACHE_EXTENDED_TTL = 2592000  # 30 days for embeds in the pending set


class ReminderCacheMixin:
    """
    Mixin for reminder hot-cache operations.

    The cache is a disposable acceleration layer -- all durable state lives in
    PostgreSQL (via Directus). Methods here manage the ZSET index and per-reminder
    JSON cache entries used by the 60-second fire task.
    """

    # =========================================================================
    # HOT CACHE WRITE METHODS
    # =========================================================================

    async def load_reminder_into_cache(self, reminder_data: Dict[str, Any]) -> bool:
        """
        Load a single reminder into the hot cache (ZSET + JSON entry).

        Called by:
        - SetReminderSkill when trigger_at is within the hot window
        - The promotion task when moving reminders from DB -> cache
        - Startup cache warm-up

        Args:
            reminder_data: Dict with reminder fields. Must include:
                - reminder_id (or id): UUID string
                - trigger_at: Unix timestamp
                At minimum these two fields; full data is preferred.

        Returns:
            True if successfully loaded, False otherwise.
        """
        try:
            reminder_id = reminder_data.get("reminder_id") or reminder_data.get("id")
            trigger_at = reminder_data.get("trigger_at")

            if not reminder_id or not trigger_at:
                logger.error("Cannot load reminder into cache: missing reminder_id or trigger_at")
                return False

            client = await self.client
            if not client:
                logger.error("Cannot load reminder into cache: cache client not available")
                return False

            # Normalize the data -- ensure reminder_id is set (DB rows use 'id')
            cache_data = dict(reminder_data)
            if "reminder_id" not in cache_data and "id" in cache_data:
                cache_data["reminder_id"] = cache_data["id"]

            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"
            reminder_json = json.dumps(cache_data)

            async with client.pipeline(transaction=True) as pipe:
                pipe.setex(reminder_key, REMINDER_CACHE_TTL, reminder_json)
                pipe.zadd(REMINDER_SCHEDULE_KEY, {reminder_id: trigger_at})
                await pipe.execute()

            logger.debug(f"Loaded reminder {reminder_id} into hot cache, trigger_at={trigger_at}")
            return True

        except Exception as e:
            logger.error(f"Error loading reminder into cache: {e}", exc_info=True)
            return False

    async def load_reminders_batch_into_cache(self, reminders: List[Dict[str, Any]]) -> int:
        """
        Load multiple reminders into the hot cache efficiently using pipelines.

        Args:
            reminders: List of reminder data dicts (from Directus query).

        Returns:
            Number of reminders successfully loaded.
        """
        if not reminders:
            return 0

        try:
            client = await self.client
            if not client:
                logger.error("Cannot load reminders batch: cache client not available")
                return 0

            loaded = 0
            batch_size = 100
            for i in range(0, len(reminders), batch_size):
                batch = reminders[i:i + batch_size]
                async with client.pipeline(transaction=True) as pipe:
                    for reminder_data in batch:
                        reminder_id = reminder_data.get("reminder_id") or reminder_data.get("id")
                        trigger_at = reminder_data.get("trigger_at")

                        if not reminder_id or not trigger_at:
                            continue

                        cache_data = dict(reminder_data)
                        if "reminder_id" not in cache_data and "id" in cache_data:
                            cache_data["reminder_id"] = cache_data["id"]

                        reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"
                        reminder_json = json.dumps(cache_data)

                        pipe.setex(reminder_key, REMINDER_CACHE_TTL, reminder_json)
                        pipe.zadd(REMINDER_SCHEDULE_KEY, {reminder_id: trigger_at})
                        loaded += 1

                    await pipe.execute()

            logger.info(f"Loaded {loaded} reminders into hot cache (batch)")
            return loaded

        except Exception as e:
            logger.error(f"Error loading reminders batch into cache: {e}", exc_info=True)
            return 0

    # =========================================================================
    # HOT CACHE READ METHODS
    # =========================================================================

    async def get_reminder(self, reminder_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single reminder from the hot cache.

        Args:
            reminder_id: The reminder UUID.

        Returns:
            Reminder data dict or None if not in cache.
        """
        try:
            if not reminder_id:
                return None

            client = await self.client
            if not client:
                return None

            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"
            reminder_json = await client.get(reminder_key)

            if not reminder_json:
                return None

            if isinstance(reminder_json, bytes):
                reminder_json = reminder_json.decode("utf-8")

            return json.loads(reminder_json)

        except Exception as e:
            logger.error(f"Error getting reminder {reminder_id} from cache: {e}", exc_info=True)
            return None

    async def get_due_reminders(self, current_time: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all reminders that are due (trigger_at <= current_time) from the hot cache.

        Uses ZRANGEBYSCORE on the ZSET for O(log N + M) efficiency, then MGET
        for batch fetching (replaces the previous N+1 GET loop).

        Args:
            current_time: Unix timestamp to check against (defaults to now).

        Returns:
            List of due reminder data dicts.
        """
        try:
            client = await self.client
            if not client:
                return []

            if current_time is None:
                current_time = int(time.time())

            due_reminder_ids = await client.zrangebyscore(
                REMINDER_SCHEDULE_KEY, min=0, max=current_time
            )

            if not due_reminder_ids:
                return []

            # Batch fetch with MGET for efficiency
            keys = []
            id_list = []
            for rid in due_reminder_ids:
                if isinstance(rid, bytes):
                    rid = rid.decode("utf-8")
                id_list.append(rid)
                keys.append(f"{REMINDER_KEY_PREFIX}{rid}")

            if not keys:
                return []

            values = await client.mget(*keys)

            due_reminders = []
            orphaned_ids = []
            for rid, val in zip(id_list, values):
                if val is None:
                    orphaned_ids.append(rid)
                    continue
                if isinstance(val, bytes):
                    val = val.decode("utf-8")
                try:
                    reminder = json.loads(val)
                    if reminder.get("status") == "pending":
                        due_reminders.append(reminder)
                except json.JSONDecodeError:
                    logger.warning(f"Malformed JSON for reminder {rid} in cache")
                    orphaned_ids.append(rid)

            # Clean up orphaned ZSET entries
            if orphaned_ids:
                logger.warning(
                    f"Cleaning up {len(orphaned_ids)} orphaned ZSET entries: {orphaned_ids}"
                )
                await client.zrem(REMINDER_SCHEDULE_KEY, *orphaned_ids)

            logger.debug(f"Found {len(due_reminders)} due reminders at time {current_time}")
            return due_reminders

        except Exception as e:
            logger.error(f"Error getting due reminders: {e}", exc_info=True)
            return []

    # =========================================================================
    # HOT CACHE REMOVE / UPDATE METHODS
    # =========================================================================

    async def remove_reminder_from_cache(self, reminder_id: str) -> bool:
        """
        Remove a reminder from the hot cache (ZSET + JSON key).

        Args:
            reminder_id: The reminder UUID.

        Returns:
            True if removed, False otherwise.
        """
        try:
            if not reminder_id:
                return False

            client = await self.client
            if not client:
                return False

            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"

            async with client.pipeline(transaction=True) as pipe:
                pipe.delete(reminder_key)
                pipe.zrem(REMINDER_SCHEDULE_KEY, reminder_id)
                await pipe.execute()

            logger.debug(f"Removed reminder {reminder_id} from hot cache")
            return True

        except Exception as e:
            logger.error(f"Error removing reminder {reminder_id} from cache: {e}", exc_info=True)
            return False

    async def claim_due_reminder(self, reminder_id: str) -> bool:
        """
        Atomically remove a reminder from the ZSET to claim it for processing.

        Provides idempotency: if two workers both try to process the same
        reminder, only one ZREM returns 1.

        Args:
            reminder_id: The reminder UUID.

        Returns:
            True if this call claimed the reminder, False if already claimed.
        """
        try:
            if not reminder_id:
                return False

            client = await self.client
            if not client:
                return False

            removed = await client.zrem(REMINDER_SCHEDULE_KEY, reminder_id)
            claimed = removed > 0

            if claimed:
                logger.debug(f"Claimed reminder {reminder_id} for processing")
            else:
                logger.debug(f"Reminder {reminder_id} already claimed by another worker")

            return claimed

        except Exception as e:
            logger.error(f"Error claiming reminder {reminder_id}: {e}", exc_info=True)
            return False

    async def reschedule_reminder_in_cache(
        self,
        reminder_id: str,
        reminder_data: Dict[str, Any],
        new_trigger_at: int,
    ) -> bool:
        """
        Reschedule a repeating reminder in the hot cache.

        Only adds to cache if new_trigger_at is within the hot window (48h).

        Args:
            reminder_id: The reminder UUID.
            reminder_data: Updated reminder data dict.
            new_trigger_at: New Unix timestamp for next trigger.

        Returns:
            True if rescheduled (or skipped because beyond window), False on error.
        """
        try:
            if not reminder_id or not new_trigger_at:
                return False

            current_time = int(time.time())
            hot_window_end = current_time + (48 * 3600)

            if new_trigger_at > hot_window_end:
                logger.debug(
                    f"Reminder {reminder_id} rescheduled to {new_trigger_at} "
                    f"(beyond hot window, skipping cache)"
                )
                return True

            client = await self.client
            if not client:
                return False

            cache_data = dict(reminder_data)
            cache_data["trigger_at"] = new_trigger_at
            cache_data["status"] = "pending"

            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"
            reminder_json = json.dumps(cache_data)

            async with client.pipeline(transaction=True) as pipe:
                pipe.setex(reminder_key, REMINDER_CACHE_TTL, reminder_json)
                pipe.zadd(REMINDER_SCHEDULE_KEY, {reminder_id: new_trigger_at})
                await pipe.execute()

            logger.debug(f"Rescheduled reminder {reminder_id} in cache to trigger_at={new_trigger_at}")
            return True

        except Exception as e:
            logger.error(f"Error rescheduling reminder {reminder_id} in cache: {e}", exc_info=True)
            return False

    async def get_cache_schedule_count(self) -> int:
        """
        Get the number of reminders in the hot cache ZSET.

        Returns:
            Number of entries in the ZSET.
        """
        try:
            client = await self.client
            if not client:
                return 0
            return await client.zcard(REMINDER_SCHEDULE_KEY)
        except Exception as e:
            logger.error(f"Error getting cache schedule count: {e}", exc_info=True)
            return 0

    async def get_reminder_stats(self) -> Dict[str, int]:
        """
        Get statistics about reminders in the hot cache (for monitoring/admin).

        Returns:
            Dict with counts: total_in_cache, due_now.
        """
        try:
            client = await self.client
            if not client:
                return {"total_in_cache": 0, "due_now": 0}

            current_time = int(time.time())
            total = await client.zcard(REMINDER_SCHEDULE_KEY)
            due_now = await client.zcount(REMINDER_SCHEDULE_KEY, 0, current_time)

            return {"total_in_cache": total, "due_now": due_now}

        except Exception as e:
            logger.error(f"Error getting reminder stats: {e}", exc_info=True)
            return {"total_in_cache": 0, "due_now": 0}

    # =========================================================================
    # PENDING DELIVERY METHODS
    #
    # When a reminder fires but the user has no active WebSocket connections,
    # the delivery payload is queued here. On reconnect the client retrieves
    # and clears these entries.  Email notifications serve as a backup.
    # =========================================================================

    async def add_pending_reminder_delivery(
        self, user_id: str, delivery_payload: Dict[str, Any]
    ) -> bool:
        """
        Queue a fired reminder for delivery when the user comes back online.

        Args:
            user_id: The user ID (UUID, not hashed).
            delivery_payload: The reminder_fired payload dict (plaintext content).

        Returns:
            True if queued successfully.
        """
        try:
            if not user_id or not delivery_payload:
                return False

            client = await self.client
            if not client:
                logger.error("Cannot queue pending reminder delivery: cache client not available")
                return False

            key = f"{PENDING_DELIVERY_KEY_PREFIX}{user_id}"
            payload_json = json.dumps(delivery_payload)

            async with client.pipeline(transaction=True) as pipe:
                pipe.rpush(key, payload_json)
                pipe.expire(key, PENDING_DELIVERY_TTL)
                await pipe.execute()

            logger.info(
                f"Queued pending reminder delivery for user {user_id[:8]}... "
                f"(reminder_id={delivery_payload.get('reminder_id')})"
            )
            return True

        except Exception as e:
            logger.error(f"Error queuing pending reminder delivery: {e}", exc_info=True)
            return False

    async def get_and_clear_pending_reminder_deliveries(
        self, user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Atomically retrieve and remove all pending reminder deliveries for a user.

        Args:
            user_id: The user ID (UUID, not hashed).

        Returns:
            List of delivery payload dicts (may be empty).
        """
        try:
            if not user_id:
                return []

            client = await self.client
            if not client:
                return []

            key = f"{PENDING_DELIVERY_KEY_PREFIX}{user_id}"

            async with client.pipeline(transaction=True) as pipe:
                pipe.lrange(key, 0, -1)
                pipe.delete(key)
                results = await pipe.execute()

            raw_entries = results[0] if results else []
            if not raw_entries:
                return []

            deliveries = []
            for entry in raw_entries:
                if isinstance(entry, bytes):
                    entry = entry.decode("utf-8")
                try:
                    deliveries.append(json.loads(entry))
                except json.JSONDecodeError:
                    logger.warning(f"Skipping malformed pending delivery entry for user {user_id[:8]}...")

            if deliveries:
                logger.info(
                    f"Retrieved {len(deliveries)} pending reminder deliveries for user {user_id[:8]}..."
                )
            return deliveries

        except Exception as e:
            logger.error(f"Error retrieving pending reminder deliveries: {e}", exc_info=True)
            return []

    async def has_pending_reminder_deliveries(self, user_id: str) -> bool:
        """
        Check if a user has any pending reminder deliveries without consuming them.

        Args:
            user_id: The user ID (UUID, not hashed).

        Returns:
            True if there are pending deliveries.
        """
        try:
            if not user_id:
                return False

            client = await self.client
            if not client:
                return False

            key = f"{PENDING_DELIVERY_KEY_PREFIX}{user_id}"
            count = await client.llen(key)
            return count > 0

        except Exception as e:
            logger.error(f"Error checking pending reminder deliveries: {e}", exc_info=True)
            return False

    async def cleanup_expired_pending_deliveries(self) -> int:
        """
        Audit pending delivery entries and log for monitoring.
        Redis handles TTL-based expiry; this provides visibility.

        Returns:
            Number of users with pending deliveries.
        """
        try:
            client = await self.client
            if not client:
                return 0

            users_with_pending = 0
            async for key in client.scan_iter(match=f"{PENDING_DELIVERY_KEY_PREFIX}*"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                user_id = key.replace(PENDING_DELIVERY_KEY_PREFIX, "")
                count = await client.llen(key)
                ttl = await client.ttl(key)

                if count > 0:
                    users_with_pending += 1
                    days_remaining = ttl / 86400 if ttl > 0 else 0
                    logger.info(
                        f"[PENDING_DELIVERY_AUDIT] User {user_id[:8]}... has "
                        f"{count} pending deliveries, {days_remaining:.1f} days remaining"
                    )

            return users_with_pending

        except Exception as e:
            logger.error(f"Error auditing pending deliveries: {e}", exc_info=True)
            return 0

    # ===================================================================
    # PENDING EMBED ENCRYPTION TRACKING
    # ===================================================================

    async def add_pending_embed(self, user_id: str, embed_id: str) -> bool:
        """Track a finalized embed as pending client encryption."""
        try:
            client = await self.client
            if not client:
                logger.warning(f"Cannot add pending embed {embed_id}: cache client not available")
                return False

            key = f"{PENDING_EMBED_KEY_PREFIX}{user_id}"
            score = time.time()

            await client.zadd(key, {embed_id: score})
            await client.expire(key, PENDING_EMBED_TTL)

            logger.debug(
                f"[PENDING_EMBED] Added embed {embed_id} to pending set for "
                f"user {user_id[:8]}... (score={score:.0f})"
            )
            return True

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error adding embed {embed_id} to pending set "
                f"for user {user_id[:8]}...: {e}",
                exc_info=True
            )
            return False

    async def remove_pending_embed(self, user_id: str, embed_id: str) -> bool:
        """Remove an embed from the pending encryption tracking set."""
        try:
            client = await self.client
            if not client:
                logger.warning(f"Cannot remove pending embed {embed_id}: cache client not available")
                return False

            key = f"{PENDING_EMBED_KEY_PREFIX}{user_id}"
            removed = await client.zrem(key, embed_id)

            if removed:
                remaining = await client.zcard(key)
                if remaining == 0:
                    await client.delete(key)
                logger.info(
                    f"[PENDING_EMBED] Removed embed {embed_id} from pending set for "
                    f"user {user_id[:8]}... (confirmed client encryption)"
                )
                return True
            else:
                logger.debug(
                    f"[PENDING_EMBED] Embed {embed_id} was not in pending set for "
                    f"user {user_id[:8]}... (already removed or never tracked)"
                )
                return False

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error removing embed {embed_id} from pending set "
                f"for user {user_id[:8]}...: {e}",
                exc_info=True
            )
            return False

    async def get_pending_embed_ids(self, user_id: str) -> List[str]:
        """Get all pending embed IDs for a user."""
        try:
            client = await self.client
            if not client:
                return []

            key = f"{PENDING_EMBED_KEY_PREFIX}{user_id}"
            members = await client.zrange(key, 0, -1)

            return [
                m.decode("utf-8") if isinstance(m, bytes) else m
                for m in members
            ]

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error getting pending embeds for "
                f"user {user_id[:8]}...: {e}",
                exc_info=True
            )
            return []

    async def get_all_users_with_pending_embeds(self) -> List[str]:
        """Find all users who have pending embed encryptions."""
        try:
            client = await self.client
            if not client:
                return []

            user_ids = []
            async for key in client.scan_iter(match=f"{PENDING_EMBED_KEY_PREFIX}*"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                user_id = key.replace(PENDING_EMBED_KEY_PREFIX, "")
                user_ids.append(user_id)

            return user_ids

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error scanning for users with pending embeds: {e}",
                exc_info=True
            )
            return []

    async def refresh_pending_embed_cache_ttls(self, user_id: str) -> int:
        """Refresh cache TTLs for all pending embeds of a user."""
        try:
            client = await self.client
            if not client:
                return 0

            pending_ids = await self.get_pending_embed_ids(user_id)
            if not pending_ids:
                return 0

            refreshed = 0
            for embed_id in pending_ids:
                try:
                    cache_key = f"embed:{embed_id}"
                    existing = await client.get(cache_key)
                    if existing:
                        await client.expire(cache_key, EMBED_CACHE_EXTENDED_TTL)
                        refreshed += 1
                    else:
                        logger.debug(
                            f"[PENDING_EMBED] Cache key {cache_key} not found "
                            f"(already expired?) for user {user_id[:8]}..."
                        )
                except Exception as e:
                    logger.warning(
                        f"[PENDING_EMBED] Error refreshing TTL for embed {embed_id}: {e}"
                    )

            if refreshed > 0:
                logger.debug(
                    f"[PENDING_EMBED] Refreshed {refreshed} cache TTLs for "
                    f"user {user_id[:8]}..."
                )
            return refreshed

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error refreshing cache TTLs for "
                f"user {user_id[:8]}...: {e}",
                exc_info=True
            )
            return 0

    async def cleanup_expired_pending_embeds(self, max_age_seconds: int = 2592000) -> int:
        """Remove stale entries from pending embed sets across all users."""
        try:
            client = await self.client
            if not client:
                return 0

            cutoff = time.time() - max_age_seconds
            total_removed = 0

            user_ids = await self.get_all_users_with_pending_embeds()
            for user_id in user_ids:
                try:
                    key = f"{PENDING_EMBED_KEY_PREFIX}{user_id}"

                    expired = await client.zrangebyscore(key, "-inf", cutoff)
                    if expired:
                        removed = await client.zremrangebyscore(key, "-inf", cutoff)
                        total_removed += removed
                        logger.info(
                            f"[PENDING_EMBED] Cleaned up {removed} expired pending embed(s) "
                            f"for user {user_id[:8]}... (older than {max_age_seconds / 86400:.0f} days)"
                        )

                    remaining = await client.zcard(key)
                    if remaining == 0:
                        await client.delete(key)

                except Exception as e:
                    logger.warning(
                        f"[PENDING_EMBED] Error cleaning up pending embeds for "
                        f"user {user_id[:8]}...: {e}"
                    )

            if total_removed > 0:
                logger.info(
                    f"[PENDING_EMBED] Total cleanup: removed {total_removed} expired "
                    f"pending embed entries across {len(user_ids)} users"
                )

            return total_removed

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error in cleanup_expired_pending_embeds: {e}",
                exc_info=True
            )
            return 0
