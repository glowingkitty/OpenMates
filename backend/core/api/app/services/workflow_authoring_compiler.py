"""Compile a compact, registry-scoped authoring plan into a Workflow V2 graph.

Gemini chooses semantic steps and values. This module owns graph wiring, reference
syntax, selected capability enforcement, and final runtime validation. The plan
contains ordered steps; a Check's yes/no/unsure arrays are branch-local steps.
Steps following a Check become its default continuation, which the runner executes
after the selected branch completes. No model-authored graph edges are accepted.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import is_dataclass, replace
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_identity_service import (
    WORKFLOW_ALLOWED_ICONS, normalize_workflow_identity,
)
from backend.core.api.app.services.workflow_models import (
    WorkflowEdge, WorkflowGraph, WorkflowNode, WorkflowNodeType,
    _validate_builder_execution_inputs, validate_workflow_composition_refs,
    validate_workflow_readiness,
)


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)*$")
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DATES = ("today", "today_end", "tomorrow", "tomorrow_end", "next_seven_days_start",
          "next_seven_days_end", "next_week_start", "next_week_end")
_MAX_STEPS = 40
_MAX_PLAN_BYTES = 64 * 1024


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": required if required is not None else list(properties)}


def _ref_schema() -> dict[str, Any]:
    return _object({"step": {"type": "string"}, "field": {"type": "string"}})


def _reference_schema() -> dict[str, Any]:
    return _object({"ref": {"anyOf": [_ref_schema(), _object({"loop": {"type": "string"}, "field": {"type": "string"}}),
                                          _object({"trigger": {"type": "string"}})]}})


def _date_schema() -> dict[str, Any]:
    return _object({"$date": {"type": "string", "enum": list(_DATES)},
                    "format": {"type": "string", "enum": ["date", "datetime"]}}, ["$date"])


def _input_schema(schema: dict[str, Any], *, depth: int = 0, allow_ref: bool = True,
                  field_name: str | None = None) -> dict[str, Any]:
    """Project a selected app contract into Gemini's bounded JSON Schema subset."""
    if depth > 8:
        raise ValueError("Selected capability input schema is too deep")
    kind = schema.get("type", "string")
    if isinstance(kind, list):
        kinds = [item for item in kind if item != "null"]
        kind = kinds[0] if len(kinds) == 1 else "string"
    if kind == "object":
        props = {key: _input_schema(value, depth=depth + 1, field_name=key)
                 for key, value in (schema.get("properties") or {}).items()
                 if isinstance(value, dict)}
        literal = _object(props, list(schema.get("required") or []))
    elif kind == "array":
        literal = {"type": "array", "items": _input_schema(schema.get("items") or {"type": "string"}, depth=depth + 1)}
    else:
        literal = {"type": kind}
        if isinstance(schema.get("enum"), list):
            literal["enum"] = schema["enum"]
        if isinstance(schema.get("description"), str):
            literal["description"] = schema["description"][:180]
    alternatives = [literal]
    if allow_ref:
        alternatives.append(_reference_schema())
    # App contracts often describe an ISO date in prose without a JSON Schema
    # format (for example nested event start_date/end_date). Runtime markers
    # are valid for those date-named fields and resolve before dispatch.
    date_named = field_name == "date" or isinstance(field_name, str) and field_name.endswith(
        ("_date", "_datetime", "_timestamp"))
    if kind == "string" and (schema.get("format") in {"date", "date-time", "datetime"} or date_named):
        alternatives.append(_date_schema())
    return {"anyOf": alternatives} if len(alternatives) > 1 else literal


