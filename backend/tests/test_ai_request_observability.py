# backend/tests/test_ai_request_observability.py
"""Focused contract tests for privacy-safe AI request phase telemetry.

These tests prove count bucketing, span hierarchy, normalized failure state,
and the absence of automatically captured exception payloads. Product AI
decisions and response content are intentionally outside this helper.
"""

import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.shared.python_utils.tracing.ai_observability import (
    AICompletionTiming,
    ai_provider_span,
    ai_phase_span,
    count_bucket,
    observe_ai_stream,
    record_ai_completion_timing,
    record_ai_queue_span,
)


@pytest.fixture
def phase_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)
    yield exporter
    provider.shutdown()


# contract-test: direct surface=rest_api assertions=ai-request-observability.default-metrics.identity-free
def test_count_bucket_is_bounded_and_low_cardinality():
    assert count_bucket(-1) == "0"
    assert count_bucket(1) == "1"
    assert count_bucket(18) == "11_50"
    assert count_bucket(39521) == "10k_50k"
    assert count_bucket(100000) == "50k_plus"


# contract-test: direct surface=cli assertions=ai-request-observability.waterfall.complete
def test_phase_spans_form_a_content_free_hierarchy(phase_exporter):
    with ai_phase_span("turn"):
        with ai_phase_span("preprocess"):
            pass

    spans = {span.name: span for span in phase_exporter.get_finished_spans()}
    assert spans["ai.preprocess"].parent.span_id == spans["ai.turn"].context.span_id
    assert set(spans["ai.preprocess"].attributes) == {
        "ai.phase",
        "ai.status_class",
        "ai.duration_ms",
    }


# contract-test: direct surface=cli assertions=ai-request-observability.waterfall.complete,ai-request-observability.structural-traces.content-free
def test_queue_span_uses_internal_timestamp_without_request_identity(phase_exporter):
    assert record_ai_queue_span(1_000_000_000)

    span = phase_exporter.get_finished_spans()[0]
    assert span.name == "ai.queue"
    assert set(span.attributes) == {
        "ai.phase",
        "ai.status_class",
        "ai.duration_ms",
    }


# contract-test: direct surface=rest_api assertions=ai-request-observability.waterfall.complete
def test_queue_span_rejects_missing_or_invalid_timestamp(phase_exporter):
    assert not record_ai_queue_span(None)
    assert not record_ai_queue_span("not-a-timestamp")
    assert phase_exporter.get_finished_spans() == ()


# contract-test: direct surface=rest_api assertions=ai-request-observability.exporter.allowlist,ai-request-observability.no-behavior-change
def test_phase_error_is_normalized_without_exception_payload(phase_exporter):
    with pytest.raises(RuntimeError, match="private provider response"):
        with ai_phase_span("main"):
            raise RuntimeError("private provider response")

    span = phase_exporter.get_finished_spans()[0]
    assert span.attributes["ai.status_class"] == "error"
    assert not span.events
    assert "private provider response" not in str(span.attributes)


# contract-test: direct surface=rest_api assertions=ai-request-observability.waterfall.complete
def test_stream_span_records_ttft_without_chunk_content(phase_exporter):
    async def exercise():
        async def chunks():
            yield "private response content"

        return [item async for item in observe_ai_stream(chunks(), "provider")]

    output = asyncio.run(exercise())
    assert output == ["private response content"]
    span = phase_exporter.get_finished_spans()[0]
    assert span.name == "ai.provider"
    assert "ai.ttft_ms" in span.attributes
    assert "ai.stream_duration_ms" in span.attributes
    assert "private response content" not in str(span.attributes)


# contract-test: direct surface=rest_api assertions=ai-request-observability.default-metrics.identity-free
def test_unreviewed_phase_is_rejected():
    with pytest.raises(ValueError, match="Unreviewed AI observability phase"):
        with ai_phase_span("private-dynamic-value"):
            pass


# contract-test: direct surface=rest_api assertions=ai-request-observability.waterfall.complete,ai-request-observability.exporter.allowlist
def test_provider_purpose_is_reviewed_and_content_free(phase_exporter):
    with ai_provider_span("translation"):
        pass

    span = phase_exporter.get_finished_spans()[0]
    assert span.name == "ai.provider"
    assert span.attributes["ai.provider_purpose"] == "translation"
    assert set(span.attributes) == {
        "ai.phase",
        "ai.status_class",
        "ai.provider_purpose",
        "ai.duration_ms",
    }

    with pytest.raises(ValueError, match="Unreviewed AI provider purpose"):
        with ai_provider_span("private-dynamic-purpose"):
            pass


# contract-test: direct surface=cli assertions=ai-request-observability.waterfall.complete,ai-request-observability.structural-traces.content-free
def test_completion_timing_uses_reviewed_terminal_class(phase_exporter):
    with ai_phase_span("turn") as span:
        record_ai_completion_timing(
            span,
            first_token_ms=800.0,
            final_marker_ms=10_000.0,
            worker_tail_ms=5_000.0,
            terminal_class="completed",
        )

    exported = phase_exporter.get_finished_spans()[0]
    assert exported.attributes["ai.first_token_ms"] == 800.0
    assert exported.attributes["ai.final_marker_ms"] == 10_000.0
    assert exported.attributes["ai.worker_tail_ms"] == 5_000.0
    assert exported.attributes["ai.terminal_class"] == "completed"

    with pytest.raises(ValueError, match="Unreviewed AI terminal class"):
        record_ai_completion_timing(span, terminal_class="private-error")


# contract-test: direct surface=rest_api assertions=ai-request-observability.waterfall.complete
def test_completion_timing_records_only_first_visible_content_and_final_marker(monkeypatch):
    clock = iter((10.0, 10.8, 12.0, 15.0))
    monkeypatch.setattr(
        "backend.shared.python_utils.tracing.ai_observability.monotonic",
        lambda: next(clock),
    )

    timing = AICompletionTiming.start()
    timing.mark_first_visible_content()
    timing.mark_first_visible_content()
    timing.mark_final_marker()

    assert timing.first_token_ms == pytest.approx(800.0)
    assert timing.final_marker_ms == pytest.approx(2000.0)
    assert timing.worker_tail_ms() == pytest.approx(3000.0)


# contract-test: direct surface=rest_api assertions=ai-request-observability.waterfall.complete
@pytest.mark.parametrize(
    "phase",
    ["setup", "compression", "pre_main", "main.response_finalize", "postprocess.delivery", "queue_handoff"],
)
def test_reviewed_lifecycle_gap_phases_are_supported(phase_exporter, phase):
    with ai_phase_span(phase):
        pass

    assert phase_exporter.get_finished_spans()[0].name == f"ai.{phase}"
