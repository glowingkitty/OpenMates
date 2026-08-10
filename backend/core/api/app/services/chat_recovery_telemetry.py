"""Sanitized duration telemetry for durable chat recovery protocol phases.

The preflight and enqueue paths process encrypted chat state and transient model
requests. This module intentionally records only a fixed protocol phase and a
monotonic duration so performance analysis never receives user, chat, key, or
message data.
"""

from __future__ import annotations

import logging
import time


logger = logging.getLogger(__name__)
RECOVERY_TIMING_PHASES = frozenset({"durable_preflight", "enqueue_inference"})


def start_recovery_timing() -> float:
    """Return a monotonic start value for a recovery protocol phase."""
    return time.perf_counter()


def record_recovery_duration(phase: str, started_at: float) -> float:
    """Log a sanitized recovery phase duration and return milliseconds."""
    if phase not in RECOVERY_TIMING_PHASES:
        raise ValueError(f"unsupported recovery timing phase: {phase}")
    duration_ms = (time.perf_counter() - started_at) * 1000.0
    try:
        logger.info(
            "Chat recovery protocol phase completed",
            extra={"recovery_phase": phase, "duration_ms": duration_ms},
        )
    except Exception:
        # Observability must not change the recovery protocol result.
        pass
    return duration_ms
