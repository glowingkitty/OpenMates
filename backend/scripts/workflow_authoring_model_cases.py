"""Synthetic, read-only semantic cases for the current flat workflow author.

``evaluate`` consumes compiled planner operations, never provider JSON.  Its
checks intentionally complement graph validation: a valid graph can still do
the wrong thing.  No account, workflow, or secret is loaded by this module.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from backend.core.api.app.services.workflow_authoring_compiler import compile_authoring_plan
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
from backend.core.api.app.services.workflow_models import WorkflowGraph


EXISTING_ID = "00000000-0000-4000-8000-000000000381"


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    timezone: str
    expected_capability_ids: tuple[str, ...]
    expected_summary: str
    selected_workflow: dict[str, Any] | None = None


def _original() -> dict[str, Any]:
    """Build a real V2 update target with the production registry/compiler."""
    registry = WorkflowCapabilityRegistry()
    selection = WorkflowPreselection(
        capabilities=[registry.get_capability("weather.forecast")], operation="create",
        check_mode="none", chat_delivery=True, scores={}, metrics={},
    )
    plan = {
        "operation": "create", "title": "Paris morning forecast",
        "description": "Send the daily Paris forecast", "icon": "cloud-rain",
        "schedule": {"type": "daily", "time": "07:00", "timezone": "Europe/Paris"},
        "steps": [
            {"kind": "app", "id": "paris_forecast", "capability": "weather.forecast",
             "input": {"location": "Paris", "days": 1}},
            {"kind": "send", "id": "paris_reply", "title": "Paris forecast",
             "message": [{"text": "Paris forecast: "},
                         {"ref": {"step": "paris_forecast", "field": "results"}}]},
        ],
    }
    graph = compile_authoring_plan(plan, selection, "Europe/Paris")["graph"]
    return {"id": EXISTING_ID, "version": 3, "title": plan["title"],
            "description": plan["description"], "icon": plan["icon"], "graph": graph}


def cases() -> tuple[Case, ...]:
    """Fixed requests and independent outcome summaries for report rows."""
    return (
        Case("headphones_filter",
             "Every Friday at 09:00 Berlin time, search shopping for refurbished noise-cancelling headphones under 150 EUR and send matching products and prices to chat.",
             "Europe/Berlin", ("shopping.search_products",),
             "One Friday 09:00 Berlin shopping search constrained to refurbished noise-cancelling headphones and EUR 150; results reach chat; no Check."),
        Case("corrected_rain",
             "Um every day at 07:00 in Berlin—no, sorry, at 08:30 Lisbon time—check tomorrow's weather in Lisbon. If rain is expected, tell me in chat to take an umbrella; otherwise tell me it should be dry.",
             "Europe/Lisbon", ("weather.forecast",),
             "Daily 08:30 Lisbon; tomorrow's Lisbon forecast; exact rain Check with distinct umbrella and dry chat branches; no Berlin or 07:00."),
        Case("three_city_forecast",
             "Every weekday at 07:30 Berlin time, get today's weather for Berlin, Paris and London. Ask AI to combine all three forecasts into one chat update and say when any city has no forecast.",
             "Europe/Berlin", ("weather.forecast", "ai.ask"),
             "Three today weather actions feed all forecast results into one Ask AI prompt; its answer reaches chat and covers missing forecasts."),
        Case("events_free_text",
             "Every Friday at 16:00 Berlin time, find upcoming AI events in Berlin. Ask AI in free text to summarize those event results for a founder, then send its answer to chat.",
             "Europe/Berlin", ("events.search", "ai.ask"),
             "Friday 16:00 Berlin; events.search results appear as a reference in Ask AI prompt; Ask AI answer reaches chat."),
        Case("nutrition_free_text",
             "Every Sunday at 17:00 Berlin time, search nutrition recipes for high-protein vegetarian dinners. Ask AI in free text to choose three recipes from those search results and explain why, then send its answer to chat.",
             "Europe/Berlin", ("nutrition.search_recipes", "ai.ask"),
             "Sunday 17:00 Berlin; recipe results appear as a reference in Ask AI prompt; answer reaches chat."),
        Case("subjective_news",
             "Every day at 18:00 Berlin time, search news about AI policy. Use an AI check to decide whether anything matters to a small European startup. If yes, send the relevant news to chat; if no, say there is no important update.",
             "Europe/Berlin", ("news.search",),
             "Daily 18:00 Berlin; news results feed an AI Check with distinct yes and no chat messages; no extra Ask AI action."),
        Case("two_creates",
             "Create two separate workflows: every day at 07:00 Lisbon time remind me in chat to stretch, and every weekday at 18:00 Berlin time search AI news and send the results to chat.",
             "Europe/Berlin", ("news.search",),
             "Two creates: daily 07:00 Europe/Lisbon stretch reminder; weekday 18:00 Europe/Berlin AI news search delivered to chat."),
        Case("mixed_create_update",
             "Move my existing Paris morning forecast to 10:00, keeping its Paris weather search and chat message intact. Also create a separate workflow every Friday at 09:00 Berlin time to search refurbished noise-cancelling headphones under 150 EUR and send matches to chat.",
             "Europe/Berlin", ("shopping.search_products",),
             "One update of the owned Paris workflow to 10:00 with its timezone and unrelated nodes intact, plus one new Friday 09:00 Berlin headphone workflow.",
             _original()),
    )


def _nodes(graph: WorkflowGraph, kind: str) -> list[Any]:
    return [node for node in graph.nodes if node.type.value == kind]


def _actions(graph: WorkflowGraph, capability: str) -> list[Any]:
    app, skill = capability.split(".", 1)
    return [node for node in _nodes(graph, "app_skill_action")
            if (node.config.get("app_id"), node.config.get("skill_id")) == (app, skill)]


def _schedule(graph: WorkflowGraph) -> dict[str, Any]:
    triggers = _nodes(graph, "schedule_trigger")
    return triggers[0].config.get("schedule", {}) if len(triggers) == 1 else {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).casefold()


def _has_ref(value: Any, node_id: str, fields: tuple[str, ...]) -> bool:
    source = _json(value)
    return any(re.search(rf"(?:\$nodes\.{re.escape(node_id)}\.output|steps\.{re.escape(node_id)})"
                         rf"\.{re.escape(field)}(?![\w])", source) for field in fields)


def _check_schedule(graph: WorkflowGraph, recurrence: str, time: str, zone: str,
                    weekdays: tuple[str, ...] = ()) -> list[str]:
    actual = _schedule(graph)
    issues = []
    for key, expected in (("type", recurrence), ("time", time), ("timezone", zone)):
        if actual.get(key) != expected:
            issues.append(f"schedule {key}: expected {expected}")
    if weekdays and set(actual.get("weekdays") or ()) != set(weekdays):
        issues.append(f"schedule weekdays: expected {weekdays}")
    return issues


def _delivery_from(graph: WorkflowGraph, source: Any, fields: tuple[str, ...]) -> bool:
    return any(_has_ref(node.config, source.id, fields)
               for node in _nodes(graph, "send_chat_message"))


def _check_ai_chain(graph: WorkflowGraph, capability: str, *, search_terms: tuple[str, ...],
                    prompt_terms: tuple[tuple[str, ...], ...]) -> list[str]:
    sources, asks = _actions(graph, capability), _actions(graph, "ai.ask")
    issues = []
    if not sources:
        issues.append(f"missing {capability}")
    if len(asks) != 1:
        issues.append("expected one Ask AI action")
    if sources and not any(all(term in _json(source.config.get("input")) for term in search_terms)
                           for source in sources):
        issues.append("search input lacks requested subject or location")
    if sources and asks:
        prompt = (asks[0].config.get("input") or {}).get("prompt", "")
        if not any(_has_ref(prompt, source.id, ("results", "events", "recipes")) for source in sources):
            issues.append("Ask AI prompt lacks search result reference")
        for alternatives in prompt_terms:
            if not any(term in prompt.casefold() for term in alternatives):
                issues.append(f"Ask AI prompt lacks requested {alternatives[0]} intent")
        if not _delivery_from(graph, asks[0], ("answer",)):
            issues.append("chat lacks Ask AI answer reference")
    return issues


def _check_headphones(graph: WorkflowGraph) -> list[str]:
    issues = []
    actions = _actions(graph, "shopping.search_products")
    if len(actions) != 1:
        return ["expected one shopping.search_products action"]
    authored = actions[0].config.get("input") or {}
    value = _json(authored)
    for term in ("headphones", "refurbished"):
        if term not in value:
            issues.append(f"shopping input lacks {term}")
    if not re.search(r"noise[\s\-‐‑‒–—]?cancelling", value):
        issues.append("shopping input lacks noise-cancelling")
    requests = authored.get("requests") if isinstance(authored, dict) else None
    if not isinstance(requests, list) or not any(
        isinstance(request, dict) and request.get("max_price") == 150
        and str(request.get("country") or "").strip().upper() == "DE" for request in requests
    ):
        issues.append("shopping request lacks EUR 150 max_price and German marketplace country")
    if _nodes(graph, "check"):
        issues.append("shopping filter became a Check")
    if not _delivery_from(graph, actions[0], ("results", "products")):
        issues.append("shopping results do not reach chat")
    return issues


def _branch_messages(graph: WorkflowGraph, mode: str, words: dict[str, str]) -> list[str]:
    checks = [node for node in _nodes(graph, "check") if node.config.get("mode") == mode]
    if len(checks) != 1:
        return [f"expected one {mode} Check"]
    check = checks[0]
    by_id = {node.id: node for node in graph.nodes}
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.from_node, []).append(edge.to_node)
    issues = []
    branch_sends: dict[str, set[str]] = {}
    for branch, word in words.items():
        starts = [edge.to_node for edge in graph.edges if edge.from_node == check.id and edge.branch == branch]
        if not starts:
            issues.append(f"missing {branch} branch")
            continue
        seen, pending = set(starts), list(starts)
        while pending:
            for child in outgoing.get(pending.pop(), []):
                if child not in seen:
                    seen.add(child)
                    pending.append(child)
        branch_sends[branch] = {node_id for node_id in seen
                                if by_id[node_id].type.value == "send_chat_message"}
        if not any(not word or word in _json(by_id[node_id].config)
                   for node_id in branch_sends[branch]):
            issues.append(f"{branch} branch lacks {word} message")
    if len(branch_sends) == 2:
        for branch, sends in branch_sends.items():
            if not sends - set().union(*(other for label, other in branch_sends.items()
                                         if label != branch)):
                issues.append(f"{branch} branch lacks a distinct chat message")
    return issues


def evaluate(case: Case, operations: list[dict[str, Any]]) -> list[str]:
    """Return semantic mismatches in current compiled planner operations."""
    issues: list[str] = []
    expected_count = 2 if case.id in {"two_creates", "mixed_create_update"} else 1
    if len(operations) != expected_count:
        issues.append(f"expected {expected_count} operations, got {len(operations)}")
    valid: list[tuple[str, dict[str, Any], WorkflowGraph]] = []
    for index, operation in enumerate(operations):
        action = operation.get("action", operation.get("type"))
        if action not in {"create_workflow", "update_workflow"}:
            issues.append(f"operation {index} is not create/update")
            continue
        try:
            graph = WorkflowGraph.model_validate(operation["graph"])
        except (KeyError, ValueError) as exc:
            issues.append(f"operation {index} graph invalid: {type(exc).__name__}")
            continue
        valid.append((action, operation, graph))
    if case.id == "mixed_create_update":
        creates = [item for item in valid if item[0] == "create_workflow"]
        updates = [item for item in valid if item[0] == "update_workflow"]
        if len(creates) != 1 or len(updates) != 1:
            return issues + ["mixed request requires one create and one update"]
        _, update, changed = updates[0]
        original = case.selected_workflow or {}
        if update.get("workflow_id", update.get("target_id")) != original.get("id"):
            issues.append("update targets wrong workflow ID")
        if update.get("expected_record_version") not in (None, original.get("version")):
            issues.append("update uses wrong original version")
        for field in ("title", "description", "icon"):
            if field in update and update[field] != original.get(field):
                issues.append(f"update changed unrelated {field}")
        issues += _check_schedule(changed, "daily", "10:00", "Europe/Paris")
        old = WorkflowGraph.model_validate(original["graph"])
        old_nodes = {node.id: node for node in old.nodes if node.id != old.trigger_node_id}
        new_nodes = {node.id: node for node in changed.nodes}
        if set(new_nodes) != {node.id for node in old.nodes}:
            issues.append("update added or removed unrelated nodes")
        for node_id, old_node in old_nodes.items():
            if node_id not in new_nodes or new_nodes[node_id].model_dump(mode="json") != old_node.model_dump(mode="json"):
                issues.append(f"update changed unrelated node {node_id}")
        if {json.dumps(edge.model_dump(mode="json", by_alias=True), sort_keys=True) for edge in changed.edges} != {
            json.dumps(edge.model_dump(mode="json", by_alias=True), sort_keys=True) for edge in old.edges
        }:
            issues.append("update changed unrelated graph edges")
        graph = creates[0][2]
        issues += _check_schedule(graph, "weekly", "09:00", "Europe/Berlin", ("friday",))
        issues += _check_headphones(graph)
        return issues
    if case.id == "two_creates":
        if len(valid) != 2 or any(action != "create_workflow" for action, _, _ in valid):
            return issues + ["expected two creates"]
        by_clock = {_schedule(graph).get("time"): graph for _, _, graph in valid}
        stretch, news = by_clock.get("07:00"), by_clock.get("18:00")
        if stretch is None or news is None:
            return issues + ["missing distinct 07:00 and 18:00 workflows"]
        issues += _check_schedule(stretch, "daily", "07:00", "Europe/Lisbon")
        if not any("stretch" in _json(node.config) for node in _nodes(stretch, "send_chat_message")):
            issues.append("stretch reminder missing")
        issues += _check_schedule(news, "weekly", "18:00", "Europe/Berlin",
                                  ("monday", "tuesday", "wednesday", "thursday", "friday"))
        sources = _actions(news, "news.search")
        if not sources or not any(_delivery_from(news, source, ("results", "articles")) for source in sources):
            issues.append("news results do not reach chat")
        return issues
    if len(valid) != 1 or valid[0][0] != "create_workflow":
        return issues + ["expected one create"]
    graph = valid[0][2]
    schedules = {
        "headphones_filter": ("weekly", "09:00", ("friday",)),
        "corrected_rain": ("daily", "08:30", ()),
        "three_city_forecast": ("weekly", "07:30", ("monday", "tuesday", "wednesday", "thursday", "friday")),
        "events_free_text": ("weekly", "16:00", ("friday",)),
        "nutrition_free_text": ("weekly", "17:00", ("sunday",)),
        "subjective_news": ("daily", "18:00", ()),
    }
    recurrence, time, weekdays = schedules[case.id]
    issues += _check_schedule(graph, recurrence, time, case.timezone, weekdays)
    if case.id == "headphones_filter":
        issues += _check_headphones(graph)
    elif case.id == "corrected_rain":
        weather = _actions(graph, "weather.forecast")
        if len(weather) != 1:
            issues.append("expected one weather.forecast action")
        else:
            input_value = weather[0].config.get("input") or {}
            if "lisbon" not in _json(input_value) or "berlin" in _json(input_value):
                issues.append("weather location did not resolve to Lisbon")
            for field in ("start_date", "end_date"):
                if not isinstance(input_value.get(field), dict) or input_value[field].get("$date") != "tomorrow":
                    issues.append(f"weather {field} lacks tomorrow runtime date")
        if "07:00" in _json([node.config for node in graph.nodes]):
            issues.append("superseded 07:00 remains")
        issues += _branch_messages(graph, "exact", {"yes": "umbrella", "no": "dry"})
        checks = [node for node in _nodes(graph, "check") if node.config.get("mode") == "exact"]
        if checks and weather:
            predicate = checks[0].config.get("predicate") or {}
            operands = (predicate.get("left"), predicate.get("right"))
            if predicate.get("op") != "eq" or not any(operand is True for operand in operands) or not any(
                _has_ref(operand, weather[0].id, ("rain_expected",)) for operand in operands
            ):
                issues.append("exact Check does not compare forecast rain_expected to true")
    elif case.id == "three_city_forecast":
        weather, asks = _actions(graph, "weather.forecast"), _actions(graph, "ai.ask")
        if len(asks) != 1:
            issues.append("expected one Ask AI action")
        for city in ("berlin", "paris", "london"):
            city_actions = [node for node in weather if city in _json((node.config.get("input") or {}).get("location"))]
            if not city_actions:
                issues.append(f"missing {city} weather action")
            for node in city_actions:
                value = node.config.get("input") or {}
                if not ((isinstance(value.get("start_date"), dict) and value["start_date"].get("$date") == "today" and
                         isinstance(value.get("end_date"), dict) and value["end_date"].get("$date") == "today") or value.get("days") == 1):
                    issues.append(f"{city} weather is not today")
                if asks and not _has_ref((asks[0].config.get("input") or {}).get("prompt"), node.id,
                                         ("results", "forecast_days")):
                    issues.append(f"Ask AI prompt lacks {city} forecast results")
        if asks:
            prompt = (asks[0].config.get("input") or {}).get("prompt", "")
            if not any(word in prompt.casefold() for word in ("missing", "unavailable", "no forecast", "empty")):
                issues.append("Ask AI prompt lacks missing-forecast instruction")
            if not _delivery_from(graph, asks[0], ("answer",)):
                issues.append("chat lacks Ask AI answer")
    elif case.id in {"events_free_text", "nutrition_free_text"}:
        if case.id == "events_free_text":
            issues += _check_ai_chain(graph, "events.search", search_terms=("ai", "berlin"),
                                      prompt_terms=(("summar",), ("founder", "startup")))
        else:
            issues += _check_ai_chain(graph, "nutrition.search_recipes",
                                      search_terms=("protein", "vegetarian"),
                                      prompt_terms=(("three", "3"), ("explain", "why")))
    elif case.id == "subjective_news":
        news = _actions(graph, "news.search")
        if not news:
            issues.append("missing news.search")
        if _actions(graph, "ai.ask"):
            issues.append("unrequested Ask AI action")
        issues += _branch_messages(graph, "ai", {"yes": "", "no": "no important"})
        checks = [node for node in _nodes(graph, "check") if node.config.get("mode") == "ai"]
        if news and checks and not any(_has_ref(checks[0].config, node.id, ("results", "articles")) for node in news):
            issues.append("AI Check lacks news results reference")
    return issues
