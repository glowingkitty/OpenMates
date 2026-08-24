# backend/shared/python_utils/tracing/user_tier.py
"""
User tier resolution for OpenTelemetry privacy filtering.

Determines diagnostic eligibility (tiers 1-3) from span attributes. The privacy
exporter always applies a strict structural allowlist; tier 3 only permits an
additional reviewed non-content allowlist when a separate audited scope is
active and time bounded.

Note: The actual user attributes (is_admin, debug_opted_in) are injected
by WebSocket handlers and middleware in Plan 03. This module only reads
from span attributes that callers have already set.

Architecture context: docs/architecture/observability.md
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Tier level constants for clarity
TIER_FULL_VISIBILITY = 3
TIER_OPERATIONAL = 2
TIER_MINIMAL = 1


def determine_user_tier(span_attributes: Dict[str, Any]) -> int:
    """
    Determine the privacy tier for a span based on its attributes.

    Args:
        span_attributes: Dictionary of span attributes. Expected keys include
            'enduser.is_admin', 'enduser.debug_opted_in', and 'otel.status_code'.

    Returns:
        int: Privacy tier level (1, 2, or 3).
            - 3: Admin or debug-opted-in user eligible for bounded diagnostics
            - 2: Error span eligible for normalized operational metadata
            - 1: Normal span with the default structural allowlist
    """
    # Admin/debug flags establish eligibility only; exporter scope still gates fields.
    if span_attributes.get("enduser.is_admin") is True:
        return TIER_FULL_VISIBILITY

    # Users who opted into debug logging get full visibility
    if span_attributes.get("enduser.debug_opted_in") is True:
        return TIER_FULL_VISIBILITY

    # Error spans need operational context for debugging
    if span_attributes.get("otel.status_code") == "ERROR":
        return TIER_OPERATIONAL

    # Default: minimal privacy-preserving tier
    return TIER_MINIMAL
