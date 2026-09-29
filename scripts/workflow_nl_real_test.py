#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Run a disposable real-inference Workflow input pilot through OpenMates CLI.

Use an isolated OPENMATES_STATE_DIR logged into an E2E test account. Newly
created test workflows are removed in finally; no workflow is enabled or run.
Real AI inference belongs on dev, not in isolated product CI.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any


PROMPTS = [
    ("rain", "Every weekday at 7 Berlin time, check tomorrow's weather in Berlin. If rain is expected, send me a chat message reminding me to take an umbrella"),
    ("news", "Every day at 8 UTC, search for AI research news and send me a chat digest"),
    ("news_ai", "Every weekday at 8 UTC, search for AI research news, ask AI to summarize the search results in three bullets, and send the answer to chat"),
    ("reminder", "Every weekday at 9 UTC, send me a chat message reminding me to stretch"),
    ("unsupported", "Every weekday at 7 UTC, email me tomorrow's Berlin rain forecast"),
]


def cli_json(command: str, api_url: str, state_dir: Path, args: list[str]) -> tuple[Any, float]:
    env = dict(os.environ, OPENMATES_STATE_DIR=str(state_dir))
    started = time.perf_counter()
    completed = subprocess.run(
        [command, *args, "--api-url", api_url, "--json"],
        env=env, capture_output=True, text=True, timeout=90, check=False,
    )
    duration = round(time.perf_counter() - started, 3)
    if completed.returncode:
        raise RuntimeError(f"CLI {' '.join(args[:2])} failed: {completed.stderr[-700:] or completed.stdout[-700:]}")
    return json.loads(completed.stdout), duration


def run(api_url: str, state_dir: Path, command: str) -> dict[str, Any]:
    created: list[str] = []
    cases: list[dict[str, Any]] = []
    try:
        for label, prompt in PROMPTS:
            result, wall_seconds = cli_json(command, api_url, state_dir, ["workflows", "input", prompt])
            workflow = result.get("workflow") or {}
            metrics = result.get("authoring_metrics") or {}
            if label == "unsupported":
                assert result.get("status") == "needs_clarification", result
                assert not workflow
            else:
                assert result.get("status") == "executed", result
                assert workflow.get("enabled") is False, result
                assert workflow.get("description") and workflow.get("icon") != "help-circle", result
                assert workflow.get("graph", {}).get("version") == 2, result
                created.append(str(workflow["id"]))
                if label == "rain":
                    nodes = {node["id"]: node for node in workflow["graph"]["nodes"]}
                    assert nodes["weather"]["config"]["input"]["start_date"]["$date"] == "tomorrow"
                    assert nodes["trigger"]["config"]["schedule"]["timezone"] == "Europe/Berlin"
                if label == "news_ai":
                    nodes = {node["id"]: node for node in workflow["graph"]["nodes"]}
                    assert "{{ $nodes.news.output.results }}" in nodes["ask"]["config"]["input"]["prompt"]
            cases.append({
                "case": label,
                "status": result.get("status"),
                "workflow_id": workflow.get("id"),
                "node_count": len(workflow.get("graph", {}).get("nodes") or []),
                "wall_seconds": wall_seconds,
                "planning_seconds": metrics.get("total_seconds"),
                "jev_seconds": metrics.get("jev_seconds"),
                "jev_calls": metrics.get("jev_calls"),
                "gemini_calls": metrics.get("gemini_calls"),
                "bounded_fallback": metrics.get("bounded_fallback"),
                "input_tokens": metrics.get("input_tokens"),
                "output_tokens": metrics.get("output_tokens"),
                "estimated_cost_usd": metrics.get("estimated_cost_usd"),
            })
        rain_id = created[0]
        edited, edit_wall = cli_json(command, api_url, state_dir, [
            "workflows", "input", "Move this workflow to 8:30 Berlin time", "--workflow-id", rain_id,
        ])
        assert edited.get("status") == "executed", edited
        assert edited["workflow"]["enabled"] is False
        trigger = next(node for node in edited["workflow"]["graph"]["nodes"] if node["id"] == "trigger")
        assert trigger["config"]["schedule"]["time"] == "08:30"
        cases.append({"case": "edit", "status": edited["status"], "wall_seconds": edit_wall,
                      **{key: value for key, value in (edited.get("authoring_metrics") or {}).items()
                         if key in {"total_seconds", "jev_calls", "gemini_calls", "estimated_cost_usd", "bounded_fallback"}}})
        undone, undo_wall = cli_json(command, api_url, state_dir, ["workflows", "input-undo", edited["session_id"]])
        assert undone.get("status") == "undone", undone
        cases.append({"case": "undo", "status": undone["status"], "wall_seconds": undo_wall})
        valid = [case for case in cases if case["case"] in {"rain", "news", "news_ai", "reminder", "edit"}]
        return {"cases": cases,
                "mean_wall_seconds": round(statistics.mean(case["wall_seconds"] for case in valid), 3),
                "mean_estimated_cost_usd": round(statistics.mean(float(case.get("estimated_cost_usd") or 0) for case in valid), 8)}
    finally:
        for workflow_id in reversed(created):
            try:
                cli_json(command, api_url, state_dir, ["workflows", "delete", workflow_id, "--yes"])
            except Exception as exc:
                print(f"Cleanup required for disposable workflow {workflow_id}: {type(exc).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--cli", default="openmates")
    args = parser.parse_args()
    print(json.dumps(run(args.api_url, args.state_dir, args.cli), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
