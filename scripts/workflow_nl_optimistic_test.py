#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Measure queued preview and durable completion on dev with disposable workflows."""

import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

PROMPTS = [
    ("rain", "Every weekday at 7 Berlin time, check tomorrow's weather in Berlin. If rain is expected, send me a chat message reminding me to take an umbrella"),
    ("news", "Every day at 8 UTC, search for AI research news and send me a chat digest"),
    ("news_ai", "Every weekday at 8 UTC, search for AI research news, ask AI to summarize the search results in three bullets, and send the answer to chat"),
    ("reminder", "Every weekday at 9 UTC, send me a chat message reminding me to stretch"),
]


def call(cli: str, state_dir: Path, api_url: str, args: list[str]) -> tuple[dict, float]:
    started = time.perf_counter()
    completed = subprocess.run(
        [cli, *args, "--api-url", api_url, "--json"],
        env={**os.environ, "OPENMATES_STATE_DIR": str(state_dir)},
        capture_output=True, text=True, timeout=90, check=False,
    )
    duration = time.perf_counter() - started
    if completed.returncode:
        raise RuntimeError(f"CLI {' '.join(args[:2])} failed: {completed.stderr[-500:] or completed.stdout[-500:]}")
    return json.loads(completed.stdout), duration


def author(cli: str, state_dir: Path, api_url: str, label: str, prompt: str, extra: tuple[str, ...] = ()) -> tuple[dict, dict]:
    started = time.perf_counter()
    response, preview_wall = call(cli, state_dir, api_url, ["workflows", "input", prompt, *extra, "--optimistic"])
    if response["status"] != "queued":
        raise AssertionError(f"{label}: expected queued, got {response['status']}")
    preview = response.get("preview_workflow") or {}
    assert preview.get("graph", {}).get("version") == 2, f"{label}: missing V2 preview"
    assert preview.get("enabled") is False, f"{label}: unexpectedly active"
    session_id = response["session_id"]
    final = response
    for _ in range(20):
        final, _ = call(cli, state_dir, api_url, ["workflows", "input-show", session_id])
        if final["status"] != "queued":
            break
        time.sleep(0.2)
    completed_wall = time.perf_counter() - started
    assert final["status"] == "executed", f"{label}: {final['status']}"
    workflow = final.get("workflow") or {}
    assert workflow.get("id") == preview.get("id"), f"{label}: preview ID changed"
    metrics = response.get("authoring_metrics") or {}
    return workflow, {
        "case": label,
        "preview_wall_seconds": round(preview_wall, 3),
        "completed_observed_wall_seconds": round(completed_wall, 3),
        "planner_seconds": metrics.get("total_seconds"),
        "service_seconds": metrics.get("service_seconds"),
        "service_stages_seconds": metrics.get("service_stages_seconds"),
        "jev_seconds": metrics.get("jev_seconds"),
        "jev_calls": metrics.get("jev_calls"),
        "gemini_calls": metrics.get("gemini_calls"),
        "bounded_fallback": metrics.get("bounded_fallback"),
        "estimated_cost_usd": metrics.get("estimated_cost_usd"),
        "nodes": len(workflow.get("graph", {}).get("nodes") or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--cli", required=True)
    args = parser.parse_args()
    created: list[str] = []
    rows: list[dict] = []
    try:
        for label, prompt in PROMPTS:
            workflow, row = author(args.cli, args.state_dir, args.api_url, label, prompt)
            created.append(workflow["id"])
            rows.append(row)
            print(json.dumps(row), flush=True)
        _, row = author(args.cli, args.state_dir, args.api_url, "edit", "Move this workflow to 8:30 Berlin time", ("--workflow-id", created[0]))
        rows.append(row)
        print(json.dumps(row), flush=True)
        jev = [row for row in rows if not row["bounded_fallback"]]
        print(json.dumps({"summary": {
            "jev_path_count": len(jev),
            "mean_preview_wall_seconds": round(statistics.mean(row["preview_wall_seconds"] for row in jev), 3),
            "mean_completed_observed_wall_seconds": round(statistics.mean(row["completed_observed_wall_seconds"] for row in jev), 3),
            "mean_estimated_cost_usd": round(statistics.mean(row["estimated_cost_usd"] for row in jev), 8),
        }}), flush=True)
    finally:
        for workflow_id in reversed(created):
            try:
                call(args.cli, args.state_dir, args.api_url, ["workflows", "delete", workflow_id, "--yes"])
            except Exception as exc:
                print(f"cleanup_needed {workflow_id}: {type(exc).__name__}", flush=True)


if __name__ == "__main__":
    main()
