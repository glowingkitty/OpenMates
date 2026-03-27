# backend/shared/python_utils/tracing/privacy_filter.py
"""
TracePrivacyFilter — a wrapping SpanExporter that enforces the 3-tier
privacy model before spans are exported to OpenObserve.

OTel Python SDK's on_end() receives immutable ReadableSpan objects, so we
cannot modify attributes in a SpanProcessor. Instead, this module wraps the
real OTLP exporter and creates filtered span copies during export().

Tier attribute visibility:
- Tier 1 (regular user, OK span): Only safe operational attrs, pseudonymized user_id
- Tier 2 (error span): Adds debugging attrs (stacktrace, task IDs, query timing)
- Tier 3 (admin/opted-in): Full visibility except always-strip attrs
- Dev server: All attributes pass through unfiltered

Architecture context: docs/architecture/observability.md
"""

import hashlib
import logging
import os
from datetime import date
from typing import Dict, Any, Optional, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from backend.shared.python_utils.tracing.user_tier import determine_user_tier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attribute tier lists — define which attributes are visible at each tier
# ---------------------------------------------------------------------------

# Attributes NEVER exported regardless of tier (secrets, raw auth tokens)
ALWAYS_STRIP_ATTRS = frozenset({
    "http.request.header.cookie",
    "http.request.header.authorization",
})

# Attributes only kept at Tier 3 (full visibility — admin/opted-in)
TIER_3_ONLY_ATTRS = frozenset({
    "ws.payload_size",
    "cache.key",
    "cache.value",
    "llm.timing",
    "llm.token_count",
    "skill.params",
})

# Attributes only kept at Tier 2+ (operational debugging — error spans, admin)
TIER_2_ONLY_ATTRS = frozenset({
    "exception.stacktrace",
    "http.request.header.authorization_type",
    "http.request.header.content_type",
    "cache.hit",
    "db.query_timing",
    "celery.task_id",
    "celery.queue",
})

# Attributes stripped at Tier 1 but not in the tier-2/tier-3 lists above
# (these are sensitive data attributes that should only be visible at Tier 3)
TIER_1_STRIP_ATTRS = frozenset({
    "db.statement",
    "rpc.request.body",
})

# ---------------------------------------------------------------------------
# Daily salt cache for user ID pseudonymization
# ---------------------------------------------------------------------------
_cached_salt: Optional[str] = None
_cached_salt_date: Optional[date] = None

SALT_PREFIX = "otel-salt"
PSEUDONYM_LENGTH = 12
SALT_LENGTH = 16


def _pseudonymize_user_id(user_id: str) -> str:
    """
    Pseudonymize a user ID using SHA256 with a daily-rotated salt.

    The salt is derived from the current date, ensuring that pseudonymized
    IDs change daily — preventing long-term tracking while still allowing
    same-day correlation of spans from the same user.

    Args:
        user_id: The real user ID to pseudonymize.

    Returns:
        str: First 12 hex characters of SHA256(user_id:daily_salt).
    """
    global _cached_salt, _cached_salt_date

    today = date.today()
    if _cached_salt is None or _cached_salt_date != today:
        # Generate new daily salt
        salt_input = f"{SALT_PREFIX}:{today.isoformat()}"
        _cached_salt = hashlib.sha256(salt_input.encode()).hexdigest()[:SALT_LENGTH]
        _cached_salt_date = today

    hash_input = f"{user_id}:{_cached_salt}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:PSEUDONYM_LENGTH]


def _filter_attributes(attributes: Dict[str, Any], tier: int) -> Dict[str, Any]:
    """
    Filter span attributes based on the privacy tier.

    Args:
        attributes: Original span attributes dict.
        tier: Privacy tier (1, 2, or 3).

    Returns:
        Dict with filtered attributes appropriate for the tier.
    """
    filtered = {}

    for key, value in attributes.items():
        # Always strip sensitive auth/cookie attrs regardless of tier
        if key in ALWAYS_STRIP_ATTRS:
            continue

        # Tier 3 only attrs — stripped at Tier 1 and 2
        if key in TIER_3_ONLY_ATTRS and tier < 3:
            continue

        # Tier 2+ only attrs — stripped at Tier 1
        if key in TIER_2_ONLY_ATTRS and tier < 2:
            continue

        # Tier 1 strip attrs (db.statement, rpc.request.body) — stripped at Tier 1 and 2
        if key in TIER_1_STRIP_ATTRS and tier < 3:
            continue

        # Pseudonymize user ID at Tier 1
        if key == "enduser.id" and tier == 1:
            filtered[key] = _pseudonymize_user_id(str(value))
            continue

        filtered[key] = value

    return filtered


class _FilteredSpan:
    """
    A lightweight wrapper around ReadableSpan with filtered attributes.

    OTel ReadableSpan is immutable, so we create this proxy object that
    delegates all properties to the original span but overrides attributes.
    """

    def __init__(self, original: ReadableSpan, filtered_attrs: Dict[str, Any]) -> None:
        self._original = original
        self._filtered_attrs = filtered_attrs

    @property
    def attributes(self) -> Dict[str, Any]:
        """Return the filtered attributes instead of the original ones."""
        return self._filtered_attrs

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attribute access to the original span."""
        return getattr(self._original, name)


class TracePrivacyFilter(SpanExporter):
    """
    Wrapping SpanExporter that applies privacy filtering before forwarding
    spans to the real exporter (typically OTLPSpanExporter).

    On dev servers (SERVER_ENVIRONMENT=dev), all filtering is bypassed
    and spans pass through unchanged for maximum debugging visibility.

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
        # Dev server: bypass all filtering for maximum debugging visibility
        server_env = os.getenv("SERVER_ENVIRONMENT", "dev")
        if server_env == "dev":
            return self._inner.export(spans)

        filtered_spans = []
        for span in spans:
            # Get attributes as a dict (ReadableSpan.attributes may be a BoundedAttributes)
            attrs = dict(span.attributes) if span.attributes else {}
            tier = determine_user_tier(attrs)
            filtered_attrs = _filter_attributes(attrs, tier)
            filtered_spans.append(_FilteredSpan(span, filtered_attrs))

        return self._inner.export(filtered_spans)

    def shutdown(self) -> None:
        """Delegate shutdown to the inner exporter."""
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Delegate force_flush to the inner exporter."""
        return self._inner.force_flush(timeout_millis)
