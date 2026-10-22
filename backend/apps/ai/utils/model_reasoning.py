"""Resolve turn reasoning recommendations using explicit model/server capabilities.

Only server-local ``reasoning_control`` metadata enables a control. Provider
identity, adapter enums and ``reasoning: true`` are deliberately insufficient.
"""
from collections.abc import Mapping
from typing import Any

REASONING_LEVELS = ("LOW", "MEDIUM", "HIGH", "EXTRA_HIGH")


def normalize_reasoning_level(value: Any) -> str | None:
    """Normalize the four Jev recommendation levels; reject other values."""
    if not isinstance(value, str):
        return None
    level = value.strip().upper()
    return level if level in REASONING_LEVELS else None


def resolve_reasoning_parameters(
    model_config: Mapping[str, Any] | None,
    server_id: str,
    requested_level: Any,
) -> dict[str, str]:
    """Return native dispatch kwargs, clamping unsupported effort to the ceiling.

    ``servers[].reasoning_control`` declares ``parameter`` and ``levels`` (a
    canonical-level-to-native-value mapping). ``fixed: true`` preserves explicit
    effort variants. Missing/invalid recommendations preserve adapter defaults.
    Unknown servers and undeclared controls never inherit another route's support.
    """
    level = normalize_reasoning_level(requested_level)
    if level is None or not isinstance(model_config, Mapping):
        return {}
    # A model-wide fixed marker can protect every hosting route for a variant.
    model_control = model_config.get("reasoning_control")
    if isinstance(model_control, Mapping) and model_control.get("fixed"):
        return {}
    servers = model_config.get("servers")
    if not isinstance(servers, list):
        return {}
    server = next((item for item in servers if isinstance(item, Mapping)
                   and item.get("id") == server_id), None)
    if server is None:
        return {}
    control = server.get("reasoning_control")
    if not isinstance(control, Mapping) or control.get("fixed"):
        return {}
    parameter, levels = control.get("parameter"), control.get("levels")
    if parameter not in {"thinking_level", "reasoning_effort"} or not isinstance(levels, Mapping):
        return {}
    # Fail closed on malformed metadata rather than accidentally enabling a
    # partial declaration whose real maximum is unknown.
    if not levels or any(key not in REASONING_LEVELS or not isinstance(value, str)
                         or not value.strip() for key, value in levels.items()):
        return {}
    resolved = level if level in levels else next(
        candidate for candidate in reversed(REASONING_LEVELS) if candidate in levels
    )
    return {parameter: levels[resolved]}
