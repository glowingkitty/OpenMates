"""Public, schema-derived presentation data for the Apps workspace.

Only request-schema defaults are returned. Workflow test examples are deliberately
excluded: they are fixtures, not safe user defaults.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def request_schema(skill: Any) -> dict[str, Any]:
    """Return the direct caller's schema with Apps-only presentation hints."""
    schema = skill.sdk_tool_schema or skill.tool_schema
    if not isinstance(schema, dict):
        return {}
    result = deepcopy(schema)
    _normalize_apps_ui_hints(result)
    return result


def _normalize_apps_ui_hints(node: Any) -> None:
    """Apply ``x-ui.apps`` only to this detached public Apps schema copy."""
    if isinstance(node, list):
        for item in node:
            _normalize_apps_ui_hints(item)
        return
    if not isinstance(node, dict):
        return
    ui = node.get("x-ui")
    if isinstance(ui, dict) and isinstance(ui.get("apps"), dict):
        node["x-ui"] = {**{key: value for key, value in ui.items() if key != "apps"}, **ui["apps"]}
    for key, value in node.items():
        if key != "x-ui":
            _normalize_apps_ui_hints(value)


def schema_defaults(schema: dict[str, Any]) -> dict[str, Any]:
    """Build a partial request with declared defaults, including one array item."""
    result = _default_value(schema)
    return result if isinstance(result, dict) else {}


def _default_value(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return None
    if "default" in schema:
        return deepcopy(schema["default"])
    if schema.get("type") == "object":
        values = {
            name: value
            for name, child in (schema.get("properties") or {}).items()
            if (value := _default_value(child)) is not None
        }
        return values or None
    if schema.get("type") == "array":
        item = _default_value(schema.get("items"))
        return [item] if item is not None else None
    return None


def primary_fields(schema: dict[str, Any]) -> list[str]:
    """Select at most two form controls from public x-ui hints and required fields.

    Count editable leaf controls, including fields inside nested route objects.
    Paths use ``[]`` for array items so the web form preserves request shape.
    """
    candidates: list[tuple[str, bool, bool]] = []

    def walk(node: Any, path: str, required: bool = False) -> None:
        if not isinstance(node, dict):
            return
        ui = node.get("x-ui") or {}
        if ui.get("hidden") is True:
            return
        kind = node.get("type")
        if kind == "array":
            items = node.get("items") or {}
            if isinstance(items, dict) and items.get("type") == "object":
                walk(items, f"{path}[]", required)
            else:
                candidates.append((path, ui.get("basic") is True, required))
            return
        if kind == "object":
            properties = node.get("properties") or {}
            mandatory = set(node.get("required") or [])
            if not properties:
                if path:
                    candidates.append((path, ui.get("basic") is True, required))
                return
            # A date range uses the start path as its control anchor. The
            # sibling end field is rendered by the same x-ui date-range hint.
            date_end = ui.get("end_field") if ui.get("control") == "date-range" else None
            for name, child in properties.items():
                if name == date_end:
                    continue
                walk(child, f"{path}.{name}" if path else name, name in mandatory)
            return
        if path and ui.get("basic") is not False:
            candidates.append((path, ui.get("basic") is True, required))

    walk(schema, "")
    # Preserve schema order among fields with the same priority. Required input
    # beats an optional "basic" setting such as count or provider.
    ranked = sorted(enumerate(candidates), key=lambda item: (
        not item[1][2], not item[1][1], item[0]
    ))
    return [candidate[0] for _, candidate in ranked[:2]]


def execution_status(*, app_id: str, skill: Any, registry: Any, capability: Any) -> tuple[bool, str | None, str | None]:
    """Fail closed unless the runtime, direct REST route and workflow seed agree."""
    workflow = (capability.metadata or {}).get("workflow") if capability else None
    mode = workflow.get("execution_mode") if isinstance(workflow, dict) else None
    if not skill.class_path or not registry or not registry.is_skill_available(app_id, skill.id):
        return False, "SKILL_NOT_REGISTERED", mode
    if skill.api_config and not skill.api_config.expose_post:
        return False, "REST_EXECUTION_UNAVAILABLE", mode
    if capability is None:
        return False, "WORKFLOW_CLASSIFICATION_REQUIRED", mode
    if not capability.enabled:
        return False, capability.reason or "WORKFLOW_UNAVAILABLE", mode
    if mode not in {"sync", "async_job", "sandbox"}:
        return False, "DIRECT_EXECUTION_UNSUPPORTED", mode
    return True, None, mode
