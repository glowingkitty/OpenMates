# backend/tests/test_ai_request_observability.py
"""Focused contract tests for privacy-safe AI request phase telemetry.

These tests prove count bucketing, span hierarchy, normalized failure state,
and the absence of automatically captured exception payloads. Product AI
decisions and response content are intentionally outside this helper.
"""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.shared.python_utils.tracing.ai_observability import (
    ai_phase_span,
    count_bucket,
    observe_ai_stream,
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


# contract-test: direct surface=rest_api assertions=ai-request-observability.waterfall.complete
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
@pytest.mark.asyncio
async def test_stream_span_records_ttft_without_chunk_content(phase_exporter):
    async def chunks():
        yield "private response content"

    output = [item async for item in observe_ai_stream(chunks(), "main.iteration")]

    assert output == ["private response content"]
    span = phase_exporter.get_finished_spans()[0]
    assert span.name == "ai.main.iteration"
    assert "ai.ttft_ms" in span.attributes
    assert "ai.stream_duration_ms" in span.attributes
    assert "private response content" not in str(span.attributes)


# contract-test: direct surface=rest_api assertions=ai-request-observability.default-metrics.identity-free
def test_unreviewed_phase_is_rejected():
    with pytest.raises(ValueError, match="Unreviewed AI observability phase"):
        with ai_phase_span("private-dynamic-value"):
            pass
