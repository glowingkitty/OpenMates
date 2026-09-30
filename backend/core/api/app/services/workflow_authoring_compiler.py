"""Compile a compact, registry-scoped authoring plan into a Workflow V2 graph.

Gemini chooses semantic steps and values. This module owns graph wiring, reference
syntax, selected capability enforcement, and final runtime validation. The plan
contains ordered steps; a Check's yes/no/unsure arrays are branch-local steps.
Steps following a Check become its default continuation, which the runner executes
after the selected branch completes. No model-authored graph edges are accepted.
"""

from __future__ import annotations

import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator

from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_identity_service import (
    WORKFLOW_ALLOWED_ICONS, normalize_workflow_identity,
)
from backend.core.api.app.services.workflow_models import (
    WorkflowEdge, WorkflowGraph, WorkflowNode, WorkflowNodeType,
    validate_workflow_composition_refs, validate_workflow_readiness,
)


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)*$")
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DATES = ("today", "today_end", "tomorrow", "tomorrow_end", "next_seven_days_start",
          "next_seven_days_end", "next_week_start", "next_week_end")
_MAX_STEPS = 40


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": required if required is not None else list(properties)}


def _ref_schema() -> dict[str, Any]:
    return _object({"step": {"type": "string"}, "field": {"type": "string"}})


def _reference_schema() -> dict[str, Any]:
    return _object({"ref": _ref_schema()})


def _date_schema() -> dict[str, Any]:
    return _object({"$date": {"type": "string", "enum": list(_DATES)},
                    "format": {"type": "string", "enum": ["date", "datetime"]}}, ["$date"])


