"""Paid opt-in comparison of direct and staged Jev workflow selection.

Run only after deployment inside the API container::

    python -m backend.scripts.compare_workflow_preselection --repeats 2 \
        --output /tmp/workflow-preselection-comparison.json

Both arms use the same seven fixed requests, Gemini author, strict compiler and
independent intent oracle. No workflow is saved or executed. Full synthetic
plans and graphs are written only to a private mode-0600 local report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from backend.core.api.app.services.workflow_authoring_compiler import compile_authoring_plan
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowAuthoringPreselector
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
from backend.core.api.app.services.workflow_gemini_authoring import (
    WorkflowAuthoringProviderError, WorkflowGeminiAuthor,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.scripts.benchmark_workflow_authoring import CASES
from backend.scripts.benchmark_workflow_compact_authoring import run_case
from backend.shared.providers.typesafe.client import JevDecisionClient


class RecordingSelector:
    """Expose stage counters discarded by the shared benchmark's flat sanitizer."""

    def __init__(self, selector: WorkflowAuthoringPreselector) -> None:
        self.selector = selector
        self.last_metrics: dict[str, Any] = {}

    async def select(self, *args: Any, **kwargs: Any) -> Any:
        self.last_metrics = {}
        # Match the planner's total selection deadline for both strategies.
        result = await asyncio.wait_for(self.selector.select(*args, **kwargs), timeout=3.2)
        self.last_metrics = result.metrics
        return result


class RecordingAuthor:
    """Capture bounded failure evidence without writing model payloads to stdout."""

    def __init__(self, author: WorkflowGeminiAuthor) -> None:
        self.author = author
        self.model = author.model
        self.last_failure: WorkflowAuthoringProviderError | None = None

    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        self.last_failure = None
        try:
            return await self.author.generate(*args, **kwargs)
        except WorkflowAuthoringProviderError as exc:
            self.last_failure = exc
            raise


