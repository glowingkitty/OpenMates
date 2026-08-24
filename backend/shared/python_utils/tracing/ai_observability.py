# backend/shared/python_utils/tracing/ai_observability.py
"""Privacy-safe AI phase spans and aggregate duration metrics.

This module records structural timing only. It disables automatic exception
capture, uses reviewed attributes, and exposes count buckets so callers never
need to attach prompts, results, private identifiers, or raw errors.
Architecture: contracts/architecture/ai-request-observability/contract.yml
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from time import monotonic
from typing import AsyncIterator, Iterator, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

try:
    from prometheus_client import Histogram

    AI_PHASE_DURATION_SECONDS = Histogram(
        "openmates_ai_phase_duration_seconds",
        "AI request phase duration without request identity or content.",
        ("phase", "status_class"),
    )
except (ImportError, ValueError):  # ValueError covers duplicate test registries.
    AI_PHASE_DURATION_SECONDS = None


COUNT_BUCKETS = (
    (0, "0"),
    (1, "1"),
    (5, "2_5"),
    (10, "6_10"),
    (50, "11_50"),
    (100, "51_100"),
    (1000, "101_1k"),
    (10000, "1k_10k"),
    (50000, "10k_50k"),
)

T = TypeVar("T")

AI_PHASES = frozenset({
    "turn",
    "prepare",
    "preprocess",
    "main",
    "main.iteration",
    "tool",
    "finalize.billing",
    "finalize.persistence",
    "finalize.validation",
    "finalize.marker",
    "postprocess",
})


def count_bucket(value: int) -> str:
    """Return a bounded, low-cardinality bucket for a non-negative count."""
    normalized = max(0, int(value))
    for upper_bound, label in COUNT_BUCKETS:
        if normalized <= upper_bound:
            return label
    return "50k_plus"


@contextmanager
def ai_phase_span(phase: str) -> Iterator[Span]:
    """Create one content-free phase span and aggregate duration observation."""
    if phase not in AI_PHASES:
        raise ValueError(f"Unreviewed AI observability phase: {phase}")
    started_at = monotonic()
    status_class = "ok"
    tracer = trace.get_tracer("openmates.ai.observability")
    with tracer.start_as_current_span(
        f"ai.{phase}",
        attributes={"ai.phase": phase, "ai.status_class": status_class},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except (asyncio.CancelledError, GeneratorExit):
            status_class = "cancelled"
            span.set_attribute("ai.status_class", status_class)
            raise
        except BaseException:
            status_class = "error"
            span.set_attribute("ai.status_class", status_class)
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            duration_ms = (monotonic() - started_at) * 1000
            span.set_attribute("ai.duration_ms", duration_ms)
            if AI_PHASE_DURATION_SECONDS is not None:
                AI_PHASE_DURATION_SECONDS.labels(
                    phase=phase,
                    status_class=status_class,
                ).observe(duration_ms / 1000)


async def observe_ai_stream(stream: AsyncIterator[T], phase: str) -> AsyncIterator[T]:
    """Trace one provider stream, including time to its first yielded chunk."""
    started_at = monotonic()
    first_chunk = True
    with ai_phase_span(phase) as span:
        try:
            async for item in stream:
                if first_chunk:
                    span.set_attribute("ai.ttft_ms", (monotonic() - started_at) * 1000)
                    first_chunk = False
                yield item
        finally:
            span.set_attribute("ai.stream_duration_ms", (monotonic() - started_at) * 1000)
