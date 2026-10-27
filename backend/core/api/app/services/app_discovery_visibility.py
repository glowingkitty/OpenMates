"""Project executable app discovery without changing durable app definitions."""

from collections.abc import Mapping
from typing import Any


EXCLUDED_DISCOVERY_APPS = frozenset({"openmates", "plans", "projects", "tasks", "workflows"})


def _value(definition: Any, key: str, default: Any = None) -> Any:
    return definition.get(key, default) if isinstance(definition, Mapping) else getattr(definition, key, default)


def enabled_discovery_components(components):
    """Ignore paused/internal components even in defensive raw-metadata callers."""
    return [item for item in components or [] if _value(item, "default_enabled") is not False and not _value(item, "internal", False)]


def direct_creation_embeds(embed_types):
    """Only explicitly catalogued direct creation qualifies, not historical renderers."""
    return [
        embed for embed in enabled_discovery_components(embed_types)
        if _value(embed, "category") == "direct"
        and (_value(embed, "content_catalog") or {}).get("enabled") is True
    ]


def creation_content_types(app_id: str, embed_types):
    """Compatible discovery evidence projected only from the explicit creation catalog."""
    result = []
    for embed in direct_creation_embeds(embed_types):
        catalog = _value(embed, "content_catalog")
        content_id = catalog.get("content_type_id") or _value(embed, "id")
        result.append({
            "id": f"{app_id}.{content_id}", "content_type_id": content_id,
            "source": "self", "name": catalog.get("name") or content_id,
            "frontend_type": _value(embed, "frontend_type"),
            "backend_type": _value(embed, "backend_type"),
        })
    return result


def app_is_discoverable(app_id: str, available_skills, enabled_focus_modes, embed_types=()) -> bool:
    """Call after provider/user filtering; durable memory alone does not qualify."""
    return app_id not in EXCLUDED_DISCOVERY_APPS and bool(
        enabled_discovery_components(available_skills)
        or enabled_discovery_components(enabled_focus_modes)
        or direct_creation_embeds(embed_types)
    )
