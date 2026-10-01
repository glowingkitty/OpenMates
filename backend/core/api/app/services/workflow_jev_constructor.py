"""Experimental graph construction using only registry-derived Jev decisions.

Jev chooses node counts, literal/reference sources, edges and condition operands;
Python assembles and validates V2 JSON. User text candidates are copied rather
than generated. Bounds deliberately expose cases needing a generative model:
three instances per skill, two checks, three messages and one array item. This
is a comparison constructor, not the production workflow input planner.
"""

from __future__ import annotations

import re
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.core.api.app.services.workflow_authoring_preselection import JEV_INPUT_PRICE, WorkflowPreselection
from backend.core.api.app.services.workflow_models import (
    WorkflowGraph, validate_workflow_composition_refs, validate_workflow_readiness,
)
from backend.shared.providers.typesafe.models import ChoiceAnswer

MAX_NODES = 16
MAX_QUESTIONS = 160
_OMIT = object()
_NUMBER_WORDS = {word: index for index, word in enumerate(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"),
)}
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _choice(instructions: str, candidates: dict[str, Any]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": candidates}


def _strings(text: str) -> list[str]:
    """Produce bounded exact user spans; no expected-case values enter here."""
    spans = re.findall(r'"([^"\n]+)"', text)
    spans += re.findall(r"'([^'\n]+)'", text)
    spans += re.findall(r"\b[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,2}\b", text)
    spans += re.findall(r"\b[A-Z][\w-]*\b", text)
    spans += [match.group(1).strip() for match in re.finditer(
        r"\b(?:about|for|in|saying|to|summarize)\s+(.+?)(?=[,.;]|\band\b|\bthen\b|\bif\b|$)",
        text, re.IGNORECASE,
    )]
    spans += re.split(r"[;\n]|\bthen\b|\bif\b|\botherwise\b", text, flags=re.IGNORECASE)
    unique = list(dict.fromkeys(span.strip(' ,.;') for span in spans if span.strip(' ,.;')))
    return unique[:30] + ([text] if text not in unique[:30] else [])


def _numbers(text: str) -> list[int | float]:
    numbers = [float(match) for match in re.findall(r"(?<!\w)\d+(?:\.\d+)?", text)]
    numbers += [value for word, value in _NUMBER_WORDS.items() if re.search(rf"\b{word}\b", text, re.IGNORECASE)]
    return list(dict.fromkeys(int(value) if int(value) == value else value for value in numbers))


def _times(text: str) -> list[str]:
    values = []
    for match in re.finditer(r"\b(?:at|to)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text, re.IGNORECASE):
        hour, minute = int(match[1]), int(match[2] or 0)
        suffix = (match[3] or "").lower()
        if suffix and 1 <= hour <= 12:
            hour = hour % 12 + (12 if suffix == "pm" else 0)
        if 0 <= hour <= 23 and minute < 60:
            values.append(f"{hour:02d}:{minute:02d}")
    return list(dict.fromkeys(values + ["09:00"]))


def _zones(text: str, browser_zone: str) -> list[str]:
    zones = [browser_zone]
    zones += re.findall(r"\b[A-Za-z_]+/[A-Za-z_]+(?:/[A-Za-z_]+)?\b", text)
    # Local scheduling aliases, not a limit on weather/search location strings.
    aliases = {"berlin": "Europe/Berlin", "london": "Europe/London", "lisbon": "Europe/Lisbon",
               "san francisco": "America/Los_Angeles", "new york": "America/New_York", "utc": "UTC"}
    zones += [zone for name, zone in aliases.items() if name in text.lower()]
    result = []
    for zone in dict.fromkeys(zones):
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        result.append(zone)
    if not result:
        raise ValueError("No valid browser or explicit schedule timezone")
    return result


def _output_values(nodes: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    values = []
    for node in nodes:
        schema = node.get("output_schema", {})
        for name, field in (schema.get("properties") or {}).items():
            values.append((f"$nodes.{node['id']}.output.{name}", field))
    return values


def _types(schema: dict[str, Any]) -> set[str]:
    raw = schema.get("type", "string")
    return set(raw if isinstance(raw, list) else [raw]) - {"null"}


def _inputs(schema: dict[str, Any], path: tuple[Any, ...] = (), required: bool = True):
    """Expose schema leaves. Optional containers are omitted in this experiment."""
    types = _types(schema)
    if "object" in types:
        for name, child in schema.get("properties", {}).items():
            is_required = name in schema.get("required", [])
            if not is_required and _types(child) & {"object", "array"}:
                continue
            yield from _inputs(child, path + (name,), required and is_required)
    elif "array" in types:
        yield from _inputs(schema.get("items", {}), path + (0,), required)
    else:
        yield path, schema, required


def _set_path(target: dict[str, Any], path: tuple[Any, ...], value: Any) -> None:
    cursor: Any = target
    for index, key in enumerate(path):
        final = index == len(path) - 1
        if isinstance(key, int):
            while len(cursor) <= key:
                cursor.append({})
            if final:
                cursor[key] = value
            else:
                cursor = cursor[key]
        elif final:
            cursor[key] = value
        else:
            cursor = cursor.setdefault(key, [] if isinstance(path[index + 1], int) else {})


class WorkflowJevConstructor:
    """Assemble a graph from two decision waves after skill preselection."""

    def __init__(self, *, jev_client: Any) -> None:
        self.jev_client = jev_client
        self.last_metrics: dict[str, Any] = {}
        self.candidate_graph: dict[str, Any] | None = None
        self.decision_trace: list[dict[str, str]] = []
        self.failure_reason: str | None = None

    async def construct(
        self, *, text: str, selection: WorkflowPreselection, timezone: str = "UTC",
        selected_workflow: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        start = time.perf_counter()
        self.last_metrics = {"jev_calls": 0, "input_tokens": 0, "estimated_cost_usd": 0.0, "wave_seconds": {}}
        self.candidate_graph = None
        self.decision_trace = []
        self.failure_reason = None
        try:
            graph = await self._construct(text=text, selection=selection, timezone=timezone,
                                          selected_workflow=selected_workflow)
            return graph, self.last_metrics
        except ValueError as exc:
            self.failure_reason = str(exc)[:500]
            raise
        finally:
            self.last_metrics["seconds"] = round(time.perf_counter() - start, 3)
            self.last_metrics["estimated_cost_usd"] = round(self.last_metrics["estimated_cost_usd"], 8)

    async def _construct(
        self, *, text: str, selection: WorkflowPreselection, timezone: str,
        selected_workflow: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if selected_workflow is not None or selection.operation != "create":
            raise ValueError("Generic Jev edit and batch construction require a separate evaluation")
        if not selection.chat_delivery:
            raise ValueError("Requested delivery is unavailable in this V2 comparison constructor")
        metrics = self.last_metrics
        state = {"request": text, "browser_timezone": timezone, **selection.context()}
        count_options = {str(count): f"Exactly {count} separate nodes" for count in range(4)}
        count_options["unsupported"] = "More than three nodes of this kind are explicitly required"
        questions = {
            f"count:{cap.id}": _choice(
                f"How many separate {cap.id} action nodes are needed? Select 0 if this candidate skill is not required; candidates are deliberately broad. Use its input schema: one array input can hold related requests, but a single location input needs one node per location. Exclude superseded requests.", count_options,
            ) for cap in selection.capabilities
        }
        for kind, meaning in (("exact", "deterministic conditions"), ("ai", "subjective yes/no assessments"),
                              ("send", "distinct chat messages, including separate true/false responses")):
            if kind in {"exact", "ai"} and selection.check_mode not in {kind, "both"}:
                continue
            options = count_options
            instructions = (
                f"How many nodes are needed for {meaning} in request? An if/else statement needs ONE check node with two branches, not two check nodes. AND/OR operands belong to the same check. Select 0 if none of this kind is required."
            )
            if kind == "send":
                # Delivery was already selected; zero would contradict that
                # required effect. Each explicitly different branch response
                # needs its own message rather than its own condition.
                options = {key: value for key, value in count_options.items() if key != "0"}
                instructions = "How many distinct chat messages does the request require? Use 1 for delivering action results, including a default chat delivery. Use 2 when the true and false branches explicitly request different messages. Three separately requested messages need 3."
            questions[f"count:{kind}"] = _choice(
                instructions, options,
            )
        questions["trigger"] = _choice("What starts the workflow? Default to a weekly schedule when no trigger is specified.", {
            "schedule": "Recurring time/date schedule or unspecified trigger", "manual": "Explicit manual run only",
            "unsupported": "An event/webhook/other trigger not supported by this graph grammar",
        })
        answers = await self._evaluate(state, questions, metrics)
        for kind in ("exact", "ai"):
            answers.setdefault(f"count:{kind}", "0")
        if any(value == "unsupported" for value in answers.values()):
            raise ValueError("Jev could not determine bounded node instances")
        nodes = [{"id": "trigger", "type": f"{answers['trigger']}_trigger", "description": "Start the workflow"}]
        for cap in selection.capabilities:
            count = int(answers[f"count:{cap.id}"])
            for index in range(count):
                nodes.append({"id": f"action{len(nodes)}", "type": "app_skill_action", "capability": cap.id,
                              "instance": index + 1, "description": cap.metadata.get("description", cap.id),
                              "input_schema": cap.metadata["input_schema"], "output_schema": cap.metadata["output_schema"]})
        for mode in ("exact", "ai"):
            if int(answers[f"count:{mode}"]) > 2:
                raise ValueError("This experiment supports up to two checks of each mode")
            for index in range(int(answers[f"count:{mode}"])):
                nodes.append({"id": f"{mode}_check{index + 1}", "type": "check", "mode": mode,
                              "description": f"{mode} condition {index + 1}"})
        for index in range(int(answers["count:send"])):
            nodes.append({"id": f"send{index + 1}", "type": "send_chat_message", "description": f"Chat message {index + 1}"})
        nodes.append({"id": "end", "type": "end", "description": "Finish without further actions"})
        if len(nodes) > MAX_NODES:
            raise ValueError("Workflow exceeds the experimental node budget")
        state["allocated_nodes"] = [{key: value for key, value in node.items() if key not in {"input_schema", "output_schema"}} for node in nodes]
        questions, values = self._field_questions(text, timezone, nodes)
        state["construction_rules"] = (
            "Choose a coherent directed acyclic graph. Every action executes at most once on a path. "
            "References must come from nodes executed before the consumer. All requested actions must "
            "be reachable. A literal value is copied verbatim; choose needs_generation when no offered "
            "value faithfully implements the requirement. Never invent a threshold or substitute an app. "
            "Only one array item and up to two condition operands are supported in this experiment."
        )
        if len(questions) > MAX_QUESTIONS:
            raise ValueError("Workflow requires more field decisions than the experimental budget")
        answers = await self._evaluate(state, questions, metrics)
        graph = self._compile(nodes, answers, values)
        self.candidate_graph = graph
        validated = WorkflowGraph.model_validate(graph)
        validate_workflow_readiness(validated)
        validate_workflow_composition_refs(validated)
        return validated.model_dump(mode="json", by_alias=True)

    async def _evaluate(self, state: dict[str, Any], questions: dict[str, Any], metrics: dict[str, Any]) -> dict[str, str]:
        started = time.perf_counter()
        response = await self.jev_client.evaluate(state=state, questions=questions)
        stage = "instances" if any(key.startswith("count:") for key in questions) else "bindings"
        metrics["wave_seconds"][stage] = round(time.perf_counter() - started, 3)
        metrics["jev_calls"] += 1
        metrics["input_tokens"] += response.usage.input_tokens
        metrics["estimated_cost_usd"] += response.usage.input_tokens * JEV_INPUT_PRICE
        answers = {}
        for key, question in questions.items():
            answer = response.answers.get(key)
            if not isinstance(answer, ChoiceAnswer) or answer.choice not in question["criteria"]:
                raise ValueError(f"Jev omitted a valid field decision: {key}")
            answers[key] = answer.choice
        self.decision_trace.append(answers)
        return answers

    def _field_questions(self, text: str, timezone: str, nodes: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        questions: dict[str, Any] = {}
        values: dict[str, dict[str, Any]] = {}
        strings, numbers = _strings(text), _numbers(text)
        outputs = _output_values(nodes)

        def add(key: str, instruction: str, options: list[Any], optional: bool = False) -> None:
            lookup = {f"value{index}": value for index, value in enumerate(options)}
            criteria = {name: {"value": value} for name, value in lookup.items()}
            if optional:
                lookup["omit"] = _OMIT
                criteria["omit"] = "Omit: the user does not request this optional field"
            criteria["needs_generation"] = "No candidate faithfully satisfies this field; text generation or clarification is needed"
            values[key] = lookup
            questions[key] = _choice(instruction, criteria)

        for node in nodes:
            node_id = node["id"]
            if node["type"] != "end":
                candidates = {other["id"]: f"{other['description']} ({other['id']}, {other.get('capability') or other['type']}, instance {other.get('instance', 1)})"
                              for other in nodes if other["id"] not in {node_id, "trigger"}}
                branches = ("yes", "no", "unsure") if node.get("mode") == "ai" else ("yes", "no") if node["type"] == "check" else ("next",)
                for branch in branches:
                    questions[f"{node_id}:{branch}"] = _choice(
                        f"Which node follows {node_id} ({node['description']}, instance {node.get('instance', 1)}) on its {branch} branch? Every allocated action and requested message must be reachable; do not skip required actions. Actions precede their checks and messages. On a false/unsure branch choose end ONLY when no response is requested for that branch. Otherwise select its message. Distinguish separate true/false messages by their instance number, true first. Messages finish at end.", candidates,
                    )
            if node["type"] == "schedule_trigger":
                add(f"{node_id}:time", "Select the final requested local schedule time, ignoring superseded times; default 09:00 if none.", _times(text))
                add(f"{node_id}:timezone", f"Select an explicitly requested schedule timezone; otherwise {timezone}. A weather/search city alone does not change schedule timezone.", _zones(text, timezone))
                add(f"{node_id}:cadence", "Select daily for every day, weekly for weekdays or named days (Monday etc.). Default weekly when unspecified. Unsupported schedules need generation/clarification.", ["daily", "weekly"])
                days = [[day] for day in _DAYS]
                mentioned = [day for day in _DAYS if re.search(rf"\b{day}\b", text, re.IGNORECASE)]
                days += [list(_DAYS[:5]), list(_DAYS[5:])]
                if len(mentioned) > 1:
                    days.append(mentioned)
                add(f"{node_id}:days", "Which weekdays are scheduled? Default Monday when unspecified; this field is ignored for daily schedules.", days)
            elif node["type"] == "app_skill_action":
                for path, schema, required in _inputs(node["input_schema"]):
                    types = _types(schema)
                    options: list[Any] = list(schema.get("enum", []))
                    if not options:
                        options += strings if "string" in types else [True, False] if "boolean" in types else numbers
                        options += [reference for reference, output in outputs
                                    if not reference.startswith(f"$nodes.{node_id}.") and _types(output) & types]
                    name = str(path[-1]) if path else "input"
                    if "date" in name or schema.get("format") in {"date", "date-time"}:
                        date_format = "datetime" if schema.get("format") == "date-time" else "date"
                        options += [{"$date": expression, "format": date_format} for expression in (
                            "today", "tomorrow", "next_seven_days_start", "next_seven_days_end",
                        )]
                    if "default" in schema:
                        options.append(schema["default"])
                    key = f"{node_id}:input:{'.'.join(map(str, path))}"
                    optional_rule = "Optional field: select omit unless the user explicitly requires a value or binding. " if not required else "Required field. "
                    add(key, f"Choose {node['capability']} instance {node['instance']} input {'.'.join(map(str, path))}. {optional_rule}Field contract: {schema}. Preserve the final request. If a required value has no suitable candidate select needs_generation.", options[:100], not required)
                    if node["capability"] == "ai.ask" and path == ("prompt",):
                        add(f"{node_id}:prompt_source", f"Which earlier data should be supplied to the copied ai.ask instruction in {node_id}? Omit only when no prior data is required.",
                            [ref for ref, _ in outputs if not ref.startswith(f"$nodes.{node_id}.")], True)
            elif node["type"] == "check" and node["mode"] == "exact":
                scalar_refs = [reference for reference, schema in outputs if _types(schema) & {"boolean", "number", "integer", "string"}]
                add(f"{node_id}:combination", f"How are predicates for {node_id} combined? Use single for one condition, or and/or for two conditions.", ["single", "and", "or"])
                for index in (1, 2):
                    add(f"{node_id}:left{index}", f"Select output operand {index} of {node_id} for the user's condition, not the notification content. Second operand may be omitted if only one predicate is required.", scalar_refs, index == 2)
                    add(f"{node_id}:op{index}", f"Select comparison operator {index} in {node_id}. Choose eq for a boolean expected flag, never invent a numeric threshold.", ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "exists"])
                    add(f"{node_id}:right{index}", f"Select comparison value {index} in {node_id}; use true for an expected boolean flag. Numeric thresholds must be explicitly specified.", [True, False, *numbers, *strings])
            elif node["type"] == "check":
                add(f"{node_id}:question", f"Copy the subjective yes/no question for {node_id} from a faithful user span. If it requires rewriting select needs_generation.", strings)
                for index in (1, 2):
                    add(f"{node_id}:source{index}", f"Select earlier data value {index} to evaluate in AI check {node_id}. Omit unused second source.", [ref for ref, _ in outputs], index == 2)
            elif node["type"] == "send_chat_message":
                for index in (1, 2):
                    add(f"{node_id}:source{index}", f"Select earlier result data value {index} to include in {node_id}, {node['description']}. Prefer a summary/answer/count for the first text variable and a results object/array for the second embed. True-branch message comes first, false-branch second. V2 requires a text variable from an earlier action when actions precede a message; only omit a first source when no action precedes it.", [ref for ref, _ in outputs], index == 2 or not outputs)
                add(f"{node_id}:message", f"Copy the requested text for {node_id}, {node['description']}. True-branch text comes first, false-branch second. Omit if result data alone is delivered; select needs_generation if new prose must be written.", strings, True)
        return questions, values

    def _compile(self, nodes: list[dict[str, Any]], answers: dict[str, str], values: dict[str, Any]) -> dict[str, Any]:
        def get(key: str) -> Any:
            if answers[key] == "needs_generation":
                raise ValueError(f"A consumed field needs generation: {key}")
            return values[key][answers[key]]

        compiled, edges = [], []
        output_types = {ref: _types(schema) for ref, schema in _output_values(nodes)}
        for node in nodes:
            node_id, node_type = node["id"], node["type"]
            config: dict[str, Any] = {}
            if node_type == "schedule_trigger":
                schedule = {"type": get(f"{node_id}:cadence"), "time": get(f"{node_id}:time"), "timezone": get(f"{node_id}:timezone")}
                if schedule["type"] == "weekly":
                    schedule["weekdays"] = get(f"{node_id}:days")
                config = {"schedule": schedule}
            elif node_type == "app_skill_action":
                app_id, skill_id = node["capability"].split(".", 1)
                authored: dict[str, Any] = {}
                for path, _, _ in _inputs(node["input_schema"]):
                    value = get(f"{node_id}:input:{'.'.join(map(str, path))}")
                    if value is not _OMIT:
                        _set_path(authored, path, value)
                config = {"app_id": app_id, "skill_id": skill_id, "input": authored}
                if node["capability"] == "ai.ask":
                    source = get(f"{node_id}:prompt_source")
                    if source is not _OMIT:
                        authored["prompt"] = f"{authored['prompt']}\n\nInput data:\n{{{{ {source} }}}}"
            elif node_type == "check":
                config["mode"] = node["mode"]
                if node["mode"] == "exact":
                    combination = get(f"{node_id}:combination")
                    predicates = []
                    for index in range(1, 2 if combination == "single" else 3):
                        left = get(f"{node_id}:left{index}")
                        if left is _OMIT:
                            raise ValueError("A compound condition omitted an operand")
                        predicates.append({"left": left, "op": get(f"{node_id}:op{index}"), "right": get(f"{node_id}:right{index}")})
                    config["predicate"] = predicates[0] if combination == "single" else {"op": combination, "conditions": predicates}
                else:
                    config["question"] = get(f"{node_id}:question")
                    config["selected_inputs"] = list(dict.fromkeys(value for index in (1, 2) if (value := get(f"{node_id}:source{index}")) is not _OMIT))
                    config["question"] += "".join(f"\n{{{{ {ref} }}}}" for ref in config["selected_inputs"])
            elif node_type == "send_chat_message":
                # Chat titles are delivery metadata, separate from choosing
                # actions and control flow. Use a neutral backend default in
                # the graph-only experiment; product identity generation is
                # deliberately measured separately.
                config["title"] = "Workflow update"
                message = get(f"{node_id}:message")
                if message is not _OMIT:
                    config["message"] = message
                sources = [value for index in (1, 2) if (value := get(f"{node_id}:source{index}")) is not _OMIT]
                config["message"] = config.get("message", "") + "".join(f"\n{{{{ {ref} }}}}" for ref in sources)
                config["blocks"] = [{"id": f"result{index}", "source": ref} for index, ref in enumerate(sources)
                                    if output_types[ref] & {"object", "array"}]
            compiled.append({"id": node_id, "type": node_type, "config": config})
            if node_type == "end":
                continue
            branches = ("yes", "no", "unsure") if node.get("mode") == "ai" else ("yes", "no") if node_type == "check" else ("next",)
            for branch in branches:
                edge = {"from": node_id, "to": answers[f"{node_id}:{branch}"]}
                if branch != "next":
                    edge["branch"] = branch
                edges.append(edge)
        return {"version": 2, "trigger_node_id": "trigger", "nodes": compiled, "edges": edges}
