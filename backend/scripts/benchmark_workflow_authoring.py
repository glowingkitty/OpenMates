"""Live, non-persistent comparison of Workflow V2 authoring after shared selection.

Run inside the API container, for example::

    python -m backend.scripts.benchmark_workflow_authoring --output /tmp/workflow-authoring.json

This is a paid, opt-in engineering benchmark. It never saves or executes graphs.
Its timings exclude identity generation, persistence and execution. The model
receives a closed, capability-derived V2 graph schema, followed by full runtime
graph validation and a separate intent oracle.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
from backend.core.api.app.services.workflow_models import (
    WorkflowGraph,
    WorkflowNodeType,
    validate_workflow_composition_refs,
    validate_workflow_readiness,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.typesafe.client import JevDecisionClient

LOGGER = logging.getLogger(__name__)
TIMEZONE = "Europe/Berlin"
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-120b"),
    "cerebras": ("https://api.cerebras.ai/v1/chat/completions", "gpt-oss-120b"),
}
PRICES_PER_MILLION = {"groq": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
                      "cerebras": {"input": 0.35, "cached_input": 0.35, "output": 0.75}}


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    required_capabilities: tuple[str, ...]
    literals: tuple[str, ...] = ()
    schedule_type: str = "daily"
    time: str = "08:00"
    weekdays: tuple[str, ...] = ()
    check_mode: str | None = None
    min_actions: int = 1
    branch_labels: tuple[str, ...] = ()
    min_variable_refs: int = 0
    action_literals: tuple[str, ...] = ()
    branch_words: tuple[tuple[str, str], ...] = ()
    require_missing_fallback: bool = False
    forbidden_literals: tuple[str, ...] = ()
    forbidden_action_literals: tuple[str, ...] = ()
    require_date_marker: str | None = None
    allow_end_branches: tuple[str, ...] = ()


CASES = (
    Case("rain_if", "Every day at 08:00 in Berlin, check today's weather in Berlin. If rain is expected, send me a chat message to take an umbrella; otherwise send me a chat message that it should be dry.", ("weather.forecast",), ("Berlin", "umbrella"), check_mode="exact", branch_labels=("yes", "no"), action_literals=("Berlin",), branch_words=(("yes", "umbrella"), ("no", "dry"))),
    Case("weather_cities", "Every weekday at 07:30 Berlin time, get today's weather for Berlin, Paris and London and send the forecasts in one chat message, including a message if a city has no forecast.", ("weather.forecast",), ("Berlin", "Paris", "London"), "weekly", "07:30", ("monday", "tuesday", "wednesday", "thursday", "friday"), min_actions=3, min_variable_refs=1, action_literals=("Berlin", "Paris", "London"), require_missing_fallback=True),
    Case("web_search", "Every Monday at 09:00 Berlin time, search the web for recent open source database releases and send the results to my chat.", ("web.search",), ("open source database",), "weekly", "09:00", ("monday",), min_variable_refs=1, action_literals=("open source database",)),
    Case("shopping_price", "Every day at 10:00 Berlin time, search shopping for a refurbished ThinkPad T14 under 700 EUR and send matching products and prices to chat.", ("shopping.search_products",), ("ThinkPad T14", "700"), time="10:00", min_variable_refs=1, action_literals=("ThinkPad T14", "700")),
    Case("events_summary", "Every Friday at 16:00 Berlin time, find upcoming AI events in Berlin, ask AI to summarize the results, and send the summary to my chat.", ("events.search", "ai.ask"), ("Berlin", "AI"), "weekly", "16:00", ("friday",), min_actions=2, min_variable_refs=2, action_literals=("Berlin",)),
    Case("subjective_check", "Every day at 18:00 Berlin time, search news about AI policy. Use an AI check to decide if anything is important for a small European startup; if yes, send the relevant news to chat, otherwise say there is no important update.", ("news.search",), ("AI policy", "European startup"), time="18:00", check_mode="ai", branch_labels=("yes", "no"), min_variable_refs=1, action_literals=("AI policy",), branch_words=(("no", "no important"),)),
    Case("speech_self_correction", "Um every day at 7, no sorry at 08:30, check tomorrow’s weather in Berlin, actually Lisbon, and if rain is expected send me a chat message reminding me to take an umbrella.", ("weather.forecast",), ("Lisbon", "umbrella"), time="08:30", check_mode="exact", branch_labels=("yes", "no"), action_literals=("Lisbon",), branch_words=(("yes", "umbrella"),), forbidden_literals=("07:00",), forbidden_action_literals=("Berlin",), require_date_marker="tomorrow", allow_end_branches=("no",)),
)


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    """All properties are required by provider strict mode; nullable means omitted."""
    result = {"type": "object", "additionalProperties": False,
              "properties": properties}
    if properties:
        result["required"] = list(properties)
    return result


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    result = dict(schema)
    if "anyOf" in result:
        return {"anyOf": [*result["anyOf"], {"type": "null"}]}
    declared = result.get("type")
    result["type"] = [declared, "null"] if isinstance(declared, str) else [*declared, "null"]
    if "enum" in result:
        result["enum"] = [*result["enum"], None]
    return result


def _date_value() -> dict[str, Any]:
    return _object({"$date": {"type": "string", "enum": [
        "today", "today_end", "tomorrow", "tomorrow_end", "next_seven_days_start",
        "next_seven_days_end", "next_week_start", "next_week_end"]},
                    "format": {"type": "string", "enum": ["date", "datetime"]}})


def _input_schema(schema: dict[str, Any], *, optional: bool = False, root: bool = False) -> dict[str, Any]:
    """Compile public app input metadata into provider-safe strict JSON Schema."""
    kind = schema.get("type", "string")
    if isinstance(kind, list):
        kind = next((part for part in kind if part != "null"), "string")
    if kind == "object":
        original = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        converted = {name: _input_schema(child, optional=name not in required)
                     for name, child in original.items() if isinstance(child, dict)}
        result = _object(converted)
    elif kind == "array":
        result = {"type": "array", "items": _input_schema(schema.get("items") or {"type": "string"})}
    else:
        result = {"type": kind}
        if isinstance(schema.get("enum"), list):
            result["enum"] = schema["enum"]
        if isinstance(schema.get("description"), str):
            result["description"] = schema["description"][:180]
        if kind == "string" and schema.get("format") in {"date", "date-time", "datetime"}:
            result = {"anyOf": [result, _date_value()]}
    # Typed upstream references are strings even when the resolved value is
    # numeric, an array or an object. Full readiness checks the referenced type.
    if kind in {"integer", "number", "boolean", "array", "object"} and not root:
        result = {"anyOf": [result, {"type": "string"}]}
    return _nullable(result) if optional else result


def _node(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    return _object({"id": {"type": "string"}, "type": {"type": "string", "const": kind},
                    "title": {"type": ["string", "null"]}, "config": config})


def _transport_schema(selection: Any) -> dict[str, Any]:
    """Close each node config over builtins and exactly the selected skills."""
    day = _object({"type": {"type": "string", "const": "daily"},
                   "time": {"type": "string"}, "timezone": {"type": "string"}})
    week = _object({"type": {"type": "string", "const": "weekly"},
                    "time": {"type": "string"}, "timezone": {"type": "string"},
                    "weekdays": {"type": "array", "items": {"type": "string", "enum": [
                        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]}}})
    scalar = {"type": ["string", "number", "boolean", "null"]}
    comparison = _object({"op": {"type": "string", "enum": [
        "eq", "neq", "gt", "gte", "lt", "lte", "contains", "starts_with", "exists"]},
                          "left": scalar, "right": scalar})
    compound = _object({"op": {"type": "string", "enum": ["and", "or"]},
                        "conditions": {"type": "array", "items": comparison}})
    block = _object({"id": {"type": "string"}, "source": {"type": "string"},
                     "only_new_results": _nullable({"type": "boolean"}),
                     "include_if": _nullable({"type": "boolean"})})
    variants = [
        _node("schedule_trigger", _object({"schedule": {"anyOf": [day, week]}})),
        _node("manual_trigger", _object({})),
        _node("check", {"anyOf": [
            _object({"mode": {"type": "string", "const": "exact"},
                     "predicate": {"anyOf": [comparison, compound]}}),
            _object({"mode": {"type": "string", "const": "ai"},
                     "question": {"type": "string"},
                     "selected_inputs": {"type": "array", "items": {"type": "string"}}})]}),
        _node("send_chat_message", _object({
            "title": {"type": "string"}, "message": _nullable({"type": "string"}),
            "blocks": {"type": "array", "items": block}})),
        _node("end", _object({})),
    ]
    app_configs = []
    for cap in selection.capabilities:
        schema = cap.metadata["input_schema"]
        if cap.id == "ai.ask":
            schema = {"type": "object", "properties": {"prompt": schema["properties"]["prompt"]},
                      "required": ["prompt"]}
        app_configs.append(_object({
            "capability_id": {"type": "string", "const": cap.id},
            "input": _input_schema(schema, root=True)}))
    if app_configs:
        variants.append(_node("app_skill_action", {"anyOf": app_configs}))
    edge = _object({"from": {"type": "string"}, "to": {"type": "string"},
                    "branch": {"type": ["string", "null"],
                               "enum": [None, "yes", "no", "unsure", "default"]}})
    return _object({"version": {"type": "integer", "const": 2},
                    "trigger_node_id": {"type": ["string", "null"]},
                    "nodes": {"type": "array", "items": {"anyOf": variants}},
                    "edges": {"type": "array", "items": edge}})


def decode_transport(raw: dict[str, Any], selection: Any | None = None) -> dict[str, Any]:
    """Remove strict-mode null placeholders for optional app and message fields."""
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list):
        raise ValueError("Transport is not a graph object")
    graph = {key: raw[key] for key in ("version", "trigger_node_id", "edges")}
    graph["nodes"] = []
    schemas = {cap.id: cap.metadata["input_schema"] for cap in selection.capabilities} if selection else {}
    for node in raw["nodes"]:
        config = node["config"]
        if not isinstance(config, dict):
            raise ValueError("Node config must be an object")
        if node["type"] == "app_skill_action":
            capability_id = config["capability_id"]
            if not isinstance(capability_id, str) or capability_id not in schemas:
                raise ValueError("Action capability ID was not selected")
            app_id, skill_id = capability_id.split(".", 1)
            config = {"app_id": app_id, "skill_id": skill_id,
                      "input": _strip_optional_nulls(config["input"], schemas[capability_id])}
        elif node["type"] == "send_chat_message":
            message_schema = {"type": "object", "properties": {
                "title": {"type": "string"}, "message": {"type": "string"},
                "blocks": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "string"}, "source": {"type": "string"},
                    "only_new_results": {"type": "boolean"},
                    "include_if": {"type": ["string", "boolean"]}},
                    "required": ["id", "source"]}}}, "required": ["title", "blocks"]}
            config = _strip_optional_nulls(config, message_schema)
        graph["nodes"].append({"id": node["id"], "type": node["type"],
                               "title": node.get("title"), "config": config})
    return graph


def _strip_optional_nulls(value: Any, schema: dict[str, Any]) -> Any:
    if isinstance(value, dict) and schema.get("type") == "object":
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        return {key: _strip_optional_nulls(child, properties.get(key) or {})
                for key, child in value.items() if child is not None or key in required}
    if isinstance(value, list) and schema.get("type") == "array":
        return [_strip_optional_nulls(child, schema.get("items") or {}) for child in value]
    return value


def validate_graph(raw: dict[str, Any], selected_ids: set[str]) -> WorkflowGraph:
    graph = WorkflowGraph.model_validate(raw)
    if graph.version != 2:
        raise ValueError("Expected Workflow V2 graph")
    for node in graph.nodes:
        if node.type == WorkflowNodeType.APP_SKILL_ACTION:
            cap = f"{node.config.get('app_id')}.{node.config.get('skill_id')}"
            if cap not in selected_ids:
                raise ValueError(f"Action {cap} was not selected by preselection")
    validate_workflow_readiness(graph, require_schedule=True)
    validate_workflow_composition_refs(graph)
    return graph


def _uses_output(value: Any, node_id: str, field: str) -> bool:
    """Recognize a complete typed output path in authored text or result blocks."""
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    escaped_node, escaped_field = re.escape(node_id), re.escape(field)
    return bool(re.search(
        rf"(?:\$nodes\.{escaped_node}\.output\.|steps\.{escaped_node}\.){escaped_field}(?![A-Za-z0-9_-])",
        content,
    ))


def _weather_city_ai_fallback(graph: WorkflowGraph, weather_actions: list[Any], cities: tuple[str, ...]) -> bool:
    """Accept an AI formatter only when every city's real rows and empty case reach one chat."""
    sends = [node for node in graph.nodes if node.type == WorkflowNodeType.SEND_CHAT_MESSAGE]
    if len(sends) != 1:
        return False
    message = sends[0].config.get("message") or ""
    for node in graph.nodes:
        if node.type != WorkflowNodeType.APP_SKILL_ACTION or (
            node.config.get("app_id"), node.config.get("skill_id")
        ) != ("ai", "ask") or not _uses_output(message, node.id, "answer"):
            continue
        prompt = str((node.config.get("input") or {}).get("prompt") or "")
        if not all(any(
            city.casefold() in str((weather.config.get("input") or {}).get("location") or "").casefold()
            and _uses_output(prompt, weather.id, "results") for weather in weather_actions
        ) for city in cities):
            continue
        if re.search(r"\b(?:if|when)\b.{0,120}\b(?:no forecast|missing|unavailable|empty|does not have a forecast)\b",
                     prompt, re.IGNORECASE | re.DOTALL) and re.search(
                         r"\b(?:city|cities|location|place)\b", prompt, re.IGNORECASE
                     ):
            return True
    return False


