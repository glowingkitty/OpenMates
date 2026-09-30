"""Live, non-persistent comparison of Workflow V2 authoring after shared selection.

Run inside the API container, for example::

    python -m backend.scripts.benchmark_workflow_authoring --output /tmp/workflow-authoring.json

This is a paid, opt-in engineering benchmark. It never saves or executes graphs.
Its timings exclude identity generation, persistence and execution. A strict
transport schema constrains the graph envelope; node config is encoded as a
JSON string and receives the full Workflow validators after decoding.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
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
NODE_TYPES = [
    "schedule_trigger", "manual_trigger", "app_skill_action", "check",
    "send_chat_message", "end",
]


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


CASES = (
    Case("rain_if", "Every day at 08:00 in Berlin, check today's weather in Berlin. If rain is expected, send me a chat message to take an umbrella; otherwise send me a chat message that it should be dry.", ("weather.forecast",), ("Berlin", "umbrella"), check_mode="exact", branch_labels=("yes", "no"), action_literals=("Berlin",), branch_words=(("yes", "umbrella"), ("no", "dry"))),
    Case("weather_cities", "Every weekday at 07:30 Berlin time, get today's weather for Berlin, Paris and London and send the forecasts in one chat message, including a message if a city has no forecast.", ("weather.forecast",), ("Berlin", "Paris", "London"), "weekly", "07:30", ("monday", "tuesday", "wednesday", "thursday", "friday"), min_actions=3, min_variable_refs=1, action_literals=("Berlin", "Paris", "London"), require_missing_fallback=True),
    Case("web_search", "Every Monday at 09:00 Berlin time, search the web for recent open source database releases and send the results to my chat.", ("web.search",), ("open source database",), "weekly", "09:00", ("monday",), min_variable_refs=1, action_literals=("open source database",)),
    Case("shopping_price", "Every day at 10:00 Berlin time, search shopping for a refurbished ThinkPad T14 under 700 EUR and send matching products and prices to chat.", ("shopping.search_products",), ("ThinkPad T14", "700"), time="10:00", min_variable_refs=1, action_literals=("ThinkPad T14", "700")),
    Case("events_summary", "Every Friday at 16:00 Berlin time, find upcoming AI events in Berlin, ask AI to summarize the results, and send the summary to my chat.", ("events.search", "ai.ask"), ("Berlin", "AI"), "weekly", "16:00", ("friday",), min_actions=2, min_variable_refs=2, action_literals=("Berlin",)),
    Case("subjective_check", "Every day at 18:00 Berlin time, search news about AI policy. Use an AI check to decide if anything is important for a small European startup; if yes, send the relevant news to chat, otherwise say there is no important update.", ("news.search",), ("AI policy", "European startup"), time="18:00", check_mode="ai", branch_labels=("yes", "no"), min_variable_refs=1, action_literals=("AI policy",), branch_words=(("no", "no important"),)),
)


def _transport_schema() -> dict[str, Any]:
    node = {"type": "object", "additionalProperties": False, "required": ["id", "type", "title", "config_json"], "properties": {
        "id": {"type": "string"}, "type": {"type": "string", "enum": NODE_TYPES},
        "title": {"type": ["string", "null"]}, "config_json": {"type": "string"},
    }}
    edge = {"type": "object", "additionalProperties": False, "required": ["from", "to", "branch"], "properties": {
        "from": {"type": "string"}, "to": {"type": "string"},
        "branch": {"type": ["string", "null"], "enum": [None, "yes", "no", "unsure", "default"]},
    }}
    return {"type": "object", "additionalProperties": False,
            "required": ["version", "trigger_node_id", "nodes", "edges"],
            "properties": {"version": {"type": "integer", "enum": [2]},
                           "trigger_node_id": {"type": ["string", "null"]},
                           "nodes": {"type": "array", "items": node},
                           "edges": {"type": "array", "items": edge}}}


def decode_transport(raw: dict[str, Any]) -> dict[str, Any]:
    """Decode only the constrained envelope; all node semantics remain validated."""
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list):
        raise ValueError("Transport is not a graph object")
    graph = {key: raw[key] for key in ("version", "trigger_node_id", "edges")}
    graph["nodes"] = []
    for node in raw["nodes"]:
        config = json.loads(node["config_json"])
        if not isinstance(config, dict):
            raise ValueError("Node config must be a JSON object")
        graph["nodes"].append({"id": node["id"], "type": node["type"],
                               "title": node.get("title"), "config": config})
    return graph


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


def oracle(graph: WorkflowGraph, case: Case) -> list[str]:
    """Independent, conservative intent checks; no planner decisions are used."""
    issues: list[str] = []
    actions = [n for n in graph.nodes if n.type == WorkflowNodeType.APP_SKILL_ACTION]
    capabilities = [f"{n.config.get('app_id')}.{n.config.get('skill_id')}" for n in actions]
    for required in case.required_capabilities:
        if required not in capabilities:
            issues.append(f"missing capability {required}")
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
    checks = [n for n in graph.nodes if n.type == WorkflowNodeType.CHECK]
    if case.check_mode and not any(n.config.get("mode") == case.check_mode for n in checks):
        issues.append(f"missing {case.check_mode} check")
    if case.require_missing_fallback:
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
            if not branch_chats[label]:
                issues.append(f"{label} branch has no chat message")
        for label, chats in branch_chats.items():
            exclusive = chats - set().union(*(other for other_label, other in branch_chats.items()
                                              if other_label != label))
            if not exclusive:
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


def _prompt(case: Case, selection: Any) -> str:
    context = selection.context()
    return (
        "Construct one executable Workflow V2 graph for the user request. "
        "Use exactly the selected app skill contracts; never invent a capability or field. "
        "Return only the required JSON envelope. config_json must contain a JSON object string. "
        "Allowed node types: schedule_trigger, manual_trigger, app_skill_action, check, "
        "send_chat_message, end. Use a schedule_trigger with config.schedule type daily or weekly, "
        "time HH:MM, timezone IANA and weekdays for weekly. app_skill_action config has "
        "app_id, skill_id and input matching its selected schema. Check config uses mode exact "
        "with predicate {left,op,right}, or mode ai with question and selected_inputs. "
        "Check edges use branch yes/no/unsure; preserve both branches when requested. "
        "An AI check question and an ai.ask prompt must include an inline {{ $nodes.ID.output.FIELD }} "
        "variable from the earlier data being evaluated or summarized, even when selected_inputs are set. "
        "Relative dates use {\"$date\":\"today\" or \"tomorrow\" or \"next_seven_days_start\" or \"next_seven_days_end\","
        "\"format\":\"date\" or \"datetime\"} as runtime input values, never a frozen literal date. "
        "Message blocks use {id: stable_id, source: '$nodes.ID.output.FIELD'} with an object/array output. "
        "Use $nodes.<id>.output.<declared_field> or {{steps.<id>.<declared_field>}} "
        "for dataflow. send_chat_message config requires title and message or blocks; "
        "refer to prior action output in authored messages. Build a connected acyclic graph. "
        "Do not insert account IDs, credentials, runtime grants, or guessed values. "
        f"Selected context: {json.dumps(context, ensure_ascii=False, separators=(',', ':'))}\n"
        f"User request: {case.text}"
    )


async def _model_construct(client: httpx.AsyncClient, provider: str, key: str,
                           case: Case, selection: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    url, model = PROVIDERS[provider]
    body = {"model": model, "temperature": 0, "max_completion_tokens": 4096,
            "messages": [{"role": "user", "content": _prompt(case, selection)}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "workflow_graph", "strict": True, "schema": _transport_schema()}}}
    if provider == "groq":
        body["reasoning_effort"] = "low"
    response = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json=body)
    # Never include provider response bodies or exception strings: they may echo secrets.
    if response.status_code != 200:
        raise ValueError(f"{provider} HTTP {response.status_code}")
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
    for key in ("jev_calls", "input_tokens", "output_tokens", "estimated_cost_usd", "usage", "finish_reason"):
        value = metrics.get(key)
        if key == "finish_reason" and isinstance(value, str):
            safe[key] = value
        elif (filtered := numeric_tree(value)) is not None:
            safe[key] = filtered
    return safe


async def _run_case(case: Case, providers: list[str], secrets: SecretsManager,
                    client: httpx.AsyncClient, registry: WorkflowCapabilityRegistry,
                    keys: dict[str, str]) -> list[dict[str, Any]]:
    from backend.core.api.app.services.workflow_authoring_preselection import WorkflowAuthoringPreselector
    from backend.core.api.app.services.workflow_jev_constructor import WorkflowJevConstructor

    jev = JevDecisionClient(secrets_manager=secrets, http_client=client)
    preselector = WorkflowAuthoringPreselector(jev_client=jev, registry=registry)
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
                raw = decode_transport(envelope)
                row["transport_valid"] = True
            row["construction_ms"] = round((time.perf_counter() - started) * 1000, 1)
            row["planning_ms"] = round(row["preselection_ms"] + row["construction_ms"], 1)
            row["construction_metrics"] = _safe_metrics(metrics)
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
            if constructor is not None:
                row["construction_metrics"] = _safe_metrics(getattr(constructor, "last_metrics", {}))
                candidate = getattr(constructor, "candidate_graph", None)
                if isinstance(candidate, dict):
                    row["graph"] = candidate
            row["construction_ms"] = round((time.perf_counter() - started) * 1000, 1)
            row["planning_ms"] = round(row["preselection_ms"] + row["construction_ms"], 1)
            row["failure_stage"] = "transport_or_construction" if row["transport_valid"] is None else "graph_validation"
            row["error"] = type(exc).__name__
            if row["failure_stage"] == "graph_validation":
                row["validation_error"] = str(exc)[:500]
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
        registry = WorkflowCapabilityRegistry()
        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
            for repeat in range(args.repeats):
                for case in selected:
                    result = await _run_case(case, providers, secrets, client, registry, keys)
                    for row in result:
                        row["repeat"] = repeat + 1
                        print(f"{row['case']:18} {row['provider']:9} graph={row.get('graph_valid', False)!s:5} intent={row.get('intent_match', False)!s:5} {row.get('planning_ms', '-')}ms {row.get('error', '')}", flush=True)
                    rows.extend(result)
        report = {"description": "Shared live preselection; Jev vs GPT-OSS 120B on Groq/Cerebras",
                  "timing_scope": "preselection plus graph construction; excludes identity generation, persistence and execution",
                  "cost_scope": "provider reported usage and Jev estimates where available; not independently billed cost",
                  "transport_constraint": "strict JSON schema envelope; config_json decoded before full V2 validation",
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
