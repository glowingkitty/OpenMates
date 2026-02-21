# backend/core/api/app/services/cache_inspiration_mixin.py
# Cache mixin for the Daily Inspiration feature.
#
# Architecture overview:
# - Topic suggestions: collected from post-processing, stored per user in a rolling list
#   (max 50 entries, 24h TTL per batch). Used to personalize daily inspiration generation.
# - Paid request tracking: tracks last paid request timestamp to determine which users
#   are eligible for daily inspiration generation (active users only).
# - View tracking: tracks which inspiration IDs were viewed by each user. The count of
#   viewed inspirations determines how many new ones to generate the next day (0-3).
# - Pending delivery cache: stores generated inspirations for offline users (server-side
#   encrypted with vault key, 7-day TTL). Delivered on next WebSocket connection.
#
# Privacy notes:
# - Topic suggestions are stored encrypted (per-user, not cross-user)
# - Pending inspirations are encrypted with the user's vault key (server can decrypt
#   for delivery, but nothing is stored in Directus - only in transient cache)
# - View tracking stores only inspiration UUIDs, not content
# - All cache entries auto-expire, no persistent storage

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# TTL constants
# Topic suggestions: 24-hour rolling window (stale after 1 day)
TOPIC_SUGGESTIONS_TTL_SECONDS = 86400  # 24 hours
# Paid request timestamp: no TTL needed (we update on each paid request)
# Max rolling entries for topic suggestions per user
TOPIC_SUGGESTIONS_MAX_ENTRIES = 50
# Delivery cache for offline users: 7 days
PENDING_INSPIRATIONS_TTL_SECONDS = 7 * 86400  # 7 days
# Paid request tracking: 48h so the daily job can always check the previous day
PAID_REQUEST_TTL_SECONDS = 48 * 3600  # 48 hours


