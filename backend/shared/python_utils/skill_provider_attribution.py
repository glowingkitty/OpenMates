"""Provider attribution helpers shared by app-skill billing surfaces."""

from __future__ import annotations

from typing import Any, Optional


def resolve_skill_usage_provider_id(
    app_id: str,
    skill_id: str,
    skill_definition: Any,
    result_data: Any = None,
) -> Optional[str]:
    """Resolve the provider ID used for billing metadata without guessing weather routing."""
    full_model_reference = getattr(skill_definition, "full_model_reference", None)
    if isinstance(full_model_reference, str) and "/" in full_model_reference:
        return full_model_reference.split("/", 1)[0]

    providers = getattr(skill_definition, "providers", None) or []
    declared_provider_ids = {
        provider.name
        for provider in providers
        if isinstance(getattr(provider, "name", None), str) and provider.name
    }

    # Forecast routing is location-dependent. Its trusted top-level response
    # identifies the provider that actually ran, so missing, mixed, or unknown
    # IDs must remain unattributed instead of falling back to providers[0].
    if app_id == "weather" and skill_id == "forecast":
        result_items = result_data if isinstance(result_data, list) else [result_data]
        if not result_items or any(not isinstance(item, dict) for item in result_items):
            return None
        executed_provider_id_values = [
            item.get("provider_id")
            for item in result_items
            if isinstance(item.get("provider_id"), str) and item.get("provider_id")
        ]
        executed_provider_ids = set(executed_provider_id_values)
        if len(executed_provider_id_values) != len(result_items) or len(executed_provider_ids) != 1:
            return None
        executed_provider_id = next(iter(executed_provider_ids))
        return executed_provider_id if executed_provider_id in declared_provider_ids else None

    if providers:
        return providers[0].name
    return None