def oracle(graph: WorkflowGraph, case: Case) -> list[str]:
    """Independent, conservative intent checks; no planner decisions are used."""
    issues: list[str] = []
    actions = [n for n in graph.nodes if n.type == WorkflowNodeType.APP_SKILL_ACTION]
    capabilities = [f"{n.config.get('app_id')}.{n.config.get('skill_id')}" for n in actions]
    weather_actions = [n for n in actions if n.config.get("app_id") == "weather"
                       and n.config.get("skill_id") == "forecast"]
    city_ai_fallback = case.id == "weather_cities" and _weather_city_ai_fallback(
        graph, weather_actions, case.action_literals
    )
    if case.id in {"rain_if", "weather_cities", "speech_self_correction"}:
        target_day = "tomorrow" if case.id == "speech_self_correction" else "today"
        for action in weather_actions:
            weather_input = action.config.get("input") or {}
            start = weather_input.get("start_date")
            end = weather_input.get("end_date")
            exact_runtime_day = (isinstance(start, dict) and start.get("$date") == target_day
                                 and isinstance(end, dict) and end.get("$date") == target_day)
            exact_today_days = (target_day == "today" and type(weather_input.get("days")) is int
                                and weather_input["days"] == 1)
            if not (exact_runtime_day or exact_today_days):
                issues.append(f"weather action {action.id} lacks exact {target_day} range")
    for required in case.required_capabilities:
        if required not in capabilities:
            issues.append(f"missing capability {required}")
    for extra in sorted(set(capabilities) - set(case.required_capabilities)):
        if not (extra == "ai.ask" and city_ai_fallback):
            issues.append(f"unrequested capability {extra}")
    if case.id == "weather_cities":
        sends = [node for node in graph.nodes if node.type == WorkflowNodeType.SEND_CHAT_MESSAGE]
        for city in case.action_literals:
            city_actions = [node for node in weather_actions if city.casefold() in
                            str((node.config.get("input") or {}).get("location") or "").casefold()]
            direct = any(_uses_output(send.config, weather.id, field)
                         for weather in city_actions for field in ("results", "forecast_days") for send in sends)
            via_ai = any(
                _uses_output(str((ai.config.get("input") or {}).get("prompt") or ""), weather.id, field)
                and any(_uses_output(send.config.get("message") or "", ai.id, "answer") for send in sends)
                for weather in city_actions for field in ("results", "forecast_days")
                for ai in actions if (ai.config.get("app_id"), ai.config.get("skill_id")) == ("ai", "ask")
            )
            if not direct and not via_ai:
                issues.append(f"{city} forecast results do not reach chat")
    if case.id == "events_summary":
        event_nodes = [n.id for n in actions if n.config.get("app_id") == "events" and n.config.get("skill_id") == "search"]
        ask_nodes = [n for n in actions if n.config.get("app_id") == "ai" and n.config.get("skill_id") == "ask"]
        def refers_to(value: str, node_id: str, field: str) -> bool:
            return f"{node_id}.output.{field}" in value or f"steps.{node_id}.{field}" in value
        # The workflow adapter exposes the same normalized list through both
        # `results` and its declared domain alias `events`.
        if not any(any(refers_to(str(ask.config.get("input", {}).get("prompt", "")), source, field)
                       for source in event_nodes for field in ("results", "events")) for ask in ask_nodes):
            issues.append("Ask AI prompt does not use event results")
        messages = json.dumps([n.config for n in graph.nodes
                               if n.type == WorkflowNodeType.SEND_CHAT_MESSAGE], ensure_ascii=False)
        if not any(refers_to(messages, ask.id, "answer") for ask in ask_nodes):
            issues.append("final message does not use Ask AI answer")
    if len(actions) < case.min_actions:
        issues.append(f"expected at least {case.min_actions} actions")
    triggers = [n for n in graph.nodes if n.type == WorkflowNodeType.SCHEDULE_TRIGGER]
    if len(triggers) != 1:
        issues.append("missing single schedule trigger")
    else:
        schedule = triggers[0].config.get("schedule") or {}
        if schedule.get("type") != case.schedule_type:
            issues.append("schedule recurrence mismatch")
        if schedule.get("time") != case.time:
            issues.append("schedule time mismatch")
        if schedule.get("timezone") != TIMEZONE:
            issues.append("schedule timezone mismatch")
        if case.weekdays and {str(x).lower() for x in schedule.get("weekdays", [])} != set(case.weekdays):
            issues.append("schedule weekdays mismatch")
    serialized = json.dumps([n.config for n in graph.nodes], ensure_ascii=False).casefold()
    action_inputs = json.dumps([n.config.get("input") for n in actions], ensure_ascii=False).casefold()
    for literal in case.literals:
        if literal.casefold() not in serialized:
            issues.append(f"missing requested literal {literal}")
    for literal in case.action_literals:
        if literal.casefold() not in action_inputs:
            issues.append(f"missing action input {literal}")
    for literal in case.forbidden_literals:
        if literal.casefold() in serialized:
            issues.append(f"retained superseded literal {literal}")
    for literal in case.forbidden_action_literals:
        if literal.casefold() in action_inputs:
            issues.append(f"retained superseded action input {literal}")
    if case.require_date_marker:
        def has_date_marker(value: Any) -> bool:
            if isinstance(value, dict):
                return value.get("$date") == case.require_date_marker or any(has_date_marker(child) for child in value.values())
            if isinstance(value, list):
                return any(has_date_marker(child) for child in value)
            return False
        if not any(has_date_marker(n.config.get("input")) for n in actions):
            issues.append(f"missing runtime {case.require_date_marker} date")
    checks = [n for n in graph.nodes if n.type == WorkflowNodeType.CHECK]
    if case.check_mode and not any(n.config.get("mode") == case.check_mode for n in checks):
        issues.append(f"missing {case.check_mode} check")
    if case.require_missing_fallback and not city_ai_fallback:
        messages = json.dumps([n.config for n in graph.nodes
                               if n.type == WorkflowNodeType.SEND_CHAT_MESSAGE], ensure_ascii=False).casefold()
        if not any(term in messages for term in ("no forecast", "unavailable", "missing")):
            issues.append("missing forecast fallback message")
        if not any(n.config.get("mode", "exact") == "exact" and
                   "exists" in json.dumps(n.config.get("predicate", {})).casefold() for n in checks):
            issues.append("missing forecast existence check")
    labels = {e.branch for e in graph.edges if e.branch}
    for label in case.branch_labels:
        if label not in labels:
            issues.append(f"missing {label} branch")
    if case.branch_labels:
        outgoing: dict[str, list[str]] = {}
        for edge in graph.edges:
            outgoing.setdefault(edge.from_node, []).append(edge.to_node)
        by_id = {n.id: n for n in graph.nodes}
        branch_chats: dict[str, set[str]] = {}
        for label in case.branch_labels:
            branch_nodes = {e.to_node for e in graph.edges if e.branch == label}
            if not branch_nodes:
                continue
            reachable = set(branch_nodes)
            pending = list(branch_nodes)
            while pending:
                for child in outgoing.get(pending.pop(), []):
                    if child not in reachable:
                        reachable.add(child)
                        pending.append(child)
            branch_chats[label] = {node_id for node_id in reachable
                                   if by_id[node_id].type == WorkflowNodeType.SEND_CHAT_MESSAGE}
            if not branch_chats[label] and label not in case.allow_end_branches:
                issues.append(f"{label} branch has no chat message")
            if label in case.allow_end_branches and not branch_chats[label] and not any(
                by_id[node_id].type == WorkflowNodeType.END for node_id in reachable
            ):
                issues.append(f"{label} branch has no end")
        for label, chats in branch_chats.items():
            exclusive = chats - set().union(*(other for other_label, other in branch_chats.items()
                                              if other_label != label))
            if not exclusive and label not in case.allow_end_branches:
                issues.append(f"{label} branch has no distinct chat message")
            for expected_label, word in case.branch_words:
                if expected_label == label and not any(
                    word.casefold() in json.dumps(by_id[node_id].config, ensure_ascii=False).casefold()
                    for node_id in exclusive
                ):
                    issues.append(f"{label} branch is missing {word}")
    if serialized.count("$nodes.") + serialized.count("{{steps.") < case.min_variable_refs:
        issues.append("missing upstream output variables")
    if not any(n.type == WorkflowNodeType.SEND_CHAT_MESSAGE for n in graph.nodes):
        issues.append("missing chat delivery")
    return issues


