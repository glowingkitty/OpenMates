#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Compare Jev, GLiDE, and GLiNER-Decide on synthetic OpenMates decisions.

Purpose: Measure label quality, caller eligibility, HTTP latency, usage, and cost.
Architecture: Capture production request builders without making their AI calls.
Data: Hand-labeled synthetic cases and bounded, synthetic public search projections.
Credentials: Read provider keys from Vault inside the API container; never export them.
Output: JSONL receipts containing only synthetic outputs, plus aggregate JSON.
Usage: docker exec api python /app/backend/scripts/benchmark_decision_models.py
Limitations: Encoder classification is an adapted task, not a System One replacement.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import statistics
import time
from typing import Any
from unittest.mock import patch

import httpx

from backend.scripts.decision_benchmark_cases import CASES

MODELS = {
    "jev": ("typesafe/jev-1.13", "https://openrouter.ai/api/alpha/decisions", "openrouter", 0.042),
    "glide": ("fastino/GLiDE", "https://api.fastino.ai/v1/systemone", "fastino", 0.30),
    "gliner_decide": ("fastino/GLiNER-2.5-Decide", "https://api.fastino.ai/v1/chat/completions", "fastino", 0.03),
}


class Captured(BaseException):
    """Escape caller fallbacks while collecting, without invoking inference."""

    def __init__(self, state: Any, questions: dict[str, Any]):
        self.state, self.questions = state, questions


async def capture(*args: Any, **kwargs: Any) -> None:
    raise Captured(kwargs["state"], kwargs["questions"])


# Each profile includes explicit direct-fit evidence and explicit conflicting evidence.
SEARCH_INPUTS = {
    "hosting_domains": ("A non-premium .com domain about syntheticwidgets with renewal below 20 EUR", {"name": "syntheticwidgets.com", "available": True, "renewal_price": 12, "currency": "EUR", "premium": False}, {"name": "unrelated.example", "available": True, "renewal_price": 1000, "currency": "EUR", "premium": True}),
    "web": ("Primary technical evidence about Python local-first synchronization", {"title": "Python local-first synchronization architecture", "description": "Official implementation guide with runnable Python examples and measured conflict-resolution benchmarks", "url": "https://docs.example.invalid/python-sync"}, {"title": "Fashion trends", "description": "A photo gallery of seasonal clothing", "url": "https://fashion.example.invalid"}),
    "news": ("A concrete new AI compliance deadline for European startups", {"title": "EU authority publishes new startup compliance deadline", "description": "Primary notice states the exact filing obligation and deadline", "publisher": "EU authority", "url": "https://authority.example.invalid/notice"}, {"title": "Celebrity wedding", "description": "Entertainment gossip", "url": "https://gossip.example.invalid"}),
    "events": ("An AI community event where a founder can demonstrate their AI product", {"title": "AI founder demo evening", "description": "AI founders demonstrate products to potential users, followed by community networking", "location": "Berlin"}, {"title": "Classical concert", "description": "A seated orchestral performance; no technology demonstrations", "location": "Berlin"}),
    "home": ("A rental apartment with a balcony and explicitly quiet surroundings", {"title": "Apartment with balcony", "description": "Rental apartment, balcony, on a quiet residential courtyard"}, {"title": "Room beside highway", "description": "Shared room with no balcony; noisy highway setting"}),
    "maps": ("A laptop-friendly cafe with Wi-Fi and desk seating", {"displayName": "Work Cafe", "description": "Laptop-friendly cafe with Wi-Fi and desk seating; open until 20:00"}, {"displayName": "Takeaway Kiosk", "description": "Takeaway only, no seats and no Wi-Fi"}),
    "shopping": ("A compact mouse with silent clicks and multi-device support", {"title": "Silent travel mouse", "description": "Compact mouse, silent clicks, connects to three devices", "price": 25}, {"title": "Office keyboard", "description": "Large wired mechanical keyboard", "price": 90}),
    "travel_stays": ("A stay with explicit Wi-Fi and a work desk", {"name": "Work Stay", "description": "Every room includes Wi-Fi and a work desk", "amenities": ["Wi-Fi", "desk"]}, {"name": "Off-grid Camping", "description": "No internet, no desk, tent pitches only"}),
    "videos": ("Advanced production Python RAG implementation with evaluation", {"title": "Production Python RAG evaluation", "description": "Advanced hands-on architecture, deployment and evaluation tutorial"}, {"title": "Beginner gardening", "description": "How to plant tomatoes"}),
    "code_repositories": ("A Python local-first synchronization library with a permissive license", {"name": "python-local-sync", "description": "Python library for local-first synchronization", "language": "Python", "license": "MIT"}, {"name": "java-ui-theme", "description": "Java UI theme", "language": "Java", "license": "proprietary"}),
    "models3d": ("A free adjustable laptop stand with an STL file and stated license", {"title": "Adjustable laptop stand", "description": "Height-adjustable laptop stand", "file_formats": ["STL"], "license": "CC-BY", "price": 0}, {"title": "Decorative vase", "description": "Fixed decorative vase", "file_formats": ["OBJ"], "price": 15}),
    "fitness_locations": ("A central Berlin venue with explicit yoga class variety", {"name": "Central Yoga", "description": "Vinyasa, Hatha and Yin yoga", "address": "Berlin Mitte"}, {"name": "Boxing Gym", "description": "Boxing only", "address": "Hamburg"}),
    "fitness_classes": ("An evening Berlin yoga class with remaining spots", {"title": "Evening Yoga", "description": "On-site yoga", "location": "Berlin Mitte", "start_time": "19:00", "available_spots": 8}, {"title": "Morning Boxing", "description": "Boxing", "location": "Hamburg", "start_time": "07:00", "available_spots": 0}),
}


