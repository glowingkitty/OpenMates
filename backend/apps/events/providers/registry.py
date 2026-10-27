"""Validate official conference schedule source selection."""
import logging
from typing import Dict, List, Optional
logger = logging.getLogger(__name__)
_VALID_PROVIDER_IDS = frozenset({"pretalx"})
_NAME_TO_ID = {"pretalx": "pretalx", "conference schedule": "pretalx", "conference schedules": "pretalx",
               **{key: "pretalx" for key in ("gpn", "gpn24", "39c3", "38c3", "37c3")}}

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
        # Prefer explicit "id" field; fall back to deriving from "name"
        pid = meta.get("id")
        if not pid:
            name = (meta.get("name") or "").lower()
            pid = _NAME_TO_ID.get(name)
        if not pid or pid not in _VALID_PROVIDER_IDS:
            continue

        if meta.get("available") is False:
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
        elif scope == "conference":
            # Conference schedules are opt-in. They are added explicitly by the
            # search skill when a known conference alias is present.
            if requested_providers:
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

    # LLM made a selection — normalize display names/aliases, then validate.
    normalized_requested = [
        _NAME_TO_ID.get(str(provider).lower().strip(), str(provider).lower().strip())
        for provider in requested_providers
    ]
    validated = [p for p in normalized_requested if p in applicable_set]
    stripped = [p for p in normalized_requested if p not in applicable_set]

    if stripped:
        logger.warning(
            "Stripped %d non-applicable providers for city=%r: %s (kept: %s)",
            len(stripped), city, stripped, validated,
        )

    if not validated:
        # The caller made an explicit provider choice. Do not broaden it to auto;
        # returning no providers lets the skill surface a visible provider error.
        logger.warning(
            "All LLM-chosen providers stripped for city=%r: %s",
            city, normalized_requested,
        )
        return []

    return validated