def _prompt(selection: Any) -> str:
    context = selection.context()
    # The input schema is already in the complete transport schema below. Keep
    # public output contracts visible so the model can choose real references.
    visible_context = {**context, "capabilities": [
        {key: value for key, value in cap.items() if key not in {"input_schema", "workflow"}}
        for cap in context["capabilities"]]}
    schema = _transport_schema(selection)
    return (
        "Construct one executable Workflow V2 graph for the next user message. "
        f"Browser timezone: {TIMEZONE}. Use it for schedule timezone unless the "
        "user explicitly gives a different schedule timezone. A search or weather "
        "location alone does not change the schedule timezone. "
        "Use only the relevant members of the selected candidate app skill contracts; "
        "never invent a capability or field, and do not add irrelevant selected skills. "
        "Return only JSON with this exact root envelope: "
        "{version:2,trigger_node_id:'an ID from nodes',nodes:[node,...],edges:[edge,...]}. "
        "Every node is {id:'unique ID',type:'one allowed type',title:'text or null',config:object}. "
        "Every edge is {from:'existing node ID',to:'existing node ID',branch:null|'yes'|'no'|'unsure'|'default'}. "
        "No root or node fields beyond the schema. Each node config depends on that node's type. "
        "A schedule_trigger node has config:{schedule:{type:'daily'|'weekly',time:'HH:MM',"
        "timezone:'IANA timezone',weekdays:[lowercase weekday,...] only for weekly}}. "
        "An app_skill_action node has config:{capability_id:'one selected full app.skill ID',"
        "input:{fields from that capability input schema}}. Do not put app_id or skill_id "
        "in the transport config. Do not put schedule fields in an app action config. "
        "Check config uses mode exact with predicate {left,op,right}; valid ops are "
        "eq, neq, gt, gte, lt, lte, contains, starts_with, exists. For combined exact "
        "checks use {op:'and' or 'or',conditions:[simple predicates]}. AI check config "
        "uses mode ai, question and selected_inputs. "
        "Check edges use branch yes/no/unsure; preserve both branches when requested. "
        "An AI check question and an ai.ask prompt must include an inline "
        "{{steps.ID.FIELD}} variable from an earlier action, even when selected_inputs are set. "
        "Relative dates use {\"$date\":\"today\" or \"tomorrow\" or \"next_seven_days_start\" or \"next_seven_days_end\","
        "\"format\":\"date\" or \"datetime\"} as runtime input values, never a frozen literal date. "
        "Message blocks use {id: stable_id, source: '$nodes.ID.output.FIELD', "
        "only_new_results: true/false/null, include_if: true/false/null}. "
        "A block source must be a declared object or array output; use a message "
        "with an inline variable for scalar text outputs. "
        "For conditional delivery use Check yes/no edges with separate message nodes; "
        "leave include_if null. Set only_new_results true only for an array of objects. "
        "Use $nodes.<id>.output.<declared_field> or {{steps.<id>.<declared_field>}} "
        "for dataflow. Output fields must exist in the selected public output_schema; "
        "never invent a field. Send-chat config always has title, message and blocks. "
        "Message must contain an inline prior-action output variable even when blocks "
        "are present and even if the requested text is otherwise fixed. Use blocks:[] "
        "when no structured result list is needed. Set optional input fields to null "
        "when omitted. "
        "Build a connected acyclic graph. Write every node before writing edges. "
        "Every edge.from and edge.to MUST be an ID in nodes, letter-for-letter. "
        "A terminal message node may have no outgoing edge; do not point to a "
        "made-up end node. Add an end node only when an explicit branch needs to "
        "stop without sending a message. Each Check yes/no destination must exist. "
        "Do not insert account IDs, credentials, runtime grants, or guessed values. "
        f"Selected candidate context and public outputs: {json.dumps(visible_context, ensure_ascii=False, separators=(',', ':'))}\n"
        f"Complete transport JSON Schema: {json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}"
    )