def provider_failure_details(error: WorkflowAuthoringProviderError) -> dict[str, Any]:
    """Summarize accepted synthetic content without copying generated text."""
    prefixes = error.accepted_prefixes if isinstance(error.accepted_prefixes, list) else []
    counts = [{"header_accepted": isinstance(item.get("header"), dict),
               "nodes_accepted": len(item.get("nodes", [])) if isinstance(item.get("nodes"), list) else 0}
              for item in prefixes[:8] if isinstance(item, dict)]
    details: dict[str, Any] = {"accepted_prefix_counts": counts,
                               "accepted_node_count": sum(item["nodes_accepted"] for item in counts)}
    validation_error = getattr(error, "validation_error", None)
    if isinstance(validation_error, str):
        details["provider_validation_error"] = validation_error[:600]
    metrics = error.metrics if isinstance(error.metrics, dict) else {}
    # A numeric provider estimate is useful even when the plan failed. It is
    # reported as known metering, never as a complete invoice estimate.
    known_cost = metrics.get("estimated_cost_usd")
    details["provider_usage_reported"] = isinstance(known_cost, (int, float))
    if isinstance(known_cost, (int, float)):
        details["known_generation_cost_usd"] = known_cost
    return details


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep skill selection quality separate from graph transport and intent."""
    summary: dict[str, Any] = {}
    by_case = {case.id: case for case in CASES}
    for mode in ("direct", "staged"):
        arm = [row for row in rows if row["mode"] == mode]
        if not arm:
            continue
        required_hits = false_positives = required_total = 0
        for row in arm:
            required = set(by_case[row["case"]].required_capabilities)
            selected = set(row.get("selected_capabilities", []))
            # ai.ask is always provided as a composer builtin; it is counted
            # only when the case explicitly requires an AI summary.
            required_hits += len(required & selected)
            required_total += len(required)
            false_positives += len((selected - required) - {"ai.ask"})
        def numeric(key: str) -> list[float]:
            return [float(row[key]) for row in arm if isinstance(row.get(key), (int, float))]

        # The streaming callback's first complete component is an action node.
        # Gemini's first header is recorded separately in generation_metrics.
        first_action = numeric("first_complete_component_ms")
        selection_cost = [row.get("preselection_metrics", {}).get("estimated_cost_usd") for row in arm]
        generation_cost = [row.get("generation_metrics", {}).get("estimated_cost_usd") for row in arm]
        summary[mode] = {
            "runs": len(arm), "required_skill_recall": round(required_hits / required_total, 3),
            "extra_skill_selections": false_positives,
            "graph_valid": sum(bool(row.get("graph_valid")) for row in arm),
            "intent_match": sum(bool(row.get("intent_match")) for row in arm),
            "failure_stages": {stage: sum(row.get("failure_stage") == stage for row in arm)
                               for stage in sorted({row.get("failure_stage") for row in arm if row.get("failure_stage")})},
            "median_preselection_ms": round(statistics.median(numeric("preselection_ms")), 1) if numeric("preselection_ms") else None,
            "median_first_preview_after_generation_ms": round(statistics.median(first_action), 1) if first_action else None,
            "median_total_ms": round(statistics.median(numeric("total_ms")), 1) if numeric("total_ms") else None,
            "preselection_estimated_cost_usd": round(sum(value for value in selection_cost if isinstance(value, (int, float))), 6),
            "generation_estimated_cost_usd": round(sum(value for value in generation_cost if isinstance(value, (int, float))), 6),
            "estimated_cost_usd": round(sum(row.get("estimated_cost_usd") or 0 for row in arm), 6),
            "cost_estimate_complete": all(row.get("cost_estimate_complete") for row in arm),
        }
    return summary


async def _main(args: argparse.Namespace) -> int:
    cases = list(CASES) if args.cases == ["all"] else [case for case in CASES if case.id in args.cases]
    if not cases or (args.cases != ["all"] and len(cases) != len(args.cases)):
        raise ValueError("Unknown or duplicate benchmark case")
    logging.getLogger("backend.core.api.app.utils.secrets_manager").setLevel(logging.CRITICAL)
    secrets = SecretsManager()
    await secrets.initialize()
    try:
        registry = WorkflowCapabilityRegistry()
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
            jev = JevDecisionClient(secrets_manager=secrets, http_client=client,
                                    timeout_seconds=3.0, max_retries=0)
            author = RecordingAuthor(WorkflowGeminiAuthor(secrets_manager=secrets,
                                                           client=client, model=args.model))
            selectors = {mode: RecordingSelector(WorkflowAuthoringPreselector(
                jev_client=jev, registry=registry, mode=mode)) for mode in ("direct", "staged")}
            rows: list[dict[str, Any]] = []
            for repeat in range(args.repeats):
                # Alternate first arm to reduce warm-cache/order bias.
                modes = ("direct", "staged") if repeat % 2 == 0 else ("staged", "direct")
                for case in cases:
                    for mode in modes:
                        row = await run_case(case, preselector=selectors[mode], author=author,
                                             compile_plan=compile_authoring_plan)
                        row.update(mode=mode, repeat=repeat + 1)
                        row["first_preview_after_generation_ms"] = row.get("first_complete_component_ms")
                        metrics = selectors[mode].last_metrics
                        row["selection_stages"] = metrics.get("stages", [])
                        row["app_scores"] = metrics.get("app_scores", {})
                        row["selection_fallback"] = metrics.get("fallback")
                        if author.last_failure is not None:
                            row.update(provider_failure_details(author.last_failure))
                            row["cost_estimate_complete"] = False
                        rows.append(row)
                        print(f"{case.id:23} {mode:6} selection={row.get('selected_capabilities', [])} "
                              f"graph={row['graph_valid']} intent={row['intent_match']} "
                              f"total={row['total_ms']}ms {row.get('error', '')}", flush=True)
        report = {
            "description": "Direct versus app-first parallel per-app Jev selection; shared Gemini author and compiler",
            "model": args.model, "repeats": args.repeats,
            "scope": "Synthetic authoring only; no persistence or execution. Transport/schema failures are separate from intent failures.",
            "first_preview_scope": "Time from Gemini generation start to the first complete action-node callback. Gemini's earlier header is generation_metrics.first_component_ms; neither measure includes Jev preselection.",
            "cases": [asdict(case) for case in cases], "summary": summarize(rows), "rows": rows,
        }
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
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", nargs="+", default=["all"], help="Case IDs or all")
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--output", default="/tmp/workflow-preselection-comparison.json")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 3:
        parser.error("--repeats must be between 1 and 3")
    try:
        return asyncio.run(_main(args))
    except Exception as exc:
        print(f"Benchmark setup failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
