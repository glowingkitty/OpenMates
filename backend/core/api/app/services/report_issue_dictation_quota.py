"""Free, rate-limited dictation for the Report Issue form (signed-in users).

Report dictation is not charged, so abuse is bounded here instead:
- one recording may contain at most REPORT_DICTATION_MAX_RECORDING_SECONDS of audio;
- each user may transcribe at most REPORT_DICTATION_DAILY_SECONDS per UTC day.

Usage is reserved in whole seconds *before* each audio chunk is forwarded to
the provider, so a client cannot exceed the daily budget by disconnecting
early. The counter is an ephemeral rate limit that lives only in Redis (no
database fallback by design): when Redis is unavailable the quota fails
closed, so no free dictation is possible.
Guests keep using GuestTranscriptionMeter, which already caps a recording at
two minutes and draws from the bounded anonymous allowance.

Used by: backend/core/api/app/routes/audio_realtime.py (purpose=report_issue)
Tests: backend/tests/test_report_issue_dictation_quota.py
"""

from __future__ import annotations

import datetime
import math
from typing import Any

REPORT_DICTATION_PURPOSE = "report_issue"
REPORT_DICTATION_MAX_RECORDING_SECONDS = 120
REPORT_DICTATION_DAILY_SECONDS = 30 * 60
# Keys outlive their UTC day slightly so a recording that spans midnight
# still finds its counter; they are never read after the next day.
_KEY_TTL_SECONDS = 2 * 24 * 60 * 60


class ReportDictationDenied(RuntimeError):
    """Raised when a report dictation would exceed a limit."""

    def __init__(self, code: str) -> None:
        messages = {
            "recording_limit": "Report dictation is limited to two minutes per recording.",
            "daily_limit": "Daily report dictation limit reached. Try again tomorrow.",
            "quota_unavailable": "Report dictation is temporarily unavailable.",
        }
        super().__init__(messages.get(code, messages["quota_unavailable"]))
        self.code = code


def _utc_day(now: datetime.datetime | None = None) -> str:
    return (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%d")


def _seconds_until_next_utc_day(now: datetime.datetime | None = None) -> int:
    current = now or datetime.datetime.now(datetime.timezone.utc)
    tomorrow = (current + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((tomorrow - current).total_seconds()))


class ReportDictationQuota:
    """Per-user daily seconds budget for one report dictation stream."""

    def __init__(self, cache_service: Any, user_id_hash: str) -> None:
        self.cache_service = cache_service
        self.key = f"report_issue:dictation:{user_id_hash}:{_utc_day()}"
        self.reserved_seconds = 0

    async def _client(self) -> Any:
        client = await self.cache_service.client
        if not client:
            raise ReportDictationDenied("quota_unavailable")
        return client

    async def used_seconds(self) -> int:
        raw = await (await self._client()).get(self.key)
        if raw is None:
            return 0
        return int(raw.decode() if isinstance(raw, bytes) else raw)

    async def status(self) -> dict[str, int]:
        remaining = max(0, REPORT_DICTATION_DAILY_SECONDS - await self.used_seconds())
        return {
            "remaining_seconds": remaining,
            "daily_limit_seconds": REPORT_DICTATION_DAILY_SECONDS,
            "max_recording_seconds": REPORT_DICTATION_MAX_RECORDING_SECONDS,
            "resets_in_seconds": _seconds_until_next_utc_day(),
        }

    async def admit(self) -> None:
        if await self.used_seconds() >= REPORT_DICTATION_DAILY_SECONDS:
            raise ReportDictationDenied("daily_limit")

    async def reserve(self, total_audio_seconds: float) -> None:
        """Reserve budget so this stream may forward ``total_audio_seconds``."""
        if (
            not math.isfinite(total_audio_seconds)
            or total_audio_seconds > REPORT_DICTATION_MAX_RECORDING_SECONDS
        ):
            raise ReportDictationDenied("recording_limit")
        target = math.ceil(total_audio_seconds)
        additional = target - self.reserved_seconds
        if additional <= 0:
            return
        client = await self._client()
        used = await client.incrby(self.key, additional)
        await client.expire(self.key, _KEY_TTL_SECONDS)
        self.reserved_seconds = target
        if used > REPORT_DICTATION_DAILY_SECONDS:
            # The reservation stays counted: the chunk is refused, and the day
            # is exhausted either way.
            raise ReportDictationDenied("daily_limit")