async def _model_construct(client: httpx.AsyncClient, provider: str, key: str,
                           case: Case, selection: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    url, model = PROVIDERS[provider]
    schema = _transport_schema(selection)
    body = {"model": model, "temperature": 0, "max_completion_tokens": 4096,
            "messages": [{"role": "system", "content": _prompt(selection)},
                         {"role": "user", "content": case.text}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "workflow_graph", "strict": True, "schema": schema}}}
    body["reasoning_effort"] = "low"
    response = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json=body)
    # Never include provider response bodies or exception strings: they may echo secrets.
    if response.status_code != 200:
        raise ProviderHTTPFailure(provider, response.status_code, _safe_http_code(response))
    payload = response.json()
    choice = payload["choices"][0]
    metrics = {"usage": payload.get("usage", {}),
               "finish_reason": choice.get("finish_reason")}
    content = choice["message"].get("content")
    if not isinstance(content, str):
        raise TransportFailure("Provider returned no JSON content", metrics)
    try:
        raw = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise TransportFailure("Provider content is not JSON", metrics) from exc
    return raw, metrics


class TransportFailure(ValueError):
    """Safe transport failure carrying usage already billed by the provider."""

    def __init__(self, message: str, metrics: dict[str, Any]) -> None:
        super().__init__(message)
        self.metrics = metrics


