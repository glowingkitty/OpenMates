"""Paid opt-in benchmark for Jev selection + streaming Gemini compact authoring.

Run inside the API container::

    python -m backend.scripts.benchmark_workflow_compact_authoring \
        --cases all --output /tmp/workflow-compact-authoring.json

The compact plan is compiled and validated in memory. This script never saves
or executes a workflow. Generated plans and graphs stay in a mode-0600 report;
stdout contains only bounded status lines. Timings include selection, complete
Gemini generation, compilation/validation and the independent intent oracle.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import httpx

from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
from backend.core.api.app.services.workflow_models import WorkflowGraph
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.scripts.benchmark_workflow_authoring import CASES, TIMEZONE, Case, oracle
from backend.shared.providers.typesafe.client import JevDecisionClient


def select_cases(names: list[str]) -> list[Case]:
    if names == ["all"]:
        return list(CASES)
    selected = [case for case in CASES if case.id in names]
    if not selected or len(selected) != len(names) or len(set(names)) != len(names):
        raise ValueError("Unknown or duplicate case; use --list-cases")
    return selected


def _numeric_metrics(metrics: Any) -> dict[str, Any]:
    """Keep billed counters and timing only; provider payload text is excluded."""
    if not isinstance(metrics, dict):
        return {}
    accepted = {"seconds", "jev_calls", "first_component_ms", "component_count", "input_tokens",
                "output_tokens", "thinking_tokens", "estimated_cost_usd", "wave_seconds"}
    result: dict[str, Any] = {}
    for key, value in metrics.items():
        if key not in accepted:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
        elif key == "wave_seconds" and isinstance(value, dict):
            result[key] = {str(name): seconds for name, seconds in value.items()
                           if isinstance(seconds, (int, float)) and not isinstance(seconds, bool)}
    return result


async def run_case(
    case: Case,
    *,
    preselector: Any,
    author: Any,
    compile_plan: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate one request using the shared selection and deterministic compiler."""
    started = time.perf_counter()
    row: dict[str, Any] = {"case": case.id, "model": getattr(author, "model", "gemini-3.8-flash"),
                           "graph_valid": False, "intent_match": False}
    stage = "preselection"
    selection = None
    try:
        selection = await preselector.select(case.text, timezone=TIMEZONE)
        row["preselection_ms"] = round((time.perf_counter() - started) * 1000, 1)
        row["preselection_metrics"] = _numeric_metrics(selection.metrics)
        row["preselection_scores"] = {str(key): float(value) for key, value in selection.scores.items()}
        row["selected_capabilities"] = sorted(cap.id for cap in selection.capabilities)
        row["operation"] = selection.operation
        row["check_mode"] = selection.check_mode
        row["chat_delivery"] = selection.chat_delivery

        stage = "generation"
        generation_started = time.perf_counter()
        first_component_ms: float | None = None
        observed_components = 0

        async def on_component(event: dict[str, Any]) -> None:
            nonlocal first_component_ms, observed_components
            # Provider invokes this only after a complete compact step has
            # parsed, not on the first network byte or partial JSON token.
            observed_components += 1
            if first_component_ms is None:
                first_component_ms = round((time.perf_counter() - generation_started) * 1000, 1)

        raw, metrics = await author.generate(text=case.text, selection=selection,
                                              timezone=TIMEZONE, on_component=on_component)
        row["generation_ms"] = round((time.perf_counter() - generation_started) * 1000, 1)
        row["first_complete_component_ms"] = first_component_ms
        row["observed_components"] = observed_components
        row["generation_metrics"] = _numeric_metrics(metrics)
        row["compact_plan"] = raw

        stage = "compile_validation"
        compile_started = time.perf_counter()
        envelope = compile_plan(raw, selection, TIMEZONE)
        row["compile_validation_ms"] = round((time.perf_counter() - compile_started) * 1000, 1)
        row["action"] = envelope.get("action")
        if row["action"] == "needs_clarification":
            row["failure_stage"] = "clarification"
            row["intent_issues"] = ["clarification instead of requested workflow"]
            return row
        graph_raw = envelope["graph"]
        graph = graph_raw if isinstance(graph_raw, WorkflowGraph) else WorkflowGraph.model_validate(graph_raw)
        row["graph"] = graph.model_dump(mode="json", by_alias=True)
        row["graph_valid"] = True

        stage = "intent_oracle"
        oracle_started = time.perf_counter()
        row["intent_issues"] = oracle(graph, case)
        row["intent_oracle_ms"] = round((time.perf_counter() - oracle_started) * 1000, 1)
        row["intent_match"] = not row["intent_issues"]
    except Exception as exc:
        row["failure_stage"] = stage
        row["error"] = type(exc).__name__
        if stage in {"compile_validation", "intent_oracle"}:
            # Local compiler/validator errors are safe for these fixed synthetic
            # cases. Provider/Vault exception text is never copied to reports.
            row["validation_error"] = str(exc)[:500]
        if stage == "generation":
            row["generation_ms"] = round((time.perf_counter() - generation_started) * 1000, 1)
            row["first_complete_component_ms"] = first_component_ms
            row["observed_components"] = observed_components
            row["generation_metrics"] = _numeric_metrics(getattr(exc, "metrics", None))
        elif stage == "compile_validation":
            row["compile_validation_ms"] = round((time.perf_counter() - compile_started) * 1000, 1)
    finally:
        row["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        pre_cost = row.get("preselection_metrics", {}).get("estimated_cost_usd")
        gen_cost = row.get("generation_metrics", {}).get("estimated_cost_usd")
        if isinstance(pre_cost, (int, float)):
            row["estimated_cost_usd"] = round(pre_cost + (gen_cost if isinstance(gen_cost, (int, float)) else 0), 8)
            row["cost_estimate_complete"] = isinstance(gen_cost, (int, float)) and stage not in {
                "preselection", "generation"}
    return row


async def _main(args: argparse.Namespace) -> int:
    cases = select_cases(args.cases)
    logging.getLogger("backend.core.api.app.utils.secrets_manager").setLevel(logging.CRITICAL)
    from backend.core.api.app.services.workflow_authoring_preselection import WorkflowAuthoringPreselector
    from backend.core.api.app.services.workflow_authoring_compiler import compile_authoring_plan
    from backend.core.api.app.services.workflow_gemini_authoring import WorkflowGeminiAuthor

    secrets = SecretsManager()
    await secrets.initialize()
    try:
        cold_started = time.perf_counter()
        registry = WorkflowCapabilityRegistry()
        registry_init_ms = round((time.perf_counter() - cold_started) * 1000, 1)
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
            jev = JevDecisionClient(secrets_manager=secrets, http_client=client)
            warm_started = time.perf_counter()
            preselector = WorkflowAuthoringPreselector(jev_client=jev, registry=registry)
            catalogue_warmup_ms = round((time.perf_counter() - warm_started) * 1000, 1)
            author = WorkflowGeminiAuthor(secrets_manager=secrets, client=client, model=args.model)
            rows = []
            for case in cases:
                row = await run_case(case, preselector=preselector, author=author,
                                     compile_plan=compile_authoring_plan)
                rows.append(row)
                print(f"{case.id:23} graph={row['graph_valid']!s:5} intent={row['intent_match']!s:5} "
                      f"total={row['total_ms']}ms {row.get('error', '')}", flush=True)

        report = {"description": "Shared Jev selection + streaming Gemini compact semantic plan + V2 compiler",
                  "model": args.model,
                  "timing_scope": "per request includes Jev, complete Gemini generation, compiler validation and intent oracle; excludes persistence and execution",
                  "first_component_scope": "first complete compact step callback after generation began, not first byte",
                  "cost_scope": "reported Jev and Gemini estimates including billed reasoning where available; not provider invoices",
                  "registry_init_ms": registry_init_ms,
                  "catalogue_warmup_ms": catalogue_warmup_ms,
                  "cases": [asdict(case) for case in cases], "rows": rows}
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
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--output", default="/tmp/workflow-compact-authoring.json")
    parser.add_argument("--list-cases", action="store_true")
    args = parser.parse_args()
    if args.list_cases:
        for case in CASES:
            print(case.id)
        return 0
    try:
        return asyncio.run(_main(args))
    except Exception as exc:
        print(f"Benchmark setup failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
