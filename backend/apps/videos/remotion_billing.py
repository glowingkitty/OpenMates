# backend/apps/videos/remotion_billing.py
#
# Billing helpers for Remotion E2B render runtime. Auto-started renders get a
# consent-specific first minute grace period; explicit user rerenders are billed
# from their configured start point.

from __future__ import annotations

import math


REMOTION_RENDER_CREDITS_PER_STARTED_MINUTE = 5
AUTO_STARTED_RENDER_FREE_SECONDS = 60


def calculate_remotion_render_credits(
    *,
    runtime_seconds: int | float,
    auto_started: bool,
    credits_per_started_minute: int = REMOTION_RENDER_CREDITS_PER_STARTED_MINUTE,
) -> int:
    runtime = max(0.0, float(runtime_seconds or 0))
    billable_seconds = max(0.0, runtime - AUTO_STARTED_RENDER_FREE_SECONDS) if auto_started else runtime
    if billable_seconds <= 0:
        return 0
    return int(math.ceil(billable_seconds / 60.0) * credits_per_started_minute)