class ProviderHTTPFailure(RuntimeError):
    """Safe HTTP failure classification without response body or auth content."""

    def __init__(self, provider: str, status: int, code: str | None = None) -> None:
        super().__init__(f"{provider} HTTP {status}")
        self.status = status
        self.code = code


def _safe_http_code(response: httpx.Response) -> str | None:
    """Classify known errors while discarding raw provider bodies and generations."""
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None
    known = {"json_validate_failed", "invalid_json_schema", "invalid_request_error",
             "rate_limit_exceeded", "authentication_error"}
    code = error.get("code")
    if isinstance(code, str) and code in known:
        return code
    # Some compatible providers expose only a prose message. Recognize only
    # stable markers; never store or display the message or failed_generation.
    message = error.get("message")
    if isinstance(message, str):
        lowered = message.casefold()
        if "json_validate_failed" in lowered:
            return "json_validate_failed"
        if "response_format" in lowered and "schema" in lowered:
            return "schema_request"
    return None


def _provider_cost(provider: str, usage: dict[str, Any]) -> float | None:
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    if not isinstance(prompt, (int, float)) or not isinstance(completion, (int, float)):
        return None
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    if not isinstance(cached, (int, float)):
        cached = 0
    cached = min(max(0, cached), prompt)
    prices = PRICES_PER_MILLION[provider]
    return round(((prompt - cached) * prices["input"] + cached * prices["cached_input"]
                  + completion * prices["output"]) / 1_000_000, 8)


