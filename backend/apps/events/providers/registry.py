# backend/apps/events/providers/registry.py
"""
Provider registry — safety filter for event search provider selection.

Validates LLM-chosen providers against region scope metadata from app.yml.
Ensures providers that don't serve the requested region are never called,
eliminating wasted HTTP requests and proxy latency.

Scope hierarchy (from app.yml provider metadata):
  - global: Provider serves any location (e.g. Meetup, Luma)
  - city:   Provider serves a single city only (e.g. Siegessäule → Berlin)
  - country: Provider serves a single country (future)
  - continent: Provider serves a continent (future)

Architecture context: docs/architecture/apps/events.md
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# All known provider IDs — used for backward-compat validation
_VALID_PROVIDER_IDS = frozenset({
    "meetup", "luma", "google_events", "resident_advisor", "siegessaeule",
})


def filter_providers(
    requested_providers: Optional[List[str]],
    city: str,
    providers_meta: List[Dict],
) -> List[str]:
    """
    Validate and filter provider IDs based on region scope.

    If requested_providers is empty/None, returns all region-applicable providers.
    If requested_providers is given, strips any that don't serve the requested region.

    Args:
        requested_providers: Provider IDs chosen by the LLM (from per-request field),
            or None to auto-select all applicable providers.
        city: Normalized city name from the search request (e.g. "Berlin, Germany").
        providers_meta: Provider metadata list from app.yml (with id, scope, region).

    Returns:
        List of validated provider IDs that are applicable for this city.
    """
    city_lower = city.lower() if city else ""

    # Build region-applicable set from metadata
    applicable: List[str] = []
    for meta in providers_meta:
        pid = meta.get("id")
        if not pid or pid not in _VALID_PROVIDER_IDS:
            continue

        scope = meta.get("scope", "global")
        if scope == "global":
            applicable.append(pid)
        elif scope == "city":
            region = (meta.get("region") or "").lower()
            if region and region in city_lower:
                applicable.append(pid)
        elif scope == "country":
            region = (meta.get("region") or "").lower()
            if region and region in city_lower:
                applicable.append(pid)
        elif scope == "continent":
            # Future: continent-level matching
            applicable.append(pid)
        else:
            # Unknown scope — include as fallback
            applicable.append(pid)

    applicable_set = set(applicable)

    if not requested_providers:
        # No LLM selection — return all applicable
        logger.info(
            "Provider auto-select for city=%r: %s (%d/%d)",
            city, applicable, len(applicable), len(providers_meta),
        )
        return applicable

    # LLM made a selection — validate against applicable set
    validated = [p for p in requested_providers if p in applicable_set]
    stripped = [p for p in requested_providers if p not in applicable_set]

    if stripped:
        logger.warning(
            "Stripped %d non-applicable providers for city=%r: %s (kept: %s)",
            len(stripped), city, stripped, validated,
        )

    if not validated:
        # LLM chose only non-applicable providers — fall back to all applicable
        logger.warning(
            "All LLM-chosen providers stripped for city=%r, falling back to auto: %s",
            city, applicable,
        )
        return applicable

    return validated