def _input_schema(schema: dict[str, Any], *, depth: int = 0, allow_ref: bool = True) -> dict[str, Any]:
    """Project a selected app contract into Gemini's bounded JSON Schema subset."""
    if depth > 8:
        raise ValueError("Selected capability input schema is too deep")
    kind = schema.get("type", "string")
    if isinstance(kind, list):
        kinds = [item for item in kind if item != "null"]
        kind = kinds[0] if len(kinds) == 1 else "string"
    if kind == "object":
        props = {key: _input_schema(value, depth=depth + 1)
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
    if kind == "string" and schema.get("format") in {"date", "date-time", "datetime"}:
        alternatives.append(_date_schema())
    return {"anyOf": alternatives} if len(alternatives) > 1 else literal


def build_authoring_schema(selection: WorkflowPreselection) -> dict[str, Any]:
    """Return a compact JSON Schema scoped to Jev's selected capabilities.

    The provider may emit ``operation=clarify`` with a reason when a faithful
    workflow cannot be represented. Objects are intentionally shallow and step
    nesting is bounded to three Check levels; compilation also enforces limits.
    """
    ref = _reference_schema()
    segment = {"anyOf": [_object({"text": {"type": "string"}}), ref]}
    segments = {"type": "array", "items": segment}
    scalar = {"anyOf": [{"type": ["string", "number", "boolean", "null"]}, ref]}
    comparison = _object({"op": {"type": "string", "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "starts_with", "exists"]},
                          "left": scalar, "right": scalar}, ["op", "left"])
    predicate = {"anyOf": [comparison, _object({"op": {"type": "string", "enum": ["and", "or"]},
                                                "conditions": {"type": "array", "items": comparison}})]}
    block = _object({"id": {"type": "string"}, "source": _ref_schema(),
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
    definitions["send"] = _object({**common, "kind": {"type": "string", "enum": ["send"]},
                                    "title": {"type": "string"}, "message": segments,
                                    "blocks": {"type": "array", "items": block}}, ["kind", "id", "title", "message"])
    definitions["end"] = _object({**common, "kind": {"type": "string", "enum": ["end"]}})
    base_variants = [*app_variants]
    if "ask_ai" in definitions:
        base_variants.append({"$ref": "#/$defs/ask_ai"})
    base_variants.extend([{"$ref": "#/$defs/send"}, {"$ref": "#/$defs/end"}])
    definitions["step_0"] = {"anyOf": base_variants}
    for depth in range(1, 4):
        children = {"type": "array", "items": {"$ref": f"#/$defs/step_{depth - 1}"}}
        check_name = f"check_{depth}"
        definitions[check_name] = _object({**common, "kind": {"type": "string", "enum": ["check"]},
                                           "mode": {"type": "string", "enum": ["exact", "ai"]},
                                           "predicate": predicate, "question": segments,
                                           "selected_inputs": {"type": "array", "items": _ref_schema()},
                                           "yes": children, "no": children, "unsure": children},
                                          ["kind", "id", "mode", "yes", "no"])
        definitions[f"step_{depth}"] = {"anyOf": [*base_variants, {"$ref": f"#/$defs/{check_name}"}]}

    schedule = _object({"type": {"type": "string", "enum": ["daily", "weekly", "manual"]},
                        "time": {"type": "string"}, "timezone": {"type": "string"},
                        "weekdays": {"type": "array", "items": {"type": "string", "enum": list(_DAYS)}}}, ["type"])
    result = _object({"operation": {"type": "string", "enum": ["create", "update", "clarify"]},
                    "workflow_id": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "icon": {"anyOf": [{"type": "string", "enum": sorted(WORKFLOW_ALLOWED_ICONS)},
                                       {"type": "null"}]},
                    "schedule": schedule,
                    "steps": {"type": "array", "items": {"$ref": "#/$defs/step_3"}},
                    "message": {"type": ["string", "null"]}}, ["operation"])
    result["$defs"] = definitions
    return result


def _reference(value: Any, known: set[str], label: str) -> str:
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


def _value(value: Any, known: set[str], label: str) -> Any:
    if isinstance(value, dict):
        if set(value) == {"ref"}:
            return _reference(value["ref"], known, label)
        if "$date" in value:
            if set(value) - {"$date", "format"} or value["$date"] not in _DATES or value.get("format", "datetime") not in {"date", "datetime"}:
                raise ValueError(f"{label}: invalid runtime date marker")
            return value
        return {key: _value(child, known, f"{label}.{key}") for key, child in value.items() if child is not None}
    if isinstance(value, list):
        return [_value(child, known, label) for child in value]
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
            result.append("{{ " + _reference(segment["ref"], known, label) + " }}")
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


def compile_authoring_plan(
    raw: dict[str, Any], selection: WorkflowPreselection, timezone: str,
    selected_workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile one compact plan to the WorkflowInputService action envelope.

    ``raw`` is untrusted model output. Every generated graph passes the existing
    typed graph, readiness, and composition validators. Updates are full graph
    replacements and keep any supplied existing node IDs unchanged.
    """
    if not isinstance(raw, dict):
        raise ValueError("Authoring plan must be an object")
    # JSON mode does not enforce responseFormat's union schema. Validate the
    # selected capability contract here before interpreting any model field.
    # Never include raw values or validator messages in errors: they can contain
    # user content or provider output.
    errors = Draft202012Validator(build_authoring_schema(selection)).iter_errors(raw)
    first_error = next(errors, None)
    if first_error is not None:
        path = first_error.json_path
        raise ValueError(f"Authoring plan violates the selected capability schema at {path}")
    operation = raw.get("operation")
    if operation == "clarify":
        message = raw.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Clarification requires a reason")
        return {"action": "needs_clarification", "message": message.strip()[:1000]}
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
    trigger_id = previous_graph.trigger_node_id if previous_graph and previous_graph.trigger_node_id else "trigger"
    schedule = raw.get("schedule") or {"type": "weekly", "time": "09:00", "weekdays": ["monday"]}
    if not isinstance(schedule, dict):
        raise ValueError("Schedule must be an object")
    schedule_type = schedule.get("type")
    if schedule_type not in {"daily", "weekly", "manual"}:
        raise ValueError("Schedule type is unsupported")
    if schedule_type != "manual":
        time = schedule.get("time", "09:00")
        zone = schedule.get("timezone") or timezone
        if not isinstance(time, str) or not _TIME.fullmatch(time):
            raise ValueError("Schedule time must be HH:MM")
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("Schedule timezone is invalid") from exc
        config_schedule: dict[str, Any] = {"type": schedule_type, "time": time, "timezone": zone}
        if schedule_type == "weekly":
            weekdays = schedule.get("weekdays") or ["monday"]
            if not isinstance(weekdays, list) or not weekdays or any(day not in _DAYS for day in weekdays) or len(set(weekdays)) != len(weekdays):
                raise ValueError("Weekly schedule needs unique weekdays")
            config_schedule["weekdays"] = weekdays
        trigger = WorkflowNode(id=trigger_id, type=WorkflowNodeType.SCHEDULE_TRIGGER, config={"schedule": config_schedule})
    else:
        trigger = WorkflowNode(id=trigger_id, type=WorkflowNodeType.MANUAL_TRIGGER)
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Authoring plan requires steps")
    selected_ids = {cap.id for cap in selection.capabilities}
    nodes = [trigger]
    edges: list[WorkflowEdge] = []
    used_ids = {trigger_id}
    sends = 0
    total = 0

    def edge(source: str, target: str, branch: str | None = None) -> None:
        edges.append(WorkflowEdge(**{"from": source, "to": target, "branch": branch}))

    def compile_sequence(items: list[Any], incoming: tuple[str, str | None] | None,
                         depth: int, known: set[str]) -> None:
        nonlocal sends, total
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
                capability = item.get("capability")
                if capability not in selected_ids or capability == "ai.ask":
                    raise ValueError("App step must use a selected capability")
                authored = item.get("input")
                if not isinstance(authored, dict):
                    raise ValueError("App input must be an object")
                app_id, skill_id = capability.split(".", 1)
                node = WorkflowNode(id=node_id, type=WorkflowNodeType.APP_SKILL_ACTION,
                                    config={"app_id": app_id, "skill_id": skill_id,
                                            "input": _value(authored, known, f"Step {node_id} input")})
            elif kind == "ask_ai":
                if "ai.ask" not in selected_ids:
                    raise ValueError("Ask AI capability was not selected")
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
                    config = {"mode": "ai", "question": _text(item.get("question"), known, f"Step {node_id} question"),
                              "selected_inputs": selected_inputs}
                node = WorkflowNode(id=node_id, type=WorkflowNodeType.CHECK, config=config)
            elif kind == "send":
                if not selection.chat_delivery:
                    raise ValueError("Chat delivery was not selected")
                message = _text(item.get("message"), known, f"Step {node_id} message")
                blocks = []
                for block in item.get("blocks") or []:
                    if not isinstance(block, dict) or not isinstance(block.get("id"), str):
                        raise ValueError("Message block requires an ID")
                    compiled = {"id": block["id"], "source": _reference(block.get("source"), known, f"Step {node_id} block")}
                    if "only_new_results" in block:
                        compiled["only_new_results"] = block["only_new_results"]
                    if "include_if" in block:
                        value = block["include_if"]
                        compiled["include_if"] = _reference(value["ref"], known, f"Step {node_id} block condition") if isinstance(value, dict) and set(value) == {"ref"} else value
                    blocks.append(compiled)
                node = WorkflowNode(id=node_id, type=WorkflowNodeType.SEND_CHAT_MESSAGE,
                                    config={"title": item.get("title") or raw.get("title") or "Workflow update",
                                            "message": message, "blocks": blocks})
                sends += 1
            elif kind == "end":
                node = WorkflowNode(id=node_id, type=WorkflowNodeType.END)
            else:
                raise ValueError("Unsupported authoring step kind")
            nodes.append(node)
            known.add(node_id)
            if kind == "check":
                for branch in ("yes", "no", "unsure"):
                    branch_items = item.get(branch) or []
                    if not isinstance(branch_items, list):
                        raise ValueError("Check branches must be step lists")
                    if branch_items:
                        compile_sequence(branch_items, (node_id, branch), depth + 1, known.copy())
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
            elif kind == "end":
                if position != len(items) - 1:
                    raise ValueError("End must finish its sequence")
                previous = None
            else:
                previous = (node_id, None)

    compile_sequence(steps, (trigger_id, None), 0, {trigger_id})
    if not sends:
        raise ValueError("Authoring plan has no chat delivery")
    graph = WorkflowGraph(version=2, trigger_node_id=trigger_id, nodes=nodes, edges=edges)
    validate_workflow_readiness(graph, require_schedule=schedule_type != "manual")
    validate_workflow_composition_refs(graph, previous_graph, allow_data_dependencies=True)
    graph_data = graph.model_dump(mode="json", by_alias=True)
    if operation == "update":
        result = {"action": "update_workflow", "workflow_id": selected_workflow["id"], "graph": graph_data}
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
            "enabled": False, "assumptions": []}