def _safe_metrics(metrics: Any) -> dict[str, Any]:
    """Retain numeric usage only; no provider text, prompts or credentials."""
    if not isinstance(metrics, dict):
        return {}
    def numeric_tree(value: Any) -> Any:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, dict):
            return {str(k): child for k, v in value.items()
                    if (child := numeric_tree(v)) is not None}
        return None
    safe: dict[str, Any] = {}
    for key in ("jev_calls", "input_tokens", "output_tokens", "estimated_cost_usd", "usage", "finish_reason", "wave_seconds"):
        value = metrics.get(key)
        if key == "finish_reason" and isinstance(value, str):
            safe[key] = value
        elif (filtered := numeric_tree(value)) is not None:
            safe[key] = filtered
    return safe


async def _run_case(case: Case, providers: list[str],
                    client: httpx.AsyncClient, preselector: Any, jev: JevDecisionClient,
                    keys: dict[str, str]) -> list[dict[str, Any]]:
    from backend.core.api.app.services.workflow_jev_constructor import WorkflowJevConstructor

    start = time.perf_counter()
    try:
        selection = await preselector.select(case.text, timezone=TIMEZONE)
        preselection_ms = round((time.perf_counter() - start) * 1000, 1)
        selected_ids = {cap.id for cap in selection.capabilities}
        selection_metrics = _safe_metrics(selection.metrics)
    except Exception as exc:
        # Exception text can contain provider payloads; report only class name.
        return [{"case": case.id, "provider": p, "stage": "preselection",
                 "error": type(exc).__name__} for p in providers]

    rows = []
    for provider in providers:
        row: dict[str, Any] = {"case": case.id, "provider": provider,
                               "preselection_ms": preselection_ms,
                               "preselection_metrics": selection_metrics,
                               "preselection_scores": {str(key): float(value) for key, value in selection.scores.items()},
                               "operation": selection.operation,
                               "check_mode": selection.check_mode,
                               "chat_delivery": selection.chat_delivery,
                               "selected_capabilities": sorted(selected_ids),
                               "transport_valid": None, "graph_valid": False,
                               "intent_match": False}
        started = time.perf_counter()
        constructor = None
        try:
            if provider == "jev":
                constructor = WorkflowJevConstructor(jev_client=jev)
                raw, metrics = await constructor.construct(
                    text=case.text, selection=selection, timezone=TIMEZONE)
                row["transport_valid"] = True  # Jev constructs native graph directly.
            else:
                envelope, metrics = await _model_construct(client, provider, keys[provider], case, selection)
                row["construction_metrics"] = _safe_metrics(metrics)
                row["construction_metrics"]["estimated_cost_usd"] = _provider_cost(provider, metrics["usage"])
                raw = decode_transport(envelope, selection)
                row["transport_valid"] = True
            row["construction_ms"] = round((time.perf_counter() - started) * 1000, 1)
            row["planning_ms"] = round(row["preselection_ms"] + row["construction_ms"], 1)
            row["construction_metrics"] = _safe_metrics(metrics)
            if provider in PROVIDERS:
                row["construction_metrics"]["estimated_cost_usd"] = _provider_cost(provider, metrics["usage"])
            if constructor is not None:
                trace = getattr(constructor, "decision_trace", None)
                if isinstance(trace, list):
                    row["decision_trace"] = trace
            row["graph"] = raw  # Private local report only; never printed to stdout.
            graph = validate_graph(raw, selected_ids)
            row["graph_valid"] = True
            row["intent_issues"] = oracle(graph, case)
            row["intent_match"] = not row["intent_issues"]
            row["node_types"] = [n.type.value for n in graph.nodes]
            row["action_capabilities"] = [f"{n.config['app_id']}.{n.config['skill_id']}" for n in graph.nodes if n.type == WorkflowNodeType.APP_SKILL_ACTION]
        except Exception as exc:
            if isinstance(exc, TransportFailure):
                row["construction_metrics"] = _safe_metrics(exc.metrics)
                row["construction_metrics"]["estimated_cost_usd"] = _provider_cost(provider, exc.metrics.get("usage", {}))
            if isinstance(exc, ProviderHTTPFailure):
                row["http_status"] = exc.status
                row["http_code"] = exc.code
            if constructor is not None:
                row["construction_metrics"] = _safe_metrics(getattr(constructor, "last_metrics", {}))
                candidate = getattr(constructor, "candidate_graph", None)
                if isinstance(candidate, dict):
                    row["graph"] = candidate
                trace = getattr(constructor, "decision_trace", None)
                if isinstance(trace, list):
                    row["decision_trace"] = trace
                reason = getattr(constructor, "failure_reason", None)
                if isinstance(reason, str):
                    row["failure_reason"] = reason[:500]
            row["construction_ms"] = round((time.perf_counter() - started) * 1000, 1)
            row["planning_ms"] = round(row["preselection_ms"] + row["construction_ms"], 1)
            row["failure_stage"] = "transport_or_construction" if row["transport_valid"] is None else "graph_validation"
            row["error"] = type(exc).__name__
            if row["failure_stage"] == "graph_validation":
                row["validation_error"] = str(exc)[:500]
        pre_cost = selection_metrics.get("estimated_cost_usd")
        construction_cost = row.get("construction_metrics", {}).get("estimated_cost_usd")
        if isinstance(pre_cost, (int, float)):
            row["estimated_cost_usd"] = round(pre_cost + (construction_cost or 0), 8)
            row["cost_estimate_complete"] = isinstance(construction_cost, (int, float))
        rows.append(row)
    return rows


