# backend/shared/python_utils/tracing/privacy_filter.py
"""
TracePrivacyFilter — a strict allowlist applied before OpenObserve export.

OTel Python SDK's on_end() receives immutable ReadableSpan objects, so we
cannot modify attributes in a SpanProcessor. Instead, this module wraps the
real OTLP exporter and creates filtered span copies during export().

All tiers use the same structural allowlist. Tier 3 eligibility can add only
reviewed exact non-content fields when an audited scope is active and expires
within 24 hours. Raw identities, content, errors, events, and links never pass.

Architecture context: docs/architecture/observability.md
"""

import logging
import os
import time
from typing import Any, Dict, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status

from backend.shared.python_utils.tracing.user_tier import determine_user_tier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reviewed attribute allowlists
# ---------------------------------------------------------------------------

DEFAULT_ALLOWED_ATTRS = frozenset({
    "service.name",
    "http.method",
    "http.route",
    "http.status_code",
    "http.request.method",
    "http.response.status_code",
    "server.port",
    "network.protocol.version",
    "rpc.system",
    "rpc.service",
    "rpc.method",
    "db.system",
    "messaging.system",
    "messaging.operation",
    "ws.message_type",
    "cache.hit",
    "celery.queue",
    "otel.status_code",
    "ai.phase",
    "ai.status_class",
    "ai.model_family",
    "ai.capability_category",
    "ai.duration_ms",
    "ai.ttft_ms",
    "ai.stream_duration_ms",
    "ai.provider_purpose",
    "ai.terminal_class",
    "ai.first_token_ms",
    "ai.final_marker_ms",
    "ai.worker_tail_ms",
    "ai.token_count_bucket",
    "ai.character_count_bucket",
    "ai.message_count_bucket",
    "ai.request_count_bucket",
    "ai.result_count_bucket",
    "ai.retry_count_bucket",
})

DIAGNOSTIC_ALLOWED_ATTRS = frozenset({
    "ai.token_count",
    "ai.character_count",
    "ai.message_count",
    "ai.request_count",
    "ai.result_count",
    "ai.retry_count",
    "ai.model_id",
    "ai.app_id",
    "ai.skill_id",
})

DIAGNOSTIC_SCOPE_MAX_SECONDS = 24 * 60 * 60


def _diagnostic_scope_active(tier: int) -> bool:
    """Require an owned, justified, audited scope bounded to 24 hours."""
    required_text = (
        "OTEL_DIAGNOSTIC_AUDIT_ID",
        "OTEL_DIAGNOSTIC_OWNER",
        "OTEL_DIAGNOSTIC_REASON",
    )
    if tier < 3 or any(not os.getenv(name, "").strip() for name in required_text):
        return False
    try:
        started_at = float(os.getenv("OTEL_DIAGNOSTIC_STARTED_AT", "0"))
        expires_at = float(os.getenv("OTEL_DIAGNOSTIC_EXPIRES_AT", "0"))
    except ValueError:
        return False
    now = time.time()
    return (
        0 < started_at <= now < expires_at
        and expires_at - started_at <= DIAGNOSTIC_SCOPE_MAX_SECONDS
    )


def _filter_attributes(attributes: Dict[str, Any], tier: int) -> Dict[str, Any]:
    """
    Filter span attributes based on the privacy tier.

    Args:
        attributes: Original span attributes dict.
        tier: Privacy tier (1, 2, or 3).

    Returns:
        Dict with filtered attributes appropriate for the tier.
    """
    allowed = DEFAULT_ALLOWED_ATTRS
    if _diagnostic_scope_active(tier):
        allowed = allowed | DIAGNOSTIC_ALLOWED_ATTRS
    return {key: value for key, value in attributes.items() if key in allowed}


class _FilteredSpan:
    """
    A lightweight wrapper around ReadableSpan with filtered attributes.

    OTel ReadableSpan is immutable, so we create this proxy object that
    delegates all properties to the original span but overrides attributes.
    """

    def __init__(
        self,
        original: ReadableSpan,
        filtered_attrs: Dict[str, Any],
        filtered_resource: Resource,
    ) -> None:
        self._original = original
        self._filtered_attrs = filtered_attrs
        self._filtered_resource = filtered_resource

    @property
    def attributes(self) -> Dict[str, Any]:
        """Return the filtered attributes instead of the original ones."""
        return self._filtered_attrs

    @property
    def resource(self) -> Resource:
        """Return only reviewed resource attributes to prevent OTLP bypasses."""
        return self._filtered_resource

    @property
    def events(self) -> tuple:
        """Drop event payloads because exception events can contain private text."""
        return ()

    @property
    def links(self) -> tuple:
        """Drop link attributes; parentage remains available through span context."""
        return ()

    @property
    def status(self) -> Status:
        """Preserve normalized status code while dropping its free-text description."""
        return Status(self._original.status.status_code)

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attribute access to the original span."""
        return getattr(self._original, name)


class TracePrivacyFilter(SpanExporter):
    """
    Wrapping SpanExporter that applies privacy filtering before forwarding
    spans to the real exporter (typically OTLPSpanExporter).

    Args:
        inner: The real SpanExporter to forward filtered spans to.
    """

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """
        Filter span attributes based on privacy tier, then forward to inner exporter.

        Args:
            spans: Sequence of ReadableSpan objects from the SDK.

        Returns:
            SpanExportResult from the inner exporter.
        """
        filtered_spans = []
        for span in spans:
            # Get attributes as a dict (ReadableSpan.attributes may be a BoundedAttributes)
            attrs = dict(span.attributes) if span.attributes else {}
            tier = determine_user_tier(attrs)
            filtered_attrs = _filter_attributes(attrs, tier)
            resource_attrs = dict(span.resource.attributes) if span.resource else {}
            filtered_resource = Resource(_filter_attributes(resource_attrs, tier))
            filtered_spans.append(_FilteredSpan(span, filtered_attrs, filtered_resource))

        return self._inner.export(filtered_spans)

    def shutdown(self) -> None:
        """Delegate shutdown to the inner exporter."""
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Delegate force_flush to the inner exporter."""
        return self._inner.force_flush(timeout_millis)
