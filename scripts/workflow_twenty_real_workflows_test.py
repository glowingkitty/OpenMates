#!/usr/bin/env python3
"""Run twenty real scheduled Workflows through the OpenMates CLI.

Creates near-future one-time workflows against the real dev API, enables them,
polls for accepted runs, inspects retained run details, and deletes temporary
artifacts. The default matrix uses low-risk enabled capabilities; paid generation
coverage remains bounded by the separate step-test script.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from workflow_real_test_helpers import dump_yaml_value, resolve_cli_path, run_cli, run_cli_json, step_id_for


LOW_RISK_WORKFLOWS: list[tuple[str, str]] = [
    ("math.calculate", "Compute a daily checksum"),
    ("web.search", "Search current OpenMates mentions"),
    ("web.read", "Read OpenMates homepage"),
    ("news.search", "Search OpenMates news"),
    ("weather.forecast", "Check Berlin forecast"),
    ("weather.rain_radar", "Check Berlin rain radar"),
    ("events.search", "Find Berlin AI events"),
    ("videos.search", "Search Svelte videos"),
    ("videos.get_transcript", "Fetch sample video transcript"),
    ("code.search_repos", "Search Svelte repositories"),
    ("code.get_docs", "Fetch Svelte docs"),
    ("design.search_icons", "Search calendar icons"),
    ("maps.search", "Find Berlin coffee"),
    ("nutrition.search_recipes", "Find lentil recipes"),
    ("shopping.search_products", "Find coffee beans"),
    ("social_media.search", "Search social posts"),
    ("social_media.get-posts", "Fetch selfhosted posts"),
    ("travel.search_connections", "Search Berlin Hamburg trains"),
    ("travel.search_stays", "Search Berlin stays"),
    ("home.search", "Search Berlin apartments"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run twenty real scheduled Workflows through the OpenMates CLI")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--cli-path")
    parser.add_argument("--home")
    parser.add_argument("--schedule-delay-seconds", type=int, default=90)
    parser.add_argument("--workflow-count", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    args = parser.parse_args()

    cli_path = resolve_cli_path(args.cli_path)
    capabilities = run_cli_json(cli_path, args.api_url, ["workflows", "capabilities"], home=args.home)
    by_id = {item["id"]: item for item in capabilities if item.get("enabled") is True}
    selected = [(capability_id, title) for capability_id, title in LOW_RISK_WORKFLOWS if capability_id in by_id]
    selected = selected[: args.workflow_count]
    if len(selected) != args.workflow_count:
        raise RuntimeError(f"Expected {args.workflow_count} enabled low-risk capabilities, found {len(selected)}: {selected}")

    created: list[dict[str, str]] = []
    report: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="openmates-workflow-twenty-") as tmp:
            for index, (capability_id, title) in enumerate(selected):
                run_at = datetime.now(UTC) + timedelta(seconds=args.schedule_delay_seconds + index * 2)
                workflow_file = Path(tmp) / f"workflow-{index}.yml"
                workflow_file.write_text(_workflow_yaml(capability_id, title, by_id[capability_id], run_at), encoding="utf-8")
                created_payload = run_cli_json(cli_path, args.api_url, ["workflows", "create", "--file", str(workflow_file)], home=args.home, timeout_seconds=120)
                workflow_id = created_payload.get("workflow", {}).get("id")
                if not workflow_id:
                    raise RuntimeError(f"Workflow create did not return an id: {created_payload}")
                run_cli_json(cli_path, args.api_url, ["workflows", "enable", workflow_id], home=args.home, timeout_seconds=60)
                created.append({"workflow_id": workflow_id, "capability_id": capability_id})

            deadline = time.time() + args.timeout_seconds
            pending = {item["workflow_id"]: item for item in created}
            while pending and time.time() < deadline:
                for workflow_id, item in list(pending.items()):
                    runs = run_cli_json(cli_path, args.api_url, ["workflows", "runs", workflow_id], home=args.home, timeout_seconds=60)
                    accepted = next((run for run in runs if run.get("trigger_type") == "schedule"), None)
                    if not accepted:
                        continue
                    run = run_cli_json(cli_path, args.api_url, ["workflows", "run-show", workflow_id, accepted["id"]], home=args.home, timeout_seconds=60)
                    if run.get("status") in {"completed", "waiting", "failed"}:
                        report.append({**item, "run_id": run.get("id"), "status": run.get("status"), "node_runs": run.get("node_runs", [])})
                        del pending[workflow_id]
                if pending:
                    time.sleep(5)
            if pending:
                raise RuntimeError(f"Timed out waiting for scheduled runs: {list(pending.values())}")
    finally:
        for item in created:
            run_cli(cli_path, args.api_url, ["workflows", "disable", item["workflow_id"]], home=args.home, timeout_seconds=60)
            run_cli(cli_path, args.api_url, ["workflows", "delete", item["workflow_id"], "--yes"], home=args.home, timeout_seconds=60)

    print(json.dumps({"workflow_count": len(report), "results": report}, indent=2, sort_keys=True))
    return 0


def _workflow_yaml(capability_id: str, title: str, capability: dict[str, Any], run_at: datetime) -> str:
    workflow = capability.get("metadata", {}).get("workflow", {})
    example = workflow.get("test_example_input") if isinstance(workflow, dict) else {}
    step_id = step_id_for(capability_id)
    return "\n".join(
        [
            f"title: {json.dumps('Real scheduled ' + title)}",
            "description: Real scheduled workflow expansion proof.",
            "start_when:",
            "  schedule:",
            "    type: once",
            f"    at: {json.dumps(run_at.isoformat())}",
            "steps:",
            f"  - id: {step_id}",
            f"    use_app_skill: {capability_id}",
            "    input:",
            dump_yaml_value(example or {}, 6),
        ]
    ) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