async def _main(args: argparse.Namespace) -> int:
    selected = list(CASES) if args.cases == ["all"] else [case for case in CASES if case.id in args.cases]
    if not selected or len(selected) != len(args.cases) and args.cases != ["all"]:
        raise ValueError("Unknown or duplicate case; use --list-cases")
    # Vault's general utility logs raw transport exceptions at ERROR by default.
    logging.getLogger("backend.core.api.app.utils.secrets_manager").setLevel(logging.CRITICAL)
    secrets = SecretsManager()
    await secrets.initialize()
    providers = args.providers
    keys: dict[str, str] = {}
    try:
        for provider in providers:
            if provider == "jev":
                continue
            key = await secrets.get_secret(f"kv/data/providers/{provider}", "api_key")
            if not key:
                raise RuntimeError(f"Missing {provider} credential")
            keys[provider] = key
        from backend.core.api.app.services.workflow_authoring_preselection import WorkflowAuthoringPreselector
        registry_start = time.perf_counter()
        registry = WorkflowCapabilityRegistry()
        registry_init_ms = round((time.perf_counter() - registry_start) * 1000, 1)
        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
            jev = JevDecisionClient(secrets_manager=secrets, http_client=client)
            warm_start = time.perf_counter()
            preselector = WorkflowAuthoringPreselector(jev_client=jev, registry=registry)
            catalogue_warmup_ms = round((time.perf_counter() - warm_start) * 1000, 1)
            for repeat in range(args.repeats):
                for case in selected:
                    result = await _run_case(case, providers, client, preselector, jev, keys)
                    for row in result:
                        row["repeat"] = repeat + 1
                        print(f"{row['case']:18} {row['provider']:9} graph={row.get('graph_valid', False)!s:5} intent={row.get('intent_match', False)!s:5} {row.get('planning_ms', '-')}ms {row.get('error', '')}", flush=True)
                    rows.extend(result)
        report = {"description": "Shared live preselection; Jev vs GPT-OSS 120B on Groq/Cerebras",
                  "timing_scope": "preselection plus graph construction; excludes identity generation, persistence and execution",
                  "cost_scope": "estimated USD from reported usage and public model prices; not provider invoices",
                  "transport_constraint": "strict capability-derived V2 node/config union; only optional null placeholders omitted before validation",
                  "registry_init_ms": registry_init_ms,
                  "catalogue_warmup_ms": catalogue_warmup_ms,
                  "cases": [asdict(case) for case in selected], "rows": rows}
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"Report: {output}")
        return 0
    finally:
        await secrets.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", default=["all"], help="Case IDs or all")
    parser.add_argument("--providers", nargs="+", choices=["jev", "groq", "cerebras"], default=["jev", "groq", "cerebras"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", default="/tmp/workflow-authoring-comparison.json")
    parser.add_argument("--list-cases", action="store_true")
    args = parser.parse_args()
    if args.list_cases:
        for case in CASES:
            print(case.id)
        return 0
    if not 1 <= args.repeats <= 3:
        parser.error("--repeats must be between 1 and 3")
    try:
        return asyncio.run(_main(args))
    except Exception as exc:
        # Suppress raw provider/Vault exception text.
        print(f"Benchmark setup failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