async def build_cases() -> list[dict[str, Any]]:
    from backend.apps.ai.processing import jev_preprocessing as pre
    from backend.apps.ai.processing import chat_request_safety as safety
    from backend.apps.ai.processing import content_sanitization as injection
    from backend.apps.ai.processing import postprocessor as post
    from backend.apps.ai.processing.preprocessor import _build_topic_areas_list
    from backend.core.api.app.services.skill_registry import build_skill_registry
    from backend.core.api.app.services import workflow_ai_service as workflow
    from backend.core.api.app.services.workflow_authoring_preselection import WorkflowAuthoringPreselector
    from backend.shared.python_utils import search_relevance as ranking

    _, metadata = build_skill_registry()
    skills = [f"{app}-{skill.id}: {skill.preprocessor_hint or skill.id}" for app, info in metadata.items() for skill in (info.skills or []) if (app, skill.id) != ("ai", "ask")]
    focuses = [f"{app}-{focus.id}: {focus.preprocessor_hint or focus.id}" for app, info in metadata.items() for focus in (info.focuses or [])]
    cases: list[dict[str, Any]] = []

    async def add(case: dict[str, Any], module: Any, call: Any) -> None:
        target = "evaluate_jev_decisions"
        with patch.object(module, target, capture):
            try:
                await call(capture)
            except Captured as payload:
                cases.append({**case, "state": payload.state, "questions": payload.questions, "call": call, "module": module})
                return
        raise RuntimeError(f"No production payload captured for {case['id']}")

    for original in CASES:
        case = dict(original)
        area = case["area"]
        if area == "preprocessing":
            async def call(evaluator: Any, case=case):
                return await pre.decide_preprocessing_with_jev(model_id=MODELS["jev"][0], secrets_manager=None, message_history=[*case.get("history", []), {"role": "user", "content": case["text"]}], topic_areas=_build_topic_areas_list(), available_skills=skills, available_focus_modes=focuses, available_settings_and_memories={"travel": ["preferred_airlines"], "ai": ["response_preferences"]}, recent_skill_activity=[], conversation_summary=None, previous_category=None, is_first_message=not case.get("history"))
            await add(case, pre, call)
        elif area == "request_safety":
            history = case.get("history", [])
            context = {"current_request": case["text"], "previous_user_request": next((item["content"] for item in reversed(history) if item["role"] == "user"), ""), "previous_assistant_response": next((item["content"] for item in reversed(history) if item["role"] == "assistant"), "")}
            async def call(evaluator: Any, context=context):
                return await safety._confirm_with_jev(context=context, task_id="synthetic-benchmark", model_id=MODELS["jev"][0], secrets_manager=None)
            await add(case, safety, call)
        elif area == "prompt_injection":
            async def call(evaluator: Any, case=case):
                return await injection._jev_prompt_injection_probability(content=case["text"], task_id="synthetic-benchmark", secrets_manager=None)
            await add(case, injection, call)
        elif area == "postprocessing":
            async def call(evaluator: Any, case=case):
                return await post._postprocessing_decisions_with_jev(model_id=MODELS["jev"][0], user_message=case["text"], assistant_response=case["assistant_response"], available_app_ids=list(metadata), secrets_manager=None)
            await add(case, post, call)
        elif area in {"workflow_check", "workflow_authoring"}:
            async def call(evaluator: Any, case=case):
                service = workflow.WorkflowAiService(secrets_manager=None, jev_evaluator=evaluator)
                if case["area"] == "workflow_check":
                    return await service.evaluate_check(question=case["question"], selected_inputs=case["selected_inputs"])
                if "question" in case:
                    return await service.validate_check_question(case["question"])
                return await service._authoring_with_jev(case["text"], [])
            await add(case, workflow, call)

    # A separate, identical compact classification workload for all three models.
    # It does not select tools, focus modes, or private memory and is not full preprocessing.
    for case in list(cases):
        if case["area"] == "preprocessing":
            cases.append({**case, "id": case["id"] + "_core", "area": "preprocessing_core", "questions": {key: value for key, value in case["questions"].items() if key in case["expected"]}, "call": None})

    for profile, (criteria, good, bad) in SEARCH_INPUTS.items():
        # Original provider order deliberately puts the conflicting result first.
        projections = [bad, good]
        async def call(evaluator: Any, profile=profile, criteria=criteria, projections=projections):
            with patch.object(ranking.JevDecisionClient, "evaluate", evaluator):
                return await ranking.rank_search_candidates(candidates=["bad", "good"], candidate_projections=projections, relevance_criteria=criteria, search_parameters={"query": criteria}, profile=profile, secrets_manager=None)
        case = {"id": f"ranking_{profile}", "area": "search_ranking", "expected": {}, "ranking": ["candidate_001", "candidate_000"]}
        try:
            await call(capture)
        except Captured as payload:
            cases.append({**case, "state": payload.state, "questions": payload.questions, "call": call, "module": ranking})

    for profile, count in [("web", 40), ("maps", 20), ("code_repositories", 40)]:
        base = next(case for case in cases if case["id"] == f"ranking_{profile}")
        state = json.loads(json.dumps(base["state"]))
        state["candidates"] = [{"candidate_id": f"candidate_{index:03d}", "data": {**state["candidates"][index % 2]["data"], "fixture_id": f"synthetic_{index}"}} for index in range(count)]
        definition = next(iter(base["questions"].values()))
        questions = {item["candidate_id"]: {**definition, "instructions": definition["instructions"].replace("candidate_000", item["candidate_id"])} for item in state["candidates"]}
        cases.append({**base, "id": f"ranking_{profile}_{count}", "area": "search_ranking_scale", "state": state, "questions": questions, "call": None})

    for text, expected in [
        ("Every Monday at 09:00 send tomorrow's Berlin weather forecast to this chat.", {"operation": "create", "check_mode": "none", "workflow_count": "1", "chat_delivery": True}),
        ("Every day at 09:00 fetch AI news, ask AI whether any item matters to my startup, and send a chat summary only if the answer is yes.", {"operation": "create", "check_mode": "ai", "workflow_count": "1", "chat_delivery": True}),
    ]:
        selector = WorkflowAuthoringPreselector(jev_client=type("CaptureClient", (), {"evaluate": capture})())
        try:
            await selector.select(text, timezone="Europe/Berlin")
        except Captured as payload:
            cases.append({"id": f"workflow_preselection_{len(cases)}", "area": "workflow_preselection", "expected": expected, "state": payload.state, "questions": payload.questions, "call": None})
    return cases


