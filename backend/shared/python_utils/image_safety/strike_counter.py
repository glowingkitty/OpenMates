# backend/shared/python_utils/image_safety/strike_counter.py
#
# Severity-weighted strike counter with single-response debounce.
#
# Architecture: docs/architecture/image-safety-pipeline.md §5
#
# Key invariant: at most ONE strike is recorded per (user_id, assistant_response_id)
# regardless of how many images-generate sub-calls trip safety. This protects
# users from LLM autonomy (the LLM can call images-generate multiple times in a
# single response — we don't want one ambiguous prompt to cause an instant ban
# just because the LLM iterated).
#
# The audit log still records every rejection with full detail. Only the
# counter is debounced.
#
# Redis schema:
#   chat_image_rejects:<user_id>       24h TTL  — severity-weighted counter
#   safety_response_strike:<user_id>:<assistant_response_id>  24h TTL  — debounce flag
#
# "chat_image_rejects" is the SAME key used by the upload-content-safety-reject
# endpoint so uploads + generations share a single 24h counter.

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Severity → weight (must match policy §Strike severity mapping)
SEVERITY_WEIGHTS = {
    "critical": 4,  # instant ban at 4
    "adversarial": 2,
    "severe": 2,
    "moderate": 1,
}

# Ban threshold — matches the existing upload content-safety-reject logic
BAN_THRESHOLD = 4
# 24h TTL in seconds, matching the existing upload counter
COUNTER_TTL_SECONDS = 86400


class StrikeCounter:
    """
    Async wrapper over Redis that implements severity-weighted strike counting
    with a single-response debounce.

    Depends on an injected cache client with `.get()`, `.set()` (with optional
    ttl=), `.incrby()`, and `.expire()` support. The OpenMates CacheService
    exposes these via `.get_raw_client()` or by using the higher-level wrappers
    below — we use the raw client for incrby semantics.
    """

    def __init__(self, cache_service) -> None:
        self._cache = cache_service

    async def _raw(self):
        """Return the underlying redis client for direct commands."""
        # CacheService exposes `.client` (async property) or similar helpers
        client = getattr(self._cache, "client", None)
        if client is None:
            raise RuntimeError("CacheService has no `.client` attribute")
        if hasattr(client, "__await__"):
            client = await client  # type: ignore[assignment]
        return client

    @staticmethod
    def _counter_key(user_id: str) -> str:
        # Shares namespace with upload_route.py → chat_image_rejects:<user_id>
        return f"chat_image_rejects:{user_id}"

    @staticmethod
    def _debounce_key(user_id: str, assistant_response_id: str) -> str:
        return f"safety_response_strike:{user_id}:{assistant_response_id}"

    async def record_strike(
        self,
        *,
        user_id: str,
        severity: str,
        assistant_response_id: Optional[str],
    ) -> "StrikeResult":
        """
        Record a strike for the given user.

        Single-response cap: if `assistant_response_id` is given and we have
        already recorded a strike for this (user, response), this call returns
        `recorded=False` and does not increment the counter.

        Returns a StrikeResult with the new count and whether the ban threshold
        was reached.
        """
        weight = SEVERITY_WEIGHTS.get(severity, SEVERITY_WEIGHTS["moderate"])

        try:
            client = await self._raw()
        except Exception as e:
            logger.error(f"[StrikeCounter] cache unavailable: {e}", exc_info=True)
            # Fail closed on strike recording → treat as recorded but can't
            # ban without the counter. Surface error for caller to log.
            return StrikeResult(
                recorded=False,
                debounced=False,
                new_count=0,
                ban_triggered=False,
                error=str(e),
            )

        # 1) Single-response debounce check.
        if assistant_response_id:
            dkey = self._debounce_key(user_id, assistant_response_id)
            try:
                already = await client.set(
                    dkey, "1", ex=COUNTER_TTL_SECONDS, nx=True
                )
            except Exception as e:
                logger.error(
                    f"[StrikeCounter] debounce set failed: {e}", exc_info=True
                )
                already = None
            if not already:
                logger.info(
                    f"[StrikeCounter] debounced strike for user {user_id[:8]} "
                    f"response {assistant_response_id[:8]}"
                )
                return StrikeResult(
                    recorded=False,
                    debounced=True,
                    new_count=await self._get_count(user_id),
                    ban_triggered=False,
                )

        # 2) Increment the shared 24h counter.
        key = self._counter_key(user_id)
        try:
            new_count_raw = await client.incrby(key, weight)
            await client.expire(key, COUNTER_TTL_SECONDS)
            new_count = int(new_count_raw or 0)
        except Exception as e:
            logger.error(
                f"[StrikeCounter] incrby failed: {e}", exc_info=True
            )
            return StrikeResult(
                recorded=False,
                debounced=False,
                new_count=0,
                ban_triggered=False,
                error=str(e),
            )

        ban_triggered = new_count >= BAN_THRESHOLD
        logger.warning(
            f"[StrikeCounter] user={user_id[:8]} severity={severity} "
            f"weight={weight} count={new_count} ban={ban_triggered}"
        )
        return StrikeResult(
            recorded=True,
            debounced=False,
            new_count=new_count,
            ban_triggered=ban_triggered,
        )

    async def _get_count(self, user_id: str) -> int:
        try:
            client = await self._raw()
            raw = await client.get(self._counter_key(user_id))
            return int(raw) if raw else 0
        except Exception:
            return 0

    async def reset(self, user_id: str) -> None:
        """Test/admin helper — clears the counter for a user."""
        try:
            client = await self._raw()
            await client.delete(self._counter_key(user_id))
        except Exception as e:
            logger.error(f"[StrikeCounter] reset failed: {e}")


class StrikeResult:
    """Return value of StrikeCounter.record_strike."""

    def __init__(
        self,
        *,
        recorded: bool,
        debounced: bool,
        new_count: int,
        ban_triggered: bool,
        error: Optional[str] = None,
    ) -> None:
        self.recorded = recorded
        self.debounced = debounced
        self.new_count = new_count
        self.ban_triggered = ban_triggered
        self.error = error

    def __repr__(self) -> str:
        return (
            f"StrikeResult(recorded={self.recorded}, debounced={self.debounced}, "
            f"count={self.new_count}, ban={self.ban_triggered}, error={self.error})"
        )


_singleton: Optional[StrikeCounter] = None


def get_strike_counter(cache_service) -> StrikeCounter:
    """Return a StrikeCounter bound to the given cache service."""
    global _singleton
    if _singleton is None or _singleton._cache is not cache_service:
        _singleton = StrikeCounter(cache_service)
    return _singleton
