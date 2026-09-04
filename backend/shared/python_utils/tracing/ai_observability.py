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
from dataclasses import dataclass
from time import monotonic, time_ns
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
AI_QUEUE_ENQUEUED_AT_HEADER = "openmates_ai_queued_at_ns"

AI_PHASES = frozenset({
    "turn",
    "queue",
    "prepare",
    "setup",
    "compression",
    "preprocess",
    "pre_main",
    "main",
    "main.iteration",
    "main.response_finalize",
    "provider",
    "tool",
    "finalize.billing",
    "finalize.persistence",
    "finalize.validation",
    "finalize.marker",
    "postprocess",
    "postprocess.delivery",
    "queue_handoff",
})
AI_PROVIDER_PURPOSES = frozenset({
    "preprocess",
    "main",
    "postprocess",
    "translation",
    "compression",
    "safety",
    "inspiration",
})
AI_TERMINAL_CLASSES = frozenset({
    "completed",
    "failed_before_main",
    "failed_during_main",
    "billing_failed",
    "soft_limited",
    "revoked",
    "worker_interrupted",
})


@dataclass
class AICompletionTiming:
    """Monotonic request-local completion milestones with no request data."""

    started_at: float
    first_token_ms: float | None = None
    final_marker_ms: float | None = None
    billing_failed: bool = False

    @classmethod
    def start(cls) -> "AICompletionTiming":
        return cls(started_at=monotonic())

    def mark_first_visible_content(self) -> None:
        if self.first_token_ms is None:
            self.first_token_ms = (monotonic() - self.started_at) * 1000

    def mark_final_marker(self) -> None:
        if self.final_marker_ms is None:
            self.final_marker_ms = (monotonic() - self.started_at) * 1000

    def worker_tail_ms(self) -> float | None:
        if self.final_marker_ms is None:
            return None
        return max(0.0, (monotonic() - self.started_at) * 1000 - self.final_marker_ms)


def record_ai_queue_span(enqueued_at_ns: object) -> bool:
    """Record broker queue latency from a trusted internal Celery header."""
    try:
        started_at_ns = int(enqueued_at_ns)
    except (TypeError, ValueError):
        return False

    ended_at_ns = time_ns()
    if started_at_ns <= 0 or started_at_ns > ended_at_ns:
        return False

    duration_ms = (ended_at_ns - started_at_ns) / 1_000_000
    tracer = trace.get_tracer("openmates.ai.observability")
    span = tracer.start_span(
        "ai.queue",
        start_time=started_at_ns,
        attributes={
            "ai.phase": "queue",
            "ai.status_class": "ok",
            "ai.duration_ms": duration_ms,
        },
    )
    span.end(end_time=ended_at_ns)
    if AI_PHASE_DURATION_SECONDS is not None:
        AI_PHASE_DURATION_SECONDS.labels(phase="queue", status_class="ok").observe(
            duration_ms / 1000
        )
    return True


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


@contextmanager
def ai_provider_span(purpose: str) -> Iterator[Span]:
    """Create a provider span with one reviewed low-cardinality purpose."""
    if purpose not in AI_PROVIDER_PURPOSES:
        raise ValueError(f"Unreviewed AI provider purpose: {purpose}")
    with ai_phase_span("provider") as span:
        span.set_attribute("ai.provider_purpose", purpose)
        yield span


def record_ai_completion_timing(
    span: Span,
    *,
    first_token_ms: float | None = None,
    final_marker_ms: float | None = None,
    worker_tail_ms: float | None = None,
    terminal_class: str,
) -> None:
    """Attach reviewed completion milestones to the request-scoped turn span."""
    if terminal_class not in AI_TERMINAL_CLASSES:
        raise ValueError(f"Unreviewed AI terminal class: {terminal_class}")
    span.set_attribute("ai.terminal_class", terminal_class)
    for name, value in (
        ("ai.first_token_ms", first_token_ms),
        ("ai.final_marker_ms", final_marker_ms),
        ("ai.worker_tail_ms", worker_tail_ms),
    ):
        if value is None:
            continue
        normalized = float(value)
        if normalized < 0:
            raise ValueError(f"AI completion timing must be non-negative: {name}")
        span.set_attribute(name, normalized)


async def observe_ai_stream(
    stream: AsyncIterator[T],
    phase: str,
    *,
    provider_purpose: str | None = None,
) -> AsyncIterator[T]:
    """Trace one provider stream, including time to its first yielded chunk."""
    started_at = monotonic()
    first_chunk = True
    with ai_phase_span(phase) as span:
        if provider_purpose is not None:
            if phase != "provider" or provider_purpose not in AI_PROVIDER_PURPOSES:
                raise ValueError(f"Unreviewed AI provider purpose: {provider_purpose}")
            span.set_attribute("ai.provider_purpose", provider_purpose)
        try:
            async for item in stream:
                if first_chunk:
                    span.set_attribute("ai.ttft_ms", (monotonic() - started_at) * 1000)
                    first_chunk = False
                yield item
        finally:
            span.set_attribute("ai.stream_duration_ms", (monotonic() - started_at) * 1000)