def encoder_payload(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    classifications, mappings = [], {}
    for name, question in case["questions"].items():
        criteria = question.get("criteria")
        if question["type"] == "noul":
            criteria = criteria or {"true": "Yes, the answer to the question is true", "false": "No, the answer to the question is false"}
        elif question["type"] == "score":
            criteria = {str(index): value for index, value in enumerate(criteria)}
        labels = {value if isinstance(value, str) else json.dumps(value, ensure_ascii=False): key for key, value in criteria.items()}
        task = {"model_llm": "ai_language_model_comparison", "harmful": "harmful_request", "misuse": "malicious_request", "user_unhappy": "explicit_user_dissatisfaction", "topic_shift": "conversation_topic_continuity"}.get(name, name)
        mappings[task] = {"question": name, **labels}
        classifications.append({"task": task, "labels": list(labels), "multi_label": False})
    state_text = json.dumps(case["state"], ensure_ascii=False)
    if "messages" in case["state"]:
        state_text = "\n".join(f"{message['role']}: {message['content']}" for message in case["state"]["messages"])
    return {"model": MODELS["gliner_decide"][0], "messages": [{"role": "user", "content": state_text}], "schema": {"classifications": classifications}, "threshold": 0, "include_confidence": True, "store": False}, mappings


def answer_value(answer: dict[str, Any]) -> Any:
    if "adapted_label" in answer:
        return answer["adapted_label"]
    if answer["type"] == "choice":
        return answer["choice"]
    if answer["type"] == "noul":
        return answer["noul"] >= 0.5
    return answer.get("expected_level", answer.get("score"))


def systemone_payload(case: dict[str, Any], model_id: str, *, encode_instructions: bool) -> dict[str, Any]:
    questions = json.loads(json.dumps(case["questions"]))
    if encode_instructions:
        for question in questions.values():
            if not isinstance(question["instructions"], str):
                question["instructions"] = json.dumps(question["instructions"], ensure_ascii=False, sort_keys=True)
    return {"model": model_id, "state": case["state"], "questions": questions}


async def evaluate(client: httpx.AsyncClient, case: dict[str, Any], model: str, key: str) -> dict[str, Any]:
    model_id, endpoint, provider, rate = MODELS[model]
    payload = systemone_payload(case, model_id, encode_instructions=model == "glide")
    mappings = None
    if model == "gliner_decide":
        payload, mappings = encoder_payload(case)
    # Includes network and server execution; excludes credential and case preparation.
    started = time.perf_counter()
    result = {"case": case["id"], "area": case["area"], "model": model, "question_count": len(case["questions"]), "payload_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    try:
        response = await client.post(endpoint, headers={"Authorization": f"Bearer {key}"}, json=payload)
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        result["within_current_3s_timeout"] = result["latency_ms"] <= 3000
        result["http_status"] = response.status_code
        if not response.is_success:
            result.update(status="provider_error", error=f"HTTP {response.status_code}")
            return result
        data = response.json()
        usage = data["usage"]
        result["input_tokens"] = usage.get("input_tokens", usage.get("prompt_tokens", 0))
        result["output_tokens"] = usage.get("output_tokens", usage.get("completion_tokens", 0))
        result["estimated_cost_usd"] = result["input_tokens"] * rate / 1_000_000
        if mappings is not None:
            raw = json.loads(data["choices"][0]["message"]["content"])
            answers = {}
            for task, mapping in mappings.items():
                item = raw[task]
                label = mapping[item["label"]]
                name = mapping["question"]
                kind = case["questions"][name]["type"]
                answers[name] = {"adapted_label": label == "true" if kind == "noul" else int(label) if kind == "score" else label, "classification_confidence": item.get("confidence")}
            result["caller_eligible"] = False
        else:
            from backend.shared.providers.typesafe.models import DecisionResponse
            # Preserve Jev's continuous scoring semantics for GLiDE callers.
            normalized = json.loads(json.dumps(data))
            if model == "glide":
                for answer in normalized["answers"].values():
                    if answer["type"] == "score":
                        answer["score"] = answer["expected_level"]
            parsed = DecisionResponse.model_validate(normalized)
            if set(case["questions"]) - set(parsed.answers):
                raise ValueError("missing answers")
            answers = data["answers"]
            async def replay(*args: Any, **kwargs: Any):
                return parsed
            result["caller_eligible"] = True
            if case.get("call"):
                try:
                    with patch.object(case["module"], "evaluate_jev_decisions", replay, create=True):
                        decoded = await case["call"](replay)
                    if case["area"] == "request_safety":
                        result["caller_eligible"] = decoded is not None
                    elif case["area"] == "prompt_injection":
                        result["caller_eligible"] = decoded is not None and (decoded <= 0.2 or decoded >= 0.90)
                    elif case["area"] == "workflow_check":
                        result["caller_eligible"] = decoded.decision_path == "bounded_decision_primary"
                    elif case["area"] == "workflow_authoring":
                        result["caller_eligible"] = decoded is not None and getattr(decoded, "verdict", "allowed") != "unverified"
                    elif case["area"] == "search_ranking":
                        result["caller_eligible"] = decoded.applied
                except Exception as exc:
                    result["caller_eligible"] = False
                    result["decoder_error_type"] = type(exc).__name__
        judgments = []
        failures = []
        for name, expected in case["expected"].items():
            actual = answer_value(answers[name])
            correct = expected[0] <= actual <= expected[1] if isinstance(expected, list) else actual == expected
            judgments.append(correct)
            if not correct:
                failures.append({"question": name, "expected": expected, "actual": actual})
        if "ranking" in case:
            good, bad = case["ranking"]
            correct = answer_value(answers[good]) > answer_value(answers[bad])
            judgments.append(correct)
            if not correct:
                failures.append({"question": "direct_fit_above_conflict", "good_score": answer_value(answers[good]), "bad_score": answer_value(answers[bad])})
        result.update(status="ok", assertions=len(judgments), correct_assertions=sum(judgments), case_correct=all(judgments), failures=failures, answers=answers)
    except Exception as exc:
        result.setdefault("latency_ms", round((time.perf_counter() - started) * 1000, 2))
        result.update(status="error", error_type=type(exc).__name__)
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["model"], "all"].append(row)
        groups[row["model"], row["area"]].append(row)
    for (model, area), items in groups.items():
        valid = [item for item in items if item["status"] == "ok"]
        latencies = sorted(item["latency_ms"] for item in valid)
        assertions = sum(item.get("assertions", 0) for item in valid)
        result.setdefault(model, {})[area] = {
            "requests": len(items), "valid": len(valid), "correct_cases": sum(item.get("case_correct", False) for item in valid),
            "assertions": assertions, "correct_assertions": sum(item.get("correct_assertions", 0) for item in valid),
            "caller_eligible": sum(item.get("caller_eligible", False) for item in valid),
            "within_current_3s_timeout": sum(item.get("within_current_3s_timeout", False) for item in valid),
            "p50_ms": round(statistics.median(latencies), 2) if latencies else None,
            "p95_ms": latencies[math.ceil(len(latencies) * .95) - 1] if latencies else None,
            "input_tokens": sum(item.get("input_tokens", 0) for item in items),
            "output_tokens": sum(item.get("output_tokens", 0) for item in items),
            "estimated_cost_usd": round(sum(item.get("estimated_cost_usd", 0) for item in items), 8),
        }
    return result


async def main(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.CRITICAL)
    cases = await build_cases()
    if args.area:
        cases = [case for case in cases if case["area"] in args.area]
    if args.list:
        for case in cases:
            print(case["id"], case["area"], len(case["questions"]))
        return
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    manager = SecretsManager()
    await manager.initialize()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        keys = {provider: await manager.get_secret(secret_path=f"kv/data/providers/{provider}", secret_key="api_key") for provider in {MODELS[model][2] for model in args.models}}
        if not all(keys.values()):
            raise RuntimeError("Missing provider credentials in Vault")
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20)) as client:
            for repeat in range(args.repeats):
                for index, case in enumerate(cases):
                    order = args.models[index % len(args.models):] + args.models[:index % len(args.models)]
                    for model in order:
                        if sum(row.get("estimated_cost_usd", 0) for row in rows) >= args.max_usd:
                            raise RuntimeError("Benchmark spend stop reached")
                        row = await evaluate(client, case, model, keys[MODELS[model][2]])
                        row["repeat"] = repeat + 1
                        rows.append(row)
                        with (args.output / "requests.jsonl").open("a") as output:
                            output.write(json.dumps(row, ensure_ascii=False) + "\n")
                        print(json.dumps({key: row.get(key) for key in ["case", "model", "status", "latency_ms", "input_tokens", "case_correct", "caller_eligible"]}), flush=True)
                        if row.get("http_status") in {401, 402, 403}:
                            raise RuntimeError("Provider credentials or funding requires attention")
    finally:
        await manager.aclose()
        summary = {"started_source": "production request builders, synthetic fixtures", "completed_at": datetime.now(timezone.utc).isoformat(), "rates_usd_per_million_input": {model: MODELS[model][3] for model in args.models}, "repeats": args.repeats, "case_count": len(cases), "metrics": summarize(rows), "provenance": {"builder_sha256": {str(case["module"].__name__): hashlib.sha256(Path(case["module"].__file__).read_bytes()).hexdigest() for case in cases if "module" in case}, "case_payloads_sha256": hashlib.sha256(json.dumps([{key: case[key] for key in ["id", "state", "questions", "expected"]} for case in cases], sort_keys=True, ensure_ascii=False).encode()).hexdigest()}}
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=list(MODELS), default=list(MODELS))
    parser.add_argument("--area", action="append")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=2)
    parser.add_argument("--max-usd", type=float, default=2.0)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("/app/test-results/decision-benchmark"))
    asyncio.run(main(parser.parse_args()))
