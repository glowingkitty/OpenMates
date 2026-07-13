# backend/core/api/app/services/workflow_template_expressions.py
#
# Safe Workflow template-expression resolver. It supports only deterministic
# variable paths and a tiny date/time filter set; arbitrary code, attributes,
# calls, and imports are never evaluated.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any


_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_PATH_PATTERN = re.compile(r"^(steps|trigger|clock)(?:\.[a-zA-Z0-9_-]+)*$")
_FILTER_PATTERN = re.compile(r"^(plus_hours|plus_days):\s*(-?\d+)$")


class WorkflowTemplateExpressionError(ValueError):
    """Raised for unsafe or invalid Workflow template expressions."""


def resolve_workflow_template(value: Any, context: dict[str, Any], *, now: datetime | None = None) -> Any:
    """Resolve safe templates inside scalars, arrays, and mappings."""
    if isinstance(value, str):
        return _resolve_template_string(value, context, now=now or datetime.now(timezone.utc))
    if isinstance(value, list):
        return [resolve_workflow_template(item, context, now=now) for item in value]
    if isinstance(value, dict):
        return {key: resolve_workflow_template(item, context, now=now) for key, item in value.items()}
    return value


def _resolve_template_string(value: str, context: dict[str, Any], *, now: datetime) -> Any:
    matches = list(_TEMPLATE_PATTERN.finditer(value))
    if not matches:
        return _legacy_node_reference(value, context)
    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        return _evaluate_expression(matches[0].group(1), context, now=now)
    rendered = value
    for match in reversed(matches):
        resolved = _evaluate_expression(match.group(1), context, now=now)
        rendered = rendered[: match.start()] + str(resolved) + rendered[match.end() :]
    return rendered


def _evaluate_expression(expression: str, context: dict[str, Any], *, now: datetime) -> Any:
    parts = [part.strip() for part in expression.split("|")]
    if not parts or not _PATH_PATTERN.fullmatch(parts[0]):
        raise WorkflowTemplateExpressionError("Workflow template expressions only support trigger, steps, and clock paths")
    if any(segment.startswith("_") for segment in parts[0].split(".")):
        raise WorkflowTemplateExpressionError("Workflow template paths cannot reference private attributes")
    value = _resolve_path(parts[0], context, now=now)
    for filter_expression in parts[1:]:
        filter_match = _FILTER_PATTERN.fullmatch(filter_expression)
        if filter_match is None:
            raise WorkflowTemplateExpressionError(f"Unsupported Workflow template filter: {filter_expression}")
        filter_name, amount_text = filter_match.groups()
        value = _apply_datetime_filter(value, filter_name, int(amount_text))
    return value


def _resolve_path(path: str, context: dict[str, Any], *, now: datetime) -> Any:
    if path == "clock.now":
        return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    parts = path.split(".")
    if parts[0] == "steps":
        value: Any = context.get("nodes", {})
        for index, part in enumerate(parts[1:]):
            if index == 1 and isinstance(value, dict) and "output" in value:
                value = value["output"]
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        if isinstance(value, dict) and "output" in value and len(parts) == 2:
            return value["output"]
        return value
    value = context.get(parts[0], {})
    for part in parts[1:]:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _legacy_node_reference(value: str, context: dict[str, Any]) -> Any:
    if not value.startswith("$nodes."):
        return value
    parts = value.removeprefix("$nodes.").split(".")
    item: Any = context.get("nodes", {})
    for part in parts:
        if isinstance(item, dict):
            item = item.get(part)
        else:
            return None
    return item


def _apply_datetime_filter(value: Any, filter_name: str, amount: int) -> str:
    if not isinstance(value, str):
        raise WorkflowTemplateExpressionError("Date/time filters require an ISO timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowTemplateExpressionError("Date/time filters require an ISO timestamp string") from exc
    if filter_name == "plus_hours":
        parsed = parsed + timedelta(hours=amount)
    elif filter_name == "plus_days":
        parsed = parsed + timedelta(days=amount)
    else:
        raise WorkflowTemplateExpressionError(f"Unsupported Workflow template filter: {filter_name}")
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