def build_authoring_schema(selection: WorkflowPreselection) -> dict[str, Any]:
    """Return a compact JSON Schema scoped to Jev's selected capabilities.

    The schema retains deterministic draft/clarify actions used by upstream
    routing; Gemini's flat transport emits only actionable create/update plans.
    Steps are bounded to three Check levels here and again during compilation.
    """
    ref = _reference_schema()
    segment = {"anyOf": [_object({"text": {"type": "string"}}), ref]}
    segments = {"type": "array", "items": segment}
    scalar = {"anyOf": [{"type": ["string", "number", "boolean", "null"]}, ref]}
    comparison = _object({"op": {"type": "string", "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "starts_with", "exists"]},
                          "left": scalar, "right": scalar}, ["op", "left"])
    predicate = {"anyOf": [comparison, _object({"op": {"type": "string", "enum": ["and", "or"]},
                                                "conditions": {"type": "array", "items": comparison}})]}
    block = _object({"id": {"type": "string"}, "source": _ref_schema(), "label": {"type": "string"},
                     "only_new_results": {"type": "boolean"},
                     "include_if": {"anyOf": [{"type": "boolean"}, ref]}}, ["id", "source"])
    common = {"kind": {"type": "string"}, "id": {"type": "string"}}
    definitions: dict[str, Any] = {}
    app_variants = []
    for index, capability in enumerate(selection.capabilities):
        if capability.id == "ai.ask":
            continue
        name = f"app_{index}"
        definitions[name] = _object({**common, "kind": {"type": "string", "enum": ["app"]},
                                     "capability": {"type": "string", "enum": [capability.id]},
                                     "input": _input_schema(capability.metadata["input_schema"], allow_ref=False)},
                                    ["kind", "id", "capability", "input"])
        app_variants.append({"$ref": f"#/$defs/{name}"})

    if any(cap.id == "ai.ask" for cap in selection.capabilities):
        definitions["ask_ai"] = _object({**common, "kind": {"type": "string", "enum": ["ask_ai"]},
                                         "prompt": segments})
    definitions["reuse_app"] = _object({"kind": {"type": "string", "enum": ["app"]},
                                          "id": {"type": "string"}}, ["kind", "id"])
    definitions["reuse_ask_ai"] = _object({"kind": {"type": "string", "enum": ["ask_ai"]},
                                             "id": {"type": "string"}}, ["kind", "id"])
    definitions["send_full"] = _object({**common, "kind": {"type": "string", "enum": ["send"]},
                                         "title": {"type": "string"}, "message": segments,
                                         "blocks": {"type": "array", "items": block}},
                                        ["kind", "id", "title", "message"])
    definitions["reuse_send"] = _object({"kind": {"type": "string", "enum": ["send"]},
                                           "id": {"type": "string"}}, ["kind", "id"])
    definitions["end"] = _object({**common, "kind": {"type": "string", "enum": ["end"]}})
    base_variants = [*app_variants, {"$ref": "#/$defs/reuse_app"}, {"$ref": "#/$defs/reuse_ask_ai"}]
    if "ask_ai" in definitions:
        base_variants.append({"$ref": "#/$defs/ask_ai"})
    base_variants.extend([{"$ref": "#/$defs/send_full"}, {"$ref": "#/$defs/reuse_send"},
                          {"$ref": "#/$defs/end"}])
    definitions["step_0"] = {"anyOf": base_variants}
    for depth in range(1, 4):
        children = {"type": "array", "items": {"$ref": f"#/$defs/step_{depth - 1}"}}
        option = _object({"id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
                          "label": {"type": "string"}, "description": {"type": "string"}}, ["id", "label"])
        option_branch = _object({"option_id": {"type": "string"}, "steps": children}, ["option_id", "steps"])
        check_name = f"check_{depth}"
        definitions[check_name] = _object({**common, "kind": {"type": "string", "enum": ["check"]},
                                           "mode": {"type": "string", "enum": ["exact", "ai"]},
                                           "predicate": predicate, "question": segments,
                                           "selected_inputs": {"type": "array", "items": _reference_schema()["properties"]["ref"]},
                                           "result_type": {"type": "string", "enum": ["boolean", "options"]},
                                           "selection_mode": {"type": "string", "enum": ["single", "multiple"]},
                                           "options": {"type": "array", "items": option, "minItems": 2, "maxItems": 10},
                                           "option_branches": {"type": "array", "items": option_branch},
                                           "no_match": children,
                                           "yes": children, "no": children, "unsure": children},
                                          ["kind", "id", "mode", "yes", "no"])
        loop_name = f"for_each_{depth}"
        definitions[loop_name] = _object({**common, "kind": {"type": "string", "enum": ["for_each"]},
                                          "items": {"anyOf": [_ref_schema(), _object({"trigger": {"type": "string"}})]}, "body": children,
                                          "max_items": {"type": "integer", "minimum": 1, "maximum": 100},
                                          "max_duration_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                                          "max_credits": {"type": "integer", "minimum": 1, "maximum": 1000},
                                          "per_item_timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600}},
                                         ["kind", "id", "items", "body"])
        definitions[f"step_{depth}"] = {"anyOf": [*base_variants, {"$ref": f"#/$defs/{check_name}"}, {"$ref": f"#/$defs/{loop_name}"}]}

    schedule = _object({"type": {"type": "string", "enum": ["daily", "weekly", "hourly", "once", "manual"]},
                        "time": {"type": "string"}, "timezone": {"type": "string"},
                        "weekdays": {"type": "array", "items": {"type": "string", "enum": list(_DAYS)}},
                        "minute": {"type": "integer"}, "at": {"type": "string"}}, ["type"])
    result = _object({"operation": {"type": "string", "enum": ["create", "update", "draft", "clarify"]},
                    "workflow_id": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "icon": {"anyOf": [{"type": "string", "enum": sorted(WORKFLOW_ALLOWED_ICONS)},
                                       {"type": "null"}]},
                    "schedule": schedule,
                    "steps": {"type": "array", "items": {"$ref": "#/$defs/step_3"}},
                    "remove_step_ids": {"type": "array", "items": {"type": "string"}},
                    "message": {"type": ["string", "null"]}}, ["operation"])
    result["$defs"] = definitions
    return result


def _reference(value: Any, known: set[str], label: str) -> str:
    if isinstance(value, dict) and set(value) == {"trigger"}:
        field = value["trigger"]
        if not isinstance(field, str) or not _FIELD.fullmatch(field):
            raise ValueError(f"{label}: trigger reference must name a declared input field")
        return f"trigger.{field}"
    if isinstance(value, dict) and set(value) == {"loop", "field"}:
        loop, field = value["loop"], value["field"]
        if not isinstance(loop, str) or loop not in known or not isinstance(field, str) or not (field == "index" or field == "item" or field.startswith("item.") and _FIELD.fullmatch(field[5:])):
            raise ValueError(f"{label}: item reference must name an earlier For each and a declared item field")
        return f"$items.{loop}.{field}"
    if not isinstance(value, dict) or set(value) != {"step", "field"}:
        raise ValueError(f"{label}: expected a typed step/field reference")
    step, field = value["step"], value["field"]
    if not isinstance(step, str) or step not in known or not isinstance(field, str) or not _FIELD.fullmatch(field):
        raise ValueError(f"{label}: reference must name an earlier step and declared output field")
    if field.startswith("output."):
        field = field[len("output."):]
    if field == "output":
        field = ""
    return f"$nodes.{step}.output" + (f".{field}" if field else "")


def _value(value: Any, known: set[str], label: str, *, app_input: bool = False) -> Any:
    if isinstance(value, dict):
        if set(value) == {"ref"}:
            return _reference(value["ref"], known, label)
        if "$date" in value:
            if set(value) - {"$date", "format"} or value["$date"] not in _DATES or value.get("format", "datetime") not in {"date", "datetime"}:
                raise ValueError(f"{label}: invalid runtime date marker")
            return value
        return {key: _value(child, known, f"{label}.{key}", app_input=app_input)
                for key, child in value.items() if child is not None}
    if isinstance(value, list):
        return [_value(child, known, label, app_input=app_input) for child in value]
    if isinstance(value, str) and app_input and "$date" in value:
        stripped = value.lstrip()
        if stripped.startswith(("{", "$date")):
            raise ValueError(f"{label}: runtime date markers must be structured objects")
    if isinstance(value, str) and ("$nodes." in value or "{{" in value or "}}" in value):
        raise ValueError(f"{label}: use a typed reference instead of model-written template syntax")
    return value


def _text(segments: Any, known: set[str], label: str) -> str:
    if not isinstance(segments, list) or len(segments) > 48:
        raise ValueError(f"{label}: expected at most 48 structured text segments")
    result = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError(f"{label}: invalid text segment")
        if set(segment) == {"text"} and isinstance(segment["text"], str):
            result.append(_value(segment["text"], known, label))
        elif set(segment) == {"ref"}:
            reference = _reference(segment["ref"], known, label)
            result.append("{{" + (reference[1:] if reference.startswith("$items.") else " " + reference + " ") + "}}")
        else:
            raise ValueError(f"{label}: text segments must contain text or a typed reference")
    return "".join(result)


def _predicate(value: Any, known: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Exact Check requires a predicate")
    op = value.get("op")
    if op in {"and", "or"}:
        children = value.get("conditions")
        if not isinstance(children, list) or not 1 <= len(children) <= 8:
            raise ValueError("Compound Check requires one to eight conditions")
        return {"op": op, "conditions": [_predicate(child, known) for child in children]}
    if op not in {"eq", "neq", "gt", "gte", "lt", "lte", "contains", "starts_with", "exists"} or "left" not in value:
        raise ValueError("Exact Check has an unsupported comparison")
    result = {"op": op, "left": _value(value["left"], known, "Check left operand")}
    if op != "exists":
        if "right" not in value:
            raise ValueError("Exact Check comparison requires a right operand")
        result["right"] = _value(value["right"], known, "Check right operand")
    return result


def _selected_app_schema_diagnostic(
    raw: dict[str, Any], selection: WorkflowPreselection, error: Any,
) -> tuple[str, str] | None:
    """Return a registry-field path and schema keyword, never an authored value."""
    parts = list(error.absolute_path)
    if len(parts) < 2 or parts[0] != "steps" or not isinstance(parts[1], int):
        return None
    try:
        step = raw["steps"][parts[1]]
        for part in parts[2:]:
            step = step[part]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(step, dict) or step.get("kind") != "app" or not isinstance(step.get("input"), dict):
        return None
    capability = next((cap for cap in selection.capabilities if cap.id == step.get("capability")), None)
    if capability is None:
        return None
    app_schema = capability.metadata["input_schema"]
    app_error = next(Draft202012Validator(_input_schema(app_schema, allow_ref=False)).iter_errors(step["input"]), None)
    if app_error is None:
        return None
    while app_error.context:
        # A generated app input follows the literal branch of each anyOf;
        # reference alternatives add noisy errors without useful field paths.
        literal = [child for child in app_error.context if child.schema_path and child.schema_path[0] == 0]
        app_error = (literal or app_error.context)[0]
    keyword = app_error.validator
    if keyword not in {"type", "required", "enum", "additionalProperties", "minimum", "maximum", "minItems", "maxItems"}:
        return None
    current = app_schema
    path = f"$.steps[{parts[1]}].input"
    for part in app_error.absolute_path:
        if isinstance(part, int):
            if not isinstance(current, dict) or current.get("type") != "array" or part > 999:
                return None
            current = current.get("items")
            path += f"[{part}]"
        elif isinstance(part, str):
            properties = current.get("properties") if isinstance(current, dict) else None
            if not isinstance(properties, dict) or part not in properties:
                return None
            current = properties[part]
            path += f".{part}"
        else:
            return None
    return (path, keyword) if len(path) <= 160 else None


def _selected_node_schema_diagnostic(
    raw: dict[str, Any], selection: WorkflowPreselection, error: Any, schema: dict[str, Any],
) -> tuple[str, str] | None:
    """Choose the authored node's schema branch and return only a fixed field path."""
    parts = list(error.absolute_path)
    if len(parts) < 2 or parts[0] != "steps" or not isinstance(parts[1], int) or not 0 <= parts[1] < _MAX_STEPS:
        return None
    try:
        step = raw["steps"][parts[1]]
        for part in parts[2:]:
            step = step[part]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(step, dict):
        return None
    kind = step.get("kind")
    definitions = schema["$defs"]
    if kind == "app":
        capability = step.get("capability")
        matched = next((index for index, cap in enumerate(selection.capabilities) if cap.id == capability), None)
        if matched is None:
            keyword = "required" if capability is None else "enum"
            return f"$.steps[{parts[1]}].capability", keyword
        variant = definitions.get(f"app_{matched}")
    elif kind == "ask_ai":
        variant = definitions.get("ask_ai")
    elif kind == "send":
        variant = definitions["send_full"]
    elif kind == "end":
        variant = definitions["end"]
    else:
        return None
    if variant is None:
        return None
    chosen = best_match(Draft202012Validator(variant).iter_errors(step))
    if chosen is None or chosen.validator not in {"required", "type", "enum", "anyOf", "additionalProperties"}:
        return None
    base = f"$.steps[{parts[1]}]"
    if chosen.validator == "required":
        required = chosen.validator_value
        missing = [field for field in required if field not in step] if isinstance(required, list) else []
        return (f"{base}.{missing[0]}", "required") if missing else None
    if chosen.absolute_path:
        first = next(iter(chosen.absolute_path))
        allowed = {"kind", "id", "capability", "input", "prompt", "title", "message", "blocks"}
        return (f"{base}.{first}", chosen.validator) if first in allowed else None
    return base, chosen.validator


def _compile_authoring(
    raw: dict[str, Any], selection: WorkflowPreselection, timezone: str,
    selected_workflow: dict[str, Any] | None = None,
    *, preview: bool = False,
) -> dict[str, Any]:
    """Compile a complete plan or a provisional read-only graph preview.

    ``raw`` is untrusted model output. Every generated graph passes the existing
    typed graph, readiness, and composition validators. Updates are full graph
    replacements and keep any supplied existing node IDs unchanged.
    """
    if not isinstance(raw, dict):
        raise ValueError("Authoring plan must be an object")
    try:
        size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Authoring plan must contain JSON values") from exc
    if size > _MAX_PLAN_BYTES:
        raise ValueError("Authoring plan exceeds the size limit")
    # Icon choice is cosmetic. Preserve the selected graph and all non-icon
    # fields under the strict schema; only a string outside the icon set gets
    # the same identity fallback already used by WorkflowInputService.
    if isinstance(raw.get("icon"), str) and raw["icon"] not in WORKFLOW_ALLOWED_ICONS:
        if raw.get("operation") == "create":
            raw = {**raw, "icon": normalize_workflow_identity("general_knowledge", raw["icon"]).icon}
        elif raw.get("operation") == "update":
            raw = {key: value for key, value in raw.items() if key != "icon"}
    # JSON mode does not enforce responseFormat's union schema. Validate the
    # selected capability contract here before interpreting any model field.
    # Never include raw values or validator messages in errors: they can contain
    # user content or provider output.
    schema = build_authoring_schema(selection)
    errors = Draft202012Validator(schema).iter_errors(raw)
    first_error = next(errors, None)
    if first_error is not None:
        path = first_error.json_path
        failure = ValueError(f"Authoring plan violates the selected capability schema at {path}")
        detail = (_selected_app_schema_diagnostic(raw, selection, first_error)
                  or _selected_node_schema_diagnostic(raw, selection, first_error, schema))
        if detail is not None:
            failure.validation_path, failure.validation_keyword = detail
        raise failure
    for field, limit in (("title", 200), ("description", 2_000)):
        value = raw.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError(f"Authoring {field} exceeds its allowed length")
    operation = raw.get("operation")
    if operation == "clarify":
        if preview:
            raise ValueError("Clarification has no workflow preview")
        message = raw.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Clarification requires a reason")
        return {"action": "needs_clarification", "message": message.strip()[:1000]}
    if operation == "draft":
        if preview:
            raise ValueError("Empty draft has no workflow preview")
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            raise ValueError("Empty draft requires a short title")
        return {"action": "create_empty_workflow", "title": title.strip()}
    if operation not in {"create", "update"} or operation != selection.operation:
        raise ValueError("Authoring operation does not match preselection")
    if operation == "update":
        if not selected_workflow or not selected_workflow.get("id") or raw.get("workflow_id") != selected_workflow["id"]:
            raise ValueError("Update must target the selected workflow")
    elif raw.get("workflow_id"):
        raise ValueError("Create cannot target an existing workflow")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("Browser timezone is invalid") from exc
    previous_graph = WorkflowGraph.model_validate(selected_workflow["graph"]) if operation == "update" else None
    prior_nodes_by_id = {node.id: node for node in previous_graph.nodes} if previous_graph else {}
    trigger_id = previous_graph.trigger_node_id if previous_graph and previous_graph.trigger_node_id else "trigger"
    prior_trigger = next((node for node in previous_graph.nodes if node.id == trigger_id), None) if previous_graph else None
    assumptions: list[str] = []
    schedule = raw.get("schedule")
    if schedule is None and prior_trigger is not None:
        trigger = prior_trigger.model_copy(deep=True)
        schedule_type = (trigger.config.get("schedule") or {}).get("type") if trigger.type == WorkflowNodeType.SCHEDULE_TRIGGER else "manual"
    else:
        if schedule is None:
            schedule = {"type": "weekly"}
        if not isinstance(schedule, dict):
            raise ValueError("Schedule must be an object")
        schedule_type = schedule.get("type")
        if schedule_type not in {"daily", "weekly", "hourly", "once", "manual"}:
            raise ValueError("Schedule type is unsupported")
        schedule_fields = {
            "daily": {"type", "time", "timezone"},
            "weekly": {"type", "time", "timezone", "weekdays"},
            "hourly": {"type", "minute", "timezone"},
            "once": {"type", "at", "timezone"},
            "manual": {"type"},
        }
        unsupported = sorted(set(schedule) - schedule_fields[schedule_type])
        if unsupported:
            supported = sorted(schedule_fields[schedule_type] - {"type"})
            allowed = ", ".join(supported) if supported else "only type"
            raise ValueError(f"{schedule_type} schedule supports {allowed}; unsupported fields: {', '.join(unsupported)}")
        if schedule_type == "manual":
            trigger = WorkflowNode(id=trigger_id, type=WorkflowNodeType.MANUAL_TRIGGER)
        else:
            # For a time-only edit, preserve the target's schedule zone even
            # when Gemini echoes the browser zone in its authored schedule.
            prior_zone = None
            if (operation == "update" and getattr(selection, "preserve_schedule_timezone", False)
                    and prior_trigger is not None and prior_trigger.type == WorkflowNodeType.SCHEDULE_TRIGGER):
                prior_schedule = prior_trigger.config.get("schedule") or {}
                candidate = prior_schedule.get("timezone") if isinstance(prior_schedule, dict) else None
                if isinstance(candidate, str):
                    try:
                        ZoneInfo(candidate)
                    except (ZoneInfoNotFoundError, ValueError):
                        pass
                    else:
                        prior_zone = candidate
            # A newly authored single-workflow clock follows Jev's explicit
            # choice; batch workflows retain their individual authored zones.
            selected_zone = getattr(selection, "schedule_timezone", None)
            workflow_count = getattr(selection, "workflow_count", None)
            if isinstance(workflow_count, int) and workflow_count > 1:
                selected_zone = None  # One global choice cannot encode distinct batch timezones.
            zone = prior_zone or selected_zone or schedule.get("timezone") or timezone
            try:
                ZoneInfo(zone)
            except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
                raise ValueError("Schedule timezone is invalid") from exc
            config_schedule: dict[str, Any] = {"type": schedule_type, "timezone": zone}
            if schedule_type in {"daily", "weekly"}:
                time = schedule.get("time")
                if time is None:
                    time = "09:00"
                    assumptions.append("No time was specified, so this workflow is scheduled for 09:00.")
                if not isinstance(time, str) or not _TIME.fullmatch(time):
                    raise ValueError("Schedule time must be HH:MM")
                config_schedule["time"] = time
                if schedule_type == "weekly":
                    weekdays = schedule.get("weekdays")
                    if weekdays is None:
                        weekdays = ["monday"]
                        assumptions.append("No weekly day was specified, so this workflow is scheduled for Monday.")
                    if not isinstance(weekdays, list) or not weekdays or any(day not in _DAYS for day in weekdays) or len(set(weekdays)) != len(weekdays):
                        raise ValueError("Weekly schedule needs unique weekdays")
                    config_schedule["weekdays"] = weekdays
            elif schedule_type == "hourly":
                minute = schedule.get("minute")
                if minute is None:
                    minute = 0
                    assumptions.append("No hourly minute was specified, so this workflow runs at minute 00.")
                if isinstance(minute, bool) or not isinstance(minute, int) or not 0 <= minute <= 59:
                    raise ValueError("Hourly schedule minute must be between 0 and 59")
                config_schedule["minute"] = minute
            else:
                at = schedule.get("at")
                if not isinstance(at, str) or not at.strip():
                    raise ValueError("One-time schedule requires an ISO timestamp")
                config_schedule["at"] = at
            trigger = WorkflowNode(id=trigger_id, type=WorkflowNodeType.SCHEDULE_TRIGGER,
                                   config={"schedule": config_schedule})
    steps = raw.get("steps")
    preserve_prior_steps = operation == "update" and steps is None
    if steps is None:
        steps = []
    if not isinstance(steps, list) or (not steps and not preview and not preserve_prior_steps):
        raise ValueError("Authoring plan requires steps")
    removed_ids = raw.get("remove_step_ids") or []
    if removed_ids and operation != "update":
        raise ValueError("Only an update can remove existing steps")
    if len(removed_ids) != len(set(removed_ids)):
        raise ValueError("Removed step IDs must be unique")
    if preserve_prior_steps and removed_ids:
        raise ValueError("Removing steps requires a complete replacement step list")
    selected_ids = {cap.id for cap in selection.capabilities}
    nodes = [trigger]
    edges: list[WorkflowEdge] = []
    used_ids = {trigger_id}
    total = 0

    def edge(source: str, target: str, branch: str | None = None) -> None:
        edges.append(WorkflowEdge(**{"from": source, "to": target, "branch": branch}))

    def compile_sequence(items: list[Any], incoming: tuple[str, str | None] | None,
                         depth: int, known: set[str], continuation_pending: bool = False) -> None:
        nonlocal total
        if depth > 4 or not isinstance(items, list):
            raise ValueError("Authoring Check nesting is too deep")
        previous = incoming
        for position, item in enumerate(items):
            total += 1
            if total > _MAX_STEPS or not isinstance(item, dict):
                raise ValueError("Authoring plan exceeds its step limit")
            kind, node_id = item.get("kind"), item.get("id")
            if not isinstance(node_id, str) or not _ID.fullmatch(node_id) or node_id in used_ids:
                raise ValueError("Step IDs must be unique stable identifiers")
            used_ids.add(node_id)
            if previous is not None:
                edge(previous[0], node_id, previous[1])
            if kind == "app":
                if set(item) == {"kind", "id"}:
                    prior_app = prior_nodes_by_id.get(node_id)
                    if operation != "update" or prior_app is None or prior_app.type != WorkflowNodeType.APP_SKILL_ACTION:
                        raise ValueError("App reuse requires an unchanged existing app ID")
                    capability = f"{prior_app.config.get('app_id')}.{prior_app.config.get('skill_id')}"
                    if capability == "ai.ask" or not any(
                            cap.id == capability and cap.enabled for cap in selection.capabilities):
                        raise ValueError("App reuse requires its selected available capability")
                    node = prior_app.model_copy(deep=True)
                else:
                    capability = item.get("capability")
                    if capability not in selected_ids or capability == "ai.ask":
                        raise ValueError("App step must use a selected capability")
                    authored = item.get("input")
                    if not isinstance(authored, dict):
                        raise ValueError("App input must be an object")
                    app_id, skill_id = capability.split(".", 1)
                    node = WorkflowNode(id=node_id, type=WorkflowNodeType.APP_SKILL_ACTION,
                                        config={"app_id": app_id, "skill_id": skill_id,
                                                "input": _value(authored, known, f"Step {node_id} input", app_input=True)})
            elif kind == "ask_ai":
                if not any(cap.id == "ai.ask" and cap.enabled for cap in selection.capabilities):
                    raise ValueError("Ask AI capability was not selected or available")
                if set(item) == {"kind", "id"}:
                    prior_ask = prior_nodes_by_id.get(node_id)
                    if (operation != "update" or prior_ask is None
                            or prior_ask.type != WorkflowNodeType.APP_SKILL_ACTION
                            or prior_ask.config.get("app_id") != "ai" or prior_ask.config.get("skill_id") != "ask"):
                        raise ValueError("Ask AI reuse requires an unchanged existing Ask AI ID")
                    node = prior_ask.model_copy(deep=True)
                else:
                    prompt = _text(item.get("prompt"), known, f"Step {node_id} prompt")
                    node = WorkflowNode(id=node_id, type=WorkflowNodeType.APP_SKILL_ACTION,
                                        config={"app_id": "ai", "skill_id": "ask", "input": {"prompt": prompt}})
            elif kind == "check":
                mode = item.get("mode")
                if mode not in {"exact", "ai"}:
                    raise ValueError("Check mode is unsupported")
                if mode == "exact":
                    config = {"mode": "exact", "predicate": _predicate(item.get("predicate"), known)}
                else:
                    inputs = item.get("selected_inputs")
                    if not isinstance(inputs, list):
                        raise ValueError("AI Check requires selected inputs")
                    selected_inputs = [_reference(ref, known, f"Step {node_id} selected input") for ref in inputs]
                    config = {"mode": "ai", "question": _text(item.get("question", []), known, f"Step {node_id} question"),
                              "selected_inputs": selected_inputs}
                    if item.get("result_type") == "options":
                        config.update(result_type="options", selection_mode=item.get("selection_mode"), options=item.get("options"))
                node = WorkflowNode(id=node_id, type=WorkflowNodeType.CHECK, config=config)
            elif kind == "for_each":
                authored_items = item.get("items")
                if isinstance(authored_items, dict) and set(authored_items) == {"trigger"}:
                    items_ref = _reference(authored_items, known, f"Step {node_id} items")
                elif (isinstance(authored_items, dict) and set(authored_items) == {"step", "field"}
                        and authored_items["step"] == trigger_id and isinstance(authored_items["field"], str)
                        and _FIELD.fullmatch(authored_items["field"])):
                    items_ref = f"trigger.{authored_items['field']}"
                else:
                    items_ref = _reference(authored_items, known, f"Step {node_id} items")
                if not items_ref.startswith(("$nodes.", "trigger.")):
                    raise ValueError("For each items must reference an earlier list output")
                config = {"items": items_ref}
                for key in ("max_items", "max_duration_seconds", "max_credits", "per_item_timeout_seconds"):
                    if key in item:
                        config[key] = item[key]
                node = WorkflowNode(id=node_id, type=WorkflowNodeType.FOR_EACH, config=config)
            elif kind == "send":
                prior_send = prior_nodes_by_id.get(node_id)
                if "message" not in item:
                    if (operation != "update" or set(item) != {"kind", "id"} or prior_send is None
                            or prior_send.type != WorkflowNodeType.SEND_CHAT_MESSAGE):
                        raise ValueError("Send requires authored message or an unchanged existing Send ID")
                    node = prior_send.model_copy(deep=True)
                else:
                    message = _text(item["message"], known, f"Step {node_id} message")
                    prior_blocks = {block["id"]: block for block in (prior_send.config.get("blocks") or [])
                                    if isinstance(block, dict) and isinstance(block.get("id"), str)} if prior_send else {}
                    blocks = []
                    for block in item.get("blocks") or []:
                        if not isinstance(block, dict) or not isinstance(block.get("id"), str):
                            raise ValueError("Message block requires an ID")
                        compiled = {"id": block["id"], "source": _reference(block.get("source"), known, f"Step {node_id} block")}
                        if "label" in block:
                            compiled["label"] = block["label"]
                        elif isinstance(prior_blocks.get(block["id"], {}).get("label"), str):
                            compiled["label"] = prior_blocks[block["id"]]["label"]
                        if "only_new_results" in block:
                            compiled["only_new_results"] = block["only_new_results"]
                        if "include_if" in block:
                            value = block["include_if"]
                            compiled["include_if"] = _reference(value["ref"], known, f"Step {node_id} block condition") if isinstance(value, dict) and set(value) == {"ref"} else value
                        blocks.append(compiled)
                    node = WorkflowNode(id=node_id, type=WorkflowNodeType.SEND_CHAT_MESSAGE,
                                        config={"title": item.get("title") or raw.get("title") or "Workflow update",
                                                "message": message, "blocks": blocks})
            elif kind == "end":
                if continuation_pending:
                    raise ValueError("End inside a Check branch cannot stop a queued continuation")
                node = WorkflowNode(id=node_id, type=WorkflowNodeType.END)
            else:
                raise ValueError("Unsupported authoring step kind")
            prior_same = prior_nodes_by_id.get(node_id)
            if operation == "update" and prior_same is not None and prior_same.type == node.type:
                node.ui = deepcopy(prior_same.ui)
            nodes.append(node)
            known.add(node_id)
            if kind == "check":
                branches = ("yes", "no", "unsure") if node.config.get("result_type") != "options" else ("no_match", "unsure")
                if node.config.get("result_type") == "options":
                    seen_options: set[str] = set()
                    for branch_item in item.get("option_branches") or []:
                        option_id = branch_item.get("option_id") if isinstance(branch_item, dict) else None
                        if option_id not in {option["id"] for option in node.config["options"]} or option_id in seen_options:
                            raise ValueError("Option branch must name one declared option")
                        seen_options.add(option_id)
                        compile_sequence(branch_item.get("steps") or [], (node_id, f"option:{option_id}"), depth + 1, known.copy(),
                                         continuation_pending or position < len(items) - 1)
                    if item.get("yes") or item.get("no"):
                        raise ValueError("Option Check cannot use Boolean branches")
                for branch in branches:
                    branch_items = item.get(branch) or []
                    if not isinstance(branch_items, list):
                        raise ValueError("Check branches must be step lists")
                    if branch_items:
                        compile_sequence(branch_items, (node_id, branch), depth + 1, known.copy(),
                                         continuation_pending or position < len(items) - 1)
                    elif branch in {"yes", "no"} and position == len(items) - 1:
                        # A terminal empty branch has no continuation to fall
                        # through to, so give it an explicit safe endpoint.
                        end_id = f"{node_id}_{branch}_end"
                        if end_id in used_ids:
                            raise ValueError("Generated end ID collides with a step ID")
                        used_ids.add(end_id)
                        nodes.append(WorkflowNode(id=end_id, type=WorkflowNodeType.END))
                        edge(node_id, end_id, branch)
                previous = (node_id, "default") if position < len(items) - 1 else None
            elif kind == "for_each":
                body = item.get("body")
                if not isinstance(body, list):
                    raise ValueError("For each body must be a step list")
                if any(child.get("kind") == "for_each" for child in body if isinstance(child, dict)):
                    raise ValueError("Nested For each steps are unavailable")
                if body:
                    compile_sequence(body, (node_id, "body"), depth + 1, known.copy())
                previous = (node_id, None)
            elif kind == "end":
                if position != len(items) - 1:
                    raise ValueError("End must finish its sequence")
                previous = None
            else:
                previous = (node_id, None)

    if preserve_prior_steps:
        if previous_graph.version != 2 or prior_trigger is None:
            raise ValueError("Updating an existing graph without steps requires a V2 trigger")
        nodes.extend(node.model_copy(deep=True) for node in previous_graph.nodes if node.id != trigger_id)
        edges.extend(edge.model_copy(deep=True) for edge in previous_graph.edges)
    else:
        compile_sequence(steps, (trigger_id, None), 0, {trigger_id})
    if previous_graph and not preserve_prior_steps and not preview:
        old_ids = {node.id for node in previous_graph.nodes if node.id != trigger_id}
        new_ids = {node.id for node in nodes if node.id != trigger_id}
        incoming_edges: dict[str, list[WorkflowEdge]] = {}
        for prior_edge in previous_graph.edges:
            incoming_edges.setdefault(prior_edge.to_node, []).append(prior_edge)
        generated_ends = {node.id for node in previous_graph.nodes
                          if node.type == WorkflowNodeType.END
                          and len(incoming_edges.get(node.id, [])) == 1
                          and (edge := incoming_edges[node.id][0]) is not None
                          and node.id == f"{edge.from_node}_{edge.branch}_end"
                          and edge.branch in {"yes", "no"}}
        missing = old_ids - new_ids - generated_ends
        if set(removed_ids) != missing:
            raise ValueError("Update must preserve existing step IDs or explicitly list removed steps")
    graph = WorkflowGraph(version=2, trigger_node_id=trigger_id, nodes=nodes, edges=edges)
    if preview:
        _validate_builder_execution_inputs(graph)
    else:
        validate_workflow_readiness(graph, require_schedule=schedule_type != "manual")
    validate_workflow_composition_refs(graph, previous_graph, allow_data_dependencies=True)
    graph_data = graph.model_dump(mode="json", by_alias=True)
    if preview:
        return {"title": raw.get("title"), "description": raw.get("description"),
                "icon": raw.get("icon") if raw.get("icon") is not None else
                (selected_workflow or {}).get("icon"), "graph": graph_data,
                "assumptions": assumptions, "complete": False,
                **({"workflow_id": selected_workflow["id"]} if operation == "update" else {})}
    if operation == "update":
        result = {"action": "update_workflow", "workflow_id": selected_workflow["id"],
                  "graph": graph_data, "assumptions": assumptions}
        record_version = selected_workflow.get("version")
        if isinstance(record_version, int) and not isinstance(record_version, bool) and record_version >= 1:
            result["expected_record_version"] = record_version
        for key in ("title", "description", "icon"):
            if raw.get(key) is not None:
                result[key] = raw[key]
        return result
    title = raw.get("title")
    description = raw.get("description")
    if not isinstance(title, str) or not title.strip() or not isinstance(description, str) or not description.strip():
        raise ValueError("Create requires a title and description")
    if raw.get("icon") not in WORKFLOW_ALLOWED_ICONS:
        raise ValueError("Create requires a supported icon")
    identity = normalize_workflow_identity("general_knowledge", raw["icon"])
    return {"action": "create_workflow", "title": title.strip()[:200], "description": description.strip()[:2000],
            "category": identity.category, "icon": identity.icon, "graph": graph_data,
            "enabled": False, "assumptions": assumptions}


def compile_authoring_plan(
    raw: dict[str, Any], selection: WorkflowPreselection, timezone: str,
    selected_workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a validated action envelope for one complete compact workflow."""
    return _compile_authoring(raw, selection, timezone, selected_workflow)


def compile_authoring_preview(
    raw_prefix: dict[str, Any], selection: WorkflowPreselection, timezone: str,
    selected_workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a read-only V2 preview from completed header and step components.

    The preview has no WorkflowInputService action or enable flag. It validates
    completed nodes and references, but need not contain a final delivery.
    """
    return _compile_authoring(raw_prefix, selection, timezone, selected_workflow, preview=True)


_FLAT_JSON_FIELDS = {
    "input_json": "input", "predicate_json": "predicate", "question_json": "question",
    "selected_inputs_json": "selected_inputs", "prompt_json": "prompt",
    "message_json": "message", "blocks_json": "blocks", "options_json": "options",
    "items_json": "items", "body_json": "body",
}
_FLAT_NODE_FIELDS = {"kind", "id", "parent_check_id", "parent_loop_id", "branch", "capability", "mode", "title",
                     "result_type", "selection_mode", "max_items", "max_duration_seconds", "max_credits", "per_item_timeout_seconds",
                     *_FLAT_JSON_FIELDS}


_HEADER_SCHEMA_PATHS = frozenset({
    "$.schedule", "$.schedule.type", "$.schedule.time", "$.schedule.timezone",
    "$.schedule.weekdays", "$.schedule.minute", "$.schedule.at",
    "$.title", "$.description", "$.icon", "$.workflow_id",
})


def authoring_validation_path(error: ValueError, phase: str) -> str | None:
    """Expose only known structural header paths, never authored field values."""
    if phase != "header":
        return None
    message = str(error)
    prefix = "Authoring plan violates the selected capability schema at "
    if message.startswith(prefix):
        path = message.removeprefix(prefix)
        return path if path in _HEADER_SCHEMA_PATHS else None
    lower = message.lower()
    if lower.startswith("schedule timezone") or lower == "browser timezone is invalid":
        return "$.schedule.timezone"
    if lower.startswith("schedule time"):
        return "$.schedule.time"
    if lower.startswith("weekly schedule needs"):
        return "$.schedule.weekdays"
    if lower.startswith("hourly schedule minute"):
        return "$.schedule.minute"
    if lower.startswith("one-time schedule requires"):
        return "$.schedule.at"
    if lower.startswith(("schedule must", "schedule type")) or re.match(
            r"^(daily|weekly|hourly|once|manual) schedule supports ", lower):
        return "$.schedule"
    return None


def authoring_validation_code(error: ValueError, phase: str) -> str:
    """Classify an authored prefix with fixed privacy-safe failure codes."""
    message = str(error).lower()
    if phase == "header":
        path = authoring_validation_path(error, phase)
        if path == "$.schedule":
            return "header_schedule_field_set" if "schedule supports " in message else "header_schedule_schema"
        if path in {"$.schedule.time", "$.schedule.minute", "$.schedule.at"}:
            return "header_schedule_time"
        if path == "$.schedule.timezone":
            return "header_schedule_timezone"
        if path == "$.schedule.weekdays":
            return "header_schedule_weekdays"
        if path == "$.schedule.type":
            return "header_schedule_schema"
        if "icon" in message or "selected capability schema at $.icon" in message:
            return "header_icon"
        if ("title" in message or "description" in message or
                "selected capability schema at $.title" in message or
                "selected capability schema at $.description" in message):
            return "header_metadata"
        if "selected workflow" in message or "target" in message:
            return "header_target"
        if "selected capability schema" in message:
            return "header_selected_schema"
        return "header_validation"
    if "json field" in message or "duplicate property" in message:
        return "node_json"
    if "reference" in message or "upstream" in message or "branch-local" in message:
        return "node_reference"
    if "selected capability schema" in message or "selected capability" in message:
        return "node_selected_schema"
    if "node id" in message or "step ids" in message:
        return "node_id"
    return "node_validation"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate property in authored node JSON")
        result[key] = value
    return result


def _selected_target(selected_workflow: dict[str, Any] | None, workflow_id: Any) -> dict[str, Any] | None:
    if not isinstance(selected_workflow, dict):
        return None
    if selected_workflow.get("id") == workflow_id:
        return selected_workflow
    candidates = selected_workflow.get("workflows") or selected_workflow.get("selected_workflows") or []
    if isinstance(candidates, list):
        return next((item for item in candidates if isinstance(item, dict) and item.get("id") == workflow_id), None)
    return None


class FlatAuthoringAccumulator:
    """Accept complete flat records only after the current prefix compiles safely.

    Check children are separate records with ``parent_check_id`` and ``branch``.
    Every accepted prefix has a read-only V2 preview; rejected records leave the
    accepted state intact. The final compact tree retains existing compiler APIs.
    """

    def __init__(self, selection: WorkflowPreselection, timezone: str,
                 selected_workflow: dict[str, Any] | None = None) -> None:
        self.selection = selection
        self.timezone = timezone
        self.selected_workflow = selected_workflow
        self.header: dict[str, Any] | None = None
        self.records: list[dict[str, Any]] = []
        self.preview: dict[str, Any] | None = None

    def _context(self, operation: str) -> tuple[WorkflowPreselection, dict[str, Any] | None]:
        if operation not in {"create", "update"}:
            raise ValueError("Flat authoring operation is invalid")
        selection = (replace(self.selection, operation=operation) if is_dataclass(self.selection)
                     else SimpleNamespace(**{**vars(self.selection), "operation": operation}))
        target = _selected_target(self.selected_workflow, self.header.get("workflow_id") if self.header else None)
        return selection, target

    def accept_header(self, header: dict[str, Any]) -> dict[str, Any] | None:
        if self.header is not None or not isinstance(header, dict) or "steps" in header or "nodes" in header:
            raise ValueError("Flat authoring header is invalid")
        if any(key not in {"operation", "workflow_id", "title", "description", "icon", "schedule",
                               "remove_step_ids", "message"} for key in header):
            raise ValueError("Flat authoring header has an unknown property")
        candidate = dict(header) if header.get("operation") == "update" else {**header, "steps": []}
        self.header = dict(header)
        try:
            selection, target = self._context(str(header.get("operation")))
            preview = compile_authoring_preview(candidate, selection, self.timezone, target)
        except (ValueError, TypeError):
            self.header = None
            raise
        self.preview = preview
        if header.get("operation") in {"create", "update"}:
            try:
                self.compile_partial()
            except ValueError:
                self.header = None
                self.preview = None
                raise
        return preview

    def _compact(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        if self.header is None:
            raise ValueError("Flat authoring header is missing")
        steps: list[dict[str, Any]] = []
        checks: dict[str, dict[str, Any]] = {}
        loops: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict) or not {"kind", "id"} <= set(record) or set(record) - _FLAT_NODE_FIELDS:
                raise ValueError("Flat authoring node shape is invalid")
            node_id = record["id"]
            if not isinstance(node_id, str) or not _ID.fullmatch(node_id) or node_id in seen:
                raise ValueError("Flat authoring node ID is invalid or repeated")
            seen.add(node_id)
            parent = record.get("parent_check_id")
            parent_loop = record.get("parent_loop_id")
            branch = record.get("branch")
            if parent is not None and parent_loop is not None:
                raise ValueError("Authoring node cannot have two control parents")
            if parent_loop is not None:
                if not isinstance(parent_loop, str) or parent_loop not in loops or branch not in {None, "body"}:
                    raise ValueError("Body node must name an earlier For each")
                destination = loops[parent_loop]["body"]
            elif parent is None:
                if branch not in (None, "default"):
                    raise ValueError("Root authoring node cannot use a Check branch")
                destination = steps
            else:
                if not isinstance(parent, str) or parent not in checks or not isinstance(branch, str):
                    raise ValueError("Branch node must name an earlier Check and branch")
                if branch.startswith("option:"):
                    option_id = branch[7:]
                    choices = checks[parent].get("option_branches") or []
                    chosen = next((choice for choice in choices if choice["option_id"] == option_id), None)
                    if chosen is None:
                        raise ValueError("Option branch must name a declared Check option")
                    destination = chosen["steps"]
                elif branch in {"yes", "no", "unsure", "no_match"}:
                    destination = checks[parent].setdefault(branch, [])
                else:
                    raise ValueError("Branch node must name a declared Check branch")
            item = {key: value for key, value in record.items()
                    if key in {"kind", "id", "capability", "mode", "title", "result_type", "selection_mode",
                               "max_items", "max_duration_seconds", "max_credits", "per_item_timeout_seconds"}}
            for transport_key, compact_key in _FLAT_JSON_FIELDS.items():
                if transport_key in record:
                    encoded = record[transport_key]
                    if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > _MAX_PLAN_BYTES:
                        raise ValueError("Flat authoring JSON field is invalid")
                    try:
                        item[compact_key] = json.loads(encoded, object_pairs_hook=_unique_json_object)
                    except (ValueError, RecursionError) as exc:
                        raise ValueError("Flat authoring JSON field is malformed") from exc
            if item["kind"] == "check":
                item.update({"yes": [], "no": [], "unsure": []})
                if item.get("result_type") == "options":
                    item["option_branches"] = [{"option_id": option["id"], "steps": []}
                                               for option in item.get("options") or []]
                checks[node_id] = item
            elif item["kind"] == "for_each":
                item.setdefault("body", [])
                loops[node_id] = item
            destination.append(item)
        return {**self.header, **({"steps": steps} if records or self.header.get("operation") != "update" else {})}

    def accept_node(self, record: dict[str, Any]) -> dict[str, Any]:
        if self.header is None or self.header.get("operation") not in {"create", "update"}:
            raise ValueError("Flat authoring nodes require a workflow header")
        if len(self.records) >= _MAX_STEPS:
            raise ValueError("Flat authoring plan exceeds its node limit")
        candidate = self._compact([*self.records, record])
        selection, target = self._context(self.header["operation"])
        preview = compile_authoring_preview(candidate, selection, self.timezone, target)
        old_records, old_preview = self.records, self.preview
        self.records = [*self.records, record]
        self.preview = preview
        if self.header["operation"] == "update":
            try:
                merged = self.compile_partial()
            except ValueError:
                self.records = old_records
                self.preview = old_preview
                raise
            return {**preview, "graph": merged["graph"]}
        return preview

    def snapshot(self) -> dict[str, Any] | None:
        return self._compact(self.records) if self.header is not None else None

    def flat_snapshot(self) -> dict[str, Any] | None:
        """Return accepted transport records for a single bounded continuation."""
        return {"header": dict(self.header), "nodes": [dict(node) for node in self.records]} if self.header else None

    def compile_partial(self) -> dict[str, Any]:
        """Return a disabled action only when every accepted edit can be retained.

        New update nodes splice into the original edge slot named by their
        accepted predecessor and branch. The displaced old target follows the
        inserted node through its default edge, preserving unrelated old steps.
        A splice that cannot preserve the old target is rejected before emit.
        """
        plan = self.snapshot()
        if plan is None or plan["operation"] not in {"create", "update"}:
            raise ValueError("No workflow header is available for a partial draft")
        selection, target = self._context(plan["operation"])
        preview = self.preview
        if preview is None:
            raise ValueError("Partial draft has no validated preview")
        if plan["operation"] == "create":
            title, description = plan.get("title"), plan.get("description")
            if not isinstance(title, str) or not title.strip() or not isinstance(description, str) or not description.strip():
                raise ValueError("Partial create needs a title and description")
            # A frozen header must already satisfy final create metadata. Only
            # unsupported string icons receive the existing cosmetic fallback.
            if not isinstance(plan.get("icon"), str):
                raise ValueError("Partial create needs an icon string")
            icon = preview.get("icon") or normalize_workflow_identity("general_knowledge", plan["icon"]).icon
            identity = normalize_workflow_identity("general_knowledge", icon)
            return {"action": "create_workflow", "title": title.strip()[:200],
                    "description": description.strip()[:2000], "category": identity.category,
                    "icon": identity.icon, "graph": preview["graph"], "enabled": False,
                    "assumptions": preview["assumptions"], "partial": True}
        if target is None:
            raise ValueError("Partial update target is missing")
        prior = WorkflowGraph.model_validate(target["graph"])
        if not self.records:
            preserve = compile_authoring_preview({key: value for key, value in plan.items() if key != "steps"},
                                                  selection, self.timezone, target)
            graph_data = preserve["graph"]
        else:
            authored = WorkflowGraph.model_validate(preview["graph"])
            old_ids = {node.id for node in prior.nodes}
            new_ids = {record["id"] for record in self.records} - old_ids
            replacements = {node.id: node for node in authored.nodes}
            merged = prior.model_copy(deep=True)
            merged.nodes = [replacements.get(node.id, node) for node in merged.nodes]
            authored_edges = {edge.to_node: edge for edge in authored.edges}
            for record in self.records:
                node_id = record["id"]
                if node_id not in new_ids:
                    continue
                node = replacements.get(node_id)
                incoming = authored_edges.get(node_id)
                if node is None or incoming is None:
                    raise ValueError("Partial update node has no validated insertion point")
                if incoming.from_node not in {item.id for item in merged.nodes}:
                    raise ValueError("Partial update predecessor is unavailable")
                slot = next((index for index, edge in enumerate(merged.edges)
                             if edge.from_node == incoming.from_node and edge.branch == incoming.branch), None)
                displaced = merged.edges[slot].to_node if slot is not None else None
                if displaced is not None and node.type == WorkflowNodeType.END:
                    raise ValueError("Partial update End cannot hide an existing continuation")
                merged.nodes.append(node)
                inserted = incoming.model_copy(deep=True)
                if slot is None:
                    merged.edges.append(inserted)
                else:
                    merged.edges[slot] = inserted
                    continuation_branch = "default" if node.type == WorkflowNodeType.CHECK else None
                    merged.edges.append(WorkflowEdge(**{"from": node_id, "to": displaced,
                                                        "branch": continuation_branch}))
            merged = WorkflowGraph.model_validate(merged.model_dump(mode="json", by_alias=True))
            _validate_builder_execution_inputs(merged)
            validate_workflow_composition_refs(merged, prior, allow_data_dependencies=True)
            graph_data = merged.model_dump(mode="json", by_alias=True)
        result = {"action": "update_workflow", "workflow_id": target["id"], "graph": graph_data,
                  "enabled": False, "assumptions": preview["assumptions"], "partial": True}
        version = target.get("version")
        if isinstance(version, int) and not isinstance(version, bool) and version >= 1:
            result["expected_record_version"] = version
        for key in ("title", "description", "icon"):
            if plan.get(key) is not None:
                result[key] = plan[key]
        return result

    def compile_final(self) -> dict[str, Any]:
        plan = self.snapshot()
        if plan is None:
            raise ValueError("Flat authoring header is missing")
        selection, target = self._context(plan["operation"])
        return compile_authoring_plan(plan, selection, self.timezone, target)
