"""Synthetic, read-only semantic cases for the current flat workflow author.

``evaluate`` consumes compiled planner operations, never provider JSON.  Its
checks intentionally complement graph validation: a valid graph can still do
the wrong thing.  No account, workflow, or secret is loaded by this module.
"""

from __future__ import annotations

import json
import math
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
    expectations: tuple[dict[str, Any], ...] = ()
    language: str = "en"


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


def cases(suite: str = 'baseline') -> tuple[Case, ...]:
    """Keep the original eight by default; expanded adds sixteen frozen cases."""
    if suite not in {'baseline', 'expanded'}:
        raise ValueError('Unknown workflow benchmark suite: ' + suite)
    baseline = (
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
    return baseline + _expanded_cases() if suite == 'expanded' else baseline


def _nodes(graph: WorkflowGraph, kind: str) -> list[Any]:
    return [node for node in graph.nodes if node.type.value == kind]


def _actions(graph: WorkflowGraph, capability: str) -> list[Any]:
    app, skill = capability.split(".", 1)
    return [node for node in _nodes(graph, "app_skill_action")
            if (node.config.get("app_id"), node.config.get("skill_id")) == (app, skill)]


def _schedule(graph: WorkflowGraph) -> dict[str, Any]:
    triggers = _nodes(graph, "schedule_trigger")
    if len(triggers) == 1:
        return triggers[0].config.get("schedule", {})
    manual = _nodes(graph, "manual_trigger")
    return {"type": "manual"} if len(manual) == 1 and manual[0].id == graph.trigger_node_id else {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).casefold()


def _has_ref(value: Any, node_id: str, fields: tuple[str, ...]) -> bool:
    source = json.dumps(value, ensure_ascii=False)
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


def _evaluate_legacy(case: Case, operations: list[dict[str, Any]]) -> list[str]:
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


LEGACY_CASE_IDS = frozenset({
    'headphones_filter', 'corrected_rain', 'three_city_forecast', 'events_free_text',
    'nutrition_free_text', 'subjective_news', 'two_creates', 'mixed_create_update',
})
CORPUS_VERSION = 'workflow-native-quality-24-v1'


def _rx(pattern: str) -> dict[str, str]:
    return {'$regex': pattern}


def _flow(schedule: dict[str, Any], roles: dict[str, Any], sends: list[dict[str, Any]],
          check: dict[str, Any] | None = None, *, update: bool = False) -> dict[str, Any]:
    return {'action': 'update_workflow' if update else 'create_workflow', 'schedule': schedule,
            'roles': roles, 'sends': sends, 'check': check, 'preserve_existing': update}


def _schedule_rule(kind: str, clock: str, zone: str, *weekdays: str) -> dict[str, Any]:
    return {'type': kind, 'time': clock, 'timezone': zone,
            **({'weekdays': list(weekdays)} if weekdays else {})}


def _source(capability: str, subset: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return {'capability': capability, 'input_subset': subset or {}, **kwargs}


def _send(*patterns: str, refs: tuple[str, ...] = (), branch: str | None = None) -> dict[str, Any]:
    return {'patterns': list(patterns), 'refs': list(refs), 'branch': branch}


def _ask(*refs: str, patterns: tuple[str, ...]) -> dict[str, Any]:
    return _source('ai.ask', refs=list(refs), prompt_patterns=list(patterns))


def _expanded_cases() -> tuple[Case, ...]:
    """Independent explicit requirements, frozen before any model comparison."""
    manual = {'type': 'manual'}
    weekday = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')
    return (
        Case('en_manual_lunch_choices',
             'Create a manually triggered workflow, without a schedule: search nutrition recipes for high-protein vegetarian lunches. '
             'Ask AI to choose exactly two recipes from those results and explain the choice, then send only its answer to chat. Do not add checks or other actions.',
             'Europe/London', ('nutrition.search_recipes', 'ai.ask'),
             'Manual vegetarian high-protein lunch search, two-recipe explanation from result references, one answer delivery; no schedule/check.',
             expectations=(_flow(manual, {
                 'recipes': _source('nutrition.search_recipes', {'requests': [{'query': _rx(r'lunch|mittag'),
                     'health': ['vegetarian'], 'diet': ['high-protein']}]}),
                 'answer': _ask('recipes', patterns=(r'\b(two|2|zwei)\b', r'explain|why|begr.nd|warum')),
             }, [_send(refs=('answer',))]),)),
        Case('de_two_city_weather',
             'Erstelle einen Workflow für jeden Tag um 06:45 Uhr Wiener Zeit. Hole die heutige Wettervorhersage für Wien und Graz. '
             'Ask AI soll beide Ergebnisse vergleichen und sagen, welche Stadt heute wärmer ist; fehlen Daten, soll es das nennen. '
             'Sende nur diese Antwort in den Chat, ohne Check oder weitere Aktionen.',
             'Europe/Vienna', ('weather.forecast', 'ai.ask'),
             'Daily 06:45 Vienna; two today forecasts, relative temperature comparison and missing-data handling, one answer delivery.',
             expectations=(_flow(_schedule_rule('daily', '06:45', 'Europe/Vienna'), {
                 'vienna': _source('weather.forecast', {'location': _rx(r'Wien|Vienna')}, day='today'),
                 'graz': _source('weather.forecast', {'location': _rx(r'Graz')}, day='today'),
                 'answer': _ask('vienna', 'graz', patterns=(r'w.rmer|warm|temperatur', r'fehl|missing|unavailable|no data')),
             }, [_send(refs=('answer',))]),), language='de'),
        Case('en_edit_weekly_keep_paris',
             'Edit the selected Paris morning forecast only: replace its daily schedule with Tuesdays and Thursdays at 10:15. '
             'Keep its existing Paris timezone, workflow ID, title and every weather/chat step unchanged. Do not create another workflow.',
             'America/New_York', ('weather.forecast',),
             'One owned schedule-only update; Tue/Thu 10:15 Europe/Paris; original ID, metadata, nontrigger nodes and edges retained.',
             _original(), (_flow(_schedule_rule('weekly', '10:15', 'Europe/Paris', 'tuesday', 'thursday'), {}, [], update=True),)),
        Case('de_edit_clock_keep_identity',
             'Ändere beim ausgewählten Paris-Morgenwetter ausschließlich die Uhrzeit auf 08:40. '
             'Täglich und die bestehende Pariser Zeitzone beibehalten, auch wenn mein Browser Berlin verwendet. '
             'Titel, ID, Wetterabfrage und Chatnachricht dürfen sich nicht ändern; keine Kopie erstellen.',
             'Europe/Berlin', ('weather.forecast',),
             'One daily 08:40 Europe/Paris edit preserving original ID and complete unrelated definition.',
             _original(), (_flow(_schedule_rule('daily', '08:40', 'Europe/Paris'), {}, [], update=True),), 'de'),
        Case('en_battery_news_no_ai',
             'Every Monday and Thursday at 13:05 Lisbon time, search news for battery recycling and send the search results to chat. '
             'Use no Ask AI, no Check and no other action. Do not restrict the start to a particular calendar date.',
             'Europe/Lisbon', ('news.search',),
             'Mon/Thu 13:05 Lisbon news search for battery recycling, direct result delivery, no invented start or AI/check.',
             expectations=(_flow(_schedule_rule('weekly', '13:05', 'Europe/Lisbon', 'monday', 'thursday'), {
                 'news': _source('news.search', {'requests': [{'query': _rx(r'battery.*recycl|recycl.*battery')}]})
             }, [_send(refs=('news',))]),)),
        Case('de_backpack_self_correction',
             'Jeden Samstag um 10:40 Berliner Zeit bei Shopping nach roten Wanderrucksäcken suchen, nein, nach blauen. '
             'Maximal 95 Euro, deutscher Amazon-Marktplatz. Keine gebrauchten oder generalüberholten Angebote; '
             'diese Anforderungen in den Sucheingaben behalten. Ergebnisse direkt im Chat zeigen, kein Check und kein Ask AI.',
             'Europe/Berlin', ('shopping.search_products',),
             'Saturday 10:40 Berlin, blue hiking backpacks EUR95 DE, excludes used/refurbished in search intent, direct delivery.',
             expectations=(_flow(_schedule_rule('weekly', '10:40', 'Europe/Berlin', 'saturday'), {
                 'products': _source('shopping.search_products', {'requests': [{'country': 'de', 'max_price': 95}]},
                     input_patterns=[r'blue|blau', r'hik|wander', r'backpack|rucks',
                                     r'no used|not used|exclude.*used|keine gebrauchten|nicht gebraucht|new|neu',
                                     r'no refurbished|not refurbished|exclude.*refurbish|keine.*general.berhol|new|neu'],
                     input_forbidden=[r'\bred\b|\brot(?:e|en)?\b']),
             }, [_send(refs=('products',))]),), language='de'),
        Case('en_exact_false_rain',
             'Create a manually triggered workflow. Get tomorrow’s Boston weather. Use an exact deterministic Check: '
             'rain_expected equals false. If true, send exactly DRY to chat; if false, send exactly WET. '
             'No AI judgment, no Ask AI, and no other messages or actions.',
             'America/New_York', ('weather.forecast',),
             'Manual Boston tomorrow; exact rain_expected==false; yes DRY, no WET, distinct branches and no extra action.',
             expectations=(_flow(manual, {'weather': _source('weather.forecast', {'location': _rx(r'Boston')}, day='tomorrow')},
                 [_send(r'^dry$', branch='yes'), _send(r'^wet$', branch='no')],
                 {'mode': 'exact', 'op': 'eq', 'source': 'weather', 'field': 'rain_expected', 'right': False}),)),
        Case('de_ai_check_three_paths',
             'Jeden Mittwoch um 19:00 Berliner Zeit Nachrichten zur Energiepolitik suchen. Ein AI Check soll anhand dieser '
             'Suchergebnisse beurteilen, ob etwas für Mieter wichtig ist. Bei Ja genau WICHTIG mit den Ergebnissen im Chat senden; '
             'bei Nein nur KEIN UPDATE; bei Unsicher nur UNSICHER. Kein Ask-AI-Schritt und keine anderen Aktionen.',
             'Europe/Berlin', ('news.search',),
             'Wednesday 19:00; tenant relevance AI Check over news results; distinct WICHTIG+results / KEIN UPDATE / UNSICHER branches.',
             expectations=(_flow(_schedule_rule('weekly', '19:00', 'Europe/Berlin', 'wednesday'), {
                 'news': _source('news.search', {'requests': [{'query': _rx(r'Energiepolitik|energy policy')}]}),
             }, [_send(r'wichtig', refs=('news',), branch='yes'), _send(r'^kein update$', branch='no'),
                 _send(r'^unsicher$', branch='unsure')],
                 {'mode': 'ai', 'sources': ['news'], 'question_patterns': [r'mieter|tenant', r'wichtig|important|relevant']}),), language='de'),
        Case('en_exact_shared_continuation',
             'Every day at 12:00 UTC get tomorrow’s Madrid weather. Use an exact Check of rain_expected equals true. '
             'On the yes branch send exactly RAIN; on the no branch send exactly DRY. After either branch, send exactly CHECK COMPLETE once. '
             'No AI judgment, no Ask AI and no other actions.',
             'UTC', ('weather.forecast',),
             'Daily UTC noon; rain true Check, exclusive RAIN/DRY messages and one shared CHECK COMPLETE continuation.',
             expectations=(_flow(_schedule_rule('daily', '12:00', 'UTC'), {
                 'weather': _source('weather.forecast', {'location': _rx(r'Madrid')}, day='tomorrow'),
             }, [_send(r'^rain$', branch='yes'), _send(r'^dry$', branch='no'),
                 _send(r'^check complete$', branch='shared')],
                 {'mode': 'exact', 'op': 'eq', 'source': 'weather', 'field': 'rain_expected', 'right': True}),)),
        Case('de_two_zones_recipe_reminder',
             'Erstelle zwei getrennte Workflows: täglich um 09:00 Berliner Zeit nur die Chat-Erinnerung TRINKWASSER senden. '
             'Der zweite soll samstags um 16:00 Lissaboner Zeit vegetarische Abendessen-Rezepte suchen und die Ergebnisse '
             'direkt in den Chat senden. Keine Checks, kein Ask AI, keine weiteren Aktionen.',
             'Europe/Berlin', ('nutrition.search_recipes',),
             'Two creates: Berlin daily water reminder; Lisbon Saturday vegetarian-dinner search with direct delivery; no AI/check.',
             expectations=(
                 _flow(_schedule_rule('daily', '09:00', 'Europe/Berlin'), {}, [_send(r'^trinkwasser$')]),
                 _flow(_schedule_rule('weekly', '16:00', 'Europe/Lisbon', 'saturday'), {
                     'recipes': _source('nutrition.search_recipes', {'requests': [{'health': ['vegetarian'],
                         'query': _rx(r'dinner|abend')}]})
                 }, [_send(refs=('recipes',))])), language='de'),
        Case('en_mixed_edit_glutenfree',
             'Move only the selected Paris forecast’s daily clock to 09:25, preserving its Paris timezone, ID, metadata and steps. '
             'Also create one separate workflow: Sundays at 17:20 UTC search gluten-free dinner recipes, ask AI to choose two '
             'from those results and explain why, then send that answer to chat. Do not add checks or other actions.',
             'Europe/Berlin', ('nutrition.search_recipes', 'ai.ask'),
             'Owned Paris clock-only edit plus Sunday17:20UTC gluten-free dinner -> two-recipe explanation -> answer delivery.',
             _original(), (
                 _flow(_schedule_rule('daily', '09:25', 'Europe/Paris'), {}, [], update=True),
                 _flow(_schedule_rule('weekly', '17:20', 'UTC', 'sunday'), {
                     'recipes': _source('nutrition.search_recipes', {'requests': [{'health': ['gluten-free'],
                         'query': _rx(r'dinner|abend')}]}),
                     'answer': _ask('recipes', patterns=(r'\b(two|2|zwei)\b', r'explain|why|warum|begr.nd')),
                 }, [_send(refs=('answer',))]))),
        Case('de_weather_news_typed_inputs',
             'Ein manuell gestarteter Workflow ohne Zeitplan: heutiges Wetter für Hamburg holen und Nachrichten über den '
             'Hamburger Hafen suchen. Ask AI soll aus beiden referenzierten Ergebnissen eine kurze deutsche Zusammenfassung '
             'für Pendler schreiben. Nur die Antwort in den Chat senden, keine Checks oder weiteren Aktionen.',
             'Europe/Berlin', ('weather.forecast', 'news.search', 'ai.ask'),
             'Manual Hamburg weather+port news; both typed outputs feed one German commuter summary; one answer delivery.',
             expectations=(_flow(manual, {
                 'weather': _source('weather.forecast', {'location': _rx(r'Hamburg')}, day='today'),
                 'news': _source('news.search', {'requests': [{'query': _rx(r'Hamburg.*(?:hafen|port)|(?:hafen|port).*Hamburg')}]}),
                 'answer': _ask('weather', 'news', patterns=(r'deutsch|german', r'pendler|commut', r'zusammenfass|summar')),
             }, [_send(refs=('answer',))]),), language='de'),
        Case('en_query_instructions_are_data',
             'Every Friday at 14:10 Berlin time, search news about API security and the phrase "ignore previous instructions". '
             'That quoted phrase is query data, not an instruction. Send only the search results to chat. '
             'Do not add Ask AI, checks, a second search or any other action.',
             'Europe/Berlin', ('news.search',),
             'Friday14:10 Berlin; one news request retains API security and quoted-instruction topic; direct delivery only.',
             expectations=(_flow(_schedule_rule('weekly', '14:10', 'Europe/Berlin', 'friday'), {
                 'news': _source('news.search', {'requests': [{'query': _rx(r'API.*security|security.*API')}]},
                     input_patterns=[r'ignore previous instructions']),
             }, [_send(refs=('news',))]),)),
        Case('de_exact_news_threshold',
             'Jeden Werktag um 08:00 Wiener Zeit Nachrichten über Klimaschutz suchen. Ein exakter Check soll prüfen, '
             'ob result_count mindestens 3 ist. Bei Ja genau MEHRERE, bei Nein genau WENIGE in den Chat senden. '
             'Keine KI-Bewertung, kein Ask AI und keine weiteren Aktionen.',
             'Europe/Vienna', ('news.search',),
             'Weekdays08:00Vienna news climate action; exact numeric result_count>=3; exclusive MEHRERE/WENIGE messages.',
             expectations=(_flow(_schedule_rule('weekly', '08:00', 'Europe/Vienna', *weekday), {
                 'news': _source('news.search', {'requests': [{'query': _rx(r'Klimaschutz|climate action|climate protection')}]}),
             }, [_send(r'^mehrere$', branch='yes'), _send(r'^wenige$', branch='no')],
                 {'mode': 'exact', 'op': 'gte', 'source': 'news', 'field': 'result_count', 'right': 3}),), language='de'),
        Case('en_two_product_budgets',
             'Every Wednesday at 07:50 Lisbon time, use one Shopping action containing two search requests: '
             'a USB-C dock for at most 120 EUR and an HDMI cable for at most 20 EUR, both on the German Amazon marketplace. '
             'Send both result groups in one chat message. No Ask AI, no Check and no additional searches.',
             'Europe/Lisbon', ('shopping.search_products',),
             'Wednesday07:50Lisbon one shopping action with exactly two DE requests and separate EUR120/EUR20 ceilings; one result delivery.',
             expectations=(_flow(_schedule_rule('weekly', '07:50', 'Europe/Lisbon', 'wednesday'), {
                 'products': _source('shopping.search_products', {'requests': [
                     {'query': _rx(r'USB.?C.*dock|dock.*USB.?C'), 'country': 'de', 'max_price': 120},
                     {'query': _rx(r'HDMI.*cable|cable.*HDMI'), 'country': 'de', 'max_price': 20},
                 ]}),
             }, [_send(refs=('products',))]),)),
        Case('de_negated_reminder_schedule',
             'Erstelle nur eine Chat-Erinnerung: montags um 07:00, nein, mittwochs und freitags um 18:35 Berliner Zeit. '
             'Der Nachrichtentext soll genau "Rechnung Zoë 127 Euro" lauten. Kein Startdatum festlegen. '
             'Keine Suche, kein Ask AI, kein Check und keine weiteren Nachrichten.',
             'Europe/Berlin', (),
             'Wednesday+Friday18:35Berlin one exact Unicode/name/amount reminder; no superseded time/day/startdate or extra action.',
             expectations=(_flow(_schedule_rule('weekly', '18:35', 'Europe/Berlin', 'wednesday', 'friday'), {},
                 [_send(r'^rechnung zoë 127 euro$')]),), language='de'),
    )


def _matches(actual: Any, expected: Any) -> bool:
    """Match semantic subsets while requiring the exact number of list requests."""
    if isinstance(expected, dict):
        if set(expected) == {'$regex'}:
            return isinstance(actual, str) and re.search(expected['$regex'], actual, re.I) is not None
        return isinstance(actual, dict) and all(key in actual and _matches(actual[key], value)
                                                for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        # Lists such as provider requests and health tags are order independent;
        # consume each candidate once, so duplicates cannot satisfy two rules.
        remaining = list(actual)
        for wanted in expected:
            index = next((i for i, value in enumerate(remaining) if _matches(value, wanted)), None)
            if index is None:
                return False
            remaining.pop(index)
        return True
    if isinstance(expected, str):
        return isinstance(actual, str) and actual.casefold() == expected.casefold()
    return type(actual) is type(expected) and actual == expected


def _preserved_update(case: Case, operation: dict[str, Any], graph: WorkflowGraph) -> list[str]:
    original = case.selected_workflow or {}
    issues = []
    if operation.get('workflow_id', operation.get('target_id')) != original.get('id'):
        issues.append('update targets wrong workflow ID')
    if operation.get('expected_record_version') not in (None, original.get('version')):
        issues.append('update uses wrong original version')
    for key in ('title', 'description', 'icon'):
        if key in operation and operation[key] != original.get(key):
            issues.append('update changed unrelated ' + key)
    before = WorkflowGraph.model_validate(original['graph'])
    old = before.model_dump(mode='json', by_alias=True)
    new = graph.model_dump(mode='json', by_alias=True)
    # Only schedule config is authorized to change; IDs, other trigger fields,
    # nontrigger nodes, edges, variables, limits and layout must be preserved.
    for data in (old, new):
        for node in data['nodes']:
            if node['id'] == before.trigger_node_id:
                node['config'].pop('schedule', None)
        data['nodes'].sort(key=lambda node: node['id'])
        data['edges'].sort(key=lambda edge: json.dumps(edge, sort_keys=True))
    if old != new:
        issues.append('schedule-only edit changed unrelated graph state')
    return issues


def _branch_send_sets(graph: WorkflowGraph, check_id: str) -> dict[str, set[str]]:
    by_id = {node.id: node for node in graph.nodes}
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.from_node, []).append(edge.to_node)
    result = {}
    for branch in ('yes', 'no', 'unsure'):
        pending = [edge.to_node for edge in graph.edges if edge.from_node == check_id and edge.branch == branch]
        seen = set(pending)
        while pending:
            for child in outgoing.get(pending.pop(), []):
                if child not in seen:
                    seen.add(child)
                    pending.append(child)
        if seen:
            result[branch] = {node_id for node_id in seen if by_id[node_id].type.value == 'send_chat_message'}
    continuation = [edge.to_node for edge in graph.edges
                    if edge.from_node == check_id and edge.branch == 'default']
    seen, pending = set(continuation), list(continuation)
    while pending:
        for child in outgoing.get(pending.pop(), []):
            if child not in seen:
                seen.add(child)
                pending.append(child)
    shared = {node_id for node_id in seen if by_id[node_id].type.value == 'send_chat_message'}
    for branch in result:
        result[branch] |= shared
    return result


def _exact_comparison_matches(predicate: dict[str, Any], rule: dict[str, Any], source: Any) -> bool:
    """Recognize equivalent scalar comparisons without requiring provider syntax."""
    left, right = predicate.get('left'), predicate.get('right')
    left_ref = bool(source and _has_ref(left, source.id, (rule['field'],)))
    right_ref = bool(source and _has_ref(right, source.id, (rule['field'],)))
    if left_ref == right_ref:
        return False
    literal = right if left_ref else left
    if isinstance(rule['right'], bool):
        if not isinstance(literal, bool) or predicate.get('op') not in {'eq', 'neq'}:
            return False
        domain = [False, True]
    else:
        if isinstance(literal, bool) or not isinstance(literal, (int, float)) or not math.isfinite(literal):
            return False
        # result_count is an integer >=0; include all comparator transition
        # boundaries, so count>2 and 3<=count are equivalent to count>=3.
        domain = sorted({0, 1, 2, 3, 4, 100, *(
            max(0, math.floor(bound) + offset) for bound in (literal, rule['right']) for offset in (-1, 0, 1, 2))})
    def compare(op, first, second):
        return {'eq': lambda: first == second, 'neq': lambda: first != second,
                'gt': lambda: first > second, 'gte': lambda: first >= second,
                'lt': lambda: first < second, 'lte': lambda: first <= second}.get(op, lambda: None)()
    return all(compare(predicate.get('op'), value if left_ref else literal, literal if left_ref else value)
               == compare(rule['op'], value, rule['right']) for value in domain)


def _evaluate_flow(case: Case, operation: dict[str, Any], graph: WorkflowGraph,
                   expected: dict[str, Any]) -> list[str]:
    issues = []
    schedule = _schedule(graph)
    if not _matches(schedule, expected['schedule']):
        issues.append('schedule differs from explicit recurrence/clock/timezone')
    if expected['preserve_existing']:
        return issues + _preserved_update(case, operation, graph)

    rules = expected['roles']
    actions = _nodes(graph, 'app_skill_action')
    if len(actions) != len(rules):
        issues.append('unrequested or missing app/Ask AI actions')
    roles: dict[str, Any] = {}
    consumed = set()
    for name, rule in rules.items():
        candidates = [node for node in _actions(graph, rule['capability']) if node.id not in consumed
                      and _matches(node.config.get('input') or {}, rule['input_subset'])]
        if len(candidates) != 1:
            issues.append('missing or ambiguous role/input: ' + name)
            continue
        node = roles[name] = candidates[0]
        consumed.add(node.id)
        inputs = node.config.get('input') or {}
        for pattern in rule.get('input_patterns', []):
            if re.search(pattern, _json(inputs), re.I) is None:
                issues.append(name + ' lacks input constraint: ' + pattern)
        for pattern in rule.get('input_forbidden', []):
            if re.search(pattern, _json(inputs), re.I) is not None:
                issues.append(name + ' retains forbidden input: ' + pattern)
        if rule.get('day'):
            day = rule['day']
            explicit = all(isinstance(inputs.get(field), dict)
                           and inputs[field].get('$date') in {day, day + '_end'}
                           and inputs[field].get('format') == 'date'
                           for field in ('start_date', 'end_date'))
            if not explicit and not (day == 'today' and inputs.get('days') == 1):
                issues.append(name + ' does not use requested runtime day: ' + day)
    for name, rule in rules.items():
        if name not in roles:
            continue
        prompt = (roles[name].config.get('input') or {}).get('prompt', '')
        for pattern in rule.get('prompt_patterns', []):
            if re.search(pattern, str(prompt), re.I) is None:
                issues.append(name + ' lacks prompt intent: ' + pattern)
        for source in rule.get('refs', []):
            if source not in roles or not _has_ref(prompt, roles[source].id, ('results', 'events', 'articles', 'recipes', 'forecast_days')):
                issues.append(name + ' lacks typed input reference: ' + source)

    checks = _nodes(graph, 'check')
    check_rule = expected['check']
    branch_sets = {}
    if len(checks) != int(check_rule is not None):
        issues.append('unrequested or missing Check')
    if check_rule and len(checks) == 1:
        check = checks[0]
        branch_sets = _branch_send_sets(graph, check.id)
        if check.config.get('mode') != check_rule['mode']:
            issues.append('Check uses wrong decision mode')
        elif check_rule['mode'] == 'exact':
            predicate = check.config.get('predicate') or {}
            source = roles.get(check_rule['source'])
            if not _exact_comparison_matches(predicate, check_rule, source):
                issues.append('exact Check changed typed field, comparison, direction or threshold')
        else:
            for source in check_rule['sources']:
                if source not in roles or not _has_ref(check.config.get('selected_inputs'), roles[source].id, ('results', 'articles')):
                    issues.append('AI Check lacks selected input: ' + source)
            for pattern in check_rule['question_patterns']:
                if re.search(pattern, str(check.config.get('question', '')), re.I) is None:
                    issues.append('AI Check changed authored question: ' + pattern)

    sends = _nodes(graph, 'send_chat_message')
    if len(sends) != len(expected['sends']):
        issues.append('unrequested or missing chat messages')
    matched = set()
    for index, send_rule in enumerate(expected['sends']):
        branch = send_rule['branch']
        eligible = {node.id for node in sends}
        if branch == 'shared':
            eligible = set.intersection(*branch_sets.values()) if len(branch_sets) >= 2 else set()
        elif branch is not None:
            others = set().union(*(value for label, value in branch_sets.items() if label != branch))
            eligible = branch_sets.get(branch, set()) - others
        candidates = []
        for node in sends:
            if node.id not in eligible or node.id in matched:
                continue
            message = str(node.config.get('message', '')).strip()
            if not all(re.search(pattern, message, re.I) is not None for pattern in send_rule['patterns']):
                continue
            if not all(source in roles and _has_ref(node.config, roles[source].id,
                ('answer',) if rules[source]['capability'] == 'ai.ask' else ('results', 'events', 'articles', 'recipes', 'forecast_days'))
                for source in send_rule['refs']):
                continue
            candidates.append(node)
        if len(candidates) != 1:
            issues.append(f'message {index} lost text, typed references, exclusivity or continuation placement')
        else:
            matched.add(candidates[0].id)
    expected_nodes = 1 + len(rules) + int(check_rule is not None) + len(expected['sends'])
    if len(graph.nodes) != expected_nodes:
        issues.append('unrequested or missing nodes')
    return issues


def evaluate(case: Case, operations: list[dict[str, Any]]) -> list[str]:
    """Evaluate explicit pre-inference facts; unknown case IDs fail closed."""
    expanded_ids = {item.id for item in _expanded_cases()}
    if case.id not in LEGACY_CASE_IDS | expanded_ids:
        raise ValueError('Unknown workflow benchmark case: ' + case.id)
    issues = []
    if case.expectations:
        if len(operations) != len(case.expectations):
            issues.append(f'expected {len(case.expectations)} operations, got {len(operations)}')
        remaining = list(operations)
        for index, expected in enumerate(case.expectations):
            # Match batch members by operation and requested schedule, not model order.
            compatible = []
            for operation in remaining:
                if operation.get('action', operation.get('type')) != expected['action']:
                    continue
                try:
                    graph = WorkflowGraph.model_validate(operation['graph'])
                except (KeyError, ValueError):
                    continue
                if _matches(_schedule(graph), expected['schedule']):
                    compatible.append((operation, graph))
            if len(compatible) != 1:
                issues.append(f'workflow {index} lacks unique operation with requested schedule')
                continue
            operation, graph = compatible[0]
            remaining.remove(operation)
            issues += _evaluate_flow(case, operation, graph, expected)
        if remaining:
            issues.append('unexpected or unmatched workflow operations')
    else:
        issues += _evaluate_legacy(case, operations)
    for operation in operations:
        for node in operation.get('graph', {}).get('nodes', []):
            if node.get('type') == 'schedule_trigger' and 'starts_at' in (node.get('config', {}).get('schedule') or {}):
                issues.append('invented starts_at date')
    return issues