class InspirationCacheMixin:
    """
    Mixin providing cache operations for the Daily Inspiration feature.

    Manages three categories of per-user data:
    1. Topic suggestions — short interest phrases captured during post-processing
    2. Paid request + view tracking — eligibility and quantity for daily generation
    3. Pending delivery cache — generated inspirations for offline users (encrypted)
    """

    # ──────────────────────────────────────────────────────────────────────────
    # Key helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _inspiration_topics_key(self, user_id: str) -> str:
        """Cache key for the rolling list of topic suggestions for a user."""
        return f"daily_inspiration_topics:{user_id}"

    def _inspiration_paid_request_key(self, user_id: str) -> str:
        """Cache key for tracking the last paid request timestamp for a user."""
        return f"daily_inspiration_last_paid_request:{user_id}"

    def _inspiration_views_key(self, user_id: str) -> str:
        """Cache key for the set of viewed daily inspiration IDs for a user."""
        return f"daily_inspiration_views:{user_id}"

    def _inspiration_pending_key(self, user_id: str) -> str:
        """Cache key for pending (offline-delivery) inspirations for a user."""
        return f"daily_inspiration_pending:{user_id}"

    # ──────────────────────────────────────────────────────────────────────────
    # Topic suggestions
    # ──────────────────────────────────────────────────────────────────────────

    async def store_inspiration_topic_suggestions(
        self,
        user_id: str,
        new_suggestions: List[str],
    ) -> bool:
        """
        Append new topic suggestions to the rolling list for a user.

        The list is capped at TOPIC_SUGGESTIONS_MAX_ENTRIES (50). Oldest entries are
        dropped when the cap is reached. Each batch is stored as a JSON object with
        a timestamp so generation code can filter by recency if needed.

        Args:
            user_id: User UUID (not hashed — this is internal server-side cache only)
            new_suggestions: List of short topic phrases (typically 3 from post-processing)

        Returns:
            True on success, False on error (non-fatal — daily inspiration can still
            be generated without personalization if topic suggestions are unavailable)
        """
        if not new_suggestions:
            return True  # Nothing to store

        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for store_inspiration_topic_suggestions")
            return False

        key = self._inspiration_topics_key(user_id)
        try:
            # Load existing entries
            existing_json = await client.get(key)
            entries: List[Dict[str, Any]] = []
            if existing_json:
                if isinstance(existing_json, bytes):
                    existing_json = existing_json.decode("utf-8")
                entries = json.loads(existing_json)

            # Append new batch with timestamp
            now_ts = int(time.time())
            entries.append({
                "suggestions": new_suggestions,
                "timestamp": now_ts,
            })

            # Enforce rolling cap: keep only the most recent N batches
            # Each batch has up to 3 suggestions; 50 suggestions = ~17 batches
            max_batches = TOPIC_SUGGESTIONS_MAX_ENTRIES // 3 + 1
            if len(entries) > max_batches:
                entries = entries[-max_batches:]

            # Persist with 24h TTL (reset TTL on each update to keep data fresh)
            await client.set(key, json.dumps(entries), ex=TOPIC_SUGGESTIONS_TTL_SECONDS)
            logger.debug(
                f"[CACHE] Stored {len(new_suggestions)} topic suggestions for user "
                f"{user_id[:8]}... (total batches: {len(entries)})"
            )
            return True
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to store inspiration topic suggestions for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return False

    async def get_inspiration_topic_suggestions(self, user_id: str) -> List[str]:
        """
        Retrieve the flat list of all topic suggestion strings for a user.

        Returns a deduplicated list of topic strings from all stored batches,
        most-recent-first. Empty list if nothing is cached or on error.

        Args:
            user_id: User UUID

        Returns:
            List of topic suggestion strings (up to TOPIC_SUGGESTIONS_MAX_ENTRIES)
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for get_inspiration_topic_suggestions")
            return []

        key = self._inspiration_topics_key(user_id)
        try:
            raw = await client.get(key)
            if not raw:
                logger.debug(f"[CACHE] No topic suggestions cached for user {user_id[:8]}...")
                return []

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            batches: List[Dict[str, Any]] = json.loads(raw)

            # Flatten all suggestions, most-recent first (last batch first)
            all_suggestions: List[str] = []
            seen: set = set()
            for batch in reversed(batches):
                for suggestion in batch.get("suggestions", []):
                    if suggestion and suggestion not in seen:
                        all_suggestions.append(suggestion)
                        seen.add(suggestion)

            logger.debug(
                f"[CACHE] Retrieved {len(all_suggestions)} unique topic suggestions "
                f"for user {user_id[:8]}..."
            )
            return all_suggestions[:TOPIC_SUGGESTIONS_MAX_ENTRIES]
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to retrieve inspiration topic suggestions for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # Paid request tracking
    # ──────────────────────────────────────────────────────────────────────────

    async def track_inspiration_paid_request(self, user_id: str, language: str = "en") -> bool:
        """
        Record that a user made a paid AI request (for daily inspiration eligibility).

        Called after each successful paid request. The stored timestamp is used by
        the daily generation job to identify active users who should receive new
        daily inspirations. The language is stored so that generated inspirations
        can be personalised to the user's preferred locale.

        Args:
            user_id: User UUID
            language: User's UI language code (e.g. "en", "de", "es"). Defaults to "en".

        Returns:
            True on success, False on error
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for track_inspiration_paid_request")
            return False

        key = self._inspiration_paid_request_key(user_id)
        try:
            now_ts = int(time.time())
            payload = json.dumps({
                "last_paid_request_timestamp": now_ts,
                "language": language or "en",
            })
            # 48h TTL so daily jobs can reliably look back 24h
            await client.set(key, payload, ex=PAID_REQUEST_TTL_SECONDS)
            logger.debug(
                f"[CACHE] Tracked paid request for inspiration eligibility: user {user_id[:8]}... "
                f"at ts={now_ts}, lang={language or 'en'}"
            )
            return True
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to track paid request for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return False

    async def get_inspiration_paid_request_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the full paid-request tracking data for a user (timestamp + language).

        Returns None if the user has never made a paid request or if the entry
        has expired (after 48h, meaning no paid request in the last 2 days).

        Args:
            user_id: User UUID

        Returns:
            Dict with 'last_paid_request_timestamp' (int) and 'language' (str), or None
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for get_inspiration_paid_request_data")
            return None

        key = self._inspiration_paid_request_key(user_id)
        try:
            raw = await client.get(key)
            if not raw:
                return None

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            return json.loads(raw)
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to retrieve paid request data for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return None

    async def get_inspiration_last_paid_request_timestamp(self, user_id: str) -> Optional[int]:
        """
        Get the Unix timestamp of the user's last paid request.

        Returns None if the user has never made a paid request or if the entry
        has expired (after 48h, meaning no paid request in the last 2 days).

        Args:
            user_id: User UUID

        Returns:
            Unix timestamp (int) or None
        """
        data = await self.get_inspiration_paid_request_data(user_id)
        if data is None:
            return None
        return data.get("last_paid_request_timestamp")

    async def had_paid_request_in_last_24h(self, user_id: str) -> bool:
        """
        Convenience method: check if user made a paid request in the last 24 hours.

        Used by the daily inspiration generation job to determine eligibility.

        Args:
            user_id: User UUID

        Returns:
            True if user made a paid request in the last 24 hours
        """
        ts = await self.get_inspiration_last_paid_request_timestamp(user_id)
        if ts is None:
            return False
        now = int(time.time())
        return (now - ts) < 86400  # 24 hours

    # ──────────────────────────────────────────────────────────────────────────
    # View tracking
    # ──────────────────────────────────────────────────────────────────────────

    async def track_inspiration_viewed(self, user_id: str, inspiration_id: str) -> bool:
        """
        Record that a user viewed a specific daily inspiration banner.

        Called by the WebSocket handler when the client reports a banner was visible.
        Only the inspiration UUID is stored (no content — privacy preserving).
        The count of viewed IDs determines how many new inspirations to generate
        the following day.

        Args:
            user_id: User UUID
            inspiration_id: UUID of the viewed daily inspiration

        Returns:
            True on success, False on error
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for track_inspiration_viewed")
            return False

        key = self._inspiration_views_key(user_id)
        try:
            # Load existing view tracking data
            raw = await client.get(key)
            view_data: Dict[str, Any] = {
                "viewed_inspiration_ids": [],
                "last_viewed_timestamp": None,
            }
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                view_data = json.loads(raw)

            # Add the new ID if not already tracked
            viewed_ids: List[str] = view_data.get("viewed_inspiration_ids", [])
            if inspiration_id not in viewed_ids:
                viewed_ids.append(inspiration_id)
                view_data["viewed_inspiration_ids"] = viewed_ids
                view_data["last_viewed_timestamp"] = int(time.time())

                # Persist — TTL is 48h to ensure daily jobs can read previous-day views
                await client.set(key, json.dumps(view_data), ex=PAID_REQUEST_TTL_SECONDS)
                logger.debug(
                    f"[CACHE] Tracked inspiration view for user {user_id[:8]}...: "
                    f"id={inspiration_id[:8]}... (total viewed: {len(viewed_ids)})"
                )
            return True
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to track inspiration view for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return False

    async def get_viewed_inspiration_count(self, user_id: str) -> int:
        """
        Get the count of daily inspirations viewed by a user since last generation.

        Used by the daily generation job to determine how many new inspirations to
        generate (0 viewed → 0 generated; 1-3 viewed → 1-3 generated).

        Args:
            user_id: User UUID

        Returns:
            Count of unique viewed inspiration IDs (0-3)
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for get_viewed_inspiration_count")
            return 0

        key = self._inspiration_views_key(user_id)
        try:
            raw = await client.get(key)
            if not raw:
                return 0

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            view_data = json.loads(raw)
            count = len(view_data.get("viewed_inspiration_ids", []))
            logger.debug(
                f"[CACHE] User {user_id[:8]}... viewed {count} inspiration(s)"
            )
            return count
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to get viewed inspiration count for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return 0

    async def clear_inspiration_views(self, user_id: str) -> bool:
        """
        Clear view tracking for a user after daily generation completes.

        Called by the daily generation job after it finishes processing a user,
        to reset the counter for the next day's cycle.

        Args:
            user_id: User UUID

        Returns:
            True on success, False on error
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for clear_inspiration_views")
            return False

        key = self._inspiration_views_key(user_id)
        try:
            await client.delete(key)
            logger.debug(f"[CACHE] Cleared inspiration view tracking for user {user_id[:8]}...")
            return True
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to clear inspiration views for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Pending delivery cache (offline users)
    # ──────────────────────────────────────────────────────────────────────────

    async def store_pending_inspirations(
        self,
        user_id: str,
        inspirations: List[Dict[str, Any]],
    ) -> bool:
        """
        Cache generated daily inspirations for delivery when the user next logs in.

        Used when the user is offline at generation time. The inspiration data should
        already be encrypted by the caller using the user's vault key before passing
        to this method (server-side encryption via EncryptionService.encrypt_with_user_key).

        The cache entry auto-expires after 7 days. If the user doesn't log in within
        7 days, the inspirations are considered stale and dropped.

        Args:
            user_id: User UUID
            inspirations: List of inspiration dicts (each with encrypted_data, key_version,
                          inspiration_id, and generated_at timestamp)

        Returns:
            True on success, False on error
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for store_pending_inspirations")
            return False

        key = self._inspiration_pending_key(user_id)
        try:
            payload = {
                "inspirations": inspirations,
                "generated_at": int(time.time()),
            }
            await client.set(
                key,
                json.dumps(payload),
                ex=PENDING_INSPIRATIONS_TTL_SECONDS,
            )
            logger.info(
                f"[CACHE] Stored {len(inspirations)} pending inspirations for offline user "
                f"{user_id[:8]}... (TTL: 7 days)"
            )
            return True
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to store pending inspirations for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return False

    async def get_pending_inspirations(self, user_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve pending daily inspirations for a user on login.

        Returns None if there are no pending inspirations or if the cache entry
        has expired (7 days). The caller is responsible for decrypting and delivering
        the inspirations via WebSocket, then calling clear_pending_inspirations().

        Args:
            user_id: User UUID

        Returns:
            List of inspiration dicts (encrypted) if found, None otherwise
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for get_pending_inspirations")
            return None

        key = self._inspiration_pending_key(user_id)
        try:
            raw = await client.get(key)
            if not raw:
                logger.debug(f"[CACHE] No pending inspirations for user {user_id[:8]}...")
                return None

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            payload = json.loads(raw)
            inspirations = payload.get("inspirations", [])
            logger.info(
                f"[CACHE] Retrieved {len(inspirations)} pending inspirations for user "
                f"{user_id[:8]}... (generated at ts={payload.get('generated_at')})"
            )
            return inspirations
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to retrieve pending inspirations for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return None

    async def clear_pending_inspirations(self, user_id: str) -> bool:
        """
        Remove pending inspirations from cache after successful WebSocket delivery.

        Must be called immediately after delivering cached inspirations to the user
        to prevent re-delivery on subsequent logins.

        Args:
            user_id: User UUID

        Returns:
            True on success, False on error
        """
        client = await self.client
        if not client:
            logger.error("[CACHE] Redis client not available for clear_pending_inspirations")
            return False

        key = self._inspiration_pending_key(user_id)
        try:
            await client.delete(key)
            logger.info(
                f"[CACHE] Cleared pending inspirations for user {user_id[:8]}... after delivery"
            )
            return True
        except Exception as e:
            logger.error(
                f"[CACHE] Failed to clear pending inspirations for user {user_id[:8]}...: {e}",
                exc_info=True,
            )
            return False
